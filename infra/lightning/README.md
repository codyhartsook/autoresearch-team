# Autoresearch Team — Lightning AI Infrastructure

Launch N GPU runners + 1 CPU reviewer as independent Lightning AI Studios.

## Prerequisites

- Python ≥ 3.11
- A [Lightning AI](https://lightning.ai) account with a teamspace named `autoresearch-team`
- `LIGHTNING_API_KEY` set in your environment (or authenticated via `lightning login`)

## Quick Start

```bash
# Install uv (if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Run the setup wizard — checks creds, tools, writes .env
uv run art init

# Preview the fleet (no Studios launched)
uv run art launch --dry-run

# Launch the full fleet (3 runners + 1 reviewer)
uv run art launch

# Check status
uv run art health

# Continuous monitoring
uv run art health --watch

# Stop everything
uv run art teardown

# Permanently delete Studios
uv run art teardown --delete
```

## Setup Wizard

Run `uv run art init` before your first launch. The wizard checks for:

| Check | Required? | How to fix |
|-------|-----------|------------|
| `python3` | Yes | Install Python 3.11+ |
| `uv` | Yes | Wizard offers to install automatically |
| `git` | Yes | Install via your OS package manager |
| Lightning AI auth | Yes | Provide `LIGHTNING_USER_ID` + `LIGHTNING_API_KEY`, or run `lightning login` |
| `ANTHROPIC_API_KEY` | Yes (for agents) | Get from [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| `node` / `npm` | Optional | Needed to install Claude Code CLI inside Studios |
| `claude` CLI | Optional | Installed automatically if `npm` is available |
| `gh` CLI | Optional | Useful for GitHub integration |

The wizard can write credentials to a `.env` file (auto-added to `.gitignore`).

For CI or non-interactive environments, use the check-only mode:

```bash
uv run art init --check    # exits 1 if required items are missing
```

## Configuration

All tunables live in [`config.yaml`](config.yaml):

| Key | Description | Default |
|-----|-------------|---------|
| `teamspace` | Lightning AI teamspace name | `autoresearch-team` |
| `runners.count` | Number of GPU runner Studios | `3` |
| `runners.gpu_type` | GPU type per runner | `H100` |
| `reviewer.enabled` | Whether to launch a reviewer | `true` |
| `reviewer.gpu_type` | Reviewer machine type | `CPU` |
| `launch.stagger_seconds` | Delay between Studio launches | `5` |
| `launch.run_setup` | Run `studio_setup.sh` on each Studio | `true` |

### CLI Overrides

Override config values directly from the command line:

```bash
# Launch 1 runner on an A10G (cheaper for testing)
uv run art launch --mode runners --runners 1 --gpu A10G

# Launch only the reviewer
uv run art launch --mode reviewer

# Use a custom config file
uv run art --config my-config.yaml launch
```

## Architecture

This infrastructure layer implements the "no rounds or barriers" design from
[`architecture.md`](../../architecture.md). Each runner and the reviewer is an
independent, long-running Lightning Studio — **not** a Pipeline step.

```
┌─────────────────────────────────────────────────────────────┐
│                    Lightning Teamspace                       │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ runner-0 │  │ runner-1 │  │ runner-2 │  │  reviewer   │ │
│  │  (H100)  │  │  (H100)  │  │  (H100)  │  │   (CPU)    │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘ │
│       │              │              │              │        │
│       └──────────────┴──────┬───────┴──────────────┘        │
│                             │                               │
│                    /teamspace/data/                          │
│              (shared knowledge store)                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

Studios share state through the teamspace filesystem (`/teamspace/data/`),
which contains the leaderboard, claims, dead ends, insights, and experiment
manifests.

## Files

| File | Purpose |
|------|---------|
| `cli.py` | Click CLI group — the `art` entry point |
| `init_wizard.py` | Setup wizard — credential & tool checks, .env writer |
| `launch.py` | Studio launch logic with rich progress output |
| `teardown.py` | Graceful shutdown / deletion |
| `health_check.py` | Status monitor with rich tables |
| `config.py` | Config loading, validation, override merging |
| `config.yaml` | Central configuration |
| `studio_setup.sh` | Environment provisioning (runs inside each Studio) |

## Open Questions

1. **`Studio.run()` blocking** — Does `Studio.run()` block until the command
   finishes? For long-running commands (the experiment loop), we may need
   `nohup` / `tmux` wrapping.

2. **Shared filesystem path** — Assumed `/teamspace/data/`. Verify on a live
   teamspace with `ls /teamspace/`.

3. **API key propagation** — How `ANTHROPIC_API_KEY` reaches each Studio.
   Options: teamspace secrets, `.env` file on shared storage, manual `export`.

4. **Machine enum values** — Exact `lightning_sdk.Machine.H100` names. These
   are isolated behind `MACHINE_MAP` in `launch.py` for easy updates.
