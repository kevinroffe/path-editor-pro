"""
autopath.py
-----------
A* pathfinding through free space on a DXF floor plan, between a start and
end point or, via find_multi_path, through an ordered chain of required
reference points.

/api/autopath expects:
  { "start": [x, y], "end": [x, y], "walls": [...polylines...] }
  or, for required points in between:
  { "points": [[x, y], ...], "walls": [...polylines...] }

Returns:
  { "waypoints": [[x, y], ...] }   — full route, all in canvas coords
"""

from __future__ import annotations
import heapq
from collections import deque
import numpy as np
from scipy.ndimage import distance_transform_edt


# ── grid / A* ─────────────────────────────────────────────────────────────────

def _build_grid(walls: list, bounds: tuple, cols: int, rows: int, clearance: float = 0.0) -> np.ndarray:
    """
    Binary grid: True = wall/obstacle, False = free.

    Rasterizes each wall's axis-aligned bounding box onto the grid instead of
    testing every cell against every wall polygon — the naive approach is
    O(rows*cols*walls*vertices), which is fine for a handful of walls but
    becomes billions of operations on a real architectural DXF (tens of
    thousands of wall segments), effectively hanging the server. This is
    O(walls) with cheap numpy slice assignment per wall, so it scales with
    wall count instead of grid size. The trade-off: a wall's bbox is used
    instead of its exact polygon, which is conservative (may block a couple
    of extra corner cells for walls at an angle) but never lets a path pass
    through a wall.

    `clearance` (in the same world units as `bounds`/`walls`) grows every
    obstacle's bbox by that amount on each side before rasterizing — a cheap
    Minkowski-sum approximation that keeps the resulting path a comfortable
    distance from walls/furniture instead of grazing right along their edge.
    """
    xmin, ymin, xmax, ymax = bounds
    W, H = xmax - xmin, ymax - ymin
    grid = np.zeros((rows, cols), dtype=bool)
    if W <= 0 or H <= 0:
        return grid

    for w in walls:
        if len(w) < 2:
            continue
        arr = np.asarray(w, dtype=float)
        c0 = int((arr[:, 0].min() - clearance - xmin) / W * cols)
        c1 = int((arr[:, 0].max() + clearance - xmin) / W * cols)
        r0 = int((arr[:, 1].min() - clearance - ymin) / H * rows)
        r1 = int((arr[:, 1].max() + clearance - ymin) / H * rows)
        c0, c1 = max(0, c0), min(cols - 1, c1)
        r0, r1 = max(0, r0), min(rows - 1, r1)
        if c0 <= c1 and r0 <= r1:
            grid[r0:r1+1, c0:c1+1] = True
    return grid


def _clear_doors(grid: np.ndarray, doors: list, bounds: tuple, cols: int, rows: int, radius: float = 0.0) -> None:
    """
    Force every real door LOCATION to be passable, in place — clears (sets
    False) a small square of `radius` around each door polyline's centroid,
    regardless of what obstacle geometry is already rasterized there.

    Deliberately centroid-only, ignoring each door polyline's own bbox/shape
    entirely — a door's classification is reliable ground truth ("this
    location is an opening") across every DXF, since it comes from the same
    classify pipeline everywhere, but its DRAWN geometry is not: measured on
    the QQQQ_TEST-0001 file, 294/548 (54%) of door entities have near-zero
    extent (<0.05m in both dimensions) — degenerate point-like markers, not
    real swing-arc/leaf geometry — yet clearing even a small area at each
    one's location still reconnected the building (see `radius` below for
    why size barely matters once you're clearing *something* at the right
    spot). Sizing the clearing from the door's own bbox instead would be
    fitting the fix to this one file's drawing convention, exactly the kind
    of geometry-specific special-casing this function is meant to avoid.

    `radius` should be derived from clearance/grid-cell size (parameters
    *we* control, consistent across every file), not from door geometry: a
    door only needs to punch through the wall's own rasterized band, whose
    thickness is bounded by the clearance already applied to that band, so
    `radius = clearance + a small grid-quantization margin` reconnects the
    building regardless of how any individual file happens to draw doors —
    confirmed empirically: bbox-based clearing (the original version of this
    function) and this centroid-based version reach the same ~99% main-
    connected-component fraction on QQQQ_TEST-0001, and reducing padding to
    zero on the bbox version barely changed the result either — the fix
    was never really about spanning the door's real width.
    """
    xmin, ymin, xmax, ymax = bounds
    W, H = xmax - xmin, ymax - ymin
    if W <= 0 or H <= 0:
        return
    for d in doors:
        if not d:
            continue
        cx = sum(p[0] for p in d) / len(d)
        cy = sum(p[1] for p in d) / len(d)
        c0 = int((cx - radius - xmin) / W * cols)
        c1 = int((cx + radius - xmin) / W * cols)
        r0 = int((cy - radius - ymin) / H * rows)
        r1 = int((cy + radius - ymin) / H * rows)
        c0, c1 = max(0, c0), min(cols - 1, c1)
        r0, r1 = max(0, r0), min(rows - 1, r1)
        if c0 <= c1 and r0 <= r1:
            grid[r0:r1+1, c0:c1+1] = False


def _bridge_gap(grid: np.ndarray, start_cell: tuple, end_cell: tuple, max_drill_cells: float) -> None:
    """
    If start_cell and end_cell fall in different connected free-space
    components, find the CHEAPEST path connecting them — a 0-1 BFS where
    moving through an already-free cell costs 0 and moving through a
    blocked cell costs 1 — and clear (set False) only the specific blocked
    cells that path actually crosses, in place. Already-connected points
    cost 0 and nothing gets cleared. A gap costing more than
    `max_drill_cells` is left alone (returns without clearing anything) —
    that's not a real doorway needing a nudge, it's two genuinely separate
    areas, and drilling a long tunnel through solid material between them
    would produce a nonsensical route rather than fix a real gap.

    This replaces blindly clearing a fixed radius around every door (see
    _clear_doors's history): that approach had to use a radius large enough
    to bridge the WORST-behaved door on a given file, but a small room can
    easily be narrower than that radius, so the same clearing that
    legitimately bridges one stubborn doorway can also erase real nearby
    furniture/walls that have nothing to do with it — confirmed as a real,
    visible bug (a path cutting straight through furniture and interior
    walls near, but not at, an actual door). Targeting only the specific
    gap between the two points THIS call actually needs to connect, with
    the smallest possible footprint, avoids that entirely: nothing gets
    cleared anywhere else in the building.
    """
    rows, cols = grid.shape
    sc, sr = start_cell
    ec, er = end_cell
    INF = float('inf')
    dist = np.full((rows, cols), INF)
    parent = {}
    start_cost = 1.0 if grid[sr, sc] else 0.0
    dist[sr, sc] = start_cost
    dq = deque([(sc, sr)])
    DIRS8 = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))

    while dq:
        c, r = dq.popleft()
        d0 = dist[r, c]
        if (c, r) == (ec, er):
            break
        for dcx, dry in DIRS8:
            nc, nr = c + dcx, r + dry
            if not (0 <= nc < cols and 0 <= nr < rows):
                continue
            step_cost = 1.0 if grid[nr, nc] else 0.0
            nd = d0 + step_cost
            if nd < dist[nr, nc]:
                dist[nr, nc] = nd
                parent[(nc, nr)] = (c, r)
                if step_cost == 0.0:
                    dq.appendleft((nc, nr))
                else:
                    dq.append((nc, nr))

    end_dist = dist[er, ec]
    if end_dist == 0.0 or end_dist == INF or end_dist > max_drill_cells:
        return

    cur = (ec, er)
    while cur in parent:
        c, r = cur
        if grid[r, c]:
            grid[r, c] = False
        cur = parent[cur]


def _rasterize_footprint(polys: list, bounds: tuple, cols: int, rows: int) -> np.ndarray:
    """
    Boolean grid, True where a cell CENTER lies inside at least one polygon
    in `polys` — the real usable floor footprint (classify's FLOOD layer).
    Auto Path must never route outside it, and unlike wall/door/etc.
    obstacles (which only need a conservative bbox — see _build_grid), a
    footprint boundary needs the real polygon shape: bbox-only would only
    support a single axis-aligned rectangular floor.

    Each polygon is filled independently (even-odd scanline rule WITHIN that
    one polygon's own edges) and the results are UNIONED (OR'd) across
    polygons — deliberately NOT a single even-odd fill across all polygons
    combined, which is what would happen if a smaller polygon nested inside
    a larger one were treated as a hole cut into it (the usual "donut" CAD/
    SVG convention for nested rings). A nested FLOOD polygon instead marks a
    sub-area/section of the larger planning area it sits inside — e.g. one
    room's footprint nested inside the whole floor's footprint — so both the
    outer and inner polygon's area must be routable, not just the space
    between them. Per-polygon fill + union is what makes that true: the
    inner polygon's area is simply covered twice (once by each), which is
    inert, not a hole.
    """
    xmin, ymin, xmax, ymax = bounds
    W, H = xmax - xmin, ymax - ymin
    inside = np.zeros((rows, cols), dtype=bool)
    if not polys or W <= 0 or H <= 0:
        return inside

    for poly in polys:
        n = len(poly)
        if n < 3:
            continue
        for r in range(rows):
            y = ymin + (r + 0.5) / rows * H
            xs = []
            for i in range(n):
                x1, y1 = poly[i]
                x2, y2 = poly[(i + 1) % n]
                if (y1 > y) != (y2 > y):
                    xs.append(x1 + (y - y1) / (y2 - y1) * (x2 - x1))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                c0 = int((xs[i] - xmin) / W * cols)
                c1 = int((xs[i + 1] - xmin) / W * cols)
                c0, c1 = max(0, c0), min(cols - 1, c1)
                if c0 <= c1:
                    inside[r, c0:c1 + 1] = True
    return inside


def _grid_dims(W: float, H: float, target_cells: int = 120 * 120,
               min_dim: int = 20, max_dim: int = 400) -> tuple:
    """
    Choose (cols, rows) so grid cells are roughly SQUARE, keeping the total
    cell count near `target_cells` (same overall budget as the old fixed
    120x120). A fixed 120x120 grid over a wide/short floor plan (e.g. 57m x
    15m) produces cells like 0.5m x 0.15m — badly non-square, which distorts
    A*'s diagonal-move cost (1.414x assumes a square cell) and biases paths.
    """
    if W <= 0 or H <= 0:
        return 120, 120
    cell = (W * H / target_cells) ** 0.5
    cols = max(min_dim, min(max_dim, int(round(W / cell))))
    rows = max(min_dim, min(max_dim, int(round(H / cell))))
    return cols, rows


def _world_to_cell(x, y, bounds, cols, rows):
    xmin, ymin, xmax, ymax = bounds
    c = int((x - xmin) / (xmax - xmin) * cols)
    r = int((y - ymin) / (ymax - ymin) * rows)
    return max(0, min(cols - 1, c)), max(0, min(rows - 1, r))


def _cell_to_world(c, r, bounds, cols, rows):
    xmin, ymin, xmax, ymax = bounds
    x = xmin + (c + 0.5) / cols * (xmax - xmin)
    y = ymin + (r + 0.5) / rows * (ymax - ymin)
    return x, y


def _nearest_free(c, r, grid):
    """Find the nearest free cell to (c, r) using BFS."""
    cols, rows = grid.shape[1], grid.shape[0]
    if not grid[r, c]:
        return c, r
    from collections import deque
    visited = {(c, r)}
    q = deque([(c, r)])
    while q:
        cc, rr = q.popleft()
        for dc, dr in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
            nc, nr = cc + dc, rr + dr
            if 0 <= nc < cols and 0 <= nr < rows and (nc, nr) not in visited:
                visited.add((nc, nr))
                if not grid[nr, nc]:
                    return nc, nr
                q.append((nc, nr))
    return c, r


def _astar(grid, start_cell, end_cell, turn_penalty: float = 0.0,
           dist_grid=None, corridor_weight: float = 0.0, corridor_cells: float = 0.0):
    """
    A* on binary grid. Returns list of (col, row) from start to end, or None.

    `turn_penalty` adds extra cost whenever the direction into a cell differs
    from the direction used to reach its predecessor, biasing the search
    toward straighter routes instead of the purely-shortest one (which can
    zigzag between grid-diagonal steps for no real benefit). This tracks only
    one incoming direction per cell rather than expanding the search state to
    (cell, direction) — an approximation that's cheap and works well in
    practice, though it isn't guaranteed globally turn-optimal.

    `dist_grid`/`corridor_weight`/`corridor_cells` bias the search away from
    cells close to an obstacle even when they're technically passable — pure
    shortest-path-with-clearance is happy to cut diagonally through a gap
    between two furniture rows the moment it's wide enough to fit, which
    doesn't read as a route a person would actually walk. `dist_grid[r,c]` is
    each free cell's distance (in cells) to the nearest obstacle (see
    find_path); cells closer than `corridor_cells` get extra cost scaled by
    `corridor_weight`, tapering to zero once a cell is that far from anything
    — effectively pulling the path toward the middle of open corridors.
    """
    rows, cols = grid.shape
    sc, sr = start_cell
    ec, er = end_cell

    def h(c, r):
        return ((c - ec) ** 2 + (r - er) ** 2) ** 0.5

    def corridor_cost(nc, nr):
        if dist_grid is None or corridor_weight <= 0:
            return 0.0
        d = dist_grid[nr, nc]
        return corridor_weight * max(0.0, corridor_cells - d)

    DIRS = [(-1,0,1.0),(1,0,1.0),(0,-1,1.0),(0,1,1.0),
            (-1,-1,1.414),(-1,1,1.414),(1,-1,1.414),(1,1,1.414)]

    g = {(sc, sr): 0.0}
    parent = {(sc, sr): None}
    heap = [(h(sc, sr), sc, sr)]
    closed = set()

    while heap:
        _, c, r = heapq.heappop(heap)
        if (c, r) in closed:
            continue
        closed.add((c, r))
        if c == ec and r == er:
            path, cur = [], (c, r)
            while cur:
                path.append(cur)
                cur = parent[cur]
            return path[::-1]

        p = parent.get((c, r))
        in_dir = (c - p[0], r - p[1]) if p is not None else None

        for dc, dr, cost in DIRS:
            nc, nr = c + dc, r + dr
            if not (0 <= nc < cols and 0 <= nr < rows):
                continue
            if grid[nr, nc] or (nc, nr) in closed:
                continue
            step_cost = cost
            if turn_penalty > 0 and in_dir is not None and (dc, dr) != in_dir:
                step_cost += turn_penalty
            step_cost += corridor_cost(nc, nr)
            ng = g[(c, r)] + step_cost
            if ng < g.get((nc, nr), float("inf")):
                g[(nc, nr)] = ng
                parent[(nc, nr)] = (c, r)
                heapq.heappush(heap, (ng + h(nc, nr), nc, nr))
    return None


# ── path simplification ───────────────────────────────────────────────────────

def _los_clear(p1, p2, grid: np.ndarray, bounds: tuple, cols: int, rows: int,
               dist_grid=None, min_dist: float = 0.0, max_narrow_cells: float = 0.0) -> bool:
    """
    True if the straight line p1→p2 doesn't cross an occupied grid cell.
    Uses the same occupancy grid as pathfinding (not the raw wall polygons) —
    O(1) per sample instead of O(walls), which is what made simplification the
    real remaining bottleneck on a floor plan with tens of thousands of walls
    even after _build_grid itself was made fast.

    The `dist_grid`/`min_dist` check matters for the same reason A* has a
    corridor bias (see _astar): without it, simplification is happy to
    straight-line-collapse a nicely corridor-following A* route the moment
    the direct line is merely collision-free, even if it cuts close between
    two furniture rows — undoing the corridor bias entirely, since
    simplification runs after pathfinding and only re-checks raw collision.

    That check is tolerant of a *brief* narrow stretch (tracked as the
    longest CONSECUTIVE run of samples under `min_dist`, capped at
    `max_narrow_cells`) rather than rejecting on any single close sample —
    a real doorway is legitimately narrower than a comfortable corridor, and
    a line that passes briefly through one is a normal route, not the
    "cutting through a cluttered area for its whole length" case this is
    meant to catch.

    Sample count scales with the segment's length in grid cells (at least 2
    samples per cell) rather than a fixed count — a fixed sample count on a
    long line (e.g. across a large real floor plan) can space samples several
    cell-widths apart, letting a thin obstacle (a single wall, a chair) slip
    between two samples undetected and falsely report a clear line.
    """
    xmin, ymin, xmax, ymax = bounds
    cell_w = (xmax - xmin) / cols
    cell_h = (ymax - ymin) / rows
    dist_cells = max(abs(p2[0] - p1[0]) / max(cell_w, 1e-9),
                      abs(p2[1] - p1[1]) / max(cell_h, 1e-9))
    samples = max(15, int(dist_cells * 2) + 1)
    max_narrow_samples = max_narrow_cells * 2  # ~2 samples per cell, matching `samples` above

    consecutive_narrow = 0
    for i in range(1, samples):
        t = i / samples
        x = p1[0] + t * (p2[0] - p1[0])
        y = p1[1] + t * (p2[1] - p1[1])
        c, r = _world_to_cell(x, y, bounds, cols, rows)
        if grid[r, c]:
            return False
        if dist_grid is not None and min_dist > 0:
            if dist_grid[r, c] < min_dist:
                consecutive_narrow += 1
                if consecutive_narrow > max_narrow_samples:
                    return False
            else:
                consecutive_narrow = 0
    return True


def _point_seg_dist(p, a, b) -> float:
    """Perpendicular distance from point p to the (infinite) line through
    a-b (falls back to distance to a if a==b)."""
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 < 1e-12:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    # |cross product of (b-a) and (a-p)| / |b-a| = perpendicular distance
    return abs(dx * (ay - py) - (ax - px) * dy) / (seg_len2 ** 0.5)


def _reduce_to_max_pts(pts: list, grid, bounds, cols, rows, max_pts: int,
                        dist_grid, min_dist: float, max_narrow_cells: float) -> list:
    """
    Reduce `pts` toward `max_pts` by repeatedly dropping the single least-
    significant interior point — the one whose removal (a) keeps its two
    neighbors mutually LOS-clear (see _los_clear) and (b) deviates least
    from the resulting straight line (a Visvalingam-Whyatt-style measure) —
    one point at a time, until either max_pts is reached or no further
    point can be safely dropped.

    Greedy one-at-a-time removal succeeds far more often than trying to
    jump straight to max_pts by evenly re-sampling the whole path in one
    shot (the previous approach here): collapsing one redundant point at a
    time is a much weaker, easier-to-satisfy safety condition than
    collapsing dozens simultaneously, which on a real multi-room route
    almost always failed outright and silently fell back to the full,
    un-reduced point list (seen in practice: 60-128 waypoints on a complex
    real route, when the user needs a small, hand-editable set afterward).
    """
    pts = list(pts)
    while len(pts) > max_pts:
        best_i, best_cost = None, None
        for i in range(1, len(pts) - 1):
            if not _los_clear(pts[i - 1], pts[i + 1], grid, bounds, cols, rows,
                               dist_grid=dist_grid, min_dist=min_dist,
                               max_narrow_cells=max_narrow_cells):
                continue
            cost = _point_seg_dist(pts[i], pts[i - 1], pts[i + 1])
            if best_cost is None or cost < best_cost:
                best_cost, best_i = cost, i
        if best_i is None:
            break  # no remaining point can be safely dropped
        del pts[best_i]
    return pts


def _simplify(path: list, grid: np.ndarray, bounds: tuple, cols: int, rows: int,
              max_pts: int = 12, dist_grid=None, corridor_cells: float = 0.0,
              max_narrow_cells: float = 0.0) -> list:
    """
    Greedy line-of-sight simplification: skip any point that can be seen
    directly from the previous kept point. Then reduce toward max_pts one
    point at a time (see _reduce_to_max_pts) rather than in one all-or-
    nothing jump.

    `dist_grid`/`corridor_cells` make "visible" also require staying at least
    `corridor_cells` from any obstacle (not just not overlapping one) — see
    _los_clear — so simplification doesn't discard the corridor-following
    shape A* found in favor of a shorter line that merely avoids collision.
    Uses a reduced threshold (half of A*'s preference) since simplification's
    job is "don't reintroduce a bad cut", not re-run the same soft preference
    A* already optimized for. `max_narrow_cells` (see _los_clear) keeps this
    from fragmenting every real doorway into extra points — those are
    legitimately narrower than a comfortable corridor.
    """
    if len(path) <= 2:
        return path

    min_dist = corridor_cells * 0.5

    kept = [path[0]]
    i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1 and not _los_clear(path[i], path[j], grid, bounds, cols, rows,
                                            dist_grid=dist_grid, min_dist=min_dist,
                                            max_narrow_cells=max_narrow_cells):
            j -= 1
        kept.append(path[j])
        i = j

    if len(kept) > max_pts:
        # The corridor-distance requirement above is what keeps a route
        # centered in a corridor rather than clipping obstacle corners —
        # a niceness preference, not a safety requirement (real collision
        # avoidance is grid[r,c] alone). On a route already fully reduced
        # under that stricter standard, every remaining point is typically
        # load-bearing FOR IT — removing any one reproduces the exact
        # corridor violation that kept it, so the reduction finds nothing
        # safe to drop and max_pts is never reached. Relaxing to pure
        # collision-safety (min_dist=0) for this squeeze trades a bit of
        # "stays centered in the corridor" for the user's actual goal here
        # (a small, hand-editable waypoint count) — still never crosses a
        # wall/obstacle, and the downstream spline smoothing already softens
        # a slightly more direct polyline visually regardless.
        kept = _reduce_to_max_pts(kept, grid, bounds, cols, rows, max_pts,
                                   dist_grid, 0.0, max_narrow_cells)

    return kept


# ── public entry point ────────────────────────────────────────────────────────

def find_path(
    start: list, end: list, walls: list,
    clearance_m: float = 0.2,
    units_to_metres: float = 1.0,
    turn_penalty: float = 4.0,
    corridor_m: float = 1.0,
    corridor_weight: float = 0.5,
    max_narrow_m: float = 1.5,
    footprint: list | None = None,
    doors: list | None = None,
    door_clear_margin_m: float = 0.15,
    max_bridge_m: float = 3.5,
) -> list[list[float]]:
    """
    Find a wall-avoiding path from start to end using A* on a floor-plan grid.
    Returns [[x,y], ...] in canvas (DXF) coordinates.

    clearance_m     — how far (metres) the path should stay from every
                       obstacle; converted to raw canvas units via
                       units_to_metres. Applied on BOTH sides of a gap, so
                       e.g. 0.4m would reduce an 0.8m doorway to 0m passable
                       width — kept modest by default, and backed off
                       automatically (see below) if it blocks the only route
                       entirely, rather than silently ignoring obstacles.
    turn_penalty    — extra A* cost per direction change, biasing toward
                       straighter, more natural/cinematic routes over the
                       purely shortest one. 0 disables it.
    corridor_m/_weight — bias AWAY from cells within corridor_m of any
                       obstacle (beyond the hard clearance_m buffer), so the
                       path prefers the middle of a wide-open aisle over
                       cutting diagonally through a gap between furniture
                       rows the moment it's technically wide enough — pure
                       shortest-path-with-clearance is happy to take that cut,
                       which doesn't read as a route a person would walk.
                       0 disables it (falls back to plain shortest path).
    max_narrow_m    — how long a stretch under the corridor threshold
                       simplification will still tolerate as "one real
                       doorway", rather than treating it as evidence the line
                       cuts through clutter and needs to be split up.
    footprint       — the classify project's FLOOD-layer polygon(s) marking
                       the real usable floor area (from geo.spaces), in the
                       same coordinate space as `walls`. When given, any grid
                       cell outside all of them is blocked regardless of
                       obstacle geometry — without this, a real gap in the
                       source DXF's exterior wall coverage (e.g. an export
                       that only captured interior partitions, not the full
                       core-and-shell envelope) can let a path leak outside
                       the building through a real door and shortcut around
                       the exterior, especially with a high turn_penalty
                       making a low-turn exterior loop look cheap. None/empty
                       disables the check (old files without a FLOOD layer
                       behave exactly as before). Multiple polygons — including
                       one nested inside another, e.g. a room's FLOOD nested
                       inside the whole floor's FLOOD — are unioned: every
                       polygon's area is routable, a nested one is never
                       treated as a hole cut out of its parent (see
                       _rasterize_footprint).
    doors           — door polylines (geo.doors, same coordinate space as
                       `walls`). Not obstacles themselves (see above), but
                       used to FORCE each door's location passable — see
                       _clear_doors for why this matters: on a real DXF, a
                       door symbol often doesn't correspond to an actual gap
                       in the wall geometry, so without this a large part of
                       a real building can end up genuinely disconnected in
                       the grid (not just costly to reach — no route exists
                       at all, at any clearance). None/empty disables it.
    door_clear_margin_m — extra distance (metres), beyond whatever
                       `clearance_m` level is active for that attempt,
                       cleared around each door's centroid. Deliberately
                       kept small (a grid-quantization safety margin, not an
                       attempt to bridge a badly-off-center door) — a value
                       big enough to always bridge the worst-behaved door on
                       some file would, on a file with rooms smaller than
                       that radius, also erase real nearby furniture/walls
                       that have nothing to do with the door (confirmed as
                       a real, visible bug: a path cutting straight through
                       furniture and interior walls near, but not at, an
                       actual door). `max_bridge_m` below handles the
                       stubborn-door case instead, without that side effect.
    max_bridge_m    — if start/end still land in different connected
                       regions of the grid after clearance/door-clearing
                       (see _bridge_gap), the farthest (in metres) Auto Path
                       will drill a targeted, minimal connection through
                       whatever's actually in the way — exactly at the gap
                       this specific route needs, nowhere else. A gap wider
                       than this is treated as two genuinely separate areas
                       rather than a doorway needing a nudge, and pathing
                       fails normally (see the no-route-found handling
                       below) instead of drilling an unrealistic tunnel.
    """
    # Bounds from walls + footprint + a small margin. Footprint must count
    # here too — if a file has a FLOOD boundary but (unusually) no wall
    # obstacles, bailing out to a raw straight line on `not walls` alone
    # would silently skip the hard footprint boundary entirely.
    all_pts = [pt for w in walls for pt in w] + [pt for poly in (footprint or []) for pt in poly]
    if not all_pts:
        return [start, end]
    arr = np.array(all_pts, dtype=float)
    margin = max(float(arr[:, 0].max() - arr[:, 0].min()), float(arr[:, 1].max() - arr[:, 1].min())) * 0.02
    bounds = (
        float(arr[:, 0].min()) - margin, float(arr[:, 1].min()) - margin,
        float(arr[:, 0].max()) + margin, float(arr[:, 1].max()) + margin,
    )

    COLS, ROWS = _grid_dims(bounds[2] - bounds[0], bounds[3] - bounds[1])
    cell_m = ((bounds[2]-bounds[0]) * units_to_metres / COLS +
              (bounds[3]-bounds[1]) * units_to_metres / ROWS) / 2
    corridor_cells = corridor_m / max(cell_m, 1e-9)
    max_narrow_cells = max_narrow_m / max(cell_m, 1e-9)

    outside_footprint = None
    if footprint:
        inside = _rasterize_footprint(footprint, bounds, COLS, ROWS)
        if inside.any():
            outside_footprint = ~inside

    orig_sc, orig_sr = _world_to_cell(start[0], start[1], bounds, COLS, ROWS)
    orig_ec, orig_er = _world_to_cell(end[0],   end[1],   bounds, COLS, ROWS)

    # Try the requested clearance first, then back off progressively — a
    # doorway or tight gap can make full clearance genuinely impassable, and
    # falling straight back to a raw line (no obstacle-avoidance at all) would
    # be worse than routing through with a smaller (but still real) buffer.
    door_clear_margin = door_clear_margin_m / max(units_to_metres, 1e-9)

    max_bridge_cells = max_bridge_m / max(cell_m, 1e-9)

    raw = None
    for clr_m in (clearance_m, clearance_m * 0.5, clearance_m * 0.2, 0.0):
        clearance = clr_m / max(units_to_metres, 1e-9)
        grid = _build_grid(walls, bounds, COLS, ROWS, clearance=clearance)
        if outside_footprint is not None:
            grid = grid | outside_footprint
        if doors:
            # A door only needs to punch through the wall band's own
            # clearance-driven thickness — see _clear_doors — so the radius
            # tracks whatever clearance is active THIS attempt, not a fixed
            # constant divorced from it. Kept small/safe on purpose (see
            # door_clear_margin_m's docstring) — _bridge_gap below handles
            # any door whose centroid is too far from the real gap for this
            # to reach, without needing a radius big enough to also erase
            # real nearby furniture/walls.
            _clear_doors(grid, doors, bounds, COLS, ROWS, radius=clearance + door_clear_margin)
        sc, sr = _nearest_free(orig_sc, orig_sr, grid)
        ec, er = _nearest_free(orig_ec, orig_er, grid)
        # If start/end still land in different connected components after
        # the above, drill the smallest possible bridge between exactly
        # those two components rather than widening door-clearing further —
        # see _bridge_gap. A no-op if they're already connected.
        _bridge_gap(grid, (sc, sr), (ec, er), max_bridge_cells)
        dist_grid = distance_transform_edt(~grid) if corridor_weight > 0 else None
        raw = _astar(grid, (sc, sr), (ec, er), turn_penalty=turn_penalty,
                      dist_grid=dist_grid, corridor_weight=corridor_weight, corridor_cells=corridor_cells)
        if raw:
            break
    if not raw:
        # No route exists even with zero clearance — the start or end point is
        # in a pocket of free space fully disconnected from the other (e.g. a
        # doorway sealed shut by clearance-inflated furniture in the grid).
        # Returning a straight line here would silently draw a "path" straight
        # through walls/furniture with no indication anything went wrong, so
        # the caller must treat an empty list as "no path found."
        return []

    # Convert grid path to world coordinates
    world_path = [list(_cell_to_world(c, r, bounds, COLS, ROWS)) for c, r in raw]

    # Use the exact clicked point when it's actually routable. If it isn't —
    # outside the FLOOD footprint, or sitting on a wall — fall back to the
    # snapped cell's world coordinate instead of the literal click, otherwise
    # the returned path would still have an endpoint outside the boundary
    # Auto Path was just told is off-limits, even though every point in
    # between correctly respects it.
    world_path[0]  = list(start) if not grid[orig_sr, orig_sc] else list(_cell_to_world(sc, sr, bounds, COLS, ROWS))
    world_path[-1] = list(end)   if not grid[orig_er, orig_ec] else list(_cell_to_world(ec, er, bounds, COLS, ROWS))

    return _simplify(world_path, grid, bounds, COLS, ROWS,
                      dist_grid=dist_grid, corridor_cells=corridor_cells,
                      max_narrow_cells=max_narrow_cells)


def find_multi_path(points: list, walls: list, **kwargs) -> list[list[float]]:
    """
    Route through an ORDERED sequence of required reference points — a start
    point, one or more must-pass-through points in between, and an end point
    — by chaining find_path across each consecutive pair and concatenating
    the segments.

    Each segment's shared boundary point is dropped rather than duplicated:
    every call uses the same `walls`/`footprint`/`**kwargs`, so bounds (and
    therefore grid resolution and nearest-free snapping) are identical
    across segments, meaning one segment's last point and the next
    segment's first point always land on the exact same coordinate.

    A failure on any one leg (find_path returning no path — see its
    docstring) fails the whole route rather than silently skipping a
    required reference point, which would be worse than no route at all.
    """
    if len(points) < 2:
        return []
    combined = find_path(points[0], points[1], walls, **kwargs)
    if not combined:
        return []
    for i in range(1, len(points) - 1):
        leg = find_path(points[i], points[i + 1], walls, **kwargs)
        if not leg:
            return []
        combined.extend(leg[1:])
    return combined
