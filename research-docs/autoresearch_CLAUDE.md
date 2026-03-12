# CLAUDE.md — Autoresearch

## Project Overview

Autoresearch is an autonomous LLM pretraining research framework. An AI agent iteratively modifies a training script, runs a 5-minute training experiment, evaluates the result, and keeps or discards the change — looping indefinitely. The goal is to minimize **val_bpb** (validation bits per byte).

Origin: simplified single-GPU implementation of [nanochat](https://github.com/karpathy/nanochat) by @karpathy.

## Repository Structure

```
prepare.py      — Constants, data prep, tokenizer, dataloader, evaluation (DO NOT MODIFY)
train.py        — GPT model, MuonAdamW optimizer, training loop (AGENT MODIFIES THIS)
program.md      — Agent instructions / experiment protocol (HUMAN MODIFIES THIS)
pyproject.toml  — Dependencies (uv-managed)
analysis.ipynb  — Experiment analysis notebook
```

## Commands

```bash
# Install dependencies
uv sync

# One-time data prep (~2 min) — downloads shards + trains BPE tokenizer
uv run prepare.py

# Run a training experiment (always exactly 5 minutes of training time)
uv run train.py

# Run experiment with output capture (standard for autonomous loop)
uv run train.py > run.log 2>&1

# Extract key metrics from a run
grep "^val_bpb:\|^peak_vram_mb:" run.log
```

## Key Constants (from prepare.py — fixed, never change)

- `MAX_SEQ_LEN = 2048` — context length
- `TIME_BUDGET = 300` — 5-minute wall-clock training budget
- `EVAL_TOKENS = 40 * 524288` — tokens used for validation eval
- `VOCAB_SIZE = 8192` — BPE vocabulary size
- Data cached at `~/.cache/autoresearch/`

## Architecture Overview (train.py)

**Model**: GPT with RoPE, RMS norm, Flash Attention 3, sliding window attention (SSSL pattern), value embeddings (ResFormer-style), per-layer residual/skip lambdas, logit soft-capping at 15.

**Key hyperparameters** (top-level constants in train.py):
- `DEPTH = 8` — number of transformer layers (primary model size knob)
- `ASPECT_RATIO = 64` — model_dim = depth * aspect_ratio, rounded up to HEAD_DIM multiple
- `HEAD_DIM = 128` — attention head dimension
- `WINDOW_PATTERN = "SSSL"` — S=half-context sliding window, L=full context (last layer always L)
- `TOTAL_BATCH_SIZE = 2**19` (~524K tokens per step)
- `DEVICE_BATCH_SIZE = 128` — micro-batch size (reduce if OOM)
- `MATRIX_LR = 0.04` — Muon LR for 2D weight matrices
- `EMBEDDING_LR = 0.6` — AdamW LR for token embeddings
- `UNEMBEDDING_LR = 0.004` — AdamW LR for lm_head
- `WARMDOWN_RATIO = 0.5` — cosine decay over last 50% of training
- `WEIGHT_DECAY = 0.2` — cautious weight decay for Muon params

**Optimizer**: `MuonAdamW` — Muon (Newton-Schulz polar decomposition) for 2D matrix params, AdamW for embeddings/scalars. LRs scale with `1/sqrt(d_model/768)`.

**Activation**: `ReLU²` (squared ReLU) in MLP.

**MLP**: Standard up-projection (4x) → ReLU² → down-projection.

## Experiment Protocol (from program.md)

1. Create branch `autoresearch/<tag>` from master
2. Establish baseline by running unmodified train.py
3. Loop: modify train.py → git commit → run → extract metrics → keep/discard → repeat
4. Log results to `results.tsv` (tab-separated, untracked by git):
   ```
   commit	val_bpb	memory_gb	status	description
   ```
5. If val_bpb improves: keep commit and advance branch
6. If val_bpb worsens or equals: `git reset` to previous state
7. Never stop — run autonomously until manually interrupted

## Metric

**val_bpb** (validation bits per byte) — lower is better. Computed by `evaluate_bpb()` in prepare.py. Vocab-size independent, so architectural changes are fairly compared.

## Constraints

- Only modify `train.py` — everything else is read-only
- No new dependencies — only what's in pyproject.toml
- Fixed 5-minute training budget — experiments compared on equal time
- VRAM: some increase OK for meaningful val_bpb gains, but no dramatic blowup
- Simplicity: prefer simpler code at equal or better val_bpb

## Dependencies

Python ≥3.10, managed by [uv](https://docs.astral.sh/uv/):
- `torch==2.9.1` (CUDA 12.8)
- `kernels` (Flash Attention 3 — uses varunneal/flash-attention-3 on Hopper, kernels-community/flash-attn3 otherwise)
- `tiktoken`, `rustbpe` (tokenizer)
- `numpy`, `pandas`, `pyarrow` (data handling)
- `matplotlib` (analysis)
- `requests` (data download)

## Code Style

- Single-file design — all model/optimizer/training code lives in train.py
- No CLI flags — hyperparameters are edited as top-level constants
- torch.compile used for model and optimizer kernels (dynamic=False, fullgraph=True)
- bf16 autocast for training, float32 for logits/loss
- GC manually managed (frozen after step 0 to avoid stalls)
