"""PlanModel for a Revit level: corridor, rooms, stops, entrance (what qbiq's design JSON supplies elsewhere).

Revit has no 'circulation' polygon or space types, so both are inferred from Room names and geometry:
  * rooms named like a corridor form the corridor; if none is named, the corridor is the floor between the
    rooms (their convex hull minus their union), keeping the pieces that touch a door;
  * a room's space type comes from SPACE_TYPE_KEYWORDS applied to its name (first match; none if unknown);
  * the entrance is the Reception stop, if the level has one.
Coordinates stay in Revit model units with the true origin: enscape_offset is always None.
"""
import logging

from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import polylabel, unary_union

import plan_model as pm
from plan_model import PlanModel, PlanRoom

log = logging.getLogger(__name__)

# First match wins, so "open office" is an open workspace and not an Office.
SPACE_TYPE_KEYWORDS = {
    "conference": "Conference",
    "meeting": "Conference",
    "kitchen": "Kitchen",
    "pantry": "Kitchen",
    "reception": "Reception",
    "lobby": "Reception",
    "storage": "Storage Room",
    "it room": "IT Room",
    "server": "IT Room",
    "print": "Print Hub",
    "open": "Open Space WorkStation",
    "workstation": "Open Space WorkStation",
    "office": "Office",
}
CORRIDOR_WORDS = ("corridor", "hallway", "hall", "circulation", "passage")
DOOR_TOUCH_M = 0.5   # a door belongs to a room when its midpoint is this close to the room's edge


def _space_type(name: str):
    low = (name or "").lower()
    return next((t for k, t in SPACE_TYPE_KEYWORDS.items() if k in low), None)


def _is_corridor_name(name: str) -> bool:
    low = (name or "").lower()
    return any(w in low for w in CORRIDOR_WORDS)


def _polygon(raw: dict):
    poly = Polygon(raw["polygon"]).buffer(0)
    if poly.is_empty:
        return None
    if isinstance(poly, MultiPolygon):
        poly = max(poly.geoms, key=lambda g: g.area)
    return poly


def _door_mid(door) -> Point:
    (x1, y1), (x2, y2) = door[0], door[-1]
    return Point((x1 + x2) / 2, (y1 + y2) / 2)


def _inferred_corridor(polys: list, doors: list, u: float):
    """Uncovered floor between the rooms that touches a door, or None."""
    union = unary_union(polys)
    gap = union.convex_hull.difference(union)
    pieces = [g for g in (gap.geoms if hasattr(gap, "geoms") else [gap])
              if g.geom_type == "Polygon" and g.area * u * u >= pm.WALKABLE_MIN_M2
              and any(g.distance(_door_mid(d)) <= pm.FRONT_TOL_M / u for d in doors)]
    return unary_union(pieces).buffer(0) if pieces else None


def build_revit_plan(payload: dict) -> PlanModel | None:
    """Plan model for one Revit level; None when it has no usable rooms or no corridor."""
    u = float(payload.get("units_to_metres", 1.0))
    raws = [(r, p) for r in payload.get("rooms") or [] if r.get("placed") and r.get("enclosed") and r.get("polygon")
            if (p := _polygon(r)) is not None]
    if not raws:
        return None
    doors = [[tuple(p) for p in d] for d in payload.get("doors") or []]
    named = [p for r, p in raws if _is_corridor_name(r.get("name"))]
    corridor = unary_union(named).buffer(0) if named else _inferred_corridor([p for _, p in raws], doors, u)
    if corridor is None or corridor.is_empty:
        log.warning("revit plan: no corridor found - corridor routing unavailable")
        return None
    inner = pm._inner(corridor, pm.STOP_OFFSET_M / u)
    rooms = []
    for raw, poly in raws:
        if _is_corridor_name(raw.get("name")):
            continue
        stype = _space_type(raw.get("name"))
        own_doors = [d for d in doors if _door_mid(d).distance(poly.boundary) <= DOOR_TOUCH_M / u]
        p = polylabel(poly, tolerance=0.1)
        label, dwell = (p.x, p.y), pm.dwell_for(stype)
        is_open = not own_doors or stype == "Open Space WorkStation"
        stop = (pm._open_stop(poly, corridor, inner, label, dwell, pm.FRONT_TOL_M / u) if is_open
                else pm._door_stop(poly, own_doors, corridor, inner, pm.STOP_OFFSET_M / u, label, dwell))
        rooms.append(PlanRoom(str(raw["id"]), stype, None, poly.area * u * u, None, None, None, poly,
                              is_open, label, stop))
    reception = next((r for r in rooms if r.space_type == "Reception"), None)
    columns = [[tuple(p) for p in c] for c in payload.get("columns") or []]
    try:
        walkable = pm._walkable(corridor, rooms, [], u)
    except Exception:  # noqa: BLE001 - a bad open-area polygon must not cost the plan its corridor routing
        log.exception("revit plan: walkable area failed - routing stays in the corridor")
        walkable = corridor
    rooms = [pm._inside_stop(r, walkable, u) for r in rooms]
    return PlanModel(corridor, columns, tuple(pm._unique_ids(rooms)),
                     reception.stop.point if reception else None, u, None, walkable)
