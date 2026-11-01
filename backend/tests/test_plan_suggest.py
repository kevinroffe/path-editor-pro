"""Suggested tour: the rooms a designer would show, within a walking budget, in route order."""
import copy

import pytest

import plan_model as pm
import plan_routing as pr
import plan_suggest as ps
from tests.test_plan_model import DATA, U, _door, _room

# 40 m corridor (y 400..600); offices above every 5 m, a kitchen (open) at the far east end below.
LONG = {
    "circulation": "POLYGON ((0 400, 4000 400, 4000 600, 0 600, 0 400))",
    "rooms": [_room(f"O{i}", "Office - Receiving Guests",
                    f"POLYGON (({500 * i} 600, {500 * i + 450} 600, {500 * i + 450} 1000, {500 * i} 1000, {500 * i} 600))",
                    [_door(f"LINESTRING ({500 * i} 600, {500 * i + 450} 600)",
                           geom=f"GEOMETRYCOLLECTION (LINESTRING ({500 * i + 200} 600, {500 * i + 200} 610), "
                                f"LINESTRING ({500 * i + 290} 600, {500 * i + 290} 610))")]) for i in range(8)]
    + [_room("K", "Kitchen", "POLYGON ((3000 0, 4000 0, 4000 400, 3000 400, 3000 0))",
             [_door("LINESTRING (3000 400, 4000 400)", shown=False)]),
       _room("S", "Storage Room", "POLYGON ((0 0, 800 0, 800 400, 0 400, 0 0))",
             [_door("LINESTRING (0 400, 800 400)",
                    geom="GEOMETRYCOLLECTION (LINESTRING (300 400, 300 390), LINESTRING (390 400, 390 390))")])],
    "nfp_data": {"main_entrance": "POINT (0 500)", "columns": None},
}


def _suggest(data, budget_m, start=None):
    plan = pm.flipped(pm.build_plan_model(data, U))
    polygon, graph = pr.corridor_graph_for(plan, 0.2)
    return plan, ps.suggest_room_ids(plan, graph, polygon, start or plan.entrance, budget_m)


def test_long_budget_walks_the_wing_into_the_kitchen():
    _, ids = _suggest(LONG, 60)
    assert "K" in ids and ids[-1] in ("K", "O7")            # into the kitchen, and on to the end of the wing
    assert [i for i in ids if i.startswith("O")] == sorted(i for i in ids if i.startswith("O"))   # in route order


def test_short_budget_keeps_the_best_value_per_metre():
    _, ids = _suggest(LONG, 8)
    assert ids and "K" not in ids and all(i.startswith("O") for i in ids)


def test_rooms_passed_on_the_way_are_glanced_at_without_being_targets():
    _, ids = _suggest(LONG, 60)
    assert len([i for i in ids if i.startswith("O")]) >= 4


def test_glances_are_at_least_5_m_apart():
    plan, ids = _suggest(LONG, 60)
    xs = [next(r for r in plan.rooms if r.id == i).stop.point[0] for i in ids if i.startswith("O")]
    assert all(b - a >= ps.MIN_LOOK_GAP_M / U - 1 for a, b in zip(xs, xs[1:]))


def test_no_duplicates_and_never_back_of_house():
    _, ids = _suggest(LONG, 60)
    assert len(ids) == len(set(ids)) and "S" not in ids


def test_budget_respected():
    plan, ids = _suggest(LONG, 25)
    tour = pr.route_on_plan(plan, [plan.entrance] + [next(r for r in plan.rooms if r.id == i).stop.point for i in ids],
                            lambda c: pr.corridor_graph_for(plan, c))
    length_m = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(tour["waypoints"], tour["waypoints"][1:])) * U
    assert length_m <= 25 * 1.1


def test_nothing_to_show_raises():
    data = copy.deepcopy(DATA)
    data["rooms"] = [r for r in data["rooms"] if r["space_type"] == "Storage Room"]
    with pytest.raises(ValueError, match="no rooms"):
        _suggest(data, 60)


def test_start_on_a_door_shared_by_two_facing_offices():
    # an office below O0 with its door straight opposite: both doors' walking-line points coincide with the start
    data = copy.deepcopy(LONG)
    data["rooms"] = [r for r in data["rooms"] if r["id"] != "S"] + [_room(
        "P", "Office - Receiving Guests", "POLYGON ((0 0, 450 0, 450 400, 0 400, 0 0))",
        [_door("LINESTRING (0 400, 450 400)",
               geom="GEOMETRYCOLLECTION (LINESTRING (200 400, 200 390), LINESTRING (290 400, 290 390))")])]
    plan = pm.flipped(pm.build_plan_model(data, U))
    polygon, graph = pr.corridor_graph_for(plan, 0.2)
    o0 = next(t for t in ps._targets(plan, graph) if t.room.id == "O0")
    ids = ps.suggest_room_ids(plan, graph, polygon, o0.go, 30)
    assert "O0" in ids                      # no crash on the zero-length walk; P is thinned (same spot as O0)
