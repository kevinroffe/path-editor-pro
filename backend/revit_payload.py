"""
revit_payload.py
----------------
Turns the JSON the Revit add-in sends (one level per payload) into the project's
shared LevelGeometry, so routing, the 3D view and the Enscape XML export work on a
Revit level exactly as they do on DXF / IFC / qbiq sources.

Payload contract (schema 1; the add-in's C# DTOs mirror it):
  {"schema": 1,
   "level": {"name": str, "elevation": float},
   "units_to_metres": float,                      # 0.3048 for Revit's internal feet
   "walls"|"doors"|"windows"|"columns"|"furniture": [[[x, y], ...], ...],   # model units
   "rooms": [{"id", "name", "number", "polygon", "area", "placed", "enclosed"}],
   "meshes": [{"type", "verts", "faces", "color", "opacity"}]}   # verts: metres, Z-up
Coordinates keep Revit's internal origin; nothing is shifted.
"""
from collections import Counter

from revit_extractor import LevelGeometry

SCHEMA = 1
_POLYLINE_KEYS = ("walls", "doors", "windows", "columns", "furniture")


def _check(payload) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"unsupported payload schema {payload.get('schema')!r}, expected {SCHEMA}")


def _enclosed_rooms(payload: dict) -> list:
    return [r for r in payload.get("rooms") or []
            if r.get("placed") and r.get("enclosed") and r.get("polygon")]


def parse_revit_payload(payload: dict) -> LevelGeometry:
    """LevelGeometry for one Revit level; ValueError with a readable message on bad input."""
    _check(payload)
    polylines = {k: [[tuple(p) for p in poly] for poly in payload.get(k) or []] for k in _POLYLINE_KEYS}
    meshes = payload.get("meshes") or []
    # An overview of a level with no walls (a foundation or site level) is still useful: the page gets the level list
    # and the user can pick another level. Any other read of an empty level is an error.
    if not polylines["walls"] and not meshes and not payload.get("overview"):
        raise ValueError("level has no geometry")
    level = payload.get("level") or {}
    return LevelGeometry(
        level_name=str(level.get("name", "Level")),
        elevation=float(level.get("elevation", 0.0)),
        walls=polylines["walls"],
        spaces=[[tuple(p) for p in r["polygon"]] for r in _enclosed_rooms(payload)],
        doors=polylines["doors"],
        columns=polylines["columns"],
        windows=polylines["windows"],
        furniture=polylines["furniture"],
        units_to_metres=float(payload.get("units_to_metres", 1.0)),
        source="revit",
        meshes=meshes,
    )


def room_issues(payload: dict) -> list:
    """Rooms the tour logic can't trust: unplaced, unenclosed, zero area, or sharing a number."""
    _check(payload)
    rooms = payload.get("rooms") or []
    counts = Counter(r["number"] for r in rooms if r.get("number"))
    out = []
    for r in rooms:
        if not r.get("placed"):
            problem = "unplaced"
        elif not r.get("enclosed"):
            problem = "unenclosed"
        elif not r.get("area") or r["area"] <= 0:
            problem = "zero_area"
        elif r.get("number") and counts[r["number"]] > 1:
            problem = "duplicate"
        else:
            continue
        out.append({"room_id": r["id"], "name": r.get("name", ""), "problem": problem})
    return out
