import io
import json

import pytest

import app as app_module
from tests.test_plan_model import DATA


def _design_json():
    data = json.loads(json.dumps(DATA))
    data["nfp_data"].update({
        "fill": "POLYGON ((0 0, 2000 0, 2000 1000, 0 1000, 0 0))",
        "walls": [{"corner1": [0, 0], "corner2": [2000, 0]}],
        "interior_walls": [], "cores": [], "windows": [], "columns": None,
    })
    return io.BytesIO(json.dumps(data).encode())


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_design_upload_returns_and_caches_display_space_plan(client):
    r = client.post("/api/upload-qbiq-design", data={"json_file": (_design_json(), "d.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    plan = r.get_json()["plan"]
    assert plan and len(plan["rooms"]) == 4
    a = next(x for x in plan["rooms"] if x["id"] == "A")
    assert a["stop"]["point"][1] == pytest.approx(-540.0)   # display space
    assert app_module._LAST_PLAN is not None
    assert app_module._LAST_PLAN.entrance[1] == pytest.approx(-460.0, abs=1.0)


def test_demo_clears_plan(client):
    client.post("/api/upload-qbiq-design", data={"json_file": (_design_json(), "d.json")},
                content_type="multipart/form-data")
    r = client.get("/api/demo")
    assert r.status_code == 200
    assert r.get_json()["plan"] is None
    assert app_module._LAST_PLAN is None
