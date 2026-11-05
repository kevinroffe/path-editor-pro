# Acceptance run — Revit add-in (version 4: 2D plan + 3D preview pane beside it, Top view, experimental Revit camera)

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
- [ ] Surroundings you cut out (neighbouring buildings, site) are **not** in the plan or the Top view.
- [ ] **Use everything** also works. **Change area** (header) shows the frame again; your points are kept and marked amber if outside.

## 3. The one-screen editor
- [ ] The **2D plan** is on the left, the **3D preview pane** next to it, the **right panel** (Tour & route, Camera style, Save) on the right, and the **video bar** across the bottom under the plan and preview. No steps, no "next" buttons, no intro/outro/music.
- [ ] The first load after **Use this area** also reads the 3D (a big model takes a while: ______ s). Once a route exists, **Play** (or scrubbing the bar) shows the walk from the camera's point of view in the preview pane, in step with the red dot on the plan.
- [ ] The **3D preview** button in the header hides and shows the pane (hidden = faster 2D-only reads). It shows the Revit meshes with the model's colours, not Enscape's lighting.
- [ ] **Plan | Top view** switch (top of the plan): **Plan** shows the coloured rooms; **Top view** shows the Revit model from straight above, cut at about 2.6 m above the level, with the route drawn on it.
- [ ] Top view follows the **active Revit 3D view** (hide a category, press **Refresh model**, it disappears). The first time it takes a moment; switching back to Plan is instant.
- [ ] The **level** list in the header changes the plan and the Top view of that level.

## 4. Path, timeline, "you are here"
- [ ] **Suggest a tour** / Auto-path draws a route that does not cross walls: ______
- [ ] Every camera point shows a **view cone** (where the camera looks); points with a pause show a ring. Dragging a point moves it; clicking a point in the plan, the list or the video bar selects it everywhere.
- [ ] The **video bar** has no intro, outro or music; it shows the walk with camera points, look-at and pauses.
- [ ] **Play** moves a red dot with a view cone along the plan at all times (also when you scrub the bar or pause).

## 5. Refresh and broken rooms
- [ ] Move or delete a wall in Revit, press **Refresh model**. Points no longer on walkable floor are marked amber, none are lost.
- [ ] On a model with broken rooms: a banner appears; **Load JSON instead** with the qbiq design JSON loads the level.

## 6. Save and Enscape
- [ ] **Save path (XML)** opens a save dialog (`enscape_walkpath.xml`) and writes the file.
- [ ] Load the file in Enscape's video editor by hand. Enscape plays the same route the window showed, **on the right level height**: ______
- [ ] Compare with one of the team's hand-made XMLs: same structure and position scale.

## 7. Revit camera (EXPERIMENTAL — please report exactly what happens)
This moves the active Revit 3D view along the path so you can judge the walk in Revit itself. Changing a view's camera counts as an
edit in Revit (each move is a small transaction named "Path Tool: preview camera"), so use it on a copy or undo afterwards.
- [ ] With the active view a **perspective 3D view**: press **Revit camera** (header), then **Play**. The Revit view moves along the path, looking where the cone points. Speed / smoothness: ______
- [ ] The eye height looks right (about 1.57 m above the level): ______ ; left/right is not mirrored: ______
- [ ] Press **Revit camera** again (or close the window): the Revit view goes back to where it was.
- [ ] Make the active view an **isometric**, **locked** or **non-3D** view and press **Revit camera**: the button switches off and says why.
- [ ] If Revit refuses the move (an error shows next to the button), write the message in "Problems": this is the spike's answer.
- [ ] Scrubbing the video bar while the camera is on moves the Revit view too. The field of view differs from Enscape's (the API has no per-view FOV): ______

## 8. Housekeeping
- [ ] Close Revit. In Task Manager no `qbiq-engine.exe` is left running.
- [ ] Without using **Revit camera**, the project title shows no unsaved-changes mark after the whole session (reading the model is read-only).

## Problems
(write anything that failed; if the active view is not a 3D view and there is no `{3D}` view, the window should tell you to open one)
