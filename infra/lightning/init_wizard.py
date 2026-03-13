"""Setup wizard — interactive environment bootstrap for the autoresearch fleet.

Checks for required credentials, tools, and configuration.  Optionally writes
a ``.env`` file so subsequent ``art`` commands Just Work.

Run via::

    art init              # interactive wizard
    art init --check      # non-interactive check only (CI-friendly)
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()

# Where the wizard writes secrets (gitignored)
_ENV_FILE = Path.cwd() / ".env"

# Lightning credential file (written by `lightning login`)
_LIGHTNING_CREDS = Path.home() / ".lightning" / "credentials.json"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_tool(name: str, *, test_cmd: str | None = None) -> dict[str, Any]:
    """Check whether a CLI tool is available on PATH."""
    path = shutil.which(name)
    if not path:
        return {"name": name, "found": False, "detail": "not found on PATH"}
    # Try to get a version string
    version = ""
    cmd = test_cmd or f"{name} --version"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        )
        version = result.stdout.strip().split("\n")[0] or result.stderr.strip().split("\n")[0]
    except Exception:
        version = path
    return {"name": name, "found": True, "detail": version}


def _check_env_var(var: str) -> dict[str, Any]:
    """Check whether an environment variable is set (non-empty)."""
    val = os.environ.get(var, "")
    if val:
        # Mask all but last 4 chars
        masked = "•" * max(0, len(val) - 4) + val[-4:] if len(val) > 4 else "•" * len(val)
        return {"name": var, "found": True, "detail": masked}
    return {"name": var, "found": False, "detail": "not set"}


def _check_lightning_auth() -> dict[str, Any]:
    """Check for Lightning AI authentication via env vars OR credential file."""
    # Option 1: env vars
    has_token = bool(os.environ.get("LIGHTNING_AUTH_TOKEN"))
    has_key = bool(os.environ.get("LIGHTNING_USER_ID") and os.environ.get("LIGHTNING_API_KEY"))

    if has_token:
        return {"name": "Lightning AI auth", "found": True, "detail": "LIGHTNING_AUTH_TOKEN set"}
    if has_key:
        return {"name": "Lightning AI auth", "found": True, "detail": "LIGHTNING_USER_ID + LIGHTNING_API_KEY set"}

    # Option 2: credential file from `lightning login`
    if _LIGHTNING_CREDS.exists():
        return {"name": "Lightning AI auth", "found": True, "detail": f"credentials at {_LIGHTNING_CREDS}"}

    return {
        "name": "Lightning AI auth",
        "found": False,
        "detail": "no env vars or credential file found",
    }


def _check_gh_token() -> dict[str, Any]:
    """Check for a GitHub token (GH_TOKEN or GITHUB_TOKEN).

    Used for git-based coordination between runners — pushing branches,
    creating repos, etc.
    """
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        val = os.environ.get(var, "")
        if val:
            masked = "•" * max(0, len(val) - 4) + val[-4:] if len(val) > 4 else "•" * len(val)
            return {"name": "GitHub token", "found": True, "detail": f"{var}: {masked}"}
    return {
        "name": "GitHub token",
        "found": False,
        "detail": "GH_TOKEN / GITHUB_TOKEN not set",
    }



# ---------------------------------------------------------------------------
# Results table
# ---------------------------------------------------------------------------


def _results_table(checks: list[dict[str, Any]], *, title: str = "Environment Check") -> Table:
    table = Table(title=title)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status")
    table.add_column("Detail", style="dim")

    for c in checks:
        if c["found"]:
            badge = "[bold green]✓ found[/bold green]"
        else:
            badge = "[bold red]✗ missing[/bold red]"
        table.add_row(c["name"], badge, c["detail"])

    return table


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------


def _prompt_lightning_creds() -> dict[str, str]:
    """Interactively collect Lightning AI credentials."""
    console.print()
    console.print(
        Panel(
            "Lightning AI credentials are needed to create and manage Studios.\n\n"
            "You have two options:\n"
            "  [bold]1.[/bold] Provide [cyan]LIGHTNING_USER_ID[/cyan] + [cyan]LIGHTNING_API_KEY[/cyan]\n"
            "     Get these from [link=https://lightning.ai/account]lightning.ai/account[/link]\n\n"
            "  [bold]2.[/bold] Run [bold]lightning login[/bold] in your terminal (interactive browser flow)\n"
            "     This saves credentials to [dim]~/.lightning/credentials.json[/dim]",
            title="[bold yellow]Lightning AI Authentication[/bold yellow]",
            border_style="yellow",
        )
    )

    choice = Prompt.ask(
        "\nHow would you like to authenticate?",
        choices=["env", "login", "skip"],
        default="env",
    )

    creds: dict[str, str] = {}
    if choice == "env":
        user_id = Prompt.ask("  LIGHTNING_USER_ID")
        api_key = Prompt.ask("  LIGHTNING_API_KEY", password=True)
        if user_id and api_key:
            creds["LIGHTNING_USER_ID"] = user_id
            creds["LIGHTNING_API_KEY"] = api_key
    elif choice == "login":
        console.print("\n[dim]Running interactive Lightning login...[/dim]")
        try:
            subprocess.run(["lightning", "login"], check=True)
            console.print("[green]✓ Lightning login successful.[/green]")
        except FileNotFoundError:
            console.print(
                "[red]✗ 'lightning' CLI not found.[/red]  "
                "Install it with [bold]pip install lightning-sdk[/bold] and try again."
            )
        except subprocess.CalledProcessError:
            console.print("[red]✗ Lightning login failed.[/red]")
    else:
        console.print("[dim]Skipped Lightning auth.[/dim]")

    return creds


def _prompt_anthropic_key() -> dict[str, str]:
    """Interactively collect the Anthropic API key."""
    console.print()
    console.print(
        Panel(
            "An Anthropic API key is required for Claude Code agents inside Studios.\n\n"
            "Get one from [link=https://console.anthropic.com/settings/keys]console.anthropic.com[/link]",
            title="[bold yellow]Anthropic API Key[/bold yellow]",
            border_style="yellow",
        )
    )

    key = Prompt.ask("  ANTHROPIC_API_KEY (or press Enter to skip)", default="", password=True)
    if key:
        return {"ANTHROPIC_API_KEY": key}
    console.print("[dim]Skipped Anthropic key.[/dim]")
    return {}


def _prompt_gh_token() -> dict[str, str]:
    """Interactively collect a GitHub personal access token."""
    console.print()
    console.print(
        Panel(
            "A GitHub token is used for git-based coordination between runners.\n"
            "Runners push/pull branches to share results via a shared repo.\n\n"
            "Create a token at [link=https://github.com/settings/tokens]github.com/settings/tokens[/link]\n"
            "Required scopes: [bold]repo[/bold]",
            title="[bold yellow]GitHub Token[/bold yellow]",
            border_style="yellow",
        )
    )

    key = Prompt.ask("  GH_TOKEN (or press Enter to skip)", default="", password=True)
    if key:
        return {"GH_TOKEN": key}
    console.print("[dim]Skipped GitHub token.[/dim]")
    return {}


def _write_env_file(env_vars: dict[str, str]) -> None:
    """Append key=value pairs to .env, creating if needed."""
    if not env_vars:
        return

    # Read existing content to avoid duplicates
    existing: dict[str, str] = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    new_vars = {k: v for k, v in env_vars.items() if k not in existing}
    if not new_vars:
        console.print("[dim]All variables already present in .env — nothing to write.[/dim]")
        return

    with open(_ENV_FILE, "a") as f:
        if not _ENV_FILE.exists() or _ENV_FILE.stat().st_size == 0:
            f.write("# Autoresearch Team — environment variables\n")
            f.write("# Generated by `art init`. Keep this file out of version control.\n\n")
        for k, v in new_vars.items():
            f.write(f'{k}="{v}"\n')

    console.print(f"\n[green]✓ Wrote {len(new_vars)} variable(s) to [bold]{_ENV_FILE}[/bold][/green]")

    # Ensure .env is gitignored
    _ensure_gitignore()


def _ensure_gitignore() -> None:
    """Add .env to .gitignore if it's not already there."""
    gitignore = Path.cwd() / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".env" in content.splitlines() or "*.env" in content:
            return
    else:
        content = ""

    with open(gitignore, "a") as f:
        if content and not content.endswith("\n"):
            f.write("\n")
        f.write("\n# Secrets — never commit\n.env\n")
    console.print("[dim]Added .env to .gitignore[/dim]")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_wizard(*, check_only: bool = False) -> None:
    """Run the setup wizard.

    Parameters
    ----------
    check_only : bool
        If True, only display the environment check table — no prompts.
    """
    console.print()
    console.print(
        Panel(
            "[bold]Autoresearch Team[/bold] — setup wizard\n\n"
            "This checks your environment for the tools and credentials\n"
            "needed to launch the Lightning AI fleet.",
            title="[bold cyan]art init[/bold cyan]",
            border_style="cyan",
        )
    )

    # Load .env early so checks can see values from it
    load_dotenv(_ENV_FILE)

    # ── Run all checks ──────────────────────────────────────────────
    #   uv          – runs everything (uv sync, art …)
    #   git         – studio_setup.sh clones repos
    #   Lightning   – SDK auth for Studio create/start/stop
    #   Anthropic   – Claude Code agents inside Studios
    #   GH_TOKEN    – git-based coordination (push/pull between runners)
    #   claude      – Claude Code CLI runs inside Studios
    checks: list[dict[str, Any]] = []

    checks.append(_check_tool("uv"))
    checks.append(_check_tool("git"))
    checks.append(_check_lightning_auth())
    checks.append(_check_env_var("ANTHROPIC_API_KEY"))
    checks.append(_check_gh_token())
    checks.append(_check_tool("claude", test_cmd="claude --version"))

    console.print()
    console.print(_results_table(checks))

    missing = [c for c in checks if not c["found"]]

    if not missing:
        console.print()
        console.print(
            Panel(
                "All checks passed.  You're ready to go!\n\n"
                "  [bold]art launch --dry-run[/bold]   preview the fleet\n"
                "  [bold]art launch[/bold]             launch it",
                title="[bold green]Ready[/bold green]",
                border_style="green",
            )
        )
        return

    # ── Check-only mode: just show results ──────────────────────────
    if check_only:
        console.print()
        if missing:
            console.print(
                f"[bold red]{len(missing)} required item(s) missing.[/bold red]  "
                "Run [bold]art init[/bold] (without --check) to fix interactively."
            )
            raise SystemExit(1)
        return

    # ── Interactive setup ───────────────────────────────────────────
    env_vars: dict[str, str] = {}

    # Lightning
    lightning_check = next(c for c in checks if c["name"] == "Lightning AI auth")
    if not lightning_check["found"]:
        env_vars.update(_prompt_lightning_creds())

    # Anthropic
    anthropic_check = next(c for c in checks if c["name"] == "ANTHROPIC_API_KEY")
    if not anthropic_check["found"]:
        env_vars.update(_prompt_anthropic_key())

    # GitHub token
    gh_check = next(c for c in checks if c["name"] == "GitHub token")
    if not gh_check["found"]:
        env_vars.update(_prompt_gh_token())

    # Write .env
    if env_vars:
        console.print()
        if Confirm.ask("Write these credentials to [bold].env[/bold]?", default=True):
            _write_env_file(env_vars)
            # Reload so the re-check sees them
            for k, v in env_vars.items():
                os.environ[k] = v
        else:
            console.print(
                "[dim]Not writing .env.  Export the variables manually before running art commands.[/dim]"
            )

    # ── Re-check and display final status ───────────────────────────
    console.print()
    final_checks: list[dict[str, Any]] = []
    final_checks.append(_check_tool("uv"))
    final_checks.append(_check_tool("git"))
    final_checks.append(_check_lightning_auth())
    final_checks.append(_check_env_var("ANTHROPIC_API_KEY"))
    final_checks.append(_check_gh_token())
    final_checks.append(_check_tool("claude", test_cmd="claude --version"))

    console.print(_results_table(final_checks, title="Final Status"))

    still_missing = [c for c in final_checks if not c["found"]]
    console.print()
    if still_missing:
        console.print(
            Panel(
                "Some items are still missing — see the table above.\n"
                "You can re-run [bold]art init[/bold] any time.",
                title="[yellow]Incomplete[/yellow]",
                border_style="yellow",
            )
        )
    else:
        console.print(
            Panel(
                "Setup complete!  Next steps:\n\n"
                "  [bold]art launch --dry-run[/bold]   preview the fleet\n"
                "  [bold]art launch[/bold]             launch it",
                title="[bold green]Ready[/bold green]",
                border_style="green",
            )
        )
