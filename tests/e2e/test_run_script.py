"""Test running multi-line scripts inside Studios.

Validates that studio.run() can execute non-trivial logic — the mechanism
the ``art launch`` command uses to run runner/reviewer commands and
studio_setup.sh.
"""

from __future__ import annotations

import time

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(300)]


# A self-contained bash script that:
#   1. Creates a temp directory
#   2. Writes a Python health probe script to it
#   3. Runs the Python script
#   4. Outputs a JSON success marker
# Mirrors how `art launch` sends commands to Studios via studio.run().
_CUSTOM_TEST_SCRIPT = """\
#!/usr/bin/env bash
set -euo pipefail

TMPDIR=$(mktemp -d)
cat > "$TMPDIR/health_probe.py" << 'PYEOF'
import json
import platform
import sys

result = {
    "python_version": platform.python_version(),
    "platform": platform.platform(),
    "status": "healthy",
    "marker": "E2E_SCRIPT_SUCCESS",
}
print(json.dumps(result))
sys.exit(0)
PYEOF

python3 "$TMPDIR/health_probe.py"
rm -rf "$TMPDIR"
"""


class TestScriptExecution:
    """Run custom scripts inside Studios and verify output."""

    def test_custom_script_in_studio_a(self, studio_pair):
        """Run a multi-line bash+python script in Studio A."""
        output = studio_pair.run_in_a(_CUSTOM_TEST_SCRIPT)
        assert "E2E_SCRIPT_SUCCESS" in output
        assert "healthy" in output

    def test_custom_script_in_studio_b(self, studio_pair):
        """Run the same script in Studio B."""
        output = studio_pair.run_in_b(_CUSTOM_TEST_SCRIPT)
        assert "E2E_SCRIPT_SUCCESS" in output

    def test_script_with_nonzero_exit(self, studio_pair):
        """A script that exits nonzero should be detectable."""
        script = "echo 'about to fail' && exit 42"
        output, exit_code = studio_pair.run_in_a_with_exit_code(script)
        assert exit_code == 42
        assert "about to fail" in output

    def test_script_writes_to_shared_storage(self, studio_pair):
        """A script in Studio A writes to shared FS, readable from B.

        Combines script execution with shared filesystem validation — the
        end-to-end path that production runners use.
        """
        marker = f"script-marker-{studio_pair.run_id}"
        test_dir = f"{studio_pair.shared_data_dir}/.e2e-script-{studio_pair.run_id}"
        filepath = f"{test_dir}/script_output.txt"

        script = f"""\
mkdir -p {test_dir}
echo '{marker}' > {filepath}
echo 'SCRIPT_DONE'
"""
        output = studio_pair.run_in_a(script)
        assert "SCRIPT_DONE" in output

        time.sleep(2)

        read_output = studio_pair.run_in_b(f"cat {filepath}")
        assert marker in read_output

        # Cleanup
        try:
            studio_pair.run_in_a(f"rm -rf {test_dir}")
        except Exception:
            pass
