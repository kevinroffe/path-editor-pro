"""
revit_extractor.py
------------------
Extracts 2-D geometry for a named building storey from:
  • IFC  files (via ifcopenshell)
  • RVT  files (attempted via rvt_model_services; falls back to demo data)

Public API
----------
extract_level(filepath, level_name="L-0") -> LevelGeometry
"""

from __future__ import annotations
import math
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from pathlib import Path

log = logging.getLogger(__name__)

# ── data types ──────────────────────────────────────────────────────────────

Polyline = List[Tuple[float, float]]

@dataclass
class LevelGeometry:
    level_name: str
    elevation: float
    walls:     List[Polyline] = field(default_factory=list)
    spaces:    List[Polyline] = field(default_factory=list)
    doors:     List[Polyline] = field(default_factory=list)
    columns:   List[Polyline] = field(default_factory=list)
    windows:   List[Polyline] = field(default_factory=list)
    furniture: List[Polyline] = field(default_factory=list)
    # Multiply any coordinate by this to get metres (for Enscape XML).
    # 1.0 = already metres, 0.001 = source is mm, 0.3048 = source is feet.
    units_to_metres: float = 1.0
    source: str = "unknown"   # "dxf", "ifc", "demo"
    # 3D mesh data for IFC files — list of {type, verts:[x,y,z,...], faces:[i,j,k,...]}
    # Verts are in IFC world coords (Z-up, metres). Empty for DXF/demo (uses extrusion).
    meshes: list = field(default_factory=list)

    def bounds(self):
        pts = [p for poly in (self.walls + self.spaces + self.doors + self.columns)
               for p in poly]
        if not pts:
            return 0, 0, 100, 100
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


# ── main entry point ─────────────────────────────────────────────────────────

def extract_level(filepath: str, level_name: str = "L-0") -> LevelGeometry:
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext == ".ifc":
        return _extract_ifc(filepath, level_name)
    elif ext == ".rvt":
        return _extract_rvt(filepath, level_name)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Upload .rvt or .ifc")


# ── IFC extraction ────────────────────────────────────────────────────────────

def _extract_ifc(filepath: str, level_name: str) -> LevelGeometry:
    try:
        import ifcopenshell
        import ifcopenshell.geom
        import ifcopenshell.util.element
        import numpy as np
    except ImportError:
        raise RuntimeError("ifcopenshell is not installed. Run: pip install ifcopenshell")

    model = ifcopenshell.open(filepath)
    storeys = model.by_type("IfcBuildingStorey")

    target = _find_storey(storeys, level_name)
    if target is None:
        raise ValueError(
            f"Level '{level_name}' not found. "
            f"Available: {[s.Name for s in storeys]}"
        )

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    geo = LevelGeometry(level_name=target.Name, elevation=target.Elevation or 0.0,
                        source="ifc")

    # IFC element types → 2D outline category (for floor plan SVG)
    OUTLINE_TYPES = {
        "IfcWall":                   "wall",
        "IfcWallStandardCase":       "wall",
        "IfcCurtainWall":            "wall",
        "IfcSpace":                  "space",
        "IfcDoor":                   "door",
        "IfcWindow":                 "window",
        "IfcColumn":                 "column",
        "IfcPillar":                 "column",
        "IfcFurnishingElement":      "furniture",
        "IfcFurniture":              "furniture",
        "IfcSystemFurnitureElement": "furniture",
        "IfcFlowTerminal":           "furniture",
        "IfcSanitaryTerminal":       "furniture",
        "IfcBuildingElementProxy":   "furniture",
    }

    # IFC element types → 3D mesh colour category (whitelist — unlisted types are skipped)
    MESH_TYPES = {
        "IfcWall":                   "wall",
        "IfcWallStandardCase":       "wall",
        "IfcCurtainWall":            "wall",
        "IfcPlate":                  "window",
        "IfcMember":                 "wall",
        "IfcSlab":                   "slab",
        "IfcColumn":                 "column",
        "IfcPillar":                 "column",
        "IfcBeam":                   "beam",
        "IfcStair":                  "stair",
        "IfcStairFlight":            "stair",
        "IfcRoof":                   "roof",
        "IfcRamp":                   "stair",
        "IfcRampFlight":             "stair",
        "IfcDoor":                   "door",
        "IfcWindow":                 "window",
        "IfcCovering":               "slab",
        "IfcRailing":                "wall",
        "IfcFurnishingElement":      "furniture",
        "IfcFurniture":              "furniture",
        "IfcSystemFurnitureElement": "furniture",
        "IfcFlowTerminal":           "furniture",
        "IfcSanitaryTerminal":       "furniture",
        "IfcLightFixture":           "furniture",
        "IfcElectricAppliance":      "furniture",
        "IfcAirTerminal":            "furniture",
        "IfcWasteTerminal":          "furniture",
        "IfcFireSuppressionTerminal":"furniture",
    }

    # All types we care about — skip create_shape for anything else
    KNOWN_TYPES = set(OUTLINE_TYPES) | set(MESH_TYPES)

    total_mesh_verts = 0
    MAX_MESH_VERTS   = 300_000   # total vertex budget across all elements

    # Collect all elements on this storey (containment only — Revit uses this)
    storey_elements = []
    for rel in model.by_type("IfcRelContainedInSpatialStructure"):
        if rel.RelatingStructure == target:
            storey_elements.extend(rel.RelatedElements)

    type_ok: dict   = {}
    type_fail: dict = {}

    for elem in storey_elements:
        kind = elem.is_a()
        if kind not in KNOWN_TYPES:
            continue

        try:
            shape     = ifcopenshell.geom.create_shape(settings, elem)
            raw_verts = shape.geometry.verts
            raw_faces = shape.geometry.faces
            if not raw_verts:
                continue
            verts = np.array(raw_verts).reshape(-1, 3)
            faces = np.array(raw_faces).reshape(-1, 3)

            # 2D outline for floor plan SVG
            outline_cat = OUTLINE_TYPES.get(kind)
            if outline_cat:
                outline = _project_outline(verts, faces)
                if outline:
                    if outline_cat == "wall":       geo.walls.append(outline)
                    elif outline_cat == "space":    geo.spaces.append(outline)
                    elif outline_cat == "door":     geo.doors.append(outline)
                    elif outline_cat == "window":   geo.windows.append(outline)
                    elif outline_cat == "column":   geo.columns.append(outline)
                    elif outline_cat == "furniture":geo.furniture.append(outline)

            # 3D mesh — whitelist only, no catch-all fallback
            mesh_type = MESH_TYPES.get(kind)
            if mesh_type and total_mesh_verts < MAX_MESH_VERTS:
                n_verts = len(raw_verts) // 3
                total_mesh_verts += n_verts
                geo.meshes.append({
                    "type":  mesh_type,
                    "verts": [round(v, 4) for v in raw_verts],
                    "faces": list(raw_faces),
                })
                type_ok[kind] = type_ok.get(kind, 0) + 1

            # Curtain wall children (IfcPlate, IfcMember) live in decomposition
            if kind == "IfcCurtainWall":
                for sub_rel in getattr(elem, "IsDecomposedBy", []):
                    for sub in sub_rel.RelatedObjects:
                        sub_kind = sub.is_a()
                        sub_mesh_type = MESH_TYPES.get(sub_kind)
                        if not sub_mesh_type:
                            continue
                        try:
                            sub_shape = ifcopenshell.geom.create_shape(settings, sub)
                            sv, sf    = sub_shape.geometry.verts, sub_shape.geometry.faces
                            if sv and total_mesh_verts < MAX_MESH_VERTS:
                                total_mesh_verts += len(sv) // 3
                                geo.meshes.append({
                                    "type":  sub_mesh_type,
                                    "verts": [round(v, 4) for v in sv],
                                    "faces": list(sf),
                                })
                        except Exception:
                            pass

        except Exception as e:
            type_fail[kind] = type_fail.get(kind, 0) + 1
            log.debug("Shape failed for %s: %s", kind, e)

    if not geo.walls and not geo.spaces:
        log.warning("No geometry extracted — returning demo floor plan")
        return _demo_geometry(level_name)

    log.info("IFC extracted: %d walls, %d doors, %d windows, %d furniture outlines",
             len(geo.walls), len(geo.doors), len(geo.windows), len(geo.furniture))
    log.info("IFC 3D meshes: %d total (%d verts). By type: %s",
             len(geo.meshes), total_mesh_verts, type_ok)
    if type_fail:
        log.warning("IFC shape failures by type: %s", type_fail)
    return geo


def _find_storey(storeys, level_name: str):
    # exact match first
    for s in storeys:
        if s.Name and s.Name.strip() == level_name:
            return s
    # case-insensitive
    for s in storeys:
        if s.Name and s.Name.strip().lower() == level_name.lower():
            return s
    # contains match
    for s in storeys:
        if s.Name and level_name.lower() in s.Name.lower():
            return s
    # fall back: lowest elevation
    if storeys:
        return min(storeys, key=lambda s: s.Elevation or 0)
    return None


def _project_outline(verts, faces) -> Polyline:
    """Convex-hull projection of mesh onto XY plane → closed polyline."""
    try:
        from scipy.spatial import ConvexHull
        pts2d = verts[:, :2]
        if len(pts2d) < 3:
            return []
        hull = ConvexHull(pts2d)
        outline = [tuple(pts2d[i]) for i in hull.vertices]
        outline.append(outline[0])  # close
        return outline
    except Exception:
        # fallback: bounding box
        xmin, ymin = verts[:, 0].min(), verts[:, 1].min()
        xmax, ymax = verts[:, 0].max(), verts[:, 1].max()
        return [(xmin, ymin), (xmax, ymin), (xmax, ymax),
                (xmin, ymax), (xmin, ymin)]


# ── RVT extraction ────────────────────────────────────────────────────────────

def _extract_rvt(filepath: str, level_name: str) -> LevelGeometry:
    """
    Attempt extraction via rvt_model_services.
    Falls back to demo geometry if the library is unavailable or the level
    cannot be found, so the UI still works for demos.
    """
    try:
        from rvt_model_services import commands
        result = commands.get_geometry(filepath, level=level_name)
        # rvt_model_services returns element dicts — convert to our format
        geo = LevelGeometry(level_name=level_name, elevation=0.0)
        for el in result.get("elements", []):
            pts = [(pt["x"], pt["y"]) for pt in el.get("outline", [])]
            if not pts:
                continue
            kind = el.get("category", "")
            if "Wall" in kind:
                geo.walls.append(pts)
            elif "Room" in kind or "Space" in kind:
                geo.spaces.append(pts)
            elif "Door" in kind or "Window" in kind:
                geo.doors.append(pts)
        if geo.walls or geo.spaces:
            return geo
    except Exception as e:
        log.info("RVT native extraction failed (%s); using demo geometry.", e)

    log.warning("Falling back to demo geometry for '%s'", level_name)
    return _demo_geometry(level_name)


# ── demo / fallback ───────────────────────────────────────────────────────────

def _demo_geometry(level_name: str) -> LevelGeometry:
    """A simple rectangular office floor plan for UI testing."""
    geo = LevelGeometry(level_name=level_name, elevation=0.0)

    # Outer perimeter wall
    W, H = 40.0, 25.0
    t = 0.3  # wall thickness

    def rect(x, y, w, h):
        return [(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)]

    # outer walls (4 sides as filled rectangles)
    geo.walls += [
        rect(0, 0, W, t),           # south
        rect(0, H-t, W, t),         # north
        rect(0, 0, t, H),           # west
        rect(W-t, 0, t, H),         # east
        rect(10-t/2, t, t, 12),     # internal divider 1
        rect(22-t/2, t, t, 15),     # internal divider 2
        rect(t, 10-t/2, 22-t, t),   # internal horizontal
    ]

    # rooms
    geo.spaces += [
        rect(t+0.5, t+0.5, 9-t, 9-t),         # room A
        rect(t+0.5, 10+t+0.5, 9-t, 14-2*t),   # room B
        rect(10+0.5, t+0.5, 12-t, 22-2*t),     # corridor
        rect(23+0.5, t+0.5, 16-2*t, 22-2*t),  # open plan
    ]

    # doors (small rects)
    geo.doors += [
        rect(4, 9.85, 2, 0.5),
        rect(4, 21.9, 2, 0.5),
        rect(9.75, 5, 0.5, 2),
        rect(21.75, 5, 0.5, 2),
    ]

    # columns
    for cx in [1.5, 11, 22.5, 38.5]:
        for cy in [1.5, 12, 23.5]:
            geo.columns.append(rect(cx-0.3, cy-0.3, 0.6, 0.6))

    return geo
