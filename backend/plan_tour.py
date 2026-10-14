"""Auto tour: entrance -> every selected room's stop, in a short corridor order."""
from __future__ import annotations

import logging
import math

import networkx as nx

from corridor_graph import _snap_to_nearest_edge
from plan_model import BACK_OF_HOUSE
from plan_routing import route_on_plan, stop_meta

log = logging.getLogger(__name__)

WALK_SPEED_MPS = 1.0
MIN_TOUR_S = 10


def _path_len(seq: list, dist: list) -> float:
    """Total length of a path visiting seq in order."""
    return sum(dist[a][b] for a, b in zip(seq, seq[1:]))


def _two_opt(seq: list, dist: list) -> list:
    """Improve an open path with fixed start by segment reversals."""
    improved = True
    while improved:
        improved = False
        for i in range(1, len(seq) - 1):
            for j in range(i + 1, len(seq)):
                cand = seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:]
                if _path_len(cand, dist) < _path_len(seq, dist) - 1e-9:
                    seq, improved = cand, True
    return seq


def order_stops(dist: list) -> list:
    """Visiting order of stops 1..n-1 reachable from 0: nearest-neighbour then 2-opt."""
    todo = {j for j in range(1, len(dist)) if math.isfinite(dist[0][j])}
    seq = [0]
    while todo:
        nxt = min(todo, key=lambda j: dist[seq[-1]][j])
        seq.append(nxt)
        todo.discard(nxt)
    return _two_opt(seq, dist)[1:]


def _distances(graph, points: list) -> list:
    """All-pairs corridor distances between points snapped onto a graph copy."""
    g = graph.copy()
    nodes = [_snap_to_nearest_edge(g, tuple(p)) for p in points]
    lengths = [nx.single_source_dijkstra_path_length(g, n, weight="weight") for n in nodes]
    return [[lengths[i].get(nodes[j], math.inf) for j in range(len(nodes))] for i in range(len(nodes))]


def _route_length_m(waypoints: list, u: float) -> float:
    """Polyline length of the waypoints in metres."""
    return sum(math.dist(a, b) for a, b in zip(waypoints, waypoints[1:])) * u


def build_tour(plan, graph, polygon, get_graph, room_types=None, clearance_m: float = 0.2,
               smoothing: float = 1.0) -> dict:
    """Ordered corridor tour from the entrance through each selected room's stop."""
    types = set(room_types) if room_types else {r.space_type for r in plan.rooms} - BACK_OF_HOUSE
    if not (rooms := [r for r in plan.rooms if r.space_type in types]):
        raise ValueError("no rooms of the selected types")
    start = plan.entrance or rooms[0].stop.point
    dist = _distances(graph, [start] + [r.stop.point for r in rooms])
    order = order_stops(dist)
    unreachable = [r.space_type or r.id for j, r in enumerate(rooms, 1) if j not in order]
    visit = [rooms[j - 1] for j in order]
    metas = [None] + [stop_meta(r) for r in visit]
    routed = route_on_plan(plan, [start] + [r.stop.point for r in visit], get_graph,
                           clearance_m=clearance_m, smoothing=smoothing, metas=metas)
    seconds = (_route_length_m(routed["waypoints"], plan.units_to_metres) / WALK_SPEED_MPS
               + sum(s["dwell_s"] for s in routed["stops"]))
    if unreachable:
        log.warning("auto tour: %d room(s) unreachable from the entrance: %s", len(unreachable), unreachable)
    return {**routed, "suggested_duration_s": max(MIN_TOUR_S, 5 * math.ceil(seconds / 5)),
            "unreachable": unreachable}
