# Sample Experiments

Self-contained experiment configurations for testing and validating the autoresearch infrastructure. Each subdirectory is a complete experiment definition that can be launched with `art launch --file`.

## Available experiments

| Experiment | GPU | Description |
|------------|-----|-------------|
| [`single-runner/`](single-runner/) | 1× H100 | Smoke test — run one autoresearch training cycle to validate the full pipeline |

## How it works

Each experiment directory contains:

- **`sessions.yaml`** — Session config for `art launch --file`
- **`run_*.sh`** — Script(s) that execute inside the Studio
- **`README.md`** — What it does, how to run it, expected output

The infra layer (`art launch`) handles Studio provisioning, environment setup (`studio_setup.sh`), and command execution. The experiment scripts are opaque payloads — the infra layer doesn't interpret them.

## Running an experiment

```bash
# 1. Ensure credentials are configured
art init

# 2. Set repo URLs (if not already in .env)
export ART_TEAM_REPO="https://github.com/codyhartsook/autoresearch-team.git"
export ART_AUTORESEARCH_REPO="https://github.com/karpathy/autoresearch.git"

# 3. Preview
art launch --file sample-experiments/<experiment>/sessions.yaml --dry-run

# 4. Launch
art launch --file sample-experiments/<experiment>/sessions.yaml

# 5. Monitor
art health --watch

# 6. Clean up
art teardown --delete
```

## Adding new experiments

Create a new subdirectory with at minimum `sessions.yaml` and a `README.md`. Follow the pattern in `single-runner/` for consistency.

Future experiments might include:
- **Multi-runner** — N parallel runners + reviewer (tests fleet coordination)
- **Autoresearch loop** — Claude Code agent running the full edit → train → evaluate cycle
- **Cost comparison** — Same experiment across H100 / A100 / L4 tiers
