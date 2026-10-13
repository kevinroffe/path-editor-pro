import os
from pathlib import Path

import pytest

import app as app_module

# Overridable so this test is portable across machines — same pattern as
# test_corridor_graph_real_files.py.
_JSON_SRC = Path(os.environ.get(
    "QBIQ_REFERENCE_JSON",
    r"C:\Users\kevin\.codex\attachments\018c77c8-e695-4975-b4e0-91fa555a148d\Pasted text.txt",
))
_SVG_SRC = Path(os.environ.get(
    "QBIQ_REFERENCE_SVG",
    r"C:\Users\kevin\.codex\attachments\3dc362f9-eecb-4740-b8af-2acff74b62ef\Pasted text.txt",
))

if not _JSON_SRC.exists() or not _SVG_SRC.exists():
    pytest.skip("real qbiq reference JSON/SVG not available on this machine",
                allow_module_level=True)


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _display_centroid(poly):
    """Model-space polyline centroid, Y-negated into the display space /api/autopath expects."""
    return [sum(p[0] for p in poly) / len(poly), -sum(p[1] for p in poly) / len(poly)]


def test_real_qbiq_pair_produces_a_routable_floor_plan(client):
    with open(_JSON_SRC, "rb") as jf, open(_SVG_SRC, "rb") as sf:
        resp = client.post(
            "/api/upload-qbiq",
            data={"json_file": (jf, "reference.json"), "svg_file": (sf, "reference.svg")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    geometry = body["geometry"]

    assert body["source"] == "qbiq"
    assert body["units_to_metres"] == 0.01
    assert geometry["walls"] and all(len(w) == 2 for w in geometry["walls"])
    assert len(geometry["columns"]) > 0
    assert len(geometry["doors"]) > 0
    plate = geometry["spaces"][0]
    assert plate[0] == plate[-1] and len(plate) >= 4  # closed floor plate first
    assert len(geometry["spaces"]) > 1  # plus the SVG rooms

    bounds = body["bounds"]
    extent_m = max(bounds["xmax"] - bounds["xmin"], bounds["ymax"] - bounds["ymin"]) * body["units_to_metres"]
    assert 2.0 <= extent_m <= 200.0

    # 5-point Smart Path route through doors spread west -> east across the floor.
    doors = sorted(geometry["doors"], key=lambda d: _display_centroid(d)[0])
    picks = [doors[round(i * (len(doors) - 1) / 4)] for i in range(5)]
    points = [_display_centroid(d) for d in picks]
    route = client.post("/api/autopath", json={"points": points})
    assert route.status_code == 200
    waypoints = route.get_json()["waypoints"]
    assert waypoints and len(waypoints) >= 5
