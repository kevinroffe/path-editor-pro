# Acceptance run — Revit add-in

Run on the project you choose, in Revit 2024. Tick each item and write what you see. Anything that fails goes in "Problems".
Nothing here has been run in Revit yet: it was built and tested without Revit (engine, window page in a browser, add-in
compiled against the Revit 2024 API).

Project: ______________________  Enscape version: ______  Date: ________

## Before you start
- [ ] Close Revit, run `install.ps1` from `addin\out` (build it first with `build-all.bat`), start Revit 2024.
- [ ] Open the project and a floor plan view of the level you want.

## 1. The tab and the extraction
- [ ] The **Path Tool** tab appears in the ribbon with **Open Path Tool** and **Dump level JSON**.
- [ ] **Dump level JSON** shows counts that look right for the level (walls, doors, rooms, meshes, vertices): ______
- [ ] The dialog's JSON file opens; room names are English and match Revit.

## 2. The window
- [ ] **Open Path Tool** opens the window with the model in 3D (orbit with the mouse). Walls, doors, furniture are where Revit shows them: ______
- [ ] The header says "Synced with Revit ✓". If rooms are broken, a banner offers **Load JSON instead**.
- [ ] Auto-path / **Suggest a tour** draws a route. It does not cross walls: ______
- [ ] Dragging a point in the 3D view moves it along the floor; the timeline lanes (Camera, Look-at, Pauses) follow.
- [ ] The small camera view in the corner plays the walk; Play/Pause and the timeline scrub work.

## 3. Refresh
- [ ] Move or delete a wall in Revit, press **Refresh model**. Points no longer on walkable floor are marked amber, none are lost.

## 4. Broken rooms
- [ ] On a model with broken rooms: the banner appears; **Load JSON instead** with the qbiq design JSON loads the level.

## 5. Save and Enscape
- [ ] **Save path (XML)** opens a save dialog (`enscape_walkpath.xml`) and writes the file.
- [ ] Load the file in Enscape's video editor by hand. Enscape plays the same route the window showed (position and direction): ______
- [ ] Compare with one of the team's hand-made XMLs: same structure and position scale.

## 6. Housekeeping
- [ ] Close Revit. In Task Manager no `qbiq-engine.exe` is left running.
- [ ] The Revit project title shows no unsaved-changes mark after the whole session (the add-in is read-only).

## Problems
(write anything that failed; if the core and shell are in a linked Revit file and Auto-path crosses walls, linked models are the first follow-up)

