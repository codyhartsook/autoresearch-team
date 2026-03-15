#!/usr/bin/env bash
# run_autoresearch.sh — Run a single autoresearch training cycle on GPU.
#
# Expects studio_setup.sh to have already run (repos cloned, deps installed).
# This script:
#   1. Validates the GPU environment
#   2. Runs data preparation (prepare.py — ~2 min)
#   3. Runs training (train.py — 5 min wall-clock budget)
#   4. Extracts and reports val_bpb + peak VRAM
#
# Telemetry: writes JSONL events to /teamspace/studios/this_studio/metrics.jsonl
# for consumption by `art logs`. See infra/lightning/telemetry.py.
#
# Exit codes:
#   0 — training completed and val_bpb was produced
#   1 — something failed (missing repo, no GPU, training error)
# ---------------------------------------------------------------
set -euo pipefail

WORKSPACE="/teamspace/studios/this_studio"
AUTORESEARCH_DIR="${WORKSPACE}/autoresearch"
LOG_FILE="${WORKSPACE}/smoke-run.log"
METRICS_FILE="${WORKSPACE}/metrics.jsonl"

# Track current phase for the error trap
CURRENT_PHASE="init"

# ---------------------------------------------------------------
# Telemetry helper — append a JSONL event to metrics.jsonl
# ---------------------------------------------------------------
# Usage: write_event <phase> <status> [key=value ...]
#
# All values are strings. No JSON library needed — just careful quoting.
# The Python reader (telemetry.py) coerces numeric fields on display.
write_event() {
    local phase="$1" status="$2"
    shift 2

    # Build extra fields from key=value args
    local extras=""
    for kv in "$@"; do
        local key="${kv%%=*}"
        local val="${kv#*=}"
        # Escape double quotes and backslashes in values
        val="${val//\\/\\\\}"
        val="${val//\"/\\\"}"
        extras="${extras}, \"${key}\": \"${val}\""
    done

    echo "{\"ts\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"host\": \"$(hostname)\", \"phase\": \"${phase}\", \"status\": \"${status}\"${extras}}" >> "${METRICS_FILE}"
}

# ---------------------------------------------------------------
# Error trap — emit a failed event on any error
# ---------------------------------------------------------------
on_error() {
    local exit_code=$?
    write_event "${CURRENT_PHASE}" "failed" "exit_code=${exit_code}"
    echo ""
    echo "[FAIL] Script failed during phase: ${CURRENT_PHASE} (exit code: ${exit_code})"
    exit "${exit_code}"
}
trap on_error ERR

# ---------------------------------------------------------------
# Header
# ---------------------------------------------------------------
echo "=== Autoresearch Single-Runner Smoke Test ==="
echo "Host:   $(hostname)"
echo "Date:   $(date -u)"
echo ""

# ---------------------------------------------------------------
# 0. Validate environment
# ---------------------------------------------------------------
CURRENT_PHASE="setup"
echo "[0/3] Validating environment..."

if [ ! -d "${AUTORESEARCH_DIR}" ]; then
    echo "[FAIL] autoresearch repo not found at ${AUTORESEARCH_DIR}"
    echo "       Did studio_setup.sh run? Check launch config: run_setup: true"
    exit 1
fi

if ! command -v nvidia-smi &>/dev/null; then
    echo "[FAIL] nvidia-smi not found — no GPU driver detected"
    exit 1
fi

GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "unknown")
echo "GPU:    ${GPU_INFO}"

if ! command -v uv &>/dev/null; then
    echo "[FAIL] uv not found — studio_setup.sh should have installed it"
    exit 1
fi

UV_VERSION=$(uv --version)
echo "uv:     ${UV_VERSION}"
echo "[OK] Environment validated"
echo ""

write_event "setup" "ok" "gpu=${GPU_INFO}" "uv_version=${UV_VERSION}"

# ---------------------------------------------------------------
# 1. Data preparation (~2 min)
# ---------------------------------------------------------------
CURRENT_PHASE="prepare"
cd "${AUTORESEARCH_DIR}"

echo "[1/3] Running data preparation (prepare.py)..."
echo "      This downloads data shards and trains the BPE tokenizer."
echo "      Expected time: ~2 minutes."
echo ""

write_event "prepare" "started"
uv run prepare.py 2>&1 | tee -a "${LOG_FILE}"
write_event "prepare" "ok"

echo ""
echo "[OK] Data preparation complete"
echo ""

# ---------------------------------------------------------------
# 2. Training (5 min wall-clock budget)
# ---------------------------------------------------------------
CURRENT_PHASE="training"

# The default DEVICE_BATCH_SIZE=128 in train.py OOMs on GPUs with <80GB VRAM.
# Patch it to a safe value for the L40S (46GB). This uses sed to edit the
# constant in-place — autoresearch uses top-level constants, not CLI args.
# On H100 (80GB) this patch is unnecessary but harmless.
VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
if [ -n "${VRAM_MB}" ] && [ "${VRAM_MB}" -lt 65000 ]; then
    echo "[INFO] GPU VRAM (${VRAM_MB} MiB) < 65 GiB — reducing DEVICE_BATCH_SIZE to 64"
    sed -i 's/^DEVICE_BATCH_SIZE = 128/DEVICE_BATCH_SIZE = 64/' train.py
    write_event "training" "patched" "DEVICE_BATCH_SIZE=64" "vram_mb=${VRAM_MB}"
fi

echo "[2/3] Running training (train.py — 5 min budget)..."
echo "      Model: GPT with RoPE, Flash Attention 3, MuonAdamW optimizer"
echo "      Metric: val_bpb (validation bits per byte — lower is better)"
echo ""

write_event "training" "started"

# Run training, tee to log, and emit periodic JSONL events for step-level metrics.
# Uses a simple grep+sed pipeline instead of gawk capture groups for portability.
uv run train.py 2>&1 | tee -a "${LOG_FILE}" | while IFS= read -r line; do
    echo "${line}"
    # Detect step progress lines — autoresearch train.py prints lines like:
    #   step N | loss X.XXX | ...
    # Extract step number and loss value using portable tools.
    step=$(echo "${line}" | sed -n 's/.*step[= ]*\([0-9]*\).*/\1/p')
    loss=$(echo "${line}" | sed -n 's/.*loss[= :]*\([0-9]*\.[0-9]*\).*/\1/p')
    if [ -n "${step}" ] && [ -n "${loss}" ]; then
        write_event "training" "running" "step=${step}" "loss=${loss}"
    fi
done

echo ""
echo "[OK] Training complete"
echo ""

# ---------------------------------------------------------------
# 3. Extract and report metrics
# ---------------------------------------------------------------
CURRENT_PHASE="results"
echo "[3/3] Extracting metrics from log..."

VAL_BPB=$(grep "^val_bpb:" "${LOG_FILE}" | tail -1 || true)
VRAM=$(grep "^peak_vram_mb:" "${LOG_FILE}" | tail -1 || true)

# Extract just the numeric values for the telemetry event
VAL_BPB_NUM=$(echo "${VAL_BPB}" | sed 's/^val_bpb:[[:space:]]*//' || true)
VRAM_NUM=$(echo "${VRAM}" | sed 's/^peak_vram_mb:[[:space:]]*//' || true)

# Emit the final training result event
write_event "training" "ok" "val_bpb=${VAL_BPB_NUM}" "peak_vram_mb=${VRAM_NUM}"

echo ""
echo "========================================"
echo "  SMOKE TEST RESULTS"
echo "========================================"
echo ""

if [ -n "${VAL_BPB}" ]; then
    echo "  ${VAL_BPB}"
else
    echo "  val_bpb: NOT FOUND (check log for errors)"
fi

if [ -n "${VRAM}" ]; then
    echo "  ${VRAM}"
else
    echo "  peak_vram_mb: NOT FOUND"
fi

echo ""
echo "  Full log:    ${LOG_FILE}"
echo "  Telemetry:   ${METRICS_FILE}"
echo ""

# Determine exit status based on whether val_bpb was produced
if [ -n "${VAL_BPB}" ]; then
    echo "========================================"
    echo "  SMOKE TEST PASSED"
    echo "========================================"
    exit 0
else
    echo "========================================"
    echo "  SMOKE TEST FAILED — no val_bpb output"
    echo "========================================"
    exit 1
fi
