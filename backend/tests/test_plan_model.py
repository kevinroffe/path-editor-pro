import pytest
from shapely.geometry import Point

import plan_model as pm

U = 0.01  # 1 unit = 1 cm


def _room(rid, space_type, poly_wkt, doors, door_geometry=None):
    return {"id": rid, "space_type": space_type, "subtype": None, "geometry": poly_wkt,
            "doors": doors, "door_geometry": door_geometry, "head_count": 4,
            "assigned_hc": 3, "department_id": 1, "stencil_geometry": None,
            "stencil_geometry_components": []}


def _door(line_wkt, shown=True, geom=None):
    return {"door_line": line_wkt, "show_door": shown, "door_geometry": geom}


# 20 m x 10 m floor; corridor band y 400..600 across the full width.
# A: enclosed Conference above the corridor, door on y=600 at x 300..400.
# B: open Open Space above the corridor (door hidden).
# C: enclosed Storage below the corridor, door on y=400 at x 500..590.
# D: open Reception below the corridor holding the main entrance.
DATA = {
    "circulation": "POLYGON ((0 400, 2000 400, 2000 600, 0 600, 0 400))",
    "rooms": [
        _room("A", "Conference", "POLYGON ((0 600, 800 600, 800 1000, 0 1000, 0 600))",
              [_door("LINESTRING (0 600, 800 600)",
                     geom="GEOMETRYCOLLECTION (LINESTRING (300 600, 300 610), LINESTRING (400 600, 400 610))")]),
        _room("B", "Open Space WorkStation", "POLYGON ((1000 600, 2000 600, 2000 1000, 1000 1000, 1000 600))",
              [_door("LINESTRING (1000 600, 2000 600)", shown=False)]),
        _room("C", "Storage Room", "POLYGON ((0 0, 800 0, 800 400, 0 400, 0 0))",
              [_door("LINESTRING (0 400, 800 400)",
                     geom="GEOMETRYCOLLECTION (LINESTRING (500 400, 500 390), LINESTRING (590 400, 590 390))")]),
        _room("D", "Reception", "POLYGON ((800 0, 2000 0, 2000 400, 800 400, 800 0))",
              [_door("LINESTRING (800 400, 2000 400)", shown=False)]),
    ],
    "nfp_data": {"main_entrance": "POINT (1500 0)", "columns": None},
}


@pytest.fixture
def plan():
    return pm.build_plan_model(DATA, U)


def _by_id(plan, rid):
    return next(r for r in plan.rooms if r.id == rid)


def test_corridor_is_top_level_circulation(plan):
    assert plan.corridor.area == pytest.approx(2000 * 200)


def test_open_vs_enclosed(plan):
    assert not _by_id(plan, "A").is_open
    assert _by_id(plan, "B").is_open
    assert not _by_id(plan, "C").is_open
    assert _by_id(plan, "D").is_open


def test_enclosed_room_stop_in_corridor_in_front_of_door(plan):
    a = _by_id(plan, "A")
    assert a.stop.point == pytest.approx((350.0, 540.0))
    assert plan.corridor.covers(Point(a.stop.point))
    assert a.polygon.covers(Point(a.stop.look_at))
    c = _by_id(plan, "C")
    assert c.stop.point == pytest.approx((545.0, 460.0))


def test_open_area_stop_is_inside_its_free_floor(plan):
    b = _by_id(plan, "B")
    assert b.polygon.buffer(-100).covers(Point(b.stop.point))        # walked into, at least 1 m from its edges
    assert plan.walkable.covers(Point(b.stop.point)) and b.stop.walk_in
    assert b.stop.look_at == b.label_point                           # pans and snapshots still aim into the room
    assert not _by_id(plan, "A").stop.walk_in


def test_open_area_too_small_to_walk_keeps_its_edge_stop():
    data = {**DATA, "rooms": [dict(r, geometry="POLYGON ((1000 600, 1250 600, 1250 900, 1000 900, 1000 600))")
                              if r["id"] == "B" else r for r in DATA["rooms"]]}
    b = _by_id(pm.build_plan_model(data, U), "B")
    assert b.stop.point[1] == pytest.approx(540.0, abs=1.0)


def test_entrance_snapped_into_corridor(plan):
    assert plan.entrance[0] == pytest.approx(1500.0, abs=1.0)
    assert plan.entrance[1] == pytest.approx(460.0, abs=1.0)


def test_dwell_by_type():
    assert pm.dwell_for("Conference") == 3.0
    assert pm.dwell_for("Office - Non Receiving Guests") == 2.0
    assert pm.dwell_for("Kitchen") == 2.0
    assert pm.dwell_for("Storage Room") == 1.5
    assert pm.dwell_for(None) == 1.5


def test_room_info_fields(plan):
    a = _by_id(plan, "A")
    assert a.area_m2 == pytest.approx(32.0)
    assert (a.head_count, a.assigned_hc, a.department_id) == (4, 3, 1)


def test_flipped_negates_y(plan):
    f = pm.flipped(plan)
    assert _by_id(f, "A").stop.point == pytest.approx((350.0, -540.0))
    assert f.entrance[1] == pytest.approx(-plan.entrance[1])
    assert f.corridor.bounds[1] == pytest.approx(-600.0)


def test_room_at(plan):
    assert pm.room_at(plan, (100, 900)).id == "A"
    assert pm.room_at(plan, (100, 500)) is None


def test_no_circulation_returns_none():
    assert pm.build_plan_model({**DATA, "circulation": None}, U) is None


def test_plan_to_json_shape(plan):
    js = pm.plan_to_json(plan)
    assert set(js) == {"corridor", "rooms", "entrance", "enscape_offset", "default_tour_types"}
    r = js["rooms"][0]
    assert {"id", "name", "type", "area_m2", "head_count", "assigned_hc",
            "department_id", "polygon", "label_point", "is_open", "stop"} <= set(r)
    assert "Storage Room" not in js["default_tour_types"]


def test_open_area_slightly_off_corridor_still_uses_shared_edge():
    data = {**DATA, "rooms": [_room(
        "E", "Storage Room", "POLYGON ((1000 600.2, 2000 600.2, 2000 1000, 1000 1000, 1000 600.2))",
        [_door("LINESTRING (1000 600.2, 2000 600.2)", shown=False)])]}
    e = pm.build_plan_model(data, U).rooms[0]
    assert e.stop.warning is None
    assert e.stop.point[0] == pytest.approx(1500.0, abs=1.0)
    assert e.stop.point[1] == pytest.approx(540.0, abs=1.0)


def test_door_stop_never_on_room_side():
    data = {
        "circulation": ["POLYGON ((0 300, 2000 300, 2000 380, 0 380, 0 300))",
                        "POLYGON ((215 760, 300 760, 300 1000, 215 1000, 215 760))"],
        "rooms": [_room("A", "Conference", "POLYGON ((0 600, 200 600, 200 1000, 0 1000, 0 600))",
                        [_door("LINESTRING (0 600, 200 600)",
                               geom="GEOMETRYCOLLECTION (LINESTRING (50 600, 50 610), LINESTRING (150 600, 150 610))")])],
        "nfp_data": {},
    }
    plan = pm.build_plan_model(data, U)
    a = plan.rooms[0]
    assert not a.polygon.covers(Point(a.stop.point))
    assert plan.corridor.covers(Point(a.stop.point))
    assert a.stop.point[1] < 400


def test_room_ids_are_unique():
    dup = _room("A", "Kitchen", "POLYGON ((1000 0, 1500 0, 1500 400, 1000 400, 1000 0))", [])
    plan = pm.build_plan_model({**DATA, "rooms": DATA["rooms"] + [dup, dup]}, U)
    ids = [r.id for r in plan.rooms]
    assert len(set(ids)) == len(ids)
    assert ids[:4] == ["A", "B", "C", "D"] and ids[4:] == ["A#2", "A#3"]
