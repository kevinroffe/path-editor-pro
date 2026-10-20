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


def _demo_geo(*_args, **_kwargs):
    from revit_extractor import _demo_geometry
    return _demo_geometry("L-0")


def test_dxf_upload_clears_plan(client, monkeypatch):
    _load_plan(client)
    monkeypatch.setattr(app_module, "_DXF_AVAILABLE", True)
    monkeypatch.setattr(app_module, "extract_dxf", _demo_geo, raising=False)
    r = client.post("/api/upload", data={"file": (io.BytesIO(b"0\nEOF\n"), "plan.dxf")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["plan"] is None
    assert app_module._LAST_PLAN is None


def test_qbiq_pair_upload_clears_plan(client):
    from tests.test_app_qbiq_upload import _post_pair
    _load_plan(client)
    r = _post_pair(client)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["plan"] is None
    assert app_module._LAST_PLAN is None


def test_upload_3d_preserves_plan(client, monkeypatch):
    _load_plan(client)
    plan = app_module._LAST_PLAN
    monkeypatch.setattr(app_module, "extract_level", _demo_geo)
    r = client.post("/api/upload-3d", data={"file": (io.BytesIO(b"ISO-10303-21;"), "model.ifc")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert app_module._LAST_PLAN is plan
    assert client.post("/api/auto-tour", json={}).status_code == 200


def test_auto_tour_success_on_synthetic_plan(client):
    _load_plan(client)
    r = client.post("/api/auto-tour", json={})
    assert r.status_code == 200, r.get_json()
    tour = r.get_json()
    assert tour["stops"] and tour["suggested_duration_s"] >= 10
    assert tour["unreachable"] == []
    idx = [s["index"] for s in tour["stops"]]
    assert idx == sorted(idx) and all(0 <= i < len(tour["waypoints"]) for i in idx)


def test_plan_graph_cache_is_keyed_on_the_plan(monkeypatch):
    seen = []
    monkeypatch.setattr(app_module, "corridor_graph_for", lambda plan, c: seen.append((plan, c)) or (None, None))
    p1, p2 = object(), object()
    app_module._LAST_PLAN = p2
    for p in (p1, p2, p1):
        app_module._plan_graph(p, 0.2)
    assert seen == [(p1, 0.2), (p2, 0.2)]


def _swap_plan_mid_request(monkeypatch, name):
    """Patch `name` so a concurrent upload replaces _LAST_PLAN before it asks for a graph; returns the plans graphed."""
    seen = []
    monkeypatch.setattr(app_module, "corridor_graph_for", lambda plan, c: seen.append(plan) or (None, None))

    def fake(*args, **kwargs):
        get_graph = next(a for a in args if callable(a))
        app_module._LAST_PLAN = object()
        get_graph(0.123)
        return {"waypoints": [[0, 0], [1, 1]], "stops": [], "suggested_duration_s": 10, "unreachable": []}

    monkeypatch.setattr(app_module, name, fake)
    return seen


def test_autopath_graph_getter_bound_to_request_plan(client, monkeypatch):
    _load_plan(client)
    plan = app_module._LAST_PLAN
    seen = _swap_plan_mid_request(monkeypatch, "route_on_plan")
    client.post("/api/autopath", json={"points": [[50, -500], [1950, -500]]})
    assert seen == [plan]


def test_auto_tour_graph_getter_bound_to_request_plan(client, monkeypatch):
    _load_plan(client)
    plan = app_module._LAST_PLAN
    app_module._plan_graph(plan, 0.2)  # the endpoint's own graph lookup hits this cached real graph
    seen = _swap_plan_mid_request(monkeypatch, "build_tour")
    client.post("/api/auto-tour", json={"clearance_m": 0.2})
    assert seen == [plan]


def test_auto_tour_backs_off_clearance_like_smart_path(client, monkeypatch):
    _load_plan(client)
    real = app_module.corridor_graph_for
    monkeypatch.setattr(app_module, "corridor_graph_for",
                        lambda plan, c: (None, None) if c >= 0.2 else real(plan, c))
    r = client.post("/api/auto-tour", json={"clearance_m": 0.2})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["stops"]


@pytest.mark.parametrize("body", [{"clearance_m": "abc"}, {"smoothing": "abc"}])
def test_auto_tour_bad_numbers_are_400(client, body):
    _load_plan(client)
    r = client.post("/api/auto-tour", json=body)
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_uncontained_route_carries_a_warning(client, monkeypatch):
    import plan_routing
    _load_plan(client)
    monkeypatch.setattr(plan_routing, "_bad_legs", lambda wps, covered, smoothing: {0})
    for url, body in (("/api/autopath", {"points": [[50, -500], [1950, -500]]}), ("/api/auto-tour", {})):
        r = client.post(url, json=body)
        assert r.status_code == 200, r.get_json()
        assert "corridor" in r.get_json()["warning"]


def test_contained_route_has_no_warning(client):
    _load_plan(client)
    assert "warning" not in client.post("/api/autopath", json={"points": [[50, -500], [1950, -500]]}).get_json()


def _untyped_design_json():
    data = json.loads(_design_json().getvalue())
    data["rooms"][0]["space_type"] = None
    return io.BytesIO(json.dumps(data).encode())


def test_untyped_rooms_round_trip_as_null(client):
    r = client.post("/api/upload-qbiq-design", data={"json_file": (_untyped_design_json(), "d.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    a = next(x for x in r.get_json()["plan"]["rooms"] if x["id"] == "A")
    assert a["type"] is None
    tour = client.post("/api/auto-tour", json={"room_types": [None]})
    assert tour.status_code == 200, tour.get_json()
    assert [s["room_id"] for s in tour.get_json()["stops"]] == ["A"]


def test_globals_leak_setup():
    app_module._LAST_PLAN = object()
    app_module._LAST_PLAN_GRAPH["stale"] = (None, None)
    app_module._LAST_WALLS["dxf"] = [[(0, 0), (1, 1)]]


def test_globals_reset_before_each_test():
    assert app_module._LAST_PLAN is None
    assert not app_module._LAST_PLAN_GRAPH
    assert app_module._LAST_WALLS == {"dxf": [], "ifc": []}
