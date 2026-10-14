import io
import json

import pytest

import app as app_module
from plan_routing import CorridorBlocked
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


def test_plan_failure_still_loads_floor_plan(client, monkeypatch):
    import plan_model

    def boom(*_args, **_kwargs):
        raise RuntimeError("plan exploded")

    monkeypatch.setattr(plan_model, "build_plan_model", boom)
    r = client.post("/api/upload-qbiq-design", data={"json_file": (_design_json(), "d.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["plan"] is None
    assert app_module._LAST_PLAN is None


def test_demo_clears_plan(client):
    client.post("/api/upload-qbiq-design", data={"json_file": (_design_json(), "d.json")},
                content_type="multipart/form-data")
    r = client.get("/api/demo")
    assert r.status_code == 200
    assert r.get_json()["plan"] is None
    assert app_module._LAST_PLAN is None


def _load_plan(client):
    r = client.post("/api/upload-qbiq-design", data={"json_file": (_design_json(), "d.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()


def _no_plan_routing(monkeypatch):
    def boom(*_args, **_kwargs):
        raise CorridorBlocked("route_on_plan must not be used")

    monkeypatch.setattr(app_module, "route_on_plan", boom)


@pytest.mark.parametrize("geometry", [{"footprint": [[[0, 0], [10, 0], [10, 10]]]}, {"doors": [[[5, 5], [15, 5]]]}])
def test_autopath_explicit_footprint_or_doors_skips_plan_routing(client, monkeypatch, geometry):
    _load_plan(client)
    _no_plan_routing(monkeypatch)
    r = client.post("/api/autopath", json={"points": [[50, -500], [1950, -500]], **geometry})
    assert "route_on_plan must not be used" not in r.get_data(as_text=True)


def test_autopath_plan_unexpected_error_is_400_not_500(client, monkeypatch):
    _load_plan(client)

    def boom(*_args, **_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(app_module, "route_on_plan", boom)
    r = client.post("/api/autopath", json={"points": [[50, -500], [1950, -500]]})
    assert r.status_code == 400
    assert "error" in r.get_json()
