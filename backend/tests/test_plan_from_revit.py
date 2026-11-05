import copy
import json
from pathlib import Path

from shapely.geometry import Point

from plan_from_revit import SPACE_TYPE_KEYWORDS, build_revit_plan

FIXTURE = Path(__file__).parent / "fixtures" / "revit_level.json"
U = 0.3048


def payload():
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _without_corridor(p):
    """No corridor room; a room fills the south-east corner so the only uncovered floor is the corridor strip."""
    p["rooms"] = [r for r in p["rooms"] if r["name"] != "Corridor"]
    p["rooms"].append({"id": "r8", "name": "Print Room", "number": "107", "polygon": [[40, 0], [60, 0], [60, 16], [40, 16]],
                       "area": 320.0, "placed": True, "enclosed": True})
    return p


def test_named_corridor_becomes_corridor():
    plan = build_revit_plan(payload())
    assert abs(plan.corridor.area - 480) < 1          # 60 ft x 8 ft strip
    assert {r.id for r in plan.rooms} == {"r2", "r3", "r4", "r5", "r6"}   # the corridor is not a room


def test_corridor_inferred_when_unnamed():
    plan = build_revit_plan(_without_corridor(payload()))
    assert plan is not None
    assert abs(plan.corridor.area - 480) < 1          # uncovered floor between the rooms


def test_space_type_from_english_names():
    plan = build_revit_plan(payload())
    got = {r.id: r.space_type for r in plan.rooms}
    assert got == {"r2": "Conference", "r3": "Kitchen", "r4": "Office", "r5": "Reception", "r6": "Storage Room"}
    assert SPACE_TYPE_KEYWORDS["conference"] == "Conference"


def test_unknown_room_has_none_space_type_and_does_not_crash():
    p = payload()
    p["rooms"].append({"id": "r7", "name": "Mystery", "number": "106", "polygon": [[40, 0], [60, 0], [60, 16], [40, 16]],
                       "area": 320.0, "placed": True, "enclosed": True})
    plan = build_revit_plan(p)
    mystery = next(r for r in plan.rooms if r.id == "r7")
    assert mystery.space_type is None and mystery.stop.point is not None


def test_stops_sit_in_the_corridor():
    plan = build_revit_plan(payload())
    for r in plan.rooms:
        assert plan.corridor.buffer(0.5).covers(Point(r.stop.point)), r.id


def test_entrance_is_reception_stop():
    plan = build_revit_plan(payload())
    reception = next(r for r in plan.rooms if r.space_type == "Reception")
    assert plan.entrance == reception.stop.point


def test_no_rooms_returns_none():
    p = payload()
    p["rooms"] = []
    assert build_revit_plan(p) is None


def test_all_unplaced_returns_none():
    p = payload()
    for r in p["rooms"]:
        r["placed"], r["polygon"] = False, None
    assert build_revit_plan(p) is None


def test_enscape_offset_is_none_and_units_are_feet():
    plan = build_revit_plan(payload())
    assert plan.enscape_offset is None and plan.units_to_metres == U
