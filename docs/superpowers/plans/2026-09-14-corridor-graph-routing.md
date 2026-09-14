# Corridor-Graph Routing Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Smart Path's hand-tuned grid-A* corridor bias with a real corridor-centerline graph (Voronoi skeleton of the walkable area), used as the primary routing method with today's grid A* kept as an automatic whole-route fallback.

**Architecture:** A new `backend/corridor_graph.py` module builds a `shapely` walkable-area polygon (FLOOD/obstacles/door-notching in vector space) and a cleaned `networkx` skeleton graph from it, then routes ordered via-points on that graph via edge-snapping + Dijkstra. `backend/app.py` caches the graph per upload (lazily, on first Smart Path request) and falls back to the existing `find_multi_path` (grid A*) if graph construction or routing fails for any reason.

**Tech Stack:** Python 3.13, Flask, `shapely` (2.1.2, already installed in the project venv), `networkx` (new), `scipy.spatial.Voronoi`/`cKDTree`, `numpy`, `pytest` (new, for this project's first real automated test suite).

**Spec:** `docs/superpowers/specs/2026-09-14-corridor-graph-routing-design.md`

## Global Constraints

- No git repository exists for this project (user declined to init one on 2026-09-02) — do not run any git commands as part of this plan; skip every "commit" step below (left in the task structure for format consistency, but each says "N/A — no git repo" instead of a real command).
- Project venv is at `C:\Users\kevin\revit-walkthrough-v2\.venv` — always invoke its `python.exe`/`pip.exe` directly (never a bare `python`/`pip`), per this project's established gotcha (a bare `python` can resolve to an unrelated project's venv on PATH).
- Windows/PowerShell environment — use `;` not `&&` if a step ever needs chaining outside the Bash tool (the Bash tool here runs Git Bash, so `&&` is fine inside it).
- Classification-driven design principle (see `feedback_classification_driven_routing` memory): any obstacle/door/wall handling must derive from the classify schema (walls/doors/windows/columns/FLOOD/furniture) and our own tunable parameters (`clearance_m`, `door_clear_margin_m`, `max_bridge_m`) — never from one specific file's drawn geometry.
- Graph routing must never mix with grid-A* routing within a single request: if any leg fails on the graph, the ENTIRE route falls back to `find_multi_path`.
- Existing modules (`autopath.py`, `app.py`'s existing routes/caches) must keep working exactly as before for any code path that doesn't touch the new graph feature — this is an additive change with a fallback, not a rewrite of the existing grid A*.

---

### Task 1: Dependencies and test scaffolding

**Files:**
- Modify: `requirements.txt`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/pytest.ini`
- Create: `backend/tests/test_scaffolding.py`

**Interfaces:**
- Produces: a working `pytest` setup under `backend/tests/` that can import any `backend/*.py` module directly (e.g. `import corridor_graph`), for every later task to build on.

- [ ] **Step 1: Add new dependencies to `requirements.txt`**

Current content of `requirements.txt`:
```
flask>=3.0.0
flask-cors>=4.0.0
numpy>=1.26.0
scipy>=1.12.0
ezdxf>=1.1.0
svgwrite>=1.4.3
werkzeug>=3.0.0
ifcopenshell
gunicorn>=22.0.0
```

Replace with:
```
flask>=3.0.0
flask-cors>=4.0.0
numpy>=1.26.0
scipy>=1.12.0
ezdxf>=1.1.0
svgwrite>=1.4.3
werkzeug>=3.0.0
ifcopenshell
gunicorn>=22.0.0
shapely>=2.1.0
networkx>=3.0
pytest>=8.0.0
```

- [ ] **Step 2: Install the new dependencies into the project venv**

Run:
```
cd "C:\Users\kevin\revit-walkthrough-v2" && ".venv/Scripts/python.exe" -m pip install networkx pytest
```
(`shapely` is already installed at 2.1.2 — confirm with `".venv/Scripts/python.exe" -c "import shapely; print(shapely.__version__)"`, no install needed.)

Expected: both installs succeed; `".venv/Scripts/python.exe" -c "import networkx, pytest, shapely; print('ok')"` prints `ok`.

- [ ] **Step 3: Create `backend/tests/__init__.py`**

Empty file — makes `tests` a proper package so relative imports behave consistently across pytest versions.

```python
```

- [ ] **Step 4: Create `backend/tests/conftest.py`**

```python
import sys
from pathlib import Path

# Every backend module (app.py, autopath.py, corridor_graph.py, ...) is
# imported as a top-level module, not a package — app.py itself relies on
# this by inserting its own directory onto sys.path at import time. Tests
# need the same thing available BEFORE any test file imports those modules
# directly (e.g. `import corridor_graph`) without going through app.py first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 5: Create `backend/pytest.ini`**

```ini
[pytest]
testpaths = tests
```

This keeps a bare `pytest` invocation from `backend/` scoped to `backend/tests/` — the project's `.venv/Lib/site-packages` contains thousands of vendored test files (numpy, colorama, ifcopenshell) that would otherwise get collected too.

- [ ] **Step 6: Write and run a smoke test**

`backend/tests/test_scaffolding.py`:
```python
def test_backend_modules_importable():
    import autopath  # noqa: F401
    import app  # noqa: F401
    assert True
```

Run:
```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_scaffolding.py -v
```
Expected: `1 passed`.

- [ ] **Step 7: Commit**

N/A — no git repository for this project (see Global Constraints). Skip.

---

### Task 2: Obstacle-to-shape conversion and wall polygon with door notching

**Files:**
- Create: `backend/corridor_graph.py`
- Test: `backend/tests/test_corridor_graph_polygon.py`

**Interfaces:**
- Consumes: nothing from other tasks (first real code in the new module).
- Produces:
  - `_polyline_to_shape(poly: list, buffer_amt: float, min_line_buffer: float = 0.0) -> shapely.geometry.base.BaseGeometry`
  - `_polygon_from_ring(poly: list) -> shapely.geometry.Polygon`
  - `_build_wall_polygon(walls: list, doors: list, clearance: float, door_half: float) -> shapely.geometry.base.BaseGeometry`
  used by Task 3's `build_walkable_polygon`.

- [ ] **Step 1: Write failing tests for `_polyline_to_shape`**

`backend/tests/test_corridor_graph_polygon.py`:
```python
from shapely.geometry import Polygon, LineString
import corridor_graph as cg


def test_polyline_to_shape_closed_polygon_keeps_real_area():
    # A 2x2 square, closed (first point repeated at the end)
    square = [(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]
    shape = cg._polyline_to_shape(square, buffer_amt=0.0)
    assert shape.area > 3.9  # ~4, allow for float slop


def test_polyline_to_shape_open_line_needs_buffer_for_area():
    line = [(0, 0), (5, 0)]
    shape = cg._polyline_to_shape(line, buffer_amt=0.5)
    assert shape.area > 0
    # buffering a 5-unit line by 0.5 gives a stadium shape close to 5*1 + pi*0.25^2... just check it's reasonably sized
    assert 4.0 < shape.area < 6.5


def test_polyline_to_shape_open_line_gets_minimum_thickness_even_at_zero_buffer():
    # A raw 2-point wall "line" (zero-width) must not vanish entirely even
    # when the caller passes buffer_amt=0.0 (the last clearance-retry level
    # in autopath.py's find_path uses exactly this) — otherwise a wall
    # represented as a bare LINE entity would silently stop blocking
    # anything at the most permissive retry level, unlike the grid approach
    # where rasterizing a line's bbox always yields at least one blocked
    # grid cell's worth of thickness.
    line = [(0, 0), (5, 0)]
    shape = cg._polyline_to_shape(line, buffer_amt=0.0, min_line_buffer=0.05)
    assert shape.area > 0
```

- [ ] **Step 2: Run to verify failure**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_polygon.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'corridor_graph'` (file doesn't exist yet).

- [ ] **Step 3: Create `backend/corridor_graph.py` with the polygon-construction primitives**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_polygon.py -v
```
Expected: `3 passed`.

- [ ] **Step 5: Add and run a door-notching test for `_build_wall_polygon`**

Append to `backend/tests/test_corridor_graph_polygon.py`:
```python
from shapely.geometry import Point


def test_build_wall_polygon_door_notch_creates_real_gap():
    # A single long wall line with a door at its midpoint.
    wall = [(0, 0), (10, 0)]
    door = [(5, -0.05), (5, 0.05)]
    wall_poly = cg._build_wall_polygon([wall], [door], clearance=0.3, door_half=0.6,
                                        min_line_buffer=0.05)
    # The door's own location must now be OUTSIDE the (notched) wall shape.
    assert not wall_poly.covers(Point(5, 0))
    # A point far from the door, still on the wall line, must still be blocked.
    assert wall_poly.covers(Point(1, 0))


def test_build_wall_polygon_no_doors_is_solid():
    wall = [(0, 0), (10, 0)]
    wall_poly = cg._build_wall_polygon([wall], [], clearance=0.3, door_half=0.6,
                                        min_line_buffer=0.05)
    assert wall_poly.covers(Point(5, 0))
```

Run:
```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_polygon.py -v
```
Expected: `5 passed`.

- [ ] **Step 6: Commit**

N/A — no git repository for this project. Skip.

---

### Task 3: Full walkable-area polygon (`build_walkable_polygon`) and bounds helper

**Files:**
- Modify: `backend/corridor_graph.py`
- Test: `backend/tests/test_corridor_graph_polygon.py`

**Interfaces:**
- Consumes: `_build_wall_polygon`, `_polyline_to_shape`, `_polygon_from_ring` (Task 2).
- Produces:
  - `compute_bounds(walls: list, footprint: list, margin_frac: float = 0.02) -> tuple[float, float, float, float]`
  - `build_walkable_polygon(walls, doors, other_obstacles, footprint, bounds, clearance_m, units_to_metres, door_clear_margin_m=0.15) -> shapely.geometry.base.BaseGeometry | None`
  used by Task 6's `build_corridor_graph` and by `app.py` (Task 8).

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_corridor_graph_polygon.py`:
```python
def test_compute_bounds_from_walls_and_footprint():
    walls = [[(0, 0), (10, 0)], [(0, 0), (0, 5)]]
    bounds = cg.compute_bounds(walls, [])
    xmin, ymin, xmax, ymax = bounds
    assert xmin < 0 and ymin < 0  # margin applied
    assert xmax > 10 and ymax > 5


def test_build_walkable_polygon_room_with_gap_in_south_wall():
    # A 10x10 room. North/east/west walls solid; south wall has a real 2-unit
    # gap in the middle (an actual doorway drawn as a gap, no door needed
    # to force it open).
    walls = [
        [(0, 10), (10, 10)],   # north
        [(10, 0), (10, 10)],   # east
        [(0, 0), (0, 10)],     # west
        [(0, 0), (4, 0)],      # south-west segment
        [(6, 0), (10, 0)],     # south-east segment (2-unit gap between x=4..6)
    ]
    bounds = cg.compute_bounds(walls, [])
    walkable = cg.build_walkable_polygon(
        walls, doors=[], other_obstacles=[], footprint=[],
        bounds=bounds, clearance_m=0.1, units_to_metres=1.0,
    )
    assert walkable is not None
    assert not walkable.is_empty
    # Room interior should be walkable.
    assert walkable.covers(Point(5, 5))
    # The gap itself should be walkable (it's a real opening, no notch needed).
    assert walkable.covers(Point(5, 0.2))


def test_build_walkable_polygon_no_footprint_uses_bounding_envelope():
    walls = [[(0, 0), (10, 0)]]
    bounds = cg.compute_bounds(walls, [])
    walkable = cg.build_walkable_polygon(
        walls, doors=[], other_obstacles=[], footprint=[],
        bounds=bounds, clearance_m=0.1, units_to_metres=1.0,
    )
    assert walkable is not None
    # A point well within bounds but away from the single wall line is walkable.
    assert walkable.covers(Point(5, 5))


def test_build_walkable_polygon_empty_when_fully_blocked():
    # A footprint fully covered by a buffered obstacle leaves nothing walkable.
    walls = [[(0, 0), (0, 0)]]  # degenerate, ignored (len < 2 after filtering isn't true here but harmless)
    footprint = [[(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]]
    other_obstacles = [[(-1, -1), (3, -1), (3, 3), (-1, 3), (-1, -1)]]  # covers the whole footprint
    bounds = (0, 0, 2, 2)
    walkable = cg.build_walkable_polygon(
        walls, doors=[], other_obstacles=other_obstacles, footprint=footprint,
        bounds=bounds, clearance_m=0.0, units_to_metres=1.0,
    )
    assert walkable is None
```

- [ ] **Step 2: Run to verify failure**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_polygon.py -v -k "compute_bounds or build_walkable_polygon"
```
Expected: FAIL — `AttributeError: module 'corridor_graph' has no attribute 'compute_bounds'` (and `build_walkable_polygon`).

- [ ] **Step 3: Implement `compute_bounds` and `build_walkable_polygon` in `backend/corridor_graph.py`**

Append to `backend/corridor_graph.py`:
```python
_MIN_WALL_BUFFER_M = 0.05  # minimum wall band half-thickness, see _polyline_to_shape


def compute_bounds(walls: list, footprint: list, margin_frac: float = 0.02) -> tuple:
    """
    Same bounds convention as autopath.py's find_path: walls + footprint
    extent, padded by margin_frac, used both as the fallback "no FLOOD
    layer" walkable envelope and to size the Voronoi boundary densification.
    """
    all_pts = [pt for w in walls for pt in w] + [pt for poly in footprint for pt in poly]
    if not all_pts:
        return (0.0, 0.0, 1.0, 1.0)
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    margin = max(max(xs) - min(xs), max(ys) - min(ys)) * margin_frac
    return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)


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
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_polygon.py -v
```
Expected: `9 passed`.

- [ ] **Step 5: Commit**

N/A — no git repository for this project. Skip.

---

### Task 4: Boundary densification and raw Voronoi skeleton

**Files:**
- Modify: `backend/corridor_graph.py`
- Test: `backend/tests/test_corridor_graph_skeleton.py`

**Interfaces:**
- Consumes: a walkable `shapely` polygon (Task 3's `build_walkable_polygon` output).
- Produces:
  - `_densify_boundary(polygon, spacing: float) -> list[tuple[float, float]]`
  - `_voronoi_skeleton(polygon, boundary_pts: list) -> networkx.Graph` (nodes are `(x, y)` tuples, edges carry a `weight` = Euclidean length)
  used by Task 6's `build_corridor_graph`.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_corridor_graph_skeleton.py`:
```python
from shapely.geometry import box, Point
import corridor_graph as cg


def test_densify_boundary_covers_perimeter_densely():
    square = box(0, 0, 10, 10)  # perimeter = 40
    pts = cg._densify_boundary(square, spacing=1.0)
    assert len(pts) >= 30  # roughly perimeter/spacing, allow slack
    # every point should lie on (or extremely close to) the square's boundary
    for x, y in pts:
        assert square.boundary.distance(Point(x, y)) < 1e-6


def test_densify_boundary_dedupes_points():
    square = box(0, 0, 10, 10)
    pts = cg._densify_boundary(square, spacing=1.0)
    assert len(pts) == len(set(pts))


def test_voronoi_skeleton_of_long_corridor_has_a_center_running_edge():
    # A long, thin walkable rectangle — the medial axis should be a single
    # line running down its horizontal center.
    corridor = box(0, 0, 20, 2)
    boundary_pts = cg._densify_boundary(corridor, spacing=0.5)
    graph = cg._voronoi_skeleton(corridor, boundary_pts)
    assert graph.number_of_nodes() > 0
    assert graph.number_of_edges() > 0
    # every kept node should be near y=1 (the corridor's centerline) and
    # strictly inside the polygon
    for (x, y) in graph.nodes():
        assert corridor.buffer(1e-6).contains(Point(x, y))
        assert abs(y - 1.0) < 0.6  # medial axis of a straight strip is its centerline
```

- [ ] **Step 2: Run to verify failure**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_skeleton.py -v
```
Expected: FAIL — `AttributeError: module 'corridor_graph' has no attribute '_densify_boundary'`.

- [ ] **Step 3: Implement `_densify_boundary` and `_voronoi_skeleton`**

Append to `backend/corridor_graph.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_skeleton.py -v
```
Expected: `3 passed`.

- [ ] **Step 5: Commit**

N/A — no git repository for this project. Skip.

---

### Task 5: Skeleton cleanup pipeline (merge, stub removal, RDP branch simplification)

**Files:**
- Modify: `backend/corridor_graph.py`
- Test: `backend/tests/test_corridor_graph_cleanup.py`

**Interfaces:**
- Consumes: a raw skeleton `networkx.Graph` (Task 4's `_voronoi_skeleton` output).
- Produces:
  - `_merge_close_nodes(graph, tol: float) -> networkx.Graph`
  - `_remove_short_stub_segments(graph, min_len: float) -> networkx.Graph`
  - `_rdp(points: list, epsilon: float) -> list`
  - `_simplify_branches(graph, epsilon: float) -> networkx.Graph`
  used by Task 6's `build_corridor_graph`.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_corridor_graph_cleanup.py`:
```python
import networkx as nx
import corridor_graph as cg


def _line_weight(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def test_merge_close_nodes_collapses_near_duplicates():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (5.0, 0.0), weight=5.0)
    g.add_edge((5.0, 0.0), (5.01, 0.02), weight=_line_weight((5.0, 0.0), (5.01, 0.02)))
    g.add_edge((5.01, 0.02), (10.0, 0.0), weight=_line_weight((5.01, 0.02), (10.0, 0.0)))
    merged = cg._merge_close_nodes(g, tol=0.1)
    # the two near-duplicate junction nodes should have collapsed into one
    assert merged.number_of_nodes() == 3


def test_remove_short_stub_segments_drops_dead_end_noise():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (10.0, 0.0), weight=10.0)
    g.add_edge((5.0, 0.0), (5.0, 0.1), weight=0.1)  # short dead-end stub
    cleaned = cg._remove_short_stub_segments(g, min_len=0.5)
    assert (5.0, 0.1) not in cleaned.nodes()
    assert (0.0, 0.0) in cleaned.nodes() and (10.0, 0.0) in cleaned.nodes()


def test_remove_short_stub_segments_keeps_long_dead_ends():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (10.0, 0.0), weight=10.0)
    g.add_edge((5.0, 0.0), (5.0, 3.0), weight=3.0)  # a real, longer side branch
    cleaned = cg._remove_short_stub_segments(g, min_len=0.5)
    assert (5.0, 3.0) in cleaned.nodes()


def test_rdp_collapses_nearly_collinear_points():
    points = [(0.0, 0.0), (5.0, 0.01), (10.0, 0.0)]
    simplified = cg._rdp(points, epsilon=0.5)
    assert simplified == [(0.0, 0.0), (10.0, 0.0)]


def test_rdp_keeps_a_real_corner():
    points = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
    simplified = cg._rdp(points, epsilon=0.5)
    assert (5.0, 5.0) in simplified


def test_simplify_branches_reduces_a_noisy_straight_chain():
    g = nx.Graph()
    chain = [(float(i), 0.01 if i % 2 else 0.0) for i in range(11)]
    for a, b in zip(chain, chain[1:]):
        g.add_edge(a, b, weight=_line_weight(a, b))
    simplified = cg._simplify_branches(g, epsilon=0.5)
    assert simplified.number_of_nodes() < g.number_of_nodes()
    assert chain[0] in simplified.nodes() and chain[-1] in simplified.nodes()
```

- [ ] **Step 2: Run to verify failure**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_cleanup.py -v
```
Expected: FAIL — `AttributeError: module 'corridor_graph' has no attribute '_merge_close_nodes'`.

- [ ] **Step 3: Implement the cleanup pipeline**

Append to `backend/corridor_graph.py`:
```python
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
            if graph.degree(node) != 1:
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_cleanup.py -v
```
Expected: `6 passed`.

- [ ] **Step 5: Commit**

N/A — no git repository for this project. Skip.

---

### Task 6: Door bridging for residual disconnection and the `build_corridor_graph` orchestrator

**Files:**
- Modify: `backend/corridor_graph.py`
- Test: `backend/tests/test_corridor_graph_build.py`

**Interfaces:**
- Consumes: Task 3 (`build_walkable_polygon`), Task 4 (`_densify_boundary`, `_voronoi_skeleton`), Task 5 (`_merge_close_nodes`, `_remove_short_stub_segments`, `_simplify_branches`).
- Produces: `build_corridor_graph(walkable_polygon, doors: list, spacing_m: float = 0.4, merge_tol_m: float = 0.3, stub_min_len_m: float = 0.5, simplify_epsilon_m: float = 0.15, max_bridge_m: float = 3.5) -> networkx.Graph | None`
  used by Task 7 (`route_multi`) and Task 8 (`app.py`).

- [ ] **Step 1: Write failing tests**

`backend/tests/test_corridor_graph_build.py`:
```python
import networkx as nx
from shapely.geometry import box, Point
import corridor_graph as cg


def test_bridge_doors_across_components_connects_two_rooms():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (4.0, 0.0), weight=4.0)   # component A
    g.add_edge((6.0, 0.0), (10.0, 0.0), weight=4.0)  # component B
    door = [(5.0, -0.1), (5.0, 0.1)]  # centroid at (5, 0), between the two
    bridged = cg._bridge_doors_across_components(g, [door], max_bridge_m=2.0)
    assert nx.number_connected_components(bridged) == 1


def test_bridge_doors_across_components_respects_max_bridge_distance():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (4.0, 0.0), weight=4.0)
    g.add_edge((100.0, 0.0), (104.0, 0.0), weight=4.0)
    door = [(50.0, 0.0)]
    bridged = cg._bridge_doors_across_components(g, [door], max_bridge_m=2.0)
    assert nx.number_connected_components(bridged) == 2


def test_build_corridor_graph_on_simple_room():
    room = box(0, 0, 10, 10)
    graph = cg.build_corridor_graph(room, doors=[])
    assert graph is not None
    assert graph.number_of_nodes() > 0
    assert graph.number_of_edges() > 0
    for (x, y) in graph.nodes():
        assert room.buffer(1e-3).contains(Point(x, y))


def test_build_corridor_graph_none_for_empty_polygon():
    from shapely.geometry import Polygon
    assert cg.build_corridor_graph(Polygon(), doors=[]) is None
```

- [ ] **Step 2: Run to verify failure**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_build.py -v
```
Expected: FAIL — `AttributeError: module 'corridor_graph' has no attribute '_bridge_doors_across_components'`.

- [ ] **Step 3: Implement door bridging and the orchestrator**

Append to `backend/corridor_graph.py`:
```python
def _bridge_doors_across_components(graph, doors: list, max_bridge_m: float) -> "nx.Graph":
    """
    For each classified door whose two sides still land in different
    connected components of the graph (the wall-notch in
    build_walkable_polygon didn't fully reconnect them — e.g. furniture or
    a second wall layer still blocks the straight-line gap), add a direct
    edge between the nearest node of each of the two nearest components to
    that door's centroid, capped at max_bridge_m. This mirrors
    autopath.py's _bridge_gap: bridge only a real, specific, minimal gap —
    never a blanket radius.
    """
    graph = graph.copy()
    if graph.number_of_nodes() == 0 or not doors:
        return graph

    for door in doors:
        if not door:
            continue
        cx = sum(p[0] for p in door) / len(door)
        cy = sum(p[1] for p in door) / len(door)

        components = list(nx.connected_components(graph))
        if len(components) <= 1:
            break

        best_per_component = []
        for comp in components:
            nearest = min(comp, key=lambda n: math.hypot(n[0] - cx, n[1] - cy))
            dist = math.hypot(nearest[0] - cx, nearest[1] - cy)
            if dist <= max_bridge_m:
                best_per_component.append((dist, nearest))
        best_per_component.sort(key=lambda t: t[0])

        if len(best_per_component) >= 2:
            (_, n1), (_, n2) = best_per_component[0], best_per_component[1]
            graph.add_edge(n1, n2, weight=math.hypot(n1[0] - n2[0], n1[1] - n2[1]))

    return graph


def build_corridor_graph(walkable_polygon, doors: list, spacing_m: float = 0.4,
                          merge_tol_m: float = 0.3, stub_min_len_m: float = 0.5,
                          simplify_epsilon_m: float = 0.15, max_bridge_m: float = 3.5):
    """
    Full pipeline: walkable polygon -> densified boundary -> raw Voronoi
    skeleton -> cleanup (merge/destub/simplify) -> door bridging. Returns
    None if no usable graph resulted (empty polygon, degenerate boundary,
    or a graph left with no edges) — the caller (app.py) must fall back to
    grid A* in that case.
    """
    if walkable_polygon is None or walkable_polygon.is_empty:
        return None

    boundary_pts = _densify_boundary(walkable_polygon, spacing_m)
    if len(boundary_pts) < 4:
        return None

    graph = _voronoi_skeleton(walkable_polygon, boundary_pts)
    graph = _merge_close_nodes(graph, merge_tol_m)
    graph = _remove_short_stub_segments(graph, stub_min_len_m)
    graph = _simplify_branches(graph, simplify_epsilon_m)
    graph = _bridge_doors_across_components(graph, doors, max_bridge_m)

    return graph if graph.number_of_edges() > 0 else None
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_build.py -v
```
Expected: `4 passed`.

- [ ] **Step 5: Commit**

N/A — no git repository for this project. Skip.

---

### Task 7: Via-point snapping and `route_multi`

**Files:**
- Modify: `backend/corridor_graph.py`
- Test: `backend/tests/test_corridor_graph_routing.py`

**Interfaces:**
- Consumes: `build_corridor_graph`'s output graph (Task 6), `_point_seg_dist` (imported from `autopath.py`).
- Produces: `route_multi(points: list, graph: networkx.Graph, walkable_polygon, max_pts: int = 12) -> list[list[float]] | None`
  used by `app.py` (Task 8).

- [ ] **Step 1: Write failing tests**

`backend/tests/test_corridor_graph_routing.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_routing.py -v
```
Expected: FAIL — `AttributeError: module 'corridor_graph' has no attribute 'route_multi'`.

- [ ] **Step 3: Implement snapping, polygon-based reduction, and `route_multi`**

Append to `backend/corridor_graph.py`:
```python
def _project_point_onto_segment(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 < 1e-12:
        return a, math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
    proj = (ax + t * dx, ay + t * dy)
    return proj, math.hypot(px - proj[0], py - proj[1])


def _snap_to_nearest_edge(graph, point):
    """
    Project `point` onto the nearest position on the nearest graph edge,
    splitting that edge at the projection (rather than snapping to an
    existing node) so via-points land as close as possible to where the
    user actually clicked. Mutates `graph` in place — callers must pass a
    per-request copy, never the shared cached graph.
    """
    if graph.number_of_edges() == 0:
        raise ValueError("graph has no edges to snap onto")

    best = None
    for u, v in graph.edges():
        proj, dist = _project_point_onto_segment(point, u, v)
        if best is None or dist < best[0]:
            best = (dist, u, v, proj)
    _, u, v, proj = best

    if proj == u:
        return u
    if proj == v:
        return v

    d_up = math.hypot(proj[0] - u[0], proj[1] - u[1])
    d_vp = math.hypot(proj[0] - v[0], proj[1] - v[1])
    graph.remove_edge(u, v)
    graph.add_edge(u, proj, weight=d_up)
    graph.add_edge(proj, v, weight=d_vp)
    return proj


def _los_clear_poly(p1, p2, walkable_polygon) -> bool:
    """Polygon-space equivalent of autopath.py's grid-based _los_clear:
    true if the straight segment p1->p2 stays entirely inside the walkable
    area."""
    line = LineString([p1, p2])
    return walkable_polygon.buffer(1e-6).contains(line)


def _reduce_to_max_pts_poly(pts: list, walkable_polygon, max_pts: int) -> list:
    """
    Polygon-space adaptation of autopath.py's _reduce_to_max_pts — same
    greedy one-point-at-a-time removal (least perpendicular deviation
    first, only when the resulting segment stays inside the walkable area),
    just backed by a polygon containment check instead of a raster grid
    lookup, since the corridor-graph path has no occupancy grid at all.
    """
    pts = list(pts)
    while len(pts) > max_pts:
        best_i, best_cost = None, None
        for i in range(1, len(pts) - 1):
            if not _los_clear_poly(pts[i - 1], pts[i + 1], walkable_polygon):
                continue
            cost = _point_seg_dist(pts[i], pts[i - 1], pts[i + 1])
            if best_cost is None or cost < best_cost:
                best_cost, best_i = cost, i
        if best_i is None:
            break
        del pts[best_i]
    return pts


def route_multi(points: list, graph, walkable_polygon, max_pts: int = 12):
    """
    Route an ORDERED sequence of required reference points on the corridor
    graph: snap each to the nearest edge, chain shortest paths between
    consecutive snapped points IN CLICK ORDER (never reordered), then
    squeeze the result toward max_pts.

    Returns None (never an empty list) on any failure — no graph, no edges
    to snap onto, or no path between two consecutive via-points — signaling
    the caller (app.py) to fall back to grid A* for the ENTIRE route.
    """
    if graph is None or graph.number_of_edges() == 0:
        return None

    g = graph.copy()
    try:
        snapped = [_snap_to_nearest_edge(g, tuple(p)) for p in points]
    except ValueError:
        return None

    combined = [snapped[0]]
    boundary_indices = [0]
    for i in range(len(snapped) - 1):
        try:
            leg = nx.shortest_path(g, snapped[i], snapped[i + 1], weight="weight")
        except nx.NetworkXNoPath:
            return None
        combined.extend(leg[1:])
        boundary_indices.append(len(combined) - 1)

    world_path = [[float(x), float(y)] for x, y in combined]

    # Use the literal clicked coordinate for every via-point that's actually
    # inside the walkable area (mirrors autopath.py's find_path: prefer the
    # exact click over the snapped position whenever it's legitimately
    # routable), not just the overall start/end.
    for orig_pt, idx in zip(points, boundary_indices):
        if walkable_polygon.covers(Point(orig_pt)):
            world_path[idx] = [float(orig_pt[0]), float(orig_pt[1])]

    if len(world_path) > max_pts:
        world_path = _reduce_to_max_pts_poly(world_path, walkable_polygon, max_pts)

    return world_path
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_routing.py -v
```
Expected: `4 passed`.

- [ ] **Step 5: Run the full `corridor_graph.py` test suite together**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_polygon.py tests/test_corridor_graph_skeleton.py tests/test_corridor_graph_cleanup.py tests/test_corridor_graph_build.py tests/test_corridor_graph_routing.py -v
```
Expected: all pass (26 tests across the five files).

- [ ] **Step 6: Commit**

N/A — no git repository for this project. Skip.

---

### Task 8: Wire the corridor graph into `app.py` with grid-A* fallback

**Files:**
- Modify: `backend/app.py:46` (imports), `backend/app.py:58-61` (cache globals), `backend/app.py:187-191` (upload), `backend/app.py:236-244` (upload_3d), `backend/app.py:270-277` (demo), `backend/app.py:298-338` (`/api/autopath`)
- Test: `backend/tests/test_app_autopath_integration.py`

**Interfaces:**
- Consumes: `corridor_graph.build_walkable_polygon`, `corridor_graph.build_corridor_graph`, `corridor_graph.route_multi`, `corridor_graph.compute_bounds` (Tasks 3, 6, 7); existing `find_multi_path` (unchanged, `autopath.py`).
- Produces: `/api/autopath` now tries the corridor graph first, falls back to grid A* — no change to the endpoint's request/response JSON shape, so the frontend needs no changes.

- [ ] **Step 1: Write failing integration tests**

`backend/tests/test_app_autopath_integration.py`:
```python
import io
import json

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _upload_demo(client):
    resp = client.get("/api/demo")
    assert resp.status_code == 200
    return resp.get_json()


def test_autopath_uses_corridor_graph_when_available(client, monkeypatch):
    _upload_demo(client)

    calls = {"route_multi": 0}
    real_route_multi = app_module.route_multi

    def spy_route_multi(*args, **kwargs):
        calls["route_multi"] += 1
        return real_route_multi(*args, **kwargs)

    monkeypatch.setattr(app_module, "route_multi", spy_route_multi)

    resp = client.post("/api/autopath", json={"start": [1, 1], "end": [2, 2]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "waypoints" in data
    assert calls["route_multi"] >= 1


def test_autopath_falls_back_to_grid_astar_when_graph_build_fails(client, monkeypatch):
    _upload_demo(client)

    monkeypatch.setattr(app_module, "build_corridor_graph", lambda *a, **k: None)

    calls = {"find_multi_path": 0}
    real_find_multi_path = app_module.find_multi_path

    def spy(*args, **kwargs):
        calls["find_multi_path"] += 1
        return real_find_multi_path(*args, **kwargs)

    monkeypatch.setattr(app_module, "find_multi_path", spy)

    resp = client.post("/api/autopath", json={"start": [1, 1], "end": [2, 2]})
    assert resp.status_code == 200
    assert calls["find_multi_path"] == 1


def test_autopath_falls_back_when_route_multi_returns_none(client, monkeypatch):
    _upload_demo(client)

    monkeypatch.setattr(app_module, "route_multi", lambda *a, **k: None)

    calls = {"find_multi_path": 0}
    real_find_multi_path = app_module.find_multi_path

    def spy(*args, **kwargs):
        calls["find_multi_path"] += 1
        return real_find_multi_path(*args, **kwargs)

    monkeypatch.setattr(app_module, "find_multi_path", spy)

    resp = client.post("/api/autopath", json={"start": [1, 1], "end": [2, 2]})
    assert resp.status_code == 200
    assert calls["find_multi_path"] == 1


def test_upload_bumps_generation_and_invalidates_graph_cache(client):
    gen_before = app_module._UPLOAD_GENERATION
    _upload_demo(client)
    assert app_module._UPLOAD_GENERATION > gen_before
```

- [ ] **Step 2: Run to verify failure**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_app_autopath_integration.py -v
```
Expected: FAIL — `AttributeError: module 'app' has no attribute 'route_multi'` (not imported/wired yet).

- [ ] **Step 3: Modify `backend/app.py`**

Change the import line (`app.py:46`):
```python
from autopath        import find_multi_path
from corridor_graph   import (build_walkable_polygon, build_corridor_graph,
                               route_multi, compute_bounds)
```

Add new cache globals right after the existing ones (`app.py:58-61`, keep the existing four lines and append):
```python
_LAST_OBSTACLES = {"dxf": [], "ifc": []}
_LAST_FOOTPRINT = {"dxf": [], "ifc": []}  # FLOOD-layer / room polygons — see _footprint_polylines
_LAST_DOORS = {"dxf": [], "ifc": []}  # door locations, forced passable — see _door_polylines
_LAST_UNITS_TO_METRES = 1.0  # from the DXF/demo canvas source, for Auto Path's clearance_m conversion

# Corridor-graph routing needs walls kept SEPARATE from other obstacle
# categories (only walls get door-notched — see corridor_graph.py's
# build_walkable_polygon), unlike _LAST_OBSTACLES which flattens everything
# together for the grid-A* fallback's simpler needs.
_LAST_WALLS = {"dxf": [], "ifc": []}
_LAST_OTHER_OBSTACLES = {"dxf": [], "ifc": []}

# Bumped on every upload/demo call; the corridor-graph cache below is keyed
# on this so a new floor plan never reuses a stale graph.
_UPLOAD_GENERATION = 0

# (generation, round(clearance_m, 3)) -> (walkable_polygon | None, graph | None)
# Built lazily on the first /api/autopath call per key, not at upload time —
# keeps upload latency unaffected even for a real file with tens of
# thousands of furniture entities.
_LAST_CIRC_GRAPH: dict = {}
```

Add two new helper functions right after `_door_polylines` (`app.py`, after line 121):
```python
def _wall_polylines(geo) -> list:
    """Walls only, flipped into SVG-display space — see _obstacle_polylines
    for why the flip is needed. Kept separate from other obstacle
    categories because only walls get door-notched in corridor_graph.py."""
    return [_flip(p) for p in geo.walls]


def _other_obstacle_polylines(geo) -> list:
    """Columns, furniture, windows — everything _obstacle_polylines
    combines with walls, minus the walls themselves."""
    return ([_flip(p) for p in geo.windows] +
            [_flip(p) for p in geo.columns] +
            [_flip(p) for p in geo.furniture])


def _get_circ_graph_and_polygon(clearance_m: float):
    """
    Lazily build (and cache) the corridor graph for the current upload at a
    given clearance_m. Any exception during construction is treated the
    same as "no graph" — the caller falls back to grid A* — rather than
    ever 500ing a Smart Path request because of a corridor-graph bug.
    """
    key = (_UPLOAD_GENERATION, round(clearance_m, 3))
    if key not in _LAST_CIRC_GRAPH:
        walls = _LAST_WALLS["dxf"] + _LAST_WALLS["ifc"]
        other = _LAST_OTHER_OBSTACLES["dxf"] + _LAST_OTHER_OBSTACLES["ifc"]
        footprint = _LAST_FOOTPRINT["dxf"] + _LAST_FOOTPRINT["ifc"]
        doors = _LAST_DOORS["dxf"] + _LAST_DOORS["ifc"]
        try:
            bounds = compute_bounds(walls, footprint)
            polygon = build_walkable_polygon(
                walls, doors, other, footprint, bounds,
                clearance_m=clearance_m, units_to_metres=_LAST_UNITS_TO_METRES,
            )
            graph = build_corridor_graph(polygon, doors) if polygon is not None else None
        except Exception:
            log.exception("Corridor graph build failed — Smart Path will use grid A* for this request")
            polygon, graph = None, None
        _LAST_CIRC_GRAPH[key] = (polygon, graph)
    return _LAST_CIRC_GRAPH[key]
```

Update `upload()` (replace `app.py:187-191`):
```python
    _LAST_OBSTACLES["dxf"] = _obstacle_polylines(geo)
    _LAST_FOOTPRINT["dxf"] = _footprint_polylines(geo)
    _LAST_DOORS["dxf"] = _door_polylines(geo)
    _LAST_WALLS["dxf"] = _wall_polylines(geo)
    _LAST_OTHER_OBSTACLES["dxf"] = _other_obstacle_polylines(geo)
    global _LAST_UNITS_TO_METRES, _UPLOAD_GENERATION
    _LAST_UNITS_TO_METRES = geo.units_to_metres
    _UPLOAD_GENERATION += 1
```

Update `upload_3d()` (replace `app.py:236-244`):
```python
    obstacles = _obstacle_polylines(geo)
    if obstacles:
        _LAST_OBSTACLES["ifc"] = obstacles
    footprint = _footprint_polylines(geo)
    if footprint:
        _LAST_FOOTPRINT["ifc"] = footprint
    doors = _door_polylines(geo)
    if doors:
        _LAST_DOORS["ifc"] = doors
    walls = _wall_polylines(geo)
    if walls:
        _LAST_WALLS["ifc"] = walls
    other = _other_obstacle_polylines(geo)
    if other:
        _LAST_OTHER_OBSTACLES["ifc"] = other
    global _UPLOAD_GENERATION
    _UPLOAD_GENERATION += 1
```

Update `demo()` (replace `app.py:270-277`):
```python
    _LAST_OBSTACLES["dxf"] = _obstacle_polylines(geo)
    _LAST_FOOTPRINT["dxf"] = _footprint_polylines(geo)
    _LAST_DOORS["dxf"] = _door_polylines(geo)
    _LAST_WALLS["dxf"] = _wall_polylines(geo)
    _LAST_OTHER_OBSTACLES["dxf"] = _other_obstacle_polylines(geo)
    global _LAST_UNITS_TO_METRES, _UPLOAD_GENERATION
    _LAST_UNITS_TO_METRES = geo.units_to_metres
    _LAST_OBSTACLES["ifc"] = []  # demo is a fresh, unrelated dataset
    _LAST_FOOTPRINT["ifc"] = []
    _LAST_DOORS["ifc"] = []
    _LAST_WALLS["ifc"] = []
    _LAST_OTHER_OBSTACLES["ifc"] = []
    _UPLOAD_GENERATION += 1
```

Update `/api/autopath` (replace `app.py:298-338`):
```python
@app.route("/api/autopath", methods=["POST"])
def autopath():
    data  = request.get_json(force=True)
    start = data.get("start")
    end   = data.get("end")
    # Ordered list of required reference points the route must pass through,
    # in order — e.g. [start, viaPoint, end]. `start`/`end` are still
    # accepted alone for a plain two-point route (and for older callers).
    points = data.get("points")
    if points:
        if len(points) < 2:
            return _err("points must contain at least a start and an end")
    elif start and end:
        points = [start, end]
    else:
        return _err("start and end points are required")
    # Obstacles (walls + columns + furniture, from both the DXF and any IFC
    # loaded alongside it) are cached server-side from the last upload —
    # sending them again from the client would mean re-transferring tens of
    # MB of JSON on every click for a real architectural DXF. `walls` in the
    # body is still honored if a caller explicitly provides it (e.g. tests).
    walls = data.get("walls") or (_LAST_OBSTACLES["dxf"] + _LAST_OBSTACLES["ifc"])
    # FLOOD-layer / room footprint polygons, cached the same way as obstacles
    # (see _footprint_polylines) — constrains routing to the real floor area
    # when the source provided one; empty for sources without a FLOOD layer.
    footprint = data.get("footprint") or (_LAST_FOOTPRINT["dxf"] + _LAST_FOOTPRINT["ifc"])
    # Door locations, forced passable regardless of nearby wall/furniture
    # geometry (see autopath.py's _clear_doors) — real doorways frequently
    # don't leave an actual gap in the wall data on a real DXF.
    doors = data.get("doors") or (_LAST_DOORS["dxf"] + _LAST_DOORS["ifc"])

    clearance_m = float(data.get("clearance_m", 0.2))

    # Corridor-graph routing (primary): a real corridor-centerline graph
    # instead of grid A*'s hand-tuned distance-transform corridor bias — see
    # docs/superpowers/specs/2026-09-14-corridor-graph-routing-design.md.
    # ANY failure here (graph build, or no route on the graph) falls back to
    # the ENTIRE route being computed by grid A* below, never a per-leg mix.
    waypoints = None
    polygon, graph = _get_circ_graph_and_polygon(clearance_m)
    if graph is not None:
        try:
            waypoints = route_multi(points, graph, polygon)
        except Exception:
            log.exception("Corridor-graph routing failed — falling back to grid A*")
            waypoints = None

    if not waypoints:
        waypoints = find_multi_path(
            points, walls,
            clearance_m=clearance_m,
            units_to_metres=_LAST_UNITS_TO_METRES,
            turn_penalty=float(data.get("turn_penalty", 4.0)),
            corridor_m=float(data.get("corridor_m", 1.0)),
            corridor_weight=float(data.get("corridor_weight", 0.5)),
            footprint=footprint,
            doors=doors,
        )

    return jsonify({"waypoints": waypoints})
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_app_autopath_integration.py -v
```
Expected: `4 passed`.

- [ ] **Step 5: Run the entire test suite so far**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest -v
```
Expected: all tests across every file pass.

- [ ] **Step 6: Commit**

N/A — no git repository for this project. Skip.

---

### Task 9: Real-file stress-test parity, regression, and fallback verification

**Files:**
- Test: `backend/tests/test_corridor_graph_real_files.py`

**Interfaces:**
- Consumes: everything from Tasks 1-8; the two real DXFs already present at `C:\Users\kevin\revit-walkthrough-v2\uploads\QQQQ_TEST-0001_-_Floor_Plan_-_L-0.dxf` and `C:\Users\kevin\revit-walkthrough-v2\uploads\Classify_DXF_45715-Sep_02nd_2026_12_38_33_PM.dxf`.
- Produces: no new production code — this task is the final correctness/performance gate before considering sub-project A done.

- [ ] **Step 1: Write the real-file stress test**

`backend/tests/test_corridor_graph_real_files.py`:
```python
import random
import time
from pathlib import Path

import pytest

import app as app_module

UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
QQQQ_FILE = UPLOADS_DIR / "QQQQ_TEST-0001_-_Floor_Plan_-_L-0.dxf"
REAL_FLOOD_FILE = UPLOADS_DIR / "Classify_DXF_45715-Sep_02nd_2026_12_38_33_PM.dxf"


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _upload_real_file(client, path: Path):
    """
    Uploads a copy of the real fixture under a DIFFERENT filename than the
    source. app.py's /api/upload saves the incoming file to
    uploads/<secure_filename(f.filename)> — if we uploaded using the
    fixture's own original name, Flask would write the save back to the
    exact same path we're reading it from mid-upload (the fixture lives in
    that same uploads/ directory), corrupting the committed test fixture.
    A harmless differently-named temp copy avoids that entirely.
    """
    assert path.exists(), f"expected real test fixture at {path}"
    temp_name = f"pytest_copy_{path.name}"
    with open(path, "rb") as f:
        data = {"file": (f, temp_name)}
        resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _random_point_within(bounds, rng):
    return [
        rng.uniform(bounds["xmin"], bounds["xmax"]),
        rng.uniform(bounds["ymin"], bounds["ymax"]),
    ]


def _stress_test_file(client, path: Path, n_triples: int, seed: int):
    upload = _upload_real_file(client, path)
    bounds = upload["bounds"]
    rng = random.Random(seed)

    failures = 0
    point_counts = []
    graph_used_count = 0

    for _ in range(n_triples):
        points = [_random_point_within(bounds, rng) for _ in range(5)]  # 5-point Smart Path
        resp = client.post("/api/autopath", json={"points": points})
        assert resp.status_code == 200
        waypoints = resp.get_json()["waypoints"]
        if not waypoints or len(waypoints) < 2:
            failures += 1
        else:
            point_counts.append(len(waypoints))

    return failures, point_counts


def test_qqqq_test_file_stress_5point_routes(client):
    start = time.time()
    failures, point_counts = _stress_test_file(client, QQQQ_FILE, n_triples=40, seed=42)
    elapsed = time.time() - start
    print(f"\nQQQQ_TEST-0001: {failures}/40 failures, "
          f"avg pts={sum(point_counts)/max(len(point_counts),1):.1f}, "
          f"max pts={max(point_counts, default=0)}, elapsed={elapsed:.1f}s")
    # Same bar as the grid-A* baseline established earlier this project
    # (0/40 failures) — the corridor graph (or its fallback) must not
    # regress this.
    assert failures == 0


def test_real_flood_file_stress_5point_routes(client):
    start = time.time()
    failures, point_counts = _stress_test_file(client, REAL_FLOOD_FILE, n_triples=20, seed=7)
    elapsed = time.time() - start
    print(f"\nreal FLOOD file: {failures}/20 failures, "
          f"avg pts={sum(point_counts)/max(len(point_counts),1):.1f}, "
          f"max pts={max(point_counts, default=0)}, elapsed={elapsed:.1f}s")
    assert failures == 0


def test_corridor_graph_builds_in_reasonable_time_on_largest_real_file(client):
    upload = _upload_real_file(client, REAL_FLOOD_FILE)
    bounds = upload["bounds"]
    start = time.time()
    resp = client.post("/api/autopath", json={
        "start": [bounds["xmin"] + 1, bounds["ymin"] + 1],
        "end": [bounds["xmax"] - 1, bounds["ymax"] - 1],
    })
    elapsed = time.time() - start
    assert resp.status_code == 200
    print(f"\nFirst Smart Path call after upload (graph build + route): {elapsed:.1f}s")
    # Generous ceiling — this is the ONE lazy-build call per (upload,
    # clearance_m); a second call right after should be much faster since
    # the graph is now cached.
    assert elapsed < 30.0

    start2 = time.time()
    resp2 = client.post("/api/autopath", json={
        "start": [bounds["xmin"] + 2, bounds["ymin"] + 2],
        "end": [bounds["xmax"] - 2, bounds["ymax"] - 2],
    })
    elapsed2 = time.time() - start2
    assert resp2.status_code == 200
    print(f"Second Smart Path call (graph cached): {elapsed2:.1f}s")
    assert elapsed2 < elapsed


def test_door_clearing_regression_does_not_erase_nearby_furniture(client, monkeypatch):
    """
    Reproduces the exact real regression found earlier this project: a
    small room (4m, smaller than an over-large blind clearing radius would
    have been) with an off-center door entity (centroid NOT on the true
    gap) and furniture flanking the real opening on both sides. The
    corridor-graph door-notch must open the real gap and must NOT swallow
    the flanking furniture.
    """
    import corridor_graph as cg
    from shapely.geometry import Point

    # A 4m-wide room split by a partition wall with a real 0.9m doorway gap
    # centered at x=2; door entity's own centroid is 1.3m off, on the solid
    # wall (mirrors the real file's misbehaved door geometry).
    partition_left = [(0.0, 2.0), (1.55, 2.0)]
    partition_right = [(2.45, 2.0), (4.0, 2.0)]
    door = [(0.7, 2.0), (0.7, 2.05)]  # centroid ~x=0.7, nowhere near the real gap at x=2
    furniture_left = [(0.3, 1.5), (0.9, 1.5), (0.9, 1.9), (0.3, 1.9), (0.3, 1.5)]
    furniture_right = [(3.1, 1.5), (3.7, 1.5), (3.7, 1.9), (3.1, 1.9), (3.1, 1.5)]

    bounds = cg.compute_bounds([partition_left, partition_right], [])
    walkable = cg.build_walkable_polygon(
        [partition_left, partition_right], [door], [furniture_left, furniture_right], [],
        bounds=bounds, clearance_m=0.1, units_to_metres=1.0,
    )
    assert walkable is not None
    # the real gap is walkable
    assert walkable.covers(Point(2.0, 2.0))
    # both furniture pieces remain solid obstacles (not swallowed by an
    # over-eager notch)
    assert not walkable.covers(Point(0.6, 1.7))
    assert not walkable.covers(Point(3.4, 1.7))
```

- [ ] **Step 2: Run to verify failure (module doesn't exist error first, then real failures)**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_real_files.py -v -s
```
Expected at this point: the file already imports only existing code (Tasks 1-8 are done by now in the plan's sequence), so this step is really "run it and see what real behavior looks like" rather than a true red step — read the console output carefully:
- failure counts, average/max point counts, and timings printed for both real files.
- If either stress test reports `failures > 0`, or the timing test exceeds its ceiling, this is a REAL signal to go back and adjust the corridor-graph parameters (`spacing_m`, `merge_tol_m`, `stub_min_len_m`, `max_bridge_m`) in `build_corridor_graph`'s defaults (Task 6) — do not weaken the test to make it pass.

- [ ] **Step 3: If failures/timeouts occur, tune and re-run**

Likely knobs, in order of expected impact:
1. `max_bridge_m` too small for this file's worst door offset — try raising from 3.5 to 5.0 (same reasoning as this project's earlier `door_clear_margin_m` tuning: measure on BOTH real files before committing to a new default, never just the one that's currently failing).
2. `spacing_m` too coarse for a file with narrow corridors — try 0.25 instead of 0.4.
3. If `unary_union` over furniture is the slow part (check by timing `build_walkable_polygon` alone in a quick throwaway script), batch the union: `unary_union([unary_union(other_shapes[i:i+500]) for i in range(0, len(other_shapes), 500)])` — GEOS's union scales better over many small batches than one flat 17,000-geometry call. Only apply this if profiling actually shows it's the bottleneck — don't add complexity speculatively.

Re-run Step 2's command after any tuning change until both stress tests report 0 failures and the timing test passes.

- [ ] **Step 4: Run the door-clearing regression test in isolation**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest tests/test_corridor_graph_real_files.py::test_door_clearing_regression_does_not_erase_nearby_furniture -v
```
Expected: PASS.

- [ ] **Step 5: Run the entire project test suite one final time**

```
cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "../.venv/Scripts/python.exe" -m pytest -v
```
Expected: all tests pass (this is the full suite built across Tasks 1-9).

- [ ] **Step 6: Manual visual spot-check (not automated)**

With the Flask dev server running (`cd backend && PYTHONUTF8=1 "../.venv/Scripts/python.exe" app.py`), open `http://localhost:5000`, load the real FLOOD-layer file, and run Smart Path with 5 clicks spanning a genuinely complex multi-room route (reuse coordinates from a case that previously needed ~100+ waypoints under grid A*, if still known/reproducible). Confirm visually: the route follows real corridors/doorways, doesn't cut through furniture/walls, and looks at least as clean as the pre-existing grid-A* output. This is a judgment call a human (or an agent with browser tooling, e.g. via Playwright) should make before considering sub-project A shippable — record the observation in this plan file's Task 9 as a completed checkbox note, not as a new automated test.

- [ ] **Step 7: Commit**

N/A — no git repository for this project. Skip.
