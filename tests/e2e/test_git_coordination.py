"""Test that sessions can execute scripts requiring network and git access.

These are infra provider tests — they verify the provider contract:
- Sessions can run opaque scripts
- Scripts have network access (can reach GitHub)
- Scripts have git available
- Environment variables (GH_TOKEN) are accessible inside sessions

The test hands each session a self-contained script and checks the output.
The infra layer doesn't know or care what the script does internally.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Ensure .env is loaded before checking for tokens at import time
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(300)]

_has_gh_token = bool(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
requires_token = pytest.mark.skipif(
    not _has_gh_token,
    reason="Requires GH_TOKEN or GITHUB_TOKEN env var",
)


def _clone_script(repo_url: str) -> str:
    """Script that clones a repo and prints a success marker with the HEAD sha."""
    return f"""\
#!/usr/bin/env bash
set -euo pipefail
WORKDIR=$(mktemp -d)
cd "$WORKDIR"
git clone --depth 1 {repo_url} repo 2>&1
cd repo
SHA=$(git rev-parse HEAD)
echo "CLONE_OK sha=$SHA"
rm -rf "$WORKDIR"
"""


def _push_script(auth_url: str, branch: str, marker: str) -> str:
    """Script that clones, creates a branch, commits a file, and pushes."""
    return f"""\
#!/usr/bin/env bash
set -euo pipefail
WORKDIR=$(mktemp -d)
cd "$WORKDIR"
git clone {auth_url} repo 2>&1
cd repo
git config user.email 'e2e@test.local'
git config user.name 'E2E Test'
git checkout -b {branch}
echo '{marker}' > payload.txt
git add payload.txt
git commit -m 'e2e: {marker}' 2>&1
git push origin {branch} 2>&1
echo "PUSH_OK branch={branch}"
rm -rf "$WORKDIR"
"""


def _fetch_script(auth_url: str, branch: str) -> str:
    """Script that clones, fetches a branch, and prints the payload file."""
    return f"""\
#!/usr/bin/env bash
set -euo pipefail
WORKDIR=$(mktemp -d)
cd "$WORKDIR"
git clone {auth_url} repo 2>&1
cd repo
git fetch origin {branch} 2>&1
git checkout {branch}
CONTENT=$(cat payload.txt)
echo "FETCH_OK content=$CONTENT"
rm -rf "$WORKDIR"
"""


def _cleanup_branch_script(auth_url: str, branch: str) -> str:
    """Script that deletes a remote branch."""
    return f"""\
#!/usr/bin/env bash
WORKDIR=$(mktemp -d)
cd "$WORKDIR"
git clone {auth_url} repo 2>&1
cd repo
git push origin --delete {branch} 2>&1 || true
rm -rf "$WORKDIR"
"""


class TestNetworkAccess:
    """Verify sessions can reach the network — the provider contract requires it.

    Tests hand opaque scripts to sessions.  The scripts happen to use git
    to verify network access, but the infra layer doesn't know that.
    """

    def test_session_a_can_clone(self, studio_pair, git_remote):
        """Session A executes a clone script and reports success."""
        script = _clone_script(git_remote.public_url)
        output = studio_pair.run_in_a(script)
        assert "CLONE_OK" in output

    def test_session_b_can_clone(self, studio_pair, git_remote):
        """Session B executes the same clone script."""
        script = _clone_script(git_remote.public_url)
        output = studio_pair.run_in_b(script)
        assert "CLONE_OK" in output

    def test_both_sessions_see_same_state(self, studio_pair, git_remote):
        """Both sessions running the same script get the same result."""
        script = _clone_script(git_remote.public_url)
        output_a = studio_pair.run_in_a(script)
        output_b = studio_pair.run_in_b(script)

        # Extract sha from "CLONE_OK sha=abc123"
        sha_a = [l for l in output_a.splitlines() if "CLONE_OK" in l][0].split("sha=")[1]
        sha_b = [l for l in output_b.splitlines() if "CLONE_OK" in l][0].split("sha=")[1]
        assert sha_a == sha_b, f"State mismatch: A={sha_a}, B={sha_b}"


@requires_token
class TestScriptWithCredentials:
    """Verify sessions can execute scripts that use injected credentials.

    The provider contract says credentials (env vars) must be accessible
    inside sessions.  These tests verify that by running scripts that
    require GH_TOKEN to authenticate with GitHub.
    """

    def test_push_script_from_a(self, studio_pair, git_remote):
        """Session A runs a script that pushes to a remote."""
        branch = f"e2e-push-a-{studio_pair.run_id}"
        marker = f"from-a-{studio_pair.run_id}"
        auth_url = git_remote.authenticated_url

        output = studio_pair.run_in_a(_push_script(auth_url, branch, marker))
        assert "PUSH_OK" in output
        assert branch in output

        # Cleanup
        try:
            studio_pair.run_in_a(_cleanup_branch_script(auth_url, branch))
        except Exception:
            pass

    def test_push_from_a_fetch_from_b(self, studio_pair, git_remote):
        """Session A pushes via script; Session B fetches via script."""
        branch = f"e2e-ab-{studio_pair.run_id}"
        marker = f"a-to-b-{studio_pair.run_id}"
        auth_url = git_remote.authenticated_url

        # Session A pushes
        push_output = studio_pair.run_in_a(_push_script(auth_url, branch, marker))
        assert "PUSH_OK" in push_output

        # Session B fetches
        fetch_output = studio_pair.run_in_b(_fetch_script(auth_url, branch))
        assert "FETCH_OK" in fetch_output
        assert marker in fetch_output

        # Cleanup
        try:
            studio_pair.run_in_a(_cleanup_branch_script(auth_url, branch))
        except Exception:
            pass

    def test_push_from_b_fetch_from_a(self, studio_pair, git_remote):
        """Reverse direction — Session B pushes, Session A fetches."""
        branch = f"e2e-ba-{studio_pair.run_id}"
        marker = f"b-to-a-{studio_pair.run_id}"
        auth_url = git_remote.authenticated_url

        # Session B pushes
        push_output = studio_pair.run_in_b(_push_script(auth_url, branch, marker))
        assert "PUSH_OK" in push_output

        # Session A fetches
        fetch_output = studio_pair.run_in_a(_fetch_script(auth_url, branch))
        assert "FETCH_OK" in fetch_output
        assert marker in fetch_output

        # Cleanup
        try:
            studio_pair.run_in_b(_cleanup_branch_script(auth_url, branch))
        except Exception:
            pass
