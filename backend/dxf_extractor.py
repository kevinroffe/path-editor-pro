"""
dxf_extractor.py
----------------
Reads a DXF file exported from Revit and converts every visible entity
into polylines for SVG rendering.

Key design decisions
--------------------
1. The origin is NEVER shifted.  Raw DXF coordinates are kept as-is so
   that the Enscape XML we export later uses the exact same coordinate
   space as the Revit model.

2. Units are auto-detected from the DXF $INSUNITS header variable and
   stored in LevelGeometry.units_to_metres so the export layer can
   convert to metres for Enscape without touching the SVG coordinates.

3. Every non-empty entity is rendered — we don't try to classify layers
   as "wall / door / space".  The DXF already looks like the Revit plan;
   we just faithfully reproduce it.

How to export from Revit
------------------------
  File → Export → CAD Formats → DXF
  • Views: select the L-0 floor plan view ONLY
  • Coordinate system: Project Internal   ← CRITICAL for Enscape alignment
  • Format: AutoCAD 2013 DXF (or newer)
  • Units: same as your Revit project (mm or feet — app auto-detects)
"""

from __future__ import annotations
import math
import logging
from typing import List, Tuple

import ezdxf
from ezdxf.enums import InsertUnits

from revit_extractor import LevelGeometry, Polyline as Poly2D

log = logging.getLogger(__name__)

ARC_SEGMENTS = 32   # polyline segments per arc/circle


# ── $INSUNITS → metres conversion ────────────────────────────────────────────
# DXF spec: https://help.autodesk.com/view/OARX/2024/ENU/?guid=GUID-A85E8E67
_INSUNITS_TO_METRES = {
    0:  1.0,        # Unitless — assume metres
    1:  0.0254,     # Inches
    2:  0.3048,     # Feet
    3:  0.9144,     # Yards
    4:  0.001,      # Millimetres  ← most common Revit metric export
    5:  0.01,       # Centimetres
    6:  1.0,        # Metres
    7:  1000.0,     # Kilometres
    8:  0.000254,   # Microinches
    9:  0.0000254,  # Mils
    10: 1609.344,   # Miles
    14: 1e-10,      # Angstroms
    15: 1e-9,       # Nanometres
    16: 1e-6,       # Microns
    17: 100.0,      # Decametres
    18: 1000.0,     # Hectometres (same as km for our purposes)
    19: 1e6,        # Gigametres
    20: 1.496e11,   # Astronomical units
    21: 9.461e15,   # Light years
    22: 3.086e16,   # Parsecs
    23: 0.3048 / 12,# US Survey Feet
}


# ── layer classification ──────────────────────────────────────────────────────
# Two sources of DXF feed this: (1) the classify project's own exports, which
# use a fixed, authoritative `qbiq_*` layer vocabulary (see
# classify/frontend/src/dxfExport.js's DXF_LAYER_NAME — the actual list that
# lands in a real exported file), and (2) raw architectural DXF exported
# directly from Revit/AutoCAD, which follows the looser AIA/NCS
# Discipline-Major-Minor convention (A-WALL, A-DOOR, A-GLAZ-CWMG, I-FURN,
# S-COLS) with no fixed vocabulary. Classify's exact `qbiq_*` names are
# checked FIRST and are the ground truth whenever present — never inferred
# from substring keywords, which is what caused a real bug: `qbiq_door_lines`
# (a threshold-sealing marker line meant to CLOSE a wall gap for classify's
# own flood-fill, conceptually the opposite of an opening) matched the
# substring `'DOOR' in name` and got treated as a real, force-passable door.
# The AIA-keyword heuristic below is kept only as a fallback for raw,
# non-classify DXFs that have no `qbiq_*` layers at all.
#
# Obstacles Auto Path should route around: wall, column, furniture (and
# everything else physically solid — see _QBIQ_LAYER_MAP). Passable / not
# obstacles: door (a real opening), window (a barrier, but excluded from the
# `wall`/`column`/`furniture` obstacle-merge distinction only for rendering/
# future 3D use — see _bucket_for; it's still included in the obstacle set
# by app.py's _obstacle_polylines). FLOOD/Outdoor Flood mark the real usable
# floor footprint (routed into `geo.spaces`) — Auto Path should never route
# outside it. Q-Line/marker layers are pure annotations for classify's own
# flood-fill sealing, not real geometry — ignored entirely.
_QBIQ_LAYER_MAP = {
    'qbiq_walls':               'wall',
    'qbiq_columns':             'column',
    'qbiq_doors':               'door',
    'qbiq_windows':             'window',
    'qbiq_furniture':           'furniture',
    'qbiq_interior_design':     'furniture',   # protected built-in furniture/fixtures — physical, blocks routing
    'qbiq_toiletseat':          'furniture',   # physical fixture
    'qbiq_mullions':            'wall',        # curtain-wall dividers — structural
    'qbiq_railings':            'wall',        # balcony/void edges — physical barrier
    'qbiq_stairs':              'wall',        # solid footprint on this level (classify's own flood-fill excludes it too)
    'qbiq_elevators':           'wall',        # solid shaft, same reasoning as stairs
    'qbiq_flood_hatch':         'floor',       # the real export name for indoor Flood (not the shorter 'qbiq_flood')
    'qbiq_flood':               'floor',       # tolerate this name too, in case it's ever used directly
    'qbiq_outdoor_flood':       'floor',       # a specific walkable outdoor area, not "everything outside"
    'qbiq_door_lines':          'ignore',      # threshold marker, not a real door — see note above
    'qbiq_main_entrance_lines': 'ignore',
    'qbiq_egress_lines':        'ignore',
}

# AIA/NCS fallback for raw (non-classify) DXFs, matched by major-code
# keyword rather than an exact prefix since minor/status suffixes vary a lot
# between projects. Decorative/non-physical layers (floor patterns,
# annotations, planting, stairs, MEP) are dropped entirely rather than
# treated as a wall — previously *every* entity landed in `walls`, so a
# dimension line or a floor hatch could block a path like a real wall.
_LAYER_IGNORE_KEYWORDS = (
    'ANNO', 'TEXT', 'IDEN', 'DIM', 'FLOR', 'PATT', 'DETL', 'PLNT',
    'STRS', 'COMM', 'ELEC', 'GENM',
)


def _classify_layer(layer_name: str) -> str:
    """Classify a DXF layer into 'wall' | 'door' | 'window' | 'furniture' | 'column' | 'floor' | 'ignore'."""
    name = (layer_name or '').upper()

    qbiq_match = _QBIQ_LAYER_MAP.get(name.lower())
    if qbiq_match:
        return qbiq_match

    if 'FLOOD' in name:
        return 'floor'
    if 'WALL' in name:
        return 'wall'
    if 'COLS' in name or 'COLUMN' in name:
        return 'column'
    if 'FURN' in name or 'CASE' in name:
        return 'furniture'
    if 'DOOR' in name:
        return 'door'
    if 'GLAZ' in name or 'WIND' in name:
        return 'window'
    if any(k in name for k in _LAYER_IGNORE_KEYWORDS):
        return 'ignore'
    return 'wall'  # unrecognized layer — conservative default, same as previous behavior


def _bucket_for(geo: LevelGeometry, category: str) -> list:
    return {
        'wall':      geo.walls,
        'door':      geo.doors,
        'window':    geo.windows,
        'furniture': geo.furniture,
        'column':    geo.columns,
        'floor':     geo.spaces,
    }.get(category, geo.walls)


# ── main entry point ──────────────────────────────────────────────────────────

def extract_dxf(filepath: str, level_name: str = "L-0") -> LevelGeometry:
    doc = ezdxf.readfile(filepath)

    # ── detect units ─────────────────────────────────────────────────────────
    insunits = int(doc.header.get("$INSUNITS", 0))
    units_to_m = _INSUNITS_TO_METRES.get(insunits, 1.0)
    unit_name  = _unit_label(insunits)
    log.info("DXF $INSUNITS=%d (%s) → 1 unit = %.6f m", insunits, unit_name, units_to_m)

    geo = LevelGeometry(
        level_name=level_name,
        elevation=0.0,
        units_to_metres=units_to_m,
        source="dxf",
    )

    # ── collect all entities (modelspace + block inserts one level deep),
    #    routed into the right bucket by the INSERT/entity's own layer ───────
    msp = doc.modelspace()
    entities = list(msp)
    for ent in list(entities):
        category = _classify_layer(ent.dxf.layer)
        if category == 'ignore':
            continue
        bucket = _bucket_for(geo, category)

        if ent.dxftype() == 'INSERT':
            try:
                blk = doc.blocks[ent.dxf.name]
                # Apply insert transform to each sub-entity
                t = ent.matrix44()
                for sub in blk:
                    polys = _entity_to_polylines(sub, doc)
                    for poly in polys:
                        bucket.append(_transform_poly(poly, t))
            except Exception as e:
                log.debug("Block insert failed: %s", e)
            continue  # handled above

        polys = _entity_to_polylines(ent, doc)
        for poly in polys:
            if poly:
                bucket.append(poly)

    total = len(geo.walls) + len(geo.doors) + len(geo.windows) + len(geo.columns) + len(geo.furniture)
    log.info(
        "DXF extracted from '%s': %d walls, %d doors, %d windows, %d columns, %d furniture, %d floor/FLOOD",
        filepath, len(geo.walls), len(geo.doors), len(geo.windows), len(geo.columns), len(geo.furniture), len(geo.spaces),
    )

    if total == 0:
        raise ValueError(
            "No geometry found in DXF.\n"
            "Make sure you exported a Floor Plan view (not a 3-D view) as DXF.\n"
            "In Revit: File → Export → CAD Formats → DXF → "
            "choose 'Current view only' and select the L-0 floor plan."
        )

    _fix_implausible_units(geo, filepath)

    return geo


# A single floor plate is never smaller than a closet or bigger than a large
# office/warehouse floor — anything outside this range at the DECLARED units
# means the DXF's own $INSUNITS is wrong relative to its actual coordinate
# scale, not that the building is really that size. Kept fairly tight (not,
# say, 2000m) specifically so that when a real mismatch is off by a full
# 100x or 1000x, an intermediate 10x/100x candidate that's merely LESS
# implausible doesn't get accepted before the correct factor is tried —
# confirmed necessary in practice: a real file off by 100x (declared
# building size 3741m) had a 10x-corrected candidate (374.1m) that still
# fell inside an earlier, more permissive 500m bound and was wrongly picked.
_PLAUSIBLE_MIN_EXTENT_M = 2.0
_PLAUSIBLE_MAX_EXTENT_M = 200.0


def _fix_implausible_units(geo: LevelGeometry, filepath: str) -> None:
    """
    Sanity-check units_to_metres against the actual entity extent, and
    correct it (by a power of 10) if the declared units make the building
    implausibly tiny or huge.

    Real bug this catches: a DXF re-exported by the classify project had
    $INSUNITS=6 (metres) in its header, but its coordinates were actually in
    centimetres — a 100x mismatch, inherited from whatever the ORIGINALLY
    uploaded floor plan's header said and never corrected during classify's
    clean/re-export pipeline (this is a separate, external system — nothing
    revit-walkthrough-v2 controls). Taken at face value, that file's overall
    footprint came out to ~3.6km × 2.4km, an impossible single floor. Every
    metric parameter in Auto Path (clearance_m, corridor_m,
    door_clear_margin_m, grid resolution) is computed from units_to_metres,
    so trusting a wrong header silently turns "0.2m clearance" into a
    fraction of a millimetre and grid cells into ~27m squares — not a
    pathfinding bug, but every distance-based heuristic becoming meaningless
    for that one file. This can't be fixed at the source (classify is a
    separate project/repo), so revit-walkthrough-v2 has to be defensive
    about it instead of trusting every DXF's header unconditionally.
    """
    all_pts = [
        pt for bucket in (geo.walls, geo.doors, geo.windows, geo.columns, geo.furniture, geo.spaces)
        for poly in bucket for pt in poly
    ]
    if not all_pts:
        return
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    raw_extent = max(max(xs) - min(xs), max(ys) - min(ys))
    if raw_extent <= 0:
        return

    declared_extent_m = raw_extent * geo.units_to_metres
    if _PLAUSIBLE_MIN_EXTENT_M <= declared_extent_m <= _PLAUSIBLE_MAX_EXTENT_M:
        return  # declared units already give a sane building size

    for factor in (10.0, 100.0, 1000.0, 0.1, 0.01, 0.001):
        corrected_m = declared_extent_m / factor
        if _PLAUSIBLE_MIN_EXTENT_M <= corrected_m <= _PLAUSIBLE_MAX_EXTENT_M:
            log.warning(
                "DXF '%s': declared units give an implausible building size "
                "(%.1fm at the stated %.6f m/unit) — correcting units_to_metres "
                "by a factor of %g to %.6f m/unit (building size now %.1fm). "
                "This DXF's $INSUNITS header doesn't match its actual "
                "coordinate scale.",
                filepath, declared_extent_m, geo.units_to_metres, factor,
                geo.units_to_metres / factor, corrected_m,
            )
            geo.units_to_metres = geo.units_to_metres / factor
            return

    log.warning(
        "DXF '%s': declared units give an implausible building size (%.1fm) "
        "and no simple power-of-10 correction fixes it — leaving "
        "units_to_metres as-is (%.6f m/unit), but Auto Path's clearance/"
        "corridor/grid parameters may not behave sensibly for this file.",
        filepath, declared_extent_m, geo.units_to_metres,
    )


# ── entity → list[polyline] ───────────────────────────────────────────────────

def _entity_to_polylines(entity, doc=None) -> List[Poly2D]:
    t = entity.dxftype()

    if t == 'LINE':
        s, e = entity.dxf.start, entity.dxf.end
        return [[(s.x, s.y), (e.x, e.y)]]

    elif t == 'LWPOLYLINE':
        pts = [(p[0], p[1]) for p in entity.get_points('xy')]
        if entity.closed and pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        return [pts] if len(pts) >= 2 else []

    elif t == 'POLYLINE':
        pts = []
        for v in entity.vertices:
            try:
                loc = v.dxf.location
                pts.append((loc.x, loc.y))
            except Exception:
                pass
        if entity.is_closed and pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        return [pts] if len(pts) >= 2 else []

    elif t == 'ARC':
        return [_arc_pts(
            entity.dxf.center.x, entity.dxf.center.y,
            entity.dxf.radius,
            entity.dxf.start_angle, entity.dxf.end_angle
        )]

    elif t == 'CIRCLE':
        return [_circle_pts(
            entity.dxf.center.x, entity.dxf.center.y,
            entity.dxf.radius
        )]

    elif t in ('SPLINE', 'ELLIPSE'):
        try:
            pts = [(p.x, p.y) for p in entity.flattening(0.01)]
            return [pts] if len(pts) >= 2 else []
        except Exception:
            return []

    elif t == 'HATCH':
        return _hatch_polylines(entity)

    elif t == 'SOLID' or t == 'TRACE':
        # 4-point filled quad
        try:
            corners = [entity.dxf.vtx0, entity.dxf.vtx1,
                       entity.dxf.vtx3, entity.dxf.vtx2, entity.dxf.vtx0]
            return [[(c.x, c.y) for c in corners]]
        except Exception:
            return []

    return []


# ── geometry helpers ──────────────────────────────────────────────────────────

def _arc_pts(cx, cy, r, start_deg, end_deg) -> Poly2D:
    if end_deg <= start_deg:
        end_deg += 360
    step = (end_deg - start_deg) / ARC_SEGMENTS
    pts = []
    for i in range(ARC_SEGMENTS + 1):
        a = math.radians(start_deg + step * i)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _circle_pts(cx, cy, r) -> Poly2D:
    pts = []
    for i in range(ARC_SEGMENTS + 1):
        a = math.radians(360 * i / ARC_SEGMENTS)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _hatch_polylines(entity) -> List[Poly2D]:
    result = []
    try:
        for path in entity.paths:
            pts = []
            for edge in path.edges:
                et = edge.EDGE_TYPE
                if et == 'LineEdge':
                    pts.append((edge.start.x, edge.start.y))
                elif et == 'ArcEdge':
                    pts.extend(_arc_pts(
                        edge.center.x, edge.center.y, edge.radius,
                        edge.start_angle, edge.end_angle
                    ))
                elif et == 'EllipseEdge':
                    try:
                        sub = [(p.x, p.y) for p in edge.flattening(0.01)]
                        pts.extend(sub)
                    except Exception:
                        pass
                elif et == 'SplineEdge':
                    try:
                        sub = [(p.x, p.y) for p in edge.flattening(0.01)]
                        pts.extend(sub)
                    except Exception:
                        pass
            if len(pts) >= 2:
                result.append(pts)
    except Exception as e:
        log.debug("Hatch failed: %s", e)
    return result


def _transform_poly(poly: Poly2D, matrix) -> Poly2D:
    """Apply a 4×4 matrix to a 2-D polyline (Z=0)."""
    from ezdxf.math import Vec3
    result = []
    for x, y in poly:
        v = matrix.transform(Vec3(x, y, 0))
        result.append((v.x, v.y))
    return result


def _unit_label(insunits: int) -> str:
    labels = {0:'unitless',1:'inches',2:'feet',4:'mm',5:'cm',6:'m'}
    return labels.get(insunits, f'code {insunits}')
