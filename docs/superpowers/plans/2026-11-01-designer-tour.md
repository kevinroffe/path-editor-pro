# Designer Tour Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Routes walk through open areas around furniture, and a "Suggest a tour" button builds a designer-like ~100 s tour learned from 312 hand-made Enscape paths.

**Architecture:** `plan_model` gains a walkable area (corridor ∪ open rooms − furniture) that every router uses; open rooms get an inside stop; a new `plan_suggest.py` picks rooms by value-per-metre within a length budget and returns ordered room ids that the existing room_ids tour builds.

**Tech Stack:** Python 3.13, Flask, shapely, networkx, numpy; vanilla JS frontend.

**Spec:** docs/superpowers/specs/2026-11-01-designer-tour-design.md

## Global Constraints

- Worktree `.worktrees/main-entrance`; test server PORT=5005; never touch :5004 (Kevin).
- pytest via `C:/Users/kevin/revit-walkthrough-v2/.venv/Scripts/python.exe -m pytest`, flake8 `--extend-ignore=W292,W391,E302,E501`, JS `node --test "frontend/tests/*.test.js"`.
- Constants live once, in the module that owns them; tests assert behaviour, not constants.
- `room_ids` tours keep the exact clicked order.

## Review Focus

1. A plan with no stencil furniture (or malformed components) — walkable must still build (corridor ∪ open rooms).
2. An open room that touches the corridor only through furniture — it must drop out of walkable, not create an unreachable stop.
3. Plans with no open rooms / no reachable target — suggestion returns a clear error, not an empty route.
4. Very large plans (55 rooms) — suggestion must answer in a few seconds.
5. A user click inside an open area's walkable part (Smart Path) must stay where clicked.

---

### Task 1: Camera constants from the 312 paths

**Files:** Modify `backend/camera_style.py` (constants); tests in `backend/tests/test_camera_style_plan.py` / `test_plan_tour.py` where they hard-code 1.1 m/s or 5 s pans.

- [ ] Write/adjust tests: `suggest_duration_s(95)` → 100; a stop pan's two keyframes are 4 s apart; a route walked at 0.7 m/s gives no "too long" warning, at 0.5 m/s it does.
- [ ] Run → FAIL.
- [ ] Set `WALK_SPEED_MPS = 0.95`, `MIN_SPEED_MPS = 0.6`, `PAN_DURATION_S = 4.0`.
- [ ] Full pytest green (incl. `test_camera_style_real_files.py`).
- [ ] Commit `feat(camera): walking speed and pans from 312 designer paths`.

### Task 2: Walkable area through open rooms

**Files:** Modify `backend/qbiq_scene3d.py` (add `component_footprint(comp) -> Polygon | None`), `backend/plan_model.py` (`PlanModel.walkable`, `flipped`), `backend/plan_routing.py` (`corridor_graph_for`, `contain_spline` callers, `snap_points` use walkable). Test: `backend/tests/test_plan_walkable.py`.

**Interfaces:** Produces `PlanModel.walkable: Polygon | MultiPolygon` (display space after `flipped`), `plan_model.WALKABLE_MIN_M2 = 8`, `FURNITURE_CLEARANCE_M = 0.35`.

- [ ] Tests (synthetic DATA from `test_plan_model.py`, plus a desk component in open room B): walkable covers B's free floor and the corridor; does not cover the desk grown by 0.35 m; does not cover closed room A or back-of-house D-types; with no components walkable = corridor ∪ B ∪ D (open, non-BOH, ≥ 8 m²); an open room touching the corridor only through furniture is excluded; `component_footprint` of a placed 100×45 box matches `matrix @ original_matrix3d` (reuse the case from `test_scene_placement.py`); a click inside B's free floor is kept by `snap_points`; `route_on_plan` between two corridor points on either side of B may cross B and stays inside walkable.
- [ ] Run → FAIL. Implement. Run → PASS; full pytest.
- [ ] Commit `feat(routing): walk through open areas around furniture`.

### Task 3: Inside stops for open rooms, centre-line stops for closed rooms

**Files:** `backend/plan_model.py` (`_open_stop` → inside stop when the walkable piece ≥ 4 m²), `backend/plan_tour.py` (`route_point(graph, room, u)`; used for every room in `build_tour`), `backend/camera_style.py` (`_room_look_offsets`: no look when target within 1.5 m of the keyframe). Tests in `test_plan_walkable.py`, `test_plan_tour.py`, `test_camera_style_gaze.py`.

- [ ] Tests: open room B's stop lies inside B and inside walkable; closed room A's route point is on a graph edge and within 2 m of its door stop (else the stop itself); a tour through A has no waypoint farther than 0.3 m off the corridor centre line near A (no zig-zag); a stop whose look_at equals its point yields gaze = lead direction (no spin).
- [ ] Run → FAIL. Implement. Run → PASS; full pytest.
- [ ] Commit `feat(tour): stop inside open areas, glance at closed rooms from the centre line`.

### Task 4: Suggested tour

**Files:** Create `backend/plan_suggest.py` (`suggest_room_ids(plan, graph, start, budget_m) -> list[str]`, `WEIGHTS`, `SEE_CLOSED_M = 3`, `SEE_OPEN_M = 1`, `MIN_LOOK_GAP_M = 5`, `TOUR_TARGET_S = 100`); modify `backend/app.py` (`/api/auto-tour` with `"suggest": true` → `{**tour, "room_ids": ids}` using budget `TOUR_TARGET_S × WALK_SPEED_MPS`). Tests: `backend/tests/test_plan_suggest.py`, `backend/tests/test_plan_suggest_real_files.py`.

- [ ] Tests (synthetic): with a tiny budget only the highest value-per-metre room is chosen; a room seen on the way is included without being a target; returned ids are in route order with no duplicates; looks closer than 5 m keep the higher weight; back-of-house never appears; no reachable room → ValueError.
- [ ] Tests (real, skip if files missing): for the five pairs, route length ≤ 1.1 × budget, no route sample inside a closed room (shrunk 0.3 m), an open highlight is entered when one is reachable, designer cover ≥ Gusto 0.8 / Kraft 0.5 / Birmingham 0.75 / 1117 0.7; each suggestion < 10 s.
- [ ] Run → FAIL. Implement. Run → PASS; full pytest; flake8.
- [ ] Commit `feat(tour): suggest a designer-like tour`.

### Task 5: "Suggest a tour" button

**Files:** `frontend/index.html` (button next to the quick-add groups; `suggestTour()` posts `{suggest: true, smoothing, entrance?}` and calls `changePicks(data.room_ids)`; busy state + error toast). Playwright smoke in scratchpad `pw/suggest.js` against :5005.

- [ ] Smoke first (fails: no button): load a real plan, click Suggest a tour, expect a non-empty pick list, a route, and video length 60–125 s.
- [ ] Implement. Smoke green; earlier smokes unchanged; JS tests green.
- [ ] Commit `feat(ui): Suggest a tour button`.
