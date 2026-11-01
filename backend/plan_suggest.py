"""Suggested tour: what a designer shows - walk into the open highlights and down the wings, glancing at the
rooms on the way - within a walking budget. Learned from 312 hand-made Enscape paths
(docs/superpowers/specs/2026-11-01-designer-tour-design.md)."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import networkx as nx
import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.prepared import prep

from corridor_graph import _snap_to_nearest_edge
from plan_model import BACK_OF_HOUSE, PlanRoom
from plan_routing import CENTRE_LINE_MAX_M, _centre_line_point

log = logging.getLogger(__name__)

TOUR_LENGTH_M = 85.0     # designers' median route is 82 m
SEE_CLOSED_M = 3.0       # a closed room is shown when the route passes this close to its door stop
SEE_OPEN_M = 1.0         # a walk-in area is shown when the route reaches its inside stop
PASS_PICK_M = 1.0        # a room seen on the way joins the tour when its route point is this close to the route
MIN_LOOK_GAP_M = 5.0
WEIGHTS = {"Reception": 5.0, "Kitchen": 4.0, "Open Space WorkStation": 3.0, "Comfort Zone": 3.0,
           "Conference": 2.0, "Executive Office": 2.0, "Phone Booth": 1.0}
_OFFICE_WEIGHT = 1.5
_OTHER_WEIGHT = 1.0
_NOTHING = BACK_OF_HOUSE | {"EmptySpace"}


@dataclass(frozen=True)
class _Target:
    room: PlanRoom
    go: tuple       # where the route goes to show the room
    see: tuple      # what the route must pass near
    see_m: float


def weight(room: PlanRoom) -> float:
    """How much a designer wants to show a room."""
    if room.space_type in _NOTHING:
        return 0.0
    if room.space_type in WEIGHTS:
        return WEIGHTS[room.space_type]
    return _OFFICE_WEIGHT if (room.space_type or "").startswith("Office") else _OTHER_WEIGHT


def _targets(plan, graph) -> list:
    """One target per room worth showing: walk-in areas at their inside stop, others glanced at from the walking line."""
    reach = CENTRE_LINE_MAX_M / plan.units_to_metres
    out = []
    for r in plan.rooms:
        if weight(r) <= 0:
            continue
        if r.stop.look_at == r.stop.point:                 # walk-in area (plan_model._inside_stop)
            out.append(_Target(r, r.stop.point, r.stop.point, SEE_OPEN_M))
        else:
            go = _centre_line_point(graph, r.stop.point, reach) if not r.is_open else r.stop.point
            out.append(_Target(r, go, r.stop.point, SEE_CLOSED_M))
    return out


class _Legs:
    """Shortest walks between the start (0) and every target (1..n), with the targets each walk shows;
    two points in plain sight of each other are joined directly, as the router's line-of-sight shortcuts do."""

    def __init__(self, graph, polygon, start, targets: list, u: float):
        g = graph.copy()
        self.nodes = [_snap_to_nearest_edge(g, tuple(start))] + [_snap_to_nearest_edge(g, t.go) for t in targets]
        clear = prep(polygon.buffer(1e-6))
        g.add_weighted_edges_from((a, b, math.dist(a, b)) for i, a in enumerate(self.nodes) for b in self.nodes[i + 1:]
                                  if a != b and clear.contains(LineString([a, b])))
        self.dist, self.path = {}, {}
        for i, n in enumerate(self.nodes):
            d, p = nx.single_source_dijkstra(g, n, weight="weight")
            for j, m in enumerate(self.nodes):
                self.dist[i, j], self.path[i, j] = d.get(m, math.inf) * u, p.get(m)
        self.see = shapely.points(np.array([t.see for t in targets], dtype=float))
        self.see_m = np.array([t.see_m for t in targets]) / u
        self._seen = {}

    def line(self, i: int, j: int):
        p = self.path[i, j]
        return LineString(p) if len(p) > 1 else Point(p[0])

    def seen(self, i: int, j: int) -> frozenset:
        """Target indices (0-based) shown by the walk from i to j; the route always reaches its own target."""
        if (i, j) not in self._seen:
            ok = self.path[i, j] is not None
            hits = np.nonzero(shapely.distance(self.line(i, j), self.see) <= self.see_m)[0] if ok else []
            self._seen[i, j] = frozenset(int(k) for k in hits) | ({j - 1} if ok and j > 0 else set())
        return self._seen[i, j]


def _evaluate(seq: list, legs: _Legs, weights: list) -> tuple:
    """(length m, shown target indices, value) of visiting seq (1-based targets) from the start."""
    length, shown = 0.0, set()
    for a, b in zip([0] + seq, seq):
        length += legs.dist[a, b]
        shown |= legs.seen(a, b)
    return length, shown, sum(weights[k] for k in shown)


def _choose(legs: _Legs, weights: list, budget_m: float) -> list:
    """Greedy budgeted orienteering: insert the target with the most value gained per metre while within budget."""
    seq, length, shown, value = [], 0.0, set(), 0.0
    while True:
        best = None
        for t in range(1, len(weights) + 1):
            if t - 1 in shown:
                continue
            for pos in range(len(seq) + 1):
                cand = seq[:pos] + [t] + seq[pos:]
                c_len, c_shown, c_val = _evaluate(cand, legs, weights)
                if not math.isfinite(c_len) or c_len > budget_m or c_val <= value:
                    continue
                ratio = (c_val - value) / max(c_len - length, 1.0)
                if best is None or ratio > best[0]:
                    best = (ratio, cand, c_len, c_shown, c_val)
        if best is None:
            return seq
        _, seq, length, shown, value = best


def _in_route_order(seq: list, legs: _Legs, targets: list, u: float) -> list:
    """(metres along the route, target index, chosen?) for the chosen targets and the rooms passed on the way."""
    out, done, s0 = [], set(), 0.0
    for a, b in zip([0] + seq, seq):
        line = legs.line(a, b)
        for k in sorted(legs.seen(a, b) - done - {b - 1}):
            if line.distance(Point(targets[k].go)) * u <= PASS_PICK_M:
                out.append((s0 + line.project(Point(targets[k].see)) * u, k, False))
                done.add(k)
        if b - 1 not in done:
            out.append((s0 + line.length * u, b - 1, True))
            done.add(b - 1)
        s0 += line.length * u
    return sorted(out)


def _thin(order: list, weights: list) -> list:
    """Drop rooms passed within MIN_LOOK_GAP_M of a kept look (the chosen ones and heavier rooms win)."""
    kept = []
    for s, k, chosen in order:
        if kept and s - kept[-1][0] < MIN_LOOK_GAP_M:
            ps, pk, pchosen = kept[-1]
            if chosen or (not pchosen and weights[k] > weights[pk]):
                if pchosen:
                    kept.append((s, k, chosen))
                else:
                    kept[-1] = (s, k, chosen)
            continue
        kept.append((s, k, chosen))
    return [k for _, k, _ in kept]


def suggest_room_ids(plan, graph, polygon, start, budget_m: float = TOUR_LENGTH_M) -> list:
    """Room ids of a designer-like tour from start, in route order."""
    if not (targets := _targets(plan, graph)):
        raise ValueError("no rooms worth showing in this plan")
    u = plan.units_to_metres
    legs = _Legs(graph, polygon, start, targets, u)
    weights = [weight(t.room) for t in targets]
    if not (seq := _choose(legs, weights, budget_m)):
        raise ValueError("none of the rooms can be reached within the tour length")
    return [targets[k].room.id for k in _thin(_in_route_order(seq, legs, targets, u), weights)]
