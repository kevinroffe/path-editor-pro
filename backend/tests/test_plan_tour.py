import math

import pytest

import camera_style as cs
import plan_model as pm
import plan_routing as pr
import plan_tour as pt
from tests.test_plan_model import DATA


@pytest.fixture(scope="module")
def plan():
    return pm.flipped(pm.build_plan_model(DATA, 0.01))


@pytest.fixture(scope="module")
def get_graph(plan):
    cache = {}
    return lambda c: cache.setdefault(c, pr.corridor_graph_for(plan, c))


def _length(order, dist):
    seq = [0] + order
    return sum(dist[a][b] for a, b in zip(seq, seq[1:]))


def test_order_stops_beats_naive_and_visits_each_once():
    pts = [(0, 0), (10, 0), (1, 0), (9, 0), (2, 0)]
    dist = [[math.dist(a, b) for b in pts] for a in pts]
    order = pt.order_stops(dist)
    assert sorted(order) == [1, 2, 3, 4]
    assert _length(order, dist) <= _length([1, 2, 3, 4], dist)
    assert _length(order, dist) == pytest.approx(10.0)


def test_order_stops_skips_unreachable():
    inf = math.inf
    dist = [[0, 1, inf], [1, 0, inf], [inf, inf, 0]]
    assert pt.order_stops(dist) == [1]


def test_tour_default_types_exclude_back_of_house(plan, get_graph):
    polygon, graph = get_graph(0.2)
    tour = pt.build_tour(plan, graph, polygon, get_graph)
    ids = [s["room_id"] for s in tour["stops"]]
    assert "C" not in ids                      # Storage Room is back-of-house
    assert sorted(ids) == ["A", "B", "D"]
    assert len(ids) == len(set(ids))


def test_tour_starts_at_entrance_and_sets_duration(plan, get_graph):
    polygon, graph = get_graph(0.2)
    tour = pt.build_tour(plan, graph, polygon, get_graph)
    assert tour["waypoints"][0] == pytest.approx(list(plan.entrance), abs=1.0)
    assert tour["suggested_duration_s"] >= 10 and tour["suggested_duration_s"] % 5 == 0
    assert tour["unreachable"] == []


def test_tour_duration_uses_house_style_walking_speed(plan):
    big = pm.flipped(pm.build_plan_model(DATA, 0.05))      # 5 cm units: a 100 m floor, long enough to matter
    cache = {}
    get = lambda c: cache.setdefault(c, pr.corridor_graph_for(big, c))  # noqa: E731
    polygon, graph = get(0.2)
    tour = pt.build_tour(big, graph, polygon, get, room_ids=["A", "D"])
    length_m = sum(math.dist(a, b) for a, b in zip(tour["waypoints"], tour["waypoints"][1:])) * big.units_to_metres
    assert tour["suggested_duration_s"] == cs.suggest_duration_s(length_m)


def test_tour_respects_requested_types(plan, get_graph):
    polygon, graph = get_graph(0.2)
    tour = pt.build_tour(plan, graph, polygon, get_graph, room_types=["Storage Room"])
    assert [s["room_id"] for s in tour["stops"]] == ["C"]


def test_tour_without_matching_rooms_raises(plan, get_graph):
    polygon, graph = get_graph(0.2)
    with pytest.raises(ValueError, match="no rooms of the selected types"):
        pt.build_tour(plan, graph, polygon, get_graph, room_types=["Nonexistent"])


def test_tour_room_ids_visit_in_given_order(plan, get_graph):
    polygon, graph = get_graph(0.2)
    tour = pt.build_tour(plan, graph, polygon, get_graph, room_ids=["D", "A", "B"])
    assert [s["room_id"] for s in tour["stops"]] == ["D", "A", "B"]
    idx = [s["index"] for s in tour["stops"]]
    assert idx == sorted(set(idx))
    assert tour["waypoints"][0] == pytest.approx(list(plan.entrance), abs=1.0)


def test_tour_room_ids_collapse_duplicates(plan, get_graph):
    polygon, graph = get_graph(0.2)
    tour = pt.build_tour(plan, graph, polygon, get_graph, room_ids=["B", "A", "B"])
    assert [s["room_id"] for s in tour["stops"]] == ["B", "A"]


def test_tour_room_ids_unknown_raises(plan, get_graph):
    polygon, graph = get_graph(0.2)
    with pytest.raises(ValueError, match="unknown room id: Z"):
        pt.build_tour(plan, graph, polygon, get_graph, room_ids=["A", "Z"])


def test_tour_room_ids_empty_raises(plan, get_graph):
    polygon, graph = get_graph(0.2)
    with pytest.raises(ValueError, match="no rooms selected"):
        pt.build_tour(plan, graph, polygon, get_graph, room_ids=[])


def test_tour_room_ids_beat_room_types(plan, get_graph):
    polygon, graph = get_graph(0.2)
    tour = pt.build_tour(plan, graph, polygon, get_graph, room_types=["Kitchen"], room_ids=["D"])
    assert [s["room_id"] for s in tour["stops"]] == ["D"]


@pytest.mark.parametrize("bad", [0, ""])
def test_tour_room_ids_falsy_unknown_raises(plan, get_graph, bad):
    polygon, graph = get_graph(0.2)
    with pytest.raises(ValueError, match="unknown room id"):
        pt.build_tour(plan, graph, polygon, get_graph, room_ids=[bad])
