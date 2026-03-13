"""E2E test fixtures — Lightning AI Studio lifecycle management.

Fixtures create two CPU Studios at session scope (shared across all e2e tests)
and guarantee teardown via try/finally.  Studio startup takes ~60s, so
session-scoping amortises the cost across all tests.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

import pytest
import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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
    shared_data_dir: str  # "/teamspace/data"

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


def _load_e2e_config() -> dict:
    """Load the e2e-specific config.yaml."""
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _delete_studio_safe(studio: object, name: str) -> None:
    """Best-effort delete — log but don't raise on failure."""
    try:
        logger.info(f"Tearing down Studio: {name}")
        studio.delete()
        logger.info(f"Deleted Studio: {name}")
    except Exception:
        logger.exception(f"Failed to delete Studio {name} — manual cleanup may be needed")


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

    teamspace = e2e_config["teamspace"]
    name_a = f"e2etest-{e2e_run_id}-0"
    name_b = f"e2etest-{e2e_run_id}-1"
    shared_data_dir = e2e_config["shared_storage"]["data_dir"]

    studio_a = None
    studio_b = None

    try:
        # ── Create & start Studio A ─────────────────────────────────
        logger.info(f"Creating Studio A: {name_a} in teamspace {teamspace}")
        studio_a = Studio(name=name_a, teamspace=teamspace, create_ok=True)
        studio_a.start(machine=Machine.CPU)
        logger.info(f"Studio A started: {name_a} — status: {studio_a.status}")

        # ── Create & start Studio B ─────────────────────────────────
        logger.info(f"Creating Studio B: {name_b} in teamspace {teamspace}")
        studio_b = Studio(name=name_b, teamspace=teamspace, create_ok=True)
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
            shared_data_dir=shared_data_dir,
        )

    finally:
        # ── Unconditional cleanup ───────────────────────────────────
        # Runs even if Studio creation fails, tests fail, or
        # KeyboardInterrupt is raised.
        if studio_a is not None:
            _delete_studio_safe(studio_a, name_a)
        if studio_b is not None:
            _delete_studio_safe(studio_b, name_b)
