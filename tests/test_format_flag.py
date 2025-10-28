"""Tests for --format flag influencing planned outputs during dry-run.

These tests parse the debug log "Planned paths" line emitted by the exporter
to verify that only the correct output files are scheduled based on --format.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]


def extract_planned_paths(text: str) -> set[str]:
    # Matches the debug log line: Planned paths (<format>): path1, path2, ...
    m = re.search(r"Planned paths \([a-z]+\): (.+)", text)
    if not m:
        return set()
    return {p.strip() for p in m.group(1).split(",") if p.strip()}


@pytest.mark.parametrize(
    "fmt,expect_csv,expect_json,expect_matrix",
    [
        ("all", True, True, True),
        ("csv", True, False, True),
        ("json", False, True, False),
    ],
)
def test_dry_run_planned_outputs(fmt: str, expect_csv: bool, expect_json: bool, expect_matrix: bool):
    env = os.environ.copy()
    env.pop("HUNTSTAND_SESSIONID", None)
    env.pop("HUNTSTAND_CSRFTOKEN", None)
    proc = subprocess.run(
        [sys.executable, "-m", "huntstand_exporter", "--dry-run", f"--format={fmt}"],
        cwd=str(PKG_ROOT),
        env={**env, "PYTHONPATH": str(PKG_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert proc.returncode == 0
    combined = proc.stdout + proc.stderr
    planned = extract_planned_paths(combined)
    # Validate presence/absence by file suffixes and stems
    has_detailed = any(p.endswith(".csv") and "members_detailed" in p for p in planned)
    has_matrix = any(p.endswith(".csv") and "membership_matrix" in p for p in planned)
    has_summary = any(p.endswith(".json") and "summary" in p for p in planned)
    assert has_detailed is expect_csv
    assert has_matrix is expect_matrix
    assert has_summary is expect_json


def test_dry_run_csv_includes_per_hunt_when_flag():
    env = os.environ.copy()
    env.pop("HUNTSTAND_SESSIONID", None)
    env.pop("HUNTSTAND_CSRFTOKEN", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "huntstand_exporter",
            "--dry-run",
            "--format=csv",
            "--per-hunt",
        ],
        cwd=str(PKG_ROOT),
        env={**env, "PYTHONPATH": str(PKG_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert proc.returncode == 0
    combined = proc.stdout + proc.stderr
    planned = extract_planned_paths(combined)
    assert any("per_hunt_csvs" in p for p in planned), "Per-hunt directory should be planned when --per-hunt is used"
