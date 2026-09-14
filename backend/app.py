"""
app.py
------
Flask REST API for the Revit Walkthrough Tool.

Endpoints
---------
POST /api/upload          — upload .rvt/.ifc, returns SVG + bounds
POST /api/smooth-preview  — live spline preview (no resampling)
POST /api/process-route   — full route processing → frames
POST /api/export/json     — export frames as JSON
POST /api/export/xml      — export frames as Enscape XML
GET  /                    — serve frontend
"""

from __future__ import annotations
import os
import sys
import json
import logging
from pathlib import Path

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

# ── path setup ────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent
UPLOAD_DIR  = BASE_DIR.parent / "uploads"
FRONTEND_DIR = BASE_DIR.parent / "frontend"
UPLOAD_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(BASE_DIR))

from revit_extractor import extract_level
from svg_generator   import generate_svg

try:
    from dxf_extractor import extract_dxf
    _DXF_AVAILABLE = True
except ImportError:
    _DXF_AVAILABLE = False
    log.warning("ezdxf not installed — DXF upload disabled. Run: py -m pip install ezdxf")
from route_processor import process_route, smooth_preview
from export_layer    import to_json, to_enscape_xml
from autopath        import find_multi_path
from corridor_graph   import (build_walkable_polygon, build_corridor_graph,
                               route_multi, compute_bounds)

ALLOWED_EXTENSIONS = {".rvt", ".ifc", ".dxf"}
MAX_UPLOAD_MB = 500

# Cached server-side so /api/autopath doesn't need physical obstacle geometry
# (which can be tens of MB of JSON on a real architectural DXF) re-sent on
# every click. Kept per-source (dxf / ifc) so either can be reloaded
# independently — a folder upload sends both in parallel — and combined at
# read time. Doors/windows are openings, not obstacles, so they're excluded;
# floor patterns, annotations, planting etc. are dropped entirely upstream in
# dxf_extractor.py / revit_extractor.py rather than cached at all.
_LAST_OBSTACLES = {"dxf": [], "ifc": []}
_LAST_FOOTPRINT = {"dxf": [], "ifc": []}  # FLOOD-layer / room polygons — see _footprint_polylines
_LAST_DOORS = {"dxf": [], "ifc": []}  # door locations, forced passable — see _door_polylines
_LAST_UNITS_TO_METRES = 1.0  # from the DXF/demo canvas source, for Auto Path's clearance_m conversion

# Corridor-graph routing needs walls kept SEPARATE from other obstacle
# categories (only walls get door-notched — see corridor_graph.py's
# build_walkable_polygon), unlike _LAST_OBSTACLES which flattens everything
# together for the grid-A* fallback's simpler needs.
_LAST_WALLS = {"dxf": [], "ifc": []}
_LAST_OTHER_OBSTACLES = {"dxf": [], "ifc": []}

# Bumped on every upload/demo call; the corridor-graph cache below is keyed
# on this so a new floor plan never reuses a stale graph.
_UPLOAD_GENERATION = 0

# (generation, round(clearance_m, 3)) -> (walkable_polygon | None, graph | None)
# Built lazily on the first /api/autopath call per key, not at upload time —
# keeps upload latency unaffected even for a real file with tens of
# thousands of furniture entities.
_LAST_CIRC_GRAPH: dict = {}


def _flip(poly):
    # SVG-display space negates Y (`svg_y = -model_y`) relative to the raw
    # model coordinates geo.* is stored in — see _obstacle_polylines below.
    return [(x, -y) for x, y in poly]


def _obstacle_polylines(geo) -> list:
    """
    Physical obstacles for pathfinding: walls, columns, furniture, windows.

    Windows were previously excluded here and treated exactly like doors
    (both just "not an obstacle"), which conflates two different classified
    categories with opposite real-world walkability: a door is a real
    opening, a window is a transparent barrier — nobody walks through a
    window. Excluding it let Auto Path route straight through one into open
    air, the same failure mode as the exterior-leak bug the FLOOD-footprint
    check exists to catch (see autopath.py's find_path docstring), just via
    a different opening type. Fixed by classifying windows as an obstacle
    like walls/columns/furniture, rather than lumping them in with doors.

    `geo.walls`/etc. are raw model coordinates (unflipped). Frontend waypoints
    — including the start/end points /api/autopath receives — are stored in
    SVG-display space where Y is negated (`svg_y = -model_y`; see
    svg_generator.py and export_layer.py's own comment on this). Every other
    consumer of waypoints is self-referential (smoothing, export, rendering)
    and never cross-references wall geometry, so this mismatch never showed
    up before — but Auto Path compares a waypoint-space click against
    wall-space geometry directly, so the obstacles must be flipped into the
    same space here, or pathfinding runs against a vertically mirrored map
    relative to where the user actually clicked.
    """
    return ([_flip(p) for p in geo.walls] +
            [_flip(p) for p in geo.windows] +
            [_flip(p) for p in geo.columns] +
            [_flip(p) for p in geo.furniture])


def _footprint_polylines(geo) -> list:
    """
    Routable-area polygons (the classify project's FLOOD layer for DXF,
    already-classified room/space polygons for IFC) — see geo.spaces and
    dxf_extractor.py's _classify_layer. Flipped into SVG-display space for
    the same reason as _obstacle_polylines. Empty for sources without one
    (older DXFs without a FLOOD layer), in which case Auto Path applies no
    footprint constraint at all — same behavior as before this existed.
    """
    return [_flip(p) for p in geo.spaces]


def _door_polylines(geo) -> list:
    """
    Door locations, flipped into SVG-display space like the other pathfinding
    inputs. Not obstacles — used to FORCE each door passable regardless of
    whether the surrounding wall/furniture geometry actually leaves a gap
    there, which on a real DXF it often doesn't (see autopath.py's
    _clear_doors for why this matters).
    """
    return [_flip(p) for p in geo.doors]


def _wall_polylines(geo) -> list:
    """Walls only, flipped into SVG-display space — see _obstacle_polylines
    for why the flip is needed. Kept separate from other obstacle
    categories because only walls get door-notched in corridor_graph.py."""
    return [_flip(p) for p in geo.walls]


def _other_obstacle_polylines(geo) -> list:
    """Columns, furniture, windows — everything _obstacle_polylines
    combines with walls, minus the walls themselves."""
    return ([_flip(p) for p in geo.windows] +
            [_flip(p) for p in geo.columns] +
            [_flip(p) for p in geo.furniture])


def _get_circ_graph_and_polygon(clearance_m: float):
    """
    Lazily build (and cache) the corridor graph for the current upload at a
    given clearance_m. Any exception during construction is treated the
    same as "no graph" — the caller falls back to grid A* — rather than
    ever 500ing a Smart Path request because of a corridor-graph bug.
    """
    key = (_UPLOAD_GENERATION, round(clearance_m, 3))
    if key not in _LAST_CIRC_GRAPH:
        walls = _LAST_WALLS["dxf"] + _LAST_WALLS["ifc"]
        other = _LAST_OTHER_OBSTACLES["dxf"] + _LAST_OTHER_OBSTACLES["ifc"]
        footprint = _LAST_FOOTPRINT["dxf"] + _LAST_FOOTPRINT["ifc"]
        doors = _LAST_DOORS["dxf"] + _LAST_DOORS["ifc"]
        try:
            bounds = compute_bounds(walls, footprint)
            polygon = build_walkable_polygon(
                walls, doors, other, footprint, bounds,
                clearance_m=clearance_m, units_to_metres=_LAST_UNITS_TO_METRES,
            )
            graph = build_corridor_graph(polygon, doors) if polygon is not None else None
        except Exception:
            log.exception("Corridor graph build failed — Smart Path will use grid A* for this request")
            polygon, graph = None, None
        _LAST_CIRC_GRAPH[key] = (polygon, graph)
    return _LAST_CIRC_GRAPH[key]

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ── app setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=str(FRONTEND_DIR))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
CORS(app)


# ── helpers ───────────────────────────────────────────────────────────────────

def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code

def _allowed(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return _err("No file field in request")
    f = request.files["file"]
    if not f.filename:
        return _err("Empty filename")
    if not _allowed(f.filename):
        return _err(f"Only {ALLOWED_EXTENSIONS} files are accepted")

    level_name = request.form.get("level", "L-0")

    fname = secure_filename(f.filename)
    fpath = UPLOAD_DIR / fname
    f.save(str(fpath))
    log.info("Uploaded: %s", fpath)

    try:
        ext = Path(fname).suffix.lower()
        if ext == ".dxf":
            if not _DXF_AVAILABLE:
                return _err("ezdxf not installed. Run: py -m pip install ezdxf")
            geo = extract_dxf(str(fpath), level_name)
        elif ext == ".rvt":
            return _err(
                "RVT files cannot be parsed without the Revit API. "
                "Please export a DXF instead:\n"
                "Revit → File → Export → CAD Formats → DXF → "
                "select the L-0 floor plan view → save → upload here."
            )
        else:
            geo = extract_level(str(fpath), level_name)
    except Exception as e:
        log.exception("Extraction failed")
        return _err(str(e))

    svg = generate_svg(geo)
    xmin, ymin, xmax, ymax = geo.bounds()

    _LAST_OBSTACLES["dxf"] = _obstacle_polylines(geo)
    _LAST_FOOTPRINT["dxf"] = _footprint_polylines(geo)
    _LAST_DOORS["dxf"] = _door_polylines(geo)
    _LAST_WALLS["dxf"] = _wall_polylines(geo)
    _LAST_OTHER_OBSTACLES["dxf"] = _other_obstacle_polylines(geo)
    global _LAST_UNITS_TO_METRES, _UPLOAD_GENERATION
    _LAST_UNITS_TO_METRES = geo.units_to_metres
    _UPLOAD_GENERATION += 1

    return jsonify({
        "svg": svg,
        "bounds": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
        "level": geo.level_name,
        "elevation": geo.elevation,
        "units_to_metres": geo.units_to_metres,
        "source": geo.source,
        "geometry": {
            "walls":     geo.walls,
            "spaces":    geo.spaces,
            "doors":     geo.doors,
            "columns":   geo.columns,
            "windows":   geo.windows,
            "furniture": geo.furniture,
            "meshes":    geo.meshes,
        },
    })


@app.route("/api/upload-3d", methods=["POST"])
def upload_3d():
    """Accept an IFC file and return 3D geometry only (no SVG, no canvas change)."""
    if "file" not in request.files:
        return _err("No file field in request")
    f = request.files["file"]
    if not f.filename:
        return _err("Empty filename")
    if Path(f.filename).suffix.lower() != ".ifc":
        return _err("Only IFC files are accepted for 3D upload")

    fname = secure_filename(f.filename)
    fpath = UPLOAD_DIR / fname
    f.save(str(fpath))
    log.info("Uploaded 3D: %s", fpath)

    try:
        geo = extract_level(str(fpath), request.form.get("level", "L-0"))
    except Exception as e:
        log.exception("3D extraction failed")
        return _err(str(e))

    xmin, ymin, xmax, ymax = geo.bounds()

    obstacles = _obstacle_polylines(geo)
    if obstacles:
        _LAST_OBSTACLES["ifc"] = obstacles
    footprint = _footprint_polylines(geo)
    if footprint:
        _LAST_FOOTPRINT["ifc"] = footprint
    doors = _door_polylines(geo)
    if doors:
        _LAST_DOORS["ifc"] = doors
    walls = _wall_polylines(geo)
    if walls:
        _LAST_WALLS["ifc"] = walls
    other = _other_obstacle_polylines(geo)
    if other:
        _LAST_OTHER_OBSTACLES["ifc"] = other
    global _UPLOAD_GENERATION
    _UPLOAD_GENERATION += 1

    return jsonify({
        "geometry": {
            "walls":     geo.walls,
            "spaces":    geo.spaces,
            "doors":     geo.doors,
            "columns":   geo.columns,
            "windows":   geo.windows,
            "furniture": geo.furniture,
            "meshes":    geo.meshes,
        },
        "bounds":          {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
        "units_to_metres": geo.units_to_metres,
        "level":           geo.level_name,
    })


@app.route("/api/demo", methods=["GET"])
def demo():
    """Load demo floor plan without uploading a file."""
    from revit_extractor import _demo_geometry
    geo = _demo_geometry("L-0")
    svg = generate_svg(geo)
    xmin, ymin, xmax, ymax = geo.bounds()

    _LAST_OBSTACLES["dxf"] = _obstacle_polylines(geo)
    _LAST_FOOTPRINT["dxf"] = _footprint_polylines(geo)
    _LAST_DOORS["dxf"] = _door_polylines(geo)
    _LAST_WALLS["dxf"] = _wall_polylines(geo)
    _LAST_OTHER_OBSTACLES["dxf"] = _other_obstacle_polylines(geo)
    global _LAST_UNITS_TO_METRES, _UPLOAD_GENERATION
    _LAST_UNITS_TO_METRES = geo.units_to_metres
    _LAST_OBSTACLES["ifc"] = []  # demo is a fresh, unrelated dataset
    _LAST_FOOTPRINT["ifc"] = []
    _LAST_DOORS["ifc"] = []
    _LAST_WALLS["ifc"] = []
    _LAST_OTHER_OBSTACLES["ifc"] = []
    _UPLOAD_GENERATION += 1

    return jsonify({
        "svg": svg,
        "bounds": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
        "level": geo.level_name,
        "elevation": geo.elevation,
        "units_to_metres": geo.units_to_metres,
        "source": geo.source,
        "geometry": {
            "walls":     geo.walls,
            "spaces":    geo.spaces,
            "doors":     geo.doors,
            "columns":   geo.columns,
            "windows":   geo.windows,
            "furniture": geo.furniture,
            "meshes":    geo.meshes,
        },
    })


@app.route("/api/autopath", methods=["POST"])
def autopath():
    data  = request.get_json(force=True)
    start = data.get("start")
    end   = data.get("end")
    # Ordered list of required reference points the route must pass through,
    # in order — e.g. [start, viaPoint, end]. `start`/`end` are still
    # accepted alone for a plain two-point route (and for older callers).
    points = data.get("points")
    if points:
        if len(points) < 2:
            return _err("points must contain at least a start and an end")
    elif start and end:
        points = [start, end]
    else:
        return _err("start and end points are required")
    # Obstacles (walls + columns + furniture, from both the DXF and any IFC
    # loaded alongside it) are cached server-side from the last upload —
    # sending them again from the client would mean re-transferring tens of
    # MB of JSON on every click for a real architectural DXF. `walls` in the
    # body is still honored if a caller explicitly provides it (e.g. tests).
    walls = data.get("walls") or (_LAST_OBSTACLES["dxf"] + _LAST_OBSTACLES["ifc"])
    # FLOOD-layer / room footprint polygons, cached the same way as obstacles
    # (see _footprint_polylines) — constrains routing to the real floor area
    # when the source provided one; empty for sources without a FLOOD layer.
    footprint = data.get("footprint") or (_LAST_FOOTPRINT["dxf"] + _LAST_FOOTPRINT["ifc"])
    # Door locations, forced passable regardless of nearby wall/furniture
    # geometry (see autopath.py's _clear_doors) — real doorways frequently
    # don't leave an actual gap in the wall data on a real DXF.
    doors = data.get("doors") or (_LAST_DOORS["dxf"] + _LAST_DOORS["ifc"])

    clearance_m = float(data.get("clearance_m", 0.2))

    # Corridor-graph routing (primary): a real corridor-centerline graph
    # instead of grid A*'s hand-tuned distance-transform corridor bias — see
    # docs/superpowers/specs/2026-09-14-corridor-graph-routing-design.md.
    # ANY failure here (graph build, or no route on the graph) falls back to
    # the ENTIRE route being computed by grid A* below, never a per-leg mix.
    waypoints = None
    polygon, graph = _get_circ_graph_and_polygon(clearance_m)
    if graph is not None:
        try:
            waypoints = route_multi(points, graph, polygon)
        except Exception:
            log.exception("Corridor-graph routing failed — falling back to grid A*")
            waypoints = None

    if not waypoints:
        waypoints = find_multi_path(
            points, walls,
            clearance_m=clearance_m,
            units_to_metres=_LAST_UNITS_TO_METRES,
            turn_penalty=float(data.get("turn_penalty", 4.0)),
            corridor_m=float(data.get("corridor_m", 1.0)),
            corridor_weight=float(data.get("corridor_weight", 0.5)),
            footprint=footprint,
            doors=doors,
        )

    return jsonify({"waypoints": waypoints})


@app.route("/api/smooth-preview", methods=["POST"])
def smooth_preview_route():
    data = request.get_json(force=True)
    wpts         = data.get("waypoints", [])
    smoothing    = float(data.get("smoothing", 1.0))
    uturn_radius = float(data.get("uturn_radius", 0.0))
    if len(wpts) < 2:
        return jsonify({"spline": wpts})
    spline = smooth_preview(wpts, smoothing=smoothing, uturn_radius=uturn_radius)
    return jsonify({"spline": spline})


@app.route("/api/process-route", methods=["POST"])
def process():
    data = request.get_json(force=True)
    wpts = data.get("waypoints", [])
    cuts = data.get("cuts", [])
    if len(wpts) < 2:
        return _err("Need at least 2 waypoints")

    settings = {
        "camera_height": float(data.get("camera_height", 1.7)),
        "smoothing":     float(data.get("smoothing", 1.0)),
        "duration":      float(data.get("duration", 30.0)),
        "fps":           float(data.get("fps", 30.0)),
        "fov":           float(data.get("fov", 90.0)),
        "level":         data.get("level", "L-0"),
    }

    try:
        frames = process_route(
            waypoints=[(p[0], p[1]) for p in wpts],
            camera_height=settings["camera_height"],
            smoothing=settings["smoothing"],
            total_duration=settings["duration"],
            fps=settings["fps"],
            fov=settings["fov"],
            cuts=cuts,
        )
    except Exception as e:
        return _err(str(e))

    return jsonify({
        "frame_count": len(frames),
        "settings": settings,
        "frames": [
            {"t": f.t, "x": f.x, "y": f.y, "z": f.z,
             "yaw": f.yaw, "pitch": f.pitch, "fov": f.fov, "cut": bool(f.cut)}
            for f in frames
        ],
    })


@app.route("/api/export/json", methods=["POST"])
def export_json():
    data = request.get_json(force=True)
    wpts     = data.get("waypoints", [])
    cuts     = data.get("cuts", [])
    settings = data.get("settings", {})

    frames = process_route(
        waypoints=wpts,   # pass full triples [x, y, yaw_offset]
        camera_height=1.75,
        smoothing=float(settings.get("smoothing", 1.0)),
        total_duration=float(settings.get("duration", 30.0)),
        fps=float(settings.get("fps", 30.0)),
        fov=float(settings.get("fov", 90.0)),
        uturn_radius=float(settings.get("uturn_radius", 0.0)),
        cuts=cuts,
    )
    settings = {**settings, "cuts": cuts}  # round-trips through JSON re-import
    out = to_json(frames, wpts, settings)
    return app.response_class(out, mimetype="application/json",
                               headers={"Content-Disposition":
                                        'attachment; filename="route.json"'})


@app.route("/api/export/xml", methods=["POST"])
def export_xml():
    data = request.get_json(force=True)
    wpts     = data.get("waypoints", [])
    cuts     = data.get("cuts", [])
    settings = data.get("settings", {})

    frames = process_route(
        waypoints=wpts,   # pass full triples [x, y, yaw_offset]
        camera_height=1.75,
        smoothing=float(settings.get("smoothing", 1.0)),
        total_duration=float(settings.get("duration", 30.0)),
        fps=float(settings.get("fps", 30.0)),
        fov=float(settings.get("fov", 90.0)),
        uturn_radius=float(settings.get("uturn_radius", 0.0)),
        cuts=cuts,
    )
    out = to_enscape_xml(frames, wpts, settings)
    return app.response_class(out, mimetype="application/xml",
                               headers={"Content-Disposition":
                                        'attachment; filename="enscape_walkpath.xml"'})


# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info("Starting on http://localhost:%d", port)
    app.run(debug=True, port=port, threaded=True)
