"""Tests for gather_huntareas fallback behavior."""
from __future__ import annotations

from typing import Any

from requests import RequestException

from huntstand_exporter.exporter import gather_huntareas, MYPROFILE_URL, HUNTAREA_BY_PROFILE


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:  # mimic requests.Response
        if not (200 <= self.status_code < 300):
            raise RequestException(f"status {self.status_code}")

    def json(self) -> Any:
        return self._payload


class FakeSessionBase:
    def __init__(self):
        self.calls: list[str] = []

    def get(self, url: str, timeout: int = 15):  # signature subset
        raise NotImplementedError


class FakeSessionEmptyThenFallback(FakeSessionBase):
    """Simulate myprofile returns empty hunt_areas triggering fallback profile id fetch."""

    def get(self, url: str, timeout: int = 15):
        self.calls.append(url)
        if url == MYPROFILE_URL:
            return FakeResponse({"hunt_areas": []})
        if url.startswith(HUNTAREA_BY_PROFILE.split("{", 1)[0]):  # profile fallback URL prefix
            return FakeResponse({"objects": [{"id": 10, "name": "Fallback Area"}]})
        return FakeResponse({}, status_code=404)


class FakeSessionErrorThenFallback(FakeSessionBase):
    """Simulate myprofile request raising exception then fallback succeeding."""

    def get(self, url: str, timeout: int = 15):
        self.calls.append(url)
        if url == MYPROFILE_URL:
            raise RequestException("network error")
        if url.startswith(HUNTAREA_BY_PROFILE.split("{", 1)[0]):
            return FakeResponse({"objects": [{"id": 99, "name": "Error Fallback"}]})
        return FakeResponse({}, status_code=404)


def test_fallback_triggered_on_empty_myprofile():
    session = FakeSessionEmptyThenFallback()
    result = gather_huntareas(session, fallback_profile_id="123")
    assert any(call == MYPROFILE_URL for call in session.calls)
    assert any(call.startswith(HUNTAREA_BY_PROFILE.split("{", 1)[0]) for call in session.calls)
    assert len(result) == 1
    assert result[0].get("id") == 10 or result[0].get("huntarea_id") == 10


def test_fallback_triggered_on_myprofile_error():
    session = FakeSessionErrorThenFallback()
    result = gather_huntareas(session, fallback_profile_id="456")
    assert any(call == MYPROFILE_URL for call in session.calls)
    assert any(call.startswith(HUNTAREA_BY_PROFILE.split("{", 1)[0]) for call in session.calls)
    assert len(result) == 1
    assert result[0].get("id") == 99 or result[0].get("huntarea_id") == 99
