from shapely.geometry import box
from shapely.ops import unary_union
import corridor_graph as cg


def test_route_multi_start_to_end_in_open_room():
    room = box(0, 0, 20, 20)
    graph = cg.build_corridor_graph(room, doors=[])
    route = cg.route_multi([(1, 1), (19, 19)], graph, room)
    assert route is not None
    assert len(route) >= 2
    # exact clicked endpoints are used verbatim since both are inside the room
    assert list(route[0]) == [1.0, 1.0]
    assert list(route[-1]) == [19.0, 19.0]


def test_route_multi_respects_ordered_via_points():
    room = box(0, 0, 20, 20)
    graph = cg.build_corridor_graph(room, doors=[])
    via = (10, 1)
    route = cg.route_multi([(1, 1), via, (19, 19)], graph, room)
    assert route is not None
    # the via point must appear somewhere along the returned route, in the
    # middle (not just start/end) — proves it's an enforced waypoint, not
    # just the shortest start->end line.
    assert any(abs(x - via[0]) < 1e-6 and abs(y - via[1]) < 1e-6 for x, y in route)


def test_route_multi_returns_none_when_graph_is_none():
    assert cg.route_multi([(0, 0), (1, 1)], None, box(0, 0, 2, 2)) is None


def test_route_multi_keeps_every_via_point_through_max_pts_reduction():
    """
    Regression: the max_pts squeeze used to silently DELETE via-points.

    A long corridor with a side alcove, 5 clicked via-points (one of them
    inside the alcove) and a max_pts small enough that the reduction loop
    really runs. Pre-fix this returned 6 points with 2 of the 3 interior
    via-points gone — including the alcove one, so the "successful" route
    never entered the room the user had explicitly clicked into.
    """
    area = unary_union([box(0, 0, 60, 4), box(26, 4, 34, 12)])  # L-shaped: corridor + alcove
    graph = cg.build_corridor_graph(area, doors=[])
    via = [(2.0, 2.0), (15.0, 2.0), (30.0, 10.0), (45.0, 2.0), (58.0, 2.0)]

    raw = cg.route_multi(via, graph, area, max_pts=10 ** 6)  # unreduced baseline
    route = cg.route_multi(via, graph, area, max_pts=6)
    assert route is not None
    # the reduction loop must actually have executed, or this proves nothing
    assert len(route) < len(raw)

    for vx, vy in via:
        assert any(abs(x - vx) < 1e-6 and abs(y - vy) < 1e-6 for x, y in route), \
            f"via-point {(vx, vy)} was dropped by the max_pts reduction"


def test_route_multi_reduces_point_count_toward_max_pts():
    room = box(0, 0, 50, 2)  # a long straight corridor, RDP already keeps
    # this small, so force a tiny max_pts to prove the squeeze runs at all.
    graph = cg.build_corridor_graph(room, doors=[], spacing_m=0.5)
    route = cg.route_multi([(1, 1), (49, 1)], graph, room, max_pts=3)
    assert route is not None
    assert len(route) <= 3
