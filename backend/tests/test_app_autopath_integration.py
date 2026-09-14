import io
import json

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _upload_demo(client):
    resp = client.get("/api/demo")
    assert resp.status_code == 200
    return resp.get_json()


def test_autopath_uses_corridor_graph_when_available(client, monkeypatch):
    _upload_demo(client)

    calls = {"route_multi": 0}
    real_route_multi = app_module.route_multi

    def spy_route_multi(*args, **kwargs):
        calls["route_multi"] += 1
        return real_route_multi(*args, **kwargs)

    monkeypatch.setattr(app_module, "route_multi", spy_route_multi)

    resp = client.post("/api/autopath", json={"start": [1, 1], "end": [2, 2]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "waypoints" in data
    assert calls["route_multi"] >= 1


def test_autopath_falls_back_to_grid_astar_when_graph_build_fails(client, monkeypatch):
    _upload_demo(client)

    monkeypatch.setattr(app_module, "build_corridor_graph", lambda *a, **k: None)

    calls = {"find_multi_path": 0}
    real_find_multi_path = app_module.find_multi_path

    def spy(*args, **kwargs):
        calls["find_multi_path"] += 1
        return real_find_multi_path(*args, **kwargs)

    monkeypatch.setattr(app_module, "find_multi_path", spy)

    resp = client.post("/api/autopath", json={"start": [1, 1], "end": [2, 2]})
    assert resp.status_code == 200
    assert calls["find_multi_path"] == 1


def test_autopath_falls_back_when_route_multi_returns_none(client, monkeypatch):
    _upload_demo(client)

    monkeypatch.setattr(app_module, "route_multi", lambda *a, **k: None)

    calls = {"find_multi_path": 0}
    real_find_multi_path = app_module.find_multi_path

    def spy(*args, **kwargs):
        calls["find_multi_path"] += 1
        return real_find_multi_path(*args, **kwargs)

    monkeypatch.setattr(app_module, "find_multi_path", spy)

    resp = client.post("/api/autopath", json={"start": [1, 1], "end": [2, 2]})
    assert resp.status_code == 200
    assert calls["find_multi_path"] == 1


def test_upload_bumps_generation_and_invalidates_graph_cache(client):
    gen_before = app_module._UPLOAD_GENERATION
    _upload_demo(client)
    assert app_module._UPLOAD_GENERATION > gen_before
