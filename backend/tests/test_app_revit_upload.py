import copy
import io
import json
import re
from pathlib import Path

import pytest

import app as app_module

FIXTURE = Path(__file__).parent / "fixtures" / "revit_level.json"
U = 0.3048


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def payload():
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _post(client, p=None):
    return client.post("/api/upload-revit", json=payload() if p is None else p)


def _positions(xml: str) -> list:
    return [tuple(float(v) for v in m) for m in re.findall(r'<Position x="([-\d.]+)" y="([-\d.]+)" z="([-\d.]+)"', xml)]


def test_upload_returns_upload_shaped_response_with_source_revit(client):
    resp = _post(client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "revit"
    assert body["units_to_metres"] == U
    assert {"svg", "bounds", "level", "elevation", "plan", "room_issues"} <= body.keys()
    assert body["room_issues"] == []
    assert {"walls", "spaces", "doors", "columns", "windows", "furniture", "meshes"} <= body["geometry"].keys()
    assert body["plan"]["enscape_offset"] is None


def test_bad_payload_returns_400_with_message(client):
    bad = payload()
    bad["schema"] = 99
    resp = _post(client, bad)
    assert resp.status_code == 400
    assert "schema" in resp.get_json()["error"]
    assert client.post("/api/upload-revit", data="not json", content_type="text/plain").status_code == 400


def test_current_returns_last_upload_and_404_before(client):
    assert client.get("/api/revit/current").status_code == 404
    posted = _post(client).get_json()
    got = client.get("/api/revit/current")
    assert got.status_code == 200 and got.get_json() == posted


def test_autopath_routes_on_revit_level(client):
    _post(client)
    resp = client.post("/api/autopath", json={"start": [5, -20], "end": [55, -20]})
    assert resp.status_code == 200
    wps = resp.get_json()["waypoints"]
    assert len(wps) >= 2
    assert all(-24.5 <= w[1] <= -15.5 for w in wps)     # stays in the corridor (display y = -model y)


def test_auto_tour_and_suggest_work(client):
    _post(client)
    assert client.post("/api/auto-tour", json={}).status_code == 200
    assert client.post("/api/auto-tour", json={"suggest": True}).status_code == 200


def test_no_rooms_autopath_ok_tour_explains(client):
    p = payload()
    p["rooms"] = []
    resp = _post(client, p)
    assert resp.status_code == 200 and resp.get_json()["plan"] is None
    assert client.post("/api/autopath", json={"start": [5, -20], "end": [55, -20]}).status_code == 200
    tour = client.post("/api/auto-tour", json={})
    assert tour.status_code == 400
    assert "Rooms" in tour.get_json()["error"]


def test_qbiq_json_after_revit_replaces_level(client):
    from tests.test_qbiq_design import DESIGN
    _post(client)
    revit_plan = app_module._LAST_PLAN
    up = client.post("/api/upload-qbiq-design",
                     data={"json_file": (io.BytesIO(json.dumps(DESIGN).encode("utf-8")), "d.json")},
                     content_type="multipart/form-data")
    assert up.status_code == 200 and up.get_json()["source"] == "qbiq"
    assert app_module._LAST_PLAN is not revit_plan


def test_xml_export_is_in_model_metres(client):
    _post(client)
    body = {"waypoints": [[10, -20, 0, "", None], [50, -20, 0, "", None]], "cuts": [],
            "settings": {"duration": 10, "units_to_metres": U}}
    r = client.post("/api/export/xml", json=body)
    assert r.status_code == 200
    x, _, z = _positions(r.data.decode())[0]
    assert (x, z) == pytest.approx((10 * U, -20 * U), abs=0.002)   # no qbiq offset: true model coordinates


def test_far_from_origin_xml_exact(client):
    p = payload()
    far = 100000.0
    p["walls"] = [[[x + far, y + far] for x, y in w] for w in p["walls"]]
    p["doors"] = [[[x + far, y + far] for x, y in d] for d in p["doors"]]
    p["rooms"] = []
    assert _post(client, p).status_code == 200
    body = {"waypoints": [[far + 10, -(far + 20.5), 0, "", None], [far + 50, -(far + 20.5), 0, "", None]], "cuts": [],
            "settings": {"duration": 10, "units_to_metres": U}}
    r = client.post("/api/export/xml", json=body)
    x, _, z = _positions(r.data.decode())[0]
    assert (x, z) == pytest.approx(((far + 10) * U, -(far + 20.5) * U), abs=0.001)


def test_response_meshes_are_reduced_to_the_budget(client, monkeypatch):
    monkeypatch.setenv("QBIQ_MAX_MESH_VERTICES", "100")
    p = payload()
    cube = [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1]
    p["meshes"] += [{"type": "furniture", "verts": [c + i * 3 * (n % 3 == 0) for n, c in enumerate(cube)],
                     "faces": [0, 1, 2], "color": f"#00{i:04x}", "opacity": None} for i in range(30)]
    meshes = _post(client, p).get_json()["geometry"]["meshes"]
    assert sum(len(m["verts"]) // 3 for m in meshes) <= 100
    assert any(m["type"] == "floor" for m in meshes)
