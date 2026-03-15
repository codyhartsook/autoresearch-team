"""Telemetry — fetch and parse JSONL metrics from running Lightning Studios.

Lightweight infra-level telemetry: each Studio writes append-only JSONL events
to a well-known path.  This module pulls those files via the Lightning SDK and
parses them for display.

This is intentionally minimal — it will be replaced by the protocol layer's
experiment tracking.  The infra layer only knows "there's a JSONL file at a
known path" and "here's how to download it from a Studio".
"""

from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from infra.lightning.config import session_specs, studio_kwargs

console = Console()

# Well-known path inside every Studio where the run script writes events.
REMOTE_METRICS_PATH = "/teamspace/studios/this_studio/metrics.jsonl"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_events(raw: str) -> list[dict[str, Any]]:
    """Parse newline-delimited JSON into a list of dicts.

    Silently skips blank lines and malformed JSON lines.
    """
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


# ---------------------------------------------------------------------------
# Fetching from Studios
# ---------------------------------------------------------------------------


def fetch_events(
    cfg: dict[str, Any],
    studio_name: str,
    remote_path: str = REMOTE_METRICS_PATH,
) -> list[dict[str, Any]]:
    """Download metrics.jsonl from a Studio and return parsed events.

    Tries ``studio.download_file()`` first.  Falls back to
    ``studio.run("cat ...")`` if the download method fails (e.g. the SDK
    version doesn't support it cleanly for the file type).

    Returns an empty list on any error — Studio not running, file doesn't
    exist yet, SDK not installed, etc.
    """
    try:
        from lightning_sdk import Studio  # type: ignore[import-untyped]
    except ImportError:
        return []

    try:
        studio = Studio(**studio_kwargs(cfg, studio_name))
    except Exception:
        return []

    # Strategy 1: download_file to a temp path
    try:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name
        studio.download_file(remote_path, tmp_path)
        raw = Path(tmp_path).read_text()
        Path(tmp_path).unlink(missing_ok=True)
        return parse_events(raw)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)

    # Strategy 2: cat via run()
    try:
        raw = studio.run(f"cat {remote_path} 2>/dev/null || true")
        return parse_events(raw)
    except Exception:
        return []


def fetch_latest(
    cfg: dict[str, Any],
    studio_name: str,
    remote_path: str = REMOTE_METRICS_PATH,
) -> dict[str, Any] | None:
    """Return the most recent event from a Studio, or ``None``."""
    events = fetch_events(cfg, studio_name, remote_path)
    return events[-1] if events else None


# ---------------------------------------------------------------------------
# Multi-studio fetching
# ---------------------------------------------------------------------------


def _studio_names_from_config(cfg: dict[str, Any]) -> list[str]:
    """Extract Studio names from either legacy or session-file config.

    Legacy config has ``runners`` + ``reviewer`` sections.
    Session-file config has a ``sessions`` list.
    """
    names: list[str] = []

    # Session-file path
    if "sessions" in cfg:
        for spec in session_specs(cfg):
            names.append(spec["name"])
        return names

    # Legacy path
    rcfg = cfg.get("runners", {})
    vcfg = cfg.get("reviewer", {})

    prefix = rcfg.get("studio_prefix", "runner")
    for i in range(rcfg.get("count", 0)):
        names.append(f"{prefix}-{i}")

    if vcfg.get("enabled", True):
        names.append(vcfg.get("studio_name", "reviewer"))

    return names


def fetch_all_studios(
    cfg: dict[str, Any],
    remote_path: str = REMOTE_METRICS_PATH,
    studio_filter: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch events from all Studios described by the config.

    Parameters
    ----------
    cfg : dict
        Validated config (legacy or session-file).
    remote_path : str
        Path to the JSONL file inside each Studio.
    studio_filter : str | None
        If provided, only fetch from this Studio name.

    Returns
    -------
    dict[str, list[dict]]
        Mapping of studio name → list of parsed events.
    """
    names = _studio_names_from_config(cfg)

    if studio_filter:
        names = [n for n in names if n == studio_filter]

    result: dict[str, list[dict[str, Any]]] = {}
    for name in names:
        result[name] = fetch_events(cfg, name, remote_path)

    return result


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def _status_style(status: str) -> str:
    """Return rich-styled status string."""
    s = status.lower()
    if s == "ok":
        return "[green]ok[/green]"
    if s == "started":
        return "[yellow]started[/yellow]"
    if s == "running":
        return "[cyan]running[/cyan]"
    if s == "failed":
        return "[bold red]failed[/bold red]"
    return f"[dim]{status}[/dim]"


def _build_logs_table(
    all_events: dict[str, list[dict[str, Any]]],
    tail_n: int = 10,
) -> Table:
    """Build a Rich Table showing the latest events from each Studio."""
    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    table = Table(
        title=f"Studio Telemetry  •  [dim]{now_str}[/dim]",
        show_lines=False,
    )
    table.add_column("Studio", style="cyan", no_wrap=True)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Phase", style="blue", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Step", style="magenta", no_wrap=True)
    table.add_column("Loss", no_wrap=True)
    table.add_column("val_bpb", style="bold", no_wrap=True)
    table.add_column("VRAM", style="dim", no_wrap=True)
    table.add_column("Info", style="dim", max_width=30, overflow="ellipsis")

    for studio_name, events in all_events.items():
        if not events:
            table.add_row(
                studio_name, "-", "-", "[dim]no events[/dim]",
                "-", "-", "-", "-", "-",
            )
            continue

        # Show the last tail_n events
        tail_events = events[-tail_n:]
        for event in tail_events:
            ts_raw = event.get("ts", "")
            # Format timestamp: show just time portion if it's a full ISO timestamp
            if "T" in ts_raw:
                ts_display = ts_raw.split("T")[1].replace("Z", "")
            else:
                ts_display = ts_raw

            phase = event.get("phase", "-")
            status = event.get("status", "-")
            step = event.get("step", "-")
            loss = event.get("loss", "-")
            val_bpb = event.get("val_bpb", "-")
            vram = event.get("peak_vram_mb", "-")

            # Build info string from interesting extra fields
            skip_keys = {"ts", "host", "phase", "status", "step", "loss", "val_bpb", "peak_vram_mb"}
            extras = {k: v for k, v in event.items() if k not in skip_keys and v}
            info = ", ".join(f"{k}={v}" for k, v in extras.items()) if extras else "-"

            table.add_row(
                studio_name,
                ts_display,
                phase,
                _status_style(status),
                str(step),
                str(loss),
                str(val_bpb),
                str(vram),
                info[:40],
            )

    return table


def show_logs(
    cfg: dict[str, Any],
    *,
    studio_filter: str | None = None,
    tail_n: int = 10,
    watch: bool = False,
    interval: int = 30,
) -> None:
    """Fetch and display telemetry events from Studios.

    Parameters
    ----------
    cfg : dict
        Validated config (legacy or session-file).
    studio_filter : str | None
        If provided, only show events from this Studio.
    tail_n : int
        Number of recent events to show per Studio.
    watch : bool
        If True, continuously refresh using Rich Live.
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
            all_events = fetch_all_studios(cfg, studio_filter=studio_filter)
            with Live(
                _build_logs_table(all_events, tail_n),
                console=console,
                refresh_per_second=0.5,
            ) as live:
                while True:
                    time.sleep(interval)
                    all_events = fetch_all_studios(cfg, studio_filter=studio_filter)
                    live.update(_build_logs_table(all_events, tail_n))
        except KeyboardInterrupt:
            console.print("\n[dim]Watch stopped.[/dim]")
    else:
        all_events = fetch_all_studios(cfg, studio_filter=studio_filter)
        console.print(_build_logs_table(all_events, tail_n))
        console.print()

        total = sum(len(evts) for evts in all_events.values())
        if total == 0:
            console.print(
                "[yellow]No telemetry events found.  Studios may not be running yet, "
                "or the run script hasn't started writing metrics.jsonl.[/yellow]"
            )
        else:
            console.print(
                f"[dim]Showing last {tail_n} events per Studio "
                f"({total} total events across {len(all_events)} Studio(s)).[/dim]"
            )
        console.print(
            "[dim]Tip: run [bold]art logs --watch[/bold] for continuous monitoring.[/dim]"
        )
