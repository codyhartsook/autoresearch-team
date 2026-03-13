#!/usr/bin/env bash
# studio_setup.sh — Idempotent environment provisioning for Lightning Studios.
#
# Installs tools and sets up the workspace. Repo URLs and branches are
# passed in via environment variables by the caller (launch.py), not
# hardcoded here — keeping the infra layer free of architecture knowledge.
#
# Required env vars:
#   ART_TEAM_REPO       — autoresearch-team repo URL
#   ART_TEAM_BRANCH     — branch to clone (default: main)
#   ART_AUTORESEARCH_REPO — karpathy/autoresearch repo URL
#
# Usage:  bash studio_setup.sh
# ---------------------------------------------------------------
set -euo pipefail

TEAM_REPO="${ART_TEAM_REPO:?ART_TEAM_REPO env var is required}"
TEAM_BRANCH="${ART_TEAM_BRANCH:-main}"
AUTORESEARCH_REPO="${ART_AUTORESEARCH_REPO:?ART_AUTORESEARCH_REPO env var is required}"
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

echo ""
echo "=== Setup Complete ==="
echo "  Team repo:    ${TEAM_DIR}"
echo "  Autoresearch: ${AUTORESEARCH_DIR}"
