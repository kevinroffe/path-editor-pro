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


_MIN_WALL_BUFFER_M = 0.05  # minimum wall band half-thickness, see _polyline_to_shape


def compute_bounds(walls: list, footprint: list, margin_frac: float = 0.02) -> tuple:
    """
    Same bounds convention as autopath.py's find_path: walls + footprint
    extent, padded by margin_frac, used both as the fallback "no FLOOD
    layer" walkable envelope and to size the Voronoi boundary densification.

    Degenerate-dimension handling: when one dimension (width or height) is
    much smaller than the other (< 1% of the non-degenerate dimension),
    it is expanded to match the non-degenerate dimension, centered on its
    midpoint. This ensures a single wall (e.g., a line) produces a reasonable
    rectangular envelope for routing, not a pathological sliver. This applies
    symmetrically to both x and y dimensions.
    """
    all_pts = [pt for w in walls for pt in w] + [pt for poly in footprint for pt in poly]
    if not all_pts:
        return (0.0, 0.0, 1.0, 1.0)
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    min_xs = min(xs)
    max_xs = max(xs)
    min_ys = min(ys)
    max_ys = max(ys)

    # Handle degenerate width (vertical line): expand x to match y
    # Using 1% threshold to detect degenerate dimension
    if width < height * 0.01:
        center_x = (max_xs + min_xs) / 2
        min_xs = center_x - height / 2
        max_xs = center_x + height / 2

    # Handle degenerate height (horizontal line): expand y to match x
    # Using 1% threshold to detect degenerate dimension
    if height < width * 0.01:
        center_y = (max_ys + min_ys) / 2
        min_ys = center_y - width / 2
        max_ys = center_y + width / 2

    margin = max(max_xs - min_xs, max_ys - min_ys) * margin_frac
    return (min_xs - margin, min_ys - margin, max_xs + margin, max_ys + margin)


def build_walkable_polygon(walls: list, doors: list, other_obstacles: list, footprint: list,
                            bounds: tuple, clearance_m: float, units_to_metres: float,
                            door_clear_margin_m: float = 0.15):
    """
    The exact walkable area Auto Path may route through: the FLOOD footprint
    (or, if none exists, the plan's own bounding envelope) minus every
    classified obstacle, buffered by clearance_m, with a door-sized notch
    carved out of the wall layer at every classified door location.

    Returns None if the result is empty (fully blocked, or degenerate
    input) — callers must treat that as "graph routing unavailable, use
    the grid-A* fallback", never as an empty-but-valid walkable area.
    """
    clearance = clearance_m / max(units_to_metres, 1e-9)
    min_line_buffer = _MIN_WALL_BUFFER_M / max(units_to_metres, 1e-9)
    door_half = clearance + (door_clear_margin_m / max(units_to_metres, 1e-9))

    wall_union = _build_wall_polygon(walls, doors, clearance, door_half, min_line_buffer)

    other_shapes = [_polyline_to_shape(o, clearance, min_line_buffer)
                    for o in other_obstacles if len(o) >= 2]
    other_union = unary_union(other_shapes) if other_shapes else Polygon()

    obstacle_union = unary_union([wall_union, other_union])

    footprint_shapes = [_polygon_from_ring(p) for p in footprint if len(p) >= 3]
    area = unary_union(footprint_shapes) if footprint_shapes else None
    if area is None or area.is_empty:
        xmin, ymin, xmax, ymax = bounds
        area = box(xmin, ymin, xmax, ymax)

    walkable = area.difference(obstacle_union)
    return None if walkable.is_empty else walkable


def _densify_boundary(polygon, spacing: float) -> list:
    """
    Sample points along every ring (exterior + holes, across all
    sub-polygons if `polygon` is a MultiPolygon) at roughly `spacing`
    intervals — the Voronoi skeleton's resolution is bounded by how densely
    its input boundary is sampled, so this needs to be finer than the
    narrowest real corridor width we care about resolving.
    """
    geoms = list(polygon.geoms) if hasattr(polygon, "geoms") else [polygon]
    rings = []
    for geom in geoms:
        if geom.is_empty:
            continue
        rings.append(geom.exterior)
        rings.extend(geom.interiors)

    pts = []
    for ring in rings:
        length = ring.length
        if length <= 0:
            continue
        n = max(4, int(length / max(spacing, 1e-9)))
        for i in range(n):
            pt = ring.interpolate(i / n * length)
            pts.append((pt.x, pt.y))

    seen = set()
    unique = []
    for x, y in pts:
        key = (round(x, 6), round(y, 6))
        if key not in seen:
            seen.add(key)
            unique.append((x, y))
    return unique


def _voronoi_skeleton(polygon, boundary_pts: list) -> "nx.Graph":
    """
    Cheap medial-axis approximation: run scipy's Voronoi diagram over the
    walkable polygon's densified boundary, keep only the ridges whose
    midpoint falls strictly inside the polygon. This is the raw, noisy
    skeleton — Task 5 cleans it up into a real corridor-centerline graph.
    """
    graph = nx.Graph()
    if len(boundary_pts) < 4:
        return graph

    vor = Voronoi(np.array(boundary_pts))
    inflated = polygon.buffer(1e-6)

    for i, j in vor.ridge_vertices:
        if i < 0 or j < 0:
            continue
        a = tuple(round(c, 6) for c in vor.vertices[i])
        b = tuple(round(c, 6) for c in vor.vertices[j])
        if a == b:
            continue
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        if not inflated.contains(Point(mid)):
            continue
        dist = math.hypot(a[0] - b[0], a[1] - b[1])
        if dist < 1e-9:
            continue
        graph.add_edge(a, b, weight=dist)

    return graph


def _merge_close_nodes(graph, tol: float) -> "nx.Graph":
    """
    Collapse clusters of Voronoi vertices within `tol` of each other into a
    single node at their centroid — raw Voronoi output often produces
    several near-duplicate vertices right at a real junction/corner instead
    of one clean point ("T-junction"/corner noise).
    """
    if tol <= 0 or graph.number_of_nodes() == 0:
        return graph

    nodes = list(graph.nodes())
    parent = {n: n for n in nodes}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    tree = cKDTree(np.array(nodes))
    for i, j in tree.query_pairs(tol):
        union(nodes[i], nodes[j])

    clusters = {}
    for n in nodes:
        clusters.setdefault(find(n), []).append(n)

    rep_of = {}
    for members in clusters.values():
        cx = sum(m[0] for m in members) / len(members)
        cy = sum(m[1] for m in members) / len(members)
        rep = (cx, cy)
        for m in members:
            rep_of[m] = rep

    merged = nx.Graph()
    for u, v, data in graph.edges(data=True):
        ru, rv = rep_of[u], rep_of[v]
        if ru == rv:
            continue
        w = math.hypot(ru[0] - rv[0], ru[1] - rv[1])
        if merged.has_edge(ru, rv):
            if w < merged[ru][rv]["weight"]:
                merged[ru][rv]["weight"] = w
        else:
            merged.add_edge(ru, rv, weight=w)
    return merged


def _remove_short_stub_segments(graph, min_len: float) -> "nx.Graph":
    """
    Iteratively drop degree-1 (dead-end) nodes whose single edge is shorter
    than `min_len` — Voronoi skeletons fan out short spurious branches from
    every concave polygon corner (furniture corners, door-notch corners,
    etc.) that aren't real corridors. Repeats until stable, since removing
    one stub can expose a new (now shorter) dead end behind it.
    """
    graph = graph.copy()
    changed = True
    while changed:
        changed = False
        for node in list(graph.nodes()):
            deg = graph.degree(node)
            if deg == 0:
                # a node left with no edges at all (e.g. the far endpoint of
                # a short, topologically isolated stub whose only neighbor
                # was just pruned) is not a usable routing node either.
                graph.remove_node(node)
                changed = True
                continue
            if deg != 1:
                continue
            (neighbor,) = graph.neighbors(node)
            if graph[node][neighbor]["weight"] < min_len:
                graph.remove_node(node)
                changed = True
    return graph


def _rdp(points: list, epsilon: float) -> list:
    """Standard Ramer-Douglas-Peucker polyline simplification."""
    if len(points) < 3:
        return points
    a, b = points[0], points[-1]
    max_dist, idx = -1.0, -1
    for i in range(1, len(points) - 1):
        d = _point_seg_dist(points[i], a, b)
        if d > max_dist:
            max_dist, idx = d, i
    if max_dist <= epsilon:
        return [a, b]
    left = _rdp(points[:idx + 1], epsilon)
    right = _rdp(points[idx:], epsilon)
    return left[:-1] + right


def _simplify_branches(graph, epsilon: float) -> "nx.Graph":
    """
    RDP-simplify every maximal chain of degree-2 nodes running between two
    junctions (or a junction and a dead end) — this is what turns the raw,
    vertex-dense skeleton into a small number of straight-ish corridor
    segments ("straightening corners").
    """
    graph = graph.copy()
    junctions = {n for n in graph.nodes() if graph.degree(n) != 2}
    if not junctions:
        # a pure cycle with no junction at all — nothing safe to anchor a
        # chain-walk on, leave it as-is (rare for a real building layout).
        return graph

    visited_edges = set()
    for start in list(junctions):
        for first_neighbor in list(graph.neighbors(start)):
            edge_key = frozenset((start, first_neighbor))
            if edge_key in visited_edges:
                continue
            visited_edges.add(edge_key)
            chain = [start, first_neighbor]
            prev, cur = start, first_neighbor
            while graph.degree(cur) == 2 and cur not in junctions:
                nxt = next(n for n in graph.neighbors(cur) if n != prev)
                e_key = frozenset((cur, nxt))
                if e_key in visited_edges:
                    break
                visited_edges.add(e_key)
                chain.append(nxt)
                prev, cur = cur, nxt

            if len(chain) <= 2:
                continue

            simplified = _rdp(chain, epsilon)
            for a, b in zip(chain, chain[1:]):
                if graph.has_edge(a, b):
                    graph.remove_edge(a, b)
            for a, b in zip(simplified, simplified[1:]):
                w = math.hypot(a[0] - b[0], a[1] - b[1])
                graph.add_edge(a, b, weight=w)

    graph.remove_nodes_from([n for n in list(graph.nodes()) if graph.degree(n) == 0])
    return graph
