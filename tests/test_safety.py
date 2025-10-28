"""Tests for safety helpers like is_safe_id and fetch suppression."""
from __future__ import annotations

from huntstand_exporter.exporter import is_safe_id, fetch_members_for_area


class DummySession:
    def __init__(self):
        self.last_url: str | None = None

    def get(self, url: str, timeout: int = 15):  # pragma: no cover - not used for unsafe id
        self.last_url = url

        class R:
            def raise_for_status(self):
                return None

            def json(self):
                return {"objects": []}
        return R()


def test_is_safe_id_valid_values():
    assert is_safe_id(123)
    assert is_safe_id("abcDEF123")
    assert is_safe_id("123-456-789")


def test_is_safe_id_invalid_values():
    for v in (None, "", " / ", "abc;rm", "../etc/passwd", "id with space", "✨", {"x": 1}):
        assert not is_safe_id(v)


def test_fetch_members_block_unsafe_id():
    sess = DummySession()
    result = fetch_members_for_area(sess, "../bad")
    assert result is None
    assert sess.last_url is None  # no network attempted
