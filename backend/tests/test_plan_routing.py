import networkx as nx
import pytest
from shapely.geometry import LineString, Point, box

import plan_model as pm
import plan_routing as pr
from route_processor import smooth_preview
from tests.test_plan_model import DATA


@pytest.fixture(scope="module")
def plan():
    return pm.flipped(pm.build_plan_model(DATA, 0.01))


@pytest.fixture(scope="module")
def get_graph(plan):
    cache = {}

    def get(c):
        if c not in cache:
            cache[c] = pr.corridor_graph_for(plan, c)
        return cache[c]
    return get


def _inside(plan, pt):
    return plan.corridor.buffer(1e-6).covers(Point(pt))


def test_snap_corridor_point_unchanged(plan):
    pts, metas = pr.snap_points(plan, [(100, -500)])
    assert pts == [(100, -500)] and metas == [None]


def test_snap_room_click_goes_to_its_stop(plan):
    pts, metas = pr.snap_points(plan, [(100, -900)])           # inside room A
    a = next(r for r in plan.rooms if r.id == "A")
    assert pts[0] == pytest.approx(a.stop.point)
    assert metas[0]["room_id"] == "A" and metas[0]["dwell_s"] == 3.0
    assert metas[0]["look_at"] == pytest.approx(list(a.stop.look_at))


def test_snap_outside_goes_to_nearest_corridor(plan):
    pts, _ = pr.snap_points(plan, [(2500, -500)])
    assert _inside(plan, pts[0])


def test_route_stays_in_corridor_and_spline_too(plan, get_graph):
    out = pr.route_on_plan(plan, [(50, -500), (100, -900), (1500, -900), (1950, -500)], get_graph)
    wps = out["waypoints"]
    assert all(_inside(plan, p) for p in wps)
    assert all(_inside(plan, p) for p in smooth_preview(wps, smoothing=1.0))


def test_stops_attached_in_order(plan, get_graph):
    out = pr.route_on_plan(plan, [(50, -500), (100, -900), (1500, -900), (1950, -500)], get_graph)
    assert [s["room_id"] for s in out["stops"]] == ["A", "B"]
    idx = [s["index"] for s in out["stops"]]
    assert idx == sorted(idx)
    a = next(r for r in plan.rooms if r.id == "A")
    assert out["waypoints"][idx[0]] == pytest.approx(list(a.stop.point), abs=1.0)


def test_blocked_corridor_raises(plan):
    with pytest.raises(pr.CorridorBlocked, match="corridor blocked near"):
        pr.route_on_plan(plan, [(50, -500), (1950, -500)], lambda c: (None, None))


def test_contain_spline_inserts_points_until_inside(plan):
    corridor = plan.corridor
    zig = [(50, -410), (1000, -590), (1950, -410)]
    out = pr.contain_spline(zig, corridor, smoothing=1.0)
    assert len(out) >= len(zig)
    assert all(corridor.buffer(1e-6).covers(Point(p)) for p in smooth_preview(out, smoothing=1.0))


def test_contain_spline_out_and_back_attributes_bulge_to_its_own_leg():
    route = [(0, 0), (2000, 0), (2000, -400), (2000, 0), (0, 0), (0, -400)]
    corridor = LineString(route).buffer(40, cap_style=2, join_style=2)
    out = pr.contain_spline(route, corridor, smoothing=1.0)
    assert all(corridor.buffer(1e-6).covers(Point(p)) for p in smooth_preview(out, smoothing=1.0))


def test_prune_outside_drops_edges_leaving_the_walkable_polygon():
    g = nx.Graph()
    g.add_edge((10, 50), (90, 50))
    g.add_edge((90, 50), (150, 50))
    pruned = pr._prune_outside(g, box(0, 0, 100, 100))
    assert sorted(pruned.edges) == [((10, 50), (90, 50))]
    assert (150, 50) not in pruned


def test_corridor_graph_edges_stay_inside_walkable_polygon(plan):
    polygon, graph = pr.corridor_graph_for(plan, 0.2)
    inside = polygon.buffer(1e-6)
    assert all(inside.covers(LineString([a, b])) for a, b in graph.edges)
