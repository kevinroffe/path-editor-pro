"""
qbiq_scene3d.py
---------------
Builds the 3D preview scene (LevelGeometry.meshes) for a single-file qbiq
design JSON: tinted floor slabs, a white exterior shell with sill/glass/head
window bands, glass interior partitions with frames and door openings,
columns, cores and simple typed furniture placed from each stencil
component's geom_box + matrix3d.

Plan coordinates stay in model units (centimetres) until the final merge,
where x/y are scaled by units_to_metres; z is always metres. Every face
gets its own vertices (flat shading) and faces sharing one material are
merged into a single mesh dict so the frontend issues a few dozen draw calls.
"""

from __future__ import annotations
import logging
import math
import re
from collections import Counter, namedtuple
from dataclasses import dataclass

import numpy as np
import shapely
from shapely import wkt
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

log = logging.getLogger(__name__)

Mat = namedtuple("Mat", "type color opacity roughness metalness smooth finish", defaults=(False, "plain"))
Bounds = namedtuple("Bounds", "x0 x1 y0 y1")


def _mat(kind: str, color: str, opacity: float = 1.0, roughness: float = 0.85, metalness: float = 0.0,
         smooth: bool = False, finish: str = "plain") -> Mat:
    """A material key; faces with equal keys are merged into one mesh (smooth ones share side vertices)."""
    return Mat(kind, color, opacity, roughness, metalness, smooth, finish)


PLATE = _mat("floor", "#e9e7e2", roughness=0.9, finish="concrete")
WALL = _mat("wall", "#f4f4f2", roughness=0.9, finish="plaster")
WINDOW = _mat("window", "#a9c7d6", 0.35, 0.05, finish="glass")
GLASS = _mat("glass", "#bcd6e0", 0.28, 0.05, finish="glass")
FRAME = _mat("frame", "#3a3f45", roughness=0.4, metalness=0.6, finish="metal")
TRIM = _mat("frame", "#f4f4f2", roughness=0.9, finish="plaster")
COLUMN = _mat("column", "#f2f2f0", roughness=0.9, finish="plaster")
BOOTH = _mat("furniture", "#e2e5ea", roughness=0.7)
NEUTRAL = _mat("furniture", "#c9c6c0", roughness=0.8)

FABRIC_CHARCOAL = _mat("furniture", "#3b3f46", roughness=0.95, smooth=True, finish="fabric")
FABRIC_GREY = _mat("furniture", "#8a8f96", roughness=0.95, smooth=True, finish="fabric")
FABRIC_SAND = _mat("furniture", "#c9b79c", roughness=0.95, smooth=True, finish="fabric")
FABRIC_TEAL = _mat("furniture", "#5b8a8c", roughness=0.95, smooth=True, finish="fabric")
OAK_LIGHT = _mat("furniture", "#c49a6c", roughness=0.6, finish="oak")
LAMINATE = _mat("furniture", "#f3f3f1", roughness=0.55, finish="laminate")
METAL = _mat("furniture", "#b8bcc2", roughness=0.35, metalness=0.7, finish="metal")
METAL_SMOOTH = _mat("furniture", "#b8bcc2", roughness=0.35, metalness=0.7, smooth=True, finish="metal")
PLASTIC_BLACK = _mat("furniture", "#25282c", roughness=0.5, finish="plastic")
PLASTIC_BLACK_SMOOTH = _mat("furniture", "#25282c", roughness=0.5, smooth=True, finish="plastic")
STAINLESS = _mat("furniture", "#c9cdd2", roughness=0.25, metalness=0.8, finish="steel")
FRIDGE = _mat("furniture", "#eef0f2", roughness=0.4, finish="metal")
FOLIAGE = _mat("furniture", "#4f7d4a", roughness=0.9, smooth=True, finish="foliage")
FOLIAGE_LIGHT = _mat("furniture", "#5f9558", roughness=0.9, smooth=True, finish="foliage")
TERRACOTTA = _mat("furniture", "#b5674d", roughness=0.85, smooth=True, finish="ceramic")
SCREEN = _mat("furniture", "#15171a", roughness=0.2, metalness=0.2, finish="screen")

_ROOM_COLOURS = (
    (("open space", "workstation"), "#dcdcdc"),
    (("office",), "#d9c4a1"),
    (("conference", "meeting", "board"), "#cfc9c2"),
    (("kitchen", "pantry"), "#e7d3b3"),
    (("comfort", "lounge"), "#c9d8c5"),
    (("storage", "it room", "server"), "#c8c8c8"),
)
_DEFAULT_ROOM_COLOUR = "#dddad4"

CEILING = 3.0
CEILING_TOP = 3.05
CEILING_MAT = _mat("ceiling", "#f7f7f5", roughness=0.95, finish="ceiling")
LIGHT_MAT = _mat("light", "#fff6e0", roughness=1.0, finish="light")
PANEL_W, PANEL_L, PANEL_PITCH = 0.6, 1.2, 2.4
PANEL_Z0, PANEL_Z1 = 2.99, 2.995
WALL_THICK = 0.25
SILL, HEAD = 0.9, 2.4
PANE_Z0, PANE_Z1, RAIL_TOP = 0.05, 2.7, 2.8
GLASS_THICK, RAIL_THICK, BULKHEAD_THICK = 0.03, 0.06, 0.1
MULLION_W, MULLION_SPACING = 0.05, 1.5
JAMB_W, JAMB_THICK, DOOR_HEAD = 0.05, 0.08, 2.1

_SHELL_TOL = 15.0
_DOOR_TOL = 5.0
_MIN_LEN = 1e-6
_MAX_VERTS = 400_000


@dataclass
class SceneInputs:
    """What the extractor already parsed, in model units."""
    plates: list
    rooms: list
    exterior: list
    windows: list
    partitions: list
    doors: list
    columns: list
    cores: list


# ── primitives ──────────────────────────────────────────────────────────────

def _sides(mat: Mat, ring: list, z0: float, z1: float, top: list | None = None) -> list:
    """One outward quad per edge of an (open) ring extruded z0→z1 (top ring may be shifted), tagged "side"."""
    top = top or ring
    n = len(ring)
    return [(mat, [(*ring[i], z0), (*ring[(i + 1) % n], z0), (*top[(i + 1) % n], z1), (*top[i], z1)], "side")
            for i in range(n)]


def _prism(mat: Mat, ring: list, z0: float, z1: float, shift: tuple = (0.0, 0.0)) -> list:
    """A convex CCW ring extruded z0→z1 with both caps; a shift slants the top ring (chair backs, legs)."""
    top = [(x + shift[0], y + shift[1]) for x, y in ring]
    return _sides(mat, ring, z0, z1, top) + [(mat, [(*p, z1) for p in top]), (mat, [(*p, z0) for p in ring[::-1]])]


def _round_rect(b: Bounds, r: float, seg: int = 4) -> list:
    """A CCW rectangle ring with rounded corners (radius clamped to the box)."""
    r = max(0.0, min(r, (b.x1 - b.x0) / 2, (b.y1 - b.y0) / 2))
    corners = ((b.x1 - r, b.y0 + r, -math.pi / 2), (b.x1 - r, b.y1 - r, 0.0),
               (b.x0 + r, b.y1 - r, math.pi / 2), (b.x0 + r, b.y0 + r, math.pi))
    return [(cx + r * math.cos(a0 + math.pi / 2 * i / seg), cy + r * math.sin(a0 + math.pi / 2 * i / seg))
            for cx, cy, a0 in corners for i in range(seg + 1)]


def _bar_ring(cx: float, cy: float, length: float, width: float, angle: float) -> list:
    """A CCW rectangle from (cx, cy) outward `length` along `angle`, `width` wide (star-base spokes)."""
    ux, uy, h = math.cos(angle), math.sin(angle), width / 2
    nx, ny = -uy * h, ux * h
    return [(cx - nx, cy - ny), (cx + ux * length - nx, cy + uy * length - ny),
            (cx + ux * length + nx, cy + uy * length + ny), (cx + nx, cy + ny)]


def _polygons(geom) -> list:
    """The non-empty polygon parts of a geometry, repaired when invalid."""
    fixed = geom if geom.is_valid else shapely.make_valid(geom)
    return [p for p in shapely.get_parts(fixed) if p.geom_type == "Polygon" and p.area > 0]


def _solid_part(mat: Mat, poly: Polygon, z0: float, z1: float) -> list:
    """Side walls plus a triangulated top cap of one polygon (holes respected)."""
    poly = orient(poly, 1.0)
    sides = [f for r in (poly.exterior, *poly.interiors) for f in _sides(mat, list(r.coords)[:-1], z0, z1)]
    tris = shapely.get_parts(shapely.constrained_delaunay_triangles(poly))
    return sides + [(mat, [(*p, z1) for p in list(orient(t, 1.0).exterior.coords)[:3]]) for t in tris]


def _solid(mat: Mat, geom, z0: float, z1: float) -> list:
    """A polygonal geometry extruded z0→z1 (top cap and sides)."""
    return [f for p in _polygons(geom) for f in _solid_part(mat, p, z0, z1)]


def _apply(frame: tuple, x: float, y: float) -> tuple:
    """Map a local point through a (a, b, c, d, tx, ty) affine frame."""
    a, b, c, d, tx, ty = frame
    return (a * x + b * y + tx, c * x + d * y + ty)


def _rect(x0: float, x1: float, y0: float, y1: float) -> list:
    """A CCW axis-aligned rectangle ring."""
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _framed(mat: Mat, frame: tuple, ring: list, z0: float, z1: float, shift: tuple = (0.0, 0.0)) -> list:
    """A local convex ring (top optionally shifted) placed through a frame; mirrored frames keep CCW winding."""
    a, b, c, d = frame[:4]
    world = [_apply(frame, *p) for p in ring]
    world_shift = (a * shift[0] + b * shift[1], c * shift[0] + d * shift[1])
    return _prism(mat, world if a * d - b * c > 0 else world[::-1], z0, z1, world_shift)


def _seg_frame(p, q) -> tuple:
    """An orthonormal frame with local x along p→q and local y to its left, plus its length."""
    length = math.dist(p, q)
    if length < _MIN_LEN:
        raise ValueError("zero-length segment")
    dx, dy = (q[0] - p[0]) / length, (q[1] - p[1]) / length
    return (dx, -dy, dy, dx, p[0], p[1]), length


def _local(frame: tuple, pt) -> tuple:
    """A world point's (along, across) coordinates in an orthonormal segment frame."""
    dx, _, dy, _, px, py = frame
    rx, ry = pt[0] - px, pt[1] - py
    return (dx * rx + dy * ry, -dy * rx + dx * ry)


def _bar(mat: Mat, frame: tuple, s0: float, s1: float, half: float, z0: float, z1: float) -> list:
    """A box along a segment frame between positions s0..s1, `half` thick each side."""
    return _framed(mat, frame, _rect(s0, s1, -half, half), z0, z1) if s1 - s0 > _MIN_LEN else []


# ── intervals along a segment ───────────────────────────────────────────────

def _merge_intervals(intervals: list) -> list:
    """Union overlapping (lo, hi) intervals."""
    merged = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _subtract(length: float, holes: list) -> list:
    """The parts of [0, length] not covered by merged hole intervals."""
    edges = [0.0, *(v for iv in holes for v in iv), length]
    return [(a, b) for a, b in zip(edges[::2], edges[1::2]) if b - a > _MIN_LEN]


def _on_line(frame: tuple, length: float, seg, tol: float):
    """The clipped interval a segment covers along a frame's line when both its ends lie within tol of it."""
    (sa, ta), (sb, tb) = _local(frame, seg[0]), _local(frame, seg[1])
    if abs(ta) > tol or abs(tb) > tol:
        return None
    lo, hi = max(min(sa, sb), 0.0), min(max(sa, sb), length)
    return (lo, hi) if hi - lo > _MIN_LEN else None


def _intervals(frame: tuple, length: float, segments: list, tol: float) -> list:
    """Merged intervals covered by every segment lying along a frame's line."""
    return _merge_intervals([iv for s in segments if (iv := _on_line(frame, length, s, tol))])


# ── exterior shell ──────────────────────────────────────────────────────────

def _ext(lo: float, hi: float, length: float, half: float) -> tuple:
    """Stretch an interval by `half` past whichever segment end it touches, closing wall corners."""
    return (lo - half if lo <= _MIN_LEN else lo, hi + half if hi >= length - _MIN_LEN else hi)


def _window_band(frame: tuple, lo: float, hi: float, length: float, k: float) -> list:
    """Solid sill, glass band and solid head across one window interval."""
    half = WALL_THICK / 2 * k
    s0, s1 = _ext(lo, hi, length, half)
    return (_bar(WALL, frame, s0, s1, half, 0.0, SILL) + _bar(WINDOW, frame, lo, hi, GLASS_THICK / 2 * k, SILL, HEAD)
            + _bar(WALL, frame, s0, s1, half, HEAD, CEILING))


def _exterior_wall(seg, windows: list, k: float) -> list:
    """One exterior wall: full-height solid outside window spans, window bands inside them."""
    frame, length = _seg_frame(*seg)
    half = WALL_THICK / 2 * k
    spans = _intervals(frame, length, windows, _SHELL_TOL)
    solid = [f for lo, hi in _subtract(length, spans) for f in _bar(WALL, frame, *_ext(lo, hi, length, half), half, 0.0, CEILING)]
    return solid + [f for lo, hi in spans for f in _window_band(frame, lo, hi, length, k)]


def _facade_window(seg, k: float) -> list:
    """A window segment on no wall is glazed façade: a window band over its full length."""
    frame, length = _seg_frame(*seg)
    return _window_band(frame, 0.0, length, length, k)


def _on_any_wall(window, walls: list) -> bool:
    """True when a window segment projects onto some exterior wall."""
    return any(_on_line(*_seg_frame(*w), window, _SHELL_TOL) for w in walls if math.dist(*w) > _MIN_LEN)


# ── interior glass partitions ───────────────────────────────────────────────

def _partition_segments(inp: SceneInputs) -> list:
    """Interior partition edges, overlaps unioned, minus anything along the exterior shell."""
    lines = [LineString(s) for s in inp.partitions if math.dist(*s) > _MIN_LEN]
    if not lines:
        return []
    shell = unary_union([LineString(s) for s in inp.exterior + inp.windows if math.dist(*s) > _MIN_LEN])
    pieces = unary_union(lines).difference(shell.buffer(_SHELL_TOL))
    return [pair for p in shapely.get_parts(pieces) if p.geom_type == "LineString"
            for pair in zip(p.coords, p.coords[1:])]


def _mullions(frame: tuple, lo: float, hi: float, length: float, k: float) -> list:
    """Vertical mullions across a pane at ≤1.5 m spacing; pane ends next to a door get a jamb instead."""
    n = max(1, math.ceil((hi - lo) / (MULLION_SPACING * k)))
    w, half = MULLION_W * k / 2, RAIL_THICK / 2 * k
    keep = [i for i in range(n + 1) if not (i == 0 and lo > _MIN_LEN) and not (i == n and hi < length - _MIN_LEN)]
    return [f for i in keep for pos in (lo + i * (hi - lo) / n,)
            for f in _bar(FRAME, frame, max(lo, pos - w), min(hi, pos + w), half, PANE_Z0, PANE_Z1)]


def _pane(frame: tuple, lo: float, hi: float, length: float, k: float) -> list:
    """A glass pane with bottom and top rails and mullions over one interval."""
    rail = RAIL_THICK / 2 * k
    return (_bar(GLASS, frame, lo, hi, GLASS_THICK / 2 * k, PANE_Z0, PANE_Z1)
            + _bar(FRAME, frame, lo, hi, rail, 0.0, PANE_Z0) + _bar(FRAME, frame, lo, hi, rail, PANE_Z1, RAIL_TOP)
            + _mullions(frame, lo, hi, length, k))


def _door_frame(frame: tuple, lo: float, hi: float, k: float) -> list:
    """Two jambs to door height plus a white header up to the bulkhead."""
    jamb, half = min(JAMB_W * k, (hi - lo) / 4), JAMB_THICK / 2 * k
    return (_bar(FRAME, frame, lo, lo + jamb, half, 0.0, DOOR_HEAD) + _bar(FRAME, frame, hi - jamb, hi, half, 0.0, DOOR_HEAD)
            + _bar(TRIM, frame, lo, hi, BULKHEAD_THICK / 2 * k, DOOR_HEAD, RAIL_TOP))


def _partition(seg, doors: list, k: float) -> list:
    """A glass partition: panes between door openings, door frames in them, a bulkhead above all."""
    frame, length = _seg_frame(*seg)
    openings = _intervals(frame, length, doors, _DOOR_TOL)
    return ([f for lo, hi in _subtract(length, openings) for f in _pane(frame, lo, hi, length, k)]
            + [f for lo, hi in openings for f in _door_frame(frame, lo, hi, k)]
            + _bar(TRIM, frame, 0.0, length, BULKHEAD_THICK / 2 * k, RAIL_TOP, CEILING))


# ── floors, columns, cores ──────────────────────────────────────────────────

_FLOOR_FINISHES = (
    (("office", "conference", "meeting", "board", "focus", "open space", "work"), "carpet"),
    (("kitchen", "pantry", "cafe", "comfort", "lounge", "reception", "wellness"), "wood"),
)


def room_colour(space_type) -> str:
    """The floor tint for a room's space_type."""
    name = str(space_type or "").lower()
    return next((c for keys, c in _ROOM_COLOURS if any(key in name for key in keys)), _DEFAULT_ROOM_COLOUR)


def floor_finish(space_type) -> str:
    """The floor surface name (carpet / wood / concrete) for a room's space_type."""
    name = str(space_type or "").lower()
    return next((f for keys, f in _FLOOR_FINISHES if any(key in name for key in keys)), "concrete")


def _room_slab(rings: list, space_type) -> list:
    """A 0.02–0.03 m slab per room ring, tinted by space type."""
    mat = _mat("floor", room_colour(space_type), roughness=0.85, finish=floor_finish(space_type))
    return [f for ring in rings for f in _solid(mat, Polygon(ring), 0.02, 0.03)]


def _column(ring: list) -> list:
    """A column outline extruded floor to ceiling."""
    return _solid(COLUMN, Polygon(ring), 0.0, CEILING)


def _core(polyline: list, k: float) -> list:
    """A closed core outline becomes a solid block; an open one a run of solid walls."""
    if len(polyline) >= 4 and math.dist(polyline[0], polyline[-1]) < _MIN_LEN:
        return _solid(WALL, Polygon(polyline), 0.0, CEILING)
    return [f for seg in zip(polyline, polyline[1:]) for f in _exterior_wall(seg, [], k)]


# ── ceiling ─────────────────────────────────────────────────────────────────

def _ceiling_part(poly: Polygon) -> list:
    """One ceiling polygon: sides, top cap and a downward-facing underside (seen from the room)."""
    poly = orient(poly, 1.0)
    tris = shapely.get_parts(shapely.constrained_delaunay_triangles(poly))
    under = [(CEILING_MAT, [(*q, CEILING) for q in list(orient(t, 1.0).exterior.coords)[:3][::-1]]) for t in tris]
    return _solid_part(CEILING_MAT, poly, CEILING, CEILING_TOP) + under


def _ceiling(plates: list) -> list:
    """A flat ceiling over every floor plate (holes respected)."""
    return [f for g in plates for poly in _polygons(g) for f in _ceiling_part(poly)]


def _core_area(cores: list, k: float):
    """The union of core footprints (closed outlines, or open runs as wall-thick strips)."""
    shapes = [Polygon(c) if len(c) >= 4 and math.dist(c[0], c[-1]) < _MIN_LEN else LineString(c).buffer(WALL_THICK * k / 2)
              for c in cores if len(c) >= 2]
    return unary_union(shapes) if shapes else None


def _wall_area(partitions: list, exterior: list, k: float):
    """Partition bulkheads and exterior walls as areas the ceiling panels must stay clear of."""
    lines = [LineString(seg).buffer(BULKHEAD_THICK * k / 2) for seg in partitions if math.dist(*seg) > _MIN_LEN]
    lines += [LineString(seg).buffer(WALL_THICK * k / 2) for seg in exterior if math.dist(*seg) > _MIN_LEN]
    return unary_union(lines) if lines else None


def _light_panels(plates: list, cores: list, k: float, walls=None) -> list:
    """0.6 x 1.2 m recessed panels on a 2.4 m grid, wholly inside a plate and clear of cores and walls."""
    blocked = unary_union([g for g in (_core_area(cores, k), walls) if g is not None]) if cores or walls else None
    pitch, hw, hl = PANEL_PITCH * k, PANEL_W * k / 2, PANEL_L * k / 2
    faces = []
    for plate in plates:
        x0, y0, x1, y1 = plate.bounds
        for cx in np.arange(x0 + pitch / 2, x1, pitch):
            for cy in np.arange(y0 + pitch / 2, y1, pitch):
                panel = box(cx - hw, cy - hl, cx + hw, cy + hl)
                if plate.contains(panel) and (blocked is None or not blocked.intersects(panel)):
                    faces += _prism(LIGHT_MAT, _rect(cx - hw, cx + hw, cy - hl, cy + hl), PANEL_Z0, PANEL_Z1)
    return faces


# ── furniture ───────────────────────────────────────────────────────────────

def _inset(b: Bounds, d: float) -> Bounds:
    """Shrink bounds by d on every side, never past a quarter of either dimension."""
    d = min(d, (b.x1 - b.x0) / 4, (b.y1 - b.y0) / 4)
    return Bounds(b.x0 + d, b.x1 - d, b.y0 + d, b.y1 - d)


def _box(mat: Mat, b: Bounds, z0: float, z1: float) -> tuple:
    """A local furniture piece filling bounds b from z0 to z1."""
    return (mat, _rect(*b), z0, z1)


def _ngon(b: Bounds, n: int = 12) -> list:
    """The inscribed circle of b as a CCW n-gon."""
    cx, cy, r = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, min(b.x1 - b.x0, b.y1 - b.y0) / 2
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _phone_booth(b: Bounds, k: float, name: str, bom: str) -> list:
    """A phone booth as a pale box (not in the bom catalogue)."""
    return [_box(BOOTH, b, 0.0, 2.2)]


def _fallback(b: Bounds, k: float, name: str, bom: str) -> list:
    """Anything unrecognised: a neutral box at desk height."""
    return [_box(NEUTRAL, b, 0.0, 0.75)]


# ── bom-driven furniture ────────────────────────────────────────────────────

Part = namedtuple("Part", "code length width")   # metres
_BOM_PART = re.compile(r"^([A-Z]+(?:_[A-Z]+)*)_L(\d+)_W(\d+)$")
_PRIMARY_ORDER = ("T_WS", "T_D", "T_R", "T_C", "T_CF", "T_DT", "T_BR", "CO_H", "K_C", "K_DB", "L_S", "L_B",
                  "S_LS", "S_HS", "PH_PR", "V_P", "C_C", "C_K", "C_W", "C_E", "C_G", "C_B", "K_S", "K_R")
_DESKS = frozenset({"T_WS", "T_D", "T_R"})
_PART_BUILDERS: dict = {}        # code -> builder(b, k, name, part) -> pieces (filled per part kind below)
_UNKNOWN_CODES: set = set()
_SINK_MARGIN_M = 0.1


def parse_bom(bom) -> list:
    """The `CODE_L<cm>_W<cm>` parts of a bom string, in metres; malformed parts are skipped."""
    return [Part(m[1], int(m[2]) / 100, int(m[3]) / 100)
            for raw in str(bom or "").split("|") if (m := _BOM_PART.match(raw.strip()))]


def _rank(code: str) -> int:
    """Primary-part priority: furniture bodies before the chairs and fittings that come with them."""
    return _PRIMARY_ORDER.index(code) if code in _PRIMARY_ORDER else len(_PRIMARY_ORDER)


def _known_parts(bom: str) -> list:
    """Buildable parts when the primary part has a builder (unknown extras skipped, logged once), else []."""
    parts = parse_bom(bom)
    for part in parts:
        if part.code not in _PART_BUILDERS and part.code not in _UNKNOWN_CODES:
            _UNKNOWN_CODES.add(part.code)
            log.warning("qbiq scene: no furniture builder for bom code %s", part.code)
    if not parts or min(parts, key=lambda part: _rank(part.code)).code not in _PART_BUILDERS:
        return []
    return [part for part in parts if part.code in _PART_BUILDERS]


def _build_part(part: Part, b: Bounds, k: float, name: str) -> list:
    """Pieces of one bom part filling bounds b."""
    return _PART_BUILDERS[part.code](b, k, name, part)


def _span(b: Bounds, length: float) -> Bounds:
    """b narrowed to `length` across x, centred (never wider than b)."""
    w, cx = min(length, b.x1 - b.x0), (b.x0 + b.x1) / 2
    return b._replace(x0=cx - w / 2, x1=cx + w / 2)


def _flip_y(pieces: list, b: Bounds) -> list:
    """Pieces mirrored across b's middle in local y (a chair turned to face +y)."""
    def mirror(ring):
        return [(x, b.y0 + b.y1 - y) for x, y in ring][::-1]
    return [(mat, mirror(ring), z0, z1, *([(sh[0][0], -sh[0][1])] if (sh := rest) else []))
            for mat, ring, z0, z1, *rest in pieces]


_GUEST_FIT = 0.9          # guests fit when the box has >= 90% of the depth they need
_L_DESK_TOP_M, _L_DESK_RETURN_M = 0.72, 0.46


def _tucked_chair(zone: Bounds, k: float, name: str, chair: Part, desk_b: Bounds) -> list:
    """The desk chair at its own depth, facing the desk; it slides under the desk when the zone is shallower."""
    depth = min(chair.width * k, desk_b.y1 - zone.y0)
    y0 = max(zone.y0, desk_b.y0 - depth)
    seat = _span(zone, chair.length * k)._replace(y0=y0, y1=y0 + depth)
    return _flip_y(_build_part(chair, seat, k, name), seat)


def _l_desk(b: Bounds, k: float, name: str, desk: Part, chair) -> list:
    """An L-desk (top along +y plus a return down +x) with its chair in the notch."""
    top_d, ret = min(_L_DESK_TOP_M * k, (b.y1 - b.y0) / 2), min(_L_DESK_RETURN_M * k, (b.x1 - b.x0) / 3)
    band = b._replace(y0=b.y1 - top_d)
    pieces = _build_part(desk, band, k, name) + _build_part(desk, Bounds(b.x1 - ret, b.x1, b.y0, band.y0), k, name)
    return pieces + (_tucked_chair(Bounds(b.x0, b.x1 - ret, b.y0, band.y0), k, name, chair, band) if chair else [])


def _desk_assembly(b: Bounds, k: float, name: str, desk: Part, rest: list) -> list:
    """Desk with its chair tucked in front; guest chairs beyond it when the box (nearly) has room."""
    chair = next((p for p in rest if p.code != "C_G"), None)
    guests = [p for p in rest if p.code == "C_G"]
    depth = b.y1 - b.y0
    if desk.width * k >= _GUEST_FIT * depth:
        return _l_desk(b, k, name, desk, chair)
    desk_d, chair_d = min(desk.width * k, depth), (chair.width * k if chair else 0.0)
    guest_d = max((g.width * k for g in guests), default=0.0)
    with_guests = bool(guests) and depth >= _GUEST_FIT * (desk_d + chair_d + guest_d)
    guest_d = min(guest_d, depth - desk_d - chair_d / 2) if with_guests else 0.0
    desk_b = _span(b, desk.length * k)._replace(y0=b.y1 - guest_d - desk_d, y1=b.y1 - guest_d)
    pieces = _build_part(desk, desk_b, k, name) + (_tucked_chair(b, k, name, chair, desk_b) if chair else [])
    if with_guests:
        slot = (b.x1 - b.x0) / len(guests)
        for i, g in enumerate(guests):
            cx, half = b.x0 + slot * (i + 0.5), min(g.length * k, slot) / 2
            pieces += _build_part(g, Bounds(cx - half, cx + half, b.y1 - guest_d, b.y1), k, name)
    return pieces


def _kitchen_assembly(b: Bounds, k: float, name: str, counter: Part, rest: list) -> list:
    """Counter run along +y with the fridge at the -x end and the sink set in near the +x end."""
    fridge = next((p for p in rest if p.code == "K_R"), None)
    sink = next((p for p in rest if p.code == "K_S"), None)
    depth = min(counter.width * k, b.y1 - b.y0)
    run, pieces = Bounds(b.x0, b.x1, b.y1 - depth, b.y1), []
    if fridge:
        fw = min(fridge.length * k, (b.x1 - b.x0) / 2)
        pieces += _build_part(fridge, Bounds(b.x0, b.x0 + fw, b.y1 - min(fridge.width * k, b.y1 - b.y0), b.y1), k, name)
        run = run._replace(x0=b.x0 + fw)
    pieces += _build_part(counter, run, k, name)
    if sink:
        sw, sd = min(sink.length * k, (run.x1 - run.x0) / 2), min(sink.width * k, depth)
        x1 = max(run.x1 - _SINK_MARGIN_M * k, run.x0 + sw)
        cy = (run.y0 + run.y1) / 2
        pieces += _build_part(sink, Bounds(x1 - sw, x1, cy - sd / 2, cy + sd / 2), k, name)
    return pieces


def _assemble(b: Bounds, k: float, name: str, parts: list) -> list:
    """Pieces of a bom item: its primary part, plus chairs/fittings laid out around it."""
    primary = min(parts, key=lambda part: _rank(part.code))
    rest = [part for part in parts if part is not primary]
    if primary.code in _DESKS and rest:
        return _desk_assembly(b, k, name, primary, rest)
    if primary.code == "K_C" and rest:
        return _kitchen_assembly(b, k, name, primary, rest)
    return _build_part(primary, b, k, name)


# ── seating ─────────────────────────────────────────────────────────────────

ARM_Z = (0.62, 0.65)          # chair armrest pads
SPOKE_Z = (0.06, 0.09)        # five-star base spokes
CASTOR_Z = (0.0, 0.06)
FOOTREST_Z = (0.28, 0.30)
SOFA_SEAT_Z = (0.38, 0.46)    # sofa seat cushions
SOFA_ARM_Z = (0.08, 0.62)     # sofa arms (full height block from the plinth)
_CHAIR_FABRIC = {"C_C": FABRIC_GREY, "C_K": FABRIC_SAND, "C_G": FABRIC_GREY, "C_W": FABRIC_CHARCOAL,
                 "C_E": FABRIC_CHARCOAL}
_BACK_TOP = {"C_C": 0.88, "C_K": 0.86, "C_G": 0.88, "C_W": 0.95, "C_E": 1.15}
_SEAT_H = {"C_C": 0.46, "C_K": 0.46, "C_G": 0.46, "C_W": 0.47, "C_E": 0.47}


def _disc(cx: float, cy: float, r: float, n: int = 12) -> list:
    """A CCW n-gon of radius r around (cx, cy)."""
    return _ngon(Bounds(cx - r, cx + r, cy - r, cy + r), n)


def _m(v: float, k: float, cap: float) -> float:
    """v metres in model units, never more than cap (small footprints)."""
    return min(v * k, cap)


def _has_arms(code: str, name: str) -> bool:
    """Office chairs always have arms; others when the name says #arms (and not #no_arms)."""
    return code in ("C_W", "C_E") or ("#arms" in name and "no_arms" not in name)


def _chair_seat(b: Bounds, k: float, code: str) -> tuple:
    """(seat bounds, pieces) for a chair's shell, cushion and slanted back."""
    seat_h, fabric = _SEAT_H[code], _CHAIR_FABRIC[code]
    w, d = b.x1 - b.x0, b.y1 - b.y0
    seat = _inset(b, _m(0.02, k, w / 10))
    back_d, tilt = _m(0.05, k, d / 6), _m(0.05, k, d / 6)
    cushion = seat._replace(y1=seat.y1 - back_d - tilt)
    back = Bounds(seat.x0 + _m(0.01, k, w / 20), seat.x1 - _m(0.01, k, w / 20), seat.y1 - back_d - tilt, seat.y1 - tilt)
    shell = PLASTIC_BLACK if code in ("C_W", "C_E") else (OAK_LIGHT if code == "C_K" else PLASTIC_BLACK)
    return seat, [(shell, _round_rect(cushion, _m(0.03, k, w / 4)), seat_h - 0.08, seat_h - 0.06),
                  (fabric, _round_rect(cushion, _m(0.04, k, w / 4)), seat_h - 0.06, seat_h),
                  (fabric, _round_rect(back, _m(0.02, k, w / 8)), seat_h, _BACK_TOP[code], (0.0, tilt))]


def _chair_arms(seat: Bounds, k: float, code: str) -> list:
    """Two armrest pads on posts along the seat's sides."""
    w, d = seat.x1 - seat.x0, seat.y1 - seat.y0
    aw = _m(0.04, k, w / 8)
    y0, y1 = seat.y0 + d * 0.25, seat.y1 - d * 0.15
    out = []
    for x0 in (seat.x0, seat.x1 - aw):
        pad = Bounds(x0, x0 + aw, y0, y1)
        post = Bounds(x0, x0 + aw, (y0 + y1) / 2 - aw / 2, (y0 + y1) / 2 + aw / 2)
        out += [(PLASTIC_BLACK_SMOOTH, _round_rect(pad, aw / 2), *ARM_Z), (METAL, _rect(*post), _SEAT_H[code], ARM_Z[0])]
    return out


def _star_base(seat: Bounds, k: float, code: str) -> list:
    """Gas column, five spokes and five castors under an office chair."""
    cx, cy = (seat.x0 + seat.x1) / 2, (seat.y0 + seat.y1) / 2
    reach = min(seat.x1 - seat.x0, seat.y1 - seat.y0) / 2 - _m(0.025, k, (seat.x1 - seat.x0) / 10)
    col, spoke_w, castor = _m(0.03, k, reach / 4), _m(0.03, k, reach / 4), _m(0.025, k, reach / 5)
    out = [(METAL_SMOOTH, _disc(cx, cy, col, 16), SPOKE_Z[1], _SEAT_H[code] - 0.08)]
    for i in range(5):
        a = math.pi / 2 + 2 * math.pi * i / 5
        out.append((PLASTIC_BLACK, _bar_ring(cx, cy, reach, spoke_w, a), *SPOKE_Z))
        out.append((PLASTIC_BLACK_SMOOTH, _disc(cx + (reach - castor) * math.cos(a), cy + (reach - castor) * math.sin(a),
                                                castor, 10), *CASTOR_Z))
    return out


def _four_legs(seat: Bounds, k: float, top: float, mat: Mat) -> list:
    """Four round legs in the seat's corners."""
    r = _m(0.015, k, min(seat.x1 - seat.x0, seat.y1 - seat.y0) / 8)
    inset = _inset(seat, r * 1.5)
    return [(mat, _disc(x, y, r, 10), 0.0, top) for x in (inset.x0, inset.x1) for y in (inset.y0, inset.y1)]


def _chair_part(b: Bounds, k: float, name: str, part) -> list:
    """Conference / kitchen / guest / task / executive chair facing local -y."""
    seat, pieces = _chair_seat(b, k, part.code)
    if _has_arms(part.code, name):
        pieces += _chair_arms(seat, k, part.code)
    if part.code in ("C_W", "C_E"):
        return pieces + _star_base(seat, k, part.code)
    legs = OAK_LIGHT if part.code == "C_K" else METAL_SMOOTH
    return pieces + _four_legs(seat._replace(y1=seat.y1 - _m(0.05, k, (seat.y1 - seat.y0) / 6)), k,
                               _SEAT_H[part.code] - 0.08, legs)


def _bar_stool(b: Bounds, k: float, name: str, part) -> list:
    """Round upholstered seat on a column with a footrest and a round base."""
    cx, cy = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2
    r = min(b.x1 - b.x0, b.y1 - b.y0) / 2
    return [(FABRIC_CHARCOAL, _disc(cx, cy, r * 0.8, 24), 0.72, 0.75),
            (METAL_SMOOTH, _disc(cx, cy, r * 0.12, 12), 0.02, 0.72),
            (METAL_SMOOTH, _disc(cx, cy, r * 0.65, 24), *FOOTREST_Z),
            (METAL_SMOOTH, _disc(cx, cy, r * 0.75, 24), 0.0, 0.02)]


def _seat_count(name: str, width_m: float) -> int:
    """Seat cushions: from SOFA_<n>_SEAT, 1 for armchairs, else one per ~0.65 m."""
    if m := re.search(r"sofa_(\d)_seat", name):
        return int(m.group(1))
    return 1 if "armchair" in name else max(1, round(width_m / 0.65))


def _sofa_part(b: Bounds, k: float, name: str, part) -> list:
    """Sofa / armchair: legs, base, two rounded arms, a back and one cushion per seat (back at +y)."""
    fabric = FABRIC_SAND if "armchair" in name else FABRIC_TEAL
    w, d = b.x1 - b.x0, b.y1 - b.y0
    arm, back = _m(0.16, k, w / 6), _m(0.18, k, d / 3)
    body = _inset(b, _m(0.01, k, w / 20))
    pieces = _four_legs(_inset(b, _m(0.05, k, w / 8)), k, 0.08, PLASTIC_BLACK)
    pieces += [(fabric, _round_rect(body._replace(x0=b.x0 + arm, x1=b.x1 - arm), _m(0.02, k, w / 8)), 0.08, SOFA_SEAT_Z[0]),
               (fabric, _round_rect(Bounds(b.x0 + arm, b.x1 - arm, b.y1 - back, b.y1), _m(0.06, k, back / 2)), 0.08, 0.82)]
    for x0, x1 in ((b.x0, b.x0 + arm), (b.x1 - arm, b.x1)):
        pieces.append((fabric, _round_rect(Bounds(x0, x1, b.y0, b.y1), arm / 2), *SOFA_ARM_Z))
    n = _seat_count(name, part.length)
    slot = (b.x1 - b.x0 - 2 * arm) / n
    gap = _m(0.01, k, slot / 10)
    for i in range(n):
        cell = Bounds(b.x0 + arm + slot * i + gap, b.x0 + arm + slot * (i + 1) - gap, b.y0 + gap, b.y1 - back - gap)
        pieces.append((fabric, _round_rect(cell, _m(0.05, k, slot / 4)), *SOFA_SEAT_Z))
    return pieces


def _bench_part(b: Bounds, k: float, name: str, part) -> list:
    """Upholstered bench block on short legs."""
    w = b.x1 - b.x0
    return (_four_legs(_inset(b, _m(0.04, k, w / 8)), k, 0.08, PLASTIC_BLACK)
            + [(FABRIC_GREY, _round_rect(_inset(b, _m(0.01, k, w / 20)), _m(0.04, k, w / 6)), 0.08, 0.45)])


def _booth_part(b: Bounds, k: float, name: str, part) -> list:
    """Dining booth: two benches with tall backs facing a table between them."""
    d, w = b.y1 - b.y0, b.x1 - b.x0
    bench, back = min(0.45 * k, d / 3), _m(0.1, k, d / 10)
    table = _inset(Bounds(b.x0, b.x1, b.y0 + bench, b.y1 - bench), _m(0.05, k, w / 8))
    pieces = [(LAMINATE, _round_rect(table, _m(0.02, k, w / 8)), 0.715, 0.74),
              (METAL_SMOOTH, _disc((table.x0 + table.x1) / 2, (table.y0 + table.y1) / 2, _m(0.04, k, w / 8), 12), 0.0, 0.715)]
    for y0, y1, by0, by1 in ((b.y0, b.y0 + bench, b.y0, b.y0 + back), (b.y1 - bench, b.y1, b.y1 - back, b.y1)):
        pieces += [(FABRIC_TEAL, _round_rect(Bounds(b.x0, b.x1, y0, y1), _m(0.03, k, w / 8)), 0.0, 0.45),
                   (FABRIC_TEAL, _round_rect(Bounds(b.x0, b.x1, by0, by1), back / 2), 0.45, 1.1)]
    return pieces


_PART_BUILDERS.update({"C_C": _chair_part, "C_K": _chair_part, "C_G": _chair_part, "C_W": _chair_part,
                       "C_E": _chair_part, "C_B": _bar_stool, "L_S": _sofa_part, "L_B": _bench_part,
                       "K_DB": _booth_part})


# ── tables, desks, storage, kitchen, accessories ────────────────────────────

DESK_H, TOP_T = 0.74, 0.025
STORAGE_BODY = _mat("furniture", "#ecebe7", roughness=0.55, finish="laminate")
PRINTER = _mat("furniture", "#d9dbde", roughness=0.5, finish="plastic")
_TABLE_H = {"T_C": 0.74, "T_DT": 0.74, "T_CF": 0.42, "T_BR": 1.05, "CO_H": 0.74}
_TABLE_TOP = {"T_C": OAK_LIGHT, "T_DT": OAK_LIGHT, "T_CF": OAK_LIGHT, "T_BR": LAMINATE, "CO_H": LAMINATE}


def _monitor(b: Bounds, k: float) -> list:
    """A screen on a stand near the back of a desk, and a keyboard in front of it."""
    w, d = b.x1 - b.x0, b.y1 - b.y0
    cx = (b.x0 + b.x1) / 2
    sw, st = _m(0.55, k, w * 0.6) / 2, _m(0.02, k, d / 20)
    ys = b.y1 - _m(0.15, k, d / 4)
    col = _m(0.02, k, w / 20)
    kw, kd, ky = _m(0.21, k, w * 0.3), _m(0.065, k, d / 8), b.y0 + d * 0.35
    return [(SCREEN, _rect(cx - sw, cx + sw, ys - st, ys), 0.9, 1.22),
            (SCREEN, _rect(cx - col, cx + col, ys, ys + 2 * col), DESK_H, 0.9),
            (PLASTIC_BLACK, _rect(cx - 3 * col, cx + 3 * col, ys - col, ys + 3 * col), DESK_H, DESK_H + 0.01),
            (PLASTIC_BLACK, _round_rect(Bounds(cx - kw, cx + kw, ky - kd, ky + kd), kd / 3), DESK_H, DESK_H + 0.02)]


def _reception(b: Bounds, k: float) -> list:
    """Reception desk: a tall counter on the visitor side (+y) with the work surface toward the chair (-y)."""
    w, d = b.x1 - b.x0, b.y1 - b.y0
    front, end = _m(0.3, k, d / 3), _m(0.025, k, w / 10)
    counter = b._replace(y0=b.y1 - front)
    return [(LAMINATE, _rect(*counter), 0.0, 1.02),
            (OAK_LIGHT, _round_rect(counter, _m(0.01, k, w / 10)), 1.02, 1.05),
            (LAMINATE, _rect(b.x0, b.x1, b.y0, counter.y0), DESK_H - TOP_T, DESK_H),
            (LAMINATE, _rect(b.x0, b.x0 + end, b.y0, counter.y0), 0.0, DESK_H - TOP_T),
            (LAMINATE, _rect(b.x1 - end, b.x1, b.y0, counter.y0), 0.0, DESK_H - TOP_T)]


def _desk_part(b: Bounds, k: float, name: str, part) -> list:
    """Desk: laminate top, metal frame (workstation) or panel ends, modesty panel; workstations get a monitor."""
    if part.code == "T_R":
        return _reception(b, k)
    w, d = b.x1 - b.x0, b.y1 - b.y0
    leg_t, inset, panel_t = _m(0.05, k, w / 8), _m(0.03, k, d / 8), _m(0.018, k, d / 10)
    leg_mat = METAL if part.code == "T_WS" else LAMINATE
    pieces = [(LAMINATE, _round_rect(b, _m(0.01, k, w / 10)), DESK_H - TOP_T, DESK_H)]
    pieces += [(leg_mat, _rect(x0, x0 + leg_t, b.y0 + inset, b.y1 - inset), 0.0, DESK_H - TOP_T)
               for x0 in (b.x0 + inset, b.x1 - inset - leg_t)]
    pieces.append((leg_mat, _rect(b.x0 + inset + leg_t, b.x1 - inset - leg_t, b.y1 - inset - panel_t, b.y1 - inset),
                   0.3, DESK_H - TOP_T))
    return pieces + (_monitor(b, k) if part.code == "T_WS" else [])


def _cut_triangle(b: Bounds, k: float) -> list:
    """A triangle in b (base at -y, apex at +y) with its three corners cut: a convex CCW hexagon."""
    a, bb, c = (b.x0, b.y0), (b.x1, b.y0), ((b.x0 + b.x1) / 2, b.y1)
    t = 0.18

    def towards(p, q):
        return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
    return [towards(a, bb), towards(bb, a), towards(bb, c), towards(c, bb), towards(c, a), towards(a, c)]


def _triangle_table(b: Bounds, k: float, part) -> list:
    """Collaboration table: a rounded triangle top on three legs."""
    h = _TABLE_H[part.code]
    ring = _cut_triangle(b, k)
    gx, gy = sum(x for x, _ in ring) / 6, sum(y for _, y in ring) / 6
    r = _m(0.025, k, (b.x1 - b.x0) / 20)
    corners = [(b.x0, b.y0), (b.x1, b.y0), ((b.x0 + b.x1) / 2, b.y1)]
    legs = [(METAL_SMOOTH, _disc(x + (gx - x) * 0.3, y + (gy - y) * 0.3, r, 10), 0.0, h - 0.03) for x, y in corners]
    return [(_TABLE_TOP[part.code], ring, h - 0.03, h)] + legs


def _table_part(b: Bounds, k: float, name: str, part) -> list:
    """Conference / dining / coffee / bar table: round on a pedestal, else rectangular on four legs."""
    if part.code == "CO_H":
        return _triangle_table(b, k, part)
    h, top_mat = _TABLE_H[part.code], _TABLE_TOP[part.code]
    w, d = b.x1 - b.x0, b.y1 - b.y0
    if "round" in name or "circle" in name:
        cx, cy, r = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, min(w, d) / 2
        return [(top_mat, _disc(cx, cy, r, 32), h - 0.03, h), (METAL_SMOOTH, _disc(cx, cy, r * 0.12, 16), 0.02, h - 0.03),
                (METAL_SMOOTH, _disc(cx, cy, r * 0.45, 24), 0.0, 0.02)]
    r = _m(0.025, k, min(w, d) / 10)
    legs = _inset(b, _m(0.06, k, min(w, d) / 6))
    return [(top_mat, _round_rect(b, _m(0.01, k, min(w, d) / 10)), h - 0.03, h)] + [
        (METAL_SMOOTH, _disc(x, y, r, 10), 0.0, h - 0.03) for x in (legs.x0, legs.x1) for y in (legs.y0, legs.y1)]


def _fronts(b: Bounds, k: float, n: int, z0: float, z1: float, front_mat: Mat, handle_z: tuple) -> list:
    """n door fronts on b's -y face with 3 mm gaps, each with a bar handle."""
    w, d = b.x1 - b.x0, b.y1 - b.y0
    gap, ft, hd = _m(0.003, k, w / 50), _m(0.018, k, d / 10), _m(0.02, k, d / 10)
    out = []
    for i in range(n):
        x0, x1 = b.x0 + w * i / n + gap, b.x0 + w * (i + 1) / n - gap
        cx, hw = (x0 + x1) / 2, min(_m(0.06, k, w / 8), (x1 - x0) / 3)
        out += [(front_mat, _rect(x0, x1, b.y0 + hd, b.y0 + hd + ft), z0, z1),
                (METAL, _rect(cx - hw, cx + hw, b.y0, b.y0 + hd), *handle_z)]
    return out


def _storage_part(b: Bounds, k: float, name: str, part) -> list:
    """Storage: recessed plinth, carcass and oak door fronts with bar handles (front at -y)."""
    h = 1.8 if part.code == "S_HS" else 0.8
    w, d = b.x1 - b.x0, b.y1 - b.y0
    front = _m(0.018, k, d / 10) + _m(0.02, k, d / 10)
    carcass = b._replace(y0=b.y0 + front)
    n = max(1, round(part.length / 0.5))
    i = _m(0.02, k, min(w, d - front) / 6)
    handle = (h - 0.1, h - 0.08) if h < 1.0 else (0.9, 1.1)
    return ([(PLASTIC_BLACK, _rect(b.x0 + i, b.x1 - i, carcass.y0 + i, b.y1 - i), 0.0, 0.08),
             (STORAGE_BODY, _rect(*carcass), 0.08, h)]
            + _fronts(b, k, n, 0.1, h - 0.01, OAK_LIGHT, handle))


def _counter_part(b: Bounds, k: float, name: str, part) -> list:
    """Kitchen run: recessed plinth, base units with fronts, 40 mm worktop at 0.9 m (front at -y)."""
    w, d = b.x1 - b.x0, b.y1 - b.y0
    front = _m(0.018, k, d / 10) + _m(0.02, k, d / 10)
    i = _m(0.05, k, min(w, d) / 6)
    n = max(1, round(part.length / 0.6))
    return ([(PLASTIC_BLACK, _rect(b.x0, b.x1, b.y0 + front + i, b.y1), 0.0, 0.1),
             (LAMINATE, _rect(b.x0, b.x1, b.y0 + front, b.y1), 0.1, 0.86),
             (OAK_LIGHT, _rect(*b), 0.86, 0.9)]
            + _fronts(b._replace(y1=b.y0 + front), k, n, 0.12, 0.84, LAMINATE, (0.76, 0.78)))


def _sink_part(b: Bounds, k: float, name: str, part) -> list:
    """Sink: a stainless basin set into the worktop, with a tap at the back."""
    w, d = b.x1 - b.x0, b.y1 - b.y0
    cx = (b.x0 + b.x1) / 2
    tap, reach = _m(0.015, k, w / 10), _m(0.15, k, d / 3)
    ty = b.y1 - _m(0.05, k, d / 6)
    return [(STAINLESS, _rect(*_inset(b, _m(0.02, k, min(w, d) / 6))), 0.86, 0.905),
            (METAL_SMOOTH, _disc(cx, ty, tap, 12), 0.9, 1.15),
            (METAL_SMOOTH, _rect(cx - tap / 2, cx + tap / 2, ty - reach, ty), 1.12, 1.15)]


def _fridge_part(b: Bounds, k: float, name: str, part) -> list:
    """Tall fridge: white body, door split and two vertical handles (front at -y)."""
    w, d = b.x1 - b.x0, b.y1 - b.y0
    hd = _m(0.03, k, d / 10)
    body = b._replace(y0=b.y0 + hd)
    hx = b.x1 - _m(0.06, k, w / 5)
    bar = _m(0.012, k, w / 20)
    return [(FRIDGE, _round_rect(body, _m(0.01, k, w / 10)), 0.0, 1.8),
            (SCREEN, _rect(body.x0, body.x1, body.y0 - _m(0.002, k, hd / 4), body.y0), 1.1, 1.11),
            (METAL, _rect(hx - bar, hx + bar, b.y0, b.y0 + hd), 1.2, 1.6),
            (METAL, _rect(hx - bar, hx + bar, b.y0, b.y0 + hd), 0.6, 1.0)]


def _plant_part(b: Bounds, k: float, name: str, part) -> list:
    """Potted plant: terracotta pot with a rim and three overlapping foliage masses."""
    cx, cy, r = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, min(b.x1 - b.x0, b.y1 - b.y0) / 2
    return [(TERRACOTTA, _disc(cx, cy, r * 0.7, 16), 0.0, 0.38), (TERRACOTTA, _disc(cx, cy, r * 0.8, 16), 0.34, 0.4),
            (FOLIAGE, _disc(cx, cy, r * 0.95, 16), 0.4, 0.85),
            (FOLIAGE_LIGHT, _disc(cx + r * 0.15, cy, r * 0.75, 16), 0.7, 1.1),
            (FOLIAGE, _disc(cx - r * 0.2, cy + r * 0.1, r * 0.55, 16), 0.95, 1.3)]


def _printer_part(b: Bounds, k: float, name: str, part) -> list:
    """Printer on a low cabinet with an output tray."""
    w, d = b.x1 - b.x0, b.y1 - b.y0
    return [(LAMINATE, _rect(*b), 0.0, 0.5),
            (PRINTER, _round_rect(_inset(b, _m(0.05, k, min(w, d) / 6)), _m(0.02, k, w / 10)), 0.5, 0.95),
            (SCREEN, _rect(*_inset(b, _m(0.12, k, min(w, d) / 4))), 0.95, 0.97)]


_PART_BUILDERS.update({"T_WS": _desk_part, "T_D": _desk_part, "T_R": _desk_part, "T_C": _table_part,
                       "T_CF": _table_part, "T_DT": _table_part, "T_BR": _table_part, "CO_H": _table_part,
                       "S_LS": _storage_part, "S_HS": _storage_part, "K_C": _counter_part, "K_S": _sink_part,
                       "K_R": _fridge_part, "V_P": _plant_part, "PH_PR": _printer_part})

# keyword fallback (no usable bom): name keywords -> (kind, bom code built with the item's own box size)
_FURNITURE_RULES = (
    (("sofa", "lounge", "armchair"), "sofa", "L_S"),
    (("stool",), "chair", "C_B"),
    (("chair", "seat"), "chair", "C_C"),
    (("phone", "booth"), "booth", None),
    (("plant",), "plant", "V_P"),
    (("storage", "cabinet", "locker"), "storage", "S_LS"),
    (("table",), "table", "T_C"),
    (("desk", "workstation", "unit_fr_os", "bench"), "desk", "T_WS"),
    (("kitchen", "counter"), "kitchen", "K_C"),
)


def _refine(code: str, name: str) -> str:
    """Keyword code refined by name: coffee tables, high storage."""
    if code == "T_C" and "coffee" in name:
        return "T_CF"
    if code == "S_LS" and re.search(r"_h(?:[_#]|$)", name):
        return "S_HS"
    return code


def _keyword_build(code: str):
    """A builder that makes a detailed model of `code` sized to the item's own box."""
    def build(b: Bounds, k: float, name: str, bom: str) -> list:
        real = _refine(code, name)
        return _PART_BUILDERS[real](b, k, name, Part(real, (b.x1 - b.x0) / k, (b.y1 - b.y0) / k))
    return build


def classify_furniture(name: str, bom: str = "") -> tuple:
    """(kind, builder) for a component: its bom primary part when known, else keyword rules, else a box."""
    if parts := _known_parts(bom):
        primary = min(parts, key=lambda part: _rank(part.code))
        return primary.code, lambda b, k, nm, _bom: _assemble(b, k, nm, parts)
    lowered = name.lower()
    for keys, kind, code in _FURNITURE_RULES:
        if any(key in lowered for key in keys):
            return kind, (_keyword_build(code) if code else _phone_booth)
    return "fallback", _fallback


def _flag(value, default: bool) -> bool:
    """A component flag that may arrive as a bool or as its string form."""
    return default if value is None else str(value).lower() == "true"


def _affine(matrix) -> np.ndarray:
    """A 3×3 [[a, b, tx], [c, d, ty], [0, 0, 1]] list as a float matrix."""
    return np.vstack([np.asarray(matrix, dtype=float)[:2, :3], [0.0, 0.0, 1.0]])


def _canonical_box(comp: dict) -> Bounds:
    """
    The component's footprint in its own unmirrored frame. Real exports store
    geom_box with original_matrix3d (the in-group offset/mirror) already
    applied, while the placement is group matrix @ original_matrix3d — so undoing
    original_matrix3d first puts the box back where _placement expects it, with
    chair backs and desk tops on the local +y side.
    """
    inv = np.linalg.inv(_affine(comp.get("original_matrix3d") or np.eye(3)))
    x0, y0, x1, y1 = affine_transform(wkt.loads(comp["geom_box"]), [*inv[0, :2], *inv[1, :2], inv[0, 2], inv[1, 2]]).bounds
    return Bounds(x0, x1, y0, y1)


def _placement(comp: dict) -> np.ndarray:
    """
    Where the component's canonical box sits in the plan: matrix @ original_matrix3d. Real exports
    can carry a stale matrix3d (the first placement of a stencil reused in other rooms), so it is
    only used when `matrix` is missing.
    """
    if comp.get("matrix") is None:
        return _affine(comp["matrix3d"])
    return _affine(comp["matrix"]) @ _affine(comp.get("original_matrix3d") or np.eye(3))


def _component(comp: dict, k: float) -> tuple:
    """(kind, faces) for one stencil component; ("hidden", []) when removed or not shown."""
    if _flag(comp.get("is_remove"), False) or not _flag(comp.get("show"), True):
        return "hidden", []
    full = str(comp.get("name") or "")
    bom = str(comp.get("bom_data") or "")
    m = _placement(comp)
    kind, build = classify_furniture(full.split("#")[0], bom)
    frame = tuple(float(v) for v in (m[0, 0], m[0, 1], m[1, 0], m[1, 1], m[0, 2], m[1, 2]))
    pieces = build(_canonical_box(comp), k, full.lower(), bom)
    return kind, [f for mat, ring, z0, z1, *shift in pieces for f in _framed(mat, frame, ring, z0, z1, *shift)]


# ── assembly ────────────────────────────────────────────────────────────────

def _safe(build, *args) -> list:
    """Run one element builder; an element that fails is skipped, never fatal."""
    try:
        return build(*args)
    except Exception:  # noqa: BLE001 — one bad element must not abort the scene
        log.debug("qbiq scene: skipping an element in %s", build.__name__, exc_info=True)
        return []


def _furniture(rooms: list, k: float) -> tuple:
    """All furniture faces plus a Counter of furniture kinds built."""
    kinds, faces = Counter(), []
    for comp in (c for _, _, comps in rooms for c in comps or [] if isinstance(c, dict)):
        kind, built = _safe(_component, comp, k) or ("failed", [])
        kinds[kind] += 1
        faces += built
    return faces, kinds


def _merge(faces: list, u: float) -> list:
    """Merge faces into one mesh per material, scaling x/y to metres; stop at the vertex cap."""
    groups, total, dropped = {}, 0, 0
    for mat, pts, *tag in faces:
        if total + len(pts) > _MAX_VERTS:
            dropped += 1
            continue
        verts, idx, shared = groups.setdefault(mat, ([], [], {}))
        ids = [_vertex(verts, shared if mat.smooth and tag == ["side"] else None, (x * u, y * u, z))
               for x, y, z in pts]
        idx.extend(i for j in range(1, len(ids) - 1) for i in (ids[0], ids[j], ids[j + 1]))
        total += len(pts)
    if dropped:
        log.warning("qbiq scene: vertex cap %d reached — dropped %d faces", _MAX_VERTS, dropped)
    return [{"type": m.type, "verts": v, "faces": f, "color": m.color, "opacity": m.opacity,
             "roughness": m.roughness, "metalness": m.metalness, "smooth": m.smooth, "finish": m.finish} for m, (v, f, _) in groups.items()]


def _vertex(verts: list, shared: dict | None, p: tuple) -> int:
    """Index of point p in verts; smooth side faces reuse an existing vertex at the same rounded position."""
    key = tuple(round(c, 4) for c in p)
    if shared is not None and key in shared:
        return shared[key]
    verts.extend(key)
    index = len(verts) // 3 - 1
    if shared is not None:
        shared[key] = index
    return index


def build_design_scene(inp: SceneInputs, units_to_metres: float) -> list[dict]:
    """The full merged 3D scene for a qbiq design, in priority order (furniture is dropped first at the cap)."""
    k = 1.0 / units_to_metres
    facade = [w for w in inp.windows if math.dist(*w) > _MIN_LEN and not _on_any_wall(w, inp.exterior)]
    faces = [f for g in inp.plates for f in _safe(_solid, PLATE, g, 0.0, 0.02)]
    faces += [f for rings, space_type, _ in inp.rooms for f in _safe(_room_slab, rings, space_type)]
    faces += [f for seg in inp.exterior for f in _safe(_exterior_wall, seg, inp.windows, k)]
    faces += [f for seg in facade for f in _safe(_facade_window, seg, k)]
    faces += [f for seg in _safe(_partition_segments, inp) for f in _safe(_partition, seg, inp.doors, k)]
    faces += [f for ring in inp.columns for f in _safe(_column, ring)]
    faces += [f for core in inp.cores for f in _safe(_core, core, k)]
    walls = _safe(_wall_area, _safe(_partition_segments, inp), inp.exterior, k) or None
    faces += _safe(_ceiling, inp.plates) + _safe(_light_panels, inp.plates, inp.cores, k, walls)
    furniture, kinds = _furniture(inp.rooms, k)
    meshes = _merge(faces + furniture, units_to_metres)
    per_type = Counter(m["type"] for m in meshes)
    log.info("qbiq scene: %d meshes, %d verts; meshes by type %s; furniture %s",
             len(meshes), sum(len(m["verts"]) // 3 for m in meshes), dict(per_type), dict(kinds))
    return meshes
