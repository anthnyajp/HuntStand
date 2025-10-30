from typing import Any

from huntstand_exporter.exporter import refine_active_asset_endpoints, _normalize_asset


class ProbeSession:
    def __init__(self, probe_payloads: dict[str, Any]):
        self.probe_payloads = probe_payloads
        self.cookies = {}
        self.verify = True

    def get(self, url: str, timeout: int = 10):  # pragma: no cover - simple stub
        # Return 200 with payload if any probe key matches prefix; else 404
        for k, payload in self.probe_payloads.items():
            if url.startswith(k):
                return DummyResponse(200, payload)
        return DummyResponse(404, {})


class DummyResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_refine_active_asset_endpoints_filters(monkeypatch):
    # Build synthetic active endpoints list with two usable and one unusable
    from huntstand_exporter import exporter as exp
    exp.ACTIVE_ASSET_ENDPOINTS = [
        ("camera", "https://example/api/v1/camera/?huntarea_id={}"),
        ("broken", "https://example/api/v1/broken/?huntarea_id={}"),
        ("stand", "https://example/api/v1/stand/?huntarea_id={}"),
    ]
    usable_payload = [{"id": "c1", "name": "Cam"}]
    objects_payload = {"objects": [{"id": "s1", "name": "Stand"}]}
    # broken returns dict without list or objects key
    broken_payload = {"detail": "error"}
    session = ProbeSession({
        "https://example/api/v1/camera/": usable_payload,
        "https://example/api/v1/stand/": objects_payload,
        "https://example/api/v1/broken/": broken_payload,
    })
    refine_active_asset_endpoints(session, "abc123")  # type: ignore[arg-type]
    # After refinement, 'broken' should be removed
    types = {t for t, _ in exp.ACTIVE_ASSET_ENDPOINTS}
    assert "broken" not in types
    assert "camera" in types and "stand" in types


def test_normalize_asset_visibility_boolean():
    raw = {"id": "x1", "name": "Item", "public": False}
    norm = _normalize_asset(raw, "asset", "ha", "Area")
    assert norm["visibility"] == "private"


def test_normalize_asset_owner_fallback_username():
    raw = {"id": "x2", "label": "Trail Sensor", "user": {"username": "user123"}}
    norm = _normalize_asset(raw, "sensor", "ha", "Area")
    assert norm["owner_email"] == "user123"
