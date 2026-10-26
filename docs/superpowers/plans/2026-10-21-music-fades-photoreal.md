# Real Music, Fade Pins, Photoreal Preview and Video Render — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the synthesized music with four real tracks, replace fade picking with draggable pins on a mini-map, make the 3D preview look as close to photoreal as a real-time WebGL renderer allows, and add an offline best-quality MP4 render with cards, fades and music.

**Architecture:** Pure logic goes in focused `frontend/js/*.js` classic scripts with `node --test` tests (music timing, fade pins, UV mapping and finishes, render quality, frame schedule). three.js moves from the r128 global build to r186 ES modules loaded through an import map; a small module (`three-boot.js`) exposes `window.THREE` and the add-ons so the existing page script keeps working. The backend adds a `finish` name to each 3D mesh; nothing else on the backend changes.

**Tech Stack:** three@0.186.1 (+ examples/jsm add-ons), mediabunny@1.61.3, WebCodecs, Web Audio (OfflineAudioContext), CC0 textures (ambientCG / Poly Haven) and HDRI (Poly Haven), Mixkit tracks, Flask, `node --test`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-music-fades-photoreal-design.md` (continues `2026-10-20-guided-redesign-design.md`).

## Global Constraints

- Worktree `C:\Users\kevin\revit-walkthrough-v2\.worktrees\guided-redesign`, branch `guided-redesign`; commit per task; never push.
- XML and saved-path waypoints/cuts unchanged — the camera parity smoke (`pw/guided_camera.js`) must stay green.
- JS tests: `node --test "frontend/tests/*.test.js"`; Python: `cd backend && <venv python> -m pytest -q`; flake8 `--extend-ignore=W292,W391,E302,E501`.
- Browser smokes: scratchpad `pw/` (playwright-core), against the dedicated test server `PORT=5003` (never Kevin's :5002). Reference app for parity: :5001.
- CDN pins (import map, jsDelivr): `three@0.186.1` (`build/three.module.js`, `examples/jsm/`), `mediabunny@1.61.3`. No other new runtime libraries.
- Assets: relative URLs under `frontend/` (`frontend/audio/…`, `frontend/assets/…`); all textures and the HDRI CC0; credits files beside them; total new assets ≲ 40 MB.
- Target: Chrome/Edge on Windows; MP4 (H.264 + AAC) there, WebM (VP9 + Opus) fallback elsewhere.
- Lighting is one fixed daylight setup; time of day is ignored by the 3D.
- Music fades in over the 3 s intro, out over the last 2 s; loops with a 2 s crossfade when the video is longer than the track; plays only at 1×.

## Review Focus

1. Video longer than its track (e.g. 300 s with a 96 s track): music loops with a crossfade, never goes silent — pinned by `trackOffset` loop tests (Task 2).
2. An HDRI or texture fails to load (offline, 404): the preview still renders with plain materials and no page error — pinned by smoke `asset failure` (Task 6).
3. WebCodecs H.264/AAC unavailable: the render dialog says so and offers WebM — pinned by smoke `no AAC` (Task 7).
4. A pin dragged past the other pin or into another fade: it stops at the boundary with a hint — pinned by `clampPin` tests (Task 3).
5. Cancel during a video render: no file is saved, the preview returns to its normal size and quality, the app is usable — pinned by smoke `cancel render` (Task 7).

---

### Task 1: Backend — a finish name on every 3D mesh

**Files:**
- Modify: `backend/qbiq_scene3d.py` (`Mat`, `_mat`, material constants, room floor material at ≈ line 328, mesh export at ≈ line 979)
- Test: `backend/tests/test_scene_finish.py`

**Interfaces:**
- Produces: each mesh dict from the scene export has `"finish": str`; `floor_finish(space_type: str) -> str` in `qbiq_scene3d`.
- Finish vocabulary (exact strings): `carpet, wood, concrete, plaster, glass, metal, steel, oak, laminate, fabric, plastic, foliage, ceramic, screen, ceiling, light, plain`.

- [ ] **Step 1: Write the failing tests** — `floor_finish('Office - Non Receiving Guests') == 'carpet'`, `floor_finish('Conference') == 'carpet'`, `floor_finish('Open Space WorkStation') == 'carpet'`, `floor_finish('Kitchen') == 'wood'`, `floor_finish('Comfort Zone') == 'wood'`, `floor_finish('Corridor') == 'concrete'`, `floor_finish('') == 'concrete'`; constants: `WALL.finish == 'plaster'`, `GLASS.finish == WINDOW.finish == 'glass'`, `FABRIC_GREY.finish == 'fabric'`, `OAK_LIGHT.finish == 'oak'`, `METAL.finish == 'metal'`, `STAINLESS.finish == 'steel'`, `CEILING_MAT.finish == 'ceiling'`, `LIGHT_MAT.finish == 'light'`; an exported scene for `C:/Users/kevin/Downloads/121937120410001.json` (reuse the loader the existing `test_scene_catalogue_real_files.py` uses; skip if the file is missing) has a `finish` in the vocabulary on every mesh and at least one `carpet` and one `wood` floor.
- [ ] **Step 2: Run** `cd backend && <venv python> -m pytest tests/test_scene_finish.py -q` — Expected: FAIL (`floor_finish` missing / no `finish` field).
- [ ] **Step 3: Implement** — `Mat` gains a trailing `finish` field (default `'plain'`); `_mat(..., finish='plain')`; set each constant's finish per the vocabulary; the per-room floor material uses `floor_finish(space_type)` (rule: office|conference|meeting|board|focus|open space|work → carpet; kitchen|pantry|cafe|comfort|lounge|reception|wellness → wood; else concrete); the export adds `"finish": m.finish`.
- [ ] **Step 4: Run** the new test file and the full backend suite + flake8 — Expected: PASS, no new flake8 hits.
- [ ] **Step 5: Commit** `feat(3d): finish names on scene meshes`

### Task 2: Real music tracks

**Files:**
- Create: `frontend/audio/premium-lobby.mp3`, `modern-workspace.mp3`, `bright-leasing.mp3`, `cinematic-reveal.mp3` (downloaded from the spec's URLs), `frontend/audio/CREDITS.md`
- Modify: `frontend/js/music.js` (rewrite), `frontend/js/video-settings.js` (`THEMES[].sub` = "Title — Artist"), `frontend/index.html` (`renderTimelineLanes` music lane, `sampleTheme`), `frontend/tests/music.test.js` (rewrite)

**Interfaces:**
- Consumes: `musicGain(t, total)` (video-timeline.js).
- Produces (music.js):
  - `TRACKS = { 'premium-lobby': { file: 'frontend/audio/premium-lobby.mp3', title: 'Your Breath', artist: 'Eugenio Mininni', durationS: 236 }, 'modern-workspace': { …'Focus on Yourself', 'Eugenio Mininni', 286 }, 'bright-leasing': { …'Motivating Mornings', 'Ahjay Stelino', 96 }, 'cinematic-reveal': { …'Drawing the Sky', 'Eugenio Mininni', 207 } }` (durations from the decoded files, whole seconds).
  - `LOOP_CROSSFADE_S = 2`
  - `trackOffset(atS: number, durS: number) -> number` — position in the newest pass of the track for timeline second `atS`: pass k starts at `k × (durS − LOOP_CROSSFADE_S)`, so the offset is `atS mod (durS − LOOP_CROSSFADE_S)`; during the first 2 s of a pass the previous pass is still sounding its last 2 s (the crossfade).
  - `createMusicPlayer(makeContext?) -> { setTheme(id), setVolume(v), start(atS, totalS), stop(), sample(id), prime(), playing }` — same surface as today; decodes and caches each track once (fetch + `decodeAudioData`); schedules `AudioBufferSourceNode`s from `trackOffset`, with a crossfade source near each loop point; master gain = volume × `musicGain`.
  - `renderMusicMix(id, totalS, volume, sampleRate = 48000) -> Promise<AudioBuffer>` — OfflineAudioContext render of the same envelope and looping, used by Task 7.
  - `intensityAt` and `themePattern` are removed (the timeline lane uses `musicGain` alone).

- [ ] **Step 1: Write the failing tests** (`music.test.js`): `trackOffset(10, 96) === 10`; `trackOffset(93, 96) === 93`; `trackOffset(95, 96) === 1` (second pass began at 94 s, crossfading); `trackOffset(96, 96) === 2`; `trackOffset(300, 96) === 300 % 94`; every `TRACKS` entry has a `file` under `frontend/audio/` that exists on disk (`fs.existsSync`), a title and a positive duration; the four ids equal `THEMES.map(t => t.id)`. Keep the `prime()` fake-context test (no context created twice, nothing started).
- [ ] **Step 2: Run** `node --test "frontend/tests/*.test.js"` — Expected: FAIL.
- [ ] **Step 3: Download** the four MP3s with curl from the spec's URLs into `frontend/audio/` (names above); write `CREDITS.md` (title, artist, source URL, "Mixkit Stock Music Free License", date fetched). Read each file's duration (decode in the browser smoke or `ffprobe` if present) and put the whole-second values in `TRACKS`.
- [ ] **Step 4: Implement** music.js per Interfaces; update `THEMES[].sub` to "Your Breath — Eugenio Mininni" etc.; the timeline music lane draws `musicGain` only; `sample(id)` plays 15 s from the track start with 0.3 s fade-in and 1 s fade-out.
- [ ] **Step 5: Run** unit tests — PASS. Browser smoke `pw/guided_music.js` (port 5003): step 4 → `state.video.theme = 'bright-leasing'`, play → `musicPlayer().playing === true` and the player's decoded buffer for that id has `duration` within 1 s of `TRACKS[id].durationS`; seek to 120 s on a 100 s+ timeline → no page error; theme card text shows "Motivating Mornings". Then all earlier smokes (`guided_video.js`, `guided_preview.js`).
- [ ] **Step 6: Commit** `feat(music): four real tracks replace the synthesizer`

### Task 3: Fade pins on a mini-map, and the mini-map in the video

**Files:**
- Create: `frontend/js/fade-pins.js`, `frontend/tests/fade-pins.test.js`, `frontend/js/minimap.js`, `frontend/tests/minimap.test.js`
- Modify: `frontend/js/video-settings.js` (`minimap` setting), `frontend/tests/video-settings.test.js`
- Modify: `frontend/index.html` (step-4 Fades section; remove the plan-swap picking: `startFadePick`, `fadePickClick`, `endFadePick`, `body.picking-fade` CSS, the fade branch in `handleClick`/`actOnClick`)

**Interfaces:**
- Consumes: `routeDistances`, `projectToRoute`, `walkTimeAtDistance`, `buildTimeline`, `FADE_S` (video-timeline.js); `roomColour` (room-colours.js); `seekTimeline`, `rebuildTimeline`, `renderVideoPanel`, `routePointAt` (index.html).
- Produces (fade-pins.js):
  - `MIN_GAP_M = 0.5`, `PIN_STEP_M = 0.5`, `PIN_STEP_BIG_M = 5`
  - `defaultPins(fades: Fade[], lengthM: number) -> {outM, inM} | null` — 30% / 50% of the route if that range is free; otherwise the middle third of the largest free gap; `null` if no gap ≥ 2 × `MIN_GAP_M`.
  - `clampPin(kind: 'out'|'in', m: number, draft: {outM, inM}, others: Fade[], lengthM: number) -> { m: number, hint: string|null }` — keeps `0 ≤ out`, `out + MIN_GAP_M ≤ in ≤ lengthM`, and outside every other fade's `[outM, inM]`; `hint` is user copy when it had to stop the pin: `"The fade-in has to come after the fade-out."` or `"Fades can't overlap."`.
  - `stepPin(m: number, dir: -1|1, big: boolean) -> number`
- In index.html: `state.fadeDraft: null | { outM, inM, index: number|null }` (index = editing an existing fade), `openFadeEditor(index|null)`, `closeFadeEditor(save: boolean)`, `previewCut()`.
- Produces (minimap.js) — one drawing routine for the fade editor and the video:
  - `mapTransform(bounds: {xmin, ymin, xmax, ymax}, w: number, h: number, pad: number) -> { k, ox, oy }` — uniform scale that fits the plan inside `w × h` with `pad` px margin, centred; a plan point `(x, y)` (display units, svg y already flipped, as in `p3.frames`) maps to `(ox + x·k, oy + y·k)`. Pure.
  - `toMap(t, x, y) -> [px, py]`. Pure.
  - `drawMiniMap(ctx: CanvasRenderingContext2D, { w, h, rooms, route, camera?, pins?, fadeRanges? })` (browser only) — white rounded card, room polygons filled with `roomColour(type)`, route polyline (accent, 2 px), optional camera dot (accent, 4 px radius, white ring) with a 60° view cone pointing at `camera.yaw`, optional OUT/IN pins, skipped parts of the route drawn faded.
- video-settings.js: `defaultVideo()` gains `minimap: true`; `cleanVideo` keeps a boolean `minimap` (non-boolean → `true`).
- In index.html: the preview overlay `#p3d-minimap` (a `<canvas>`, bottom-right, ≈22% of the preview width, aspect from the plan), redrawn each frame from the current camera pose; hidden when `!state.video.minimap`, during intro/outro cards and when the fade overlay is fully black; a **Mini-map** switch (`#v-minimap`, role=switch) in the Video panel; `drawMiniMapFrame(ctx, w, h)` exposed for Task 7.

- [ ] **Step 1a: Write the failing mini-map tests** — `mapTransform({xmin: 0, ymin: 0, xmax: 100, ymax: 50}, 220, 120, 10)` gives `k === 2` (limited by width: (220−20)/100 = 2 vs (120−20)/50 = 2 → 2), centring so `toMap(t, 0, 0)` is `[10, 10]` and `toMap(t, 100, 50)` is `[210, 110]`; a tall plan `{0,0,10,100}` in 220×120 with pad 10 gives `k === 1` and is centred horizontally (`toMap(t, 0, 0)[0] === 105`); `cleanVideo({})` has `minimap === true`, `cleanVideo({minimap: false}).minimap === false`, `cleanVideo({minimap: 'yes'}).minimap === true`.
- [ ] **Step 1b: Write the failing pin tests** — `defaultPins([], 100)` → `{outM: 30, inM: 50}`; `defaultPins([{outM: 25, inM: 60}], 100)` → a pair inside the larger free gap `[60, 100]`'s middle third (`outM ≈ 73.33`, `inM ≈ 86.67`); `defaultPins([{outM: 0.2, inM: 99.9}], 100)` → `null`; `clampPin('in', 10, {outM: 20, inM: 40}, [], 100)` → `{m: 20.5, hint: 'The fade-in has to come after the fade-out.'}`; `clampPin('in', 45, {outM: 20, inM: 30}, [{outM: 40, inM: 50}], 100)` → `m < 40` (stops before the other fade) with hint `"Fades can't overlap."`; `clampPin('out', 45, {outM: 55, inM: 70}, [{outM: 40, inM: 50}], 100)` → `m > 50` (stops after it) with the same hint; `clampPin('in', 120, {outM: 20, inM: 40}, [], 100).m === 100`; `stepPin(10, 1, false) === 10.5`, `stepPin(10, -1, true) === 5`.
- [ ] **Step 2: Run** unit tests — FAIL (module missing).
- [ ] **Step 3: Implement** minimap.js and the `minimap` setting; the preview mini-map overlay and its switch; fade-pins.js; then the Fades section (its map uses `drawMiniMap` on a canvas with pointer hit-testing for the pins) per the spec and mockup option 3: `+ Add fade` → `openFadeEditor(null)` (toast "There's no room for another fade on this route." when `defaultPins` is null); the editor shows an SVG mini-map (`#fade-map`, viewBox from `state.bounds`, room polygons filled with `roomColour`, route polyline from `p3.frames`, OUT pin dark `#1e2430`, IN pin accent) with pointer-drag pins snapping via `projectToRoute` then `clampPin`; hints in `#fade-hint`; two live frame thumbnails (`#fade-out-shot`, `#fade-in-shot`) rendered with the same snapshot method as the camera strip, throttled to one render per 150 ms; while dragging, `seekTimeline` to that pin's time so the big preview shows it; summary "Skips N m · saves M s · 0.8 s fade to black"; `Preview the cut` plays from 2 s before the draft's fade to 2 s after it (timeline rebuilt with the draft) then pauses; `Done` saves into `state.video.fades` (replacing `index` when editing), `Cancel`/Esc discards; clicking a fade row opens it for editing; pins are focusable buttons (`role="slider"`, `aria-valuenow` in metres) and ←/→ use `stepPin` (Shift = big) then `clampPin`.
- [ ] **Step 4: Run** unit tests — PASS. Rewrite `pw/guided_video.js`'s fade part and run it: add fade → editor visible and the 3D preview still visible; drag IN before OUT → pin stops, hint shown; drag OUT pin by mouse along the route → `aria-valuenow` changes and the big preview's `p3.tl` follows; keyboard → 0.5 m / 5 m steps; Done → one fade row "→ … Skips N m"; click the row → editor reopens with that fade's pins; Preview the cut → playback starts before and stops after the fade; save + re-import still restores the fade. Then `guided_fixes.js` (its old dot-click fade check is replaced by a pin-keyboard check). Mini-map smoke (in `guided_video.js`): during playback `#p3d-minimap` is visible and its pixel content changes between two times 3 s apart (the dot moved); at 1 s (intro card) it is hidden; switching **Mini-map** off hides it and `state.video.minimap === false` survives save + re-import.
- [ ] **Step 5: Commit** `feat(fades): pins on a mini-map; mini-map with the camera dot in the video`

### Task 4: three.js r186

**Files:**
- Create: `frontend/js/three-boot.js` (ES module)
- Modify: `frontend/index.html` (script tags, renderer setup, the few r128-only APIs, 3D readiness)

**Interfaces:**
- Produces: `window.THREE` (r186 namespace) and `window.THREE_ADDONS = { EffectComposer, RenderPass, GTAOPass, UnrealBloomPass, OutputPass, SMAAPass, HDRLoader, RectAreaLightUniformsLib }`, then `window.dispatchEvent(new Event('three-ready'))`; `window.threeReady: Promise<void>` created by an inline classic script before the module so page code can `await` it.

- [ ] **Step 1: Write the failing smoke** `pw/guided_three.js`: after load, `THREE.REVISION === '186'`, `typeof THREE_ADDONS.GTAOPass === 'function'`; step 4 preview renders (canvas non-blank: sampled pixels have > 3 tones); the camera strip still produces images; no page errors.
- [ ] **Step 2: Run** — FAIL (`REVISION` is `'128'`).
- [ ] **Step 3: Implement** — import map (`three`, `three/addons/`, `mediabunny`) before any module; remove the r128 `<script>`; `three-boot.js` imports and publishes as above (HDRLoader is r186's loader for `.hdr`; fall back to `RGBELoader` if `HDRLoader` is absent); code paths that build the scene `await window.threeReady` (or no-op until ready); r186 renames: `renderer.outputColorSpace = THREE.SRGBColorSpace`, `texture.colorSpace = THREE.SRGBColorSpace`, `THREE.MathUtils.degToRad`, drop `convertSRGBToLinear` (r186 colour management converts `Color` set from hex/CSS automatically); re-balance light intensities for r186's physically based units so the scene's brightness matches today's (compare screenshots).
- [ ] **Step 4: Run** `guided_three.js` — PASS; then every earlier smoke on :5003, including the camera parity check.
- [ ] **Step 5: Commit** `refactor(3d): move to three.js r186`

### Task 5: Real materials and textures

**Files:**
- Create: `frontend/js/materials3d.js`, `frontend/tests/materials3d.test.js`, `frontend/assets/textures/<finish>/{albedo,normal,roughness}.jpg` (1K, CC0), `frontend/assets/CREDITS.md`
- Modify: `frontend/index.html` (`buildContractMesh`, texture cache)

**Interfaces:**
- Consumes: mesh `finish` (Task 1), `THREE` (Task 4).
- Produces (materials3d.js):
  - `FINISH_LOOKS: Record<finish, { maps: string|null, tileM: number, roughness: number, metalness: number, tint: string|null, physical?: object }>` — `maps` is a folder under `frontend/assets/textures/` or null (plain colour); `tileM` = metres one texture repeat covers.
  - `finishFor(mesh: {type, finish?, color}) -> finish` — `mesh.finish` when present, else a fallback from `type` (wall→plaster, floor→concrete, glass|window→glass, frame→metal, ceiling→ceiling, light→light, else plain).
  - `boxUV(positions: Float32Array, normals: Float32Array, tileM: number) -> Float32Array` — per vertex, project onto the plane facing the dominant normal axis and divide by `tileM`.
  - `makeMaterial(mesh, textures) -> THREE.Material` (browser only): glass → `MeshPhysicalMaterial` (transmission ≈ 1, roughness ≈ 0.05, ior 1.5, thickness 0.01); light → emissive (`emissiveIntensity` for bloom); others → `MeshStandardMaterial` with the finish's maps (albedo sRGB, normal, roughness), colour = mesh colour × tint.
- Texture set (CC0, 1K): carpet, wood (floor), concrete (polished), plaster, oak (veneer), laminate, fabric, metal (brushed), steel, plastic (fine), ceramic (terracotta), foliage (leaf); `ceiling`, `screen`, `light`, `glass`, `plain` without maps.

- [ ] **Step 1: Write the failing tests** — `finishFor({type: 'wall'}) === 'plaster'`, `finishFor({type: 'furniture', finish: 'fabric'}) === 'fabric'`; `boxUV` on a unit quad facing +Y at y=0 spanning x,z ∈ [0, 2] with `tileM = 2` gives UVs spanning [0, 1]; a quad facing +X uses (z, y); every `FINISH_LOOKS[f].maps` folder exists with `albedo.jpg` (fs check); every backend finish from Task 1's vocabulary has an entry.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Download** the CC0 1K texture sets (ambientCG or Poly Haven) into the folders; resize/convert to JPG ≤ 1024 px if needed; record each source and licence in `frontend/assets/CREDITS.md`.
- [ ] **Step 4: Implement** materials3d.js and use it in `buildContractMesh` (non-indexed geometry for meshes that get `boxUV` so faces don't share UVs across axes; textures loaded once and cached per finish; while a texture is loading the material shows its plain colour).
- [ ] **Step 5: Run** unit tests — PASS; smoke `pw/guided_three.js` extended: at least one material per textured finish present in the scene has a `map`; glass is `MeshPhysicalMaterial`; screenshots of office, conference, kitchen saved for review.
- [ ] **Step 6: Commit** `feat(3d): textured physically based materials`

### Task 5b: Real furniture models

**Files:**
- Modify: `backend/qbiq_scene3d.py` (model-backed parts become placed items), plus wherever the scene payload is assembled (`backend/app.py` or the scene route)
- Create: `backend/tests/test_scene_items.py`, `frontend/js/furniture-models.js`, `frontend/tests/furniture-models.test.js`, `frontend/assets/models/<id>/…` (Poly Haven 1k glTF), credits added to `frontend/assets/CREDITS.md`
- Modify: `frontend/js/three-boot.js` (add `GLTFLoader` to `THREE_ADDONS`), `frontend/index.html` (scene build places items)

**Interfaces:**
- Consumes: `THREE`, `THREE_ADDONS` (Task 4); `makeMaterial`/finishes (Task 5) for the stand-in block.
- Produces (backend): `MODEL_CODES = frozenset({"L_S", "T_CF", "C_B", "V_P"})`; the 3D scene response gains `"items": [{"model": str, "x": float, "y": float, "yaw": float, "mirror": bool, "w": float, "d": float}]` — metres, same plan-space x/y as mesh verts, `yaw` radians from the component matrix, `w`/`d` = the part's placed footprint (local x / local y). `model` ∈ `{"sofa", "armchair", "coffee_table", "bar_stool", "plant"}`; `L_S` with `w < 1.2` → `"armchair"`. Those parts produce no faces; every other part (including chairs inside desk assemblies) is built as today.
- Produces (furniture-models.js):
  - `MODELS: Record<model, { files: string[] }>` — `frontend/assets/models/<id>/<id>_1k.gltf` paths (plant has 2–3 variants).
  - `variantFor(model: string, x: number, y: number) -> number` — a stable index into `files` from the position (same piece → same variant).
  - `fitScale(box: {w, d, h}, item: {w, d}) -> [sx, sy, sz]` — `sx = item.w / box.w`, `sz = item.d / box.d`, `sy = (sx + sz) / 2` (three's y is up).
- In index.html: each file loads once (GLTFLoader, cached, cloned per item), rotated by `yaw`, mirrored when `mirror`, standing on the floor at (x, y); while loading or on failure a rounded block of the footprint stands in; failure never raises a page error.

- [ ] **Step 1: Write the failing tests** — backend (`test_scene_items.py`): a component whose bom primary part is `L_S_L200_W90` yields one `sofa` item with `w ≈ 2.0`, `d ≈ 0.9` and contributes no furniture faces; `L_S_L90_W85` → `armchair`; `V_P_L50_W50` → `plant`; a component rotated 90° gives `yaw ≈ ±π/2` (sign per the three.js convention the frontend uses — document it); a desk assembly `T_WS_…|C_W_…` yields no items; the real file `C:/Users/kevin/Downloads/121937120410001.json` (skip if missing) yields ≥ 1 item and every item's `model` is in the set above. Frontend: `fitScale({w: 2, d: 1, h: 0.8}, {w: 1, d: 0.5})` → `[0.5, 0.5, 0.5]`; `fitScale({w: 1, d: 1, h: 1}, {w: 2, d: 1})` → `[2, 1.5, 1]`; `variantFor('plant', 3, 4) === variantFor('plant', 3, 4)` and is within `MODELS.plant.files.length`; every `MODELS[*].files` path exists on disk.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Download** from Poly Haven (CC0, 1k glTF with its bin and textures; file list from `https://api.polyhaven.com/files/<id>`): `sofa_03` (sofa), `modern_arm_chair_01` (armchair), `modern_coffee_table_01` (coffee table), `bar_chair_round_01` (bar stool), `potted_plant_02`, `potted_plant_04`, `pachira_aquatica_01` (plants). Look at each thumbnail (`https://cdn.polyhaven.com/asset_img/thumbs/<id>.png`) and swap for a better-fitting model from the same CC0 set if one looks wrong in an office. Record each in `frontend/assets/CREDITS.md`. Models total ≲ 25 MB.
- [ ] **Step 4: Implement** backend items and the frontend placement.
- [ ] **Step 5: Run** unit tests, the full backend suite, flake8 — PASS. Smoke `pw/guided_three.js` extended: the scene has ≥ 1 loaded glTF item; each placed item's world bounding-box footprint is within 15% of its `w × d`; **model failure**: with `page.route('**/assets/models/**', r => r.abort())` the preview renders, stand-in blocks exist and there are no page errors; screenshots of a lounge and a kitchen with stools.
- [ ] **Step 6: Commit** `feat(3d): real furniture models for sofas, armchairs, coffee tables, stools and plants`

### Task 5c: More detailed code-built furniture

**Files:**
- Modify: `backend/qbiq_scene3d.py` (desk, chair, monitor, storage, counter, printer builders)
- Test: `backend/tests/test_scene_detail.py` (existing scene tests stay green)

**Interfaces:**
- Consumes: the builders as they are (`_desk_part`, `_chair_part`, `_monitor`, `_storage_part`, `_counter_part`, `_printer_part`, `_round_rect`, `_fronts`).
- Produces: same builder signatures and the same footprints and heights; only detail changes.

- [ ] **Step 1: Write the failing tests** — a `T_WS` desk's top ring has rounded corners (> 4 points) and the desk has ≥ 4 leg/frame pieces plus a modesty panel below the top; a `C_W` chair's back ring is curved (> 4 points, not all on one line) and the chair keeps its five-star base and castors; a monitor has a stand (a piece from the desk top up to the screen) and a bezel thinner than 0.03 m around the screen; `S_LS` storage has a top with rounded edges and a handle on each front; the real file's full scene logs no "vertex cap" warning (no faces dropped).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the extra detail with the existing primitives (`_round_rect`, `_disc`, `_bar_ring`, prisms).
- [ ] **Step 4: Run** the new tests, the full backend suite, flake8 — PASS; smoke screenshots of an open-space desk cluster and a meeting room for review.
- [ ] **Step 5: Commit** `feat(3d): more detailed desks, chairs, monitors and storage`

### Task 6: Light, environment, post-processing and quality

**Files:**
- Create: `frontend/js/render3d.js`, `frontend/tests/render3d.test.js`, `frontend/assets/hdri/<name>_2k.hdr` (Poly Haven, CC0; daylight sky)
- Modify: `frontend/index.html` (`init3DScene`, `fitSunToPlan`, render loop, `resize3D`, camera strip and step-3 preview use the pipeline)

**Interfaces:**
- Consumes: `THREE`, `THREE_ADDONS` (Task 4); materials (Task 5).
- Produces (render3d.js):
  - `QUALITY = { draft: {…}, high: {…}, max: {…} }` — per level: `pixelRatio`, `shadowMapSize`, `ao` (off / GTAO samples), `bloom` (bool), `smaa` (bool), `supersample` (1 | 2).
  - `pickQuality(frameTimesMs: number[], current: 'draft'|'high') -> 'draft'|'high'` — switch to draft when the median of the last 30 frames > 40 ms; back to high when < 22 ms for 60 frames; ignores `max` (max is only for the video render).
  - `createPipeline(renderer, scene, camera) -> { setQuality(q), setSize(w, h), render(), quality }` (browser only).
  - `loadEnvironment(renderer, scene, url) -> Promise<boolean>` — PMREM from the HDRI as `scene.environment` and as background visible through windows; resolves `false` on failure and leaves a neutral fallback (RoomEnvironment-like gradient or the previous plain background).
- Lighting: sun (`DirectionalLight`) with soft shadows sized to the plan, low hemisphere fill, HDRI for reflections and ambient; ceiling light panels emissive with bloom plus up to 16 `RectAreaLight`s placed at the panels nearest the camera path (re-chosen when the route changes).

- [ ] **Step 1: Write the failing tests** — `pickQuality(Array(30).fill(50), 'high') === 'draft'`; `pickQuality(Array(30).fill(16), 'high') === 'high'`; `pickQuality(Array(60).fill(15), 'draft') === 'high'`; `pickQuality(Array(59).fill(15), 'draft') === 'draft'`; `QUALITY.max.supersample === 2` and `QUALITY.max.shadowMapSize >= QUALITY.high.shadowMapSize`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Download** a CC0 daylight HDRI (2k `.hdr`) from Poly Haven into `frontend/assets/hdri/`; credits.
- [ ] **Step 4: Implement** render3d.js and wire it: the render loop renders through the pipeline; scrubbing/dragging forces draft until 300 ms after the last input; `pickQuality` runs on measured frame times; the step-2 strip and step-3 preview use `high`.
- [ ] **Step 5: Run** unit tests — PASS; smoke `pw/guided_three.js` extended: `scene.environment` is set; the composer has GTAO, bloom, output and SMAA passes in high; **asset failure**: with `page.route('**/assets/hdri/**', r => r.abort())` the preview still renders (non-blank) and there are no page errors; screenshots of the same three views for side-by-side review with Task 5's.
- [ ] **Step 6: Commit** `feat(3d): daylight, soft shadows, AO, bloom and adaptive quality`

### Task 7: Render video

**Files:**
- Create: `frontend/js/video-render.js`, `frontend/tests/video-render.test.js`
- Modify: `frontend/index.html` (step-4 "Render video" button, dialog, progress overlay)

**Interfaces:**
- Consumes: `buildTimeline`, `sampleTimeline` (video-timeline.js); `renderMusicMix` (Task 2); `drawMiniMapFrame(ctx, w, h)` (Task 3); `createPipeline`, `QUALITY.max` (Task 6); title-card drawing (index.html's card content: logo, name, line, colour).
- Produces (video-render.js):
  - `VIDEO_FPS = 30`, `RESOLUTIONS = { '1080p': [1920, 1080], '720p': [1280, 720] }`
  - `frameTimes(totalS: number, fps: number) -> number[]` — `[0, 1/fps, …]`, `Math.round(totalS * fps)` entries.
  - `estimateMinutes(msPerFrame: number, totalS: number, fps: number) -> number` (rounded up to whole minutes, minimum 1).
  - `pickContainer(support: { avc: boolean, aac: boolean, vp9: boolean, opus: boolean }) -> 'mp4'|'webm'|null`.
  - `renderVideo({ resolution, onProgress, signal }) -> Promise<Blob>` (browser only): per frame — `sampleTimeline` → camera + black fade → `pipeline.render()` at `QUALITY.max` → composite onto a 2D canvas (fade overlay, title card for intro/outro, and the mini-map via `drawMiniMapFrame` when `state.video.minimap` is on and the frame is a walk frame) → mediabunny `CanvasSource`; audio from `renderMusicMix` → mediabunny `AudioBufferSource`; `Mp4OutputFormat` or `WebMOutputFormat` from `pickContainer` (support via `VideoEncoder.isConfigSupported` / `AudioEncoder.isConfigSupported`); rejects with an `AbortError` when `signal` aborts.
- UI: "Render video" opens a dialog (resolution 1080p/720p, estimate from rendering 3 test frames, Start/Cancel); during render a full-screen overlay with the current frame, "Frame n of N · elapsed · about M min left", Cancel; on finish download `walkthrough_<level>.mp4` (or `.webm`); afterwards the preview is restored to its size and quality.

- [ ] **Step 1: Write the failing tests** — `frameTimes(1, 30).length === 30`, `frameTimes(1, 30)[29] ≈ 29/30`; `estimateMinutes(150, 66, 30) === 5`, `estimateMinutes(10, 6, 30) === 1`; `pickContainer({avc: true, aac: true, vp9: true, opus: true}) === 'mp4'`, `pickContainer({avc: true, aac: false, vp9: true, opus: true}) === 'webm'`, `pickContainer({avc: false, aac: false, vp9: false, opus: false}) === null`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** video-render.js and the UI.
- [ ] **Step 4: Run** unit tests — PASS; smoke `pw/guided_render.js` (short route: two nearby rooms, `cam.dur` set to 6 s so the whole video is ~12 s; 720p): Start → wait for the download (`page.waitForEvent('download')`), the file's first bytes contain `ftyp` (MP4) and its size > 50 KB; **no AAC**: stub `AudioEncoder.isConfigSupported` to resolve `{supported: false}` → the dialog says "Your browser can't make MP4 with sound here — the video will be saved as WebM." and the saved file starts with the WebM magic `1A 45 DF A3`; **cancel render**: start, cancel after 2 frames → no download within 3 s, overlay gone, preview canvas back to its panel size, `pipeline.quality !== 'max'`, no page errors.
- [ ] **Step 5: Commit** `feat(video): render the walkthrough to MP4 with cards, fades and music`
