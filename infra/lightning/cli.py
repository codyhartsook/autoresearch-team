"""Autoresearch Team CLI — Lightning AI infrastructure management.

Single entry point ``art`` with subcommands: init, launch, teardown, health, logs.

Usage::

    art init                  # setup wizard
    art init --check          # non-interactive env check
    art launch --dry-run
    art health --watch
    art logs --watch
    art teardown
"""

from __future__ import annotations

import click

from infra.lightning.config import apply_overrides, load_config


@click.group()
@click.option(
    "--config",
    type=click.Path(exists=True),
    default=None,
    help="Path to config.yaml (defaults to built-in config).",
)
@click.pass_context
def cli(ctx: click.Context, config: str | None) -> None:
    """Autoresearch Team — Lightning AI infrastructure CLI."""
    ctx.ensure_object(dict)
    # Lazy config loading — some commands (like init) don't need it.
    ctx.obj["_config_path"] = config


def _get_config(ctx: click.Context) -> dict:
    """Load config on first access (so ``init`` can skip it)."""
    if "config" not in ctx.obj:
        ctx.obj["config"] = load_config(ctx.obj["_config_path"])
    return ctx.obj["config"]


# ---------------------------------------------------------------------------
# init — runs before anything else, no config required
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--check", is_flag=True, help="Non-interactive check only (CI-friendly).")
@click.pass_context
def init(ctx: click.Context, check: bool) -> None:
    """Setup wizard — check credentials, tools, and write .env."""
    from infra.lightning.init_wizard import run_wizard

    run_wizard(check_only=check)


@cli.command()
@click.option(
    "--file",
    "session_file",
    type=click.Path(exists=True),
    default=None,
    help="Session YAML file (alternative to --mode/--runners/--gpu).",
)
@click.option(
    "--mode",
    type=click.Choice(["all", "runners", "reviewer"]),
    default="all",
    help="Which components to launch.",
)
@click.option("--runners", type=int, default=None, help="Override runner count.")
@click.option(
    "--gpu",
    type=click.Choice(["H100", "H200", "A100", "L40S", "L4", "T4"]),
    default=None,
    help="Override GPU type for runners.",
)
@click.option("--dry-run", is_flag=True, help="Preview the fleet without launching.")
@click.pass_context
def launch(
    ctx: click.Context,
    session_file: str | None,
    mode: str,
    runners: int | None,
    gpu: str | None,
    dry_run: bool,
) -> None:
    """Launch the autoresearch fleet (runners + reviewer Studios).

    Use --file to provide a session YAML file instead of the global config.
    """
    if session_file:
        # New path: launch from session file
        from infra.lightning.config import load_session_config
        from infra.lightning.launch import launch_sessions

        base_cfg = _get_config(ctx)
        cfg = load_session_config(session_file, base_cfg=base_cfg)
        launch_sessions(cfg, dry_run=dry_run)
    else:
        # Legacy path: runners/reviewer from global config
        from infra.lightning.launch import launch_fleet

        cfg = apply_overrides(_get_config(ctx), runners=runners, gpu=gpu)
        launch_fleet(cfg, mode=mode, dry_run=dry_run)


@cli.command()
@click.option(
    "--mode",
    type=click.Choice(["all", "runners", "reviewer"]),
    default="all",
    help="Which components to tear down.",
)
@click.option("--delete", is_flag=True, help="Remove Studios entirely, not just stop.")
@click.pass_context
def teardown(ctx: click.Context, mode: str, delete: bool) -> None:
    """Stop or remove fleet Studios."""
    from infra.lightning.teardown import teardown_fleet

    teardown_fleet(_get_config(ctx), mode=mode, delete=delete)


@cli.command()
@click.option("--watch", is_flag=True, help="Continuously refresh status.")
@click.option("--interval", type=int, default=30, help="Watch refresh interval (seconds).")
@click.pass_context
def health(ctx: click.Context, watch: bool, interval: int) -> None:
    """Show fleet health status."""
    from infra.lightning.health_check import check_health

    check_health(_get_config(ctx), watch=watch, interval=interval)


# ---------------------------------------------------------------------------
# logs — pull telemetry from running Studios
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--file",
    "session_file",
    type=click.Path(exists=True),
    default=None,
    help="Session YAML file (to discover Studio names).",
)
@click.option("--name", default=None, help="Filter to a single Studio by name.")
@click.option("--tail", "tail_n", type=int, default=10, help="Show last N events per Studio.")
@click.option("--watch", is_flag=True, help="Continuously refresh.")
@click.option("--interval", type=int, default=30, help="Watch refresh interval (seconds).")
@click.pass_context
def logs(
    ctx: click.Context,
    session_file: str | None,
    name: str | None,
    tail_n: int,
    watch: bool,
    interval: int,
) -> None:
    """Pull and display telemetry events from running Studios.

    Reads metrics.jsonl from each Studio and displays a summary table.
    Use --file to discover Studios from a session YAML, otherwise uses
    the global config (runners + reviewer).
    """
    from infra.lightning.telemetry import show_logs

    if session_file:
        from infra.lightning.config import load_session_config

        base_cfg = _get_config(ctx)
        cfg = load_session_config(session_file, base_cfg=base_cfg)
    else:
        cfg = _get_config(ctx)

    show_logs(cfg, studio_filter=name, tail_n=tail_n, watch=watch, interval=interval)
