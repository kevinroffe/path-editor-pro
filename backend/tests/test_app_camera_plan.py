import re

import pytest

import app as app_module
from camera_style import Keyframe, KeyframePlan, keyframe_plan_to_json

ROUTE = [[0, 0, 0, "", None], [500, 0, 0, "", None], [500, 500, 0, "", None]]


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _body(**extra):
    return {"waypoints": ROUTE, "cuts": [], "settings": {"duration": 10, "units_to_metres": 0.01, **extra}}


def test_camera_plan_matches_xml_keyframes(client):
    plan = client.post("/api/camera-plan", json=_body()).get_json()
    xml = client.post("/api/export/xml", json=_body()).data.decode()
    times = [float(t) for t in re.findall(r'timestampSeconds="([\d.]+)"', xml)]
    assert [k["t_s"] for k in plan["keyframes"]] == pytest.approx(times, abs=1e-3)
    assert plan["units_to_metres"] == 0.01
    assert {"t_s", "x", "y", "yaw", "hour", "cut_after", "still_s"} <= plan["keyframes"][0].keys()


def test_still_s_is_the_wait_at_a_keyframe():
    out = keyframe_plan_to_json(KeyframePlan([Keyframe(0, 0, 0, 0.0), Keyframe(3, 0, 0, 1.0), Keyframe(5, 1000, 0, 1.0)],
                                             units_to_metres=0.01))
    assert [k["still_s"] for k in out["keyframes"]] == [3, 0, 0]


def test_start_pan_creates_a_pause(client):
    plan = client.post("/api/camera-plan", json=_body(start_pan=True)).get_json()
    assert any(k["still_s"] > 0 for k in plan["keyframes"])


def test_bad_body_400(client):
    r = client.post("/api/camera-plan", json={"waypoints": [[0, 0]], "cuts": [], "settings": {}})
    assert r.status_code == 400 and "error" in r.get_json()
