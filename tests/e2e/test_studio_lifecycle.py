"""Test Studio lifecycle: creation, status queries, and basic commands."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(300)]


class TestStudioCreationAndStatus:
    """Verify Studios were created and are running."""

    def test_studio_a_is_running(self, studio_pair):
        """Studio A should report Running status."""
        status = str(studio_pair.studio_a.status)
        assert "running" in status.lower()

    def test_studio_b_is_running(self, studio_pair):
        """Studio B should report Running status."""
        status = str(studio_pair.studio_b.status)
        assert "running" in status.lower()

    def test_studio_names_are_unique(self, studio_pair):
        """Studio names include the run ID, ensuring uniqueness."""
        assert studio_pair.name_a != studio_pair.name_b
        assert studio_pair.run_id in studio_pair.name_a
        assert studio_pair.run_id in studio_pair.name_b


class TestBasicCommand:
    """Verify we can run simple commands inside Studios."""

    def test_echo_in_studio_a(self, studio_pair):
        """A basic echo command should return the expected string."""
        output = studio_pair.run_in_a("echo 'hello from studio a'")
        assert "hello from studio a" in output

    def test_echo_in_studio_b(self, studio_pair):
        """A basic echo command should return the expected string."""
        output = studio_pair.run_in_b("echo 'hello from studio b'")
        assert "hello from studio b" in output

    def test_run_with_exit_code_success(self, studio_pair):
        """run_with_exit_code should return exit code 0 for a successful command."""
        output, exit_code = studio_pair.run_in_a_with_exit_code("echo ok")
        assert exit_code == 0
        assert "ok" in output

    def test_run_with_exit_code_failure(self, studio_pair):
        """run_with_exit_code should return nonzero for a failing command."""
        _output, exit_code = studio_pair.run_in_a_with_exit_code("false")
        assert exit_code != 0

    def test_shared_data_dir_exists(self, studio_pair):
        """The shared teamspace data directory must exist in both Studios."""
        data_dir = studio_pair.shared_data_dir

        output_a, rc_a = studio_pair.run_in_a_with_exit_code(
            f"test -d {data_dir} && echo exists"
        )
        output_b, rc_b = studio_pair.run_in_b_with_exit_code(
            f"test -d {data_dir} && echo exists"
        )
        assert rc_a == 0 and "exists" in output_a, f"Studio A: {data_dir} not found"
        assert rc_b == 0 and "exists" in output_b, f"Studio B: {data_dir} not found"
