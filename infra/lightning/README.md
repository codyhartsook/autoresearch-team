# Autoresearch Team — Lightning AI Infrastructure

Launch independent Lightning AI Studios from a session YAML file or the legacy
runners + reviewer config.

## Prerequisites

- Python ≥ 3.11
- A [Lightning AI](https://lightning.ai) account with a teamspace
- `LIGHTNING_API_KEY` set in your environment (or authenticated via `lightning login`)
- `GH_TOKEN` or `GITHUB_TOKEN` with `repo` scope for git-based coordination

## Installation

```bash
# Install uv (if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install the package (from the repo root)
uv sync

# Activate the virtual environment so `art` is on your PATH
source .venv/bin/activate    # macOS / Linux
# .venv\Scripts\activate     # Windows

# Verify
art --help
```

After activation, the `art` command is available directly in your shell.

> **Tip:** If you prefer not to activate the venv, `uv run art <command>` works
> without any install step — uv resolves dependencies and runs the entry point
> on the fly.

## Quick Start

```bash
# Run the setup wizard — checks creds, tools, writes .env
art init

# Preview the fleet (no Studios launched)
art launch --dry-run

# Launch from the legacy config (3 runners + 1 reviewer)
art launch

# Launch from a session YAML file
art launch --file sessions.example.yaml

# Preview the session file launch
art launch --file sessions.example.yaml --dry-run

# Check status
art health

# Continuous monitoring
art health --watch

# Stop everything
art teardown

# Permanently delete Studios
art teardown --delete
```

## Setup Wizard

Run `art init` before your first launch. The wizard checks for:

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
art init --check    # exits 1 if required items are missing
```

## Configuration

There are two ways to configure what gets launched:

### Option 1: Session YAML file (recommended for new setups)

Pass a session file with `--file`. Each session group defines a name,
instance count, GPU type, and command. No role semantics — the infra layer
just provisions what you describe.

See [`sessions.example.yaml`](sessions.example.yaml) for a documented example.

| Key | Description |
|-----|-------------|
| `teamspace` | Lightning AI teamspace (falls back to global config) |
| `org` | Lightning AI org (falls back to global config) |
| `sessions[].name` | Group name — instances named `{name}-0`, `{name}-1`, … |
| `sessions[].count` | Number of instances in the group |
| `sessions[].gpu_type` | `H100` / `A100` / `A10G` / `L4` / `CPU` |
| `sessions[].command` | Command to run (supports `{i}` for instance index) |
| `launch.stagger_seconds` | Delay between Studio launches |
| `launch.run_setup` | Run `studio_setup.sh` on each Studio |

### Option 2: Legacy config (runners + reviewer)

All tunables live in [`config.yaml`](config.yaml):

| Key | Description | Default |
|-----|-------------|---------|
| `teamspace` | Lightning AI teamspace name | `chartsoo` |
| `org` | Lightning AI org (leave empty to auto-detect) | `""` |
| `runners.count` | Number of GPU runner Studios | `3` |
| `runners.gpu_type` | GPU type per runner | `H100` |
| `runners.command` | Command to run in each runner Studio | placeholder |
| `reviewer.enabled` | Whether to launch a reviewer | `true` |
| `reviewer.gpu_type` | Reviewer machine type | `CPU` |
| `launch.stagger_seconds` | Delay between Studio launches | `5` |
| `launch.run_setup` | Run `studio_setup.sh` on each Studio | `true` |

Repo URLs and coordination details are **not** in this config — they're
passed via environment variables (`ART_TEAM_REPO`, `ART_AUTORESEARCH_REPO`,
etc.). See [`../PROVIDER_CONTRACT.md`](../PROVIDER_CONTRACT.md) for the
separation between infra and architecture concerns.

### CLI Overrides

```bash
# Launch from a session file
art launch --file sessions.yaml

# Launch from a session file (dry run)
art launch --file sessions.yaml --dry-run

# Legacy: launch 1 runner on an A10G (cheaper for testing)
art launch --mode runners --runners 1 --gpu A10G

# Legacy: launch only the reviewer
art launch --mode reviewer

# Use a custom global config file
art --config my-config.yaml launch
```

## Role in the stack

This is a **provider adapter** — it satisfies the infrastructure contract
defined in [`../PROVIDER_CONTRACT.md`](../PROVIDER_CONTRACT.md) using
Lightning AI Studios. It provisions sessions, runs commands, and tears down.
It has no knowledge of the protocol, experiment loop, or coordination logic.

See [`architecture.md`](../../architecture.md) § Infrastructure for how this
layer fits into the overall system.

```
┌─────────────────────────────────────────────────────────────┐
│                    Lightning Teamspace                      │
│                                                             │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │ gpu-worker-0 │ │ gpu-worker-1 │ │ gpu-worker-2 │  ...    │
│  │    (H100)    │ │    (H100)    │ │    (H100)    │         │
│  └──────────────┘ └──────────────┘ └──────────────┘         │
│  ┌──────────────┐                                           │
│  │ cpu-worker-0 │   Session groups are defined in YAML.     │
│  │    (CPU)     │   The infra layer assigns no roles.       │
│  └──────────────┘                                           │
│                                                             │
│  Each Studio is independent — no shared filesystem, no      │
│  inter-session communication through the provider.          │
└─────────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `cli.py` | Click CLI group — the `art` entry point |
| `init_wizard.py` | Setup wizard — credential & tool checks, .env writer |
| `launch.py` | Studio launch logic with rich progress output |
| `teardown.py` | Graceful shutdown / deletion |
| `health_check.py` | Status monitor with rich tables |
| `config.py` | Config loading, validation, override merging |
| `config.yaml` | Legacy configuration (runners + reviewer) |
| `sessions.example.yaml` | Example session YAML for `--file` path |
| `studio_setup.sh` | Environment provisioning (runs inside each Studio) |

## Testing

End-to-end tests live in `tests/e2e/` and exercise the real Lightning SDK against
live CPU Studios. They validate the three core infrastructure assumptions:
Studio lifecycle, git-based cross-machine coordination, and script execution.

Studios are treated as fully independent remote machines — **no shared filesystem**.
All cross-studio data exchange goes through a real GitHub remote.

### Prerequisites

- Lightning AI auth configured (`art init` or env vars)
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
pytest tests/e2e/ -v --tb=short -s --log-cli-level=INFO

# Run a single test module
pytest tests/e2e/test_studio_lifecycle.py -v -s

# Use an existing repo instead of auto-creating
E2E_TEST_REPO_URL=https://github.com/you/repo.git \
  pytest tests/e2e/test_git_coordination.py -v -s

# Skip e2e tests (for fast unit test runs later)
pytest -m "not e2e"
```

### What the tests do

The suite creates **two CPU Studios** with unique names (`e2etest-{uuid}-0`,
`e2etest-{uuid}-1`) at session scope, runs all tests, then deletes both
Studios — even if tests fail or are interrupted.

| Module | Tests | What it validates (provider contract) |
|--------|-------|---------------------------------------|
| `test_studio_lifecycle.py` | 8 | Sessions start, commands execute, exit codes propagate, git available |
| `test_git_coordination.py` | 6 | Network access (clone scripts), credential injection (push/fetch scripts) |
| `test_run_script.py` | 3 | Multi-line bash+python scripts, nonzero exit detection |

Tests are written as **opaque scripts** — the infra layer runs them without
knowing what they do internally.  This keeps tests provider-agnostic.

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
