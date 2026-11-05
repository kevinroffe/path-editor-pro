# Revit Add-in — Design

Date: 2026-11-05 · Branch: `feat/revit-addin-design` · Status: draft for Kevin's approval; "Kevin" decisions are his words, calls marked **(Claude's call)** are not

## Why

qbiq's visualisation team builds walkthrough camera paths in Enscape's own video editor inside Revit. Kevin: the
editor "is not intuitive and with no control". Today the team can do better in this repo's web tool (Auto-path, a
corridor-aware route, a camera house style learned from 312 hand-made paths, an editable path, a video timeline,
Enscape XML export), but only after exporting the model out of Revit and loading it into a separate app.

Kevin's ask: make the path tool **part of the Revit process** so the user sees the Revit model in the app, and gets
Auto-path, path editing and a video timeline in one place, with the finished path handed to Enscape.

## What gets built

A Revit **2024** add-in. It puts a **Path Tool** tab in the Revit ribbon. The tab's button opens a large working
window above Revit with the current Revit model already loaded. This is the layout Kevin chose, "option B" in the
mockups (`.superpowers/brainstorm/…/panel-layouts-detailed-v2.html`, not committed):

- **Header:** qbiq logo, "Path Editor", steps (Model, Rooms, Path, Video), a "synced with Revit" chip, and a
  **Save path (XML)** button (the mockup labels it "Send to Enscape"; version one only saves the file).
- **Left tools:** Auto-path; add point; move points, look-at, smooth path, pauses; level and ceiling toggles.
- **Centre: a 3D view of the actual Revit model with the path on it** (Kevin added this explicitly and, when
  asked, answered "the Revit model"). It is the real Revit geometry (true wall, floor, ceiling, door, window and
  furniture shapes taken from Revit, with their colours or materials where available), **not** a simplified
  stand-in built from outlines. The user can orbit, zoom and pan it, with the route drawn as a line through the model, numbered
  points, and camera cones showing where each point looks. Selecting a point in 3D, the plan, the list or the
  timeline selects it everywhere; dragging a point in 3D moves it along the floor.
- **Camera-view window** (**Claude's call**, my reading of "a window to see the path on the 3D model"): a second,
  smaller view showing what the camera sees at the play head, so Play walks the path in first person through the
  same 3D model. It is a preview in the app's own 3D, not Enscape's render.
- **Right inspector:** the selected point (eye height, look-at, pause, speed, easing).
- **Bottom timeline:** a full video timeline with tracks for video thumbnails, camera path keyframes, look-at,
  pauses and music, play head, snap and zoom, Preview and Export.

The window is a web page: **the existing `frontend/` app, adapted**, not a rebuild. Everything it does today
(Auto-path, Suggested Tour, route smoothing, camera house style, 3D preview, music with fades, video settings,
Enscape XML / JSON export) stays and keeps its behaviour.

### Where the model comes from

1. **Normal case:** the add-in reads, for each level, the walls, doors, windows, columns, floors, **Rooms** and
   furniture from the open Revit model and gives them to the engine in the existing `LevelGeometry` shape
   (`backend/revit_extractor.py`: polylines for walls/spaces/doors/columns/windows/furniture, `units_to_metres`,
   optional 3D `meshes`). Revit Rooms supply the room stops that Auto-path and Suggested Tour need.
2. **Rooms missing or broken** (Kevin: "sometimes the rooms arrive broken"): the user can load a **JSON** instead.
   **(Claude's call)** this is the qbiq design JSON the tool already imports (`/api/upload-qbiq-design`); and the
   add-in detects obviously bad rooms (unplaced, unenclosed, zero area, duplicate) and offers the JSON choice
   rather than letting Auto-path quietly misbehave.

### Getting the path into Enscape

Kevin: sending to Enscape automatically "will be perfect". Research (web search plus the team's `path learn` XMLs)
found **no documented Enscape API for pushing a path into its video editor**; the working route is the XML file
Enscape saves and loads (`VideoPath` → `Keyframes` → `Keyframe` with `Position` and `LookAt`). Kevin's final
decision for version one: the user **uploads the XML into Enscape by hand**, so the tool only needs a **Save /
Download XML button** that writes the file (existing `export_layer.py`). It does not open or drive Enscape at all.
Pushing a path into Enscape automatically stays a wish for later, if Enscape ever offers a way.

## Goals

- A designer goes from an open Revit model to a path in Enscape without leaving Revit and without exporting or
  uploading files.
- Auto-path, path editing and the video timeline work on the Revit model with the quality of today's tool on the
  same plan.
- The same engine serves both the web tool and the add-in, so an improvement to routing or camera style lands in both.
- The user can see the path on the 3D model, orbit around it, and preview the walk from the camera's point of view.
- The user's model never leaves their computer.

## Non-goals (first release)

- Any automatic hand-off to Enscape, including opening its import (no known API; the user imports by hand).
- Showing Revit's own live 3D view inside the window; the window shows a copy of the model, refreshed on demand.
- Revit versions other than 2024; macOS.
- Rendering the video (Enscape does that).
- Editing the Revit model.

## Anti-goals (a failure even if it technically works)

- Requiring DXF/IFC export, drag-and-drop uploads or a browser tab: that is today's pain.
- Anything that modifies, saves or locks the Revit model, or slows Revit down while idle.
- A path in Enscape that is in the wrong place or scale because coordinates or units were converted differently from Revit.
- Auto-path that silently produces rubbish on a model with broken rooms.

## Decided, in Kevin's words

- "The tool itself is not intuitive and with no control" → make it an add-in inside Revit.
- Revit version: **2024**.
- Layout: **option B**, the full working window.
- "Use all the technology of the current software" → reuse the engine, do not reimplement.
- Rooms come from Revit; an **option to load JSON** when they are broken.
- Getting the path into Enscape: the user uploads the XML by hand, so version one has only a **save / download
  XML button**. No automatic hand-off, no opening Enscape's import.
- The acceptance test project: Kevin will choose and run it himself.
- All software text is **English**, and the rooms the tool receives are named in English.
- "Everything is good for the first experiment" → this is an **experiment**, not a finished product.

## Calls the builder should respect (Claude's calls, change if wrong)

- **Add-in language and host:** C# on .NET Framework 4.8 (what Revit 2024 loads); the window is a WebView2 control
  hosting the adapted `frontend/`. WebView2 must be on the team's machines (it ships with current Windows/Edge).
- **Engine packaging:** the existing Flask engine is packaged as a local program (the repo already has
  `qbiq.spec` / `build.bat` for PyInstaller) and installed with the add-in. The add-in starts it when the window
  opens, on `127.0.0.1` with a random port and a per-session key, and stops it when Revit closes.
- **Integration contract:** a new endpoint, alongside `/api/upload-qbiq-design`, accepting the Revit extraction as
  `LevelGeometry` JSON per level. The add-in must not re-implement routing.
- **Coordinates and units:** keep the model's own origin and scale so the exported XML lands in Enscape's space
  exactly as the existing DXF path already does (`dxf_extractor.py`: "origin is NEVER shifted"; `svg_generator.py`:
  `svg_y = -model_y`). Revit's internal unit is feet; convert via `units_to_metres`.
- **Revit threading:** read the model on Revit's main thread (an `ExternalEvent`), then hand plain data to the
  window; the window must stay responsive while it reads a big model.
- **Refresh:** a **Refresh model** button re-reads Revit and keeps the user's points where still valid.
- **Distribution:** the team installs it themselves (installer or folder copy plus `.addin` manifest); no store listing.

## Settled after the builder check (Claude's calls, change if wrong)

- **Enscape hand-off is just a saved file.** The one real risk left is that the saved XML imports cleanly in the
  team's Enscape. Check the first output against the team's own hand-made XMLs and one real import. The Enscape
  version on the team's machines was not given; the builder should find it out when testing.
- **Coordinate frame:** extract in Revit's **internal origin**, as the DXF export the tool uses today does, and
  verify against a known-good pair (a project with a hand-made Enscape path, see "How we will know it works").
  Project Base Point, survey points and rotated True North are not corrected in version one.
- **Refresh keeps points** by position within the same level; a point still inside walkable space stays, one that
  no longer is stays on screen **flagged**, never silently dropped or moved.
- **Extraction scope for v1:** footprints for routing **plus real 3D meshes from Revit for the 3D view** (the
  existing `meshes` field of `LevelGeometry` already carries `{type, verts, faces}`, which is the shape to fill).
  The active phase and primary design option only; stairs and multi-storey connections, design options, worksets
  are out. Because real meshes can be large, the builder should reduce them (merge by material, drop tiny
  details, level of detail) so the 3D view stays smooth.
- **Linked models** (a Revit file that references another Revit file, such as a separate core or shell model) are
  **out of version one** (Kevin agreed). Kevin's test project will show whether this hurts; if the team's projects
  usually keep the core and shell in a linked file, revisit this first.
- **JSON fallback replaces the whole level:** when JSON is loaded for a level, that JSON (walls, rooms, 3D) is the
  source for that level, so nothing needs registering against Revit geometry.
- **Frontend work is partly new, not only adaptation:** `video-timeline.js` is about 100 lines today, so the
  multi-track timeline (thumbnails, look-at, pauses, music) and the option B window shell are new UI on top of the
  existing 3D view, routing and music. One codebase with a mode flag for "inside Revit" versus "browser".
- **Offline and local:** the frontend must load every asset (three.js, fonts, audio) from the local package, with
  no network at runtime and no telemetry; the engine binds to `127.0.0.1` only; the add-in kills the engine on
  exit and a new Revit session reaps any orphan.
- **Performance target for v1:** one level extracts in a time that feels like a normal Revit command (aim: under
  30 seconds on a typical office floor), without freezing Revit; refine once real models are measured.
- **Video thumbnails** come from the window's own 3D view rendered at each keyframe, not from Revit.

## Left to the builder

- Installer and update mechanism; where files live; code-signing.
- How the add-in turns Revit geometry into `LevelGeometry` and real 3D meshes (Revit geometry API, triangulation,
  materials, mesh reduction), including how furniture and ceilings are shown and what to do with very heavy models.
- Level-picking UI when the model has many levels.
- How to test the add-in without a Revit licence on every machine (recorded extractions, a fake host).
- Names, icons and exact visuals within the chosen layout.

## How we will know it works

Kevin will pick and run the test project himself. **(Claude's call)** the bar to propose to him: on a real qbiq
project that currently needs the DXF/IFC route, open it in Revit, press the button, get Auto-path, edit a point,
adjust the timeline, save the XML, upload it to Enscape by hand, and Enscape plays the same route the window
showed. And on one model with broken rooms, loading the JSON fixes it. Kevin may replace this with his own bar.

---

## Revision 2 — after Kevin's first look (2026-11-05)

Kevin tried the first build and asked for four changes. Where this section disagrees with the text above, **this section wins**.

### What Kevin asked for (his words, translated)

1. See the **plan in full and the 3D in full**; textures may be light so the model stays light.
2. The 3D model always comes from **the Revit 3D view that Enscape uses**. Kevin chose: *the active 3D view* (answer to "what exactly").
3. **No steps.** One screen: a 3D window and one 2D canvas **side by side**, a **bar at the bottom** with the video timeline and the camera points (like a video editor), and on the **right** the editing panel with everything else.
4. **Before starting, ask the user to crop** the plan area so the surroundings in the Revit file do not come in. Kevin chose: *a frame inside the window* (answer to "how").

### The screen (one screen, no wizard)

```
header:  qbiq · Path Editor · level [Level 1 ▾] · Change area · Refresh model · Load JSON · Save path (XML)
┌──────────────────────────┬──────────────────────────┬──────────────────┐
│  3D view (orbit)         │  2D plan canvas          │  Right panel     │
│  route, points, cones,   │  click to add points,    │  (sections, all  │
│  camera-view inset       │  drag them, auto-path    │  open at once):  │
│                          │                          │  Tour & route    │
│                          │                          │  Selected point  │
│                          │                          │  Camera style    │
│                          │                          │  Video & music   │
│                          │                          │  Export          │
├──────────────────────────┴──────────────────────────┴──────────────────┤
│ ▶ 0:18 / 0:42   Video │ Camera points │ Look-at │ Pauses │ Music      │
└────────────────────────────────────────────────────────────────────────┘
```
- The existing step panels become **sections of the right panel**, all visible, scrolling; the step dock and "next step" buttons are not shown in the Revit window. Browser mode keeps its wizard.
- The bottom bar is **full width** with the transport controls and the lanes; the camera points (route waypoints) are markers on it that select the point and seek the video; keyframe markers seek.
- 3D and plan are always both visible and share one selection (already built).

### 3D model: the active Revit 3D view (replaces "per-level categories")

- The add-in reads the model through **the active 3D view** (`FilteredElementCollector(doc, view3D.Id)` and `Options.View = view3D`): hidden categories, view filters, visibility/graphics, phase filter, design options and the section box are honoured, as in Enscape.
- If the active view is not a 3D view: use the project's default `{3D}` view; if there is none, ask the user to open a 3D view. **(Claude's call)**
- **The whole building**, not one level, inside the crop area. Roofs and ceilings are included (the 3D view has toggles to hide them while editing). **(Claude's call)**
- Materials: colour and transparency from the Revit material; textures stay the tool's existing light procedural ones. Shell types (walls, floors, ceilings, roofs) are always kept; over the vertex budget detail goes first (as built).
- The **2D plan, rooms, doors and routing still belong to one level**: the header's level selector (default: the active view's level if it is a plan, else the lowest). Changing the level re-reads the 2D part only.
- Revision-1 mesh logic by level height band is no longer used for meshes (it stays for the 2D plan).

### Crop: a frame inside the window, before loading

1. The window opens and asks the add-in for a **quick overview**: the chosen level's 2D footprints only (walls, doors, rooms, columns — no 3D), uncropped.
2. The page shows that plan with a **draggable, resizable rectangle** (default: the area holding most of the walls, so a distant site outline does not stretch it) and the text "Drag the frame around the area to use. Anything outside is ignored." Buttons: **Use this area**, **Use everything**.
3. On confirm, the page sends the rectangle (model feet) and the add-in does the **full read inside it**: 2D elements and 3D meshes whose bounding box intersects the rectangle (all heights). Partly inside = kept whole. Then the usual load.
4. **Change area** in the header repeats from step 2; the points already drawn are kept and flagged if outside the new area. The rectangle is remembered for **Refresh model**.

### Out of scope (unchanged unless said)

Linked models, stairs/multi-storey path connections, Revit versions other than 2024, automatic Enscape hand-off, and (still not built) video thumbnails, snap and zoom on the timeline — **the bottom bar's video lane is a plain strip this round; thumbnails are the next follow-up**. **(Claude's call, to keep this round focused.)**

### How we will know it works (additions)

Open a 3D view and a plan, press the button: the plan overview appears, drag a frame, **Use this area**; the screen shows 3D and plan side by side with the video bar below and the panel on the right, and **the 3D shows what Enscape shows** (hide a category in the view → it disappears from the tool after Refresh). Change the level: the plan changes, the 3D stays.

---

## Revision 3 — no 3D model in the tool; the 2D plan shows everything; a Revit-camera preview (spike)

Kevin: *"I don't need the 3D model, but I want everything the path shows in the 3D (where it looks, the points, etc.) on the 2D. And the video preview must be accurate like Enscape or the Revit 3D model — how?"* He approved: **do both** (the 2D plan, and a spike of playing the path in Revit's own 3D view). Where this section disagrees with earlier text, **this section wins**.

### A. The 3D window goes; the plan carries everything
- The Revit window has **no 3D view and reads no 3D geometry** (faster reads, much smaller uploads). Layout: **plan (large) | right panel**, the video bar under the plan. The "3D from the active view" read and its roofs/ceilings toggles are retired for the window (the code stays for the diagnostics button only).
- On the plan, besides the route and numbered points the page already draws: a **view cone at every point** (where the camera looks, sized by the field of view, the selected point highlighted), **pause marks** where the camera stands still, and the live **"you are here"** dot and cone that follows the play head. Dragging points and turning the look direction on the plan keep working.
- The point inspector sits on the plan.

### B. Accuracy of the video preview (what is and is not possible)
- **Enscape's own interpolation between keyframes is not documented**; our preview emulates it (learned from 312 hand-made paths), so only Enscape itself plays *exactly* like Enscape. The XML carries exact position and look-at per keyframe.
- **Spike (experimental):** a header button **Revit camera** drives the **active Revit 3D view's camera** along the path, in step with the play head, so the user sees the real model through the path. Revit's `View3D.SetOrientation` is a temporary orientation (documented as not saved in the document); it fails if the view is locked; the field of view cannot be set directly (it follows the view's crop region). The add-in restores the view's original orientation when the preview is turned off. **Claude's calls:** the view driven is the active view if it is a 3D view, otherwise the user is told to open one; the pose is eye height 1.57 m above the level; pose updates are throttled to about 15 a second; any error turns the preview off with a message. Whether this works in the user's Revit is exactly what the spike is for; it is not claimed to work until he runs it.
- The only exact preview is Enscape: Save path (XML) stays the hand-off.

### Out of scope (unchanged)
Thumbnails, snap and zoom on the timeline; linked models; automatic Enscape hand-off.
