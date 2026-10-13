import io
import json

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


_JSON_FIXTURE = {
    "perimeter_ls": [[[0, 0], [2000, 0]], [[2000, 0], [2000, 1500]],
                     [[2000, 1500], [0, 1500]], [[0, 1500], [0, 0]]],
    "core_ls": [], "columns_ls": [], "qbiq_walls_ls": [], "mullions": [],
    "perimeter": [], "core": [], "columns": [], "qbiq_walls": [],
}

_SVG_FIXTURE = """<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
<desc>job_code="TEST0001"</desc>
<g id="maing"><g id="designg"><g id="prop">
<g id="ext"></g>
<g id="rooms">
<path fill="#E9D8A6" stroke="#000000" stroke-width="1.42" class="d0 r1 office c1 h1 a1"
      d="M 0,0 L 500,0 L 500,500 L 0,500 L 0,0 z" />
</g>
<g id="cols"></g>
</g></g></g>
</svg>"""


def json_bytes():
    return io.BytesIO(json.dumps(_JSON_FIXTURE).encode("utf-8"))


def svg_bytes():
    return io.BytesIO(_SVG_FIXTURE.encode("utf-8"))


def _post_pair(client, **extra):
    return client.post(
        "/api/upload-qbiq",
        data={"json_file": (json_bytes(), "job.json"), "svg_file": (svg_bytes(), "job.svg"), **extra},
        content_type="multipart/form-data",
    )


def test_upload_qbiq_returns_upload_shaped_response(client):
    resp = _post_pair(client, level="L-2")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "qbiq"
    assert body["level"] == "L-2"
    assert body["units_to_metres"] == 0.01
    assert "geometry" in body and "walls" in body["geometry"]
    assert len(body["geometry"]["walls"]) >= 1
    assert len(body["geometry"]["spaces"]) == 2


def test_upload_qbiq_populates_the_same_caches_as_dxf_upload(client):
    assert _post_pair(client).status_code == 200
    # Smart Path must work immediately after a qbiq upload, exactly like
    # after a DXF upload, since it reads the same _LAST_* caches. Points are in
    # SVG-display space (Y negated); the route runs over open floor outside
    # the room, so it only works because the floor plate is in the footprint.
    assert len(app_module._LAST_FOOTPRINT["dxf"]) == 2
    assert app_module._LAST_WALLS["dxf"]
    autopath_resp = client.post("/api/autopath", json={
        "start": [1000, -750],
        "end": [1800, -1300],
    })
    assert autopath_resp.status_code == 200
    assert len(autopath_resp.get_json()["waypoints"]) >= 2


def test_upload_qbiq_clears_stale_ifc_caches(client):
    app_module._LAST_WALLS["ifc"] = [[(0.0, 0.0), (1.0, 1.0)]]
    assert _post_pair(client).status_code == 200
    assert app_module._LAST_WALLS["ifc"] == []


def test_upload_qbiq_missing_file_field_returns_400(client):
    resp = client.post(
        "/api/upload-qbiq",
        data={"json_file": (json_bytes(), "job.json")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_qbiq_removes_uploaded_files(client):
    before = set(app_module.UPLOAD_DIR.iterdir())
    assert _post_pair(client).status_code == 200
    assert set(app_module.UPLOAD_DIR.iterdir()) == before


def test_upload_qbiq_rejects_filename_that_sanitises_to_empty(client):
    resp = client.post(
        "/api/upload-qbiq",
        data={"json_file": (json_bytes(), "../.."), "svg_file": (svg_bytes(), "job.svg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
