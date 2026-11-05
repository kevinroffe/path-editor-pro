# Revit Add-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Revit 2024 add-in whose button opens a window with the actual Revit model in 3D, Auto-path, path editing, a multi-track video timeline and a Save-XML button, powered by the existing engine.

**Architecture:** The add-in (C#) reads each level from Revit on the main thread and POSTs it to the existing Flask engine, which runs as a local program the add-in starts and stops. The engine turns the payload into the `LevelGeometry` and `PlanModel` the tool already routes on, so Auto-path, Suggested Tour, camera style and XML export are reused unchanged. The window is a WebView2 hosting the existing `frontend/` with a `?host=revit` mode that adds the option-B shell, 3D path view, camera view and tracks timeline.

**Tech Stack:** Python 3.12 + Flask + shapely (engine, pytest); vanilla JS + three.js + d3 (frontend, `node --test`); C# on .NET Framework 4.8 + Revit 2024 API + WebView2 (add-in, xunit); PyInstaller (engine package).

**Spec:** `docs/superpowers/specs/2026-11-05-revit-addin-design.md` (read it first; this plan argues from it)

## Global Constraints

- Revit **2024** only; add-in is C# on **.NET Framework 4.8**; window is a **WebView2** control; Windows only.
- Engine binds **`127.0.0.1` only**, on a **random port**, with a **per-session key**; started on window open, stopped when Revit closes.
- The model **never leaves the computer**: no network at runtime, no telemetry; every frontend asset loads from the local package.
- Coordinates keep **Revit's internal origin**; units via `units_to_metres` (feet = `0.3048`); never shifted, matching `dxf_extractor.py` (`svg_y = -model_y`).
- The add-in is **read-only**: it never opens a Transaction, saves, or modifies the Revit model.
- Version one: active phase and primary design option only; **linked models, stairs, design options, worksets, Project Base Point / survey point / True North correction are out**.
- Hand-off to Enscape is a **Save / Download XML button only** (`VideoPath` → `Keyframes` → `Keyframe` with `Position`, `LookAt`); no opening or driving Enscape.
- **All software text is English** (UI, messages, file names), and room names arrive in English (Kevin's decision).
- One frontend codebase with a **mode flag** (`?host=revit`), not a fork. Backend modules are imported as top-level modules (see `backend/tests/conftest.py`).
- The 3D view is the **real Revit geometry** (meshes), reduced so it stays smooth; JSON loaded for a level **replaces the whole level**.

## Review Focus

Inputs the spec implies but no feature task would exercise on its own; each has a test in the named task.

1. A level with **no Rooms, or every Room unplaced/unenclosed**: Auto-path still works, Suggested Tour says why it can't, never a 500 (Task 2, Task 3).
2. **Non-ASCII room names** (e.g. `Café Lounge`) through JSON, the engine and the XML; the engine runs with UTF-8 on a cp1255 console (Task 1, Task 4, Task 13).
3. **Engine lifecycle:** wrong or missing key rejected; a stale engine from a crashed Revit is reaped; a busy port is not reused (Task 4, Task 13).
4. A **huge mesh** payload (millions of vertices) is reduced and the response stays bounded (Task 5).
5. A model **far from the origin** (coordinates around 1e5 feet) exports XML positions that are still correct to the millimetre (Task 3).

---

## Phase 1: Engine (Python, `backend/`, run `pytest` from `backend/`)

### Task 1: Revit payload → LevelGeometry

**Files:**
- Create: `backend/revit_payload.py`, `backend/tests/test_revit_payload.py`, `backend/tests/fixtures/revit_level.json` (small office floor in feet: 4 rooms, a corridor, 2 doors, 1 mesh)

**Interfaces:**
- Produces:
  - `SCHEMA = 1`
  - `parse_revit_payload(payload: dict) -> LevelGeometry`, raising `ValueError` with a readable message on bad input.
  - `room_issues(payload: dict) -> list[dict]` where each issue is `{"room_id": str, "name": str, "problem": "unplaced" | "unenclosed" | "zero_area" | "duplicate"}`.
- Payload contract (the add-in's C# DTOs mirror it, Task 12):
  `{"schema":1,"level":{"name":str,"elevation":float},"units_to_metres":float,"walls":[polyline],"doors":[polyline],"windows":[polyline],"columns":[polyline],"furniture":[polyline],"rooms":[{"id":str,"name":str,"number":str|null,"polygon":[[x,y]]|null,"area":float,"placed":bool,"enclosed":bool}],"meshes":[{"type":str,"verts":[float],"faces":[int],"color":str|null,"opacity":float|null}]}`; polylines are `[[x,y],...]` in model units; mesh verts are metres, Z-up, same origin.

- [ ] **Step 1: Write failing tests** in `test_revit_payload.py`: `test_parse_fills_levelgeometry` (walls/doors/windows/columns/furniture copied, `units_to_metres == 0.3048`, `source == "revit"`, `meshes` passed through, `spaces` holds only placed+enclosed room polygons); `test_bad_schema_raises` (`schema: 2` → `ValueError`); `test_empty_level_raises` (no walls and no meshes → `ValueError("level has no geometry")`); `test_room_issues_flags_each_problem` (one fixture room per problem, plus two rooms with the same `number` → `duplicate`); `test_non_ascii_names_survive` (room name `"Café Lounge"` unchanged in the result).
- [ ] **Step 2:** Run `pytest tests/test_revit_payload.py -v`. Expected: FAIL, module not found.
- [ ] **Step 3:** Implement both functions in `revit_payload.py`; `LevelGeometry` comes from `revit_extractor.py`.
- [ ] **Step 4:** Run the same command. Expected: PASS.
- [ ] **Step 5:** `git add backend/revit_payload.py backend/tests && git commit -m "feat(revit): parse Revit level payload into LevelGeometry"`

### Task 2: PlanModel from Revit rooms

**Files:**
- Create: `backend/plan_from_revit.py`, `backend/tests/test_plan_from_revit.py`

**Interfaces:**
- Consumes: Task 1 payload shape; `PlanModel`, `PlanRoom`, `Stop`, `dwell_for` from `plan_model.py`.
- Produces: `build_revit_plan(payload: dict) -> PlanModel | None`, returning `None` when there are no usable rooms; `SPACE_TYPE_KEYWORDS: dict[str, str]` (module-level, extendable).

The tool's tour logic needs a `PlanModel`; qbiq JSON supplies one, Revit does not. Rules (Claude's calls, in the spec's spirit): a room's `space_type` comes from its name by case-insensitive keyword (Conference/meeting → `"Conference"`, kitchen/pantry → `"Kitchen"`, reception/lobby → `"Reception"`, storage/IT/server → `"Storage Room"`/`"IT Room"`, office → `"Office"`, open/workstation → `"Open Space WorkStation"`, anything else → `None`). Rooms named corridor/hall/circulation form the `corridor`; if none is named, the corridor is the placed rooms' union minus all other room polygons, kept only if at least `WALKABLE_MIN_M2`. `enscape_offset` is always `None` (true model coordinates).

- [ ] **Step 1: Write failing tests:** `test_named_corridor_becomes_corridor`; `test_corridor_inferred_when_unnamed`; `test_space_type_from_english_names`; `test_unknown_room_has_none_space_type_and_does_not_crash`; `test_no_rooms_returns_none`; `test_all_unplaced_returns_none`; `test_enscape_offset_is_none`.
- [ ] **Step 2:** Run `pytest tests/test_plan_from_revit.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `build_revit_plan`, building the same `PlanRoom` stops `plan_model._plan_room` builds (reuse its helpers rather than duplicating geometry code; export them if needed).
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(revit): build a PlanModel from Revit rooms`.

### Task 3: `/api/upload-revit`, `/api/revit/current`, and end-to-end routing

**Files:**
- Modify: `backend/app.py` (new routes next to `upload_qbiq_design`, ~line 372)
- Test: `backend/tests/test_app_revit_upload.py`

**Interfaces:**
- Consumes: `parse_revit_payload`, `room_issues`, `build_revit_plan`, `_load_2d_geometry`, `flipped`, `plan_to_json`.
- Produces: `POST /api/upload-revit` (JSON body = payload) → the same JSON as `/api/upload-qbiq-design` plus `"room_issues": [...]`; `GET /api/revit/current` → the last such response, or 404 before any upload.

- [ ] **Step 1: Write failing tests** (mirror `test_app_qbiq_design_upload.py`): `test_upload_returns_upload_shaped_response_with_source_revit`; `test_bad_payload_returns_400_with_message`; `test_current_returns_last_upload_and_404_before` ; `test_autopath_routes_on_revit_level`; `test_auto_tour_and_suggest_work`; `test_no_rooms_autopath_ok_tour_explains` (**Review Focus 1**: `/api/autopath` 200, `/api/auto-tour` 400 with a message, no 500); `test_qbiq_json_after_revit_replaces_level` (post Revit, then `/api/upload-qbiq-design`, `/api/revit/current` still returns the Revit response but `_LAST_PLAN` is the qbiq plan); `test_xml_export_is_in_model_metres` asserting `Position` x equals waypoint x × 0.3048 with the y convention of `test_enscape_origin.py`; `test_far_from_origin_xml_exact` (**Review Focus 5**: a level at x≈1e5 ft, XML positions within 0.001 m).
- [ ] **Step 2:** Run `pytest tests/test_app_revit_upload.py -v`. Expected: FAIL (404 on routes).
- [ ] **Step 3:** Implement both routes; the mesh array in the response must line up with the plan in the 3D view the way the existing IFC route does (check `flipped` and the mesh y handling in the frontend `addBuilt`).
- [ ] **Step 4:** Run the new file, then the whole `pytest`. Expected: PASS, no regressions.
- [ ] **Step 5:** Commit `feat(revit): /api/upload-revit and /api/revit/current`.

### Task 4: Engine key, localhost-only, UTF-8

**Files:**
- Modify: `backend/app.py` (a `before_request` check), `run.py` (`--key`, UTF-8)
- Test: `backend/tests/test_app_engine_key.py`

**Interfaces:**
- Produces: when env `QBIQ_ENGINE_KEY` is set, every request except `GET /` and `/frontend/*` needs header `X-Qbiq-Key` equal to it, else 403; `run.py` refuses `--host` other than `127.0.0.1` unless `--allow-remote` is given, and forces `PYTHONUTF8=1`.

- [ ] **Step 1: Write failing tests:** `test_missing_key_403_when_set`; `test_wrong_key_403`; `test_right_key_ok`; `test_no_key_env_allows_all` (browser mode stays as today); `test_static_assets_need_no_key`; `test_non_ascii_room_name_round_trips_through_upload` (**Review Focus 2**).
- [ ] **Step 2:** Run `pytest tests/test_app_engine_key.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. The page itself obtains the key from the `?key=` query parameter and sends it as the header on every `fetch`, so Task 7 adds that.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(engine): per-session key, localhost-only, UTF-8`.

### Task 5: Mesh reduction

**Files:**
- Create: `backend/mesh_reduce.py`, `backend/tests/test_mesh_reduce.py`
- Modify: `backend/app.py` (apply inside `/api/upload-revit`)

**Interfaces:**
- Produces: `reduce_meshes(meshes: list[dict], max_vertices: int = 400_000, min_extent_m: float = 0.05) -> list[dict]`: merges meshes sharing `(type, color, opacity)`, drops meshes whose bounding box is under `min_extent_m` on every axis (smallest first) until the total is at most `max_vertices`; never drops floors or walls.

- [ ] **Step 1: Write failing tests:** `test_merges_by_material`; `test_drops_tiny_before_big`; `test_keeps_walls_and_floors_over_budget`; `test_under_budget_unchanged_content`; `test_huge_payload_is_bounded_and_fast` (**Review Focus 4**: 3 million vertices of tiny furniture ends ≤ `max_vertices` in under 5 s).
- [ ] **Step 2:** Run `pytest tests/test_mesh_reduce.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement with numpy; wire into the upload route; add one assertion in `test_app_revit_upload.py` that the response vertex count is within budget.
- [ ] **Step 4:** Run both test files. Expected: PASS.
- [ ] **Step 5:** Commit `feat(revit): reduce meshes to a smooth budget`.

### Task 6: Camera plan for the timeline

**Files:**
- Modify: `backend/camera_style.py` (add `keyframe_plan_to_json`), `backend/app.py` (new route)
- Test: `backend/tests/test_app_camera_plan.py`

**Interfaces:**
- Produces: `keyframe_plan_to_json(plan: KeyframePlan) -> dict` = `{"keyframes":[{"t_s","x","y","yaw","hour","cut_after","still_s"}],"units_to_metres","warnings","pans"}` where `still_s` is the seconds the camera stays put at that keyframe (reuse `_still_s`); `POST /api/camera-plan` with the same body as `/api/export/xml` → that JSON.

- [ ] **Step 1: Write failing tests:** `test_camera_plan_matches_xml_keyframes` (same count and times as the XML export for the same body); `test_still_s_marks_pauses`; `test_bad_body_400`.
- [ ] **Step 2:** Run `pytest tests/test_app_camera_plan.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(engine): expose the keyframe plan for the timeline`.

### Task 7: Points still valid after refresh

**Files:**
- Modify: `backend/app.py`
- Test: `backend/tests/test_app_points_valid.py`

**Interfaces:**
- Produces: `POST /api/points-valid` body `{"points":[[x,y],...]}` → `{"valid":[bool,...]}`, true when the point is inside the loaded plan's `walkable` (or, with no plan, not inside any obstacle).

- [ ] **Step 1: Write failing tests:** `test_inside_walkable_true`; `test_inside_wall_false`; `test_no_plan_uses_obstacles`; `test_empty_list_ok`; `test_non_point_400`.
- [ ] **Step 2:** Run `pytest tests/test_app_points_valid.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement using `_LAST_PLAN.walkable` and the obstacle caches.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(engine): points-valid check for model refresh`.

---

## Phase 2: Frontend (`frontend/`, run `node --test frontend/tests/` from the repo root)

### Task 8: Offline assets and host bridge

**Files:**
- Create: `frontend/vendor/` (d3 7.9.0, three 0.186.1 + addons used, mediabunny 1.61.3, Inter 400–800 woff2), `frontend/js/host.js`, `frontend/tests/host.test.js`, `backend/tests/test_frontend_offline.py`
- Modify: `frontend/index.html` (import map, d3 script tag, `@import` of Google Fonts, every `fetch` gets the key header)

**Interfaces:**
- Produces: `host.js` exports `hostMode(search: string): "revit" | "browser"`, `engineKey(search: string): string | null`, `authHeaders(search: string): object`, `handleHostMessage(msg: object, handlers: object): boolean` (returns false and ignores unknown `type`s), `postToHost(msg: object): void` (no-op outside WebView2).

- [ ] **Step 1: Write failing tests:** JS `hostMode('?host=revit') === 'revit'`, default `'browser'`; `engineKey('?key=abc') === 'abc'`; `authHeaders` carries `X-Qbiq-Key` only when a key exists; `handleHostMessage({type:'nonsense'}, {})` returns false and never throws; Python `test_index_has_no_external_urls` fails on any `https://` in a `<script>`, `<link>`, `@import` or import map of `index.html`.
- [ ] **Step 2:** Run `node --test frontend/tests/host.test.js` and `pytest tests/test_frontend_offline.py -v`. Expected: FAIL.
- [ ] **Step 3:** Download the pinned versions into `frontend/vendor/`, point `index.html` at them, add `host.js`, and route all `fetch(`${API}/...`)` calls through one helper that adds `authHeaders`. The existing exe build (`qbiq.spec`) already copies `frontend/`.
- [ ] **Step 4:** Run both, then open the app in the browser pane and confirm it still loads the demo plan with the network blocked (devtools offline). Expected: PASS and the demo renders.
- [ ] **Step 5:** Commit `feat(frontend): vendor assets for offline use; add host bridge`.

### Task 9: Tracks model and selection

**Files:**
- Create: `frontend/js/tracks.js`, `frontend/js/selection.js`, `frontend/tests/tracks.test.js`, `frontend/tests/selection.test.js`

**Interfaces:**
- Consumes: the `/api/camera-plan` JSON from Task 6; `video-timeline.js` `buildTimeline`; `music.js` clip data.
- Produces:
  - `buildTracks({ plan, fades, music }) -> { durationS, lanes: [{ id: "video"|"camera"|"lookat"|"pauses"|"music", clips: [{ id, startS, endS, kind }] }] }`; the camera lane has one marker per keyframe (`startS == endS == t_s`), the pauses lane one clip per keyframe with `still_s > 0`.
  - `createSelection(): { select(id: string|null): void, get(): string|null, subscribe(fn): () => void }`; ids are `"kf:<index>"` for points everywhere (list, 3D, plan, timeline).

- [ ] **Step 1: Write failing tests:** `buildTracks` lane order and ids; a keyframe with `still_s: 2` yields a pause clip of 2 s; `durationS` equals the last keyframe time plus intro/outro from `video-timeline.js`; `select` notifies subscribers once per change and not on re-selecting the same id; unsubscribe stops calls.
- [ ] **Step 2:** Run `node --test frontend/tests/tracks.test.js frontend/tests/selection.test.js`. Expected: FAIL.
- [ ] **Step 3:** Implement as CommonJS-compatible modules like `video-timeline.js`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(frontend): tracks model and shared selection`.

### Task 10: 3D path and camera-view maths

**Files:**
- Create: `frontend/js/path3d.js`, `frontend/tests/path3d.test.js`

**Interfaces:**
- Produces:
  - `routeToWorld(waypoints: [[x,y]], unitsToMetres: number, eyeHeightM: number) -> [[x,y,z]]` (x,y scaled to metres with the same y handling as the mesh, z = elevation + eye height).
  - `coneParams(point: [x,y,z], yaw: number, fovDeg: number, lengthM: number) -> { apex: [x,y,z], baseCorners: [[x,y,z]] }`.
  - `poseAt(keyframes, tS: number, unitsToMetres: number, eyeHeightM: number) -> { position: [x,y,z], lookAt: [x,y,z] }`.
  - `floorHit(rayOrigin: [x,y,z], rayDir: [x,y,z], floorZ: number) -> [x,y] | null`.

- [ ] **Step 1: Write failing tests:** `routeToWorld` scales feet to metres and adds eye height; `coneParams` base corners sit at `lengthM` along `yaw`, spread by FOV; `poseAt` between two keyframes lies between them and at a keyframe time equals it; `floorHit` returns null for a ray pointing up and the exact point for a 45° down ray.
- [ ] **Step 2:** Run `node --test frontend/tests/path3d.test.js`. Expected: FAIL.
- [ ] **Step 3:** Implement as pure functions.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(frontend): 3D path and camera-pose maths`.

### Task 11: Option-B shell, 3D path view, camera view, timeline UI

**Files:**
- Modify: `frontend/index.html` (the existing three.js scene around `buildScene`, the timeline markup, the toolbar); create `frontend/css/revit-shell.css`

**Interfaces:**
- Consumes: `host.js`, `tracks.js`, `selection.js`, `path3d.js`, `/api/revit/current`, `/api/camera-plan`, `/api/points-valid`, `/api/export/xml`.

Under `?host=revit` only: header (logo, step chips, "synced with Revit" chip, **Save path (XML)**), left tools (Auto-path, add point, move points, look-at, smooth path, pauses, level, ceilings, **Load JSON instead**, **Refresh model**), centre 3D view of the real meshes with the route line, numbered points and cones, a small camera-view window that renders from `poseAt` at the play head, right inspector for the selected point, and the bottom tracks timeline with play head, snap, zoom. Selecting a point in any view selects it in all; dragging a point in 3D uses `floorHit`; on a `modelRefreshed` message, points failing `/api/points-valid` are kept and flagged (amber), never dropped. When `room_issues` is non-empty a banner offers **Load JSON instead**. With no rooms, Suggested Tour is disabled with the engine's message. Browser mode must look and behave exactly as today.

- [ ] **Step 1:** Add a `?host=revit` demo path (`/?host=revit&demo=1` loads `/api/demo` as if from Revit) so the window can be developed without Revit.
- [ ] **Step 2:** Implement the shell, 3D route overlay, cones, camera view, tracks timeline, selection sync and point dragging; keep every new function pure where possible and covered by Tasks 9 and 10.
- [ ] **Step 3:** Run `node --test frontend/tests/` and the full `pytest`. Expected: PASS.
- [ ] **Step 4:** Start the app (`preview_start`, `.claude/launch.json`), open `/?host=revit&demo=1`, and verify by screenshots: the layout matches option B; Auto-path draws a route in the 3D view; Play moves the camera view; clicking a timeline marker selects the same point in the 3D view; browser mode `/` is unchanged. Record any mismatch as a fix, not a note.
- [ ] **Step 5:** Commit `feat(frontend): Revit window shell with 3D path view and tracks timeline`.

---

## Phase 3: Add-in (C#, `addin/`)

### Task 12: Solution and the payload DTOs

**Files:**
- Create: `addin/Qbiq.PathTool.sln`, `addin/Qbiq.PathTool.Core/` (netstandard2.0 class library, no Revit references), `addin/Qbiq.PathTool.Tests/` (xunit), `addin/Qbiq.PathTool.Addin/` (net48, references RevitAPI/RevitAPIUI 2024 and `Microsoft.Web.WebView2`), `addin/Qbiq.PathTool.Core/Payload.cs`, `addin/Qbiq.PathTool.Tests/PayloadTests.cs`

**Interfaces:**
- Produces: `LevelPayload` with the exact field names and types from Task 1's contract (`Schema`, `Level`, `UnitsToMetres`, `Walls`, `Doors`, `Windows`, `Columns`, `Furniture`, `Rooms`, `Meshes`) and `PayloadJson.Serialize(LevelPayload): string` / `Deserialize(string): LevelPayload`, camelCase-lowercase keys as in the contract.

- [ ] **Step 1: Write failing tests:** `Golden_fixture_round_trips_identically` (load `backend/tests/fixtures/revit_level.json`, deserialize, serialize, compare as JSON trees); `Non_ascii_room_name_survives`; `Missing_optional_fields_become_empty_lists`.
- [ ] **Step 2:** Run `dotnet test addin/Qbiq.PathTool.sln`. Expected: FAIL. (If `dotnet --list-sdks` is empty, install the .NET 8 SDK first; the add-in project builds against the `Microsoft.NETFramework.ReferenceAssemblies.net48` package so no Visual Studio is needed.)
- [ ] **Step 3:** Implement with `System.Text.Json` or Newtonsoft.Json (whichever loads cleanly inside Revit; add the choice to this file's header comment).
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(addin): solution scaffold and payload contract`.

### Task 13: Engine host (start, stop, key, orphan reaping)

**Files:**
- Create: `addin/Qbiq.PathTool.Core/EngineHost.cs`, `addin/Qbiq.PathTool.Tests/EngineHostTests.cs`, `addin/Qbiq.PathTool.Tests/fake_engine.py`

**Interfaces:**
- Produces: `EngineHost(string enginePath, string stateDir)` with `Task<EngineEndpoint> StartAsync()` (`EngineEndpoint { int Port; string Key; Uri BaseUri }`), `void Stop()`, and static `int ReapOrphans(string stateDir)` (kills engines recorded in `stateDir/engine.pid` whose parent is gone, returns how many). Port is a free one chosen per start; the key is 32 random bytes hex; the child gets `QBIQ_ENGINE_KEY` and `PYTHONUTF8=1`.

- [ ] **Step 1: Write failing tests** (use `fake_engine.py`, a tiny HTTP server that honours the key): `Start_returns_reachable_endpoint_with_key`; `Wrong_key_is_rejected_by_engine` (**Review Focus 3**); `Stop_kills_the_process`; `Two_starts_use_different_ports`; `Busy_port_is_not_reused`; `ReapOrphans_kills_stale_engine_from_pid_file`; `Start_fails_with_clear_message_if_engine_missing`.
- [ ] **Step 2:** Run `dotnet test --filter EngineHostTests`. Expected: FAIL.
- [ ] **Step 3:** Implement; wait for the engine to answer `GET /` before returning from `StartAsync`, with a 30 s timeout.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(addin): engine host with key, free port and orphan reaping`.

### Task 14: Read levels, footprints and Rooms from Revit

**Files:**
- Create: `addin/Qbiq.PathTool.Core/IModelReader.cs`, `addin/Qbiq.PathTool.Addin/Extraction/RevitModelReader.cs`, `addin/Qbiq.PathTool.Addin/Extraction/RoomChecks.cs`, `addin/Qbiq.PathTool.Tests/RoomChecksTests.cs`

**Interfaces:**
- Produces: `IModelReader { IReadOnlyList<string> LevelNames(); LevelPayload ReadLevel(string levelName); }`; `RevitModelReader(Document doc) : IModelReader` reading walls (curved walls tessellated), doors, windows, columns and furniture footprints and Rooms (`placed` = `Location != null`, `enclosed` = `Area > 0` and boundary segments returned, `area` in model units) for the level, in the active phase and primary design option, ignoring linked models, all in Revit's internal units/origin with `UnitsToMetres = 0.3048`; no Transaction is ever opened. `RoomChecks.Classify(room): "unplaced"|"unenclosed"|"zero_area"|null` is pure.

- [ ] **Step 1: Write failing tests** for `RoomChecks` (each class, plus a healthy room → null) and for `ReadLevel` against a **recorded** `IModelReader` fixture, so the rest of the add-in is testable without Revit.
- [ ] **Step 2:** Run `dotnet test --filter RoomChecksTests`. Expected: FAIL.
- [ ] **Step 3:** Implement. `RevitModelReader` is verified by hand in Step 5.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** In Revit 2024 open the test project, run a debug command that dumps `ReadLevel` to JSON, and post it to `/api/upload-revit`; confirm the response has the expected counts and `room_issues`. Record the dump as `backend/tests/fixtures/revit_real_level.json` if Kevin allows it to be committed.
- [ ] **Step 6:** Commit `feat(addin): read levels and rooms from Revit`.

### Task 15: Real 3D meshes from Revit

**Files:**
- Create: `addin/Qbiq.PathTool.Addin/Extraction/MeshReader.cs`; modify `RevitModelReader.cs`; test `addin/Qbiq.PathTool.Tests/MeshMathTests.cs`

**Interfaces:**
- Produces: `MeshReader.Read(Document doc, ElementId levelId) -> IReadOnlyList<MeshPayload>` (triangulated solids by category, `Type` among `wall|floor|ceiling|door|window|column|furniture|other`, colour from the material or null, `Opacity` from the material transparency, vertices in metres, Z-up, same origin); a pure helper `MeshMath.ToMetresZUp(XYZ feet) -> (double x, double y, double z)`.

- [ ] **Step 1: Write failing tests** for `MeshMath.ToMetresZUp` (feet to metres exactly, axes unchanged) and for merging triangles by material in a pure helper `MeshBuilder`.
- [ ] **Step 2:** Run `dotnet test --filter MeshMathTests`. Expected: FAIL.
- [ ] **Step 3:** Implement with `Element.get_Geometry`, `Solid.Faces` triangulation, per-material grouping; skip hidden/other-phase elements; do not load linked instances.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** In Revit, send the test project's level and confirm in the window that the real shapes line up with the route in the 3D view (walls, doors, furniture are where Revit shows them); note the vertex count before and after `reduce_meshes`.
- [ ] **Step 6:** Commit `feat(addin): triangulate real Revit geometry for the 3D view`.

### Task 16: Ribbon, window, main-thread reads, Save dialog

**Files:**
- Create: `addin/Qbiq.PathTool.Addin/App.cs`, `OpenPathToolCommand.cs`, `PathToolWindow.xaml(.cs)`, `ReadModelEvent.cs`, `addin/Qbiq.PathTool.Addin/QbiqPathTool.addin`

**Interfaces:**
- Consumes: `EngineHost`, `IModelReader`, `PayloadJson`, the page's host messages from Task 8/11.
- Produces: an `IExternalApplication` adding a **Path Tool** ribbon tab with one **Open Path Tool** button; `OpenPathToolCommand : IExternalCommand` opening a modeless `PathToolWindow` (WebView2 at `{BaseUri}?host=revit&key={Key}`); an `ExternalEventHandler` (`ReadModelEvent`) that reads on Revit's main thread, POSTs the payload to `/api/upload-revit` with the key, then sends the page `{type:"modelLoaded"}` (or `modelRefreshed` for **Refresh model**); WebView2 `DownloadStarting` shows a `SaveFileDialog` defaulting to `enscape_walkpath.xml`. The window calls `EngineHost.ReapOrphans` on first open and `Stop()` on Revit shutdown.

- [ ] **Step 1:** Implement the five files; reading levels must not block the window (progress state in the page while the event runs).
- [ ] **Step 2:** `dotnet build addin -c Release`; expected: builds with no warnings treated as errors.
- [ ] **Step 3:** Copy the output and `QbiqPathTool.addin` into `%AppData%\Autodesk\Revit\Addins\2024\`, start Revit 2024, and verify by hand: the tab appears; the button opens the window with the test model in 3D; closing Revit leaves no `engine` process (`Get-Process`); **Save path (XML)** writes a file that matches `/api/export/xml`.
- [ ] **Step 4:** Check Revit stays read-only: the model title bar shows no unsaved-changes mark after a full session.
- [ ] **Step 5:** Commit `feat(addin): ribbon, window and main-thread model read`.

### Task 17: Package the engine and an installer

**Files:**
- Create: `engine.spec` (from `qbiq.spec`: entry `run.py`, no `tkinter`, same data and hidden imports), `addin/build-all.bat`, `addin/install.ps1`

**Interfaces:**
- Produces: `dist/qbiq-engine/qbiq-engine.exe` accepting `--port` and `--key`; `build-all.bat` producing `addin/out/` (add-in DLLs, `.addin`, `engine/`, `install.ps1`); `install.ps1` copying to the Revit 2024 add-ins folder and rewriting the `.addin` `Assembly` path.

- [ ] **Step 1:** Run `pyinstaller engine.spec --clean --noconfirm`; expected: `qbiq-engine.exe` exists.
- [ ] **Step 2:** With the network off, run the exe with `--port 5555 --key test`, then `curl -H "X-Qbiq-Key: test" http://127.0.0.1:5555/api/demo`; expected 200 with plan JSON, and 403 without the header.
- [ ] **Step 3:** Run `build-all.bat` then `install.ps1` on a clean user profile; expected: Task 16's manual checks pass using the packaged engine.
- [ ] **Step 4:** Note in `addin/README.md` how to install, update, and what antivirus to whitelist.
- [ ] **Step 5:** Commit `build(addin): package the engine and install script`.

### Task 18: Acceptance on Kevin's project

**Files:** none (a checklist run; results go in `addin/ACCEPTANCE.md`)

- [ ] **Step 1:** On the project Kevin picks, open it in Revit 2024, press the button, and confirm the 3D model matches Revit.
- [ ] **Step 2:** Press Auto-path and Suggested Tour, edit a point in the 3D view, adjust the timeline, and play the camera view.
- [ ] **Step 3:** Change the Revit model, press **Refresh model**, and confirm points outside walkable space are flagged, not dropped.
- [ ] **Step 4:** On a model with broken rooms, confirm the banner appears and **Load JSON instead** fixes it.
- [ ] **Step 5:** Save the XML, upload it into Enscape by hand, and confirm Enscape plays the same route the window showed; compare with one of the team's hand-made XMLs for structure and position scale. Record the Enscape version.
- [ ] **Step 6:** Record results, and anything that fails, in `addin/ACCEPTANCE.md`; if the project keeps its core and shell in a linked file and Auto-path crosses walls, flag linked models as the first follow-up.
