"""E2E test fixtures — Lightning AI Studio lifecycle management.

Fixtures create two CPU Studios at session scope (shared across all e2e tests)
and guarantee teardown via try/finally.  Studio startup takes ~60s, so
session-scoping amortises the cost across all tests.

Git coordination fixtures manage a remote GitHub repo — either an existing
one supplied via config, or a temporary one created/deleted per session.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv

import pytest

from infra.lightning.config import load_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "config_e2e.yaml"

# Load .env from repo root before any env lookups
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_RUN_ID = os.environ.get("E2E_RUN_ID", uuid.uuid4().hex[:8])
_CONFIG_PATH = Path(__file__).parent / "config_e2e.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class StudioPair:
    """Container for two live Studios and their metadata."""

    studio_a: object  # lightning_sdk.Studio
    studio_b: object  # lightning_sdk.Studio
    name_a: str
    name_b: str
    teamspace: str
    run_id: str

    def run_in_a(self, *commands: str) -> str:
        """Run command(s) in Studio A, return stdout."""
        return self.studio_a.run(*commands)

    def run_in_b(self, *commands: str) -> str:
        """Run command(s) in Studio B, return stdout."""
        return self.studio_b.run(*commands)

    def run_in_a_with_exit_code(self, *commands: str) -> tuple[str, int]:
        """Run command(s) in Studio A, return (stdout, exit_code)."""
        return self.studio_a.run_with_exit_code(*commands)

    def run_in_b_with_exit_code(self, *commands: str) -> tuple[str, int]:
        """Run command(s) in Studio B, return (stdout, exit_code)."""
        return self.studio_b.run_with_exit_code(*commands)


@dataclass
class GitRemote:
    """A remote GitHub repo available to both Studios for coordination tests.

    If ``created`` is True, the fixture that produced this will delete the
    repo during teardown.
    """

    clone_url: str          # HTTPS clone URL (with embedded token for push)
    public_url: str         # HTTPS clone URL without credentials (for display)
    owner: str              # GitHub user or org
    repo_name: str          # Short repo name
    gh_token: str           # Token used for push operations
    created: bool = False   # True if we created this repo (will be deleted)

    @property
    def authenticated_url(self) -> str:
        """HTTPS URL with token embedded for git push from Studios."""
        return f"https://x-access-token:{self.gh_token}@github.com/{self.owner}/{self.repo_name}.git"


def _load_e2e_config() -> dict:
    """Load the e2e-specific config through the standard config loader."""
    return load_config(_CONFIG_PATH)


def _delete_studio_safe(studio: object, name: str) -> None:
    """Best-effort delete — log but don't raise on failure."""
    try:
        logger.info(f"Tearing down Studio: {name}")
        studio.delete()
        logger.info(f"Deleted Studio: {name}")
    except Exception:
        logger.exception(f"Failed to delete Studio {name} — manual cleanup may be needed")


def _gh_token() -> str:
    """Resolve GitHub token from environment."""
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def _create_temp_repo(owner: str, run_id: str) -> tuple[str, str]:
    """Create a temporary private GitHub repo via ``gh api``.

    Returns (owner, repo_name).  Raises on failure.
    """
    repo_name = f"e2e-test-{run_id}"
    logger.info(f"Creating temporary GitHub repo: {owner}/{repo_name}")
    result = subprocess.run(
        [
            "gh", "api", "user/repos",
            "-X", "POST",
            "-f", f"name={repo_name}",
            "-f", "private=true",
            "-f", "auto_init=true",
            "-f", "description=Temporary repo for autoresearch e2e tests — safe to delete",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create GitHub repo {owner}/{repo_name}: {result.stderr}"
        )
    resp = json.loads(result.stdout)
    actual_owner = resp.get("owner", {}).get("login", owner)
    logger.info(f"Created temporary repo: {actual_owner}/{repo_name}")
    return actual_owner, repo_name


def _delete_temp_repo(owner: str, repo_name: str) -> None:
    """Delete a temporary GitHub repo via ``gh api``.  Best-effort."""
    try:
        logger.info(f"Deleting temporary GitHub repo: {owner}/{repo_name}")
        result = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo_name}", "-X", "DELETE"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info(f"Deleted temporary repo: {owner}/{repo_name}")
        else:
            logger.warning(f"Failed to delete repo {owner}/{repo_name}: {result.stderr}")
    except Exception:
        logger.exception(f"Error deleting repo {owner}/{repo_name} — manual cleanup needed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def e2e_config() -> dict:
    """Load and return the e2e test configuration."""
    return _load_e2e_config()


@pytest.fixture(scope="session")
def e2e_run_id() -> str:
    """Unique identifier for this test run (for Studio name uniqueness)."""
    return _RUN_ID


@pytest.fixture(scope="session")
def git_remote(e2e_config: dict, e2e_run_id: str) -> Generator[GitRemote, None, None]:
    """Provide a GitHub remote repo for cross-studio git tests.

    Behaviour depends on config:

    - **Existing repo** (``test_repo.url`` is set): wraps it in a GitRemote.
      Push tests require ``GH_TOKEN`` with push access.
    - **Auto-create** (``test_repo.url`` is empty): creates a temporary private
      repo via ``gh api``, yields it, then deletes it in the finally block.
      Requires ``GH_TOKEN`` with ``repo`` scope.

    Overridable via env vars:
    - ``E2E_TEST_REPO_URL`` — force an existing repo URL
    - ``GH_TOKEN`` / ``GITHUB_TOKEN`` — GitHub auth for push + repo management
    """
    token = _gh_token()
    repo_cfg = e2e_config.get("test_repo", {})
    explicit_url = os.environ.get("E2E_TEST_REPO_URL") or repo_cfg.get("url", "")
    github_owner = repo_cfg.get("github_owner", "")

    if explicit_url:
        # ── Existing repo mode ──────────────────────────────────────
        # Parse owner/repo from URL like https://github.com/owner/repo.git
        parts = explicit_url.rstrip("/").rstrip(".git").split("/")
        owner = parts[-2] if len(parts) >= 2 else github_owner
        repo_name = parts[-1] if parts else "unknown"
        logger.info(f"Using existing repo for git tests: {explicit_url}")
        yield GitRemote(
            clone_url=explicit_url,
            public_url=explicit_url,
            owner=owner,
            repo_name=repo_name,
            gh_token=token,
            created=False,
        )
        return

    # ── Auto-create mode ────────────────────────────────────────
    if not token:
        pytest.skip(
            "Git coordination tests need either test_repo.url in config "
            "or GH_TOKEN env var to auto-create a temporary repo"
        )

    if not github_owner:
        # Try to get from gh cli
        try:
            result = subprocess.run(
                ["gh", "api", "user", "-q", ".login"],
                capture_output=True, text=True, timeout=10,
            )
            github_owner = result.stdout.strip()
        except Exception:
            pass
    if not github_owner:
        pytest.skip("Cannot determine GitHub owner — set test_repo.github_owner in config")

    owner, repo_name = _create_temp_repo(github_owner, e2e_run_id)
    try:
        public_url = f"https://github.com/{owner}/{repo_name}.git"
        yield GitRemote(
            clone_url=f"https://x-access-token:{token}@github.com/{owner}/{repo_name}.git",
            public_url=public_url,
            owner=owner,
            repo_name=repo_name,
            gh_token=token,
            created=True,
        )
    finally:
        _delete_temp_repo(owner, repo_name)


@pytest.fixture(scope="session")
def studio_pair(e2e_config: dict, e2e_run_id: str) -> Generator[StudioPair, None, None]:
    """Create two CPU Studios, yield them, then unconditionally tear down.

    This is the primary fixture.  It:
    1. Creates Studio A and Studio B with unique names
    2. Starts both on Machine.CPU
    3. Waits for both to reach Running status
    4. Yields a StudioPair for tests to use
    5. Deletes both Studios in the finally block (even on failure)

    Scope is ``session`` so Studios are reused across all e2e tests.
    Total startup cost: ~60-120s (paid once).
    """
    from lightning_sdk import Machine, Studio

    from infra.lightning.config import studio_kwargs

    teamspace = e2e_config["teamspace"]
    name_a = f"e2etest-{e2e_run_id}-0"
    name_b = f"e2etest-{e2e_run_id}-1"

    studio_a = None
    studio_b = None

    try:
        # ── Create & start Studio A ─────────────────────────────────
        logger.info(f"Creating Studio A: {name_a} in teamspace {teamspace}")
        studio_a = Studio(**studio_kwargs(e2e_config, name_a), create_ok=True)
        studio_a.start(machine=Machine.CPU)
        logger.info(f"Studio A started: {name_a} — status: {studio_a.status}")

        # ── Create & start Studio B ─────────────────────────────────
        logger.info(f"Creating Studio B: {name_b} in teamspace {teamspace}")
        studio_b = Studio(**studio_kwargs(e2e_config, name_b), create_ok=True)
        studio_b.start(machine=Machine.CPU)
        logger.info(f"Studio B started: {name_b} — status: {studio_b.status}")

        # ── Verify both are running ─────────────────────────────────
        for label, studio in [("A", studio_a), ("B", studio_b)]:
            status = str(studio.status)
            assert "running" in status.lower(), (
                f"Studio {label} not running after start(). Status: {status}"
            )

        yield StudioPair(
            studio_a=studio_a,
            studio_b=studio_b,
            name_a=name_a,
            name_b=name_b,
            teamspace=teamspace,
            run_id=e2e_run_id,
        )

    finally:
        # ── Unconditional cleanup ───────────────────────────────────
        if studio_a is not None:
            _delete_studio_safe(studio_a, name_a)
        if studio_b is not None:
            _delete_studio_safe(studio_b, name_b)
