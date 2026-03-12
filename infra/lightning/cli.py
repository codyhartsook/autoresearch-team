"""Autoresearch Team CLI — Lightning AI infrastructure management.

Single entry point ``art`` with subcommands: init, launch, teardown, health.

Usage::

    uv run art init                  # setup wizard
    uv run art init --check          # non-interactive env check
    uv run art launch --dry-run
    uv run art health --watch
    uv run art teardown
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
    "--mode",
    type=click.Choice(["all", "runners", "reviewer"]),
    default="all",
    help="Which components to launch.",
)
@click.option("--runners", type=int, default=None, help="Override runner count.")
@click.option(
    "--gpu",
    type=click.Choice(["H100", "A100", "A10G", "L4"]),
    default=None,
    help="Override GPU type for runners.",
)
@click.option("--dry-run", is_flag=True, help="Preview the fleet without launching.")
@click.pass_context
def launch(ctx: click.Context, mode: str, runners: int | None, gpu: str | None, dry_run: bool) -> None:
    """Launch the autoresearch fleet (runners + reviewer Studios)."""
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
