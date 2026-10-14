import os
from pathlib import Path

import pytest
from shapely.geometry import Point

import app as app_module
from route_processor import smooth_preview

FILES = [Path(os.environ.get("QBIQ_DESIGN_JSON", r"C:\Users\kevin\Downloads\121937120410001.json")),
         Path(os.environ.get("QBIQ_DESIGN_JSON_2", r"C:\Users\kevin\Downloads\80565468720002.json"))]
FILES = [f for f in FILES if f.exists()]
if not FILES:
    pytest.skip("real qbiq design JSONs not available", allow_module_level=True)


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_real_file_auto_tour_stays_in_corridor(client, path):
    with open(path, "rb") as f:
        r = client.post("/api/upload-qbiq-design", data={"json_file": (f, path.name)},
                        content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    plan = app_module._LAST_PLAN
    assert plan is not None
    covered = plan.corridor.buffer(1e-6)

    tour = client.post("/api/auto-tour", json={}).get_json()
    assert "error" not in tour, tour
    wps = tour["waypoints"]
    assert len(tour["stops"]) >= 5
    assert all(covered.covers(Point(p)) for p in wps)
    assert all(covered.covers(Point(p)) for p in smooth_preview(wps, smoothing=1.0))
    assert 10 <= tour["suggested_duration_s"] <= 600

    by_id = {room.id: room for room in plan.rooms}
    for s in tour["stops"]:
        room = by_id[s["room_id"]]
        assert wps[s["index"]] == pytest.approx(list(room.stop.point), abs=60)

    wire = [[p[0], p[1], 0, "", None] for p in wps]
    for s in tour["stops"]:
        wire[s["index"]][4] = {k: s[k] for k in ("room_id", "room_name", "look_at", "dwell_s")}
    frames = client.post("/api/process-route", json={"waypoints": wire,
                         "duration": tour["suggested_duration_s"], "fps": 30}).get_json()
    assert frames["frame_count"] >= tour["suggested_duration_s"] * 30 - 5
