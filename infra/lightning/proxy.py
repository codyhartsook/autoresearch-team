"""Proxy management — dumbpipe tunnel for LiteLLM proxy access from Studios.

Manages a local ``dumbpipe listen-tcp`` listener that tunnels the user's
LiteLLM proxy (e.g. ``localhost:4445``) into remote Lightning Studios via
iroh-based P2P encrypted connections.

State is persisted to ``~/.art/proxy.json`` so that ``art launch`` can
automatically inject the tunnel connector into Studio setup.

Usage::

    art proxy start                        # start listener (defaults to port 4445)
    art proxy start --port 4445            # explicit port
    art proxy start --auth-token TOKEN     # with explicit proxy auth token
    art proxy stop                         # stop the listener
    art proxy status                       # show current state

The auth token (``ANTHROPIC_AUTH_TOKEN``) is forwarded to Studios so Claude
Code can authenticate against the LiteLLM proxy.  It can be passed via
``--auth-token`` or read from the ``ANTHROPIC_AUTH_TOKEN`` env var.
"""

from __future__ import annotations

import json
import os
import secrets
import select
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# State file — user-level, not repo-level
_STATE_DIR = Path.home() / ".art"
_STATE_FILE = _STATE_DIR / "proxy.json"

# Where to persist the iroh secret for stable tickets
_SECRET_FILE = _STATE_DIR / "dumbpipe-secret"

DEFAULT_PORT = 4445

# dumbpipe version pinned for reproducibility
DUMBPIPE_VERSION = "0.34.0"


# ---------------------------------------------------------------------------
# State file I/O
# ---------------------------------------------------------------------------


def _read_state() -> dict[str, Any] | None:
    """Read proxy state from ``~/.art/proxy.json``, or None if absent."""
    if not _STATE_FILE.exists():
        return None
    try:
        return json.loads(_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_state(state: dict[str, Any]) -> None:
    """Write proxy state to ``~/.art/proxy.json``."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def _remove_state() -> None:
    """Remove the proxy state file."""
    if _STATE_FILE.exists():
        _STATE_FILE.unlink()


# ---------------------------------------------------------------------------
# PID helpers
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ---------------------------------------------------------------------------
# Secret / ticket management
# ---------------------------------------------------------------------------


def _load_or_generate_secret() -> str:
    """Load an existing IROH_SECRET or generate a new one.

    The secret is stored at ``~/.art/dumbpipe-secret`` so tickets remain
    stable across restarts.  dumbpipe accepts any string as IROH_SECRET —
    we generate 32 random hex bytes.
    """
    if _SECRET_FILE.exists():
        secret = _SECRET_FILE.read_text().strip()
        if secret:
            return secret

    # Generate a random secret (dumbpipe has no generate-secret subcommand)
    secret = secrets.token_hex(32)
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _SECRET_FILE.write_text(secret + "\n")
    _SECRET_FILE.chmod(0o600)
    return secret


def _generate_ticket(secret: str) -> str:
    """Pre-compute the dumbpipe ticket without starting a listener.

    Uses ``dumbpipe generate-ticket`` with the given ``IROH_SECRET``.
    The ticket is endpoint-based (not host-specific) — it identifies the
    listener by its iroh node ID derived from the secret.
    """
    _ensure_dumbpipe()
    env = {**os.environ, "IROH_SECRET": secret}
    result = subprocess.run(
        ["dumbpipe", "generate-ticket"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to generate ticket: {result.stderr.strip()}")

    return result.stdout.strip()


def _ensure_dumbpipe() -> None:
    """Verify that ``dumbpipe`` is on PATH."""
    if not shutil.which("dumbpipe"):
        console.print(
            "[bold red]Error:[/bold red] dumbpipe is not installed.\n"
            "Install it from [link=https://github.com/n0-computer/dumbpipe/releases]"
            "github.com/n0-computer/dumbpipe/releases[/link]\n\n"
            "  macOS:  [bold]brew install n0-computer/iroh/dumbpipe[/bold]\n"
            "  Linux:  download the prebuilt binary from GitHub releases"
        )
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def proxy_start(
    port: int = DEFAULT_PORT,
    use_secret: bool = True,
    auth_token: str | None = None,
) -> None:
    """Start a ``dumbpipe listen-tcp`` listener in the background.

    Parameters
    ----------
    port : int
        Local port to tunnel (where LiteLLM is running).
    use_secret : bool
        If True, use a stable IROH_SECRET for reusable tickets.
    auth_token : str | None
        Proxy auth token for Studios to authenticate against LiteLLM.
        Falls back to the ``ANTHROPIC_AUTH_TOKEN`` env var if not provided.
    """
    # Check for existing listener
    state = _read_state()
    if state and _pid_alive(state.get("pid", 0)):
        console.print(
            f"[yellow]Proxy already running[/yellow] (PID {state['pid']}, "
            f"port {state['port']})\n"
            f"Ticket: [dim]{state['ticket']}[/dim]\n\n"
            "Run [bold]art proxy stop[/bold] first to restart."
        )
        return

    # Resolve auth token: explicit arg > env var
    auth_token = auth_token or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")

    _ensure_dumbpipe()

    # Get or generate secret for stable tickets
    secret = _load_or_generate_secret() if use_secret else ""

    # Pre-compute the ticket
    if secret:
        ticket = _generate_ticket(secret)
    else:
        ticket = ""  # will be captured from stderr

    # Start the listener as a background process
    env = {**os.environ}
    if secret:
        env["IROH_SECRET"] = secret

    proc = subprocess.Popen(
        ["dumbpipe", "listen-tcp", "--host", f"localhost:{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,  # detach from terminal
    )

    # Wait for stderr output confirming listener is ready
    console.print(f"[dim]Starting dumbpipe listener on localhost:{port}...[/dim]")

    # Give it a moment to start and emit the ticket
    ready = False
    captured_ticket = ""
    start_time = time.time()
    timeout = 10

    while time.time() - start_time < timeout:
        if proc.poll() is not None:
            # Process died
            stderr_out = proc.stderr.read().decode() if proc.stderr else ""
            console.print(f"[bold red]dumbpipe exited unexpectedly:[/bold red]\n{stderr_out}")
            raise SystemExit(1)

        # Try to read stderr non-blocking
        if proc.stderr and select.select([proc.stderr], [], [], 0.5)[0]:
            line = proc.stderr.readline().decode().strip()
            if line:
                # dumbpipe prints ticket info to stderr
                if not ticket and ("blob" in line.lower() or len(line) > 50):
                    captured_ticket = line
                if "listening" in line.lower() or "ready" in line.lower():
                    ready = True
                    break
                # If we have a pre-computed ticket, just wait for any output
                if ticket:
                    ready = True
                    break

        time.sleep(0.2)

    # If we got any stderr output, consider it ready
    if not ready and proc.poll() is None:
        # Process is still running — assume it's ready after timeout
        ready = True

    if not ticket:
        ticket = captured_ticket

    if not ticket:
        console.print(
            "[bold yellow]Warning:[/bold yellow] Could not capture ticket from dumbpipe.\n"
            "The listener appears to be running but the ticket is unknown.\n"
            "Consider using --secret for stable, pre-computed tickets."
        )

    # Save state
    state_data = {
        "pid": proc.pid,
        "ticket": ticket,
        "port": port,
        "secret": secret,
        "auth_token": auth_token,
    }
    _write_state(state_data)

    # Display results
    auth_display = "[dim]set[/dim]" if auth_token else "[dim]not set[/dim]"
    console.print()
    console.print(
        Panel(
            f"[bold green]Proxy listener started[/bold green]\n\n"
            f"  PID:        {proc.pid}\n"
            f"  Port:       {port}\n"
            f"  Auth token: {auth_display}\n"
            f"  Ticket:     [dim]{ticket[:80]}{'...' if len(ticket) > 80 else ''}[/dim]\n\n"
            "Studios launched with [bold]art launch[/bold] will automatically\n"
            "connect to this proxy tunnel.",
            title="[green]dumbpipe proxy[/green]",
            border_style="green",
        )
    )


def proxy_stop() -> None:
    """Stop the running dumbpipe listener."""
    state = _read_state()
    if not state:
        console.print("[yellow]No proxy is running[/yellow] (no state file found).")
        return

    pid = state.get("pid", 0)
    if pid and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            # Wait briefly for graceful shutdown
            for _ in range(10):
                if not _pid_alive(pid):
                    break
                time.sleep(0.2)
            else:
                # Force kill if still alive
                os.kill(pid, signal.SIGKILL)
            console.print(f"[green]Stopped proxy listener[/green] (PID {pid})")
        except (OSError, ProcessLookupError):
            console.print(f"[yellow]Process {pid} already gone.[/yellow]")
    else:
        console.print(f"[yellow]Process {pid} is not running.[/yellow]")

    _remove_state()
    console.print("[dim]State file removed.[/dim]")


def proxy_status() -> None:
    """Display current proxy state."""
    state = _read_state()
    if not state:
        console.print(
            Panel(
                "No proxy is currently running.\n\n"
                "Start one with [bold]art proxy start[/bold]",
                title="[yellow]Proxy status[/yellow]",
                border_style="yellow",
            )
        )
        return

    pid = state.get("pid", 0)
    alive = _pid_alive(pid) if pid else False

    table = Table(title="Proxy Status")
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value")

    status_str = "[bold green]running[/bold green]" if alive else "[bold red]stopped[/bold red]"
    table.add_row("Status", status_str)
    table.add_row("PID", str(pid))
    table.add_row("Port", str(state.get("port", "unknown")))

    ticket = state.get("ticket", "")
    if ticket:
        # Truncate for display but show full ticket below
        table.add_row("Ticket", ticket[:60] + ("..." if len(ticket) > 60 else ""))
    else:
        table.add_row("Ticket", "[dim]unknown[/dim]")

    table.add_row("Secret", "[dim]stored[/dim]" if state.get("secret") else "[dim]none[/dim]")

    auth_token = state.get("auth_token", "")
    if auth_token:
        masked = "***" + auth_token[-4:] if len(auth_token) > 4 else "***"
        table.add_row("Auth token", masked)
    else:
        table.add_row("Auth token", "[dim]not set[/dim]")

    console.print()
    console.print(table)

    if ticket:
        console.print(f"\n[bold]Full ticket:[/bold]\n[dim]{ticket}[/dim]")

    if not alive:
        console.print(
            "\n[yellow]The proxy process is no longer running.[/yellow]\n"
            "Run [bold]art proxy start[/bold] to restart it."
        )
        _remove_state()


def get_active_proxy() -> dict[str, Any] | None:
    """Return the active proxy state, or None if no proxy is running.

    This is the interface used by ``launch.py`` to detect whether tunnel
    injection should happen.
    """
    state = _read_state()
    if not state:
        return None
    pid = state.get("pid", 0)
    if not pid or not _pid_alive(pid):
        return None
    if not state.get("ticket"):
        return None
    return state
