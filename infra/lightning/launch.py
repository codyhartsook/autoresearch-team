"""Launch logic — spin up Lightning AI Studios for runners + reviewer.

Uses ``lightning_sdk.Studio`` to create independent, long-running Studios.
Each runner gets its own GPU Studio; the reviewer runs on CPU.  Studios are
*not* orchestrated through a Pipeline — they are independent, matching the
architecture's "no rounds or barriers" principle.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from infra.lightning.config import studio_kwargs

console = Console()

# Map config GPU names → lightning_sdk Machine enum members.
# The exact attribute names are isolated here so that a single dict update
# fixes any SDK naming drift.
MACHINE_MAP: dict[str, str] = {
    "H100": "H100",
    "A100": "A100",
    "A10G": "A10G",
    "L4": "L4",
    "CPU": "CPU",
}

_SETUP_SCRIPT = Path(__file__).parent / "studio_setup.sh"


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

    # Inject config values as env vars so studio_setup.sh can read them
    if setup_script_raw:
        env_prefix = (
            f'export ART_TEAM_REPO="{cfg.get("repo_url", "")}"\n'
            f'export ART_TEAM_BRANCH="{cfg.get("repo_branch", "main")}"\n'
            f'export ART_AUTORESEARCH_REPO="{cfg.get("autoresearch_repo_url", "")}"\n'
        )
        setup_script: str | None = env_prefix + setup_script_raw
    else:
        setup_script = None
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
                studio.run(spec["command"])

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
                "  • Run [bold]uv run art health[/bold] to check status.\n"
                "  • Run [bold]uv run art teardown[/bold] to stop the fleet.",
                title="[green]Next steps[/green]",
                border_style="green",
            )
        )
