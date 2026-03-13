# Autoresearch Team — Lightning AI Infrastructure

Launch N GPU runners + 1 CPU reviewer as independent Lightning AI Studios.

## Prerequisites

- Python ≥ 3.11
- A [Lightning AI](https://lightning.ai) account with a teamspace
- `LIGHTNING_API_KEY` set in your environment (or authenticated via `lightning login`)
- `GH_TOKEN` or `GITHUB_TOKEN` with `repo` scope for git-based coordination

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
| `uv` | Yes | Install via `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `git` | Yes | Install via your OS package manager |
| Lightning AI auth | Yes | Provide `LIGHTNING_USER_ID` + `LIGHTNING_API_KEY`, or run `lightning login` |
| `ANTHROPIC_API_KEY` | Yes (for agents) | Get from [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| GitHub token | Yes (for coordination) | `GH_TOKEN` or `GITHUB_TOKEN` with `repo` scope — [github.com/settings/tokens](https://github.com/settings/tokens) |
| `claude` CLI | Yes | `npm install -g @anthropic-ai/claude-code` |

The wizard can write credentials to a `.env` file (auto-added to `.gitignore`).

For CI or non-interactive environments, use the check-only mode:

```bash
uv run art init --check    # exits 1 if required items are missing
```

## Configuration

All tunables live in [`config.yaml`](config.yaml):

| Key | Description | Default |
|-----|-------------|---------|
| `teamspace` | Lightning AI teamspace name | `chartsoo` |
| `org` | Lightning AI org (leave empty to auto-detect) | `""` |
| `repo_url` | Git repo cloned during studio setup | `codyhartsook/autoresearch-team` |
| `repo_branch` | Branch to clone | `main` |
| `coordination_repo.url` | Repo runners push/pull to for coordination | `codyhartsook/autoresearch-team` |
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
│                      Git (remote repo)                      │
│              (shared knowledge store)                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

Studios coordinate through git — each runner clones the shared repo, works
on branches, and pushes results. The reviewer fetches and reads across
branches. No shared filesystem required.

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

## Testing

End-to-end tests live in `tests/e2e/` and exercise the real Lightning SDK against
live CPU Studios. They validate the three core infrastructure assumptions:
Studio lifecycle, git-based cross-machine coordination, and script execution.

Studios are treated as fully independent remote machines — **no shared filesystem**.
All cross-studio data exchange goes through a real GitHub remote.

### Prerequisites

- Lightning AI auth configured (`uv run art init` or env vars)
- No GPU required — all tests use `Machine.CPU`
- `GH_TOKEN` or `GITHUB_TOKEN` env var with `repo` scope (for git push tests)
- `gh` CLI installed (for auto-creating temporary repos, unless using an existing repo)

### Git repo options

The git coordination tests need a GitHub repo that both Studios can push to.
Two modes are supported:

1. **Auto-create (default)** — Leave `test_repo.url` empty in `config_e2e.yaml`.
   The fixture creates a temporary private repo before tests and deletes it
   after. Requires `GH_TOKEN` with `repo` scope.

2. **Existing repo** — Set `test_repo.url` to a repo you own. The `GH_TOKEN`
   must have push access. Test branches are cleaned up after each test.

Override via env: `E2E_TEST_REPO_URL=https://github.com/you/repo.git`

### Running

```bash
# Install test deps
uv sync --extra test

# Set GitHub token (needed for git push tests)
export GH_TOKEN="ghp_..."

# Run the full e2e suite (~3-5 min, dominated by Studio startup)
uv run pytest tests/e2e/ -v --tb=short -s --log-cli-level=INFO

# Run a single test module
uv run pytest tests/e2e/test_studio_lifecycle.py -v -s

# Use an existing repo instead of auto-creating
E2E_TEST_REPO_URL=https://github.com/you/repo.git \
  uv run pytest tests/e2e/test_git_coordination.py -v -s

# Skip e2e tests (for fast unit test runs later)
uv run pytest -m "not e2e"
```

### What the tests do

The suite creates **two CPU Studios** with unique names (`e2etest-{uuid}-0`,
`e2etest-{uuid}-1`) at session scope, runs all tests, then deletes both
Studios — even if tests fail or are interrupted.

| Module | Tests | What it validates |
|--------|-------|-------------------|
| `test_studio_lifecycle.py` | 8 | Studios reach Running status, echo commands work, exit codes propagate, git is available |
| `test_git_coordination.py` | 8 | Both Studios clone same remote, A pushes branch → B fetches it, incremental commits via pull, JSON payload round-trip |
| `test_run_script.py` | 3 | Multi-line bash+python scripts, nonzero exit detection |

### Test config

Tests use their own [`tests/e2e/config_e2e.yaml`](../../tests/e2e/config_e2e.yaml)
— CPU-only, 2 runners, no reviewer, no `studio_setup.sh`. Completely isolated
from the production `config.yaml`.

### Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `LIGHTNING_USER_ID` + `LIGHTNING_API_KEY` | Yes (or credential file) | Lightning AI auth |
| `GH_TOKEN` or `GITHUB_TOKEN` | Yes (for git tests) | GitHub auth — push access + `repo` scope for auto-create |
| `E2E_RUN_ID` | No | Override the random Studio name suffix (useful for debugging) |
| `E2E_TEST_REPO_URL` | No | Force an existing repo instead of auto-creating |

### Cleanup

Studios are deleted in a `finally` block, so cleanup runs even on failure or
Ctrl-C. Temporary GitHub repos are also deleted in a `finally` block.
If a previous run left orphaned Studios (e.g. process kill), they'll
have unique names and won't interfere — clean them up manually via the
Lightning AI dashboard or `art teardown`.

## Open Questions

1. **`Studio.run()` blocking** — Does `Studio.run()` block until the command
   finishes? For long-running commands (the experiment loop), we may need
   `nohup` / `tmux` wrapping.

2. **API key propagation** — How `ANTHROPIC_API_KEY` reaches each Studio.
   Options: teamspace secrets, `Studio.set_env()`, manual `export`.

3. **Machine enum values** — Exact `lightning_sdk.Machine.H100` names. These
   are isolated behind `MACHINE_MAP` in `launch.py` for easy updates.
