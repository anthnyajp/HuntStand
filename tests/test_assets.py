from typing import Any

import pytest

from huntstand_exporter.exporter import fetch_assets_for_area, _normalize_asset, ASSET_ENDPOINT_CANDIDATES


class DummyResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class DummySession:
    def __init__(self, mapping: dict[str, Any]):
        self.mapping = mapping

    def get(self, url: str, timeout: int = 15):  # pragma: no cover - trivial
        # Return payload if key matches start of URL ignoring huntarea id specifics
        for k, v in self.mapping.items():
            if url.startswith(k):
                return DummyResponse(200, v)
        return DummyResponse(404, {})


@pytest.fixture
def sample_assets_payload():
    return {
        "objects": [
            {
                "id": "stand-123",
                "name": "South Ridge Stand",
                "type": "ladder",
                "lat": 35.1,
                "lon": -80.9,
                "created": "2025-10-30T09:00:00Z",
                "owner": {"email": "owner@example.com"},
                "public": True,
            },
            {
                "id": "cam-9",
                "title": "Main Trail Cam",
                "category": "cellular",
                "location": {"latitude": 35.2, "longitude": -80.95},
                "last_activity": "2025-10-30T09:05:00Z",
                "user": {"username": "trail_user"},
                "shared": False,
            },
        ]
    }


def test_normalize_asset_basic(sample_assets_payload):
    first = sample_assets_payload["objects"][0]
    norm = _normalize_asset(first, "stand", "ha-1", "Area Name")
    assert norm["asset_type"] == "stand"
    assert norm["asset_id"] == "stand-123"
    assert norm["latitude"] == "35.1"
    assert norm["longitude"] == "-80.9"
    assert norm["owner_email"] == "owner@example.com"
    assert norm["visibility"] == "public"


def test_normalize_asset_fallbacks(sample_assets_payload):
    second = sample_assets_payload["objects"][1]
    norm = _normalize_asset(second, "camera", "ha-1", "Area Name")
    assert norm["asset_type"] == "camera"
    assert norm["subtype"] == "cellular"
    # location dict extraction
    assert norm["latitude"] == "35.2"
    assert norm["longitude"] == "-80.95"
    assert norm["owner_email"] == "trail_user"
    assert norm["visibility"] == "private"


def test_fetch_assets_for_area_aggregates(sample_assets_payload, monkeypatch):
    # Build dummy endpoints mapping using first candidate only to simulate partial availability
    safe_hid = "abc123"  # hex-only string accepted by is_safe_id
    mapping = {ASSET_ENDPOINT_CANDIDATES[0][1].format(safe_hid): sample_assets_payload}
    session = DummySession(mapping)
    assets = fetch_assets_for_area(session, safe_hid, "Test Area")
    assert len(assets) == 2
    types_found = {a["asset_type"] for a in assets}
    assert "stand" in types_found  # because candidate at index 0 labeled 'stand'


def test_fetch_assets_for_area_safe_id_rejects():
    session = DummySession({})
    # Unsafe ID with spaces should be rejected
    assets = fetch_assets_for_area(session, "not safe id", "Area")
    assert assets == []
