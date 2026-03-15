"""Health-check monitor — show fleet status as a rich table.

Supports one-shot and ``--watch`` (auto-refreshing via ``rich.live.Live``).
Queries each Studio's status via the Lightning SDK and displays colour-coded
badges: running / stale / stopped.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from infra.lightning.config import session_specs, studio_kwargs

console = Console()

# A Studio that hasn't had activity in this many seconds is "stale".
_STALE_THRESHOLD_SECONDS = 30 * 60  # 30 minutes


def _studio_specs(cfg: dict[str, Any]) -> list[dict[str, str]]:
    """Return all Studios described by the config."""
    specs: list[dict[str, str]] = []

    # Session-file path — cfg has a "sessions" key
    if "sessions" in cfg:
        for s in session_specs(cfg):
            specs.append(
                {
                    "name": s["name"],
                    "gpu_type": s["gpu_type"],
                    "role": s["group"],
                }
            )
        return specs

    # Legacy path — runners + reviewer
    rcfg = cfg["runners"]
    vcfg = cfg["reviewer"]

    for i in range(rcfg["count"]):
        specs.append(
            {
                "name": f"{rcfg['studio_prefix']}-{i}",
                "gpu_type": rcfg["gpu_type"],
                "role": "runner",
            }
        )

    if vcfg.get("enabled", True):
        specs.append(
            {
                "name": vcfg["studio_name"],
                "gpu_type": vcfg["gpu_type"],
                "role": "reviewer",
            }
        )

    return specs


def _status_badge(status: str) -> str:
    """Return a rich-markup badge for a Studio status string."""
    s = status.lower()
    if s in ("running", "active"):
        return "[bold green]running[/bold green]"
    if s in ("pending", "starting"):
        return "[bold yellow]starting[/bold yellow]"
    if s in ("stopped", "shutting_down", "not_found"):
        return "[bold red]stopped[/bold red]"
    if s == "stale":
        return "[bold yellow]stale[/bold yellow]"
    return f"[dim]{status}[/dim]"


def _query_studio(cfg: dict[str, Any], name: str) -> dict[str, str]:
    """Query a single Studio's status via the Lightning SDK.

    Returns a dict with keys: status, last_activity, uptime.
    Catches all exceptions so one bad Studio doesn't crash the table.
    """
    try:
        from lightning_sdk import Studio  # type: ignore[import-untyped]

        studio = Studio(**studio_kwargs(cfg, name))
        status = str(getattr(studio, "status", "unknown"))
        # Best-effort: the SDK may not expose these directly
        last_activity = str(getattr(studio, "last_activity", "-"))
        uptime = str(getattr(studio, "uptime", "-"))
        return {"status": status, "last_activity": last_activity, "uptime": uptime}
    except ImportError:
        return {"status": "sdk-missing", "last_activity": "-", "uptime": "-"}
    except Exception as exc:
        return {"status": f"error: {exc}", "last_activity": "-", "uptime": "-"}


def _build_table(cfg: dict[str, Any]) -> Table:
    """Query all Studios and return a rich Table."""
    specs = _studio_specs(cfg)
    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    table = Table(
        title=f"Fleet Health  •  [dim]{cfg['teamspace']}[/dim]  •  [dim]{now_str}[/dim]",
    )
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Machine", style="magenta")
    table.add_column("Role", style="blue")
    table.add_column("Status")
    table.add_column("Last Activity", style="dim")
    table.add_column("Uptime", style="dim")

    for spec in specs:
        info = _query_studio(cfg, spec["name"])
        table.add_row(
            spec["name"],
            spec["gpu_type"],
            spec["role"],
            _status_badge(info["status"]),
            info["last_activity"],
            info["uptime"],
        )

    return table


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_health(cfg: dict[str, Any], *, watch: bool = False, interval: int = 30) -> None:
    """Display fleet health.

    Parameters
    ----------
    cfg : dict
        Validated configuration.
    watch : bool
        If *True*, continuously refresh using ``rich.live.Live``.
    interval : int
        Seconds between refreshes in watch mode.
    """
    console.print()

    if watch:
        console.print(
            Panel(
                f"Refreshing every [bold]{interval}[/bold]s.  Press [bold]Ctrl+C[/bold] to stop.",
                title="[bold cyan]Watch mode[/bold cyan]",
                border_style="cyan",
            )
        )
        try:
            with Live(
                _build_table(cfg),
                console=console,
                refresh_per_second=0.5,
            ) as live:
                while True:
                    time.sleep(interval)
                    live.update(_build_table(cfg))
        except KeyboardInterrupt:
            console.print("\n[dim]Watch stopped.[/dim]")
    else:
        console.print(_build_table(cfg))
        console.print()
        console.print(
            "[dim]Tip: run [bold]art health --watch[/bold] for continuous monitoring.[/dim]"
        )
