# Revit add-in v4: 3D preview pane beside the plan

> For agentic workers: use superpowers:executing-plans. Spec: docs/superpowers/specs/2026-11-05-revit-addin-design.md (Revision 4).

**Goal:** a 3D preview pane (first-person view along the path) between the plan and the right panel, on by default, with a header toggle.
**Architecture:** the page already renders the preview into `#preview-canvas` through `QbiqRevit.render`; v3 hid the pane and made the hook a no-op. v4 shows the pane in a third grid column, restores the hook while the pane is on, and asks for the 3D with the first read.

## Global Constraints
English UI text only. No intro/outro/music/fades. Browser (non-Revit) mode unchanged. Revit camera and Top view keep working.

### Task 29: preview pane
**Files:** Modify `frontend/js/layout-revit.js`, `frontend/js/revit-session.js`, `frontend/js/revit-shell.js`, `frontend/css/revit-shell.css`; Tests `frontend/tests/layout-revit.test.js`, `frontend/tests/revit-session.test.js`.
**Interfaces:** Produces `wantsMeshes(mode, previewOn) -> boolean` (true for mode 'top' or previewOn); `hiddenInRevit()` no longer lists `preview-3d`.
- [ ] Tests first: `wantsMeshes` truth table; `hiddenInRevit` without `preview-3d`. Watch RED.
- [ ] Implement the two functions. GREEN.
- [ ] Shell: `previewOn` state (default true), header toggle `#rv-prev`, body class `rv-preview-on`, render hook default renderer while on, `withMeshes` uses `wantsMeshes`, ResizeObserver calling `resize3D`, empty text, toggling on without meshes re-reads with 3D.
- [ ] CSS: three-column grid, pane placement, hide the pane bar/HUD extras, timeline spans plan + preview.
- [ ] Browser check with the demo plan; all suites; rebuild; commit.
