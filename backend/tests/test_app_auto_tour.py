import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_auto_tour_without_plan_is_400(client, monkeypatch):
    monkeypatch.setattr(app_module, "_LAST_PLAN", None)
    r = client.post("/api/auto-tour", json={})
    assert r.status_code == 400
    assert "design JSON" in r.get_json()["error"]


def test_auto_tour_no_matching_rooms_is_400(client):
    from tests.test_app_plan_cache import _design_json
    up = client.post("/api/upload-qbiq-design", data={"json_file": (_design_json(), "d.json")},
                     content_type="multipart/form-data")
    assert up.status_code == 200
    r = client.post("/api/auto-tour", json={"room_types": ["Nonexistent"]})
    assert r.status_code == 400
    assert r.get_json()["error"] == "no rooms of the selected types"


def _upload(client):
    from tests.test_app_plan_cache import _design_json
    up = client.post("/api/upload-qbiq-design", data={"json_file": (_design_json(), "d.json")},
                     content_type="multipart/form-data")
    assert up.status_code == 200


def test_auto_tour_room_ids_in_click_order(client):
    _upload(client)
    r = client.post("/api/auto-tour", json={"room_ids": ["D", "A"]})
    assert r.status_code == 200
    assert [s["room_id"] for s in r.get_json()["stops"]] == ["D", "A"]


@pytest.mark.parametrize("bad", ["A", [["A"]], [None], {"a": 1}])
def test_auto_tour_bad_room_ids_is_400(client, bad):
    _upload(client)
    assert client.post("/api/auto-tour", json={"room_ids": bad}).status_code == 400
