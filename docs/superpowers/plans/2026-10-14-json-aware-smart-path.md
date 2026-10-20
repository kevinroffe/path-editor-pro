# JSON-Aware Smart Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Smart Path and the camera understand a qbiq design JSON — corridor-only routing, room door stops with look-in, an auto tour from the entrance, glances into passing rooms, and room labels/info.

**Architecture:** A semantic `PlanModel` (new `backend/plan_model.py`) is built from the design JSON at upload, cached in `app.py` in display space, and shared by corridor-only routing (`backend/plan_routing.py`, reusing the corridor-graph engine on the real `circulation` polygon), the auto tour (`backend/plan_tour.py`), the camera (`route_processor.py` gains stops + glances) and the frontend (labels, tooltip, Auto Tour panel).

**Tech Stack:** Python 3.13, Flask, shapely, networkx, numpy, pytest; single-file frontend (vanilla JS, D3 v7, Three.js r128).

**Spec:** `docs/superpowers/specs/2026-10-14-json-aware-smart-path-design.md`

## Global Constraints

- Routes are confined to the **top-level `circulation`** polygon of the design JSON — never `zones.circulation`, never `zones.circulation_graph`.
- Strict corridor only: rooms AND open areas (rooms with no visible door) are never walked; both are visited via stops.
- Stop offset 0.6 m into the corridor; glance radius 1.2 m; glance max 30°; glance suppressed while the path turns (≥45° across the look-ahead window); turn-rate cap stays 180°/s.
- Dwell: Reception, Executive Office, Conference, Open Space WorkStation = 3.0 s; any type starting with "Office", Kitchen, Comfort Zone = 2.0 s; all others 1.5 s. Total dwell is capped at 50 % of the video duration (scaled proportionally, min 0.6 s per stop).
- Auto-tour default excludes back-of-house: Storage Room, IT Room, Print Hub, Other.
- Tour pacing: 1.0 m/s walking + dwells, rounded up to the next 5 s, minimum 10 s.
- Coordinates: `PlanModel` is built in **model space**; `app.py` caches and serves it in **display space** (`y_display = -y_model`), the same space as waypoints, `_LAST_*` caches and `/api/autopath` points.
- Waypoint wire format grows a 5th element: `[x, y, yaw_offset, time_of_day, stop]` where `stop` is `null` or `{room_id, room_name, look_at: [x, y], dwell_s}`. Exports and imports must keep working with 4-element arrays.
- DXF, IFC and the JSON+SVG pair behave exactly as today (no plan model → old code paths).
- Subagents never `git commit`; the controller commits. No `print()`; module loggers. Short functions, one-line docstrings. flake8 `--extend-ignore=W292,W391,E302,E501` clean on touched Python files.
- Venv: `C:/Users/kevin/revit-walkthrough-v2/.venv/Scripts/python.exe`; work in `C:/Users/kevin/revit-walkthrough-v2/.worktrees/qbiq-design-json`. Reference files: `C:\Users\kevin\Downloads\121937120410001.json` (17 rooms), `C:\Users\kevin\Downloads\80565468720002.json` (36 rooms).

## Review Focus

- **Smoothed path leaving the corridor** — Catmull-Rom can bulge outside a polygon at sharp corners even when every waypoint is inside; a person would expect the drawn/animated path to stay in the corridor. Task 3's `contain_spline` + test "every smoothed sample inside the corridor" pins this.
- **Stop placed on the wrong side of a door / inside the room** — a door's two normals point into the room and into the corridor; picking the wrong one puts the camera inside the room. Task 1 tests assert stops lie inside the corridor in front of the door.
- **Stop metadata misattached after route simplification** — `route_multi` reduces points; stops must still land on the waypoint nearest their snapped point, in order. Task 3 test with three room clicks asserts index order and positions.
- **Dwells breaking total duration / turn-rate cap** — inserting dwell frames must keep the video length and never exceed 180°/s. Task 5 tests assert both.
- **Stale plan after loading another file** — a DXF/IFC/pair upload after a design JSON must drop the plan so routing returns to the old behaviour. Task 2 test asserts `_LAST_PLAN` is cleared.

---

### Task 0: Commit the frontend redesign (controller)

The qbiq-brand frontend redesign is applied uncommitted in this worktree's `frontend/index.html` (user approved committing it as the spec's first rollout step). The controller commits it as its own commit before Task 6:

```bash
git add frontend/index.html
git commit -m "feat(frontend): qbiq-brand redesign (tokens, toolbar, logo, via-point markers)"
```

---

### Task 1: PlanModel

**Files:**
- Create: `backend/plan_model.py`
- Test: `backend/tests/test_plan_model.py`

**Interfaces:**
- Consumes: `qbiq_extractor._wkt`, `_wkt_many`, `_room` (returns `_Room(rings, enclosed, doors, furniture, space_type, components)` with `doors` = trimmed 2-point openings in model units), `_polylines`.
- Produces:
  - `Stop(point: tuple, look_at: tuple, dwell_s: float, warning: str | None)`
  - `PlanRoom(id, space_type, subtype, area_m2, head_count, assigned_hc, department_id, polygon, is_open, label_point, stop)`
  - `PlanModel(corridor, columns: list, rooms: tuple, entrance: tuple | None, glance_targets: tuple, units_to_metres: float)`
  - `build_plan_model(data: dict, units_to_metres: float) -> PlanModel | None` (None when the JSON has no usable `circulation`)
  - `flipped(plan: PlanModel) -> PlanModel` (y negated everywhere)
  - `room_at(plan: PlanModel, pt) -> PlanRoom | None`
  - `dwell_for(space_type: str | None) -> float`
  - `plan_to_json(plan: PlanModel) -> dict`
  - constants `BACK_OF_HOUSE`, `STOP_OFFSET_M`, `GLANCE_RADIUS_M`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_plan_model.py`:
```python
import pytest
from shapely.geometry import Point

import plan_model as pm

U = 0.01  # 1 unit = 1 cm


def _room(rid, space_type, poly_wkt, doors, door_geometry=None):
    return {"id": rid, "space_type": space_type, "subtype": None, "geometry": poly_wkt,
            "doors": doors, "door_geometry": door_geometry, "head_count": 4,
            "assigned_hc": 3, "department_id": 1, "stencil_geometry": None,
            "stencil_geometry_components": []}


def _door(line_wkt, shown=True, geom=None):
    return {"door_line": line_wkt, "show_door": shown, "door_geometry": geom}


# 20 m x 10 m floor; corridor band y 400..600 across the full width.
# A: enclosed Conference above the corridor, door on y=600 at x 300..400.
# B: open Open Space above the corridor (door hidden).
# C: enclosed Storage below the corridor, door on y=400 at x 500..590.
# D: open Reception below the corridor holding the main entrance.
DATA = {
    "circulation": "POLYGON ((0 400, 2000 400, 2000 600, 0 600, 0 400))",
    "rooms": [
        _room("A", "Conference", "POLYGON ((0 600, 800 600, 800 1000, 0 1000, 0 600))",
              [_door("LINESTRING (0 600, 800 600)",
                     geom="GEOMETRYCOLLECTION (LINESTRING (300 600, 300 610), LINESTRING (400 600, 400 610))")]),
        _room("B", "Open Space WorkStation", "POLYGON ((1000 600, 2000 600, 2000 1000, 1000 1000, 1000 600))",
              [_door("LINESTRING (1000 600, 2000 600)", shown=False)]),
        _room("C", "Storage Room", "POLYGON ((0 0, 800 0, 800 400, 0 400, 0 0))",
              [_door("LINESTRING (0 400, 800 400)",
                     geom="GEOMETRYCOLLECTION (LINESTRING (500 400, 500 390), LINESTRING (590 400, 590 390))")]),
        _room("D", "Reception", "POLYGON ((800 0, 2000 0, 2000 400, 800 400, 800 0))",
              [_door("LINESTRING (800 400, 2000 400)", shown=False)]),
    ],
    "nfp_data": {"main_entrance": "POINT (1500 0)", "columns": None},
}


@pytest.fixture
def plan():
    return pm.build_plan_model(DATA, U)


def _by_id(plan, rid):
    return next(r for r in plan.rooms if r.id == rid)


def test_corridor_is_top_level_circulation(plan):
    assert plan.corridor.area == pytest.approx(2000 * 200)


def test_open_vs_enclosed(plan):
    assert not _by_id(plan, "A").is_open
    assert _by_id(plan, "B").is_open
    assert not _by_id(plan, "C").is_open
    assert _by_id(plan, "D").is_open


def test_enclosed_room_stop_in_corridor_in_front_of_door(plan):
    a = _by_id(plan, "A")
    assert a.stop.point == pytest.approx((350.0, 540.0))
    assert plan.corridor.covers(Point(a.stop.point))
    assert a.polygon.covers(Point(a.stop.look_at))
    c = _by_id(plan, "C")
    assert c.stop.point == pytest.approx((545.0, 460.0))


def test_open_area_stop_on_shared_edge_pushed_into_corridor(plan):
    b = _by_id(plan, "B")
    assert b.stop.point[0] == pytest.approx(1500.0, abs=1.0)
    assert b.stop.point[1] == pytest.approx(540.0, abs=1.0)
    assert plan.corridor.covers(Point(b.stop.point))


def test_entrance_snapped_into_corridor(plan):
    assert plan.entrance[0] == pytest.approx(1500.0, abs=1.0)
    assert plan.entrance[1] == pytest.approx(460.0, abs=1.0)


def test_dwell_by_type():
    assert pm.dwell_for("Conference") == 3.0
    assert pm.dwell_for("Office - Non Receiving Guests") == 2.0
    assert pm.dwell_for("Kitchen") == 2.0
    assert pm.dwell_for("Storage Room") == 1.5
    assert pm.dwell_for(None) == 1.5


def test_room_info_fields(plan):
    a = _by_id(plan, "A")
    assert a.area_m2 == pytest.approx(32.0)
    assert (a.head_count, a.assigned_hc, a.department_id) == (4, 3, 1)


def test_glance_targets_only_for_enclosed_rooms(plan):
    looks = {t[1] for t in plan.glance_targets}
    assert _by_id(plan, "A").label_point in looks
    assert _by_id(plan, "B").label_point not in looks


def test_flipped_negates_y(plan):
    f = pm.flipped(plan)
    assert _by_id(f, "A").stop.point == pytest.approx((350.0, -540.0))
    assert f.entrance[1] == pytest.approx(-plan.entrance[1])
    assert f.corridor.bounds[1] == pytest.approx(-600.0)


def test_room_at(plan):
    assert pm.room_at(plan, (100, 900)).id == "A"
    assert pm.room_at(plan, (100, 500)) is None


def test_no_circulation_returns_none():
    assert pm.build_plan_model({**DATA, "circulation": None}, U) is None


def test_plan_to_json_shape(plan):
    js = pm.plan_to_json(plan)
    assert set(js) == {"corridor", "rooms", "entrance", "default_tour_types"}
    r = js["rooms"][0]
    assert {"id", "name", "type", "area_m2", "head_count", "assigned_hc",
            "department_id", "polygon", "label_point", "is_open", "stop"} <= set(r)
    assert "Storage Room" not in js["default_tour_types"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/c/Users/kevin/revit-walkthrough-v2/.worktrees/qbiq-design-json/backend" && "C:/Users/kevin/revit-walkthrough-v2/.venv/Scripts/python.exe" -m pytest tests/test_plan_model.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'plan_model'`.

- [ ] **Step 3: Implement `backend/plan_model.py`**

```python
"""Semantic model of a qbiq design JSON: corridor, rooms, stops, entrance, glances."""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from shapely.affinity import scale
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import nearest_points, polylabel, unary_union

import qbiq_extractor as qe

log = logging.getLogger(__name__)

STOP_OFFSET_M = 0.6
GLANCE_RADIUS_M = 1.2
GLANCE_SPACING_M = 2.0
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
    glance_targets: tuple
    units_to_metres: float


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
    best = min(
        ((corridor.distance(Point(c)), Point(c).distance(poly.centroid), c)
         for door in doors for c in _door_candidates(door, offset)),
        key=lambda t: (round(t[0], 6), t[1]),
    )
    warning = "door does not open onto the corridor" if best[0] > offset / 2 else None
    return Stop(_into(inner, corridor, best[2]), label, dwell, warning)


def _open_stop(poly, corridor, inner, label, dwell) -> Stop:
    """Stop on the corridor edge shared with an open area, nearest its centre."""
    shared = poly.boundary.intersection(corridor.buffer(1e-6))
    if shared.is_empty:
        p = nearest_points(inner, Point(label))[0]
        return Stop((p.x, p.y), label, dwell, "open area does not touch the corridor")
    edge_pt = nearest_points(shared, Point(label))[0]
    p = nearest_points(inner, edge_pt)[0]
    return Stop((p.x, p.y), label, dwell)


def _front_samples(poly, corridor, spacing: float, tol: float) -> list:
    """Points every `spacing` along a room's edges that face the corridor."""
    near = corridor.buffer(tol)
    ring = LineString(poly.exterior.coords)
    steps = max(int(ring.length // spacing), 1)
    return [(p.x, p.y) for i in range(steps + 1)
            if near.covers(p := ring.interpolate(i * spacing))]


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
    stop = (_open_stop(poly, corridor, inner, label, dwell) if is_open or not parsed.doors
            else _door_stop(poly, parsed.doors, corridor, inner, offset, label, dwell))
    if stop.warning:
        log.warning("plan model: room %s (%s): %s", raw.get("id"), raw.get("space_type"), stop.warning)
    return PlanRoom(str(raw.get("id")), raw.get("space_type"), raw.get("subtype"),
                    poly.area * u * u, raw.get("head_count"), raw.get("assigned_hc"),
                    raw.get("department_id"), poly, is_open, label, stop)


def _glances(rooms: list, corridor, u: float) -> tuple:
    """(point, look_at) targets along enclosed rooms' corridor-facing fronts."""
    spacing, tol = GLANCE_SPACING_M / u, FRONT_TOL_M / u
    return tuple((pt, r.label_point) for r in rooms if not r.is_open
                 for pt in _front_samples(r.polygon, corridor, spacing, tol))


def build_plan_model(data: dict, units_to_metres: float) -> PlanModel | None:
    """Semantic plan model from a design JSON; None when it has no circulation."""
    if (corridor := _corridor(data)) is None:
        log.warning("plan model: no top-level 'circulation' polygon — corridor routing unavailable")
        return None
    u = units_to_metres
    inner = _inner(corridor, STOP_OFFSET_M / u)
    rooms = [pr for raw in data.get("rooms") or [] if isinstance(raw, dict)
             if (parsed := qe._room(raw)) and (pr := _plan_room(raw, parsed, corridor, inner, u))]
    nfp = data.get("nfp_data") or {}
    me = qe._wkt(nfp.get("main_entrance"))
    entrance = _into(inner, corridor, (me.x, me.y)) if me is not None and me.geom_type == "Point" else None
    columns = [pl for g in qe._wkt_many(nfp.get("columns")) for pl in qe._polylines(g)]
    return PlanModel(corridor, columns, tuple(rooms), entrance, _glances(rooms, corridor, u), u)


def _fy(pt) -> tuple:
    return (pt[0], -pt[1])


def flipped(plan: PlanModel) -> PlanModel:
    """The same plan in display space (y negated)."""
    flip = lambda g: scale(g, 1, -1, origin=(0, 0))  # noqa: E731
    rooms = tuple(replace(r, polygon=flip(r.polygon), label_point=_fy(r.label_point),
                          stop=replace(r.stop, point=_fy(r.stop.point), look_at=_fy(r.stop.look_at)))
                  for r in plan.rooms)
    return replace(plan, corridor=flip(plan.corridor),
                   columns=[[_fy(p) for p in pl] for pl in plan.columns], rooms=rooms,
                   entrance=_fy(plan.entrance) if plan.entrance else None,
                   glance_targets=tuple((_fy(a), _fy(b)) for a, b in plan.glance_targets))


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: same command as Step 2. Expected: `13 passed`. If `test_enclosed_room_stop_in_corridor_in_front_of_door` reports a stop not at exactly (350, 540), check that `qe._room` trimmed the door to (300,600)-(400,600) — if the extractor trims differently, assert against its midpoint ± 60 in y rather than changing `_door_stop`.

- [ ] **Step 5: flake8 and full suite**

Run: `"C:/Users/kevin/revit-walkthrough-v2/.venv/Scripts/python.exe" -m flake8 plan_model.py tests/test_plan_model.py --extend-ignore=W292,W391,E302,E501` (clean) and `-m pytest -q` (all pass).

- [ ] **Step 6: Report the commit command (controller commits)**

```bash
git add backend/plan_model.py backend/tests/test_plan_model.py
git commit -m "feat(plan): semantic PlanModel for qbiq design JSON (corridor, rooms, stops)"
```

---

### Task 2: Build and cache the plan at upload

**Files:**
- Modify: `backend/qbiq_extractor.py` (add `extract_qbiq_design_with_plan`)
- Modify: `backend/app.py` (cache `_LAST_PLAN`, return `plan` in the design upload response, clear it on every other upload/demo)
- Test: `backend/tests/test_app_plan_cache.py`

**Interfaces:**
- Consumes: `plan_model.build_plan_model`, `flipped`, `plan_to_json`.
- Produces:
  - `qbiq_extractor.extract_qbiq_design_with_plan(json_path, level_name="L-0") -> tuple[LevelGeometry, PlanModel | None]` (reads the JSON once); `extract_qbiq_design` becomes a thin wrapper returning only the geometry.
  - `app._LAST_PLAN: PlanModel | None` — **display space**.
  - `_load_2d_geometry(geo, clear_ifc, plan=None)` — sets `_LAST_PLAN = plan` (None for every non-design caller) and adds `"plan": plan_to_json(plan) if plan else None` to the response.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_app_plan_cache.py`:
```python
import io
import json

import pytest

import app as app_module
from tests.test_plan_model import DATA


def _design_json():
    data = json.loads(json.dumps(DATA))
    data["nfp_data"].update({
        "fill": "POLYGON ((0 0, 2000 0, 2000 1000, 0 1000, 0 0))",
        "walls": [{"corner1": [0, 0], "corner2": [2000, 0]}],
        "interior_walls": [], "cores": [], "windows": [], "columns": None,
    })
    return io.BytesIO(json.dumps(data).encode())


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_design_upload_returns_and_caches_display_space_plan(client):
    r = client.post("/api/upload-qbiq-design", data={"json_file": (_design_json(), "d.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    plan = r.get_json()["plan"]
    assert plan and len(plan["rooms"]) == 4
    a = next(x for x in plan["rooms"] if x["id"] == "A")
    assert a["stop"]["point"][1] == pytest.approx(-540.0)   # display space
    assert app_module._LAST_PLAN is not None
    assert app_module._LAST_PLAN.entrance[1] == pytest.approx(-460.0, abs=1.0)


def test_demo_clears_plan(client):
    client.post("/api/upload-qbiq-design", data={"json_file": (_design_json(), "d.json")},
                content_type="multipart/form-data")
    r = client.get("/api/demo")
    assert r.status_code == 200
    assert r.get_json()["plan"] is None
    assert app_module._LAST_PLAN is None
```

- [ ] **Step 2: Run to verify failure**

Run: `-m pytest tests/test_app_plan_cache.py -q` → FAIL (`KeyError: 'plan'` / `AttributeError: _LAST_PLAN`).

- [ ] **Step 3: Implement**

In `backend/qbiq_extractor.py`, split the current `extract_qbiq_design` body:
```python
def extract_qbiq_design_with_plan(json_path: str, level_name: str = "L-0"):
    """Design JSON -> (LevelGeometry, PlanModel | None), reading the file once."""
    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    geo = _design_geometry(data, json_path, level_name)
    return geo, build_plan_model(data, geo.units_to_metres)


def extract_qbiq_design(json_path: str, level_name: str = "L-0") -> LevelGeometry:
    """Parse a single-file qbiq design JSON (WKT geometry in cm) into a LevelGeometry."""
    return extract_qbiq_design_with_plan(json_path, level_name)[0]
```
where `_design_geometry(data, json_path, level_name)` is the existing body of `extract_qbiq_design` from the `is_qbiq_design` check down to `return LevelGeometry(...)` (unchanged). Import at module bottom-safe position to avoid a cycle: `from plan_model import build_plan_model` inside `extract_qbiq_design_with_plan` (plan_model imports qbiq_extractor at module level).

In `backend/app.py`:
```python
from plan_model import flipped, plan_to_json
from qbiq_extractor import extract_qbiq, extract_qbiq_design_with_plan

_LAST_PLAN = None  # display-space PlanModel of the last design-JSON upload, else None
```
Change `_load_2d_geometry(geo, clear_ifc)` to `_load_2d_geometry(geo, clear_ifc, plan=None)`: add `_LAST_PLAN` to its `global` statement, set `_LAST_PLAN = plan`, and add `"plan": plan_to_json(plan) if plan else None,` to the returned JSON. In `upload_qbiq_design`:
```python
            geo, plan = extract_qbiq_design_with_plan(str(json_fpath), level_name)
    ...
    return _load_2d_geometry(geo, clear_ifc=True, plan=flipped(plan) if plan else None)
```
`/api/upload-3d` (IFC add-on) leaves `_LAST_PLAN` untouched only if it was None; set `_LAST_PLAN = None` there too (an IFC changes the obstacle set the plan was built for).

- [ ] **Step 4: Run** `-m pytest tests/test_app_plan_cache.py -q` → `2 passed`; then full `-m pytest -q` → all pass (existing design-upload tests must still pass; if one asserts the exact response keys, add `plan`).

- [ ] **Step 5: flake8** on `qbiq_extractor.py app.py tests/test_app_plan_cache.py` — no new findings (app.py has pre-existing ones; report only new).

- [ ] **Step 6: Report commit command**

```bash
git add backend/qbiq_extractor.py backend/app.py backend/tests/test_app_plan_cache.py
git commit -m "feat(plan): build and cache the plan model on design upload"
```

---

### Task 3: Corridor-only routing with room snapping and stops

**Files:**
- Create: `backend/plan_routing.py`
- Modify: `backend/app.py` (`/api/autopath` uses the plan when `_LAST_PLAN` is set)
- Test: `backend/tests/test_plan_routing.py`

**Interfaces:**
- Consumes: display-space `PlanModel`; `corridor_graph.compute_bounds`, `build_walkable_polygon`, `build_corridor_graph`, `route_multi`; `route_processor.smooth_preview`; `qbiq_extractor._to_segments`; `plan_model.room_at`.
- Produces:
  - `class CorridorBlocked(Exception)`
  - `corridor_graph_for(plan, clearance_m) -> (polygon | None, graph | None)`
  - `snap_points(plan, points) -> tuple[list[tuple], list[dict | None]]`
  - `stop_meta(room) -> dict` = `{"room_id", "room_name", "look_at", "dwell_s"}`
  - `contain_spline(waypoints, corridor, smoothing, max_rounds=6) -> list`
  - `route_on_plan(plan, points, get_graph, clearance_m=0.2, smoothing=1.0, metas=None) -> {"waypoints": [[x,y],...], "stops": [{"index", **meta}]}` (raises `CorridorBlocked`)

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_plan_routing.py`:
```python
import pytest
from shapely.geometry import Point

import plan_model as pm
import plan_routing as pr
from route_processor import smooth_preview
from tests.test_plan_model import DATA


@pytest.fixture(scope="module")
def plan():
    return pm.flipped(pm.build_plan_model(DATA, 0.01))


@pytest.fixture(scope="module")
def get_graph(plan):
    cache = {}
    def get(c):
        if c not in cache:
            cache[c] = pr.corridor_graph_for(plan, c)
        return cache[c]
    return get


def _inside(plan, pt):
    return plan.corridor.buffer(1e-6).covers(Point(pt))


def test_snap_corridor_point_unchanged(plan):
    pts, metas = pr.snap_points(plan, [(100, -500)])
    assert pts == [(100, -500)] and metas == [None]


def test_snap_room_click_goes_to_its_stop(plan):
    pts, metas = pr.snap_points(plan, [(100, -900)])           # inside room A
    a = next(r for r in plan.rooms if r.id == "A")
    assert pts[0] == pytest.approx(a.stop.point)
    assert metas[0]["room_id"] == "A" and metas[0]["dwell_s"] == 3.0
    assert metas[0]["look_at"] == pytest.approx(list(a.stop.look_at))


def test_snap_outside_goes_to_nearest_corridor(plan):
    pts, _ = pr.snap_points(plan, [(2500, -500)])
    assert _inside(plan, pts[0])


def test_route_stays_in_corridor_and_spline_too(plan, get_graph):
    out = pr.route_on_plan(plan, [(50, -500), (100, -900), (1500, -900), (1950, -500)], get_graph)
    wps = out["waypoints"]
    assert all(_inside(plan, p) for p in wps)
    assert all(_inside(plan, p) for p in smooth_preview(wps, smoothing=1.0))


def test_stops_attached_in_order(plan, get_graph):
    out = pr.route_on_plan(plan, [(50, -500), (100, -900), (1500, -900), (1950, -500)], get_graph)
    assert [s["room_id"] for s in out["stops"]] == ["A", "B"]
    idx = [s["index"] for s in out["stops"]]
    assert idx == sorted(idx)
    a = next(r for r in plan.rooms if r.id == "A")
    assert out["waypoints"][idx[0]] == pytest.approx(list(a.stop.point), abs=1.0)


def test_blocked_corridor_raises(plan):
    with pytest.raises(pr.CorridorBlocked, match="corridor blocked near"):
        pr.route_on_plan(plan, [(50, -500), (1950, -500)], lambda c: (None, None))


def test_contain_spline_inserts_points_until_inside(plan):
    corridor = plan.corridor
    zig = [(50, -410), (1000, -590), (1950, -410)]
    out = pr.contain_spline(zig, corridor, smoothing=1.0)
    assert len(out) >= len(zig)
    assert all(corridor.buffer(1e-6).covers(Point(p)) for p in smooth_preview(out, smoothing=1.0))
```

- [ ] **Step 2: Run to verify failure** — `-m pytest tests/test_plan_routing.py -q` → `ModuleNotFoundError: plan_routing`.

- [ ] **Step 3: Implement `backend/plan_routing.py`**

```python
"""Corridor-only Smart Path routing on a display-space PlanModel."""
from __future__ import annotations

import logging
import math

from shapely.geometry import Point
from shapely.ops import nearest_points

from corridor_graph import build_corridor_graph, build_walkable_polygon, compute_bounds, route_multi
from plan_model import room_at
from qbiq_extractor import _to_segments
from route_processor import smooth_preview

log = logging.getLogger(__name__)

_COVER_TOL = 1e-6


class CorridorBlocked(Exception):
    """The corridor does not connect the requested points at any clearance."""


def _polys(geom) -> list:
    return list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]


def corridor_graph_for(plan, clearance_m: float):
    """(walkable polygon, corridor graph) for the corridor shrunk by clearance."""
    polys = _polys(plan.corridor)
    exteriors = [list(p.exterior.coords) for p in polys]
    holes = [list(r.coords) for p in polys for r in p.interiors]
    walls = _to_segments(exteriors + holes)
    bounds = compute_bounds(walls, exteriors)
    polygon = build_walkable_polygon(walls, [], holes + plan.columns, exteriors, bounds,
                                     clearance_m=clearance_m, units_to_metres=plan.units_to_metres)
    graph = build_corridor_graph(polygon, [], units_to_metres=plan.units_to_metres) if polygon is not None else None
    return polygon, graph


def stop_meta(room) -> dict:
    """Waypoint stop metadata for a room."""
    return {"room_id": room.id, "room_name": room.space_type or "Room",
            "look_at": list(room.stop.look_at), "dwell_s": room.stop.dwell_s}


def snap_points(plan, points) -> tuple:
    """Corridor points unchanged; room clicks -> room stop; anything else -> nearest corridor point."""
    covered = plan.corridor.buffer(_COVER_TOL)
    snapped, metas = [], []
    for raw in points:
        p = (float(raw[0]), float(raw[1]))
        if covered.covers(Point(p)):
            snapped.append(p)
            metas.append(None)
        elif room := room_at(plan, p):
            snapped.append(tuple(room.stop.point))
            metas.append(stop_meta(room))
        else:
            q = nearest_points(plan.corridor, Point(p))[0]
            snapped.append((q.x, q.y))
            metas.append(None)
    return snapped, metas


def _seg_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / max(dx * dx + dy * dy, 1e-12)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def contain_spline(waypoints: list, corridor, smoothing: float, max_rounds: int = 6) -> list:
    """Insert leg midpoints until the smoothed path stays inside the corridor."""
    covered = corridor.buffer(_COVER_TOL)
    wps = [tuple(p) for p in waypoints]
    for _ in range(max_rounds):
        bad = {min(range(len(wps) - 1), key=lambda i: _seg_dist(s, wps[i], wps[i + 1]))
               for s in smooth_preview(wps, smoothing=smoothing) if not covered.covers(Point(s))}
        if not bad:
            break
        for i in sorted(bad, reverse=True):
            a, b = wps[i], wps[i + 1]
            wps.insert(i + 1, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    return [list(p) for p in wps]


def _attach(waypoints: list, snapped: list, metas: list) -> list:
    """Stop entries pinned to the waypoint nearest each stop point, in order."""
    stops, start = [], 0
    for pt, meta in zip(snapped, metas):
        if not meta:
            continue
        idx = min(range(start, len(waypoints)),
                  key=lambda i: math.hypot(waypoints[i][0] - pt[0], waypoints[i][1] - pt[1]))
        stops.append({"index": idx, **meta})
        start = idx
    return stops


def route_on_plan(plan, points, get_graph, clearance_m: float = 0.2, smoothing: float = 1.0,
                  metas: list | None = None) -> dict:
    """Corridor-only route through ordered points; raises CorridorBlocked when unconnected."""
    snapped, snapped_metas = snap_points(plan, points)
    metas = [m or s for m, s in zip(metas, snapped_metas)] if metas else snapped_metas
    max_pts = max(12, 3 * len(snapped))
    for c in (clearance_m, clearance_m / 2, 0.05):
        polygon, graph = get_graph(round(c, 3))
        if graph is None:
            continue
        if wps := route_multi(snapped, graph, polygon, max_pts=max_pts):
            wps = contain_spline(wps, plan.corridor, smoothing)
            return {"waypoints": wps, "stops": _attach(wps, snapped, metas)}
    x, y = snapped[0]
    raise CorridorBlocked(f"corridor blocked near ({x:.0f}, {y:.0f})")
```

In `backend/app.py`:
```python
from plan_routing import CorridorBlocked, corridor_graph_for, route_on_plan

_LAST_PLAN_GRAPH: dict = {}


def _plan_graph(clearance_m: float):
    """Cached corridor graph of the current plan at a clearance."""
    key = (_UPLOAD_GENERATION, round(clearance_m, 3))
    if key not in _LAST_PLAN_GRAPH:
        try:
            _LAST_PLAN_GRAPH[key] = corridor_graph_for(_LAST_PLAN, clearance_m)
        except Exception:
            log.exception("Plan corridor graph build failed")
            _LAST_PLAN_GRAPH[key] = (None, None)
    return _LAST_PLAN_GRAPH[key]
```
Clear `_LAST_PLAN_GRAPH` wherever `_LAST_CIRC_GRAPH.clear()` is called (in `_load_2d_geometry` and `upload_3d`). In `autopath()`, right after `points` is resolved and before the existing obstacle logic:
```python
    if _LAST_PLAN is not None and not data.get("walls"):
        try:
            return jsonify(route_on_plan(_LAST_PLAN, points, _plan_graph,
                                         clearance_m=float(data.get("clearance_m", 0.2)),
                                         smoothing=float(data.get("smoothing", 1.0))))
        except CorridorBlocked as e:
            return _err(str(e))
```

- [ ] **Step 4: Run** `-m pytest tests/test_plan_routing.py -q` → `7 passed`; full suite passes.
- [ ] **Step 5: flake8** clean on `plan_routing.py tests/test_plan_routing.py`, no new findings in `app.py`.
- [ ] **Step 6: Report commit command**

```bash
git add backend/plan_routing.py backend/app.py backend/tests/test_plan_routing.py
git commit -m "feat(plan): corridor-only Smart Path with room stops"
```

---

### Task 4: Auto tour

**Files:**
- Create: `backend/plan_tour.py`
- Modify: `backend/app.py` (`POST /api/auto-tour`)
- Test: `backend/tests/test_plan_tour.py`

**Interfaces:**
- Consumes: `corridor_graph._snap_to_nearest_edge`; `plan_routing.route_on_plan`, `stop_meta`; `plan_model.BACK_OF_HOUSE`.
- Produces:
  - `order_stops(dist: list[list[float]]) -> list[int]` — visiting order of indices 1..n-1 reachable from 0 (index 0 = start), NN then 2-opt on an open path with fixed start.
  - `build_tour(plan, graph, polygon, get_graph, room_types=None, clearance_m=0.2, smoothing=1.0) -> dict` = `{"waypoints", "stops", "suggested_duration_s", "unreachable": [room names]}`.
  - `POST /api/auto-tour` body `{room_types?: [str], clearance_m?, smoothing?}` → that dict; 400 when no plan is loaded or the corridor is blocked.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_plan_tour.py`:
```python
import math

import pytest

import plan_model as pm
import plan_routing as pr
import plan_tour as pt
from tests.test_plan_model import DATA


@pytest.fixture(scope="module")
def plan():
    return pm.flipped(pm.build_plan_model(DATA, 0.01))


@pytest.fixture(scope="module")
def get_graph(plan):
    cache = {}
    return lambda c: cache.setdefault(c, pr.corridor_graph_for(plan, c))


def _length(order, dist):
    seq = [0] + order
    return sum(dist[a][b] for a, b in zip(seq, seq[1:]))


def test_order_stops_beats_naive_and_visits_each_once():
    pts = [(0, 0), (10, 0), (1, 0), (9, 0), (2, 0)]
    dist = [[math.dist(a, b) for b in pts] for a in pts]
    order = pt.order_stops(dist)
    assert sorted(order) == [1, 2, 3, 4]
    assert _length(order, dist) <= _length([1, 2, 3, 4], dist)
    assert _length(order, dist) == pytest.approx(10.0)


def test_order_stops_skips_unreachable():
    inf = math.inf
    dist = [[0, 1, inf], [1, 0, inf], [inf, inf, 0]]
    assert pt.order_stops(dist) == [1]


def test_tour_default_types_exclude_back_of_house(plan, get_graph):
    polygon, graph = get_graph(0.2)
    tour = pt.build_tour(plan, graph, polygon, get_graph)
    ids = [s["room_id"] for s in tour["stops"]]
    assert "C" not in ids                      # Storage Room is back-of-house
    assert sorted(ids) == ["A", "B", "D"]
    assert len(ids) == len(set(ids))


def test_tour_starts_at_entrance_and_sets_duration(plan, get_graph):
    polygon, graph = get_graph(0.2)
    tour = pt.build_tour(plan, graph, polygon, get_graph)
    assert tour["waypoints"][0] == pytest.approx(list(plan.entrance), abs=1.0)
    assert tour["suggested_duration_s"] >= 10 and tour["suggested_duration_s"] % 5 == 0
    assert tour["unreachable"] == []


def test_tour_respects_requested_types(plan, get_graph):
    polygon, graph = get_graph(0.2)
    tour = pt.build_tour(plan, graph, polygon, get_graph, room_types=["Storage Room"])
    assert [s["room_id"] for s in tour["stops"]] == ["C"]
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: plan_tour`.

- [ ] **Step 3: Implement `backend/plan_tour.py`**

```python
"""Auto tour: entrance -> every selected room's stop, in a short corridor order."""
from __future__ import annotations

import logging
import math

import networkx as nx

from corridor_graph import _snap_to_nearest_edge
from plan_model import BACK_OF_HOUSE
from plan_routing import route_on_plan, stop_meta

log = logging.getLogger(__name__)

WALK_SPEED_MPS = 1.0
MIN_TOUR_S = 10


def _path_len(seq: list, dist: list) -> float:
    return sum(dist[a][b] for a, b in zip(seq, seq[1:]))


def _two_opt(seq: list, dist: list) -> list:
    """Improve an open path with fixed start by segment reversals."""
    improved = True
    while improved:
        improved = False
        for i in range(1, len(seq) - 1):
            for j in range(i + 1, len(seq)):
                cand = seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:]
                if _path_len(cand, dist) < _path_len(seq, dist) - 1e-9:
                    seq, improved = cand, True
    return seq


def order_stops(dist: list) -> list:
    """Visiting order of stops 1..n-1 reachable from 0: nearest-neighbour then 2-opt."""
    todo = {j for j in range(1, len(dist)) if math.isfinite(dist[0][j])}
    seq = [0]
    while todo:
        nxt = min(todo, key=lambda j: dist[seq[-1]][j])
        seq.append(nxt)
        todo.discard(nxt)
    return _two_opt(seq, dist)[1:]


def _distances(graph, points: list) -> list:
    """All-pairs corridor distances between points snapped onto a graph copy."""
    g = graph.copy()
    nodes = [_snap_to_nearest_edge(g, tuple(p)) for p in points]
    lengths = [nx.single_source_dijkstra_path_length(g, n, weight="weight") for n in nodes]
    return [[lengths[i].get(nodes[j], math.inf) for j in range(len(nodes))] for i in range(len(nodes))]


def _route_length_m(waypoints: list, u: float) -> float:
    return sum(math.dist(a, b) for a, b in zip(waypoints, waypoints[1:])) * u


def build_tour(plan, graph, polygon, get_graph, room_types=None, clearance_m: float = 0.2,
               smoothing: float = 1.0) -> dict:
    """Ordered corridor tour from the entrance through each selected room's stop."""
    types = set(room_types) if room_types else {r.space_type for r in plan.rooms} - BACK_OF_HOUSE
    rooms = [r for r in plan.rooms if r.space_type in types]
    start = plan.entrance or rooms[0].stop.point
    dist = _distances(graph, [start] + [r.stop.point for r in rooms])
    order = order_stops(dist)
    unreachable = [r.space_type or r.id for j, r in enumerate(rooms, 1) if j not in order]
    visit = [rooms[j - 1] for j in order]
    routed = route_on_plan(plan, [start] + [r.stop.point for r in visit], get_graph,
                           clearance_m=clearance_m, smoothing=smoothing,
                           metas=[None] + [stop_meta(r) for r in visit])
    seconds = (_route_length_m(routed["waypoints"], plan.units_to_metres) / WALK_SPEED_MPS
               + sum(s["dwell_s"] for s in routed["stops"]))
    if unreachable:
        log.warning("auto tour: %d room(s) unreachable from the entrance: %s", len(unreachable), unreachable)
    return {**routed, "suggested_duration_s": max(MIN_TOUR_S, 5 * math.ceil(seconds / 5)),
            "unreachable": unreachable}
```

In `backend/app.py`:
```python
from plan_tour import build_tour


@app.route("/api/auto-tour", methods=["POST"])
def auto_tour():
    """Auto walkthrough of the loaded design plan."""
    if _LAST_PLAN is None:
        return _err("Auto tour needs a qbiq design JSON to be loaded")
    data = request.get_json(force=True) or {}
    clearance_m = float(data.get("clearance_m", 0.2))
    polygon, graph = _plan_graph(clearance_m)
    if graph is None:
        return _err("The corridor is too narrow to route at this clearance")
    try:
        return jsonify(build_tour(_LAST_PLAN, graph, polygon, _plan_graph,
                                  room_types=data.get("room_types"), clearance_m=clearance_m,
                                  smoothing=float(data.get("smoothing", 1.0))))
    except CorridorBlocked as e:
        return _err(str(e))
```

- [ ] **Step 4: Run** `-m pytest tests/test_plan_tour.py -q` → `5 passed`; full suite passes.
- [ ] **Step 5: flake8** clean on new files.
- [ ] **Step 6: Report commit command**

```bash
git add backend/plan_tour.py backend/app.py backend/tests/test_plan_tour.py
git commit -m "feat(plan): auto tour from the entrance through selected rooms"
```

---

### Task 5: Room-aware camera (stops + glances)

**Files:**
- Modify: `backend/route_processor.py`
- Modify: `backend/app.py` (`/api/process-route`, `/api/export/json`, `/api/export/xml` pass full waypoints + plan glances)
- Test: `backend/tests/test_camera_stops.py`

**Interfaces:**
- Consumes: waypoint 5th element `stop` dict; display-space `_LAST_PLAN.glance_targets`, `plan_model.GLANCE_RADIUS_M`.
- Produces: `process_route(..., glances: list | None = None, glance_radius: float = 0.0)`; constants `GLANCE_MAX_DEG = 30.0`, `GLANCE_TURN_SUPPRESS_DEG = 45.0`, `MAX_DWELL_FRACTION = 0.5`, `MIN_DWELL_S = 0.6`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_camera_stops.py`:
```python
import math

import pytest

import route_processor as rp

FPS = 30.0


def _wrap(d):
    return (d + 180) % 360 - 180


def _route(stop=None, duration=20.0, glances=None, radius=0.0):
    wps = [(0, 0, 0, ""), (500, 0, 0, "", stop), (1000, 0, 0, "")]
    return rp.process_route(wps, total_duration=duration, fps=FPS, glances=glances, glance_radius=radius)


def test_dwell_freezes_position_and_faces_room():
    frames = _route({"look_at": [500, 400], "dwell_s": 3.0})
    xs = [(round(f.x, 6), round(f.y, 6)) for f in frames]
    longest = max(sum(1 for _ in g) for _, g in __import__("itertools").groupby(xs))
    assert longest >= int(3.0 * FPS) - 2
    held = [f for f in frames if abs(f.x - 500) < 30 and abs(f.y) < 1e-6]
    assert any(abs(_wrap(f.yaw - 90.0)) < 2.0 for f in held)


def test_turn_rate_never_exceeds_cap():
    frames = _route({"look_at": [500, -400], "dwell_s": 3.0})
    step = rp._MAX_YAW_RATE_DEG_PER_SEC / FPS + 1e-6
    assert all(abs(_wrap(b.yaw - a.yaw)) <= step for a, b in zip(frames, frames[1:]))


def test_total_duration_respected():
    frames = _route({"look_at": [500, 400], "dwell_s": 3.0}, duration=20.0)
    assert len(frames) == pytest.approx(20.0 * FPS, abs=3)
    assert frames[0].t == 0.0 and frames[-1].t == pytest.approx(1.0)


def test_dwells_capped_at_half_duration():
    frames = _route({"look_at": [500, 400], "dwell_s": 50.0}, duration=10.0)
    xs = [(round(f.x, 6), round(f.y, 6)) for f in frames]
    longest = max(sum(1 for _ in g) for _, g in __import__("itertools").groupby(xs))
    assert longest <= int(0.5 * 10.0 * FPS) + 2


def test_glance_bounded_and_toward_room():
    base = _route(duration=10.0)
    glanced = _route(duration=10.0, glances=[((500, 50), (500, 400))], radius=120)
    diffs = [_wrap(g.yaw - b.yaw) for g, b in zip(glanced, base)]
    assert max(abs(d) for d in diffs) <= rp.GLANCE_MAX_DEG + 1e-6
    assert max(diffs) > 5.0          # turned left (toward +y) near x=500


def test_glance_suppressed_while_turning():
    wps = [(0, 0, 0, ""), (500, 0, 0, ""), (500, 500, 0, "")]
    base = rp.process_route(wps, total_duration=10.0, fps=FPS)
    glanced = rp.process_route(wps, total_duration=10.0, fps=FPS,
                               glances=[((500, 0), (900, 0))], glance_radius=60)
    corner = [i for i, f in enumerate(base) if math.hypot(f.x - 500, f.y) < 20]
    assert all(abs(_wrap(glanced[i].yaw - base[i].yaw)) < 5.0 for i in corner)


def test_four_element_waypoints_unchanged():
    wps = [(0, 0, 0, ""), (500, 0, 0, ""), (1000, 0, 0, "")]
    a = rp.process_route(wps, total_duration=5.0, fps=FPS)
    assert len(a) == pytest.approx(5.0 * FPS, abs=2)
```

- [ ] **Step 2: Run to verify failure** — `TypeError: process_route() got an unexpected keyword argument 'glances'`.

- [ ] **Step 3: Implement in `backend/route_processor.py`**

Add constants near `_MAX_YAW_RATE_DEG_PER_SEC`:
```python
GLANCE_MAX_DEG = 30.0
GLANCE_TURN_SUPPRESS_DEG = 45.0
MAX_DWELL_FRACTION = 0.5
MIN_DWELL_S = 0.6
```
`process_route` gains `glances: Optional[list] = None, glance_radius: float = 0.0`; parse stops alongside yaw offsets and slice them per segment exactly like `yaw_offsets`:
```python
    stops = [p[4] if len(p) > 4 and isinstance(p[4], dict) and p[4].get("look_at") else None
             for p in waypoints]
```
pass `stops[s:e+1], glances, glance_radius` into every `_process_segment` call.

`_process_segment` gains `stops=None, glances=None, glance_radius=0.0`:
```python
    stops = stops or [None] * len(xy_pts)
    dwells = _scaled_dwells([float(s.get("dwell_s", 0.0)) if s else 0.0 for s in stops], total_duration)
    move_duration = max(total_duration - sum(dwells), total_duration * 0.1)
    ...
    n_frames   = max(2, int(move_duration * fps))
    resampled  = _resample(smooth_pts, n_frames)
    frames     = _build_frames(resampled, camera_height, move_duration, fov, glances, glance_radius)
    if any(o != 0.0 for o in yaw_offsets):
        _apply_yaw_offsets(frames, xy_pts, yaw_offsets)
    if any(dwells):
        frames = _insert_dwells(frames, xy_pts, stops, dwells, fps)
    return frames
```
New helpers:
```python
def _scaled_dwells(dwells: list, total_duration: float) -> list:
    """Dwells scaled down so they take at most MAX_DWELL_FRACTION of the video."""
    cap, total = MAX_DWELL_FRACTION * total_duration, sum(dwells)
    if total <= cap or total <= 0:
        return dwells
    f = cap / total
    return [max(d * f, MIN_DWELL_S) if d > 0 else 0.0 for d in dwells]


def _dwell_frames(f: CameraFrame, look_at, dwell_s: float, fps: float) -> list:
    """Frames holding position while turning toward look_at, holding, and turning back."""
    n = max(1, int(round(dwell_s * fps)))
    step = _MAX_YAW_RATE_DEG_PER_SEC / fps
    target = math.degrees(math.atan2(look_at[1] - f.y, look_at[0] - f.x))
    delta = (target - f.yaw + 180) % 360 - 180
    reach = math.copysign(min(abs(delta), step * (n // 2)), delta)
    turn = int(math.ceil(abs(reach) / step)) if reach else 0
    yaws = ([f.yaw + reach * (i + 1) / turn for i in range(turn)]
            + [f.yaw + reach] * (n - 2 * turn)
            + [f.yaw + reach * (turn - i - 1) / turn for i in range(turn)])
    return [CameraFrame(t=0.0, x=f.x, y=f.y, z=f.z, yaw=y % 360, pitch=f.pitch, fov=f.fov) for y in yaws]


def _insert_dwells(frames: list, wp_xy: list, stops: list, dwells: list, fps: float) -> list:
    """Splice dwell frames in at the frame nearest each stop waypoint, then retime."""
    pos = np.array([[f.x, f.y] for f in frames])
    out, last, k = [], 0, 0
    for (x, y), stop, d in zip(wp_xy, stops, dwells):
        if not stop or d <= 0:
            continue
        k = k + int(np.argmin(np.hypot(pos[k:, 0] - x, pos[k:, 1] - y)))
        out.extend(frames[last:k + 1])
        out.extend(_dwell_frames(frames[k], stop["look_at"], d, fps))
        last = k + 1
    out.extend(frames[last:])
    for i, f in enumerate(out):
        f.t = i / max(len(out) - 1, 1)
    return out


def _apply_glances(pts: np.ndarray, raw_yaw: np.ndarray, glances: list, radius: float, la: int) -> np.ndarray:
    """Blend raw yaw toward nearby rooms (≤ GLANCE_MAX_DEG), suppressed while the path turns."""
    gp = np.array([g[0] for g in glances], dtype=float)
    gl = np.array([g[1] for g in glances], dtype=float)
    out, n = raw_yaw.copy(), len(pts)
    for i in range(n):
        turning = abs((raw_yaw[min(i + la, n - 1)] - raw_yaw[max(i - la, 0)] + 180) % 360 - 180)
        s = max(0.0, 1.0 - turning / GLANCE_TURN_SUPPRESS_DEG)
        d = np.hypot(gp[:, 0] - pts[i, 0], gp[:, 1] - pts[i, 1])
        j = int(np.argmin(d))
        if s <= 0 or d[j] >= radius:
            continue
        target = math.degrees(math.atan2(gl[j, 1] - pts[i, 1], gl[j, 0] - pts[i, 0]))
        delta = (target - raw_yaw[i] + 180) % 360 - 180
        out[i] = raw_yaw[i] + max(-GLANCE_MAX_DEG, min(GLANCE_MAX_DEG, delta)) * (1 - d[j] / radius) * s
    return out
```
`_build_frames(pts, height, duration, fov, glances=None, glance_radius=0.0)`: right after the `raw_yaw` loop, before rate limiting:
```python
    if glances and glance_radius > 0:
        raw_yaw = _apply_glances(pts, raw_yaw, glances, glance_radius, la)
```
In the dwell test the stop waypoint sits on a straight line, so `_dwell_frames` starts from the rate-limited frame yaw; the rate test covers the transition into and out of the dwell (both are ≤ one cap step because the dwell starts and ends at `f.yaw`).

In `backend/app.py` add:
```python
from plan_model import GLANCE_RADIUS_M


def _camera_hints() -> dict:
    """Glance targets of the loaded plan for process_route (empty without a plan)."""
    if _LAST_PLAN is None:
        return {}
    return {"glances": list(_LAST_PLAN.glance_targets),
            "glance_radius": GLANCE_RADIUS_M / _LAST_PLAN.units_to_metres}
```
`/api/process-route`: replace `waypoints=[(p[0], p[1]) for p in wpts]` with `waypoints=wpts` and add `uturn_radius=float(data.get("uturn_radius", 0.0)), **_camera_hints()`. `/api/export/json` and `/api/export/xml`: add `**_camera_hints()` to their `process_route` calls.

- [ ] **Step 4: Run** `-m pytest tests/test_camera_stops.py -q` → `7 passed`; full suite passes (existing route/export tests must stay green).
- [ ] **Step 5: flake8** clean on `route_processor.py`'s new lines and the test file.
- [ ] **Step 6: Report commit command**

```bash
git add backend/route_processor.py backend/app.py backend/tests/test_camera_stops.py
git commit -m "feat(camera): dwell-and-look stops and passing glances into rooms"
```

---

### Task 6: Frontend — stops on waypoints, Smart Path, Auto Tour

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Consumes: upload response `plan` (display space; `plan_to_json` shape), `/api/autopath` response `{waypoints, stops}`, `POST /api/auto-tour` response `{waypoints, stops, suggested_duration_s, unreachable}`.
- Produces: `state.plan`; waypoint objects gain `stop: null | {room_id, room_name, look_at, dwell_s}`; helper `applyRouteResult(data)`; `wpWire(w)`.

- [ ] **Step 1: Waypoint stop field + wire format**

Add `stop: null` to every waypoint-object literal that currently lists `cutAfter:false` (the `push`/`splice`/import/Smart-Path sites near lines 914, 941, 1312, 1350-1352, 1376). Add one serialiser and use it at the three request sites (process-route ~2102, export ~1667, any other `w=>[w.x,w.y,w.yawOffset||0,w.timeOfDay||'']`):
```javascript
const wpWire = w => [w.x, w.y, w.yawOffset || 0, w.timeOfDay || '', w.stop || null];
```
In the JSON/XML path import (~1350), read the 5th element: `stop: Array.isArray(w) ? (w[4] || null) : (w.stop || null)`.

- [ ] **Step 2: Plan state**

In `applyFloorPlan(data)`: `state.plan = data.plan || null;` and toggle the Auto Tour button: `document.getElementById('btn-autotour').hidden = !state.plan;`.

- [ ] **Step 3: Route result helper used by Smart Path**

```javascript
function applyRouteResult(data) {
  const stops = new Map((data.stops || []).map(s => [s.index, s]));
  state.waypoints = data.waypoints.map((p, i) => {
    const s = stops.get(i);
    return { x: p[0], y: p[1], yawOffset: 0, timeOfDay: '', cutAfter: false,
             stop: s ? { room_id: s.room_id, room_name: s.room_name, look_at: s.look_at, dwell_s: s.dwell_s } : null };
  });
  renderRoute(); updateWpList(); enableExport(); refreshSpline();
}
```
In `autopathClick`'s final request body add `smoothing: cam.smo`; replace the `state.waypoints = pts.map(...)` + render lines with `applyRouteResult(data);` (keep the existing empty-route toast; server errors already surface via `data.error`).

- [ ] **Step 4: Your Points shows stops**

In `updateWpList()`'s per-waypoint row template, when `wp.stop` is set add a tag and an editable dwell next to the existing yaw input, using existing row classes:
```javascript
${wp.stop ? `<span class="wp-stop" title="Camera stops and looks into this room">${esc(wp.stop.room_name)}</span>
  <input type="number" class="wp-dwell" min="0.5" max="10" step="0.5" value="${wp.stop.dwell_s}"
         onchange="setWpDwell(${i}, this.value)" title="Seconds the camera spends looking in"/>` : ''}
```
with `function setWpDwell(i, v) { const w = state.waypoints[i]; if (w && w.stop) w.stop.dwell_s = Math.max(0.5, parseFloat(v) || 0.5); }` and an `esc` HTML-escaper if one doesn't already exist. Style `.wp-stop` as a small pill using `--blue` tokens.

- [ ] **Step 5: Auto Tour button + panel**

Next to `#btn-autopath` in the toolbar add `<button class="tb-btn-auto" id="btn-autotour" hidden onclick="toggleTourPanel()">Auto Tour</button>` and a popover `<div id="tour-panel" class="tour-panel" hidden>` containing a checkbox list and a "Generate tour" button. Behaviour:
```javascript
function toggleTourPanel() {
  const panel = document.getElementById('tour-panel');
  if (panel.hidden) renderTourPanel();
  panel.hidden = !panel.hidden;
}

function renderTourPanel() {
  const counts = {};
  state.plan.rooms.forEach(r => { counts[r.type] = (counts[r.type] || 0) + 1; });
  const defaults = new Set(state.plan.default_tour_types);
  document.getElementById('tour-types').innerHTML = Object.keys(counts).sort().map(t =>
    `<label class="tour-type"><input type="checkbox" value="${esc(t)}" ${defaults.has(t) ? 'checked' : ''}/>
     ${esc(t)} <span class="tour-count">${counts[t]}</span></label>`).join('');
  document.getElementById('tour-msg').textContent = '';
}

async function generateTour() {
  const types = [...document.querySelectorAll('#tour-types input:checked')].map(i => i.value);
  if (!types.length) { toast('Pick at least one room type', 'inf'); return; }
  showLoading('Planning the tour through the corridor…');
  try {
    const res = await fetch(`${API}/api/auto-tour`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ room_types: types, smoothing: cam.smo }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed');
    applyRouteResult(data);
    setVideoLength(data.suggested_duration_s);
    document.getElementById('tour-msg').textContent = data.unreachable.length
      ? `Couldn't reach from the entrance: ${data.unreachable.join(', ')}` : '';
    toast(`Tour: ${data.stops.length} rooms, ${data.suggested_duration_s}s`, 'ok');
  } catch (e) { toast('Auto tour error: ' + e.message, 'err'); }
  finally { hideLoading(); }
}
```
`setVideoLength(s)` sets `cam.dur = s` and updates the Video Length slider/value display through the same code path the slider's `oninput` uses (find it near the "Video length" control; if the slider max is below `s`, raise the slider's `max` to `s`).

- [ ] **Step 6: Verify**

Extract the longest inline `<script>` to the scratchpad and `node --check` it. With `curl -s http://localhost:5001/` confirm `applyRouteResult`, `generateTour`, `wpWire` are served. Report: browser click-through owed to the user.

- [ ] **Step 7: Report commit command**

```bash
git add frontend/index.html
git commit -m "feat(frontend): room stops on waypoints, corridor Smart Path, Auto Tour panel"
```

---

### Task 7: Frontend — room labels, tooltip, corridor tint, 3D labels

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Consumes: `state.plan` (display space — same coordinates as the SVG content and waypoints).
- Produces: `renderPlanLayer()`, toolbar toggle `#btn-labels`, `build3DLabels()`.

- [ ] **Step 1: 2D plan layer**

After `initD3(...)` in `applyFloorPlan`, call `renderPlanLayer()`. Read `initD3` first and append the layer inside the same zoom-transformed group that holds the floor-plan SVG content (so it pans/zooms with the plan), below the route layer:
```javascript
function renderPlanLayer() {
  d3.select('#plan-layer').remove();
  if (!state.plan) return;
  const host = planContentGroup();            // the zoomed <g> holding the floor-plan SVG — derive from initD3
  const g = host.insert('g', ':nth-child(2)').attr('id', 'plan-layer');
  const line = pts => 'M' + pts.map(p => p.join(',')).join('L') + 'Z';
  g.selectAll('path.corridor').data(state.plan.corridor).join('path')
    .attr('class', 'corridor').attr('d', line);
  const rooms = g.selectAll('g.room').data(state.plan.rooms).join('g').attr('class', 'room');
  rooms.append('path').attr('class', 'room-hit').attr('d', r => line(r.polygon))
    .on('mousemove', (e, r) => showRoomTip(e, r)).on('mouseleave', hideRoomTip);
  rooms.append('text').attr('class', 'room-label')
    .attr('x', r => r.label_point[0]).attr('y', r => r.label_point[1])
    .attr('font-size', r => Math.max(18, Math.min(60, Math.sqrt(r.area_m2) * 9)) * (1 / Math.max(state.unitsToMetres * 100, 1e-9)))
    .text(r => r.name);
  g.classed('labels-off', !state.showLabels);
}
```
`planContentGroup()` must return the d3 selection of the zoomed group (name it after reading `initD3`). The font size is in plan units: the formula keeps labels ~18–60 cm tall in centimetre plans; adjust the scale factor if the plan isn't in cm (`state.unitsToMetres`). CSS: `.corridor { fill: rgba(47,107,255,.07); stroke: rgba(47,107,255,.25); stroke-width: ...; pointer-events: none }`, `.room-hit { fill: transparent; pointer-events: all }`, `.room-hit:hover { fill: rgba(47,107,255,.06) }`, `.room-label { fill: var(--text-2, #475467); text-anchor: middle; dominant-baseline: middle; pointer-events: none; font-weight: 600 }`, `#plan-layer.labels-off .room-label { display: none }`. Room-hit paths must NOT swallow clicks needed for waypoint placement — in their `click` handler re-dispatch to the canvas handler, or set `pointer-events: none` while in waypoint/Smart Path click modes and only enable hover in idle. Verify clicking inside a room still places a Smart Path point.

- [ ] **Step 2: Tooltip**

A fixed-position `<div id="room-tip" hidden>` styled like existing cards; `showRoomTip(e, r)` fills: name (bold), type, `${r.area_m2} m²`, `Headcount ${r.assigned_hc ?? '–'} / ${r.head_count ?? '–'}`, department, and "Open area" when `r.is_open`; positions at the cursor + 12 px; `hideRoomTip()` hides it. Escape all text with `esc`.

- [ ] **Step 3: Labels toggle**

`state.showLabels = true` default; toolbar button `#btn-labels` (shown only when `state.plan`) toggles it, re-applies `labels-off`, and calls `build3DLabels()`.

- [ ] **Step 4: 3D labels**

```javascript
function build3DLabels() {
  (threeLabels || []).forEach(s => { threeScene.remove(s); s.material.map.dispose(); s.material.dispose(); });
  threeLabels = [];
  if (!threeScene || !state.plan || !state.showLabels) return;
  const u = state.unitsToMetres || 1;
  state.plan.rooms.forEach(r => {
    const c = document.createElement('canvas'); c.width = 512; c.height = 128;
    const x = c.getContext('2d');
    x.font = '600 56px "Plus Jakarta Sans", -apple-system, sans-serif';
    x.fillStyle = 'rgba(255,255,255,.88)'; x.fillRect(0, 0, 512, 128);
    x.fillStyle = '#1d2939'; x.textAlign = 'center'; x.textBaseline = 'middle';
    x.fillText(r.name, 256, 64);
    const tex = new THREE.CanvasTexture(c); tex.encoding = THREE.sRGBEncoding;
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
    s.scale.set(2.4, 0.6, 1);
    s.position.set(r.label_point[0] * u, 3.3, r.label_point[1] * u);   // display y = -model y => three z = y_display * u
    s.renderOrder = 10; threeScene.add(s); threeLabels.push(s);
  });
}
```
Declare `let threeLabels = [];`. Call it at the end of `build3DGeometry()`. In the playback loop, set `threeLabels.forEach(s => s.visible = !p3.playing)` each frame (or on play/pause toggle). Make sure `clear3DGeometry` (which disposes scene children) doesn't double-dispose sprites — exclude `isSprite` there or let `build3DLabels` own them exclusively.

- [ ] **Step 5: Verify**

`node --check` the extracted script; `curl -s http://localhost:5001/ | grep -c "renderPlanLayer\|build3DLabels"`. Report the browser click-through as owed to the user, listing what to look at.

- [ ] **Step 6: Report commit command**

```bash
git add frontend/index.html
git commit -m "feat(frontend): room labels, hover info, corridor tint, 3D labels"
```

---

### Task 8: Real-file verification on both design JSONs

**Files:**
- Test: `backend/tests/test_plan_real_files.py`

**Interfaces:**
- Consumes: `/api/upload-qbiq-design`, `/api/auto-tour`, `/api/autopath`, `/api/process-route`; `app_module._LAST_PLAN`.

- [ ] **Step 1: Write the test**

```python
import os
from pathlib import Path

import pytest
from shapely.geometry import Point

import app as app_module
from route_processor import smooth_preview

FILES = [Path(os.environ.get("QBIQ_DESIGN_JSON", r"C:\Users\kevin\Downloads\121937120410001.json")),
         Path(os.environ.get("QBIQ_DESIGN_JSON_2", r"C:\Users\kevin\Downloads\80565468720002.json"))]
FILES = [f for f in FILES if f.exists()]
if not FILES:
    pytest.skip("real qbiq design JSONs not available", allow_module_level=True)


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_real_file_auto_tour_stays_in_corridor(client, path):
    with open(path, "rb") as f:
        r = client.post("/api/upload-qbiq-design", data={"json_file": (f, path.name)},
                        content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    plan = app_module._LAST_PLAN
    assert plan is not None
    covered = plan.corridor.buffer(1e-6)

    tour = client.post("/api/auto-tour", json={}).get_json()
    assert "error" not in tour, tour
    wps = tour["waypoints"]
    assert len(tour["stops"]) >= 5
    assert all(covered.covers(Point(p)) for p in wps)
    assert all(covered.covers(Point(p)) for p in smooth_preview(wps, smoothing=1.0))
    assert 10 <= tour["suggested_duration_s"] <= 600

    by_id = {room.id: room for room in plan.rooms}
    for s in tour["stops"]:
        room = by_id[s["room_id"]]
        assert wps[s["index"]] == pytest.approx(list(room.stop.point), abs=60)

    wire = [[p[0], p[1], 0, "", None] for p in wps]
    for s in tour["stops"]:
        wire[s["index"]][4] = {k: s[k] for k in ("room_id", "room_name", "look_at", "dwell_s")}
    frames = client.post("/api/process-route", json={"waypoints": wire,
                         "duration": tour["suggested_duration_s"], "fps": 30}).get_json()
    assert frames["frame_count"] >= tour["suggested_duration_s"] * 30 - 5
```

- [ ] **Step 2: Run** `-m pytest tests/test_plan_real_files.py -v` → 2 passed (one per file). If a file fails, do NOT loosen assertions — report which assertion, the counts, and the first offending point.

- [ ] **Step 3: Full suite + flake8** on the new test file.

- [ ] **Step 4: Report commit command**

```bash
git add backend/tests/test_plan_real_files.py
git commit -m "test(plan): real-file auto tour stays in the corridor on both design JSONs"
```
