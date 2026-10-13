"""
qbiq_extractor.py
------------------
Parses a matched qbiq Spaceplanner JSON+SVG export pair into the project's
shared LevelGeometry dataclass (see revit_extractor.py), so every existing
downstream feature (Smart Path's corridor-graph routing, the 3D preview,
Enscape/Revit XML export) works on qbiq-sourced floor plans with zero
changes to any of those systems — they all operate purely on LevelGeometry
fields, never on how those fields were populated.

See docs/superpowers/specs/2026-10-13-qbiq-json-svg-import-design.md for the
full design rationale (why dashed-stroke rooms aren't walls, why only one
polyline per door_id is the real opening line, why the JSON's non-_ls keys
are ignored, etc.).

extract_qbiq_design parses the other qbiq export shape: a single "design"
JSON whose geometry is WKT in centimetres (top-level `rooms` + `nfp_data`).
"""

from __future__ import annotations
import json
import logging
import math
import re
import xml.etree.ElementTree as ET
from collections import namedtuple

from shapely import wkt
from shapely.errors import ShapelyError
from shapely.geometry import LineString, MultiPoint, Point as GeomPoint
from shapely.ops import unary_union

from revit_extractor import LevelGeometry

log = logging.getLogger(__name__)

Point = tuple
Polyline = list


def _key(p: tuple, precision: int = 6) -> tuple:
    """Round a point to a stable dict key — real exports repeat the exact
    same literal float for a shared vertex between two adjacent segments
    (verified against the real reference JSON), so this is a safety margin
    against trivial float-representation differences, not fuzzy matching."""
    return (round(p[0], precision), round(p[1], precision))


def _stitch_segments(segments: list) -> list:
    """
    Chain 2-point segments into connected polylines by shared endpoints.

    Each JSON `_ls` key is a flat, unordered list of edges — not already
    walked into a single connected sequence, and frequently containing
    MULTIPLE disconnected loops in one key (e.g. columns_ls has one closed
    loop per column; core_ls has one loop per core shaft plus the overall
    core-zone boundary). This walks outward from each not-yet-used segment
    in both directions until no more segments attach, producing one chain
    per disconnected component. A chain that returns to its own starting
    point is naturally closed (first point == last point) — this matches
    the project's existing closed-polyline convention (see
    dxf_extractor.py's _entity_to_polylines) with no extra step needed. A
    chain with no match at one or both ends (e.g. an isolated mullion bar)
    is returned as an open polyline, which is an equally valid polyline
    everywhere else in this codebase.
    """
    remaining = list(segments)
    chains = []
    while remaining:
        a, b = remaining.pop(0)
        chain = [a, b]

        extended = True
        while extended:
            extended = False
            tail = _key(chain[-1])
            for i, (p, q) in enumerate(remaining):
                if _key(p) == tail:
                    chain.append(q)
                    remaining.pop(i)
                    extended = True
                    break
                if _key(q) == tail:
                    chain.append(p)
                    remaining.pop(i)
                    extended = True
                    break

        extended = True
        while extended:
            extended = False
            head = _key(chain[0])
            for i, (p, q) in enumerate(remaining):
                if _key(p) == head:
                    chain.insert(0, q)
                    remaining.pop(i)
                    extended = True
                    break
                if _key(q) == head:
                    chain.insert(0, p)
                    remaining.pop(i)
                    extended = True
                    break

        chains.append(chain)
    return chains


_COMMAND_LETTER_RE = re.compile(r"[A-Za-z]")
_SUPPORTED_PATH_COMMANDS = set("MLZz")
_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _parse_coord_pairs(s: str) -> list[tuple[float, float]]:
    """Parse an SVG coordinate list ("1,2 3,4", "1 2 3 4", "1e2,-1.5E-3")
    into (x, y) pairs. Raises ValueError on stray characters or an odd
    number count."""
    if _NUMBER_RE.sub(" ", s).replace(",", " ").strip():
        raise ValueError(f"unparseable coordinate list {s!r}")
    nums = [float(n) for n in _NUMBER_RE.findall(s)]
    if len(nums) % 2:
        raise ValueError(f"odd number count ({len(nums)}) in coordinate list {s!r}")
    return list(zip(nums[::2], nums[1::2]))


def _parse_path_d(d: str) -> list[tuple[float, float]]:
    """
    Parse an SVG path `d` attribute into a point list. Only absolute M/L
    and Z/z are supported — every room path in the one real reference
    export uses exactly these (a plain polygon outline) — anything else
    (relative m/l, or a curve command: C/Q/A/S/T) must fail loudly rather
    than silently produce a wrong or truncated polygon. Z/z closes the ring
    by repeating the first point when the source didn't already.
    """
    letters = set(_COMMAND_LETTER_RE.findall(_NUMBER_RE.sub(" ", d)))
    if unsupported := sorted(letters - _SUPPORTED_PATH_COMMANDS):
        raise ValueError(
            f"unsupported SVG path command(s) {unsupported!r} in d={d!r} — "
            "only absolute M/L and Z/z are handled"
        )
    pts = _parse_coord_pairs(re.sub(r"[MLZz]", " ", d))
    if letters & {"Z", "z"} and pts and _key(pts[0]) != _key(pts[-1]):
        pts.append(pts[0])
    return pts


def _has_dashed_stroke(elem) -> bool:
    """
    True if this SVG element's stroke is dashed, via EITHER the plain
    `stroke-dasharray` attribute or an inline `style="...stroke-dasharray:
    ..."` declaration. A literal "none" value in either form explicitly
    means "no dash" and must not be treated as dashed.
    """
    attr = (elem.get("stroke-dasharray") or "").strip().lower()
    if attr and attr != "none":
        return True
    style = elem.get("style") or ""
    match = re.search(r"stroke-dasharray\s*:\s*([^;]+)", style, re.IGNORECASE)
    if match:
        return match.group(1).strip().lower() != "none"
    return False


def _pick_door_polyline(candidates: list) -> list[tuple[float, float]] | None:
    """
    Among every polyline sharing one door_id_... class (jamb lines, swing-
    arc detail, and exactly one real opening-width reference line in the
    real reference export), return the points of the one with a real
    (non-"None") fill — that is the actual opening location/width. Returns
    None if no candidate has a real fill, so the caller can skip that door
    with a clear log message instead of guessing.
    """
    return next(
        (points for fill, points in candidates if fill and fill != "None"),
        None,
    )


_SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


def _find_rooms_group(svg_root):
    """Locate designg > prop > rooms, tolerant of the SVG default namespace
    (ElementTree requires the namespace prefix on every tag when one is
    declared on the root, per the reference file's xmlns attribute)."""
    return svg_root.find(
        ".//svg:g[@id='designg']/svg:g[@id='prop']/svg:g[@id='rooms']", _SVG_NS
    )


def _extract_rooms_and_doors(svg_root):
    """
    Returns (wall_polylines, space_polylines, door_polylines) from the
    SVG's rooms group. Every room path becomes a space; only solid-stroke
    (non-dashed) room paths also become a wall. Doors are grouped by their
    door_id_... class token and reduced to one real-fill polyline each via
    _pick_door_polyline.
    """
    rooms_group = _find_rooms_group(svg_root)
    wall_polylines, space_polylines = [], []
    door_candidates = {}  # door_id -> list of (fill, points)

    if rooms_group is None:
        log.warning("qbiq SVG: no designg/prop/rooms group found — no rooms, room walls or doors will be imported")
        return wall_polylines, space_polylines, []

    for elem in rooms_group.iter():
        tag = elem.tag.split("}")[-1]
        classes = elem.get("class", "")

        if tag == "path" and "d" in elem.attrib:
            try:
                pts = _parse_path_d(elem.get("d"))
            except ValueError:
                log.warning("skipping unparseable room path: %s", elem.get("d"))
                continue
            if len(pts) < 3:
                log.warning("skipping room path with fewer than 3 points: %s", elem.get("d"))
                continue
            space_polylines.append(pts)
            if not _has_dashed_stroke(elem):
                wall_polylines.append(pts)

        elif tag == "polyline":
            door_id = next(
                (tok for tok in classes.split() if tok.startswith("door_id_")),
                None,
            )
            if door_id is None:
                continue
            try:
                pts = _parse_coord_pairs(elem.get("points", ""))
            except ValueError as e:
                log.warning("skipping unparseable %s polyline: %s", door_id, e)
                continue
            fill = elem.get("fill", "None")
            door_candidates.setdefault(door_id, []).append((fill, pts))

    door_polylines = []
    for door_id, candidates in door_candidates.items():
        picked = _pick_door_polyline(candidates)
        if picked is None:
            log.warning("door %s has no real-fill opening polyline — skipping", door_id)
            continue
        door_polylines.append(picked)

    return wall_polylines, space_polylines, door_polylines


def _ls_to_polylines(segments_raw: list) -> list:
    """Convert one JSON `_ls` key's raw [[x,y],[x,y]] segment list into
    stitched polylines."""
    segments = [
        ((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
        for a, b in segments_raw
    ]
    return _stitch_segments(segments)


def _floor_plates(data: dict) -> list:
    """Closed perimeter_ls loops — the whole floor plate, so circulation
    space between rooms is routable, not just room interiors."""
    return [c for c in _ls_to_polylines(data.get("perimeter_ls", [])) if len(c) >= 4 and _key(c[0]) == _key(c[-1])]


def _to_segments(polylines: list) -> list:
    """Explode polylines into 2-point segments — the shape DXF walls arrive in,
    which both routers assume (grid A* blocks each wall's whole bbox, so a
    closed ring would block everything inside it). Duplicate edges (room
    rings share edges with neighbours and with JSON walls) are dropped,
    regardless of direction, and zero-length edges are skipped."""
    seen, segments = set(), []
    for a, b in (pair for pl in polylines for pair in zip(pl, pl[1:])):
        if len(k := frozenset((_key(a), _key(b)))) == 2 and k not in seen:
            seen.add(k)
            segments.append([a, b])
    return segments


def _extract_json_structure(data: dict):
    """
    Returns (wall_polylines, column_polylines, window_polylines,
    extent_points) from the JSON's structural keys. perimeter_ls, core_ls,
    and qbiq_walls_ls (when present) all become walls; columns_ls becomes
    columns; mullions becomes windows. The non-_ls keys (perimeter, core,
    columns, qbiq_walls) are confirmed redundant with their _ls
    counterparts and are never read. extent_points is every raw point seen,
    for the units-plausibility check.
    """
    wall_polylines = []
    for key in ("perimeter_ls", "core_ls", "qbiq_walls_ls"):
        wall_polylines.extend(_ls_to_polylines(data.get(key, [])))

    column_polylines = _ls_to_polylines(data.get("columns_ls", []))
    window_polylines = _ls_to_polylines(data.get("mullions", []))

    extent_points = []
    for polylines in (wall_polylines, column_polylines, window_polylines):
        for poly in polylines:
            extent_points.extend(poly)

    return wall_polylines, column_polylines, window_polylines, extent_points


_PLAUSIBLE_MIN_EXTENT_M = 2.0
_PLAUSIBLE_MAX_EXTENT_M = 200.0


def _fix_implausible_units(units_to_metres: float, extent_points: list) -> float:
    """
    Same plausibility-check pattern as dxf_extractor.py's
    _fix_implausible_units: if the declared units_to_metres produces an
    implausible overall building size, try power-of-ten corrections until
    one lands in a plausible single-floor-plate range (2m-200m). Returns
    the (possibly corrected) units_to_metres unchanged if no extent points
    are given or the declared scale is already plausible.
    """
    if not extent_points:
        return units_to_metres
    xs = [p[0] for p in extent_points]
    ys = [p[1] for p in extent_points]
    raw_extent = max(max(xs) - min(xs), max(ys) - min(ys))
    if raw_extent <= 0:
        return units_to_metres

    declared_extent_m = raw_extent * units_to_metres
    if _PLAUSIBLE_MIN_EXTENT_M <= declared_extent_m <= _PLAUSIBLE_MAX_EXTENT_M:
        return units_to_metres

    for factor in (10.0, 100.0, 1000.0, 0.1, 0.01, 0.001):
        corrected_m = declared_extent_m / factor
        if _PLAUSIBLE_MIN_EXTENT_M <= corrected_m <= _PLAUSIBLE_MAX_EXTENT_M:
            log.warning(
                "qbiq JSON: declared units give an implausible building size "
                "(%.1fm at %.6f m/unit) — correcting by a factor of %g to "
                "%.6f m/unit (building size now %.1fm).",
                declared_extent_m, units_to_metres, factor,
                units_to_metres / factor, corrected_m,
            )
            return units_to_metres / factor

    log.warning(
        "qbiq JSON: declared units give an implausible building size "
        "(%.1fm) and no simple power-of-10 correction fixes it — leaving "
        "units_to_metres as-is (%.6f m/unit).",
        declared_extent_m, units_to_metres,
    )
    return units_to_metres


def extract_qbiq(json_path: str, svg_path: str, level_name: str = "L-0") -> LevelGeometry:
    """Parse a matched qbiq Spaceplanner JSON+SVG export pair into a
    LevelGeometry. See the module docstring and the design spec for the
    full rationale."""
    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    json_walls, columns, windows, extent_points = _extract_json_structure(data)

    svg_root = ET.parse(svg_path).getroot()
    svg_walls, spaces, doors = _extract_rooms_and_doors(svg_root)

    if not (plates := _floor_plates(data)) and data.get("perimeter_ls"):
        log.warning("qbiq JSON: perimeter_ls has no closed loop — no floor plate, so corridors between rooms won't be routable")
    if not doors:
        log.warning("qbiq SVG: no doors extracted — routes between rooms may be blocked")
    spaces = plates + spaces
    walls = _to_segments(json_walls + svg_walls)

    units_to_metres = _fix_implausible_units(0.01, extent_points)

    # The JSON format carries no job_code field to cross-check against —
    # only the SVG's <desc> does — so this is a one-sided diagnostic
    # breadcrumb for whoever investigates a bad-looking import later, not a
    # validation step (the spec explicitly doesn't require detecting a
    # mismatched JSON/SVG pair). Read the <desc> element directly rather
    # than re-serialising the whole (potentially 1MB+) SVG back to a string.
    desc_elem = svg_root.find(".//svg:desc", _SVG_NS)
    job_code_match = re.search(r'job_code="([^"]*)"', desc_elem.text or "") if desc_elem is not None else None
    job_code = job_code_match.group(1) if job_code_match else "(none found)"

    log.info(
        "qbiq extracted from '%s' + '%s' (svg job_code=%s): %d walls, "
        "%d doors, %d columns, %d windows, %d spaces",
        json_path, svg_path, job_code, len(walls),
        len(doors), len(columns), len(windows), len(spaces),
    )

    return LevelGeometry(
        level_name=level_name,
        elevation=0.0,
        walls=walls,
        spaces=spaces,
        doors=doors,
        columns=columns,
        windows=windows,
        furniture=[],
        units_to_metres=units_to_metres,
        source="qbiq",
    )


# ── single-file qbiq "design" JSON ───────────────────────────────────────────

_DOOR_TOUCH_TOL = 3.0
_EDGE_TOUCH_TOL = 10.0
_CLUSTER_GAP = 15.0
_FALLBACK_DOOR_WIDTH = 90.0
_LINEAR_TYPES = {"LineString", "LinearRing", "Polygon"}

_Room = namedtuple("_Room", "rings enclosed doors furniture")


def is_qbiq_design(data: dict) -> bool:
    """True for a single-file qbiq design JSON (top-level rooms + nfp_data)."""
    return isinstance(data, dict) and isinstance(data.get("rooms"), list) and isinstance(data.get("nfp_data"), dict)


def _wkt(text):
    """Parse one WKT string; None (with a warning) when malformed, None when absent."""
    if not isinstance(text, str) or not text.strip() or text == "None":
        return None
    try:
        return wkt.loads(text)
    except (ShapelyError, ValueError):
        log.warning("qbiq design: skipping malformed WKT %.80r", text)
        return None


def _wkt_many(value) -> list:
    """Parse a WKT string or a list of WKT strings into geometries."""
    texts = [value] if isinstance(value, str) else [v for v in value or [] if isinstance(v, str)]
    return [g for t in texts if (g := _wkt(t)) is not None]


def _parts(geom) -> list:
    """Flatten nested collections and multi-geometries into simple parts."""
    if geom is None or geom.is_empty:
        return []
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _parts(g)]
    return [geom]


def _part_coords(part) -> list:
    """A simple part's points as float tuples (a Polygon gives its exterior ring)."""
    coords = part.exterior.coords if part.geom_type == "Polygon" else part.coords
    return [(float(c[0]), float(c[1])) for c in coords]


def _polylines(geom) -> list:
    """Every LineString / Polygon exterior in a geometry as a polyline; points dropped."""
    return [_part_coords(p) for p in _parts(geom) if p.geom_type in _LINEAR_TYPES]


def _vertices(geom) -> list:
    """Every vertex of every part of a geometry."""
    return [pt for p in _parts(geom) for pt in _part_coords(p)]


def _corner_segment(item):
    """A {corner1, corner2} dict as a 2-point polyline; None when malformed."""
    try:
        return [(float(item["corner1"][0]), float(item["corner1"][1])),
                (float(item["corner2"][0]), float(item["corner2"][1]))]
    except (KeyError, TypeError, ValueError, IndexError):
        log.warning("qbiq design: skipping malformed segment %.80r", item)
        return None


def _corner_segments(items) -> list:
    """All well-formed {corner1, corner2} entries as 2-point polylines."""
    return [seg for item in items or [] if (seg := _corner_segment(item))]


def _core_polylines(cores) -> list:
    """Cores as walls when they're corner dicts or WKT; anything else is ignored."""
    polylines = []
    for core in [cores] if isinstance(cores, str) else cores or []:
        if isinstance(core, dict) and "corner1" in core:
            polylines.extend(_corner_segments([core]))
        elif isinstance(core, str):
            polylines.extend(pl for g in _wkt_many(core) for pl in _polylines(g))
        else:
            log.debug("qbiq design: ignoring unrecognised core entry %.80r", core)
    return polylines


def _is_shown(door: dict) -> bool:
    """show_door may arrive as a bool or as its string form."""
    return str(door.get("show_door")).lower() == "true"


def _touching(line, points: list, tol: float) -> list:
    """Positions along `line` of the points lying within `tol` of it."""
    return [line.project(GeomPoint(p)) for p in points if line.distance(GeomPoint(p)) <= tol]


def _span(line, start: float, end: float) -> list:
    """The 2-point sub-segment of `line` between two positions along it."""
    return [(pt.x, pt.y) for pt in (line.interpolate(start), line.interpolate(end))]


def _extent(line, points: list, tol: float):
    """The part of `line` covered by the points within `tol` of it; None for fewer than 2."""
    pos = _touching(line, points, tol)
    return _span(line, min(pos), max(pos)) if len(pos) >= 2 and max(pos) > min(pos) else None


def _clusters(geom) -> list:
    """Split a drawing into connected clusters (parts within _CLUSTER_GAP of each other), as vertex lists."""
    parts = _parts(geom)
    blobs = _parts(unary_union([p.buffer(_CLUSTER_GAP / 2) for p in parts]))
    return [[pt for p in parts if blob.intersects(p) for pt in _part_coords(p)] for blob in blobs]


def _assign_clusters(lines: list, clusters: list) -> list:
    """
    Give each door one drawing cluster, closest (line, cluster) pairs first,
    so two doors never share one drawing and a mislabelled door_line still
    ends up with the drawing nobody nearer claimed; doors without a line take
    what's left in order. Clusters still unclaimed after that (a drawing with
    gaps, e.g. jamb ticks and no swing arc) join the door with the nearest line.
    """
    dist = [[math.inf if line is None else line.distance(MultiPoint(c)) for c in clusters] for line in lines]
    assigned, taken = {}, set()
    for _, i, j in sorted((dist[i][j], i, j) for i in range(len(lines)) for j in range(len(clusters))):
        if i not in assigned and j not in taken:
            assigned[i] = j
            taken.add(j)
    points = [list(clusters[assigned[i]]) if i in assigned else [] for i in range(len(lines))]
    for j in set(range(len(clusters))) - taken:
        if (nearest := min(range(len(lines)), key=lambda i: dist[i][j], default=None)) is not None and dist[nearest][j] < math.inf:
            points[nearest] += clusters[j]
    return points


def _door_opening(line, points: list, edges: list):
    """
    The real opening is where the door drawing touches its wall line. door_line
    is the whole wall edge, but on real exports it is sometimes a different
    edge of the room than the one the door is drawn on (or missing), and some
    drawings sit a wall-thickness inside the edge — so the room edge with the
    most drawing points within _EDGE_TOUCH_TOL is tried next, before the
    fixed-width midpoint fallback.
    """
    if line is not None and (opening := _extent(line, points, _DOOR_TOUCH_TOL)):
        return opening
    best = max(edges, key=lambda e: len(_touching(e, points, _EDGE_TOUCH_TOL)), default=None)
    if best is not None and (opening := _extent(best, points, _EDGE_TOUCH_TOL)):
        return opening
    if line is None:
        log.warning("qbiq design: door has no door_line and no geometry on a room edge — skipping")
        return None
    log.debug("qbiq design: no door geometry on %s — using a %g-unit opening at its midpoint", line.wkt, _FALLBACK_DOOR_WIDTH)
    mid = line.length / 2
    return _span(line, mid - _FALLBACK_DOOR_WIDTH / 2, mid + _FALLBACK_DOOR_WIDTH / 2)


def _room_doors(room: dict, rings: list) -> list:
    """One trimmed 2-point opening per visible door of a room."""
    doors = [d for d in room.get("doors") or [] if isinstance(d, dict)]
    lines = [_wkt(d.get("door_line")) for d in doors]
    shared = _assign_clusters(lines, _clusters(_wkt(room.get("door_geometry"))))
    edges = [LineString(pair) for ring in rings for pair in zip(ring, ring[1:])]
    return [
        op for d, line, cluster in zip(doors, lines, shared)
        if _is_shown(d) and (op := _door_opening(line, _vertices(own) if (own := _wkt(d.get("door_geometry"))) else cluster, edges))
    ]


def _room(room: dict):
    """Parse one room into rings, enclosure, doors and furniture; None when malformed."""
    try:
        if not (rings := [r for r in _polylines(_wkt(room.get("geometry"))) if len(r) >= 4]):
            log.warning("qbiq design: skipping room %r with no usable geometry", room.get("space_type"))
            return None
        enclosed = any(_is_shown(d) for d in room.get("doors") or [] if isinstance(d, dict))
        furniture = _polylines(_wkt(room.get("stencil_geometry")))
        return _Room(rings, enclosed, _room_doors(room, rings), furniture)
    except (AttributeError, KeyError, TypeError, ValueError, ShapelyError):
        log.warning("qbiq design: skipping malformed room %r", room.get("space_type"), exc_info=True)
        return None


def extract_qbiq_design(json_path: str, level_name: str = "L-0") -> LevelGeometry:
    """Parse a single-file qbiq design JSON (WKT geometry in cm) into a LevelGeometry."""
    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not is_qbiq_design(data):
        raise ValueError("Not a qbiq design JSON: expected a top-level 'rooms' list and 'nfp_data' object")
    nfp = data["nfp_data"]

    plates = [pl for g in _wkt_many(nfp.get("fill")) for pl in _polylines(g)]
    rooms = [r for room in data["rooms"] if isinstance(room, dict) and (r := _room(room))]
    structural = (_corner_segments(nfp.get("walls")) + _corner_segments(nfp.get("interior_walls"))
                  + _core_polylines(nfp.get("cores")))

    walls = _to_segments(structural + [ring for r in rooms if r.enclosed for ring in r.rings])
    spaces = plates + [ring for r in rooms for ring in r.rings]
    doors = [d for r in rooms for d in r.doors]
    columns = [pl for g in _wkt_many(nfp.get("columns")) for pl in _polylines(g)]
    windows = _corner_segments(nfp.get("windows"))
    furniture = [pl for r in rooms for pl in r.furniture]

    if not plates:
        log.warning("qbiq design: no nfp_data.fill — no floor plate, so corridors between rooms won't be routable")
    if not doors:
        log.warning("qbiq design: no doors extracted — routes between rooms may be blocked")
    if not walls:
        log.warning("qbiq design: no walls extracted")

    units_to_metres = _fix_implausible_units(0.01, [p for pl in walls + spaces + columns for p in pl])
    enclosed = sum(r.enclosed for r in rooms)
    log.info(
        "qbiq design extracted from '%s' (job_code=%s): %d walls, %d doors, %d columns, "
        "%d windows, %d furniture, %d spaces (%d enclosed rooms, %d open)",
        json_path, data.get("job_code", "(none)"), len(walls), len(doors), len(columns),
        len(windows), len(furniture), len(spaces), enclosed, len(rooms) - enclosed,
    )

    return LevelGeometry(
        level_name=level_name,
        elevation=0.0,
        walls=walls,
        spaces=spaces,
        doors=doors,
        columns=columns,
        windows=windows,
        furniture=furniture,
        units_to_metres=units_to_metres,
        source="qbiq",
    )
