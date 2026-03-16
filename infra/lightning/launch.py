"""Launch logic — spin up Lightning AI Studios for runners + reviewer.

Uses ``lightning_sdk.Studio`` to create independent, long-running Studios.
Each runner gets its own GPU Studio; the reviewer runs on CPU.  Studios are
*not* orchestrated through a Pipeline — they are independent, matching the
architecture's "no rounds or barriers" principle.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from infra.lightning.config import session_specs, studio_kwargs

console = Console()

# Map config GPU names → lightning_sdk Machine enum members.
# The exact attribute names are isolated here so that a single dict update
# fixes any SDK naming drift.
MACHINE_MAP: dict[str, str] = {
    "H100": "H100",
    "H200": "H200",
    "A100": "A100",
    "A10G": "A10G",
    "L40S": "L40S",
    "L4": "L4",
    "T4": "T4",
    "CPU": "CPU",
}

_SETUP_SCRIPT = Path(__file__).parent / "studio_setup.sh"


def _proxy_env_prefix() -> str:
    """Build shell lines that inject the dumbpipe tunnel connector.

    If an active proxy is detected (via ``~/.art/proxy.json``), returns a
    shell snippet that:
      1. Sets ``ART_PROXY_TICKET`` so studio_setup.sh can start the connector.
      2. Sets ``ART_PROXY_PORT`` so the connector knows which local port to bind.

    Returns an empty string if no proxy is active.
    """
    from infra.lightning.proxy import get_active_proxy

    proxy = get_active_proxy()
    if not proxy:
        return ""

    ticket = proxy["ticket"]
    port = proxy.get("port", 4445)

    return (
        f'export ART_PROXY_TICKET="{ticket}"\n'
        f'export ART_PROXY_PORT="{port}"\n'
    )


def _tunnel_command_prefix(proxy_state: dict[str, Any] | None) -> str:
    """Build a shell snippet that starts the dumbpipe connector before the main command.

    Injected before the main command so the tunnel is established before
    Claude Code (or any other tool) tries to reach the API.

    Returns an empty string if no proxy is active.
    """
    if not proxy_state:
        return ""

    ticket = proxy_state["ticket"]
    port = proxy_state.get("port", 4445)
    auth_token = proxy_state.get("auth_token", "")

    lines = [
        "# --- dumbpipe tunnel to local LiteLLM proxy ---",
        f'dumbpipe connect-tcp --addr localhost:{port} "{ticket}" &',
        "DUMBPIPE_PID=$!",
        "sleep 2  # let tunnel establish",
        f'export ANTHROPIC_BASE_URL="http://localhost:{port}"',
    ]
    if auth_token:
        lines.append(f'export ANTHROPIC_AUTH_TOKEN="{auth_token}"')
    lines.append('trap "kill $DUMBPIPE_PID 2>/dev/null" EXIT')
    lines.append("# --- end dumbpipe tunnel ---")

    return "\n".join(lines) + "\n"


def _studio_names(cfg: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    """Build a list of dicts describing each Studio to launch."""
    studios: list[dict[str, Any]] = []
    rcfg = cfg["runners"]
    vcfg = cfg["reviewer"]

    if mode in ("all", "runners"):
        for i in range(rcfg["count"]):
            studios.append(
                {
                    "name": f"{rcfg['studio_prefix']}-{i}",
                    "gpu_type": rcfg["gpu_type"],
                    "command": rcfg["command"].format(runner_id=i),
                    "role": "runner",
                }
            )

    if mode in ("all", "reviewer") and vcfg.get("enabled", True):
        studios.append(
            {
                "name": vcfg["studio_name"],
                "gpu_type": vcfg["gpu_type"],
                "command": vcfg["command"],
                "role": "reviewer",
            }
        )

    return studios


def _config_panel(cfg: dict[str, Any], mode: str, dry_run: bool) -> Panel:
    """Build a rich Panel summarising the launch configuration."""
    rcfg = cfg["runners"]
    vcfg = cfg["reviewer"]
    lines = [
        f"[bold]Teamspace:[/bold]  {cfg['teamspace']}",
        f"[bold]Mode:[/bold]       {mode}",
        f"[bold]Runners:[/bold]    {rcfg['count']}  ×  {rcfg['gpu_type']}",
        f"[bold]Reviewer:[/bold]   {'enabled' if vcfg.get('enabled') else 'disabled'}  ({vcfg['gpu_type']})",
        f"[bold]Stagger:[/bold]    {cfg.get('launch', {}).get('stagger_seconds', 0)}s between launches",
    ]
    title = "[bold yellow]DRY RUN — preview only[/bold yellow]" if dry_run else "[bold green]Launching fleet[/bold green]"
    border_style = "yellow" if dry_run else "green"
    return Panel("\n".join(lines), title=title, border_style=border_style)


def _summary_table(results: list[dict[str, Any]]) -> Table:
    """Build a rich Table summarising launched Studios."""
    table = Table(title="Fleet Summary")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Machine", style="magenta")
    table.add_column("Role", style="blue")
    table.add_column("Status")
    table.add_column("Command", style="dim", max_width=50)

    for r in results:
        status = r.get("status", "unknown")
        if status == "running":
            styled = "[bold green]running[/bold green]"
        elif status == "starting":
            styled = "[bold yellow]starting[/bold yellow]"
        elif status == "dry-run":
            styled = "[dim]dry-run[/dim]"
        else:
            styled = f"[bold red]{status}[/bold red]"

        table.add_row(r["name"], r["gpu_type"], r["role"], styled, r["command"][:50])

    return table


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def launch_fleet(cfg: dict[str, Any], *, mode: str = "all", dry_run: bool = False) -> None:
    """Launch the autoresearch fleet as independent Lightning Studios.

    Parameters
    ----------
    cfg : dict
        Validated configuration (from ``config.load_config``).
    mode : str
        ``"all"`` | ``"runners"`` | ``"reviewer"``.
    dry_run : bool
        If *True*, display what would be launched without calling the SDK.
    """
    studios = _studio_names(cfg, mode)
    if not studios:
        console.print("[yellow]Nothing to launch for the selected mode.[/yellow]")
        return

    # ---- Config overview ----
    console.print()
    console.print(_config_panel(cfg, mode, dry_run))
    console.print()

    # ---- Dry run: show table and exit ----
    if dry_run:
        results = [{**s, "status": "dry-run"} for s in studios]
        console.print(_summary_table(results))

        # Show proxy tunnel status in dry-run output
        from infra.lightning.proxy import get_active_proxy

        proxy_state = get_active_proxy()
        if proxy_state:
            console.print(
                f"\n[cyan]Proxy active[/cyan] — Studios would tunnel to "
                f"localhost:{proxy_state.get('port', 4445)}\n"
                f"  Ticket: [dim]{proxy_state['ticket'][:60]}...[/dim]"
            )
        else:
            console.print("\n[dim]No proxy active — Studios will not get a tunnel.[/dim]")

        console.print()
        console.print(
            Panel(
                "No Studios were launched.  Remove [bold]--dry-run[/bold] to launch for real.",
                title="[yellow]Next steps[/yellow]",
                border_style="yellow",
            )
        )
        return

    # ---- Real launch ----
    stagger = cfg.get("launch", {}).get("stagger_seconds", 0)
    run_setup = cfg.get("launch", {}).get("run_setup", True)
    setup_script_raw = _SETUP_SCRIPT.read_text() if run_setup and _SETUP_SCRIPT.exists() else None

    # Inject env vars for studio_setup.sh.  Repo URLs come from env vars
    # (set by the caller) with config fallbacks.  These are NOT provider
    # concerns — the infra layer just passes them through.
    if setup_script_raw:
        team_repo = os.environ.get("ART_TEAM_REPO", cfg.get("repo_url", ""))
        team_branch = os.environ.get("ART_TEAM_BRANCH", cfg.get("repo_branch", "main"))
        autoresearch_repo = os.environ.get("ART_AUTORESEARCH_REPO", cfg.get("autoresearch_repo_url", ""))
        env_prefix = (
            f'export ART_TEAM_REPO="{team_repo}"\n'
            f'export ART_TEAM_BRANCH="{team_branch}"\n'
            f'export ART_AUTORESEARCH_REPO="{autoresearch_repo}"\n'
        )
        # Inject proxy tunnel env vars if a proxy is active
        env_prefix += _proxy_env_prefix()
        setup_script: str | None = env_prefix + setup_script_raw
    else:
        setup_script = None

    # Check for active proxy — tunnel connector is prepended to the main command
    from infra.lightning.proxy import get_active_proxy

    proxy_state = get_active_proxy()
    tunnel_prefix = _tunnel_command_prefix(proxy_state)
    if proxy_state:
        console.print(
            f"[cyan]Proxy detected[/cyan] — tunnel will connect Studios to "
            f"localhost:{proxy_state.get('port', 4445)}"
        )

    results: list[dict[str, Any]] = []

    try:
        from lightning_sdk import Machine, Studio  # type: ignore[import-untyped]
    except ImportError:
        console.print(
            "[bold red]Error:[/bold red] lightning-sdk is not installed.  "
            "Run [bold]uv sync[/bold] first."
        )
        raise SystemExit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for idx, spec in enumerate(studios):
            task_id = progress.add_task(f"Launching [cyan]{spec['name']}[/cyan]...")

            try:
                machine = getattr(Machine, MACHINE_MAP[spec["gpu_type"]])
                studio = Studio(**studio_kwargs(cfg, spec["name"]))
                studio.start(machine=machine)

                if setup_script:
                    progress.update(task_id, description=f"Setting up [cyan]{spec['name']}[/cyan]...")
                    studio.run(setup_script)

                progress.update(task_id, description=f"Running command on [cyan]{spec['name']}[/cyan]...")
                studio.run(tunnel_prefix + spec["command"])

                results.append({**spec, "status": "running"})
            except Exception as exc:
                results.append({**spec, "status": f"failed: {exc}"})
                console.print(f"[red]  ✗ {spec['name']}: {exc}[/red]")

            progress.remove_task(task_id)

            # Stagger between launches (skip after last)
            if stagger and idx < len(studios) - 1:
                time.sleep(stagger)

    # ---- Summary ----
    console.print()
    console.print(_summary_table(results))
    console.print()

    failed = [r for r in results if not r["status"].startswith("running")]
    if failed:
        console.print(f"[bold red]{len(failed)} Studio(s) failed to launch.[/bold red]")
    else:
        console.print(
            Panel(
                "All Studios launched successfully.\n\n"
                "  • Run [bold]art health[/bold] to check status.\n"
                "  • Run [bold]art teardown[/bold] to stop the fleet.",
                title="[green]Next steps[/green]",
                border_style="green",
            )
        )


# ---------------------------------------------------------------------------
# Session-based launch (--file path)
# ---------------------------------------------------------------------------


def _session_config_panel(cfg: dict[str, Any], dry_run: bool) -> Panel:
    """Build a rich Panel summarising a session-file launch configuration."""
    groups = cfg.get("sessions", [])
    lines = [
        f"[bold]Teamspace:[/bold]  {cfg.get('teamspace', '(unset)')}",
        f"[bold]Groups:[/bold]     {len(groups)}",
    ]
    for g in groups:
        lines.append(f"  • [cyan]{g['name']}[/cyan]  ×{g['count']}  ({g['gpu_type']})")
    lines.append(
        f"[bold]Stagger:[/bold]    {cfg.get('launch', {}).get('stagger_seconds', 0)}s between launches"
    )
    title = (
        "[bold yellow]DRY RUN — preview only[/bold yellow]"
        if dry_run
        else "[bold green]Launching sessions[/bold green]"
    )
    border_style = "yellow" if dry_run else "green"
    return Panel("\n".join(lines), title=title, border_style=border_style)


def _session_summary_table(results: list[dict[str, Any]]) -> Table:
    """Build a rich Table summarising launched sessions."""
    table = Table(title="Session Summary")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Machine", style="magenta")
    table.add_column("Group", style="blue")
    table.add_column("Status")
    table.add_column("Command", style="dim", max_width=50)

    for r in results:
        status = r.get("status", "unknown")
        if status == "running":
            styled = "[bold green]running[/bold green]"
        elif status == "starting":
            styled = "[bold yellow]starting[/bold yellow]"
        elif status == "dry-run":
            styled = "[dim]dry-run[/dim]"
        else:
            styled = f"[bold red]{status}[/bold red]"

        table.add_row(r["name"], r["gpu_type"], r["group"], styled, r["command"][:50])

    return table


def launch_sessions(cfg: dict[str, Any], *, dry_run: bool = False) -> None:
    """Launch sessions defined in a session-file config.

    Parameters
    ----------
    cfg : dict
        Validated configuration (from :func:`config.load_session_config`).
        Must contain a ``sessions`` list.
    dry_run : bool
        If *True*, display what would be launched without calling the SDK.
    """
    specs = session_specs(cfg)
    if not specs:
        console.print("[yellow]No sessions to launch.[/yellow]")
        return

    # ---- Config overview ----
    console.print()
    console.print(_session_config_panel(cfg, dry_run))
    console.print()

    # ---- Dry run: show table and exit ----
    if dry_run:
        results = [{**s, "status": "dry-run"} for s in specs]
        console.print(_session_summary_table(results))

        # Show proxy tunnel status in dry-run output
        from infra.lightning.proxy import get_active_proxy

        proxy_state = get_active_proxy()
        if proxy_state:
            console.print(
                f"\n[cyan]Proxy active[/cyan] — Studios would tunnel to "
                f"localhost:{proxy_state.get('port', 4445)}\n"
                f"  Ticket: [dim]{proxy_state['ticket'][:60]}...[/dim]"
            )
        else:
            console.print("\n[dim]No proxy active — Studios will not get a tunnel.[/dim]")

        console.print()
        console.print(
            Panel(
                "No Studios were launched.  Remove [bold]--dry-run[/bold] to launch for real.",
                title="[yellow]Next steps[/yellow]",
                border_style="yellow",
            )
        )
        return

    # ---- Real launch ----
    stagger = cfg.get("launch", {}).get("stagger_seconds", 0)
    run_setup = cfg.get("launch", {}).get("run_setup", True)
    setup_script_raw = _SETUP_SCRIPT.read_text() if run_setup and _SETUP_SCRIPT.exists() else None

    # Inject env vars for studio_setup.sh
    if setup_script_raw:
        team_repo = os.environ.get("ART_TEAM_REPO", cfg.get("repo_url", ""))
        team_branch = os.environ.get("ART_TEAM_BRANCH", cfg.get("repo_branch", "main"))
        autoresearch_repo = os.environ.get("ART_AUTORESEARCH_REPO", cfg.get("autoresearch_repo_url", ""))
        env_prefix = (
            f'export ART_TEAM_REPO="{team_repo}"\n'
            f'export ART_TEAM_BRANCH="{team_branch}"\n'
            f'export ART_AUTORESEARCH_REPO="{autoresearch_repo}"\n'
        )
        # Inject proxy tunnel env vars if a proxy is active
        env_prefix += _proxy_env_prefix()
        setup_script: str | None = env_prefix + setup_script_raw
    else:
        setup_script = None

    # Check for active proxy — tunnel connector is prepended to the main command
    from infra.lightning.proxy import get_active_proxy

    proxy_state = get_active_proxy()
    tunnel_prefix = _tunnel_command_prefix(proxy_state)
    if proxy_state:
        console.print(
            f"[cyan]Proxy detected[/cyan] — tunnel will connect Studios to "
            f"localhost:{proxy_state.get('port', 4445)}"
        )

    results: list[dict[str, Any]] = []

    try:
        from lightning_sdk import Machine, Studio  # type: ignore[import-untyped]
    except ImportError:
        console.print(
            "[bold red]Error:[/bold red] lightning-sdk is not installed.  "
            "Run [bold]uv sync[/bold] first."
        )
        raise SystemExit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for idx, spec in enumerate(specs):
            task_id = progress.add_task(f"Launching [cyan]{spec['name']}[/cyan]...")

            try:
                machine = getattr(Machine, MACHINE_MAP[spec["gpu_type"]])
                studio = Studio(**studio_kwargs(cfg, spec["name"]))
                studio.start(machine=machine)

                if setup_script:
                    progress.update(task_id, description=f"Setting up [cyan]{spec['name']}[/cyan]...")
                    studio.run(setup_script)

                progress.update(task_id, description=f"Running command on [cyan]{spec['name']}[/cyan]...")
                studio.run(tunnel_prefix + spec["command"])

                results.append({**spec, "status": "running"})
            except Exception as exc:
                results.append({**spec, "status": f"failed: {exc}"})
                console.print(f"[red]  ✗ {spec['name']}: {exc}[/red]")

            progress.remove_task(task_id)

            # Stagger between launches (skip after last)
            if stagger and idx < len(specs) - 1:
                time.sleep(stagger)

    # ---- Summary ----
    console.print()
    console.print(_session_summary_table(results))
    console.print()

    failed = [r for r in results if not r["status"].startswith("running")]
    if failed:
        console.print(f"[bold red]{len(failed)} session(s) failed to launch.[/bold red]")
    else:
        console.print(
            Panel(
                "All sessions launched successfully.\n\n"
                "  • Run [bold]art health[/bold] to check status.\n"
                "  • Run [bold]art teardown[/bold] to stop sessions.",
                title="[green]Next steps[/green]",
                border_style="green",
            )
        )
