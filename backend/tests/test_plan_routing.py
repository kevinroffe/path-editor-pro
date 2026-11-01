import networkx as nx
import numpy as np
import pytest
from shapely.geometry import LineString, Point, box

import plan_model as pm
import plan_routing as pr
from route_processor import _centripetal_cr, smooth_preview
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


A_WALK_POINT = [350, -500]   # A's door stop (350, -540) moved onto the corridor's centre line


def _inside(plan, pt):
    return plan.walkable.buffer(1e-6).covers(Point(pt))


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


def test_route_stays_walkable_and_spline_too(plan, get_graph):
    out = pr.route_on_plan(plan, [(50, -500), (100, -900), (1500, -900), (1950, -500)], get_graph)
    wps, walk = out["waypoints"], plan.walkable.buffer(1e-6)
    assert all(walk.covers(Point(p)) for p in wps)
    assert all(walk.covers(Point(p)) for p in smooth_preview(wps, smoothing=1.0))
    assert all(walk.covers(Point(p)) for p in _centripetal_cr(np.array(wps), 1.0, samples=20))


def test_stops_attached_in_order(plan, get_graph):
    out = pr.route_on_plan(plan, [(50, -500), (100, -900), (1500, -900), (1950, -500)], get_graph)
    assert [s["room_id"] for s in out["stops"]] == ["A", "B"]
    idx = [s["index"] for s in out["stops"]]
    assert idx == sorted(idx)
    assert out["waypoints"][idx[0]] == pytest.approx(A_WALK_POINT, abs=1.0)


def test_blocked_corridor_raises(plan):
    with pytest.raises(pr.CorridorBlocked, match=r"corridor blocked between \(50, -500\) and \(1950, -500\)"):
        pr.route_on_plan(plan, [(50, -500), (1950, -500)], lambda c: (None, None))


def test_contain_spline_inserts_points_until_inside(plan):
    corridor = plan.corridor
    zig = [(50, -410), (1000, -590), (1950, -410)]
    out, contained = pr.contain_spline(zig, corridor, smoothing=1.0)
    assert contained and len(out) >= len(zig)
    assert all(corridor.buffer(1e-6).covers(Point(p)) for p in smooth_preview(out, smoothing=1.0))


def test_contain_spline_out_and_back_attributes_bulge_to_its_own_leg():
    route = [(0, 0), (2000, 0), (2000, -400), (2000, 0), (0, 0), (0, -400)]
    corridor = LineString(route).buffer(40, cap_style=2, join_style=2)
    out, contained = pr.contain_spline(route, corridor, smoothing=1.0)
    assert contained
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


def _stop_checks(out, expected):
    idx = [s["index"] for s in out["stops"]]
    assert len(idx) == expected and idx == sorted(set(idx))
    return idx


def test_same_room_clicked_twice_gets_two_distinct_stops(plan, get_graph):
    out = pr.route_on_plan(plan, [(50, -500), (100, -900), (100, -900), (1950, -500)], get_graph)
    for i in _stop_checks(out, 2):
        assert out["waypoints"][i] == pytest.approx(A_WALK_POINT, abs=1.0)


def test_rooms_with_identical_snap_targets_get_distinct_stops(plan, get_graph, monkeypatch):
    pt = (100.0, -500.0)
    metas = [None, {"room_id": "A"}, {"room_id": "B"}, None]
    monkeypatch.setattr(pr, "snap_points", lambda p, pts: ([(50.0, -500.0), pt, pt, (1950.0, -500.0)], metas))
    out = pr.route_on_plan(plan, [(0, 0)] * 4, get_graph)
    assert [s["room_id"] for s in out["stops"]] == ["A", "B"]
    for i in _stop_checks(out, 2):
        assert out["waypoints"][i] == pytest.approx(list(pt), abs=1.0)


def test_stop_missing_from_route_is_inserted_on_its_leg():
    wps = [[0.0, 0.0], [1000.0, 0.0]]
    out = pr._pin_stops(wps, [(0.0, 0.0), (400.0, 0.0), (1000.0, 0.0)], [None, {"room_id": "A"}, None])
    assert out == [[0.0, 0.0], [400.0, 0.0], [1000.0, 0.0]]


def test_metas_length_mismatch_raises(plan, get_graph):
    with pytest.raises(ValueError, match="metas"):
        pr.route_on_plan(plan, [(50, -500), (1950, -500)], get_graph, metas=[None])


def test_blocked_error_names_the_failing_leg(plan):
    g = nx.Graph()
    g.add_edge((0, 0), (100, 0))
    g.add_edge((1000, 0), (1100, 0))
    graph = (box(-10, -10, 1200, 10), g)
    with pytest.raises(pr.CorridorBlocked, match=r"between \(80, -500\) and \(1950, -500\)"):
        pr.route_on_plan(plan, [(50, -500), (80, -500), (1950, -500)], lambda c: graph)


def test_contain_spline_holds_at_video_sampling_density():
    route = [(963, 232), (399, 989), (314, 42), (335, 191), (324, 811), (867, 592)]
    corridor = LineString(route).buffer(40, cap_style=2, join_style=2)
    out, contained = pr.contain_spline(route, corridor, smoothing=1.0)
    assert contained
    covered = corridor.buffer(1e-6)
    assert all(covered.covers(Point(p)) for p in _centripetal_cr(np.array(out), 1.0, samples=20))


def _assert_contained(plan, wps):
    assert all(_inside(plan, p) for p in smooth_preview(wps, smoothing=1.0))
    assert all(_inside(plan, p) for p in _centripetal_cr(np.array(wps), 1.0, samples=20))


def test_start_over_first_stop_is_kept(plan, get_graph):
    b = next(r for r in plan.rooms if r.id == "B")
    start = (b.stop.point[0], -460.0)
    out = pr.route_on_plan(plan, [start, b.stop.point], get_graph, metas=[None, pr.stop_meta(b)])
    wps = out["waypoints"]
    assert wps[0] == pytest.approx(start, abs=1.0)
    assert [s["index"] for s in out["stops"]] == [len(wps) - 1]
    assert wps[-1] == pytest.approx(list(b.stop.point), abs=1.0)
    _assert_contained(plan, wps)


def test_end_over_last_stop_is_kept(plan, get_graph):
    b = next(r for r in plan.rooms if r.id == "B")
    end = (b.stop.point[0], -460.0)
    out = pr.route_on_plan(plan, [b.stop.point, end], get_graph, metas=[pr.stop_meta(b), None])
    wps = out["waypoints"]
    assert wps[-1] == pytest.approx(end, abs=1.0)
    assert [s["index"] for s in out["stops"]] == [0]
    assert wps[0] == pytest.approx(list(b.stop.point), abs=1.0)
    _assert_contained(plan, wps)


def test_route_on_plan_warns_when_containment_gives_up(plan, monkeypatch):
    monkeypatch.setattr(pr, "_bad_legs", lambda wps, covered, smoothing: {0})
    out = pr.route_on_plan(plan, [(50, -500), (1950, -500)], lambda c: pr.corridor_graph_for(plan, c))
    assert "corridor" in out["warning"]


def test_contain_spline_reports_failure_with_zero_rounds(plan):
    out_of_corridor = [(50, -500), (1000, -700), (1950, -500)]
    out, contained = pr.contain_spline(out_of_corridor, plan.corridor, smoothing=1.0, max_rounds=0)
    assert out == [list(p) for p in out_of_corridor] and not contained


def test_closed_room_is_glanced_at_from_the_centre_line(plan, get_graph):
    # A's door stop is 0.6 m off the door (y = -540); the corridor's centre line is y = -500: no zig-zag to the door
    out = pr.route_on_plan(plan, [(50, -500), (100, -900), (1950, -500)], get_graph)
    (stop,) = out["stops"]
    assert stop["room_id"] == "A" and out["waypoints"][stop["index"]][1] == pytest.approx(-500, abs=5)
    assert max(abs(p[1] + 500) for p in out["waypoints"] if p[0] < 900) <= 5


def test_door_far_from_the_walking_line_keeps_its_stop(plan):
    a = next(r for r in plan.rooms if r.id == "A")
    assert pr._centre_line_point(nx.Graph([((0, 0), (10, 0))]), a.stop.point, 50) == pytest.approx(a.stop.point)
