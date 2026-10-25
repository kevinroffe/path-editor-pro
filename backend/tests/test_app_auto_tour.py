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


@pytest.mark.parametrize("bad", [0, ""])
def test_auto_tour_falsy_unknown_room_id_is_400(client, bad):
    _upload(client)
    assert client.post("/api/auto-tour", json={"room_ids": [bad]}).status_code == 400


def test_auto_tour_reports_the_default_start(client):
    _upload(client)
    r = client.post("/api/auto-tour", json={"room_ids": ["A"]})
    assert r.status_code == 200
    assert r.get_json()["start"] == pytest.approx(list(app_module._LAST_PLAN.entrance), abs=1e-6)


def test_auto_tour_starts_at_a_chosen_entrance(client):
    _upload(client)
    d = next(rm for rm in app_module._LAST_PLAN.rooms if rm.id == "D").stop.point
    r = client.post("/api/auto-tour", json={"room_ids": ["A"], "entrance": list(d)})
    assert r.status_code == 200
    body = r.get_json()
    assert body["start"] == pytest.approx(list(d), abs=1e-6)
    assert body["waypoints"][0][:2] == pytest.approx(list(d), abs=1.0)


def test_entrance_outside_the_corridor_snaps_into_it(client):
    from shapely.geometry import Point
    _upload(client)
    r = client.post("/api/auto-tour", json={"room_ids": ["A"], "entrance": [5000, 5000]})
    assert r.status_code == 200
    assert app_module._LAST_PLAN.corridor.covers(Point(r.get_json()["start"]))


@pytest.mark.parametrize("bad", ["x", [1], [1, "a"], [float("nan"), 0], [1, 2, 3]])
def test_auto_tour_bad_entrance_is_400(client, bad):
    _upload(client)
    r = client.post("/api/auto-tour", json={"room_ids": ["A"], "entrance": bad})
    assert r.status_code == 400
    assert r.get_json()["error"] == "entrance must be [x, y]"
