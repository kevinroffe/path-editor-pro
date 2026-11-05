import copy
import json
from pathlib import Path

import pytest

from revit_payload import SCHEMA, parse_revit_payload, room_issues

FIXTURE = Path(__file__).parent / "fixtures" / "revit_level.json"


def payload():
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_parse_fills_levelgeometry():
    p = payload()
    p["rooms"].append({"id": "x", "name": "Ghost", "number": "999", "polygon": None, "area": 0.0,
                       "placed": False, "enclosed": False})
    geo = parse_revit_payload(p)
    assert geo.level_name == "Level 1"
    assert geo.source == "revit"
    assert geo.units_to_metres == 0.3048
    assert len(geo.walls) == len(p["walls"]) and len(geo.doors) == len(p["doors"])
    assert len(geo.columns) == 1 and len(geo.furniture) == 2 and geo.windows == []
    assert geo.meshes == p["meshes"]
    assert len(geo.spaces) == 6  # unplaced room is not a space


def test_bad_schema_raises():
    p = payload()
    p["schema"] = SCHEMA + 1
    with pytest.raises(ValueError, match="schema"):
        parse_revit_payload(p)


def test_empty_level_raises():
    p = payload()
    p["walls"], p["meshes"] = [], []
    with pytest.raises(ValueError, match="level has no geometry"):
        parse_revit_payload(p)


def test_room_issues_flags_each_problem():
    p = payload()
    p["rooms"] += [
        {"id": "a", "name": "A", "number": "201", "polygon": None, "area": 0.0, "placed": False, "enclosed": False},
        {"id": "b", "name": "B", "number": "202", "polygon": None, "area": 10.0, "placed": True, "enclosed": False},
        {"id": "c", "name": "C", "number": "203", "polygon": [[0, 0], [1, 0], [1, 1]], "area": 0.0,
         "placed": True, "enclosed": True},
        {"id": "d1", "name": "D1", "number": "204", "polygon": [[0, 0], [1, 0], [1, 1]], "area": 5.0,
         "placed": True, "enclosed": True},
        {"id": "d2", "name": "D2", "number": "204", "polygon": [[0, 0], [1, 0], [1, 1]], "area": 5.0,
         "placed": True, "enclosed": True},
    ]
    got = {i["room_id"]: i["problem"] for i in room_issues(p)}
    assert got == {"a": "unplaced", "b": "unenclosed", "c": "zero_area", "d1": "duplicate", "d2": "duplicate"}


def test_healthy_fixture_has_no_issues():
    assert room_issues(payload()) == []


def test_non_ascii_names_survive():
    p = payload()
    p["rooms"][1]["name"] = "Café Lounge"
    issues = room_issues(p)
    geo = parse_revit_payload(p)
    assert issues == [] and geo.level_name == "Level 1"
    assert json.loads(json.dumps(p, ensure_ascii=False))["rooms"][1]["name"] == "Café Lounge"
