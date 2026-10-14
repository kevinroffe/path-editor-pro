"""Corridor-only Smart Path routing on a display-space PlanModel."""
from __future__ import annotations

import logging
import math

import networkx as nx
import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points
from shapely.prepared import prep

from corridor_graph import build_corridor_graph, build_walkable_polygon, compute_bounds, route_multi
from plan_model import room_at
from qbiq_extractor import _to_segments
from route_processor import _centripetal_cr, smooth_preview

log = logging.getLogger(__name__)

_COVER_TOL = 1e-6
_VIDEO_SAMPLES = 20
_STOP_TOL = 1.0


class CorridorBlocked(Exception):
    """The corridor does not connect the requested points at any clearance."""


def _polys(geom) -> list:
    return list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]


def corridor_graph_for(plan, clearance_m: float):
    """(walkable polygon, corridor graph) for the corridor shrunk by clearance."""
    polys = _polys(plan.corridor)
    exteriors = [list(p.exterior.coords) for p in polys]
    holes = [list(r.coords) for p in polys for r in p.interiors]
    walls = _to_segments(exteriors + holes)
    bounds = compute_bounds(walls, exteriors)
    polygon = build_walkable_polygon(walls, [], holes + plan.columns, exteriors, bounds,
                                     clearance_m=clearance_m, units_to_metres=plan.units_to_metres)
    graph = build_corridor_graph(polygon, [], units_to_metres=plan.units_to_metres) if polygon is not None else None
    return polygon, _prune_outside(graph, polygon)


def _prune_outside(graph, polygon):
    """Drop skeleton edges that leave the walkable polygon.

    The Voronoi skeleton keeps a ridge when only its midpoint is inside, so in
    narrow inlets (door pockets) edges can poke into the neighbouring room.
    """
    if graph is None:
        return None
    inside = prep(polygon.buffer(_COVER_TOL))
    graph = graph.copy()
    graph.remove_edges_from([(a, b) for a, b in graph.edges if not inside.contains(LineString([a, b]))])
    graph.remove_nodes_from(list(nx.isolates(graph)))
    return graph if graph.number_of_edges() else None


def stop_meta(room) -> dict:
    """Waypoint stop metadata for a room."""
    return {"room_id": room.id, "room_name": room.space_type or "Room",
            "look_at": list(room.stop.look_at), "dwell_s": room.stop.dwell_s}


def snap_points(plan, points) -> tuple:
    """Corridor points unchanged; room clicks -> room stop; anything else -> nearest corridor point."""
    covered = plan.corridor.buffer(_COVER_TOL)
    snapped, metas = [], []
    for raw in points:
        p = (float(raw[0]), float(raw[1]))
        if covered.covers(Point(p)):
            snapped.append(p)
            metas.append(None)
        elif room := room_at(plan, p):
            snapped.append(tuple(room.stop.point))
            metas.append(stop_meta(room))
        else:
            q = nearest_points(plan.corridor, Point(p))[0]
            snapped.append((q.x, q.y))
            metas.append(None)
    return snapped, metas


def _bad_legs(wps: list, covered, smoothing: float) -> set:
    """Indices of legs whose spline samples leave the covered area.

    Checked at preview density and at the video's 20 samples per leg. Both emit
    the same number of samples per leg, so a sample's leg is its index // per_leg;
    nearest-leg-by-distance misattributes a bulge to a parallel leg (e.g. the
    return leg of an out-and-back) and never converges.
    """
    legs = len(wps) - 1
    bad = set()
    for samples in (smooth_preview(wps, smoothing=smoothing),
                    _centripetal_cr(np.array(wps, dtype=float), smoothing, samples=_VIDEO_SAMPLES)):
        per_leg = max(1, (len(samples) - 1) // legs)
        bad |= {min(i // per_leg, legs - 1) for i, s in enumerate(samples) if not covered.covers(Point(s))}
    return bad


def contain_spline(waypoints: list, corridor, smoothing: float, max_rounds: int = 6) -> list:
    """Insert leg midpoints until the smoothed path stays inside the corridor."""
    covered = prep(corridor.buffer(_COVER_TOL))
    wps = [tuple(p) for p in waypoints]
    for _ in range(max_rounds):
        if not (bad := _bad_legs(wps, covered, smoothing)):
            break
        for i in sorted(bad, reverse=True):
            a, b = wps[i], wps[i + 1]
            wps.insert(i + 1, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    else:
        if _bad_legs(wps, covered, smoothing):
            log.warning("Smoothed path still leaves the corridor after %d rounds", max_rounds)
    return [list(p) for p in wps]


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _seg_dist(p, a, b) -> float:
    """Distance from point p to segment a-b."""
    return Point(p).distance(LineString([a, b])) if a != b else _dist(p, a)


def _pin_stops(waypoints: list, snapped: list, metas: list) -> list:
    """Waypoints with every stop point present, in stop order (inserted on the nearest leg after the previous stop)."""
    wps, prev = [list(p) for p in waypoints], -1
    for pt, meta in zip(snapped, metas):
        if not meta:
            continue
        near = min(range(prev + 1, len(wps)), key=lambda i: _dist(wps[i], pt), default=None)
        if near is not None and _dist(wps[near], pt) <= _STOP_TOL:
            prev = near
            continue
        lo = max(prev, 0)
        leg = min(range(lo, len(wps) - 1), key=lambda i: _seg_dist(pt, wps[i], wps[i + 1]), default=len(wps) - 2)
        prev = leg + 1
        wps.insert(prev, [float(pt[0]), float(pt[1])])
    return wps


def _attach(waypoints: list, snapped: list, metas: list) -> list:
    """One stop entry per stop meta, pinned to its own waypoint, indices strictly increasing."""
    stops, prev = [], -1
    for pt, meta in zip(snapped, metas):
        if not meta:
            continue
        prev = min(range(prev + 1, len(waypoints)), key=lambda i: _dist(waypoints[i], pt))
        stops.append({"index": prev, **meta})
    return stops


def _blocked_leg(snapped: list, get_graph) -> str:
    """Message naming the first consecutive pair the corridor graph cannot connect."""
    polygon, graph = get_graph(0.05)
    pairs = list(zip(snapped, snapped[1:]))
    a, b = next((pair for pair in pairs if route_multi(list(pair), graph, polygon) is None), pairs[0])
    return f"corridor blocked between ({a[0]:.0f}, {a[1]:.0f}) and ({b[0]:.0f}, {b[1]:.0f})"


def route_on_plan(plan, points, get_graph, clearance_m: float = 0.2, smoothing: float = 1.0,
                  metas: list | None = None) -> dict:
    """Corridor-only route through ordered points; raises CorridorBlocked when unconnected."""
    if metas is not None and len(metas) != len(points):
        raise ValueError(f"metas has {len(metas)} entries for {len(points)} points")
    snapped, snapped_metas = snap_points(plan, points)
    metas = [m or s for m, s in zip(metas, snapped_metas)] if metas else snapped_metas
    max_pts = max(12, 3 * len(snapped))
    for c in (clearance_m, clearance_m / 2, 0.05):
        polygon, graph = get_graph(round(c, 3))
        if graph is None:
            continue
        if wps := route_multi(snapped, graph, polygon, max_pts=max_pts):
            wps = contain_spline(_pin_stops(wps, snapped, metas), plan.corridor, smoothing)
            return {"waypoints": wps, "stops": _attach(wps, snapped, metas)}
    raise CorridorBlocked(_blocked_leg(snapped, get_graph))
