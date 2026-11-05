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
