"""Test cross-Studio coordination via a remote git repo.

The autoresearch architecture uses git as the coordination layer between
runners.  Studios are treated as independent remote machines with **no**
shared filesystem — the only way they exchange data is by pushing to and
pulling from a shared GitHub remote.

These tests verify:
1. Both Studios can clone the same remote repo independently
2. Studio A can push a branch; Studio B can fetch and read it
3. Incremental commits from one Studio are visible to the other via pull
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Ensure .env is loaded before checking for tokens at import time
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(300)]

# Working directory inside each Studio for git operations.
# /tmp is per-Studio (not shared) — exactly like separate machines.
_WORK_DIR = "/tmp/e2e-git-test"

# Common git config for commits inside Studios
_GIT_CONFIG = (
    "git config user.email 'e2e@test.local' && "
    "git config user.name 'E2E Test'"
)

# Tests that push to the remote need a GH_TOKEN
_has_gh_token = bool(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
requires_push = pytest.mark.skipif(
    not _has_gh_token,
    reason="Push tests require GH_TOKEN or GITHUB_TOKEN env var",
)


@pytest.fixture(autouse=True)
def clean_work_dir(studio_pair):
    """Ensure a clean working directory in both Studios before/after each test."""
    for run_fn in (studio_pair.run_in_a, studio_pair.run_in_b):
        run_fn(f"rm -rf {_WORK_DIR} && mkdir -p {_WORK_DIR}")
    yield
    for run_fn in (studio_pair.run_in_a, studio_pair.run_in_b):
        try:
            run_fn(f"rm -rf {_WORK_DIR}")
        except Exception:
            pass


class TestGitClone:
    """Both Studios can independently clone the same remote repo.

    These tests are read-only — no GH_TOKEN needed for public repos.
    """

    def test_clone_in_studio_a(self, studio_pair, git_remote):
        """Studio A can clone the remote repo and see commits."""
        output = studio_pair.run_in_a(
            f"cd {_WORK_DIR} && git clone {git_remote.public_url} repo 2>&1 && "
            f"cd repo && git log --oneline -1"
        )
        assert len(output.strip()) > 0

    def test_clone_in_studio_b(self, studio_pair, git_remote):
        """Studio B can clone the remote repo and see commits."""
        output = studio_pair.run_in_b(
            f"cd {_WORK_DIR} && git clone {git_remote.public_url} repo 2>&1 && "
            f"cd repo && git log --oneline -1"
        )
        assert len(output.strip()) > 0

    def test_both_studios_see_same_head(self, studio_pair, git_remote):
        """Both Studios should see the same HEAD after cloning."""
        clone_cmd = (
            f"cd {_WORK_DIR} && git clone {git_remote.public_url} repo 2>&1 && "
            f"cd repo && git rev-parse HEAD"
        )
        output_a = studio_pair.run_in_a(clone_cmd)
        output_b = studio_pair.run_in_b(clone_cmd)

        sha_a = output_a.strip().splitlines()[-1]
        sha_b = output_b.strip().splitlines()[-1]
        assert sha_a == sha_b, f"HEAD mismatch: A={sha_a}, B={sha_b}"

    def test_ls_remote_from_both_studios(self, studio_pair, git_remote):
        """Both Studios can ls-remote — verifying network access to the repo."""
        output_a = studio_pair.run_in_a(
            f"git ls-remote --heads {git_remote.public_url} 2>&1"
        )
        output_b = studio_pair.run_in_b(
            f"git ls-remote --heads {git_remote.public_url} 2>&1"
        )
        assert "refs/heads/" in output_a, f"No refs from Studio A: {output_a}"
        assert "refs/heads/" in output_b, f"No refs from Studio B: {output_b}"


@requires_push
class TestGitPushAndFetch:
    """Studio A pushes to the remote; Studio B fetches — true remote coordination.

    Every test goes through the real GitHub remote. No local bare repos,
    no shared filesystem, no shortcuts. This mirrors how production runners
    on separate machines will coordinate.

    Requires GH_TOKEN with push access to the test repo.
    """

    def test_push_branch_a_fetch_from_b(self, studio_pair, git_remote):
        """Studio A creates a branch with a commit and pushes it.
        Studio B fetches and checks out that branch.
        """
        branch = f"e2e-branch-{studio_pair.run_id}"
        marker = f"written-by-a-{studio_pair.run_id}"
        auth_url = git_remote.authenticated_url

        # Studio A: clone, create branch, commit, push
        studio_pair.run_in_a(
            f"cd {_WORK_DIR} && git clone {auth_url} repo 2>&1 && "
            f"cd repo && {_GIT_CONFIG} && "
            f"git checkout -b {branch} && "
            f"echo '{marker}' > coordination.txt && "
            f"git add coordination.txt && "
            f"git commit -m 'e2e: {marker}' 2>&1 && "
            f"git push origin {branch} 2>&1"
        )

        # Studio B: clone, fetch, checkout the branch, read the file
        output_b = studio_pair.run_in_b(
            f"cd {_WORK_DIR} && git clone {auth_url} repo 2>&1 && "
            f"cd repo && "
            f"git fetch origin {branch} 2>&1 && "
            f"git checkout {branch} && "
            f"cat coordination.txt"
        )
        assert marker in output_b

        # Cleanup: delete remote branch
        try:
            studio_pair.run_in_a(
                f"cd {_WORK_DIR}/repo && git push origin --delete {branch} 2>&1"
            )
        except Exception:
            pass

    def test_push_from_b_pull_from_a(self, studio_pair, git_remote):
        """Studio B pushes a branch; Studio A can pull it (reverse direction)."""
        branch = f"e2e-reverse-{studio_pair.run_id}"
        marker = f"written-by-b-{studio_pair.run_id}"
        auth_url = git_remote.authenticated_url

        # Studio B: clone, branch, commit, push
        studio_pair.run_in_b(
            f"cd {_WORK_DIR} && git clone {auth_url} repo 2>&1 && "
            f"cd repo && {_GIT_CONFIG} && "
            f"git checkout -b {branch} && "
            f"echo '{marker}' > from_b.txt && "
            f"git add from_b.txt && "
            f"git commit -m 'e2e: from B' 2>&1 && "
            f"git push origin {branch} 2>&1"
        )

        # Studio A: clone, fetch, verify
        output_a = studio_pair.run_in_a(
            f"cd {_WORK_DIR} && git clone {auth_url} repo 2>&1 && "
            f"cd repo && "
            f"git fetch origin {branch} 2>&1 && "
            f"git checkout {branch} && "
            f"cat from_b.txt"
        )
        assert marker in output_a

        # Cleanup
        try:
            studio_pair.run_in_b(
                f"cd {_WORK_DIR}/repo && git push origin --delete {branch} 2>&1"
            )
        except Exception:
            pass

    def test_incremental_commits_visible_via_pull(self, studio_pair, git_remote):
        """Studio A pushes two commits incrementally; Studio B sees both via pull."""
        branch = f"e2e-incremental-{studio_pair.run_id}"
        marker_1 = f"first-{studio_pair.run_id}"
        marker_2 = f"second-{studio_pair.run_id}"
        auth_url = git_remote.authenticated_url

        # Studio A: clone, create branch, first commit, push
        studio_pair.run_in_a(
            f"cd {_WORK_DIR} && git clone {auth_url} repo 2>&1 && "
            f"cd repo && {_GIT_CONFIG} && "
            f"git checkout -b {branch} && "
            f"echo '{marker_1}' > data.txt && "
            f"git add data.txt && "
            f"git commit -m 'first' 2>&1 && "
            f"git push origin {branch} 2>&1"
        )

        # Studio B: clone and checkout the branch — sees first commit
        output_1 = studio_pair.run_in_b(
            f"cd {_WORK_DIR} && git clone {auth_url} repo 2>&1 && "
            f"cd repo && "
            f"git fetch origin {branch} 2>&1 && "
            f"git checkout {branch} && "
            f"cat data.txt"
        )
        assert marker_1 in output_1

        # Studio A: second commit, push
        studio_pair.run_in_a(
            f"cd {_WORK_DIR}/repo && "
            f"echo '{marker_2}' >> data.txt && "
            f"git add data.txt && "
            f"git commit -m 'second' 2>&1 && "
            f"git push origin {branch} 2>&1"
        )

        # Studio B: pull — sees second marker
        output_2 = studio_pair.run_in_b(
            f"cd {_WORK_DIR}/repo && "
            f"git pull origin {branch} 2>&1 && "
            f"cat data.txt"
        )
        assert marker_2 in output_2

        # Cleanup
        try:
            studio_pair.run_in_a(
                f"cd {_WORK_DIR}/repo && git push origin --delete {branch} 2>&1"
            )
        except Exception:
            pass

    def test_json_payload_round_trip(self, studio_pair, git_remote):
        """Studio A commits a JSON file; Studio B clones and parses it.

        Mirrors the real pattern: runners write structured results (JSON claims),
        the reviewer reads them via git.
        """
        branch = f"e2e-json-{studio_pair.run_id}"
        auth_url = git_remote.authenticated_url

        # Studio A: commit a JSON payload
        studio_pair.run_in_a(
            f"cd {_WORK_DIR} && git clone {auth_url} repo 2>&1 && "
            f"cd repo && {_GIT_CONFIG} && "
            f"git checkout -b {branch} && "
            f"python3 -c \""
            f"import json; json.dump({{'run_id': '{studio_pair.run_id}', "
            f"'source': 'studio_a', 'confidence': 0.95}}, "
            f"open('claim.json', 'w'))\" && "
            f"git add claim.json && "
            f"git commit -m 'e2e: json claim' 2>&1 && "
            f"git push origin {branch} 2>&1"
        )

        # Studio B: clone, checkout, parse
        output_b = studio_pair.run_in_b(
            f"cd {_WORK_DIR} && git clone {auth_url} repo 2>&1 && "
            f"cd repo && "
            f"git fetch origin {branch} 2>&1 && "
            f"git checkout {branch} && "
            f"python3 -c \""
            f"import json; d = json.load(open('claim.json')); "
            f"print(d['run_id']); print(d['confidence'])\""
        )
        assert studio_pair.run_id in output_b
        assert "0.95" in output_b

        # Cleanup
        try:
            studio_pair.run_in_a(
                f"cd {_WORK_DIR}/repo && git push origin --delete {branch} 2>&1"
            )
        except Exception:
            pass
