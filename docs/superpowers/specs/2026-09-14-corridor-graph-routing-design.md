# Corridor-Graph Routing Engine — Design Spec

Date: 2026-09-14
Project: revit-walkthrough-v2 (`C:\Users\kevin\revit-walkthrough-v2`)
Status: Approved by user, ready for implementation planning

## Background

Smart Path currently routes with grid A* (`backend/autopath.py`): obstacles are
rasterized onto an occupancy grid, and a distance-transform bias
(`corridor_m`/`corridor_weight`) plus a turn penalty pull the route toward the
center of open aisles. This works but required a long series of hand tuning
passes this project (corridor bias tuning, door-clearing radius tuning, a
targeted bridging BFS, waypoint-count reduction) — each fix was real and
verified, but the underlying mechanism has no actual concept of "this is a
corridor" or "this is a room" — it infers corridor-following behavior
indirectly from a distance field.

An old internal qbiq tool (`C:\Users\kevin\Desktop\video path tool ortal`,
specifically `circulation.py` and `spatial_graph.py`) built an actual
corridor-centerline graph via a Voronoi skeleton of the walkable area, then
routed on that graph directly. That tool depended on qbiq's own backend and a
trained ML model for other stages, but the graph-construction and graph
-routing techniques are plain geometry/graph algorithms with no ML
dependency, and are adoptable here.

This spec covers **sub-project A** of a three-part effort (A: corridor-graph
routing engine — this doc; B: yaw heuristics; C: must-see-room biasing). B and
C get their own design passes after A ships.

## Goals

- Replace hand-tuned grid-A* corridor bias with a real corridor-centerline
  graph, removing the need for `corridor_m`/`corridor_weight` tuning.
- Keep door-opening handling and via-point ordering guarantees at least as
  robust as today (0/40 and 0/20 on the existing stress tests).
- Preserve today's 5-ordered-via-point Smart Path UX unchanged — this is a
  backend routing-engine swap, not a UX change.
- Never regress: grid A* remains as an automatic fallback.

## Non-goals

- No ML models, no dependency on qbiq's backend/BAM data.
- No change to the frontend click flow, the `/api/autopath` request shape, or
  the FLOOD-boundary/classification-driven design principles already
  established ([[feedback_classification_driven_routing]]).
- No change to camera yaw logic or must-see-room biasing (sub-projects B/C).

## Architecture / end-to-end flow

1. On upload (`/api/upload`, `/api/upload-3d`, `/api/demo`), obstacles,
   doors, and footprint are classified and cached exactly as today
   (`_LAST_OBSTACLES`, `_LAST_DOORS`, `_LAST_FOOTPRINT`, `_LAST_UNITS_TO_METRES`).
   No new work happens at upload time.
2. On the first `/api/autopath` call after an upload, a new module
   (`corridor_graph.py`) lazily builds a **walkable-area polygon** and a
   **corridor skeleton graph** from the cached obstacles/doors/footprint plus
   the request's `clearance_m`. The result is cached in `app.py` as
   `_LAST_CIRC_GRAPH`, keyed by `(upload_generation, round(clearance_m, 3))`.
   A new upload invalidates the cache (bump `upload_generation`).
3. `/api/autopath` tries routing via the corridor graph first
   (`corridor_graph.route_multi(points, graph, ...)`). If that call raises,
   returns `None`, or returns a leg with no path, **the entire request falls
   back to today's `find_multi_path` (grid A*)** — never a per-leg mix, so a
   single route never blends two different routing "styles."
4. Whichever path succeeds returns the same `waypoints` shape the frontend
   already expects; no frontend change.

## Walkable-area polygon construction

New dependency: `shapely` (add to `requirements.txt`).

Given the cached obstacle/door/footprint polygons (already in the same
Y-flipped SVG-display coordinate space used throughout `autopath.py`):

1. Build the **wall polygon**: union of all wall polygons, buffered outward by
   `clearance_m` (`shapely.ops.unary_union`, `buffer`).
2. For each door: subtract a small rectangle centered on the door's centroid
   (half-width/height = `clearance_m + door_clear_margin_m`, same constants
   and same reasoning as today's `_clear_doors` — sized from parameters we
   control, never the door's drawn geometry) from the wall polygon. This is
   the vector equivalent of today's door-centroid clearing.
3. Build the **other-obstacles polygon**: union of columns, furniture, and
   windows, each buffered by `clearance_m`. Doors do *not* carve into this
   layer — a door only opens a wall, not furniture sitting near it.
4. Full obstacle polygon = wall polygon (post-door-carving) ∪ other-obstacles
   polygon.
5. Walkable-area polygon = FLOOD polygon (unioned, if one or more FLOOD
   polygons exist) minus full obstacle polygon; if there is no FLOOD layer,
   use the plan's bounding envelope (from `_LAST_UNITS_TO_METRES`-scaled
   bounds, matching today's "no footprint = no constraint" behavior) minus
   full obstacle polygon instead.
6. If this polygon is empty or invalid (degenerate geometry, zero area),
   graph construction fails cleanly and the caller falls back to grid A*.

The result may be a `MultiPolygon` (disconnected regions) — this is expected
and handled at the graph level (#7 below), not treated as an error here.

## Skeleton graph construction (`corridor_graph.py`)

1. Densify the walkable polygon's boundary (interior + exterior rings of every
   sub-polygon) to a fixed spacing (a few times finer than the corridor width
   we care about, e.g. 0.3–0.5m) so the Voronoi skeleton has enough
   resolution to follow real corridor bends.
2. Run `scipy.spatial.Voronoi` on the densified boundary points. Keep only
   ridge vertices/edges whose midpoint falls strictly inside the walkable
   polygon (`shapely.contains`) — this is the medial-axis approximation.
3. Load surviving ridges into a `networkx.Graph` (nodes = Voronoi vertices,
   edges weighted by Euclidean length).
4. Clean up the raw skeleton (ported from `circulation.py`'s pipeline):
   straighten corners, straighten T-junctions, remove short stub segments,
   adjust short middle segments, RDP-simplify each branch. This turns the
   noisy raw Voronoi skeleton into a clean corridor-centerline graph.
5. **Door bridging for residual disconnection:** for each door whose two
   sides still land in different connected components of the cleaned graph
   (checked via `networkx.connected_components`), find the nearest graph node
   to the door centroid on each side and add a direct edge between them,
   weighted by their real distance, but only if that distance is ≤
   `max_bridge_m` (3.5m default, same constant/intent as today's
   `_bridge_gap` — bridge only a real, specific, minimal gap).
6. If, after door bridging, the graph is still split into components that a
   requested route needs to cross, that specific routing call fails (falls
   back to grid A*, whose own `_bridge_gap` is more permissive) rather than
   forcing an unbounded bridge.

## Via-point routing on the graph

For an ordered list of via-points (today: 5 — start, 3 required via points,
end):

1. Snap each point to the nearest position on the nearest graph *edge*
   (project onto the closest edge segment; insert a temporary node splitting
   that edge at the projection point, rather than snapping to an existing
   junction — preserves routing precision).
2. For each consecutive pair (in click order — this ordering guarantee is
   unchanged from today), run `networkx.shortest_path` (Dijkstra, edge-length
   weighted) between their snapped nodes.
3. Concatenate the per-leg node sequences (dropping the duplicate shared
   boundary point between legs, same as today's `find_multi_path`), convert
   node coordinates back to world/display space.
4. Feed the resulting polyline through the existing waypoint-reduction pass
   (`_reduce_to_max_pts`/`_point_seg_dist`, unchanged) so point counts stay
   within the same comfortable-to-edit ceiling as today.
5. If any leg's shortest-path call raises `networkx.NetworkXNoPath`, the whole
   multi-point route falls back to grid A* (see Architecture step 3).

## Caching & performance

- `_LAST_CIRC_GRAPH` cache dict in `app.py`, parallel to the existing
  `_LAST_OBSTACLES`/`_LAST_FOOTPRINT`/`_LAST_DOORS`, keyed by
  `(upload_generation, round(clearance_m, 3))`.
- An `_UPLOAD_GENERATION` counter bumped on every `/api/upload`,
  `/api/upload-3d`, `/api/demo` call; the graph cache is cleared (or just
  never matches) once the generation changes.
- Graph build happens lazily on the first `/api/autopath` call per
  (generation, clearance_m) combination, not at upload time — keeps upload
  latency unaffected even for the real 17k-furniture-piece file.
- Must be empirically verified fast enough (low single-digit seconds) on both
  real test files during implementation; if `shapely`'s `unary_union` over
  ~17k furniture polygons is too slow, buffer/union in batches or fall back to
  bbox-simplified obstacle shapes for the union step only (skeleton precision
  doesn't need furniture's exact silhouette, just its footprint).

## Error handling

Every stage that can fail (empty/invalid walkable polygon, Voronoi
degenerate-input error, disconnected graph after bridging, no path between
snapped via-points) is caught at the `/api/autopath` level and triggers the
same fallback: run today's `find_multi_path` (grid A*) for the entire
request. No partial/mixed-style routes, no user-visible error from a graph
-construction hiccup — Smart Path just quietly uses the older, already-proven
mechanism for that request.

## Testing / verification plan

- Re-run the existing 40-triple (`QQQQ_TEST-0001`) and 20-triple (real
  classify-exported file) random-via-point stress tests against the new
  graph path; failure rate must stay at 0, waypoint counts comparable or
  lower than today's post-reduction numbers.
- Synthetic regression test reproducing the earlier door-clearing bug (4m
  room, off-center door entity, flanking furniture) — confirm vector
  door-notching doesn't erase the furniture and does open the real gap.
- Visual comparison (Playwright screenshots) of several real routes, old
  grid-A* vs. new graph output, to catch "succeeds but looks different/wrong"
  regressions that pure point-count/failure-rate metrics would miss.
- Explicit fallback test: force the graph path to fail (e.g. monkeypatch an
  empty walkable polygon) and confirm `/api/autopath` still returns a valid
  route via grid A*, with no user-visible error.
- Performance measurement on both real files (upload-to-first-click and
  cached-subsequent-click timings).

## Rollout notes

- `revit-walkthrough-v2` has no git repository (user declined to initialize
  one on 2026-09-02) — this spec is not committed to version control; it
  lives at this file path as the durable record instead.
- Sub-projects B (yaw heuristics: `fix_drywall_lookat`, `fix_moon_walk`) and C
  (must-see-room biasing) are deliberately out of scope here and will each
  get their own brainstorming pass once A is implemented and verified.
