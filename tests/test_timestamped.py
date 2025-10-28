"""Tests for --timestamped flag dry-run path mutation."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def test_timestamped_dry_run_paths():
    env = os.environ.copy()
    env.pop("HUNTSTAND_SESSIONID", None)
    env.pop("HUNTSTAND_CSRFTOKEN", None)
    pkg_root = Path(__file__).resolve().parents[1]
    # Legacy --timestamped flag removed; dry-run still produces timestamped paths unconditionally.
    proc = subprocess.run(
        [sys.executable, "-m", "huntstand_exporter", "--dry-run"],
        cwd=str(pkg_root),
        env={**env, "PYTHONPATH": str(pkg_root / "src")},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0
    # Look for planned files lines
    pattern = re.compile(r"huntstand_members_detailed_\d{8}_\d{6}\.csv")
    assert pattern.search(proc.stdout) or pattern.search(proc.stderr)
