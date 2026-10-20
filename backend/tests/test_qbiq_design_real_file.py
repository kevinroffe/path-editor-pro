import os
from pathlib import Path

import pytest

import app as app_module

_JSON_SRC = Path(os.environ.get("QBIQ_DESIGN_JSON", r"C:\Users\kevin\Downloads\121937120410001.json"))

if not _JSON_SRC.exists():
    pytest.skip("real qbiq design JSON not available on this machine", allow_module_level=True)


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _display_centroid(poly):
    """Model-space polyline centroid, Y-negated into the display space /api/autopath expects."""
    return [sum(p[0] for p in poly) / len(poly), -sum(p[1] for p in poly) / len(poly)]


def _upload(client):
    """POST the real design JSON to the upload endpoint."""
    with open(_JSON_SRC, "rb") as f:
        resp = client.post(
            "/api/upload-qbiq-design",
            data={"json_file": (f, "design.json")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200, resp.get_json()
    return resp


def test_real_design_json_produces_a_rich_3d_scene(client):
    resp = _upload(client)
    meshes = resp.get_json()["geometry"]["meshes"]
    types = {m["type"] for m in meshes}
    assert meshes and {"floor", "wall", "window", "glass", "frame", "column", "furniture"} <= types

    xs = [v for m in meshes for v in m["verts"][0::3]]
    ys = [v for m in meshes for v in m["verts"][1::3]]
    assert max(xs) - min(xs) == pytest.approx(36.0, abs=1.0)
    assert max(ys) - min(ys) == pytest.approx(18.6, abs=1.0)
    assert sum(len(m["verts"]) // 3 for m in meshes) < 400_000
    assert len(resp.data) < 10_000_000


def test_real_design_json_produces_a_routable_floor_plan(client):
    resp = _upload(client)
    body = resp.get_json()
    geometry = body["geometry"]

    assert body["source"] == "qbiq"
    assert geometry["walls"] and all(len(w) == 2 for w in geometry["walls"])
    assert len(geometry["doors"]) > 10
    assert geometry["columns"]
    assert geometry["furniture"]
    assert len(geometry["spaces"]) >= 17

    bounds = body["bounds"]
    extent_m = max(bounds["xmax"] - bounds["xmin"], bounds["ymax"] - bounds["ymin"]) * body["units_to_metres"]
    assert 2.0 <= extent_m <= 200.0

    doors = sorted(geometry["doors"], key=lambda d: _display_centroid(d)[0])
    picks = [doors[round(i * (len(doors) - 1) / 4)] for i in range(5)]
    route = client.post("/api/autopath", json={"points": [_display_centroid(d) for d in picks]})
    assert route.status_code == 200
    waypoints = route.get_json()["waypoints"]
    assert waypoints and len(waypoints) >= 5
