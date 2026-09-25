from fastapi.testclient import TestClient

from app.api import app, get_decision_recorder, get_selector
from app.records import LocalJsonlRecorder
from app.selector import FakeSelector


def test_healthz():
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_route_decision_endpoint(tmp_path):
    app.dependency_overrides = {}
    get_selector.cache_clear()
    get_decision_recorder.cache_clear()

    app.dependency_overrides[get_selector] = lambda: FakeSelector(choice_id="gemini-flash")
    app.dependency_overrides[get_decision_recorder] = lambda: LocalJsonlRecorder(str(tmp_path / "d.jsonl"))

    client = TestClient(app)
    response = client.post(
        "/v1/decisions/route",
        json={
            "task_id": "t1",
            "candidates": [
                {"id": "gemini-flash", "provider": "vertex", "model": "gemini-2.5-flash"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "selected"
    assert body["chosen"]["id"] == "gemini-flash"

    app.dependency_overrides = {}
