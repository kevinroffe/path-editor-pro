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
"""

from __future__ import annotations
import json
import logging
import re
import xml.etree.ElementTree as ET

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
_SUPPORTED_PATH_COMMANDS = set("MLZ")
_COORD_PAIR_RE = re.compile(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")


def _parse_path_d(d: str) -> list[tuple[float, float]]:
    """
    Parse an SVG path `d` attribute into a point list. Only M/L/Z are
    supported — every room path in the one real reference export uses
    exactly these (a plain polygon outline) — anything else (a curve
    command: C/Q/A/S/T) must fail loudly rather than silently produce a
    wrong or truncated polygon, since a future qbiq export could add a
    rounded corner or arc that this simple walk cannot represent.
    """
    letters = set(_COMMAND_LETTER_RE.findall(d.upper()))
    unsupported = sorted(letters - _SUPPORTED_PATH_COMMANDS)
    if unsupported:
        raise ValueError(
            f"unsupported SVG path command(s) {unsupported!r} in d={d!r} — "
            "only M/L/Z are handled"
        )
    return [(float(x), float(y)) for x, y in _COORD_PAIR_RE.findall(d)]


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
            points_str = elem.get("points", "")
            pts = [
                (float(x), float(y))
                for x, y in (pair.split(",") for pair in points_str.split())
            ]
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
    return [c for c in _ls_to_polylines(data.get("perimeter_ls", [])) if len(c) >= 4 and c[0] == c[-1]]


def _to_segments(polylines: list) -> list:
    """Explode polylines into 2-point segments — the shape DXF walls arrive in,
    which both routers assume (grid A* blocks each wall's whole bbox, so a
    closed ring would block everything inside it)."""
    return [[a, b] for pl in polylines for a, b in zip(pl, pl[1:]) if a != b]


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
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    json_walls, columns, windows, extent_points = _extract_json_structure(data)

    svg_root = ET.parse(svg_path).getroot()
    svg_walls, spaces, doors = _extract_rooms_and_doors(svg_root)

    spaces = _floor_plates(data) + spaces
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
