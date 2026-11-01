"""Routes may walk through open areas (minus furniture), never through closed or back-of-house rooms."""
import copy

import pytest
from shapely.geometry import Point

import plan_model as pm
import plan_routing as pr
import qbiq_scene3d as s3
from tests.test_plan_model import DATA, U


def _desk(x, y, w=100, d=60):
    return {"name": "QBIQ_DESK#1", "bom_data": "D_120", "show": True, "is_remove": False,
            "geom_box": f"POLYGON ((0 0, {w} 0, {w} {d}, 0 {d}, 0 0))",
            "matrix": [[1, 0, x], [0, 1, y], [0, 0, 1]], "original_matrix3d": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}


def _data(**rooms):
    """DATA with room fields overridden by id, e.g. B={"stencil_geometry_components": [...]}."""
    data = copy.deepcopy(DATA)
    for r in data["rooms"]:
        r.update(rooms.get(r["id"], {}))
    return data


def _walk(data):
    return pm.build_plan_model(data, U).walkable


def test_walkable_covers_corridor_and_open_room_floor():
    w = _walk(DATA)
    assert w.covers(Point(100, 500)) and w.covers(Point(1200, 900)) and w.covers(Point(1500, 200))


def test_walkable_keeps_clear_of_furniture():
    w = _walk(_data(B={"stencil_geometry_components": [_desk(1400, 750)]}))
    assert not w.covers(Point(1450, 780))          # on the desk
    assert not w.covers(Point(1450, 840))          # 30 cm from it: inside the 35 cm clearance
    assert w.covers(Point(1450, 870))              # 60 cm from it


def test_walkable_excludes_closed_rooms():
    w = _walk(DATA)
    assert not w.covers(Point(400, 800)) and not w.covers(Point(400, 200))   # A conference, C storage


def test_walkable_excludes_open_back_of_house_and_tiny_areas():
    w = _walk(_data(D={"space_type": "Print Hub"}))
    assert not w.covers(Point(1500, 200))
    tiny = "POLYGON ((1000 600, 1250 600, 1250 900, 1000 900, 1000 600))"      # 7.5 m²
    assert not _walk(_data(B={"geometry": tiny})).covers(Point(1100, 800))


def test_open_room_reached_only_through_furniture_is_dropped():
    wall_of_desks = [_desk(1000 + 100 * i, 600, d=40) for i in range(10)]
    w = _walk(_data(B={"stencil_geometry_components": wall_of_desks}))
    assert not w.covers(Point(1500, 900))


def test_hidden_or_broken_components_are_ignored():
    hidden = _desk(1400, 750) | {"show": "false"}
    broken = {"name": "X", "geom_box": "not wkt"}
    w = _walk(_data(B={"stencil_geometry_components": [hidden, broken]}))
    assert w.covers(Point(1450, 780))


def test_component_footprint_uses_matrix_placement():
    comp = _desk(5000, 3000, 100, 45) | {"matrix3d": [[1, 0, -7000], [0, 1, 800], [0, 0, 1]]}
    assert s3.component_footprint(comp).bounds == pytest.approx((5000, 3000, 5100, 3045))
    assert s3.component_footprint(comp | {"is_remove": True}) is None


def test_flipped_plan_flips_walkable():
    assert pm.flipped(pm.build_plan_model(DATA, U)).walkable.covers(Point(1200, -900))


def test_route_graph_reaches_into_open_rooms():
    plan = pm.flipped(pm.build_plan_model(DATA, U))
    _, graph = pr.corridor_graph_for(plan, 0.2)
    b = next(r for r in plan.rooms if r.id == "B").polygon.buffer(-50)
    assert any(b.covers(Point(n)) for n in graph.nodes)


def test_gap_between_furniture_narrower_than_a_person_is_not_walked():
    # desks along B's corridor edge leave a 1.1 m slot; minus 0.35 m clearance each side = 0.4 m < 0.6 m walk width
    desks = [_desk(1000 + 90 * i, 610, w=90, d=40) for i in range(5)] + [_desk(1560 + 88 * i, 610, w=88, d=40) for i in range(5)]
    w = _walk(_data(B={"stencil_geometry_components": desks}))
    assert not w.covers(Point(1500, 900))
