import time
import pytest
from types import SimpleNamespace

from huntstand_exporter.exporter import process_hunt_area


class SlowSession:
    def __init__(self, delay: float):
        self.delay = delay

    def get(self, url: str, timeout: int = 15):  # pragma: no cover - simple stub
        time.sleep(self.delay)
        # minimal shape for members endpoint simulation
        if "clubmember" in url:
            return SimpleNamespace(status_code=200, json=lambda: {"objects": [{"first_name": "A", "last_name": "B", "email": "a@b.com"}]}, raise_for_status=lambda: None)
        if "membershipemailinvite" in url or "membershiprequest" in url or "stand" in url or "camera" in url:
            return SimpleNamespace(status_code=200, json=lambda: [], raise_for_status=lambda: None)
        return SimpleNamespace(status_code=404, json=lambda: {}, raise_for_status=lambda: None)


@pytest.mark.parametrize("include_assets", [False, True])
def test_process_hunt_area_basic(include_assets):
    club = {"huntarea_id": "abc123", "huntarea": {"id": "abc123", "name": "Test Area"}}
    sess = SlowSession(0.01)
    rows, assets, summary = process_hunt_area(sess, club, include_assets)  # type: ignore[arg-type]
    assert len(rows) == 1
    if include_assets:
        # No asset endpoints in stub mapping return anything
        assert assets == []
    else:
        assert assets == []
    assert summary["counts"]["members"] == 1
