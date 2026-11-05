# Acceptance run — Revit add-in (version 2: one screen, 3D from the active view, area frame)

Run on the project you choose, in Revit 2024. Tick each item and write what you see. Anything that fails goes in "Problems".
Nothing here has been run in Revit yet: it was built and tested without Revit (engine, window page in a browser, add-in
compiled against the Revit 2024 API).

Project: ______________________  Enscape version: ______  Date: ________

## Before you start
- [ ] Close Revit, run `install.ps1` from `addin\out` (build it first with `build-all.bat`), start Revit 2024.
- [ ] Open the project, open **the 3D view you normally use with Enscape** (hide anything you do not want, e.g. furniture
      categories, or set a section box) and a floor plan of the level you want. Stay in the 3D view when you press the button.

## 1. The tab and the extraction
- [ ] The **Path Tool** tab shows **Open Path Tool**, and a separate **Diagnostics** panel with **Dump level JSON**.
- [ ] **Dump level JSON** shows counts that look right (walls, doors, rooms, meshes, vertices): ______ ; room names are English.

## 2. The area frame (first thing the window shows)
- [ ] The window opens on the plan of the level with a **frame**; the area outside it is dimmed. The text says to drag the frame around the area to use.
- [ ] The frame starts around the building, not stretched by a far-away site outline: ______
- [ ] Drag a corner, a side, the inside, or drag out a new frame. **Use this area** loads the model.
- [ ] Surroundings you cut out (neighbouring buildings, site) are **not** in the 3D or the plan.
- [ ] **Use everything** also works. **Change area** (header) shows the frame again; your points are kept and marked amber if outside.

## 3. The one-screen editor
- [ ] **3D view** on the left, **2D plan** next to it, **right panel** with Tour & route, Camera style, Save, and the **video bar** across the bottom. No steps or "next" buttons.
- [ ] The **3D shows what Enscape shows**: hide a category in the 3D view in Revit, press **Refresh model**, it disappears here.
- [ ] The whole building shows in 3D (not only one level); **Roofs** and **Ceilings** tick boxes show/hide them.
- [ ] Colours/transparency look like the Revit materials; the model is not heavy to orbit: ______
- [ ] The **level** list in the header changes the plan; the 3D stays (it is not re-read).

## 4. Path, timeline, "you are here"
- [ ] **Suggest a tour** / Auto-path draws a route that does not cross walls: ______
- [ ] Dragging a point in the 3D view moves it along the floor; clicking a point in the plan, 3D, list or video bar selects it everywhere.
- [ ] The **video bar** has no intro, outro or music; it shows the walk with camera points, look-at and pauses.
- [ ] **Play** moves a red dot with a view cone along the **plan** at all times (also when you scrub the bar or pause).
- [ ] The small camera view in the corner of the 3D plays the walk.

## 5. Refresh and broken rooms
- [ ] Move or delete a wall in Revit, press **Refresh model**. Points no longer on walkable floor are marked amber, none are lost.
- [ ] On a model with broken rooms: a banner appears; **Load JSON instead** with the qbiq design JSON loads the level.

## 6. Save and Enscape
- [ ] **Save path (XML)** opens a save dialog (`enscape_walkpath.xml`) and writes the file.
- [ ] Load the file in Enscape's video editor by hand. Enscape plays the same route the window showed, **on the right level height**: ______
- [ ] Compare with one of the team's hand-made XMLs: same structure and position scale.

## 7. Housekeeping
- [ ] Close Revit. In Task Manager no `qbiq-engine.exe` is left running.
- [ ] The Revit project title shows no unsaved-changes mark after the whole session (the add-in is read-only).

## Problems
(write anything that failed; if the active view is not a 3D view and there is no `{3D}` view, the window should tell you to open one)

