import io
import json

import pytest

import app as app_module
from tests.test_qbiq_design import DESIGN


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _post(client, payload=DESIGN, name="design.json"):
    return client.post(
        "/api/upload-qbiq-design",
        data={"json_file": (io.BytesIO(json.dumps(payload).encode("utf-8")), name)},
        content_type="multipart/form-data",
    )


def test_upload_returns_upload_shaped_response(client):
    resp = _post(client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "qbiq"
    assert body["units_to_metres"] == 0.01
    assert {"svg", "bounds", "level", "elevation"} <= body.keys()
    geometry = body["geometry"]
    assert {"walls", "spaces", "doors", "columns", "windows", "furniture", "meshes"} <= geometry.keys()
    assert geometry["furniture"]
    assert len(geometry["spaces"]) == 3


def test_missing_field_returns_400(client):
    resp = client.post("/api/upload-qbiq-design", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_non_design_json_returns_400(client):
    resp = _post(client, {"perimeter_ls": [], "columns_ls": []})
    assert resp.status_code == 400
    assert "design" in resp.get_json()["error"]


def test_filename_that_sanitises_to_empty_returns_400(client):
    assert _post(client, name="../..").status_code == 400


def test_uploaded_files_are_removed(client):
    before = set(app_module.UPLOAD_DIR.iterdir())
    assert _post(client).status_code == 200
    assert _post(client, {"rooms": []}).status_code == 400
    assert set(app_module.UPLOAD_DIR.iterdir()) == before


def test_autopath_routes_over_open_floor_after_upload(client):
    assert _post(client).status_code == 200
    resp = client.post("/api/autopath", json={"start": [1000, -750], "end": [1200, -300]})
    assert resp.status_code == 200
    assert len(resp.get_json()["waypoints"]) >= 2
