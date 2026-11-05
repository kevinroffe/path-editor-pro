# Revit Add-in v3 Plan — 2D plan carries everything; Revit-camera preview spike

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline). Spec: `docs/superpowers/specs/2026-11-05-revit-addin-design.md`, section **Revision 3** (wins over earlier text). Global constraints unchanged (Revit 2024, read-only except the temporary camera orientation, engine key, English, browser mode unchanged).

**Goal:** Remove the 3D window and 3D read from the Revit window, show everything the path means on the plan, and add an experimental "Revit camera" preview.

## Review Focus
1. Turning the Revit camera on with **no 3D view / a locked view / a view that is not perspective**: a clear message, preview off, no crash.
2. **Turning it off or closing the window** restores the view's original orientation.
3. **Rapid scrubbing**: pose updates are coalesced (latest wins), never queued without bound.
4. The plan with **no route**, a **single point**, or points **outside the frame**: no errors, no cones drawn from missing frames.
5. Browser mode (`/` without `?host=revit`) still has its 3D preview and wizard.

### Task 25: The plan shows everything; no 3D window (Frontend)
**Files:** create `frontend/js/plan-view.js`, `frontend/tests/plan-view.test.js`; modify `revit-shell.js`, `revit-shell.css`, `layout-revit.js` (+test).
**Interfaces:** `viewCone(x, y, yawDeg, fovDeg, len) -> [[x,y],[x,y],[x,y]]` (apex and two far corners, plan/display space, yaw direction (cos, sin)); `pauseKeyframes(plan) -> keyframes with still_s > 0`; `nearestFrame(frames, x, y)`.
- [ ] Write failing tests (cone corners at ±FOV/2, apex first; yaw 0 points +x; pause list; nearest frame; empty frames → null). Run `node --test frontend/tests/plan-view.test.js` → FAIL.
- [ ] Implement; wire in the shell: hide `.preview-3d` (never rendered), layout `plan | panel` with the bar under the plan, cones for every waypoint (selected highlighted), pause rings, inspector on the plan, remove the 3D overlay/orbit/inset/toggles; the render loop keeps running so time advances.
- [ ] Verify in the browser (`?host=revit&demo=1` with a route): cones and pause marks drawn, "you are here" moves, no 3D canvas. Commit.

### Task 26: The add-in no longer reads 3D (Add-in)
**Files:** modify `ReadModelEvent.cs`; docs.
- [ ] `ReadModelEvent` reads with `includeMeshes: false` everywhere in the window flow (the diagnostics button keeps the full read). Build Release, tests pass. Commit.

### Task 27: Revit camera preview spike
**Files:** create `addin/Qbiq.PathTool.Core/CameraPose.cs`, `addin/Qbiq.PathTool.Tests/CameraPoseTests.cs`, `addin/Qbiq.PathTool.Addin/CameraEvent.cs`, `frontend/js/revit-camera.js`, `frontend/tests/revit-camera.test.js`; modify `PathToolWindow.cs`, `revit-shell.js`.
**Interfaces:** `CameraPose.FromPage(xFt, yDisplayFt, yawDeg, levelElevationFt, eyeHeightFt) -> { Eye[3], Forward[3], Up[3] }` (eye = (x, -yDisplay, elevation + eye height), forward = (cos yaw, -sin yaw, 0), up = (0,0,1)); `CameraMessage.TryParse(json) -> (type, x, y, yaw)` for `camera`, `cameraStart`, `cameraStop`. JS: `makeThrottle(ms, now)` and `cameraMessage(frame)`.
- [ ] Failing tests (C# pose maths for yaw 0, 90, 180, -90 and elevation; message parsing incl. rejects; JS throttle coalesces to the latest and respects the interval). Run → FAIL.
- [ ] Implement Core + JS, then `CameraEvent : IExternalEventHandler` (start: remember `GetOrientation`, check active view is a 3D view and not locked; move: `SetOrientation(new ViewOrientation3D(eye, up, forward))` then refresh; stop: restore) with errors reported back as `{type:"cameraError", message}`; header button **Revit camera** (enabled only inside Revit); the page sends throttled poses from the play head. Compiles against Revit 2024; **not run in Revit**.
- [ ] Commit.

### Task 28: Gates, package, review, install
- [ ] All suites, `build-all.bat`, `smoke-engine.ps1`; update `addin/ACCEPTANCE.md` (2D-only layout, the Revit-camera spike steps and what to report); a fresh whole-range review and one fix pass; push; reinstall.
