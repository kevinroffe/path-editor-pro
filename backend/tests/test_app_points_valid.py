import copy
import json
from pathlib import Path

import pytest

import app as app_module

FIXTURE = Path(__file__).parent / "fixtures" / "revit_level.json"


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _load(client, rooms=True):
    p = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))
    if not rooms:
        p["rooms"] = []
    assert client.post("/api/upload-revit", json=p).status_code == 200


def _valid(client, points):
    r = client.post("/api/points-valid", json={"points": points})
    assert r.status_code == 200
    return r.get_json()["valid"]


def test_inside_walkable_true(client):
    _load(client)
    assert _valid(client, [[5, -20], [30, -20], [55, -20]]) == [True, True, True]


def test_outside_walkable_false(client):
    _load(client)
    assert _valid(client, [[10, -30], [-5, -20]]) == [False, False]    # inside the conference room; outside the building


def test_no_plan_uses_obstacles(client):
    _load(client, rooms=False)
    assert _valid(client, [[20, -30], [30, -20]]) == [False, True]     # on the x=20 partition wall; in open corridor


def test_nothing_loaded_everything_valid(client):
    assert _valid(client, [[1, 1]]) == [True]


def test_empty_list_ok(client):
    _load(client)
    assert _valid(client, []) == []


def test_non_point_400(client):
    _load(client)
    assert client.post("/api/points-valid", json={"points": [[1], "a"]}).status_code == 400
    assert client.post("/api/points-valid", json={}).status_code == 400
