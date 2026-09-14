"""
corridor_graph.py
------------------
Corridor-centerline routing: builds a walkable-area polygon (vector boolean
ops over classified obstacles/doors/FLOOD, via shapely) and a cleaned
Voronoi-skeleton graph over it, then routes ordered via-points on that graph.

This is the PRIMARY routing path for /api/autopath. See app.py's
_get_circ_graph_and_polygon / autopath() for how it's wired in with a
fallback to autopath.py's grid A* (find_multi_path) whenever any step here
fails — see this project's corridor-graph design spec
(docs/superpowers/specs/2026-09-14-corridor-graph-routing-design.md) for the
full rationale.
"""

from __future__ import annotations
import math
import numpy as np
import networkx as nx
from scipy.spatial import Voronoi, cKDTree
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union

from autopath import _point_seg_dist


def _polyline_to_shape(poly: list, buffer_amt: float, min_line_buffer: float = 0.0):
    """
    Turn one classified obstacle polyline into a real-area shapely shape.

    A closed ring (first point == last point, >=4 points) is filled as a
    Polygon — it already has real drawn area (e.g. a wall's own rectangular
    footprint), and `buffer_amt` only grows that area further for clearance.

    An open chain (a bare LINE/centerline representation, common for walls
    in real DXFs) has zero area on its own, so it's buffered into a real
    band. `min_line_buffer` guarantees a minimum band thickness even when
    the caller passes buffer_amt=0.0 (autopath.py's clearance-retry loop's
    last, most permissive level) — without it, a zero-width wall would
    vanish from the obstacle set entirely at that retry level, unlike the
    grid approach where rasterizing a line's bounding box always blocks at
    least one full grid cell regardless of the requested clearance.
    """
    if len(poly) >= 4 and poly[0] == poly[-1]:
        base = Polygon(poly[:-1])
        if not base.is_valid:
            base = base.buffer(0)
        return base.buffer(buffer_amt) if buffer_amt > 0 else base
    base = LineString(poly)
    eff_buffer = max(buffer_amt, min_line_buffer)
    return base.buffer(eff_buffer)


def _polygon_from_ring(poly: list):
    """A closed footprint/FLOOD ring -> a valid shapely Polygon (fixing
    self-intersections via the standard buffer(0) idiom if needed)."""
    ring = poly[:-1] if len(poly) >= 2 and poly[0] == poly[-1] else poly
    if len(ring) < 3:
        return Polygon()
    shp = Polygon(ring)
    return shp if shp.is_valid else shp.buffer(0)


def _build_wall_polygon(walls: list, doors: list, clearance: float, door_half: float,
                         min_line_buffer: float = 0.0):
    """
    Union of all wall shapes, buffered by `clearance`, with a small notch
    subtracted at every door's centroid (sized `door_half` on each side) —
    the vector equivalent of autopath.py's _clear_doors: a door always
    carves a real, classification-driven opening into the wall layer,
    regardless of whether that DXF's own wall geometry happens to have a
    gap there.
    """
    wall_shapes = [_polyline_to_shape(w, clearance, min_line_buffer) for w in walls if len(w) >= 2]
    wall_union = unary_union(wall_shapes) if wall_shapes else Polygon()

    for door in doors or []:
        if not door:
            continue
        cx = sum(p[0] for p in door) / len(door)
        cy = sum(p[1] for p in door) / len(door)
        notch = box(cx - door_half, cy - door_half, cx + door_half, cy + door_half)
        wall_union = wall_union.difference(notch)

    return wall_union
