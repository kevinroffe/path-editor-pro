# Path Editor — Guided redesign, title cards, music and fades

**Date:** 2026-10-20 · **Branch:** `guided-redesign` (from `qbiq-design-json`)
**Mockups:** https://claude.ai/artifact/7sY3VaTEe239VSQqd9qt16 — boards
"B · Guided — step 2, Rooms & route", "B · Guided — step 4, Preview & export",
and "B · Step bar — 5 options" (option 5, the floating dock, was picked).

## Intent

The Path Editor makes Enscape walkthrough camera paths from a qbiq design JSON.
Today everything lives in one dense screen: sidebar, canvas toolbar, a 3D panel
that slides in, and export buttons in the header. Kevin chose to rebuild the
whole app around a **guided, four-step flow** (direction B), so a first-time user
is walked from plan to export, and to add a **proof-of-concept video finish**
inside the app: an intro and outro title card with a logo and text, a music
theme for commercial real estate, and fades that skip part of the walk.

What matters most is unchanged: **the path and the Enscape XML.** The redesign
is a new face and flow over the same engine. The title cards, music and fades
are a demo of where the product could go and exist **only in the in-app
preview** — they never change the exported XML.

## Goals

1. Replace the current single-screen layout with four steps, navigated by a
   floating dock:
   1. **Load plan**
   2. **Rooms & route**
   3. **Camera style**
   4. **Preview & export**
2. Every capability the app has today stays reachable from one of the steps
   (inventory below), with the same behaviour.
3. Step 4 adds a **Video** panel: Brand (logo + text cards), Music (four themes),
   Fades (out point → in point on the path). The 3D preview plays the whole
   thing: intro card → walk (with fades) → outro card, with music.
4. Visual language follows the mockups and qbiq's real tokens (below).

## Non-goals

- No rendering of a finished video file (MP4) with the logo and music burned in.
- No change to the Enscape XML format, the camera engine (`camera_style.py`),
  Auto Tour, Smart Path, or the 3D scene builder.
- No licensed or downloaded music; the themes are generated in the browser.
- DXF, IFC and JSON+SVG pair loading stay hidden, as today (code kept).

## Anti-goals (a failure even if it "works")

- Any existing path feature lost or behaving differently — Auto Tour click
  order, stops/dwell, Stand & look, cuts, Look around at start, Smart Path,
  manual waypoint/freehand drawing, warnings, JSON save/reload, XML export.
- The XML for the same path differs from what `qbiq-design-json` exports.
- The preview's title cards, music or fades leaking into the XML or the saved
  path JSON's waypoints/cuts.

## Constraints

- Same stack: Flask backend, single-file frontend `frontend/index.html`
  (vanilla JS, D3 v7, Three.js r128). No new frontend libraries or build step.
- Backend tests: `pytest` from `backend/` with the project venv; flake8
  `--extend-ignore=W292,W391,E302,E501`. The backend should need no changes
  beyond what the JSON save/load of the new video settings needs (if any).
- qbiq tokens: canvas `#f6f7f9`, panel `#ffffff`, borders `#e6e8ec` / `#d7dae0`,
  text `#1f2733`, muted text `#5f6673`, accent `#2f6bff` (soft `#eaf1ff`,
  strong `#1f52d6`), dark `#1e2430`, ok `#31a354` / `#e8f5ec`, warn `#d99000` /
  `#fbf1e0`, danger `#d64545`; Inter; radius 8px (6px tight); shadows
  `0 1px 2px rgba(16,24,40,.06)` and `0 8px 24px rgba(16,24,40,.08)`.
- The qbiq wordmark (`qbiq-logo.svg`, dark `#212121`, 88×27) sits top-left in
  the header. A copy is at
  `C:\Users\kevin\AppData\Local\Temp\claude\c--Users-kevin-classify\900a02b1-8173-4329-b4b7-91e9fbbcf2f6\scratchpad\pe-design\qbiq-logo.svg`;
  it ships as a frontend static asset.
- Header holds only the brand ("qbiq | Path Editor") and the plan name
  (e.g. "Office L-0 · 17 rooms"). No step bar in the header.

## The floating dock (all steps)

A dark rounded pill (`#1e2430`, white text, large soft shadow) floating
bottom-centre over the main work area on every step:
`[‹ back]  STEP n OF 4 / <step name>  [progress dots]  [<next step> →]`.

- Dots: done = green `#31a354`, current = accent and wider (22px), todo =
  translucent white.
- The primary button names the next step ("Camera style →"). On step 4 it is
  **Export Enscape XML**.
- Back is hidden or disabled on step 1. Next is disabled until the step's
  precondition holds: step 1 → a plan is loaded; step 2 → the route has at
  least two waypoints. Steps 3 and 4 are always reachable once there is a route.
- Moving between steps never loses state.

## Step 1 — Load plan

Drop zone / file picker for the design JSON (the current loader, JSON-only).
After loading: the plan, and a summary (floor name, room count). The empty
state explains what file to bring. Loading errors show as today (toast).

## Step 2 — Rooms & route

As in the "step 2" mockup:

- **Left panel (≈380px):** "Step 2 of 4" eyebrow, heading "Which rooms should
  the tour show?", one-line help; quick-add pills (All offices / Meeting rooms /
  Amenities — add those room types, in plan order, to the end of the pick list);
  the ordered pick list (drag handle, number, room name, area/seat meta, a
  **Look** or **Stand & look** tag, remove ×); tour stats (rooms, walk length,
  video length, pace); warnings from the tour (e.g. a door that only opens into
  another room) in the warn style at the bottom.
- **Plan (main):** click rooms to add them in order, click again to remove;
  numbered pins sit on picked rooms; route drawn as today; a "Start · Entrance"
  marker. Room labels on/off stays available.
- **"What the camera will see" strip** under the plan: one thumbnail per picked
  room (up to 4 visible, scrolls if more), rendered from the real 3D scene at
  that room's stop, captioned "n · Room" and its time in the video.
- The tour regenerates when the pick list changes (debounced), replacing the
  current "Generate tour" button.
- **Manual route editing stays here**: Smart Path (start room → end room),
  drawing waypoints / freehand, dragging waypoints, and the waypoint list's
  per-stop controls (dwell seconds, Stand & look) and **Cut** toggles between
  waypoints. These live behind an "Edit route by hand" control in the left
  panel so the default view stays the room-picking flow.
- Reordering the pick list reorders the tour (same as clicking in that order).

## Step 3 — Camera style

The existing camera settings, given room and plain labels:
video length (today `s-dur`, 5–300 s, with the suggested length shown),
smoothness (`s-smo`), field of view (`s-fov`), U-turn radius (`s-utr`),
look around at start (`c-startpan`). The plan with the route stays visible so
changes can be judged; a small 3D preview of the route plays on demand.
Warnings returned by `/api/process-route` show here as today.

## Step 4 — Preview & export

As in the "step 4" mockup:

- **3D preview (main, large):** the existing Three.js walkthrough (ceiling,
  furniture, `syncCeiling`), with overlays: "Preview · m:ss / m:ss" and the
  current music theme name.
- **Video timeline** under the preview: play/pause, time, and two lanes —
  *Video*: Intro | walk | Fade | walk | … | Outro blocks to scale;
  *Music*: a waveform-style bar that fades in and out. Clicking/dragging
  scrubs. Playback speed control (today `p3d-speed-inp`) stays. A note:
  "Logo, music and fades are preview only, never in the Enscape XML".
- **Video panel (right, ≈392px):**
  - **Brand** — logo upload (PNG or SVG, shown with file name and Replace);
    card background colour from swatches (Charcoal `#1e2430`, qbiq blue
    `#2f6bff`, Teal `#5b8a8c`, Sand `#c9b79c`); text fields **Property name**,
    **Address or tagline**, **Outro line**; a live mini preview of the intro
    card. Intro card = logo + property name + address. Outro card = logo +
    property name + outro line. Each card shows for **3 s**.
  - **Music** — four theme cards in a 2×2 grid, each with a play-sample button;
    one is selected (default Premium lobby); volume (default 70%).
  - **Fades** — list of fades ("10 → 16 · Corridor → Kitchen · skips 14 m ·
    0.8 s fade to black", remove ×) and **+ Add fade**: then click the fade-out
    point and then the fade-in point on the route in a plan view (a compact
    plan in this step, or a switch to the plan — builder's choice). The in
    point must be later along the path than the out point.
- **Export:** the dock's primary button exports the Enscape XML exactly as
  today. Saving the raw path JSON (today `btn-json`) stays available here as a
  secondary action.

### How the preview plays

1. Intro card 3 s (music fades in).
2. The walk, using the same frames as today. At each fade: fade to black over
   0.4 s at the out point, jump to the in point, fade up over 0.4 s (0.8 s
   total). The walk time between out and in is skipped. Existing **cuts** keep
   today's preview behaviour (they are path features and are also in the XML).
3. Outro card 3 s (music fades out over the last 2 s).

Preview length = 3 + (walk length − skipped time + 0.8 s per fade) + 3.

### Music themes (generated with the Web Audio API)

Short loops built from oscillators, filters and envelopes — no audio files:

| Theme | Character |
|---|---|
| Premium lobby | slow, warm piano-like tones over soft pads; ~70 bpm |
| Modern workspace | light, steady electronic pulse; ~100 bpm |
| Bright leasing | upbeat, major key, optimistic; ~118 bpm |
| Cinematic reveal | slow swell that builds towards the end of the video |

They must loop without clicks, follow play/pause/scrub of the preview, and
honour the volume. Audio starts only after a user gesture (browser rule).

## Persistence

- The last-used **logo** (as a data URL), card colour and music theme are
  remembered in `localStorage` so they survive a reload (wrapped in try/catch;
  the app works without them).
- Brand text, music theme, volume and fades are saved in the path JSON's
  `meta.video` when the path is saved, and restored on load. Fades are stored
  by route distance (metres from the start), not by frame time, so they survive
  changes to the video length. Waypoints and `meta.cuts` are untouched by this.

## Today's capabilities → where they live

| Today | New home |
|---|---|
| JSON loader, drop overlay, empty state, level tag | Step 1; plan name in header |
| Auto Tour room picking + Generate tour + warnings | Step 2 (auto-regenerates) |
| Smart Path, waypoint / freehand modes, waypoint list, dwell, Stand & look, Cut | Step 2, "Edit route by hand" |
| Labels toggle | Step 2 plan |
| Duration, smoothness, FOV, U-turn radius, Look around at start | Step 3 |
| 3D preview: load, play, time, speed, resize | Step 4 (fixed large layout, no resize handle needed) |
| Export XML (primary), Save path JSON | Step 4 (dock button; secondary action) |

Also kept (not in the table above): the Quick / Standard / Cinematic presets
→ Step 3; per-waypoint time of day and heading, heading drag handles,
undo (Ctrl+Z) and Clear all → Step 2, "Edit route by hand".

## Pick list vs. hand edits (Kevin's decision)

The route is the source of truth; the pick list is how a route is made.

- Changing the pick list rebuilds the tour (debounced). Per-room settings —
  dwell seconds and Stand & look (`stop.pan`) — carry over through a rebuild,
  matched by `stop.room_id`.
- Once the route has been edited by hand (waypoints added, moved or deleted,
  cuts, heading or time of day, Smart Path, freehand, Clear all), the next pick
  list change first asks: "Rebuild the route from your rooms? Your hand edits
  will be lost." Yes rebuilds; No keeps the hand-edited route and reverts the
  pick list change.
- The Look / Stand & look tag in the pick list is a toggle bound to
  `stop.pan`, with the same limit as today (max 2 per video).
- A route that did not come from the pick list (drawn, Smart Path, loaded) is
  "hand-edited" from the start; its pick list is rebuilt from its stops'
  `room_id`s, or empty if it has none.

## Decisions made while writing (Claude's calls — check these)

- **Video length vs. rebuilds:** the length follows the tour's suggested
  length until the user changes it in step 3. After that, rebuilding the tour
  keeps the user's length and shows the new suggestion beside it, with a
  one-click "Use suggested".
- **Resuming a saved path:** step 1 offers "Continue a saved path" (today's
  Import Path: path JSON or Enscape XML) beside the plan loader. It needs a
  plan loaded first, as today. XML has no `meta`, so it loads with default
  video settings and no fades. Loading a path that has stops rebuilds the pick
  list from the stops' `room_id`s in order.
- **Fades when the route changes:** fades are kept by distance. Any fade whose
  out or in point now lies past the end of the route is dropped. When the
  route changes and fades exist, step 4 shows a one-line notice "Route changed —
  check your fades".
- **Logo and card colour** live only in `localStorage` (per machine), not in
  the saved path JSON; brand text, theme, volume and fades travel with the path.

## Left to the builder

- Exact component structure inside `index.html`, and whether to split CSS/JS
  into separate static files (allowed if Flask serves them).
- How thumbnails for "What the camera will see" are rendered (offscreen
  render of the existing scene) and when the 3D scene is first loaded.
- Exact Web Audio patches for each theme, within the characters above.
- Keyboard shortcuts (nice to have: ←/→ for dock back/next when focus is not in
  a field; Space to play/pause in step 4).
- How the compact plan in step 4 is shown for picking fade points.
