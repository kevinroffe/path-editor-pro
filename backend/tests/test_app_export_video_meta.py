import pytest

import app as app_module

ROUTE = [[0, 0, 0, "", None], [500, 0, 0, "", None], [500, 500, 0, "", None]]
VIDEO = {"name": "One Harbour Plaza", "fades": [{"outM": 1, "inM": 3}]}


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _settings(**extra):
    return {"duration": 10, "units_to_metres": 0.01, **extra}


def test_json_export_round_trips_video_meta(client):
    r = client.post("/api/export/json", json={"waypoints": ROUTE, "cuts": [], "settings": _settings(video=VIDEO)})
    assert r.status_code == 200
    assert r.get_json()["meta"]["video"] == VIDEO


def test_xml_export_ignores_video_settings(client):
    plain = client.post("/api/export/xml", json={"waypoints": ROUTE, "cuts": [], "settings": _settings()})
    with_video = client.post("/api/export/xml", json={"waypoints": ROUTE, "cuts": [], "settings": _settings(video=VIDEO)})
    assert plain.status_code == with_video.status_code == 200
    assert plain.data == with_video.data
