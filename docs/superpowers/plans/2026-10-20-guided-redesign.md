# Guided Redesign, Title Cards, Music and Fades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Path Editor UI as a four-step guided flow with a floating dock, and add a preview-only video finish (title cards, generated music, fades) without changing the path or the Enscape XML.

**Architecture:** New logic lives in four small classic-script files under `frontend/js/` (pure functions, unit-tested with `node --test`, loaded by `index.html` as globals). `frontend/index.html` is restructured into a header, four step views and a dock, reusing today's functions for loading, routing, tour, camera, 3D and export. The backend is unchanged; one backend test pins that `settings.video` round-trips in the JSON export and never changes the XML.

**Tech Stack:** Flask, vanilla JS (classic scripts, no build), D3 v7, Three.js r128, Web Audio API, `node --test` (Node 24), pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-guided-redesign-design.md` (mockups linked at its top).

## Global Constraints

- Worktree `C:\Users\kevin\revit-walkthrough-v2\.worktrees\guided-redesign`, branch `guided-redesign`. Commit per task; never push.
- Python: venv `C:/Users/kevin/revit-walkthrough-v2/.venv/Scripts/python.exe`; tests `cd backend && <venv python> -m pytest -q`; flake8 `--extend-ignore=W292,W391,E302,E501`.
- JS unit tests: `node --test frontend/tests/` from the worktree root. No npm packages, no package.json.
- Dev server for this worktree: `cd backend && PORT=5002 PYTHONUTF8=1 <venv python> app.py` (5000 = master, 5001 = qbiq-design-json).
- Browser checks: playwright-core in `C:\Users\kevin\AppData\Local\Temp\claude\c--Users-kevin-classify\900a02b1-8173-4329-b4b7-91e9fbbcf2f6\scratchpad\pw` (Chromium `%LOCALAPPDATA%/ms-playwright/chromium-1248/chrome-win64/chrome.exe`, args `--use-angle=swiftshader --enable-unsafe-swiftshader`). Smoke scripts live there, not in the repo. Test plan: `C:/Users/kevin/Downloads/121937120410001.json`.
- `frontend/js/*.js` are classic scripts: top-level `function`/`const` declarations become globals; each file ends with `if (typeof module === 'object') module.exports = { … };`.
- Scripts and assets are referenced with relative URLs (`static/js/flow.js`, `static/img/qbiq-logo.svg`): Flask serves `frontend/` at `/static`, and the app may be hosted under `/r/<slug>/`.
- qbiq tokens: canvas `#f6f7f9`, panel `#ffffff`, borders `#e6e8ec`/`#d7dae0`, text `#1f2733`, muted `#5f6673`, accent `#2f6bff` (soft `#eaf1ff`, strong `#1f52d6`), dark `#1e2430`, ok `#31a354`/`#e8f5ec`, warn `#d99000`/`#fbf1e0`, danger `#d64545`; Inter; radius 8px (6px tight); shadows `0 1px 2px rgba(16,24,40,.06)`, `0 8px 24px rgba(16,24,40,.08)`.
- Preview-only: title cards, music and fades never enter the XML request, `waypoints` or `meta.cuts`.
- Card length 3 s each; fade 0.8 s total (0.4 out + 0.4 in); music fades in over the intro, fades out over the last 2 s; default theme Premium lobby, volume 0.7.

## Review Focus

1. App served under a sub-path (`/r/<slug>/`): every script/img URL in `index.html` is relative — pinned by `test_index_has_no_root_absolute_assets` (Task 5).
2. Fast room clicks: three clicks within the debounce must yield one rebuild whose stops follow the final pick order; a slow earlier response must not overwrite a newer one — pinned by smoke `rapid picks` (Task 6).
3. Logo that is not PNG/SVG or larger than 1.5 MB: rejected with a message, previous logo kept — pinned by `acceptLogo` tests (Task 3).
4. Fade picked backwards (in point before out point) or overlapping another fade: refused with a message, nothing stored — pinned by `makeFade` tests (Task 1).
5. `localStorage` missing or throwing (private window): app loads with defaults and saving prefs is a no-op — pinned by `loadBrandPrefs`/`saveBrandPrefs` throwing-storage tests (Task 3).

---

### Task 1: Video timeline logic

**Files:**
- Create: `frontend/js/video-timeline.js`
- Test: `frontend/tests/video-timeline.test.js`

**Interfaces:**
- Produces:
  - `INTRO_S = 3`, `OUTRO_S = 3`, `FADE_S = 0.8`
  - `routeDistances(frames: {x,y}[], unitsToMetres: number) -> number[]` — cumulative metres per frame, first 0.
  - `walkTimeAtDistance(dists: number[], walkSeconds: number, d: number) -> number` — seconds of the first moment the walk reaches `d` (frames are evenly spaced in time; interpolate within the crossing frame pair; clamp to [0, walkSeconds]).
  - `makeFade(aM: number, bM: number, fades: Fade[], lengthM: number) -> {fade: {outM, inM}} | {error: string}` — `Fade = {outM: number, inM: number}`.
  - `pruneFades(fades: Fade[], lengthM: number) -> Fade[]`
  - `buildTimeline({dists, walkSeconds, fades}) -> {total: number, blocks: Block[]}` — `Block = {kind: 'intro'|'walk'|'fade'|'outro', start, end, walkFrom, walkTo}` (walkFrom/walkTo in walk seconds; null for cards).
  - `sampleTimeline(tl, t: number) -> {kind, walkS: number|null, black: number, card: 'intro'|'outro'|null}`
  - `musicGain(t: number, total: number) -> number` (0..1)
  - `projectToRoute(frames: {x,y}[], dists: number[], unitsToMetres: number, x: number, y: number) -> number` — metres along the route of the nearest point to plan point (x, y).

- [ ] **Step 1: Write the failing tests** — fixture: 11 frames on a straight line `x = 0..10` plan units, `y = 0`, `unitsToMetres = 1`, `walkSeconds = 10`.

```js
const test = require('node:test'); const assert = require('node:assert/strict');
const T = require('../js/video-timeline.js');
const frames = Array.from({ length: 11 }, (_, i) => ({ x: i, y: 0 }));
const dists = T.routeDistances(frames, 1);
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);

test('routeDistances is cumulative metres', () => assert.deepEqual(dists, [0,1,2,3,4,5,6,7,8,9,10]));
test('walkTimeAtDistance interpolates', () => assert.equal(T.walkTimeAtDistance(dists, 10, 2.5), 2.5));
test('no fades: total is cards plus walk', () => assert.equal(T.buildTimeline({ dists, walkSeconds: 10, fades: [] }).total, 16));
test('a fade skips the walk between its points', () => {
  const tl = T.buildTimeline({ dists, walkSeconds: 10, fades: [{ outM: 2, inM: 6 }] });
  near(tl.total, 12.8);
  assert.deepEqual(tl.blocks.map(b => b.kind), ['intro', 'walk', 'fade', 'walk', 'outro']);
});
test('mid-fade is black, its edges are not', () => {
  const tl = T.buildTimeline({ dists, walkSeconds: 10, fades: [{ outM: 2, inM: 6 }] });
  assert.equal(T.sampleTimeline(tl, 5.4).black, 1);
  assert.equal(T.sampleTimeline(tl, 5.0).black, 0);
  near(T.sampleTimeline(tl, 5.8).walkS, 6);
});
test('cards report their card', () => {
  const tl = T.buildTimeline({ dists, walkSeconds: 10, fades: [] });
  assert.equal(T.sampleTimeline(tl, 1).card, 'intro');
  assert.equal(T.sampleTimeline(tl, 15).card, 'outro');
  assert.equal(T.sampleTimeline(tl, 4).walkS, 1);
});
test('makeFade refuses a backwards fade', () => assert.ok(T.makeFade(6, 2, [], 10).error));
test('makeFade refuses an overlapping fade', () => assert.ok(T.makeFade(5, 8, [{ outM: 2, inM: 6 }], 10).error));
test('makeFade accepts a forward fade', () => assert.deepEqual(T.makeFade(2, 6, [], 10).fade, { outM: 2, inM: 6 }));
test('pruneFades drops fades past the end', () => assert.deepEqual(T.pruneFades([{ outM: 2, inM: 6 }, { outM: 7, inM: 12 }], 10), [{ outM: 2, inM: 6 }]));
test('musicGain fades in over the intro and out over the last 2 s', () => {
  assert.equal(T.musicGain(0, 16), 0); assert.equal(T.musicGain(3, 16), 1);
  assert.equal(T.musicGain(15, 16), 0.5); assert.equal(T.musicGain(16, 16), 0);
});
test('projectToRoute snaps a point to route metres', () => near(T.projectToRoute(frames, dists, 1, 4.2, 3), 4.2));
```

- [ ] **Step 2: Run** `node --test frontend/tests/` — Expected: FAIL, `Cannot find module '../js/video-timeline.js'`.
- [ ] **Step 3: Implement the interfaces above in `frontend/js/video-timeline.js`.** Fades are processed in `outM` order; `makeFade` errors are user-facing copy: backwards → `"Pick the fade-in point further along the path than the fade-out point."`, overlap → `"Fades can't overlap. Pick points outside the existing fade."`, zero-length (`inM - outM < 0.5`) → `"Pick two points at least half a metre apart."`. In a fade block, `black` ramps 0→1 over the first 0.4 s (walkS = walkFrom) and 1→0 over the last 0.4 s (walkS = walkTo).
- [ ] **Step 4: Run** `node --test frontend/tests/` — Expected: PASS (12 tests).
- [ ] **Step 5: Commit** `git add frontend/js/video-timeline.js frontend/tests/video-timeline.test.js && git commit -m "feat(video): preview timeline with title cards and fades"`

### Task 2: Pick list logic

**Files:**
- Create: `frontend/js/pick-list.js`
- Test: `frontend/tests/pick-list.test.js`

**Interfaces:**
- Produces:
  - `MAX_PANS = 2`
  - `carryStopSettings(prev: Waypoint[], next: Waypoint[]) -> Waypoint[]` — returns a copy of `next` where each `stop` with a `room_id` found in `prev` takes `prev`'s `dwell_s` and `pan`. Does not mutate inputs. Pans beyond `MAX_PANS` (in route order) are set false.
  - `pickListFromWaypoints(waypoints: Waypoint[]) -> string[]` — stop `room_id`s in route order, unique.
  - `QUICK_ADD = { offices: /office/i, meeting: /conference|meeting|board/i, amenities: /kitchen|comfort|lounge|break|cafe|pantry/i }`
  - `quickAdd(rooms: {id, type}[], picked: string[], group: keyof QUICK_ADD) -> string[]` — `picked` plus matching room ids not already picked, in `rooms` order.
  - `canSetPan(waypoints: Waypoint[], i: number, on: boolean) -> boolean` — always true for `on = false`; for `on = true`, true while fewer than `MAX_PANS` other stops pan.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/pick-list.test.js`:

```js
const P = require('../js/pick-list.js');
const wp = (room_id, extra = {}) => ({ x: 0, y: 0, stop: room_id ? { room_id, dwell_s: 2, pan: false, ...extra } : null });
test('carry keeps dwell and pan by room', () => {
  const out = P.carryStopSettings([wp('a', { dwell_s: 5, pan: true })], [wp('b'), wp('a')]);
  assert.deepEqual(out.map(w => [w.stop.room_id, w.stop.dwell_s, w.stop.pan]), [['b', 2, false], ['a', 5, true]]);
});
test('carry does not mutate', () => { const next = [wp('a')]; P.carryStopSettings([wp('a', { dwell_s: 9 })], next); assert.equal(next[0].stop.dwell_s, 2); });
test('carry caps pans at 2', () => {
  const prev = ['a', 'b', 'c'].map(id => wp(id, { pan: true }));
  assert.equal(P.carryStopSettings(prev, ['a', 'b', 'c'].map(id => wp(id))).filter(w => w.stop.pan).length, 2);
});
test('pick list from stops', () => assert.deepEqual(P.pickListFromWaypoints([wp(null), wp('a'), wp('b'), wp('a')]), ['a', 'b']));
test('quick add offices in plan order, no repeats', () => {
  const rooms = [{ id: 'k', type: 'Kitchen' }, { id: 'o1', type: 'Office - Non Receiving Guests' }, { id: 'o2', type: 'Office' }];
  assert.deepEqual(P.quickAdd(rooms, ['o2'], 'offices'), ['o2', 'o1']);
});
test('third pan refused, unpan always allowed', () => {
  const w = [wp('a', { pan: true }), wp('b', { pan: true }), wp('c')];
  assert.equal(P.canSetPan(w, 2, true), false); assert.equal(P.canSetPan(w, 0, false), true);
});
```

- [ ] **Step 2: Run** `node --test frontend/tests/` — Expected: FAIL, module not found.
- [ ] **Step 3: Implement** the interfaces in `frontend/js/pick-list.js`.
- [ ] **Step 4: Run** `node --test frontend/tests/` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(tour): pick list helpers that keep per-room settings`

### Task 3: Video settings, persistence and the export contract

**Files:**
- Create: `frontend/js/video-settings.js`
- Test: `frontend/tests/video-settings.test.js`, `backend/tests/test_app_export_video_meta.py`

**Interfaces:**
- Consumes: `pruneFades` (Task 1) is not used here; fades are validated structurally only.
- Produces:
  - `THEMES = [{id:'premium-lobby', name:'Premium lobby', sub:'Warm piano, soft pads'}, {id:'modern-workspace', name:'Modern workspace', sub:'Light electronic pulse'}, {id:'bright-leasing', name:'Bright leasing', sub:'Upbeat, optimistic'}, {id:'cinematic-reveal', name:'Cinematic reveal', sub:'Slow swell to the end'}]`
  - `CARD_COLOURS = [{id:'charcoal', name:'Charcoal', hex:'#1e2430'}, {id:'blue', name:'qbiq blue', hex:'#2f6bff'}, {id:'teal', name:'Teal', hex:'#5b8a8c'}, {id:'sand', name:'Sand', hex:'#c9b79c'}]`
  - `defaultVideo() -> {name:'', tagline:'', outro:'', theme:'premium-lobby', volume:0.7, fades:[]}`
  - `cleanVideo(raw: any) -> Video` — strings trimmed and cut to 120 chars; unknown theme → default; volume clamped to [0, 1] (non-number → 0.7); fades kept only if finite, `0 <= outM < inM`, sorted by `outM`, at most 20.
  - `acceptLogo(file: {type: string, size: number}) -> string | null` — error copy or null. Allowed types `image/png`, `image/svg+xml`; max 1.5 MB (`1_572_864` bytes). Copy: `"Use a PNG or SVG logo."` / `"That logo is over 1.5 MB. Use a smaller file."`
  - `loadBrandPrefs(storage) -> {logo: string|null, logoName: string, colour: string, theme: string}` and `saveBrandPrefs(storage, prefs) -> void`, key `pathEditor.brand`, both wrapped in try/catch; defaults `{logo: null, logoName: '', colour: 'charcoal', theme: 'premium-lobby'}`.

- [ ] **Step 1: Write the failing JS tests:** `cleanVideo(null)` deep-equals `defaultVideo()`; `cleanVideo({theme:'x', volume:3, name:'  A  ', fades:[{outM:5,inM:2},{outM:1,inM:4}]})` gives theme `'premium-lobby'`, volume `1`, name `'A'`, fades `[{outM:1,inM:4}]`; `acceptLogo({type:'image/jpeg', size:10})` returns the PNG/SVG copy; `acceptLogo({type:'image/png', size:2_000_000})` returns the size copy; `acceptLogo({type:'image/svg+xml', size:3000})` is null; a storage whose `getItem`/`setItem` throw gives defaults from `loadBrandPrefs` and does not throw from `saveBrandPrefs`; save-then-load round-trips through a `Map`-backed fake storage.
- [ ] **Step 2: Write the backend test** `backend/tests/test_app_export_video_meta.py` using the app test client and a three-waypoint route `[[0,0],[500,0],[500,500]]` with `settings = {"duration": 10, "units_to_metres": 0.01}`:
  - `test_json_export_round_trips_video_meta` — POST `/api/export/json` with `settings["video"] = {"name": "One Harbour Plaza", "fades": [{"outM": 1, "inM": 3}]}`; `resp.get_json()["meta"]["video"]` equals that dict.
  - `test_xml_export_ignores_video_settings` — POST `/api/export/xml` with and without `settings["video"]`; `resp.data` is byte-identical.
- [ ] **Step 3: Run** `node --test frontend/tests/` (Expected: FAIL, module not found) and `cd backend && <venv python> -m pytest tests/test_app_export_video_meta.py -q` (Expected: PASS — this pins existing behaviour; if it fails, stop and report, the backend must not change silently).
- [ ] **Step 4: Implement** `frontend/js/video-settings.js`.
- [ ] **Step 5: Run** `node --test frontend/tests/` — Expected: PASS.
- [ ] **Step 6: Commit** `feat(video): video settings, logo checks and saved brand prefs`

### Task 4: Generated music themes

**Files:**
- Create: `frontend/js/music.js`
- Test: `frontend/tests/music.test.js`

**Interfaces:**
- Consumes: `THEMES` ids (Task 3).
- Produces:
  - `midiToHz(m: number) -> number`
  - `themePattern(id: string) -> {bpm: number, bars: number, notes: {beat: number, midi: number, beats: number, vel: number, voice: 'pad'|'keys'|'pulse'|'bass'}[]}` — one seamless loop; bpm: premium-lobby 70, modern-workspace 100, bright-leasing 118, cinematic-reveal 64.
  - `intensityAt(id: string, t: number, total: number) -> number` — 1 for all themes except cinematic-reveal: `0.35 + 0.65 * min(1, t / total)`.
  - `createMusicPlayer(makeContext = () => new AudioContext()) -> {setTheme(id), setVolume(v), start(atS: number, totalS: number), stop(), sample(id)}` — schedules `themePattern` loops with oscillators, a low-pass filter and ADSR envelopes; master gain = volume × `musicGain` (Task 1) × `intensityAt`; `sample(id)` plays 6 s of a theme at full gain then stops; the context is created lazily on first `start`/`sample` (user gesture).

- [ ] **Step 1: Write the failing tests:** `midiToHz(69) === 440`; for every theme id, `themePattern(id).bpm` equals the value above and every note satisfies `beat + beats <= bars * 4` (loop ends cleanly) and `0 < vel <= 1`; the four patterns are pairwise different; `intensityAt('cinematic-reveal', 0, 60) === 0.35`, `intensityAt('cinematic-reveal', 60, 60) === 1`, `intensityAt('bright-leasing', 0, 60) === 1`.
- [ ] **Step 2: Run** `node --test frontend/tests/` — Expected: FAIL.
- [ ] **Step 3: Implement** `frontend/js/music.js` within the characters in the spec's Music table (Premium lobby: piano-like keys over pads; Modern workspace: steady pulse + bass; Bright leasing: major-key keys + pulse; Cinematic reveal: sustained pads and a rising line).
- [ ] **Step 4: Run** `node --test frontend/tests/` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(video): four generated music themes`

### Task 5: App shell, dock and step 1

**Files:**
- Create: `frontend/js/flow.js`, `frontend/img/qbiq-logo.svg` (copy from the scratchpad path in the spec), `frontend/tests/flow.test.js`
- Modify: `frontend/index.html` (header, layout, empty state/drop overlay, script tags, keyboard handler)

**Interfaces:**
- Consumes: Tasks 1–4 files via `<script src="static/js/…">` before the inline script.
- Produces:
  - `STEPS = ['Load plan', 'Rooms & route', 'Camera style', 'Preview & export']`
  - `canEnterStep(step: 1|2|3|4, s: {loaded: boolean, waypointCount: number}) -> boolean` — 1 always; 2 needs `loaded`; 3 and 4 need `loaded && waypointCount >= 2`.
  - In `index.html`: `state.step` (1–4), `goStep(n)` (no-op when `!canEnterStep`), `renderDock()`, and step containers `#step-1` … `#step-4` (only the current one visible). Later tasks fill `#step-2`…`#step-4` and call `renderDock()` after state changes.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/flow.test.js`: the `canEnterStep` table above (6 cases), and `test_index_has_no_root_absolute_assets` — read `frontend/index.html`, assert no match for `/(src|href)="\/(?!\/)/` (no root-absolute asset URLs).
- [ ] **Step 2: Run** `node --test frontend/tests/` — Expected: FAIL (flow.js missing).
- [ ] **Step 3: Implement** `flow.js`; restructure `index.html`: header = qbiq logo (`static/img/qbiq-logo.svg`, 20px tall) | "Path Editor" | plan name and room count (replaces `#h-level`); the floating dock per the spec (dark pill, back, "STEP n OF 4", step name, dots, next button naming the next step; on step 4 the button is "Export Enscape XML" calling `exportRoute('xml')`); step 1 = the existing drop zone/file picker and empty state, plus "Continue a saved path" (today's Import Path input, enabled once a plan is loaded), and after load a summary (floor name, room count). Loading a plan auto-advances to step 2. ←/→ call `goStep(state.step ∓ 1)` when focus is not in an input. Remove the header export group (moves to step 4 in Task 9).
- [ ] **Step 4: Run** `node --test frontend/tests/` — Expected: PASS. Then browser smoke `pw/guided_shell.js` against `http://localhost:5002/`: load the test plan → header shows the logo and "17 rooms", dock reads "STEP 2 OF 4", Back returns to step 1, the step-3 dot cannot be entered with no route; no `pageerror`.
- [ ] **Step 5: Commit** `feat(ui): guided shell with floating dock and load step`

### Task 6: Step 2 — rooms and route

**Files:**
- Modify: `frontend/index.html` (tour panel → step-2 left panel; `generateTour`, `toggleTourRoom`, `removeTourRoom`, `renderTourPanel`, hand-edit entry points)

**Interfaces:**
- Consumes: `carryStopSettings`, `pickListFromWaypoints`, `quickAdd`, `canSetPan`, `MAX_PANS` (Task 2); `renderDock()` (Task 5).
- Produces: `state.routeHandEdited: boolean`; `state.durationTouched: boolean` (set by the step-3 length slider in Task 8); `scheduleRebuild()` (debounce 400 ms) and `rebuildTour()` with a sequence token so only the newest response is applied; `markHandEdited()`.

- [ ] **Step 1: Write the smoke test first** `pw/guided_rooms.js` (fails until implemented): load plan; click Conference, Office, Kitchen labels within 300 ms (**rapid picks**) → after the rebuild the pick list reads 1 Conference, 2 Office, 3 Kitchen and route stops' `room_id`s follow that order; set Stand & look on Conference and dwell 4 on Office, then click a fourth room → those settings survive; toggle Stand & look on 3 stops → the third is refused with a toast; drag a waypoint (hand edit) then remove a room → confirm dialog "Rebuild the route from your rooms? Your hand edits will be lost." → dismiss keeps waypoints and the pick list unchanged; "+ Meeting rooms" appends meeting rooms.
- [ ] **Step 2: Run** `node pw/guided_rooms.js` — Expected: FAIL (no step-2 panel).
- [ ] **Step 3: Implement** step 2 per the spec and the step-2 mockup: left panel (eyebrow, heading, help, quick-add pills, ordered pick list with drag-to-reorder, Look/Stand & look toggle chip bound to `stop.pan`, remove ×, tour stats, warnings incl. unreachable rooms), plan with numbered pins and "Start · Entrance" marker, labels toggle. Rebuilds replace "Generate tour"; apply `carryStopSettings(old, new)` to the result; call `setVideoLength(suggested)` only when `!state.durationTouched`, otherwise show "Suggested m:ss · Use suggested" in step 3 (Task 8 renders it from `state.suggestedS`). "Edit route by hand" (collapsible) holds today's Smart Path, waypoint/freehand tabs, waypoint list (dwell, Stand & look, Cut, heading, time of day), undo and Clear all; every mutating hand action calls `markHandEdited()`. Loading a path (step 1) sets `routeHandEdited = true` and the pick list from `pickListFromWaypoints`. Leave a placeholder `#camera-strip` under the plan for Task 7.
- [ ] **Step 4: Run** `node pw/guided_rooms.js` — Expected: PASS, no `pageerror`. Run `node --test frontend/tests/` — PASS.
- [ ] **Step 5: Commit** `feat(ui): rooms and route step with auto-rebuilding tour`

### Task 7: Step 2 — "What the camera will see"

**Files:**
- Modify: `frontend/index.html` (`#camera-strip`, 3D scene init)

**Interfaces:**
- Consumes: `init3DScene`, `build3DGeometry`, `syncCeiling`, `threeRenderer` (existing); `state.waypoints` stops; tour stop times from the last `/api/process-route` frames when available.
- Produces: `renderCameraStrip()` — called after each rebuild (debounced 600 ms).

- [ ] **Step 1: Extend** `pw/guided_rooms.js`: after 3 picks, `#camera-strip img` count is 3, each `src` starts with `data:image/`, captions read "1 · Conference" etc.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**: build the 3D scene once (hidden), render each stop's view (camera at the stop point, 1.57 m, looking at the room's `label_point`) into a 480×270 offscreen render target, `toDataURL('image/jpeg', 0.8)`; up to 4 visible, horizontal scroll beyond; caption "n · Room" and the time in the video (from the frames if loaded, else omitted).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): camera snapshots for picked rooms`

### Task 8: Step 3 — camera style

**Files:**
- Modify: `frontend/index.html` (camera card → `#step-3`)

**Interfaces:**
- Consumes: `state.durationTouched`, `state.suggestedS` (Task 6); existing `syncSlider`, `applyPreset`, `CAMERA_PRESETS`, `loadPreviewFrames`.
- Produces: none new.

- [ ] **Step 1: Write the smoke** `pw/guided_camera.js`: with a tour, go to step 3 → controls labelled "Video length", "Smoothness", "Field of view", "U-turn radius", "Look around at start", and presets Quick/Standard/Cinematic exist; moving Video length sets `state.durationTouched`; a later rebuild in step 2 keeps the length and step 3 shows "Use suggested", which restores the suggestion when clicked; the export request body for the same tour (captured via `page.route`) equals the body the `qbiq-design-json` app at :5001 sends for the same picks and settings.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** step 3 per the spec: settings panel (existing inputs, plain labels, presets), the plan with the route read-only, a small "Preview" button that plays the route in a compact 3D view, warnings from `/api/process-route` listed in the panel.
- [ ] **Step 4: Run** — Expected: PASS (including the request-body parity check).
- [ ] **Step 5: Commit** `feat(ui): camera style step`

### Task 9: Step 4 — preview, timeline and export

**Files:**
- Modify: `frontend/index.html` (3D panel → `#step-4` main; `render3DLoop`, `updatePlaybackDisplay`, `loadPreviewFrames`, export buttons)

**Interfaces:**
- Consumes: `routeDistances`, `buildTimeline`, `sampleTimeline`, `musicGain` (Task 1); `createMusicPlayer` (Task 4); `state.video` (shape of `defaultVideo()`, Task 3).
- Produces: `p3.timeline`, `p3.tl` (timeline seconds), `rebuildTimeline()`; the playback clock runs in timeline seconds; `#title-card` overlay rendered from `state.video` + brand prefs; `exportRoute('json')` adds `settings.video = state.video`.

- [ ] **Step 1: Write the smoke** `pw/guided_preview.js`: enter step 4 → preview loads automatically; at t = 1 s `#title-card` is visible with the property name; set one fade `{outM: 5, inM: 15}` in `state.video.fades` and call `rebuildTimeline()` → the time readout total equals `3 + walk − skipped + 0.8 + 3` (rounded to the second), and the timeline lane shows Intro, Fade and Outro blocks; seek to mid-fade → `#p3d-fade` opacity is 1; the XML export request body has no `video` key; the JSON export request has `settings.video`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** step 4 layout per the mockup (large preview with "Preview · m:ss / m:ss" and theme overlays, timeline with Video and Music lanes to scale, scrub by click/drag, speed control, the preview-only note, "Save path JSON" secondary action; the resize handle is removed). Playback: advance `p3.tl`, `sampleTimeline` → camera from `walkS / walkSeconds`, black = max(timeline black, existing cut fade), title card for intro/outro; music `start/stop` follow play/pause/seek. Space toggles play when focus is not in a field.
- [ ] **Step 4: Run** — Expected: PASS; `node --test frontend/tests/` PASS.
- [ ] **Step 5: Commit** `feat(ui): preview step with title cards, fades and music playback`

### Task 10: Step 4 — Video panel

**Files:**
- Modify: `frontend/index.html` (right panel in `#step-4`; `importFromJSON`; route-change hook)

**Interfaces:**
- Consumes: `THEMES`, `CARD_COLOURS`, `cleanVideo`, `acceptLogo`, `loadBrandPrefs`, `saveBrandPrefs` (Task 3); `makeFade`, `pruneFades`, `projectToRoute` (Task 1); `createMusicPlayer().sample` (Task 4); `rebuildTimeline()` (Task 9).
- Produces: `state.video` edits; `state.fadePick: null | {outM?: number}`; `state.routeChangedSinceFades: boolean`.

- [ ] **Step 1: Write the smoke** `pw/guided_video.js`: upload a PNG logo via the Brand input → card preview shows it, reload → still there (localStorage); upload a JPEG → toast "Use a PNG or SVG logo." and the PNG stays; type property name → intro card text updates; choose "Bright leasing" → overlay shows it; "+ Add fade" then click two route points backwards → toast with the backwards copy and no fade; forwards → a fade row "a → b · From → To · skips N m · 0.8 s fade to black"; save path JSON and re-import it → name, theme and fade restored, logo from prefs; change rooms in step 2 so the route is shorter than a fade → the fade is dropped and step 4 shows "Route changed — check your fades".
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** the Video panel per the mockup (Brand: logo drop/Replace, live intro-card mini preview, colour swatches, Property name, Address or tagline, Outro line; Music: 2×2 theme cards with sample buttons, volume slider; Fades: rows with remove ×, "+ Add fade", help text). Fade picking happens on a compact plan inside step 4 (toggle "Show plan" over the preview), clicks mapped with `projectToRoute`. `importFromJSON` reads `cleanVideo(data.meta?.video)`; `importFromXML` resets `state.video = defaultVideo()` (XML has no meta). After any route rebuild or hand edit, run `pruneFades` with the new route length and set the notice when fades existed.
- [ ] **Step 4: Run** — Expected: PASS; full checks: `node --test frontend/tests/`, `cd backend && <venv python> -m pytest -q`, flake8.
- [ ] **Step 5: Commit** `feat(ui): video panel for brand, music and fades`
