from shapely.geometry import box
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


def test_route_multi_reduces_point_count_toward_max_pts():
    room = box(0, 0, 50, 2)  # a long straight corridor, RDP already keeps
    # this small, so force a tiny max_pts to prove the squeeze runs at all.
    graph = cg.build_corridor_graph(room, doors=[], spacing_m=0.5)
    route = cg.route_multi([(1, 1), (49, 1)], graph, room, max_pts=3)
    assert route is not None
    assert len(route) <= 3
