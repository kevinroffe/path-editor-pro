import json
import xml.etree.ElementTree as ET

import pytest

import app as app_module
import camera_style as cs

U = 0.01
ROUTE = [[0, 0], [3000, 0], [3000, 2000]]


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _xml(client, waypoints, **settings):
    s = {"duration": 40, "fps": 30, "smoothing": 1.0, "units_to_metres": U} | settings
    r = client.post("/api/export/xml", json={"waypoints": waypoints, "cuts": [], "settings": s})
    assert r.status_code == 200, r.data[:300]
    return ET.fromstring(r.data)


def test_process_route_returns_warnings_and_eye_height(client):
    r = client.post("/api/process-route", json={"waypoints": ROUTE, "duration": 40, "fps": 30, "units_to_metres": U})
    data = r.get_json()
    assert r.status_code == 200 and data["warnings"] == []
    assert all(f["z"] == cs.EYE_HEIGHT_M for f in data["frames"])


def test_process_route_warns_when_too_short(client):
    data = client.post("/api/process-route", json={"waypoints": ROUTE, "duration": 5, "fps": 30,
                                                   "units_to_metres": U}).get_json()
    assert any("too short" in w for w in data["warnings"])


def test_xml_house_style_shape(client):
    root = _xml(client, [[0, 0], [66000, 0]], duration=600)
    assert root.get("easingInOut") == "1" and root.get("shakyCam") == "0" and root.get("walkMode") == "1"
    kfs = root.find("Keyframes").findall("Keyframe")
    assert 2 < len(kfs) < 200
    assert all(k.get("timestampSeconds") is not None for k in kfs)
    assert all(k.find("Position").get("y") == "1.570000" for k in kfs)


def test_xml_hour_and_start_pan(client):
    root = _xml(client, [[0, 0, 0, ""], [3000, 0, 0, "14:30"], [6000, 0, 0, ""]], duration=60, start_pan=True)
    kfs = root.find("Keyframes").findall("Keyframe")
    assert any(abs(float(k.get("hour", -1)) - 14.5) < 1e-6 for k in kfs)
    p0, p1 = (kfs[i].find("Position") for i in (0, 1))
    assert (p0.get("x"), p0.get("z")) == (p1.get("x"), p1.get("z"))


def test_json_export_shape_unchanged(client):
    r = client.post("/api/export/json", json={"waypoints": ROUTE, "cuts": [],
                                              "settings": {"duration": 20, "units_to_metres": U}})
    frame = json.loads(r.data)["frames"][0]
    assert set(frame) == {"t", "x", "y", "z", "yaw_deg", "pitch_deg", "fov", "cut"}


@pytest.mark.parametrize("stop", [None, {"look_at": [1]}, "nope", {"look_at": [5, 5], "dwell_s": "x"}])
def test_four_and_five_element_waypoints_still_work(client, stop):
    wps = [[0, 0, 0, ""], [3000, 0, 0, "", stop], [3000, 2000, 0, ""]]
    assert client.post("/api/process-route", json={"waypoints": wps, "duration": 30}).status_code == 200
    assert client.post("/api/export/json", json={"waypoints": wps, "settings": {"duration": 30}}).status_code == 200
    _xml(client, wps)
    _xml(client, [w[:4] for w in wps])


def test_units_fall_back_to_request_then_default():
    assert app_module._units({"units_to_metres": 0.5}) == 0.5
    assert app_module._units({}) == 1.0


def test_smooth_preview_uturn_radius_is_metres(client):
    body = {"waypoints": [[0, 0], [3000, 0], [0, 100]], "smoothing": 1.0, "uturn_radius": 3, "units_to_metres": U}
    spline = client.post("/api/smooth-preview", json=body).get_json()["spline"]
    assert max(p[0] for p in spline) <= 2750
