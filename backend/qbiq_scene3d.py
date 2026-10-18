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
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

log = logging.getLogger(__name__)

Mat = namedtuple("Mat", "type color opacity roughness metalness smooth", defaults=(False,))
Bounds = namedtuple("Bounds", "x0 x1 y0 y1")


def _mat(kind: str, color: str, opacity: float = 1.0, roughness: float = 0.85, metalness: float = 0.0,
         smooth: bool = False) -> Mat:
    """A material key; faces with equal keys are merged into one mesh (smooth ones share side vertices)."""
    return Mat(kind, color, opacity, roughness, metalness, smooth)


PLATE = _mat("floor", "#e9e7e2", roughness=0.9)
WALL = _mat("wall", "#f4f4f2", roughness=0.9)
WINDOW = _mat("window", "#a9c7d6", 0.35, 0.05)
GLASS = _mat("glass", "#bcd6e0", 0.28, 0.05)
FRAME = _mat("frame", "#3a3f45", roughness=0.4, metalness=0.6)
TRIM = _mat("frame", "#f4f4f2", roughness=0.9)
COLUMN = _mat("column", "#f2f2f0", roughness=0.9)
DESK_TOP = _mat("furniture", "#f5f5f3", roughness=0.6)
DARK = _mat("furniture", "#4a4f55", roughness=0.5, metalness=0.3)
OAK = _mat("furniture", "#b98a5e", roughness=0.6)
SEAT = _mat("furniture", "#2f3338", roughness=0.8)
STORAGE = _mat("furniture", "#d8c3a0", roughness=0.7)
SOFA = _mat("furniture", "#4a6fd1", roughness=0.9)
BOOTH = _mat("furniture", "#e2e5ea", roughness=0.7)
PLANT = _mat("furniture", "#5f8f5a", roughness=0.9)
NEUTRAL = _mat("furniture", "#c9c6c0", roughness=0.8)

FABRIC_CHARCOAL = _mat("furniture", "#3b3f46", roughness=0.95, smooth=True)
FABRIC_GREY = _mat("furniture", "#8a8f96", roughness=0.95, smooth=True)
FABRIC_SAND = _mat("furniture", "#c9b79c", roughness=0.95, smooth=True)
FABRIC_TEAL = _mat("furniture", "#5b8a8c", roughness=0.95, smooth=True)
OAK_LIGHT = _mat("furniture", "#c49a6c", roughness=0.6)
LAMINATE = _mat("furniture", "#f3f3f1", roughness=0.55)
METAL = _mat("furniture", "#b8bcc2", roughness=0.35, metalness=0.7)
METAL_SMOOTH = _mat("furniture", "#b8bcc2", roughness=0.35, metalness=0.7, smooth=True)
PLASTIC_BLACK = _mat("furniture", "#25282c", roughness=0.5)
PLASTIC_BLACK_SMOOTH = _mat("furniture", "#25282c", roughness=0.5, smooth=True)
STAINLESS = _mat("furniture", "#c9cdd2", roughness=0.25, metalness=0.8)
FRIDGE = _mat("furniture", "#eef0f2", roughness=0.4)
FOLIAGE = _mat("furniture", "#4f7d4a", roughness=0.9, smooth=True)
FOLIAGE_LIGHT = _mat("furniture", "#5f9558", roughness=0.9, smooth=True)
TERRACOTTA = _mat("furniture", "#b5674d", roughness=0.85, smooth=True)
SCREEN = _mat("furniture", "#15171a", roughness=0.2, metalness=0.2)

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

def room_colour(space_type) -> str:
    """The floor tint for a room's space_type."""
    name = str(space_type or "").lower()
    return next((c for keys, c in _ROOM_COLOURS if any(key in name for key in keys)), _DEFAULT_ROOM_COLOUR)


def _room_slab(rings: list, space_type) -> list:
    """A 0.02–0.03 m slab per room ring, tinted by space type."""
    mat = _mat("floor", room_colour(space_type), roughness=0.85)
    return [f for ring in rings for f in _solid(mat, Polygon(ring), 0.02, 0.03)]


def _column(ring: list) -> list:
    """A column outline extruded floor to ceiling."""
    return _solid(COLUMN, Polygon(ring), 0.0, CEILING)


def _core(polyline: list, k: float) -> list:
    """A closed core outline becomes a solid block; an open one a run of solid walls."""
    if len(polyline) >= 4 and math.dist(polyline[0], polyline[-1]) < _MIN_LEN:
        return _solid(WALL, Polygon(polyline), 0.0, CEILING)
    return [f for seg in zip(polyline, polyline[1:]) for f in _exterior_wall(seg, [], k)]


# ── furniture ───────────────────────────────────────────────────────────────

def _inset(b: Bounds, d: float) -> Bounds:
    """Shrink bounds by d on every side, never past a quarter of either dimension."""
    d = min(d, (b.x1 - b.x0) / 4, (b.y1 - b.y0) / 4)
    return Bounds(b.x0 + d, b.x1 - d, b.y0 + d, b.y1 - d)


def _box(mat: Mat, b: Bounds, z0: float, z1: float) -> tuple:
    """A local furniture piece filling bounds b from z0 to z1."""
    return (mat, _rect(*b), z0, z1)


def _legs(b: Bounds, size: float, z1: float, mat: Mat = DARK) -> list:
    """Four square legs in the corners of b."""
    s = min(size, (b.x1 - b.x0) / 3, (b.y1 - b.y0) / 3)
    xs, ys = ((b.x0, b.x0 + s), (b.x1 - s, b.x1)), ((b.y0, b.y0 + s), (b.y1 - s, b.y1))
    return [_box(mat, Bounds(*x, *y), 0.0, z1) for x in xs for y in ys]


def _chair_pieces(b: Bounds, k: float, back_at_max: bool = True) -> list:
    """Seat on four thin legs with a back along the local max-y (or min-y) edge."""
    seat = _inset(b, 0.02 * k)
    depth = min(0.06 * k, (seat.y1 - seat.y0) / 4)
    back = seat._replace(y0=seat.y1 - depth) if back_at_max else seat._replace(y1=seat.y0 + depth)
    return [_box(SEAT, seat, 0.42, 0.47), _box(SEAT, back, 0.47, 0.85)] + _legs(_inset(seat, 0.02 * k), 0.03 * k, 0.42, SEAT)


def _chair(b: Bounds, k: float, name: str, bom: str) -> list:
    """Chairs face local -y: their back is the local +y edge."""
    return _chair_pieces(b, k)


def _desk_top(b: Bounds, k: float) -> list:
    """White desk top with two dark panel ends."""
    panel = min(0.03 * k, (b.x1 - b.x0) / 8)
    legs = _inset(b, 0.03 * k)
    return [_box(DESK_TOP, b, 0.72, 0.75), _box(DARK, legs._replace(x1=legs.x0 + panel), 0.0, 0.72),
            _box(DARK, legs._replace(x0=legs.x1 - panel), 0.0, 0.72)]


def _desk(b: Bounds, k: float, name: str, bom: str) -> list:
    """A desk; when the bom says the footprint also holds a task chair, the chair sits on the -y side."""
    match = re.search(r"T_WS_L\d+_W(\d+)", bom or "")
    depth = float(match.group(1)) / 100 * k if match else 0.0
    if not match or (b.y1 - b.y0) - depth < 0.3 * k:
        return _desk_top(b, k)
    top, seat_zone = b._replace(y0=b.y1 - depth), b._replace(y1=b.y1 - depth)
    cx, half = (b.x0 + b.x1) / 2, min(0.25 * k, (b.x1 - b.x0) / 2)
    return _desk_top(top, k) + _chair_pieces(seat_zone._replace(x0=cx - half, x1=cx + half), k, back_at_max=False)


def _ngon(b: Bounds, n: int = 12) -> list:
    """The inscribed circle of b as a CCW n-gon."""
    cx, cy, r = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, min(b.x1 - b.x0, b.y1 - b.y0) / 2
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _table(b: Bounds, k: float, name: str, bom: str) -> list:
    """Conference/dining at 0.75 m on legs, coffee at 0.43 m, round as a 12-gon on a pedestal."""
    z = 0.43 if "coffee" in name else 0.75
    if "round" in name:
        cx, cy, p = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, 0.05 * k
        return [(OAK, _ngon(b), z - 0.03, z), _box(DARK, Bounds(cx - p, cx + p, cy - p, cy + p), 0.0, z - 0.03),
                (DARK, _ngon(_inset(b, 0.25 * (b.x1 - b.x0))), 0.0, 0.02)]
    return [_box(OAK, b, z - 0.03, z)] + _legs(_inset(b, 0.05 * k), 0.06 * k, z - 0.03)


def _storage(b: Bounds, k: float, name: str, bom: str) -> list:
    """A light-oak cabinet on a dark plinth; _L is low, _H is high (the number is its width)."""
    tier = re.search(r"_([lh])(?:_|$)", name)
    height = {"l": 0.8, "h": 1.8}.get(tier.group(1) if tier else "", 1.1)
    return [_box(DARK, _inset(b, 0.02 * k), 0.0, 0.08), _box(STORAGE, b, 0.08, height)]


def _sofa(b: Bounds, k: float, name: str, bom: str) -> list:
    """Plinth, seat base, back along local +y and two arms."""
    back = min(0.2 * k, (b.y1 - b.y0) / 3)
    arm = min(0.2 * k, (b.x1 - b.x0) / 6)
    front = b._replace(y1=b.y1 - back)
    return [_box(DARK, _inset(b, 0.05 * k), 0.0, 0.2), _box(SOFA, b, 0.2, 0.42), _box(SOFA, b._replace(y0=b.y1 - back), 0.42, 0.8),
            _box(SOFA, front._replace(x1=b.x0 + arm), 0.42, 0.6), _box(SOFA, front._replace(x0=b.x1 - arm), 0.42, 0.6)]


def _kitchen(b: Bounds, k: float, name: str, bom: str) -> list:
    """A white counter with a dark worktop band."""
    return [_box(DESK_TOP, b, 0.0, 0.86), _box(DARK, b, 0.86, 0.9)]


def _booth(b: Bounds, k: float, name: str, bom: str) -> list:
    """A phone booth as a pale box."""
    return [_box(BOOTH, b, 0.0, 2.2)]


def _plant(b: Bounds, k: float, name: str, bom: str) -> list:
    """A plant as a green box."""
    return [_box(PLANT, b, 0.0, 1.2)]


def _fallback(b: Bounds, k: float, name: str, bom: str) -> list:
    """Anything unrecognised: a neutral box at desk height."""
    return [_box(NEUTRAL, b, 0.0, 0.75)]


_FURNITURE_RULES = (
    (("sofa", "lounge", "armchair"), "sofa", _sofa),
    (("chair", "seat"), "chair", _chair),
    (("phone", "booth"), "booth", _booth),
    (("plant",), "plant", _plant),
    (("storage", "cabinet", "locker"), "storage", _storage),
    (("table",), "table", _table),
    (("desk", "workstation", "unit_fr_os", "bench"), "desk", _desk),
    (("kitchen", "counter"), "kitchen", _kitchen),
)


def classify_furniture(name: str) -> tuple:
    """(kind, builder) for a component name; first matching keyword rule wins."""
    lowered = name.lower()
    return next(((kind, build) for keys, kind, build in _FURNITURE_RULES if any(key in lowered for key in keys)),
                ("fallback", _fallback))


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
    applied, while matrix3d = group matrix @ original_matrix3d — so undoing
    original_matrix3d first puts the box back where matrix3d expects it, with
    chair backs and desk tops on the local +y side.
    """
    inv = np.linalg.inv(_affine(comp.get("original_matrix3d") or np.eye(3)))
    x0, y0, x1, y1 = affine_transform(wkt.loads(comp["geom_box"]), [*inv[0, :2], *inv[1, :2], inv[0, 2], inv[1, 2]]).bounds
    return Bounds(x0, x1, y0, y1)


def _component(comp: dict, k: float) -> tuple:
    """(kind, faces) for one stencil component; ("hidden", []) when removed or not shown."""
    if _flag(comp.get("is_remove"), False) or not _flag(comp.get("show"), True):
        return "hidden", []
    name = str(comp.get("name") or "").split("#")[0]
    m = _affine(comp["matrix3d"])
    kind, build = classify_furniture(name)
    frame = tuple(float(v) for v in (m[0, 0], m[0, 1], m[1, 0], m[1, 1], m[0, 2], m[1, 2]))
    pieces = build(_canonical_box(comp), k, name.lower(), str(comp.get("bom_data") or ""))
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
             "roughness": m.roughness, "metalness": m.metalness, "smooth": m.smooth} for m, (v, f, _) in groups.items()]


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
    furniture, kinds = _furniture(inp.rooms, k)
    meshes = _merge(faces + furniture, units_to_metres)
    per_type = Counter(m["type"] for m in meshes)
    log.info("qbiq scene: %d meshes, %d verts; meshes by type %s; furniture %s",
             len(meshes), sum(len(m["verts"]) // 3 for m in meshes), dict(per_type), dict(kinds))
    return meshes
