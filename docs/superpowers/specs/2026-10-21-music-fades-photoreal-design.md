# Real music, fade pins on a mini-map, photoreal 3D

**Date:** 2026-10-21 · **Branch:** `guided-redesign` (continues `2026-10-20-guided-redesign-design.md`)
**Mockups:** https://claude.ai/artifact/7sY3VaTEe239VSQqd9qt16 — board "B · Fades — 3 ways to set them", option 3 (picked).

## Intent

Kevin tested the guided Path Editor and gave three verdicts:
- The generated music "is really bad" — it must sound like real music.
- Fades work, but setting one is not user-friendly.
- The 3D "looks like a low-quality video game" — he wants it **as technically close
  to a photorealistic video as the browser allows, using the best capabilities available.**
  He left the approach to Claude ("whatever you say").

The path and the Enscape XML stay exactly as they are; everything here is about what
the user sees and hears in the app, plus a new finished-video output.

## Goals

1. **Music:** replace the synthesized themes with four real royalty-free recordings
   (Kevin chose Option 1 for each theme), bundled with the app.
2. **Fades:** replace "click two points on the plan" with option 3 — a mini-map with
   draggable OUT/IN pins on the route, live frames, and Preview the cut.
3. **Photoreal real-time preview:** upgrade the 3D preview to a modern physically based
   renderer with real materials and textures, image-based lighting, soft shadows,
   ambient occlusion, glowing ceiling lights and filmic colour — smooth enough to scrub.
4. **Render video:** a new step-4 action that renders the walkthrough frame by frame with
   the real-time renderer at its absolute best quality (no need to keep up live) and saves
   a finished MP4 with the intro/outro cards, fades and music. Kevin's choice: "I don't need
   an actual render, just a really good preview" — so no path tracing.

## Non-goals

- No change to the camera engine, the route, the XML, the tour or the step flow.
- No server-side rendering; everything renders in the user's browser.
- No WebGPU-only path: the app must keep working on WebGL2.

## Anti-goals

- The XML or the exported path JSON's waypoints/cuts changing.
- A preview that is prettier but stutters while scrubbing on an ordinary laptop: the
  real-time preview must stay interactive; heavy effects scale down rather than freeze.
- Assets with unclear rights: every texture/HDRI must be CC0, every track from the
  sources below.

## 1 · Music

| Theme id | Track | Source |
|---|---|---|
| `premium-lobby` | "Your Breath" — Eugenio Mininni (3:56) | https://assets.mixkit.co/music/634/634.mp3 |
| `modern-workspace` | "Focus on Yourself" — Eugenio Mininni (4:46) | https://assets.mixkit.co/music/568/568.mp3 |
| `bright-leasing` | "Motivating Mornings" — Ahjay Stelino (1:36) | https://assets.mixkit.co/music/33/33.mp3 |
| `cinematic-reveal` | "Drawing the Sky" — Eugenio Mininni (3:27) | https://assets.mixkit.co/music/606/606.mp3 |

- Licence: Mixkit Stock Music Free License (commercial video use, no attribution).
  Bundling the files inside the app is the grey area; acceptable for this proof of
  concept, and a `frontend/audio/CREDITS.md` records title, artist, source URL and licence.
- Files are downloaded once into `frontend/audio/` and served by the app (works offline).
- Theme cards show the track name and artist; the play-sample button plays ~15 s from a
  pleasant point (start of the track is fine).
- In the preview the track starts with the intro card at volume 0 and fades in over the
  intro (3 s), plays in time with the timeline (seek = jump in the track), and fades out
  over the last 2 s. If the video is longer than the track, it loops with a 2 s crossfade.
  Volume slider and 1×-only playback stay as today. `music.js`'s synthesizer is removed.

## 2 · Fades: pins on a mini-map (option 3)

In step 4's Video panel, the Fades section becomes:
- **"+ Add fade"** opens fade editing *inside the panel* — the 3D preview stays on screen
  (no swap to the big plan any more).
- A **mini-map** of the plan (the same plan drawing, scaled to the panel width) with the
  route and two pins, **OUT** (dark) and **IN** (accent), placed by default 30% and 50%
  along the route (or around the middle third if fades already exist there).
- Pins are dragged along the route only (snap to nearest route point while dragging);
  IN can't be dragged before OUT and pins can't enter another fade's range — the pin
  stops at the boundary with a short hint rather than showing an error afterwards.
- Two live frames under the map ("Out" / "In") update while dragging (throttled), and the
  big preview shows the frame of the pin being dragged.
- A summary line: "Skips N m · saves M s · 0.8 s fade to black".
- **Preview the cut** plays from 2 s before OUT to 2 s after IN, with the fade.
- **Done** saves the fade; **Cancel**/Esc discards. Existing fades in the list are
  editable: clicking a row reopens the mini-map with its pins.
- Keyboard: when a pin has focus, ←/→ move it along the route (0.5 m steps, Shift = 5 m).

## 3 · Photoreal real-time preview

Rendering stack (CDN, pinned, loaded as ES modules through an import map; versions at
least two weeks old):
- `three@0.186.1` (replaces r128), addons from `three@0.186.1/examples/jsm/`.
- Post-processing: `EffectComposer` → `RenderPass` → `GTAOPass` (ambient occlusion) →
  `UnrealBloomPass` (subtle, for light panels) → `OutputPass` (tone mapping + sRGB) →
  `SMAAPass`.
- Renderer: `ACESFilmicToneMapping` (or `AgXToneMapping` if it reads better on the test
  plan — builder's call, one of the two), physically correct lighting, soft shadows
  (`PCFSoftShadowMap` or `VSMShadowMap`) from a sun that enters through the windows.
- Image-based lighting: a CC0 daylight HDRI from Poly Haven (1k or 2k `.hdr`), through
  `PMREMGenerator`, as environment (lighting + reflections) and visible through windows.
- Materials: physically based (`MeshStandardMaterial`/`MeshPhysicalMaterial`) with CC0
  1K textures (albedo, normal, roughness) from ambientCG or Poly Haven for: wood floor,
  carpet tiles, polished concrete, painted plaster walls, oak veneer, fabric, brushed
  metal, black plastic, laminate. Glass becomes physical glass (transmission/IOR or a
  convincing reflective approximation). Texture coordinates are generated per face from
  world position (box/triplanar mapping) at real-world scale, since meshes have no UVs.
- Material choice: the backend adds a `finish` name to each 3D mesh (from the existing
  `qbiq_scene3d` palette: fabric, oak, laminate, metal, plastic, glass, plaster, …). Floors
  get a finish per room type (carpet in offices/meeting rooms, wood or concrete in
  kitchens/lounges/corridors) using the plan's room polygons. This is a 3D-only field;
  the XML and route don't change.
- Ceiling light panels become emissive (bloom) and light the room (a small number of
  `RectAreaLight`s or point lights per room — builder's choice within the performance
  budget below).
- Quality modes: **Draft** while dragging/scrubbing or on a slow GPU (no AO/bloom, lower
  shadow resolution), **High** when idle/playing. Auto-select by measured frame time.
- Snapshot strip (step 2) and the step-3 preview use the same renderer.
- Performance budget: the step-4 preview holds ≥30 fps at 1280×720 in High on a mid-range
  laptop GPU, and stays usable on integrated graphics in Draft.

## 4 · Render video (best-quality real-time renderer, offline)

- Step 4 gets **"Render video"** (secondary button next to the dock's Export Enscape XML).
- Frames are rendered one by one with the same scene and materials as the preview, but
  with every setting at its maximum regardless of frame rate: supersampling (render at
  2× and downscale, or accumulate jittered sub-frames), highest shadow-map resolution and
  soft-shadow quality, full-resolution AO at its highest quality, bloom, SMAA.
- Output: MP4 (H.264 video + AAC audio) via WebCodecs and `mediabunny@1.61.3`, containing
  intro card → walk with fades → outro card, and the chosen music with the same
  fade-in/out. 30 fps; resolution 1080p (default) or 720p.
- Before starting: a dialog with resolution and an estimated time from rendering a few
  test frames. Target: a 1-minute video in a few minutes on Kevin's machine.
- While rendering: progress (frame n of N, elapsed, remaining), the current frame shown
  large, Cancel. On finish the file downloads as `walkthrough_<level>.mp4`.
- If WebCodecs H.264/AAC encoding isn't available, say so and offer WebM (VP9 + Opus).

## Constraints (carried over)

- Single-page frontend; new logic in focused `frontend/js/*.js` files with `node --test`
  unit tests where logic is pure; Flask backend; pytest + flake8 as before.
- Asset URLs relative (`frontend/...`), page works under `/r/<slug>` (base tag).
- qbiq tokens and the step-4 layout from the mockups.
- Browser tests run against a dedicated server (not the one Kevin is using).
- Total new bundled assets ≲ 40 MB (4 tracks ≈ 20 MB, HDRI + textures ≈ 15 MB).

## Decisions made while writing (Claude's calls — check these)

- Kevin chose the best-quality real-time renderer for the video over path tracing (hours
  per video) — "just a really good preview". No path-tracer dependency.
- The rendered MP4 includes cards, fades and music — a camera-only render would not be
  the finished video Kevin is aiming at. (This reverses the earlier non-goal "no MP4".)
- three.js jumps from r128 to r186: modern three has the post-processing (GTAO, output
  pass), physically based lighting and colour management the realism needs.
- Mixkit tracks bundled locally, with a credits file, accepting the licence grey area for
  the proof of concept.
- Target browsers: Chrome/Edge (Chromium) on Windows — Kevin's platform. MP4 (H.264 +
  AAC) there; other browsers get the WebM fallback (VP9 + Opus) without separate tuning.
- Assets (tracks, HDRI, textures) are committed to the repo under `frontend/audio/` and
  `frontend/assets/` — the origin repo is private, so this doesn't publish them; credits
  files record source and licence for each.
- Lighting is one fixed daylight setup (sun + HDRI). Per-waypoint time of day is ignored
  by the 3D, as today; a time-of-day sun is a later step.

## Left to the builder

- Exact HDRI and texture sets (CC0), texture scales, and the finish→texture table.
- Light setup per room within the performance budget.
- Quality auto-switch thresholds.
- Supersampling method and the exact "maximum" settings for the video render.
