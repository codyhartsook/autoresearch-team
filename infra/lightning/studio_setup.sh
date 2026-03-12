#!/usr/bin/env bash
# studio_setup.sh — Idempotent environment provisioning for Lightning Studios.
#
# Runs inside each Studio (runner or reviewer).  Every operation is
# check-before-act so the first Studio to run creates shared resources
# and subsequent Studios skip gracefully.
#
# Usage:  bash studio_setup.sh
# ---------------------------------------------------------------
set -euo pipefail

DATA_DIR="/teamspace/data"
CACHE_DIR="${DATA_DIR}/.cache/autoresearch"
TEAM_REPO="https://github.com/codyhartsook/autoresearch-team.git"
TEAM_BRANCH="main"
AUTORESEARCH_REPO="https://github.com/karpathy/autoresearch.git"
WORKSPACE="/teamspace/studios/this_studio"

echo "=== Autoresearch Studio Setup ==="
echo "Studio: $(hostname)"
echo "Date:   $(date -u)"
echo ""

# ---------------------------------------------------------------
# 1. Install uv (skip if present)
# ---------------------------------------------------------------
if command -v uv &>/dev/null; then
    echo "[✓] uv already installed ($(uv --version))"
else
    echo "[…] Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    echo "[✓] uv installed ($(uv --version))"
fi

# ---------------------------------------------------------------
# 2. Install Claude Code CLI (skip if present)
# ---------------------------------------------------------------
if command -v claude &>/dev/null; then
    echo "[✓] claude CLI already installed ($(claude --version 2>/dev/null || echo 'unknown'))"
else
    echo "[…] Installing Claude Code CLI..."
    if command -v npm &>/dev/null; then
        npm install -g @anthropic-ai/claude-code
        echo "[✓] claude CLI installed"
    else
        echo "[!] npm not found — skipping Claude Code CLI install."
        echo "    Install Node.js first, then: npm install -g @anthropic-ai/claude-code"
    fi
fi

# ---------------------------------------------------------------
# 3. Clone autoresearch-team repo (skip if present)
# ---------------------------------------------------------------
TEAM_DIR="${WORKSPACE}/autoresearch-team"
if [ -d "${TEAM_DIR}/.git" ]; then
    echo "[✓] autoresearch-team already cloned at ${TEAM_DIR}"
    cd "${TEAM_DIR}" && git pull --ff-only origin "${TEAM_BRANCH}" 2>/dev/null || true
else
    echo "[…] Cloning autoresearch-team..."
    git clone --branch "${TEAM_BRANCH}" "${TEAM_REPO}" "${TEAM_DIR}"
    echo "[✓] Cloned autoresearch-team"
fi

# Install autoresearch-team dependencies
cd "${TEAM_DIR}"
echo "[…] Syncing autoresearch-team dependencies..."
uv sync
echo "[✓] autoresearch-team deps synced"

# ---------------------------------------------------------------
# 4. Clone karpathy/autoresearch repo (skip if present)
# ---------------------------------------------------------------
AUTORESEARCH_DIR="${WORKSPACE}/autoresearch"
if [ -d "${AUTORESEARCH_DIR}/.git" ]; then
    echo "[✓] autoresearch already cloned at ${AUTORESEARCH_DIR}"
    cd "${AUTORESEARCH_DIR}" && git pull --ff-only origin main 2>/dev/null || true
else
    echo "[…] Cloning karpathy/autoresearch..."
    git clone "${AUTORESEARCH_REPO}" "${AUTORESEARCH_DIR}"
    echo "[✓] Cloned autoresearch"
fi

# Install autoresearch dependencies (if pyproject.toml or requirements.txt exists)
cd "${AUTORESEARCH_DIR}"
if [ -f "pyproject.toml" ]; then
    echo "[…] Syncing autoresearch dependencies..."
    uv sync
    echo "[✓] autoresearch deps synced"
elif [ -f "requirements.txt" ]; then
    echo "[…] Installing autoresearch requirements..."
    uv pip install -r requirements.txt
    echo "[✓] autoresearch requirements installed"
fi

# ---------------------------------------------------------------
# 5. Initialize shared knowledge store (first Studio creates, rest skip)
# ---------------------------------------------------------------
echo "[…] Ensuring shared knowledge store directories exist..."

mkdir -p "${DATA_DIR}/claims"
mkdir -p "${DATA_DIR}/rounds"
mkdir -p "${CACHE_DIR}"

# Create empty JSONL files if they don't exist (first-writer wins)
for f in leaderboard.jsonl dead_ends.jsonl insights.jsonl; do
    filepath="${DATA_DIR}/${f}"
    if [ ! -f "${filepath}" ]; then
        touch "${filepath}"
        echo "[✓] Created ${filepath}"
    else
        echo "[✓] ${filepath} already exists"
    fi
done

# Create empty human directive placeholder
if [ ! -f "${DATA_DIR}/human_directive.json" ]; then
    echo '{}' > "${DATA_DIR}/human_directive.json"
    echo "[✓] Created ${DATA_DIR}/human_directive.json"
fi

echo ""
echo "=== Setup Complete ==="
echo "  Data dir:    ${DATA_DIR}"
echo "  Team repo:   ${TEAM_DIR}"
echo "  Autoresearch: ${AUTORESEARCH_DIR}"
echo "  Cache:       ${CACHE_DIR}"
