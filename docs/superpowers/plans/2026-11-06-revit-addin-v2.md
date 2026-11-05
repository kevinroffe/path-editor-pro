# Revit Add-in v2 Implementation Plan (one-screen editor, 3D from the active view, crop frame)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) or superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Change the Revit window to one screen (3D + plan side by side, video bar below, panel right), read the 3D from the active Revit 3D view, and let the user crop the area before loading.

**Architecture:** Same engine and add-in as `2026-11-05-revit-addin.md` (done, shipped on `feat/revit-addin-design`). The add-in reads in two phases (a quick 2D overview, then the full read inside the user's frame); the page re-parents its existing step panels into one right-hand panel and adds a crop screen.

**Tech Stack:** unchanged (Python/Flask + pytest, vanilla JS + `node --test`, C# net48 + xunit).

**Spec:** `docs/superpowers/specs/2026-11-05-revit-addin-design.md`, section **Revision 2** (it wins over earlier text).

## Global Constraints

Everything in the first plan's Global Constraints still holds (Revit 2024 only; read-only; engine on `127.0.0.1` with the session key; no network; true Revit origin and units; English-only text; browser mode unchanged), plus:
- 3D comes from **the active Revit 3D view** (`FilteredElementCollector(doc, view3D.Id)`, `Options.View`), whole building, inside the crop; if the active view is not 3D use `{3D}`, else tell the user to open a 3D view.
- The 2D plan, rooms and routing belong to **one level** chosen in the header.
- Crop = a rectangle in model feet; elements whose bounding box intersects it are kept whole, at all heights.
- No wizard in the Revit window; browser mode keeps its steps.

## Review Focus

1. A model with **no 3D view** at all, or the active view is a sheet/schedule: a clear message, no crash (Task 20).
2. A crop frame that is **tiny, inverted, outside the model or covers nothing**: normalised, clamped, and "nothing in this area" instead of an empty broken screen (Tasks 19, 23).
3. A distant **site outline stretching the default crop** (Task 19).
4. **Change level / Change area / Refresh** after points exist: points kept and flagged, 3D not re-read for a level change (Tasks 21, 23).
5. A **huge whole-building read** stays inside the vertex budget and the 413 limit (Tasks 20, 21).

---

### Task 19: Crop maths and read requests (Core)

**Files:** Create `addin/Qbiq.PathTool.Core/Crop.cs`, `addin/Qbiq.PathTool.Tests/CropTests.cs`

**Interfaces:**
- `struct CropBox { double XMin, YMin, XMax, YMax; }` with `static CropBox Normalise(double x1, double y1, double x2, double y2)` (any corner order), `bool Intersects(double minX, double minY, double maxX, double maxY)`, `bool IsUsable` (area above 1 ft²).
- `static CropBox Crop.Default(IEnumerable<IEnumerable<double[]>> polylines)`: the 2nd to 98th percentile of all vertex x and y, grown by 5 %, so a few far-away vertices do not stretch it; empty input gives an unusable box.
- `class ReadRequest { string Type; string Level; CropBox? Crop; }` with JSON `{"type":"readModel","level":"Level 1","crop":{"xmin":..}}` and `ReadRequest.Parse(string json)` (`type` is `overview`, `readModel` or `refreshModel`).

- [ ] **Step 1: Write failing tests:** `Corners_in_any_order_normalise`; `Intersects_is_true_for_overlap_touch_and_containment_and_false_apart`; `A_tiny_box_is_not_usable`; `Default_ignores_a_far_outlier` (100 vertices in 0..100 ft plus one at 10000 ft → box inside 0..110); `Default_of_nothing_is_unusable`; `Parse_reads_level_and_crop`; `Parse_rejects_an_unknown_type`.
- [ ] **Step 2:** `dotnet test addin/Qbiq.PathTool.Tests` → FAIL (types missing).
- [ ] **Step 3:** Implement. **Step 4:** run → PASS. **Step 5:** commit `feat(addin): crop box maths and read requests`.

### Task 20: Read through the active 3D view, overview and cropped read (Add-in)

**Files:** Create `addin/Qbiq.PathTool.Core/ViewChoice.cs`, `addin/Qbiq.PathTool.Tests/ViewChoiceTests.cs`; modify `Extraction/RevitModelReader.cs`, `Extraction/MeshReader.cs`, `ReadModelEvent.cs`, `PathToolWindow.cs`.

**Interfaces:**
- `ViewChoice.Choose(bool activeIsView3D, IReadOnlyList<string> view3DNames, string defaultName)` → `ViewChoice.Active | Default | None` (pure, tested).
- `IModelReader` gains `LevelPayload ReadOverview(string level)` (2D only, no meshes, no crop) and `LevelPayload ReadModel(string level, CropBox? crop)` (2D inside the crop for that level, plus whole-building meshes from the 3D view inside the crop). `LevelPayload` gains `Levels` (all level names), `CurrentLevel`, `ViewName`.
- MeshReader categories map to mesh types by `BuiltInCategory` (walls, floors, ceilings, roofs, doors, windows, columns, beams, stairs, railings, furniture, casework, lighting, generic, everything else `other`); `Options.View = the 3D view`; elements come from `new FilteredElementCollector(doc, view.Id)` filtered by the crop's `BoundingBoxIntersectsFilter` (XY from the crop, Z unbounded). The vertex budget and shell-first rule stay.
- Page → host messages: `{type:"readOverview", level}`, `{type:"readModel", level, crop}`, `{type:"refreshModel"}`; the window raises the ExternalEvent with a `ReadRequest`.

- [ ] **Step 1: Write failing tests** (`ViewChoiceTests`): active 3D view → Active; not 3D and a default exists → Default; not 3D and none → None; a message string for None names what to do ("Open a 3D view in Revit and try again.").
- [ ] **Step 2:** `dotnet test` → FAIL. **Step 3:** implement `ViewChoice` and the Revit-side changes (compile against Revit 2024; not run in Revit). **Step 4:** tests PASS and `dotnet build addin/Qbiq.PathTool.Addin -c Release` clean. **Step 5:** commit `feat(addin): read the 3D from the active view; overview and cropped reads`.

### Task 21: Engine accepts levels, view name and overview payloads

**Files:** Modify `backend/revit_payload.py`, `backend/app.py`; test `backend/tests/test_app_revit_upload.py`, `test_revit_payload.py`.

**Interfaces:** payload fields `levels: [str]`, `current_level: str`, `view_name: str`, `keep_meshes: bool`; the response echoes `levels`, `level`, `view_name`; `keep_meshes: true` with no meshes keeps the previously loaded 3D (level change re-reads 2D only). An overview payload (no meshes, walls only) is valid.

- [ ] **Step 1: Write failing tests:** `test_levels_and_view_name_are_echoed`; `test_keep_meshes_reuses_the_last_3d_when_a_level_changes`; `test_overview_payload_without_meshes_loads`; `test_keep_meshes_without_a_previous_load_is_just_empty`.
- [ ] **Step 2:** `pytest tests/test_app_revit_upload.py tests/test_revit_payload.py -q` → FAIL. **Step 3:** implement (the golden fixture gains the new optional fields; the C# `Payload.cs` mirrors them and its golden test is updated). **Step 4:** PASS. **Step 5:** commit.

### Task 22: One-screen layout in the Revit window (Frontend)

**Files:** Modify `frontend/js/revit-shell.js`, `frontend/css/revit-shell.css`, minimal hooks in `frontend/index.html`; create `frontend/js/layout-revit.js` + `frontend/tests/layout-revit.test.js` for the pure parts.

**Interfaces:** `panelSections(ids: string[]) -> [{id, title}]` and `shouldShowStepChrome(hostMode)` (false in revit); the shell moves `#step-2`, `#step-3`, `#step-4` (and the load/JSON card from `#step-1`) into a right column `#rv-panel` as stacked sections (collapsible, all open), hides `#step-dock` and "next step" controls, forces `.canvas-area` (plan) and `.preview-3d` visible side by side, and moves `#video-timeline` into a full-width bottom bar with the transport controls. Existing element ids and handlers are untouched, so the page keeps working.

- [ ] **Step 1: Write failing tests** for the pure helpers. **Step 2:** `node --test frontend/tests/layout-revit.test.js` → FAIL. **Step 3:** implement the helpers and the DOM move. **Step 4:** `node --test frontend/tests/*.test.js` PASS; open `/?host=revit&demo=1` and verify with screenshots: 3D and plan side by side, panel on the right with all sections, timeline bar below, no step buttons; browser `/` unchanged. **Step 5:** commit.

### Task 23: Crop screen, level selector, Change area (Frontend)

**Files:** Create `frontend/js/crop.js`, `frontend/tests/crop.test.js`; modify `revit-shell.js`, `revit-shell.css`.

**Interfaces:** `crop.js`: `normaliseRect(a, b)`, `clampRect(rect, bounds)`, `hitTest(rect, point, tol) -> 'move'|'nw'|'ne'|'sw'|'se'|'n'|'s'|'e'|'w'|null`, `applyDrag(rect, handle, dx, dy, bounds)`, `toModelBox(rectDisplay) -> {xmin,ymin,xmax,ymax}` (display y is negated), `isUsable(rect)`. The shell shows the overview plan, a draggable/resizable frame (default from the engine's `crop_default` or the whole plan), text "Drag the frame around the area to use. Anything outside is ignored.", buttons **Use this area** / **Use everything**; header has the level `<select>` (from `levels`), **Change area**, and a remembered crop used by Refresh. Empty result (`nothing in this area`) shows a message and the frame again.

- [ ] **Step 1: Write failing tests** for `crop.js` (corner order, clamping, tiny frame unusable, each handle's drag, display→model y flip, hit-test tolerance). **Step 2:** FAIL. **Step 3:** implement and wire the flow (`readOverview` → frame → `readModel` → `modelLoaded`; level change sends `readModel` with `keep_meshes`). **Step 4:** node tests PASS; in the browser demo drive the frame with synthetic pointer events and check the confirm message carries model-space numbers. **Step 5:** commit.

### Task 24: Package, install and re-check

- [ ] **Step 1:** Update `addin/smoke-engine.ps1` (levels, view name, keep_meshes) and `addin/ACCEPTANCE.md` (crop frame, 3D view source, level change, one-screen layout). **Step 2:** run all gates (backend `pytest`, `node --test frontend/tests/*.test.js`, `dotnet test`, Release build) and `build-all.bat` with the real PyInstaller; run `smoke-engine.ps1` on the bundle copied to a short path. **Step 3:** a fresh whole-branch review of the revision, one fix pass. **Step 4:** push the branch and re-run `install.ps1` for the user (they restart Revit).
