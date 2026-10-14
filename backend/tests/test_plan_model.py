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


def test_open_area_stop_on_shared_edge_pushed_into_corridor(plan):
    b = _by_id(plan, "B")
    assert b.stop.point[0] == pytest.approx(1500.0, abs=1.0)
    assert b.stop.point[1] == pytest.approx(540.0, abs=1.0)
    assert plan.corridor.covers(Point(b.stop.point))


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


def test_glance_targets_only_for_enclosed_rooms(plan):
    looks = {t[1] for t in plan.glance_targets}
    assert _by_id(plan, "A").label_point in looks
    assert _by_id(plan, "B").label_point not in looks


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
    assert set(js) == {"corridor", "rooms", "entrance", "default_tour_types"}
    r = js["rooms"][0]
    assert {"id", "name", "type", "area_m2", "head_count", "assigned_hc",
            "department_id", "polygon", "label_point", "is_open", "stop"} <= set(r)
    assert "Storage Room" not in js["default_tour_types"]
