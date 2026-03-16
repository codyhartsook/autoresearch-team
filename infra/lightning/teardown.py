"""Graceful shutdown — stop or delete Lightning AI Studios.

Supports selective teardown (runners only, reviewer only, or all) for legacy
configs, and full session-file teardown via ``--file``.  An optional
``--delete`` flag removes Studios entirely rather than just stopping them.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm
from rich.table import Table

from infra.lightning.config import session_specs, studio_kwargs

console = Console()


def _studio_names(cfg: dict[str, Any], mode: str) -> list[dict[str, str]]:
    """Return a list of ``{"name": ..., "role": ...}`` dicts to tear down."""
    studios: list[dict[str, str]] = []

    # Session-file path — cfg has a "sessions" key
    if "sessions" in cfg:
        for spec in session_specs(cfg):
            studios.append({"name": spec["name"], "role": spec["group"]})
        return studios

    # Legacy path — runners + reviewer
    rcfg = cfg["runners"]
    vcfg = cfg["reviewer"]

    if mode in ("all", "runners"):
        for i in range(rcfg["count"]):
            studios.append({"name": f"{rcfg['studio_prefix']}-{i}", "role": "runner"})

    if mode in ("all", "reviewer") and vcfg.get("enabled", True):
        studios.append({"name": vcfg["studio_name"], "role": "reviewer"})

    return studios


def _result_table(results: list[dict[str, str]]) -> Table:
    """Build a summary table of teardown actions."""
    table = Table(title="Teardown Summary")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Role", style="blue")
    table.add_column("Action Taken")
    table.add_column("Result")

    for r in results:
        action = r.get("action", "unknown")
        status = r.get("status", "unknown")
        if status == "ok":
            styled = f"[green]{action}[/green]"
        else:
            styled = f"[red]{status}[/red]"
        table.add_row(r["name"], r["role"], action, styled)

    return table


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def teardown_fleet(cfg: dict[str, Any], *, mode: str = "all", delete: bool = False) -> None:
    """Stop or delete fleet Studios.

    Parameters
    ----------
    cfg : dict
        Validated configuration.
    mode : str
        ``"all"`` | ``"runners"`` | ``"reviewer"``.
    delete : bool
        If *True*, remove Studios entirely (destructive).
    """
    studios = _studio_names(cfg, mode)
    if not studios:
        console.print("[yellow]Nothing to tear down for the selected mode.[/yellow]")
        return

    action_verb = "delete" if delete else "stop"
    console.print()
    console.print(
        Panel(
            f"[bold]Teamspace:[/bold]  {cfg['teamspace']}\n"
            f"[bold]Mode:[/bold]       {mode}\n"
            f"[bold]Action:[/bold]     {action_verb}\n"
            f"[bold]Studios:[/bold]    {len(studios)}",
            title=f"[bold red]Teardown — {action_verb}[/bold red]",
            border_style="red",
        )
    )

    # Destructive action guard
    if delete:
        if not Confirm.ask(
            f"\n[bold red]This will permanently delete {len(studios)} Studio(s). Continue?[/bold red]"
        ):
            console.print("[dim]Aborted.[/dim]")
            return

    try:
        from lightning_sdk import Studio  # type: ignore[import-untyped]
    except ImportError:
        console.print(
            "[bold red]Error:[/bold red] lightning-sdk is not installed.  "
            "Run [bold]uv sync[/bold] first."
        )
        raise SystemExit(1)

    results: list[dict[str, str]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for spec in studios:
            tid = progress.add_task(
                f"{'Deleting' if delete else 'Stopping'} [cyan]{spec['name']}[/cyan]..."
            )

            try:
                studio = Studio(**studio_kwargs(cfg, spec["name"]))
                if delete:
                    studio.delete()
                    results.append({**spec, "action": "deleted", "status": "ok"})
                else:
                    studio.stop()
                    results.append({**spec, "action": "stopped", "status": "ok"})
            except Exception as exc:
                results.append({**spec, "action": action_verb, "status": f"failed: {exc}"})

            progress.remove_task(tid)

    console.print()
    console.print(_result_table(results))
    console.print()

    failed = [r for r in results if r["status"] != "ok"]
    if failed:
        console.print(f"[bold red]{len(failed)} Studio(s) failed to {action_verb}.[/bold red]")
    else:
        console.print(f"[green]All {len(results)} Studio(s) {action_verb}d successfully.[/green]")
