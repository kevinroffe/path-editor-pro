import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import app as app_module
import camera_style as cs
from tests.style_metrics import style_metrics

FILES = [Path(os.environ.get("QBIQ_DESIGN_JSON", r"C:\Users\kevin\Downloads\121937120410001.json")),
         Path(os.environ.get("QBIQ_DESIGN_JSON_2", r"C:\Users\kevin\Downloads\80565468720002.json"))]
FILES = [f for f in FILES if f.exists()]
if not FILES:
    pytest.skip("real qbiq design JSONs not available", allow_module_level=True)

BACK_OF_HOUSE = {"Storage Room", "IT Room", "Print Hub", "Other"}


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _tour(client, path):
    with open(path, "rb") as f:
        up = client.post("/api/upload-qbiq-design", data={"json_file": (f, path.name)},
                         content_type="multipart/form-data").get_json()
    ids = [r["id"] for r in up["plan"]["rooms"] if r["type"] not in BACK_OF_HOUSE][:6]
    tour = client.post("/api/auto-tour", json={"room_ids": ids}).get_json()
    wire = [[p[0], p[1], 0, "", None] for p in tour["waypoints"]]
    for s in tour["stops"]:
        wire[s["index"]][4] = {k: s[k] for k in ("room_id", "room_name", "look_at", "dwell_s", "walk_in")}
    return tour, wire, app_module._LAST_PLAN.units_to_metres


def _xml_keyframes(xml: bytes, u: float) -> list:
    """Keyframes back in plan display units: undo the move onto qbiq's Revit model, then the metre scale."""
    ox, oz = app_module._LAST_PLAN.enscape_offset
    out = []
    for k in ET.fromstring(xml).find("Keyframes").findall("Keyframe"):
        p, look = k.find("Position"), k.find("LookAt")
        yaw = math.degrees(math.atan2(float(look.get("z")), float(look.get("x"))))
        out.append((cs.Keyframe(float(k.get("timestampSeconds")), (float(p.get("x")) - ox) / u, (float(p.get("z")) - oz) / u, yaw),
                    float(p.get("y"))))
    kfs = [k for k, _ in out]
    yaws = [k.yaw for k in kfs]
    for i in range(1, len(yaws)):                     # LookAt loses the turn count; restore continuity
        yaws[i] = yaws[i - 1] + (yaws[i] - yaws[i - 1] + 180) % 360 - 180
        kfs[i].yaw = yaws[i]
    return kfs, [y for _, y in out]


def _export(client, wire, duration, u):
    s = {"duration": duration, "fps": 30, "smoothing": 1.0, "units_to_metres": u}
    return client.post("/api/export/xml", json={"waypoints": wire, "cuts": [], "settings": s}).data


def _wrap(a):
    return (a + 180) % 360 - 180


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_real_file_matches_house_style(client, path):
    tour, wire, u = _tour(client, path)
    kfs, heights = _xml_keyframes(_export(client, wire, tour["suggested_duration_s"], u), u)
    m = style_metrics(kfs, u)
    assert 2.6 <= m["s_per_kf"] <= 4.0, m   # room-dense tours (ruling)
    assert m["yaw_rate_p90"] <= 27 and m["yaw_rate_max"] <= 30, m
    assert m["reversals_per_min"] <= 8.5, m   # p90 of the 312 designer paths is 8.33 (ruling 2026-11-01)
    assert 8 <= m["look_vs_travel_med"] <= 32, m
    assert cs.MIN_SPEED_MPS <= m["speed_med"] <= 1.45, m
    assert m["n_pans"] == 0 and all(h == pytest.approx(cs.EYE_HEIGHT_M) for h in heights)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_real_file_every_room_gets_a_look(client, path):
    tour, wire, u = _tour(client, path)
    kfs, _ = _xml_keyframes(_export(client, wire, tour["suggested_duration_s"], u), u)
    for s in tour["stops"]:
        sx, sy = tour["waypoints"][s["index"]]
        if s["walk_in"]:
            continue                                  # a walk-in area: walking in is the look
        near = [(a, b) for a, b in zip(kfs, kfs[1:]) if math.hypot(a.x - sx, a.y - sy) * u <= 3.0]
        assert near, s["room_name"]
        looks = [abs(_wrap(a.yaw - math.degrees(math.atan2(s["look_at"][1] - a.y, s["look_at"][0] - a.x))))
                 for a, _ in near]
        offs = [abs(_wrap(a.yaw - math.degrees(math.atan2(b.y - a.y, b.x - a.x)))) for a, b in near
                if math.hypot(b.x - a.x, b.y - a.y) > 1]
        assert min(looks) <= 20 or max(offs, default=0) >= 55, (s["room_name"], min(looks), offs)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_real_file_preview_matches_export(client, path):
    tour, wire, u = _tour(client, path)
    kfs, _ = _xml_keyframes(_export(client, wire, tour["suggested_duration_s"], u), u)
    frames = client.post("/api/process-route", json={"waypoints": wire, "duration": tour["suggested_duration_s"],
                                                     "fps": 30, "smoothing": 1.0}).get_json()["frames"]
    total = tour["suggested_duration_s"]
    for k in kfs:   # tours walk some corridors twice: match within the eased time window, then by position
        window = [f for f in frames if abs(f["t"] * total - k.t_s) <= cs.EASE_S]
        f = min(window, key=lambda f: math.hypot(f["x"] - k.x, f["y"] - k.y))
        assert math.hypot(f["x"] - k.x, f["y"] - k.y) * u <= 0.03
        assert abs(_wrap(f["yaw"] - k.yaw)) <= 1.5
