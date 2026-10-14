"""Corridor-only Smart Path routing on a display-space PlanModel."""
from __future__ import annotations

import logging
import math

import networkx as nx
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points
from shapely.prepared import prep

from corridor_graph import build_corridor_graph, build_walkable_polygon, compute_bounds, route_multi
from plan_model import room_at
from qbiq_extractor import _to_segments
from route_processor import smooth_preview

log = logging.getLogger(__name__)

_COVER_TOL = 1e-6


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

    smooth_preview emits the same number of samples per leg, so a sample's leg
    is its index // per_leg; nearest-leg-by-distance misattributes a bulge to
    a parallel leg (e.g. the return leg of an out-and-back) and never converges.
    """
    samples = smooth_preview(wps, smoothing=smoothing)
    legs = len(wps) - 1
    per_leg = max(1, (len(samples) - 1) // legs)
    return {min(i // per_leg, legs - 1) for i, s in enumerate(samples) if not covered.covers(Point(s))}


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


def _attach(waypoints: list, snapped: list, metas: list) -> list:
    """Stop entries pinned to the waypoint nearest each stop point, in order."""
    stops, start = [], 0
    for pt, meta in zip(snapped, metas):
        if not meta:
            continue
        idx = min(range(start, len(waypoints)),
                  key=lambda i: math.hypot(waypoints[i][0] - pt[0], waypoints[i][1] - pt[1]))
        stops.append({"index": idx, **meta})
        start = idx
    return stops


def route_on_plan(plan, points, get_graph, clearance_m: float = 0.2, smoothing: float = 1.0,
                  metas: list | None = None) -> dict:
    """Corridor-only route through ordered points; raises CorridorBlocked when unconnected."""
    snapped, snapped_metas = snap_points(plan, points)
    metas = [m or s for m, s in zip(metas, snapped_metas)] if metas else snapped_metas
    max_pts = max(12, 3 * len(snapped))
    for c in (clearance_m, clearance_m / 2, 0.05):
        polygon, graph = get_graph(round(c, 3))
        if graph is None:
            continue
        if wps := route_multi(snapped, graph, polygon, max_pts=max_pts):
            wps = contain_spline(wps, plan.corridor, smoothing)
            return {"waypoints": wps, "stops": _attach(wps, snapped, metas)}
    x, y = snapped[0]
    raise CorridorBlocked(f"corridor blocked near ({x:.0f}, {y:.0f})")
