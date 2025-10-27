"""Tests for membership matrix generation."""
from __future__ import annotations

import csv
import os
import tempfile
from typing import Any

from huntstand_exporter.exporter import write_membership_matrix


def build_rows() -> list[dict[str, Any]]:
    return [
        {
            "huntarea_id": 1,
            "huntarea_name": "Alpha",
            "name": "John Doe",
            "email": "john@example.com",
            "rank": "member",
            "status": "active",
            "date_joined": "",
        },
        {
            "huntarea_id": 2,
            "huntarea_name": "Beta",
            "name": "Jane Smith",
            "email": "jane@example.com",
            "rank": "member",
            "status": "active",
            "date_joined": "",
        },
        {
            "huntarea_id": 2,
            "huntarea_name": "Beta",
            "name": "Invitee One",
            "email": "invitee@example.com",
            "rank": "guest",
            "status": "invited",
            "date_joined": "2025-10-27",
        },
        {
            "huntarea_id": 1,
            "huntarea_name": "Alpha",
            "name": "Requester Guy",
            "email": "requester@example.com",
            "rank": "",
            "status": "requested",
            "date_joined": "2025-10-27",
        },
    ]


def test_membership_matrix_basic():
    rows = build_rows()
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "matrix.csv")
        write_membership_matrix(rows, out_path=out_path)
        assert os.path.exists(out_path)

        with open(out_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            headers = reader.fieldnames
            assert headers is not None
            # email plus two hunt area columns
            assert set(headers) == {"email", "Alpha", "Beta"}
            data = list(reader)

        # There should be 4 unique emails
        emails = {r["email"] for r in data}
        assert emails == {
            "john@example.com",
            "jane@example.com",
            "invitee@example.com",
            "requester@example.com",
        }

        # Check capitalization of statuses
        lookup = {r["email"]: r for r in data}
        assert lookup["john@example.com"]["Alpha"] == "Active"
        assert lookup["john@example.com"]["Beta"] == "No"
        assert lookup["invitee@example.com"]["Beta"] == "Invited"
        assert lookup["requester@example.com"]["Alpha"] == "Requested"

        # Ensure default 'No' where no membership/invite/request
        assert lookup["jane@example.com"]["Alpha"] == "No"
        assert lookup["invitee@example.com"]["Alpha"] == "No"


def test_membership_matrix_empty_rows():
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "matrix.csv")
        write_membership_matrix([], out_path=out_path)
        # Empty file should still exist with only header row (email)
        with open(out_path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            rows = list(reader)
        assert len(rows) == 1  # header only
        assert rows[0] == ["email"]
