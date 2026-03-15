# Single-Runner Smoke Test

Prove that autoresearch runs end-to-end on a Lightning AI H100 Studio.

## What it does

Launches **1 H100 Studio** that:

1. Runs `studio_setup.sh` (clones repos, installs deps)
2. Runs `prepare.py` (downloads data shards, trains BPE tokenizer — ~2 min)
3. Runs `train.py` (5-minute training budget — GPT with Flash Attention 3)
4. Reports `val_bpb` (validation bits per byte) and peak VRAM

## Prerequisites

```bash
# Ensure credentials are configured
art init

# Required env vars (set in .env or shell):
#   ART_TEAM_REPO           — this repo's HTTPS clone URL
#   ART_AUTORESEARCH_REPO   — karpathy/autoresearch HTTPS clone URL
#   GH_TOKEN                — GitHub token with repo access
```

## Usage

```bash
# Preview (no Studios launched)
art launch --file sample-experiments/single-runner/sessions.yaml --dry-run

# Launch for real
art launch --file sample-experiments/single-runner/sessions.yaml

# Monitor progress
art health --watch

# Clean up when done
art teardown --delete
```

## Expected output

After ~10-12 minutes, the Studio log should contain:

```
========================================
  SMOKE TEST RESULTS
========================================

  val_bpb: <some value like 1.42>
  peak_vram_mb: <some value like 12000>

========================================
  SMOKE TEST PASSED
========================================
```

## Cost estimate

| Phase | Duration | Machine |
|-------|----------|---------|
| Studio startup | ~60-90s | H100 |
| `studio_setup.sh` | ~2-3 min | H100 |
| `prepare.py` | ~2 min | H100 |
| `train.py` | 5 min | H100 |
| **Total** | **~10-12 min** | **1× H100** |

## What this validates

- H100 Studio provisions correctly via `art launch --file`
- `studio_setup.sh` installs uv, clones both repos, syncs deps
- PyTorch + CUDA + Flash Attention 3 (native Hopper kernel) load correctly
- `prepare.py` downloads data and trains tokenizer
- `train.py` completes a full training cycle and produces `val_bpb`
- The full infra pipeline works: session YAML → Studio → setup → train → metrics

## Files

| File | Purpose |
|------|---------|
| `sessions.yaml` | Session config for `art launch --file` |
| `run_autoresearch.sh` | Script that runs inside the Studio after setup |
