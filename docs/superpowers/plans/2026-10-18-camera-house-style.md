# Camera House Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate sparse, eased, slow-head-movement camera keyframes in the style of qbiq's 60 hand-made Enscape paths, and drive both the Enscape XML and the 3D preview from them.

**Architecture:** New `backend/camera_style.py` plans a keyframe list (positions, timestamps, gaze yaw, hour, pans) from a route and interpolates it into `CameraFrame`s the way Enscape would. `route_processor.process_route` becomes plan → interpolate; `export_layer.to_enscape_xml` writes the planned keyframes directly. The old dwell / glance / 180°/s machinery is deleted.

**Tech Stack:** Python 3.13, numpy, Flask, pytest; single-file frontend (vanilla JS, Three.js r128).

**Spec:** `docs/superpowers/specs/2026-10-18-camera-house-style-design.md`

## Global Constraints

- Work in `C:/Users/kevin/revit-walkthrough-v2/.worktrees/qbiq-design-json` (branch `qbiq-design-json`); venv `C:/Users/kevin/revit-walkthrough-v2/.venv/Scripts/python.exe`; pytest from `backend/`.
- Style constants (spec, verbatim): `EYE_HEIGHT_M = 1.57`, `KF_SPACING_S = 3.3` (allowed 2.8–4.0), `KF_SPACING_M = 3.2`, `WALK_SPEED_MPS = 1.1` (allowed 0.8–1.45), `MAX_YAW_RATE_DPS = 25`, `MAX_REVERSALS_PER_MIN = 6`, `ROOM_LOOK_MAX_DEG = 60`, `MIN_LOOK_SPEED_MPS = 0.8`, `TURN_LEAD_S = 1.5`, `PAN_DURATION_S = 5`, `PAN_MAX_DEG = 90`, `MAX_PANS = 2`. Plus plan-level: `EASE_S = 1.5` (path start/end ramp), `CORNER_DEG = 25`, `MERGE_M = 1.0`.
- Head-turn rule (Kevin): on a turn-speed violation, slow the walk locally down to 0.8 m/s first (time taken back evenly from the rest so the video length is unchanged); only then reduce the gaze offset; never turn faster.
- Yaw is continuous (unwrapped) everywhere; never `% 360`.
- Plan coordinates are display-space plan units (cm for design JSON); every metre quantity converts with `units_to_metres`. UI `uturn_radius` is metres.
- XML: `<VideoPath version="1" easingInOut="1" shakyCam="0" walkMode="1">` (walkMode kept as today), `timestampSeconds` on every keyframe, Position y = 1.57, no 200-keyframe cap.
- Wire format: stop dict `{room_id, room_name, look_at, dwell_s, pan?}`; 4- and 5-element waypoints keep working.
- Subagents never `git commit`; the controller commits. No `print()`; module loggers; short functions with one-line docstrings; flake8 `--extend-ignore=W292,W391,E302,E501` with no new findings.

## Review Focus

- **Video far too short** (10 s for an 85 m tour) — export and preview still work, timestamps stay strictly increasing, a speed warning names a suggested length. Test in Task 2.
- **Two-waypoint straight route, no stops** — still ≥ 2 keyframes, constant gaze, no wobble. Test in Task 2.
- **Adjacent rooms picked back-to-back** (look windows overlap) — gaze moves smoothly from one room to the next, no snap back to travel between them, reversals ≤ limit. Test in Task 3.
- **Out-and-back / U-turn routes** — the lead target flips ~180°; the head turns at ≤ 25°/s, the walk slows first. Test in Task 3.
- **Cuts combined with stops and pans** — each segment plans independently, cut is a jump (two keyframes ≤ 0.1 s apart), pans never straddle a cut. Test in Task 4.

---

### Task 1: Keyframe model, interpolator, style metrics

**Files:**
- Create: `backend/camera_style.py`
- Create: `backend/tests/style_metrics.py` (test helper, not a test module)
- Test: `backend/tests/test_camera_style_interp.py`

**Interfaces:**
- Produces:
  - constants listed in Global Constraints, in `camera_style.py`.
  - `@dataclass Keyframe: t_s: float; x: float; y: float; yaw: float; hour: float | None = None; cut_after: bool = False` — plan units, seconds from start, continuous degrees.
  - `@dataclass KeyframePlan: keyframes: list[Keyframe]; units_to_metres: float; warnings: list[str] = field(default_factory=list); pans: int = 0`.
  - `interpolate(plan: KeyframePlan, fps: float, fov: float = 90.0) -> list[CameraFrame]` — frames with `z = EYE_HEIGHT_M`, `t` normalised to [0, 1], `cut=True` on the last frame before each `cut_after` jump.
  - `style_metrics(keyframes: list[Keyframe], units_to_metres: float) -> dict` in `tests/style_metrics.py` with keys `s_per_kf, m_per_kf_med, speed_med, yaw_rate_p90, yaw_rate_max, reversals_per_min, look_vs_travel_med, n_pans` (port of the scratchpad `xml-analysis/analyze.py` `metrics`, operating on keyframes directly: no timestamp filling, positions × units).

- [ ] **Step 1: Write failing tests** in `test_camera_style_interp.py`:
  - `test_interpolate_hits_keyframes`: 4 keyframes (0 s,(0,0),0°), (3 s,(300,0),10°), (6 s,(600,100),30°), (9 s,(900,100),30°), units 0.01 → frames at fps 30; the frame nearest each keyframe time is within 1 cm and 0.5° of it (ignore the first/last 1.5 s ramps for time, but positions at t=0 and end are exact).
  - `test_interpolate_eases_start_and_end`: on a straight 2-keyframe plan, speed over the first 0.2 s < 30% of mid-path speed; same for the last 0.2 s; total frame count == round(duration × fps) ± 1.
  - `test_interpolate_yaw_rate_bounded`: keyframe secants ≤ 25°/s → every frame-to-frame |Δyaw| ≤ 1.5 × 25 / fps + 1e-6 (Hermite peak bound — see Step 3).
  - `test_interpolate_cut_is_jump`: keyframes with `cut_after=True` on index 1 → no frame position lies strictly between keyframe 1 and 2; the frame before the jump has `cut=True`.
  - `test_interpolate_height_is_eye_height`: all `z == 1.57`.
  - `test_style_metrics_on_reference_like_plan`: a hand-built 10-keyframe plan at 3.3 s spacing → `s_per_kf == pytest.approx(3.3, abs=0.01)` and `n_pans == 0`.
- [ ] **Step 2: Run** `-m pytest tests/test_camera_style_interp.py -q` → FAIL (`ModuleNotFoundError: camera_style`).
- [ ] **Step 3: Implement** constants, dataclasses, `interpolate`. Approach: playback time τ ∈ [0, T] is mapped to path time through a trapezoid speed profile with `EASE_S` ramps at both ends (area-preserving, so T is unchanged); position = centripetal Catmull-Rom through keyframe positions evaluated per segment with local u = (t − t_i)/(t_{i+1} − t_i) (reuse `route_processor._cr_segment`); yaw = cubic Hermite per segment with tangents = min-mod of the adjacent secants (0 at sign changes) — this never overshoots and its peak slope is ≤ 1.5 × the larger adjacent secant. Segments split at `cut_after` (no spline across a cut).
- [ ] **Step 4: Run** the test file → PASS; flake8 clean.
- [ ] **Step 5: Commit** — `feat(camera): keyframe model and Enscape-style interpolator`.

### Task 2: Keyframe placement and timing

**Files:**
- Modify: `backend/camera_style.py`
- Test: `backend/tests/test_camera_style_plan.py`

**Interfaces:**
- Consumes: Task 1 types; `route_processor._centripetal_cr`, `_preprocess_sharp_turns`, `_clean_stops`.
- Produces: `plan_keyframes(waypoints: list, *, units_to_metres: float, total_duration: float, smoothing: float = 1.0, uturn_radius_m: float = 0.0, cuts: Iterable[int] | None = None, start_pan: bool = False) -> KeyframePlan` (this task: positions, timestamps, travel-direction yaw, hours, cuts, warnings; Tasks 3–4 extend the gaze and pans inside it) and `suggest_duration_s(length_m: float, n_pans: int = 0) -> int` = max(10, ceil to 5 s of length/1.1 + 5·pans).

- [ ] **Step 1: Write failing tests:**
  - `test_spacing_matches_house_style`: 100 m L-shaped route (units 0.01), duration = `suggest_duration_s(100)` → `style_metrics` `s_per_kf` within 2.8–4.0 and `m_per_kf_med` within 2.1–4.0.
  - `test_corner_gets_keyframe`: a 90° corner → a keyframe within 0.5 m of the smoothed corner apex.
  - `test_mandatory_keyframes`: a waypoint with time "14:30" gets a keyframe with `hour == 14.5` within 0.5 m of it; start and end keyframes are at the route ends.
  - `test_duration_and_speed`: last `t_s == total_duration`; speed_med within 0.8–1.45 at the suggested duration; `warnings == []`.
  - `test_too_short_video_warns` (Review Focus): 85 m in 10 s → timestamps strictly increasing, one warning containing "too short" and a suggested length in seconds; plan still returned.
  - `test_two_point_route` (Review Focus): straight 2-waypoint route → ≥ 2 keyframes, all yaws equal (±0.5°).
  - `test_uturn_radius_is_metres`: same route with `uturn_radius_m=3` vs 0 differs only near the U-turn and keyframes stay within 3.5 m of the original apex.
  - `test_suggest_duration`: `suggest_duration_s(110) == 100`, `suggest_duration_s(5) == 10`, `suggest_duration_s(110, n_pans=2) == 110`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Approach: per cut segment, smooth (`_preprocess_sharp_turns` with `uturn_radius_m / units_to_metres`, `_centripetal_cr` samples=20), compute arc length s; mandatory stations = ends, corners (heading change ≥ `CORNER_DEG` over ≤ 3 m), waypoints carrying a stop / yaw offset / time of day (projected to nearest s), cut ends; fill gaps with evenly spaced stations ≈ `KF_SPACING_M`; drop fill stations closer than `MERGE_M` to a mandatory one. Time: speed v = total path length / (duration − pan time) across all segments (a cut costs 0.05 s); `t_s = s / v`. Yaw (for now) = travel direction at each station (continuous). Warning text: `f"Video too short — walking at {v:.1f} m/s; try {suggest_duration_s(L)} s"` (and the analogous "too long" below 0.8 m/s).
- [ ] **Step 4: Run** → PASS; flake8.
- [ ] **Step 5: Commit** — `feat(camera): keyframe placement and timing in the house style`.

### Task 3: Gaze model with the head-turn rule

**Files:**
- Modify: `backend/camera_style.py`
- Test: `backend/tests/test_camera_style_gaze.py`

**Interfaces:**
- Consumes: Task 2 stations/timestamps inside `plan_keyframes`.
- Produces (internal helpers, all called by `plan_keyframes`): `_lead_yaw`, `_room_look_offsets`, `_apply_user_offsets`, `_limit_reversals`, `_limit_turn_rate(keyframes, s_metres) -> None` (mutates `t_s` and `yaw`). Public behaviour only through `plan_keyframes`.

- [ ] **Step 1: Write failing tests:**
  - `test_gaze_leads_turn`: on an L route, at the keyframe 1.5 s before the corner the yaw has already turned ≥ 20% of the corner angle toward the new direction.
  - `test_room_look_reaches_room`: route with one stop (`look_at` 3 m to the side, dwell 3 s) → some keyframe inside the look window has yaw within 15° of the bearing to `look_at`, or exactly 60° off travel if the room is further round.
  - `test_room_look_capped_at_60`: `look_at` directly behind → max |gaze − travel| == 60 ± 0.5.
  - `test_turn_rate_never_exceeds_cap`: any route/stops above → every consecutive keyframe pair |Δyaw|/Δt ≤ 25 + 1e-6.
  - `test_slow_down_before_turning_less` (Kevin's rule): a stop needing a 60° look within a 1 s window at 1.1 m/s → (a) the local speed around the stop drops (≥ 0.8 m/s, never below), (b) the look still reaches 60°, (c) total duration unchanged; and with a window so tight that 0.8 m/s is not enough → the reached angle is < 60 and > 0, local speed == 0.8 ± 0.01.
  - `test_adjacent_rooms_blend` (Review Focus): two stops 2 m apart on opposite sides → gaze goes from room 1 to room 2 without returning to the travel direction between them; reversals_per_min ≤ 8.
  - `test_uturn_head_turn` (Review Focus): out-and-back route → yaw rate ≤ 25°/s and local speed ≥ 0.8.
  - `test_user_yaw_offset_eased`: waypoint yaw offset +45° → keyframe at that waypoint has gaze travel+45 ± 1, neighbours partially, no |Δyaw| > 25°/s; offset of 350° behaves like −10° (continuity).
  - `test_reversal_limit`: a zig-zag of 6 small alternating stops within 30 s → reversals_per_min ≤ 6 after limiting.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (order inside `plan_keyframes`): base yaw = `_lead_yaw` (travel direction `TURN_LEAD_S × v` ahead along the smoothed path, unwrapped); add `_room_look_offsets` (per stop: window = dwell_s centred on the stop's station, plus 1.5 s ease in/out; offset = clamp(bearing(look_at) − travel, ±60) × smoothstep weight; overlapping windows take the offset of the nearer stop and blend linearly across the overlap); add `_apply_user_offsets` (offset at the waypoint's station, eased over ±1 keyframe, `((o + 180) % 360) − 180` only on the *offset value* to pick the short way); `_limit_reversals` (while reversals/min > 6: flatten the smallest-amplitude interior extremum of the gaze-offset series to the mean of its neighbours); `_limit_turn_rate` — the algorithm:

```
for each pair (i, i+1) with need = |Δyaw| / 25 > dt:
    max_dt = Δs_metres / MIN_LOOK_SPEED_MPS
    grow = min(need, max_dt) - dt            # slow down first
    if grow > 0: dt_i += grow; shrink all other intervals of the same segment
                 proportionally by grow (never below Δs / 1.45 m/s; if they can't absorb it,
                 absorb what they can and add a speed warning)
    if need > dt_i: shrink the gaze offset at the keyframe further from travel
                 direction until |Δyaw| = 25 * dt_i   # then turn less
repeat until no violation (max 50 passes; log a warning if not converged)
```
- [ ] **Step 4: Run** → PASS; flake8.
- [ ] **Step 5: Commit** — `feat(camera): gaze model — lead, walk-by room looks, slow-down-first head rule`.

### Task 4: Standing pans

**Files:**
- Modify: `backend/camera_style.py`, `backend/route_processor.py` (`_clean_stop` keeps `pan: bool`)
- Test: `backend/tests/test_camera_style_pans.py`

**Interfaces:**
- Produces: stop `pan: true` and `plan_keyframes(start_pan=True)` honoured; `KeyframePlan.pans` = count used.

- [ ] **Step 1: Write failing tests:**
  - `test_stop_pan_two_keyframes`: a stop with `pan: True` → two keyframes at the same position (≤ 1 cm) `PAN_DURATION_S` ± 0.05 apart, gaze swept toward the room by ≤ 90°, |Δyaw|/Δt ≤ 25.
  - `test_start_pan`: `start_pan=True` → keyframes 0 and 1 share a position, 5 s apart; walking starts after.
  - `test_max_two_pans`: start pan + 3 stop pans → `pans == 2`, the first two in route order win, one warning "Only 2 standing pans".
  - `test_no_pans_by_default`: stops without `pan` → `style_metrics(...)["n_pans"] == 0`.
  - `test_pan_respects_cut` (Review Focus): a stop pan on the waypoint right before a cut → pan keyframes stay in the first segment; the cut is still a jump (next keyframe ≤ 0.1 s later at the new position).
  - `test_clean_stop_keeps_pan`: `_clean_stop({..., "pan": True})["pan"] is True`; `"pan": "yes"` → False.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (pan time is reserved before speed is computed in Task 2's timing; a pan inserts a duplicate-position keyframe; its sweep is limited by the 25°/s rule over 5 s = 125° ≥ 90° so it is never rate-limited). **Step 4: Run** → PASS. **Step 5: Commit** — `feat(camera): optional standing pans (per room and at start), max two`.

### Task 5: Wire the planner into preview, exports and the tour

**Files:**
- Modify: `backend/route_processor.py` (process_route → plan + interpolate; delete `_insert_dwells`, `_dwell_frames`, `_dwell_tags`, `_scaled_dwells`, `_apply_glances`, `_build_frames`, `_apply_yaw_offsets`, `_MAX_YAW_RATE_DEG_PER_SEC`, `GLANCE_*`, `MAX_DWELL_FRACTION`, `MIN_DWELL_S`, `CameraFrame.dwell`, `_HOLD_SECONDS` handling moves into the planner as a 0.4 s hold for single-point segments)
- Modify: `backend/export_layer.py` (`to_enscape_xml(plan: KeyframePlan, meta)` writes keyframes; delete `_keyframe_indices`, `MAX_KEYFRAMES`)
- Modify: `backend/app.py` (`/api/process-route`, `/api/export/json`, `/api/export/xml`; delete `_camera_hints`; new `_units(data: dict) -> float`)
- Modify: `backend/plan_tour.py` (suggested duration via `suggest_duration_s`)
- Delete tests that assert removed mechanics: `tests/test_camera_stops.py`, `tests/test_export_stops.py` (move any still-valid compatibility assertions — 4-element waypoints, malformed stops, JSON shape — into `tests/test_camera_style_wiring.py`)
- Test: `backend/tests/test_camera_style_wiring.py`, `backend/tests/test_camera_style_real_files.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `process_route(waypoints, smoothing=1.0, total_duration=30.0, fps=30.0, fov=90.0, uturn_radius=0.0, cuts=None, units_to_metres=1.0, start_pan=False) -> list[CameraFrame]` (camera_height and glance params removed; `uturn_radius` in metres). `/api/process-route` request adds optional `units_to_metres`, `start_pan`; response adds `warnings: [str]` and frames' `z` = 1.57. Export settings accept `start_pan`. `_units(data)` = explicit `units_to_metres` → `_LAST_PLAN.units_to_metres` → `_LAST_UNITS_TO_METRES`.

- [ ] **Step 1: Write failing tests:**
  - wiring: process-route on a synthetic route returns `warnings` and frames with `z == 1.57`; export/xml has `timestampSeconds` on every keyframe, Position y `1.570000`, count < 200 for a 10-minute route, root attrs `easingInOut="1" shakyCam="0"`; export/json frames shape unchanged; 4-element waypoints and malformed stops still 200; a time-of-day waypoint yields an `hour` attribute.
  - real files (skip if the JSONs are absent, as `test_plan_real_files.py` does): both design JSONs, Auto Tour with `room_ids` of 6 non-back-of-house rooms, export XML at the suggested duration, parse it → `style_metrics`: s_per_kf 2.8–4.0, yaw_rate_p90 ≤ 27, yaw_rate_max ≤ 30, reversals_per_min ≤ 8, look_vs_travel_med 8–32, speed_med 0.8–1.45, n_pans 0, every Position y == 1.57; and for each stop some keyframe within its look window faces the room within 15° or is 60° off travel. Preview = export: process-route frames at each XML keyframe time match it (≤ 1 cm, ≤ 0.5°).
  - `test_plan_tour.py`: the suggested duration now uses 1.1 m/s (update the existing expected values).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** the wiring and deletions listed. **Step 4: Run** the new files, then the full suite (all pass; the count changes because dwell/glance tests are removed — report the number). flake8 no new findings.
- [ ] **Step 5: Commit** — `feat(camera): preview and exports driven by house-style keyframes`.

### Task 6: Frontend controls and height

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Consumes: Task 5 API (`warnings`, `start_pan`, `units_to_metres`, stop `pan`).

- [ ] **Step 1:** `updateCameraFromT` uses the frame's `z` for camera height (remove the hard-coded 1.75); `exportRoute` settings drop `camera_height`.
- [ ] **Step 2:** `cleanStop` keeps `pan` (boolean only). Your Points stop row: a small "Stand & look" checkbox (`stop.pan`), escaped label, next to the look-time input (relabel the dwell input's title to "Seconds spent looking into the room").
- [ ] **Step 3:** Video Settings: checkbox "Look around at start" (`cam.startPan`, default off) sent as `start_pan` in process-route and export settings; process-route and both exports also send `units_to_metres: state.unitsToMetres`.
- [ ] **Step 4:** After process-route, show each `warnings` entry as an `'inf'` toast.
- [ ] **Step 5: Verify:** `node --check` on the extracted longest inline script; headless browser run with the scratchpad driver (`scratchpad/pw/`, see `pick.js`): load `C:/Users/kevin/Downloads/121937120410001.json`, pick 4 rooms in Auto Tour, generate, open 3D Preview, play 3 s, assert `threeCam.position.y` ≈ 1.57, tick "Stand & look" on the first stop and "Look around at start", re-run preview without errors; screenshot `style-preview.png`.
- [ ] **Step 6: Commit** — `feat(frontend): stand-and-look and start-pan controls, eye height from frames`.
