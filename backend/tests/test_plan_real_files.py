import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from shapely.geometry import Point

import app as app_module
from route_processor import _MAX_YAW_RATE_DEG_PER_SEC, process_route, smooth_preview

FILES = [Path(os.environ.get("QBIQ_DESIGN_JSON", r"C:\Users\kevin\Downloads\121937120410001.json")),
         Path(os.environ.get("QBIQ_DESIGN_JSON_2", r"C:\Users\kevin\Downloads\80565468720002.json"))]
FILES = [f for f in FILES if f.exists()]
if not FILES:
    pytest.skip("real qbiq design JSONs not available", allow_module_level=True)

FPS = 30


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _tour(client, path) -> dict:
    """Upload the design JSON and return its default auto tour."""
    with open(path, "rb") as f:
        r = client.post("/api/upload-qbiq-design", data={"json_file": (f, path.name)},
                        content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    tour = client.post("/api/auto-tour", json={}).get_json()
    assert "error" not in tour, tour
    return tour


def _wire(tour) -> list:
    """Tour waypoints in the frontend's wire format, with stop metadata."""
    wire = [[p[0], p[1], 0, "", None] for p in tour["waypoints"]]
    for s in tour["stops"]:
        wire[s["index"]][4] = {k: s[k] for k in ("room_id", "room_name", "look_at", "dwell_s")}
    return wire


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_real_file_auto_tour_stays_in_corridor(client, path):
    tour = _tour(client, path)
    plan = app_module._LAST_PLAN
    assert plan is not None
    covered = plan.corridor.buffer(1e-6)
    wps = tour["waypoints"]
    assert len(tour["stops"]) >= 5
    assert all(covered.covers(Point(p)) for p in wps)
    assert all(covered.covers(Point(p)) for p in smooth_preview(wps, smoothing=1.0))
    assert 10 <= tour["suggested_duration_s"] <= 600

    by_id = {room.id: room for room in plan.rooms}
    for s in tour["stops"]:
        room = by_id[s["room_id"]]
        assert wps[s["index"]] == pytest.approx(list(room.stop.point), abs=60)

    frames = client.post("/api/process-route", json={"waypoints": _wire(tour),
                         "duration": tour["suggested_duration_s"], "fps": FPS}).get_json()
    assert frames["frame_count"] >= tour["suggested_duration_s"] * FPS - 5


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_real_file_camera_never_whips(client, path):
    tour = _tour(client, path)
    frames = client.post("/api/process-route", json={"waypoints": _wire(tour),
                         "duration": tour["suggested_duration_s"], "fps": FPS}).get_json()["frames"]
    jumps = [abs(b["yaw"] - a["yaw"]) for a, b in zip(frames, frames[1:])]
    assert max(jumps) <= _MAX_YAW_RATE_DEG_PER_SEC / FPS + 1e-6


def _xml_keyframes(xml: str, u: float) -> list:
    """((x, y) in plan units, yaw_deg) of every exported keyframe."""
    return [((float(k.find("Position").get("x")) / u, float(k.find("Position").get("z")) / u),
             math.degrees(math.atan2(float(k.find("LookAt").get("z")), float(k.find("LookAt").get("x")))))
            for k in ET.fromstring(xml).find("Keyframes")]


def _held_and_look(kfs: list, f0, look_yaw: float) -> tuple:
    """(keyframes holding the dwell's position, whether one of them has the dwell's look-in yaw)."""
    held = [yaw for p, yaw in kfs if math.dist(p, (f0.x, f0.y)) < 1e-3]
    return len(held), any(abs((yaw - look_yaw + 180) % 360 - 180) < 1.0 for yaw in held)


def _bearing(a, b) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_real_file_xml_keeps_every_stop(client, path):
    tour = _tour(client, path)
    u = app_module._LAST_PLAN.units_to_metres
    wire = _wire(tour)
    for length in (tour["suggested_duration_s"], 60, 400):
        xml = client.post("/api/export/xml", json={"waypoints": wire,
                          "settings": {"duration": length, "units_to_metres": u}}).get_data(as_text=True)
        kfs = _xml_keyframes(xml, u)
        frames = process_route(wire, camera_height=1.75, total_duration=length, fps=FPS, **app_module._camera_hints())
        starts = [i for i, f in enumerate(frames) if f.dwell == "start"]
        assert len(starts) == len(tour["stops"])
        for i, stop in zip(starts, tour["stops"]):
            look = next(f for f in frames[i:] if f.dwell == "look")
            held, looks_in = _held_and_look(kfs, frames[i], look.yaw)
            assert held >= 2 and looks_in, f"{length}s: stop {stop['room_id']} lost"
            if length != 60:  # at 60 s the dwells are ~1 s: the 180 deg/s turn cap can't always reach look_at
                assert abs((look.yaw - _bearing((look.x, look.y), stop["look_at"]) + 180) % 360 - 180) < 3.0
