"""Semantic model of a qbiq design JSON: corridor, rooms, stops, entrance."""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, replace

from shapely.affinity import scale
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import nearest_points, polylabel, unary_union

import qbiq_extractor as qe
from qbiq_scene3d import component_footprint

log = logging.getLogger(__name__)

WALKABLE_MIN_M2 = 8.0
INSIDE_STOP_MIN_M2 = 4.0
FURNITURE_CLEARANCE_M = 0.35
STOP_OFFSET_M = 0.6
FRONT_TOL_M = 0.5
DEFAULT_DWELL_S = 1.5
BACK_OF_HOUSE = frozenset({"Storage Room", "IT Room", "Print Hub", "Other"})
_DWELL_S = {"Reception": 3.0, "Executive Office": 3.0, "Conference": 3.0,
            "Open Space WorkStation": 3.0, "Kitchen": 2.0, "Comfort Zone": 2.0}


@dataclass(frozen=True)
class Stop:
    point: tuple
    look_at: tuple
    dwell_s: float
    warning: str | None = None


@dataclass(frozen=True)
class PlanRoom:
    id: str
    space_type: str | None
    subtype: str | None
    area_m2: float
    head_count: int | None
    assigned_hc: int | None
    department_id: int | None
    polygon: Polygon
    is_open: bool
    label_point: tuple
    stop: Stop


@dataclass(frozen=True)
class PlanModel:
    corridor: Polygon | MultiPolygon
    columns: list
    rooms: tuple
    entrance: tuple | None
    units_to_metres: float
    enscape_offset: tuple | None = None  # metres added to (x·u, y_display·u) to land on qbiq's Revit model
    walkable: Polygon | MultiPolygon | None = None  # corridor plus open areas clear of furniture; routes use this


# qbiq's Revit models put the floor outline's (max x, min y) corner 2 m / 1.7 m from the origin
# (qbiq video-path tool, nfp_to_enscape, metres mode).
ENSCAPE_SHIFT_M = (2.0, 1.7)


def enscape_offset(fill_bounds, u: float) -> tuple:
    """Metres to add to a display-space point scaled to metres so it sits on qbiq's Revit model in Enscape."""
    _, ymin, xmax, _ = fill_bounds
    return (-(xmax * u + ENSCAPE_SHIFT_M[0]), ymin * u - ENSCAPE_SHIFT_M[1])


def dwell_for(space_type: str | None) -> float:
    """Dwell seconds by room importance."""
    if space_type in _DWELL_S:
        return _DWELL_S[space_type]
    return 2.0 if (space_type or "").startswith("Office") else DEFAULT_DWELL_S


def _corridor(data: dict):
    """Union of the top-level circulation polygons, or None."""
    polys = [g for g in qe._wkt_many(data.get("circulation"))
             if g.geom_type in ("Polygon", "MultiPolygon")]
    corridor = unary_union(polys).buffer(0) if polys else None
    return None if corridor is None or corridor.is_empty else corridor


def _inner(corridor, offset: float):
    """Corridor shrunk by the stop offset, falling back to less shrink when too narrow."""
    for d in (offset, offset / 4):
        if not (inner := corridor.buffer(-d)).is_empty:
            return inner
    return corridor


def _into(inner, corridor, pt) -> tuple:
    """pt if already in the corridor, else the nearest point of the inner corridor."""
    p = Point(pt)
    if corridor.covers(p):
        return (p.x, p.y)
    q = nearest_points(inner, p)[0]
    return (q.x, q.y)


def _door_candidates(door: list, offset: float) -> list:
    """The two points `offset` away from a door's midpoint along its normals."""
    (x1, y1), (x2, y2) = door[0], door[-1]
    length = max(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, 1e-9)
    nx, ny = -(y2 - y1) / length, (x2 - x1) / length
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    return [(mx + nx * offset, my + ny * offset), (mx - nx * offset, my - ny * offset)]


def _door_stop(poly, doors, corridor, inner, offset, label, dwell) -> Stop:
    """Stop in the corridor in front of the door that best faces it."""
    cands = [c for door in doors for c in _door_candidates(door, offset)]
    best = min(
        ((corridor.distance(Point(c)), Point(c).distance(poly.centroid), c)
         for c in [c for c in cands if not poly.covers(Point(c))] or cands),
        key=lambda t: (round(t[0], 6), t[1]),
    )
    warning = "door does not open onto the corridor" if best[0] > offset / 2 else None
    return Stop(_into(inner, corridor, best[2]), label, dwell, warning)


def _open_stop(poly, corridor, inner, label, dwell, tol: float) -> Stop:
    """Stop on the corridor edge shared with an open area, nearest its centre."""
    shared = poly.boundary.intersection(corridor.buffer(tol))
    if shared.is_empty:
        p = nearest_points(inner, Point(label))[0]
        return Stop((p.x, p.y), label, dwell, "open area does not touch the corridor")
    edge_pt = nearest_points(shared, Point(label))[0]
    p = nearest_points(inner, edge_pt)[0]
    return Stop((p.x, p.y), label, dwell)


def _plan_room(raw: dict, parsed, corridor, inner, u: float) -> PlanRoom | None:
    """One PlanRoom from the raw room dict and its parsed qbiq_extractor _Room."""
    poly = qe._wkt(raw.get("geometry"))
    if poly is None or poly.is_empty or poly.geom_type not in ("Polygon", "MultiPolygon"):
        return None
    poly = poly.buffer(0)
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    p = polylabel(poly, tolerance=1.0)
    label = (p.x, p.y)
    dwell = dwell_for(raw.get("space_type"))
    offset = STOP_OFFSET_M / u
    is_open = not parsed.enclosed
    stop = (_open_stop(poly, corridor, inner, label, dwell, FRONT_TOL_M / u) if is_open or not parsed.doors
            else _door_stop(poly, parsed.doors, corridor, inner, offset, label, dwell))
    if stop.warning:
        log.warning("plan model: room %s (%s): %s", raw.get("id"), raw.get("space_type"), stop.warning)
    return PlanRoom(str(raw.get("id")), raw.get("space_type"), raw.get("subtype"),
                    poly.area * u * u, raw.get("head_count"), raw.get("assigned_hc"),
                    raw.get("department_id"), poly, is_open, label, stop)


def _unique_ids(rooms: list) -> list:
    """Keep the first of each repeated id; suffix later ones with #2, #3, ..."""
    seen = Counter()
    out = []
    for r in rooms:
        seen[r.id] += 1
        out.append(r if seen[r.id] == 1 else replace(r, id=f"{r.id}#{seen[r.id]}"))
    return out


def _parts(geom) -> list:
    return list(geom.geoms) if hasattr(geom, "geoms") else [geom]


def _furniture(data: dict) -> list:
    """Footprints of every shown stencil component."""
    return [fp for raw in data.get("rooms") or [] if isinstance(raw, dict)
            for comp in raw.get("stencil_geometry_components") or [] if isinstance(comp, dict)
            if (fp := component_footprint(comp)) is not None]


def _walk_in(room: PlanRoom) -> bool:
    """Open front-of-house areas big enough to walk into."""
    return room.is_open and room.space_type not in BACK_OF_HOUSE and room.area_m2 >= WALKABLE_MIN_M2


def _walkable(corridor, rooms: list, furniture: list, u: float):
    """Corridor plus the furniture-free floor of open front-of-house areas that connects to it."""
    open_floor = [r.polygon for r in rooms if _walk_in(r)]
    if not open_floor:
        return corridor
    blocked = unary_union([f.buffer(FURNITURE_CLEARANCE_M / u) for f in furniture])
    seam = 0.02 / u                                # closes hairline gaps between the corridor and room outlines
    merged = unary_union([corridor, unary_union(open_floor).difference(blocked)]).buffer(seam).buffer(-seam)
    return unary_union([p for p in _parts(merged) if p.intersection(corridor).area > 0])


def _inside_stop(room: PlanRoom, walkable, u: float) -> PlanRoom:
    """A walk-in area's stop moved to the middle of its largest free floor piece, when that is big enough;
    walking in is the look, so the look target is the stop itself."""
    pieces = [p for p in _parts(room.polygon.intersection(walkable)) if p.geom_type == "Polygon"] if _walk_in(room) else []
    if not pieces or (piece := max(pieces, key=lambda p: p.area)).area * u * u < INSIDE_STOP_MIN_M2:
        return room
    p = polylabel(piece, tolerance=0.05 / u)
    return replace(room, stop=replace(room.stop, point=(p.x, p.y), look_at=(p.x, p.y), warning=None))


def build_plan_model(data: dict, units_to_metres: float) -> PlanModel | None:
    """Semantic plan model from a design JSON; None when it has no circulation."""
    if (corridor := _corridor(data)) is None:
        log.warning("plan model: no top-level 'circulation' polygon - corridor routing unavailable")
        return None
    u = units_to_metres
    inner = _inner(corridor, STOP_OFFSET_M / u)
    rooms = [pr for raw in data.get("rooms") or [] if isinstance(raw, dict)
             if (parsed := qe._room(raw)) and (pr := _plan_room(raw, parsed, corridor, inner, u))]
    nfp = data.get("nfp_data") or {}
    me = qe._wkt(nfp.get("main_entrance"))
    entrance = _into(inner, corridor, (me.x, me.y)) if me is not None and me.geom_type == "Point" else None
    columns = [pl for g in qe._wkt_many(nfp.get("columns")) for pl in qe._polylines(g)]
    fill = qe._wkt(nfp.get("fill"))
    offset = enscape_offset(fill.bounds, u) if fill is not None and not fill.is_empty else None
    walkable = _walkable(corridor, rooms, _furniture(data), u)
    rooms = [_inside_stop(r, walkable, u) for r in rooms]
    return PlanModel(corridor, columns, tuple(_unique_ids(rooms)), entrance, u, offset, walkable)


def snap_to_walkable(plan: PlanModel, pt) -> tuple:
    """pt if it is walkable, else the nearest point a stop's offset inside the walkable area."""
    return _into(_inner(plan.walkable, STOP_OFFSET_M / plan.units_to_metres), plan.walkable, pt)


def _fy(pt) -> tuple:
    return (pt[0], -pt[1])


def flipped(plan: PlanModel) -> PlanModel:
    """The same plan in display space (y negated)."""
    flip = lambda g: scale(g, 1, -1, origin=(0, 0))  # noqa: E731
    rooms = tuple(replace(r, polygon=flip(r.polygon), label_point=_fy(r.label_point),
                          stop=replace(r.stop, point=_fy(r.stop.point), look_at=_fy(r.stop.look_at)))
                  for r in plan.rooms)
    return replace(plan, corridor=flip(plan.corridor), walkable=flip(plan.walkable),
                   columns=[[_fy(p) for p in pl] for pl in plan.columns], rooms=rooms,
                   entrance=_fy(plan.entrance) if plan.entrance else None)


def room_at(plan: PlanModel, pt) -> PlanRoom | None:
    """The room whose polygon covers pt, if any."""
    p = Point(pt)
    return next((r for r in plan.rooms if r.polygon.covers(p)), None)


def _rings(geom) -> list:
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    return [[list(c) for c in p.exterior.coords] for p in polys]


def plan_to_json(plan: PlanModel) -> dict:
    """JSON-serialisable view of the plan for the frontend."""
    types = sorted({r.space_type for r in plan.rooms if r.space_type})
    return {
        "corridor": _rings(plan.corridor),
        "entrance": list(plan.entrance) if plan.entrance else None,
        "enscape_offset": list(plan.enscape_offset) if plan.enscape_offset else None,
        "default_tour_types": [t for t in types if t not in BACK_OF_HOUSE],
        "rooms": [{
            "id": r.id, "name": r.space_type or "Room", "type": r.space_type,
            "subtype": r.subtype, "area_m2": round(r.area_m2, 1),
            "head_count": r.head_count, "assigned_hc": r.assigned_hc,
            "department_id": r.department_id, "polygon": _rings(r.polygon)[0],
            "label_point": list(r.label_point), "is_open": r.is_open,
            "stop": {"point": list(r.stop.point), "look_at": list(r.stop.look_at),
                     "dwell_s": r.stop.dwell_s, "warning": r.stop.warning},
        } for r in plan.rooms],
    }
