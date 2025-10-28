"""Tests for login fallback logic (attempt_login)."""
from __future__ import annotations

from typing import Any

from requests import RequestException

from huntstand_exporter.exporter import attempt_login, BASE_URL, ROOT_PATH, LOGIN_POST_PATH


class FakeCookies:
    def __init__(self, initial: dict[str, str] | None = None):
        self.store = dict(initial or {})

    def get(self, key: str, default: Any = None):
        return self.store.get(key, default)

    def set(self, key: str, value: str, domain: str | None = None, path: str | None = None):
        self.store[key] = value


class FakeResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if not (200 <= self.status_code < 300):
            raise RequestException(f"status {self.status_code}")


class FakeSessionFail:
    def __init__(self):
        self.cookies = FakeCookies({"csrftoken": "abc"})
        self.headers = {"User-Agent": "UA"}
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []

    def get(self, url: str, timeout: int = 15):
        self.get_calls.append(url)
        return FakeResponse(200)

    def post(self, url: str, data: dict[str, Any], headers: dict[str, str], timeout: int = 15):
        self.post_calls.append({"url": url, "data": data, "headers": headers})
        # Never set sessionid cookie simulating failure
        return FakeResponse(200)


class FakeSessionSuccess(FakeSessionFail):
    def post(self, url: str, data: dict[str, Any], headers: dict[str, str], timeout: int = 15):
        self.post_calls.append({"url": url, "data": data, "headers": headers})
        # Simulate server setting sessionid cookie on first attempt
        if "login" in data or "username" in data:
            self.cookies.set("sessionid", "sess-123")
        return FakeResponse(200)


def test_attempt_login_failure():
    session = FakeSessionFail()
    ok = attempt_login(session, "user@example.com", "pass")
    assert ok is False
    # Should have tried root and then POST attempts
    assert BASE_URL + ROOT_PATH in session.get_calls
    assert any(call["url"] == BASE_URL + LOGIN_POST_PATH for call in session.post_calls)
    # Should try both 'login' and 'username' fields
    user_fields = {"login" if "login" in call["data"] else "username" for call in session.post_calls}
    assert user_fields == {"login", "username"}


def test_attempt_login_success():
    session = FakeSessionSuccess()
    ok = attempt_login(session, "user@example.com", "pass")
    assert ok is True
    assert session.cookies.get("sessionid") == "sess-123"
