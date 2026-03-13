"""Test cross-Studio file coordination via shared teamspace filesystem.

The autoresearch architecture relies on /teamspace/data/ being a shared
mount across all Studios in a teamspace.  These tests write a file in
Studio A and verify Studio B can read it — the fundamental coordination
primitive.
"""

from __future__ import annotations

import json
import time

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(300)]

# All test files go under a run-specific subdirectory for easy cleanup
_TEST_SUBDIR = ".e2e-test"


@pytest.fixture(autouse=True)
def test_directory(studio_pair):
    """Create and clean up a test-specific directory in shared storage."""
    test_dir = f"{studio_pair.shared_data_dir}/{_TEST_SUBDIR}-{studio_pair.run_id}"
    studio_pair.run_in_a(f"mkdir -p {test_dir}")
    yield test_dir
    # Cleanup: remove the test directory
    try:
        studio_pair.run_in_a(f"rm -rf {test_dir}")
    except Exception:
        pass  # best-effort cleanup


class TestCrossStudioFileSharing:
    """Write in Studio A -> read in Studio B (and vice versa)."""

    def test_write_a_read_b_plain_text(self, studio_pair, test_directory):
        """Write a plain text file in Studio A, read it from Studio B."""
        filepath = f"{test_directory}/hello.txt"
        content = f"written-by-studio-a-{studio_pair.run_id}"

        studio_pair.run_in_a(f"echo '{content}' > {filepath}")
        time.sleep(2)

        output = studio_pair.run_in_b(f"cat {filepath}")
        assert content in output

    def test_write_b_read_a_plain_text(self, studio_pair, test_directory):
        """Write a plain text file in Studio B, read it from Studio A."""
        filepath = f"{test_directory}/reverse.txt"
        content = f"written-by-studio-b-{studio_pair.run_id}"

        studio_pair.run_in_b(f"echo '{content}' > {filepath}")
        time.sleep(2)

        output = studio_pair.run_in_a(f"cat {filepath}")
        assert content in output

    def test_write_json_and_read_structured(self, studio_pair, test_directory):
        """Write a JSON file in Studio A, parse and validate from Studio B.

        Mirrors the real coordination pattern: runners write JSON claims,
        the reviewer reads them.
        """
        filepath = f"{test_directory}/claim.json"
        payload = {
            "studio": studio_pair.name_a,
            "run_id": studio_pair.run_id,
            "claim": "test-hypothesis",
            "confidence": 0.95,
        }

        # Write JSON in A using python3
        studio_pair.run_in_a(
            f"python3 -c \"import json; "
            f"json.dump({payload!r}, open('{filepath}', 'w'))\""
        )
        time.sleep(2)

        # Read and parse in B
        output = studio_pair.run_in_b(
            f"python3 -c \""
            f"import json; d = json.load(open('{filepath}')); "
            f"print(d['run_id']); print(d['confidence'])\""
        )
        assert studio_pair.run_id in output
        assert "0.95" in output

    def test_append_jsonl_from_both_studios(self, studio_pair, test_directory):
        """Both Studios append to the same JSONL file.

        Simulates concurrent writes to leaderboard.jsonl — the pattern
        used by multiple runners writing results.
        """
        filepath = f"{test_directory}/results.jsonl"

        # Studio A writes line 1
        studio_pair.run_in_a(
            f"echo '{{\"source\": \"{studio_pair.name_a}\", \"score\": 1}}' >> {filepath}"
        )
        # Studio B writes line 2
        studio_pair.run_in_b(
            f"echo '{{\"source\": \"{studio_pair.name_b}\", \"score\": 2}}' >> {filepath}"
        )
        time.sleep(2)

        # Read from either Studio — should have both lines
        output = studio_pair.run_in_a(f"cat {filepath}")
        assert studio_pair.name_a in output
        assert studio_pair.name_b in output

        # Verify line count
        count_output = studio_pair.run_in_a(f"wc -l < {filepath}")
        assert int(count_output.strip()) >= 2

    def test_large_file_checksum(self, studio_pair, test_directory):
        """Write a ~1MB file in Studio A, verify checksum matches in Studio B.

        Ensures shared filesystem handles non-trivial file sizes.
        """
        filepath = f"{test_directory}/large.bin"

        # Write ~1MB of deterministic data in A
        studio_pair.run_in_a(
            f"dd if=/dev/urandom of={filepath} bs=1024 count=1024 2>/dev/null"
        )
        time.sleep(3)

        # Compare checksums
        checksum_a = studio_pair.run_in_a(f"md5sum {filepath}").split()[0]
        checksum_b = studio_pair.run_in_b(f"md5sum {filepath}").split()[0]
        assert checksum_a == checksum_b, (
            f"Checksum mismatch: A={checksum_a}, B={checksum_b}"
        )
