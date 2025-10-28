"""Tests for --dry-run flag and logger configuration."""
from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("log_format", ["text", "json"])
def test_dry_run_exits_zero(log_format: str):
    """Invoke console script with --dry-run; expect exit code 0 even without cookies."""
    env = os.environ.copy()
    env["HUNTSTAND_LOG_FORMAT"] = log_format
    # Ensure no session cookies to exercise path without outputs
    env.pop("HUNTSTAND_SESSIONID", None)
    env.pop("HUNTSTAND_CSRFTOKEN", None)
    # Use python -m to avoid relying on entry point install in test environment
    result = subprocess.run(
        [sys.executable, "-m", "huntstand_exporter", "--dry-run"],
        cwd=str(PACKAGE_ROOT),
        env={**env, "PYTHONPATH": str(PACKAGE_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0
    # Extract planned output paths from dry-run listing and assert they were not created.
    planned_paths = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        # Handle JSON log format lines by extracting the multiline message
        if line.startswith("{"):
            try:
                import json as _json
                payload = _json.loads(line)
                msg = payload.get("msg", "")
                for mline in msg.splitlines():
                    mline = mline.strip()
                    if mline.startswith("-"):
                        planned_paths.append(Path(mline[1:].strip()))
            except Exception:
                pass
        elif line.startswith("-"):
            planned_paths.append(Path(line[1:].strip()))
    # We expect at least one planned path (csv, matrix, json)
    assert planned_paths, f"No planned paths parsed from output: {result.stdout}"
    for p in planned_paths:
        assert not p.exists(), f"Dry-run should not create file: {p}"
    # Log format check (rudimentary)
    if log_format == "json":
        # Expect lines that parse as JSON
        first_line = result.stdout.strip().splitlines()[0]
        assert first_line.startswith("{")
    else:
        # Text format should contain level name
        assert "INFO" in result.stdout or "WARNING" in result.stdout
