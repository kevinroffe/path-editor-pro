# Ceiling and Detailed Furniture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a ceiling with recessed light panels to the qbiq 3D preview and replace the box furniture with detailed, bom-driven procedural models.

**Architecture:** All geometry stays in `backend/qbiq_scene3d.py` (pieces in a component's canonical local box → framed faces → merged one mesh per material). New primitives (rounded rings, slanted prisms, rotated bars) and a `smooth` material flag extend the piece vocabulary; a bom parser picks per-part builders and assembles composite items; the ceiling is a new scene layer. The frontend only learns two mesh types (`ceiling`, `light`) and hides them above ceiling height.

**Tech Stack:** Python 3.13, shapely, numpy, pytest; single-file frontend (Three.js r128).

**Spec:** `docs/superpowers/specs/2026-10-18-ceiling-and-furniture-design.md`

## Global Constraints

- Work in `C:/Users/kevin/revit-walkthrough-v2/.worktrees/qbiq-design-json` (branch `qbiq-design-json`); venv `C:/Users/kevin/revit-walkthrough-v2/.venv/Scripts/python.exe`; pytest from `backend/`.
- Plan coordinates are model units (cm); `k` = model units per metre; z is metres. Pieces are built in the component's canonical box with local +y = back (chair backs, desk tops at +y), as today.
- `CEILING = 3.0` m; ceiling slab 3.0–3.05 m; light panels 0.6 × 1.2 m on a 2.4 m grid, z 2.99–2.995, inside the ceiling and outside cores.
- Heights: seat 0.45–0.47 m; chair back top 0.85–1.0 m (executive 1.15 m); desk top 0.74 m (25 mm); reception 1.05 m; conference/dining 0.74 m; coffee 0.42 m; bar 1.05 m; bar-stool seat 0.75 m; storage 0.8 m (S_LS) / 1.8 m (S_HS); kitchen worktop 0.9 m (40 mm); fridge 1.8 m.
- Palette (spec, verbatim): fabric charcoal `#3b3f46`, grey `#8a8f96`, warm sand `#c9b79c`, muted teal `#5b8a8c`; light oak `#c49a6c`; white laminate `#f3f3f1`; brushed metal `#b8bcc2` (metalness 0.7); black plastic `#25282c`; stainless `#c9cdd2` (metalness 0.8); fridge white `#eef0f2`; foliage `#4f7d4a`, `#5f9558`; terracotta `#b5674d`; screen black `#15171a`; ceiling `#f7f7f5`; light `#fff6e0`.
- Every builder output stays within the item's canonical footprint (± 1 cm) — including assemblies.
- Pieces with a cap are convex rings (caps are fan-triangulated by `_merge`).
- The ceiling casts no shadow; ceiling + panels are visible only while the camera is below `CEILING`.
- `_MAX_VERTS = 400_000` unchanged; scene order stays structure first, furniture last (furniture is dropped first at the cap); the ceiling is structure.
- No `print()`; module logger; short functions, one-line docstrings; flake8 `--extend-ignore=W292,W391,E302,E501` with no new findings; the controller commits.

## Review Focus

- **Mirrored / rotated placements** (`matrix3d` with a negative determinant) — slanted backs and asymmetric parts (desk chair side, fridge end) still land on the drawn side; caps keep outward winding. Test in Task 1 (slanted prism through a mirrored frame) and Task 3 (mirrored desk assembly).
- **Footprints smaller than the parts** (35 cm side table, 30 cm-deep storage, a desk box with no room for guest chairs) — builders clamp; never inverted rings, never parts outside the box, guest chairs omitted rather than squeezed. Test in Tasks 3–5.
- **Missing / malformed / unknown `bom_data`** — falls back to name keywords, then the neutral box; one log line per unknown code. Test in Task 3.
- **Ceiling over plates with holes and cores** — slab respects holes; no light panel overlaps a core or crosses the plate edge. Test in Task 2.
- **Vertex cap on a huge plan** — the ceiling survives when furniture is dropped. Test in Task 2 (cap monkeypatched).

---

### Task 1: Primitives, slanted pieces, smooth merge, palette

**Files:** Modify `backend/qbiq_scene3d.py`; Test `backend/tests/test_scene_primitives.py`

**Interfaces — Produces:**
- `Mat = namedtuple("Mat", "type color opacity roughness metalness smooth", defaults=(False,))`; `_mat(kind, color, opacity=1.0, roughness=0.85, metalness=0.0, smooth=False)`.
- Palette constants named after the spec: `FABRIC_CHARCOAL, FABRIC_GREY, FABRIC_SAND, FABRIC_TEAL, OAK_LIGHT, LAMINATE, METAL, PLASTIC_BLACK, STAINLESS, FRIDGE, FOLIAGE, FOLIAGE_LIGHT, TERRACOTTA, SCREEN` (all type `"furniture"`; fabric and foliage `smooth=True`).
- `_round_rect(b: Bounds, r: float, seg: int = 4) -> list` — CCW convex ring, corners of radius `min(r, w/2, h/2)`.
- `_bar_ring(cx: float, cy: float, length: float, width: float, angle: float) -> list` — CCW rectangle from the centre outward along `angle` (radians).
- A piece is `(mat, ring, z0, z1)` or `(mat, ring, z0, z1, (dx, dy))`: the 5-tuple's top ring is the bottom ring shifted by `(dx, dy)` local units (slanted prism). `_component` and `_framed` accept both; the shift goes through the frame's linear part.
- `_merge` emits `"smooth": bool` on every mesh dict; for smooth materials, **side** faces share vertices with other side faces at the same rounded position, caps keep their own.

- [ ] **Step 1: Failing tests** — `test_round_rect_is_convex_ccw_and_inside_bounds` (signed area > 0, all points within b, corner count = 4·(seg+1)); `test_bar_ring_runs_from_centre`; `test_slanted_piece_top_is_shifted` (a 5-tuple through the identity frame: top-cap verts = bottom + (dx, dy)); `test_slanted_piece_through_mirrored_frame` (frame (-1,0,0,1,0,0): top shift x is negated and caps still face up/down — check face normal z signs); `test_smooth_cylinder_shares_side_vertices` (a 16-gon prism with a smooth mat merged → vertex count == 16·2 + 16 + 16, not 16·4 + 32); `test_flat_material_unchanged` (same prism, non-smooth → 16·4 + 32 verts, `"smooth": False`).
- [ ] **Step 2: Run** `-m pytest tests/test_scene_primitives.py -q` → FAIL (missing names).
- [ ] **Step 3: Implement.** Smooth merge: keep a per-material dict `(round(x,4), round(y,4), round(z,4)) → index` used only for side faces (faces produced by `_sides`; tag them by making `_sides` return a third tuple element `"side"` and caps `"cap"`, defaulting to `"cap"` for 2-tuples elsewhere).
- [ ] **Step 4: Run** → PASS; also `tests/test_qbiq_scene3d.py` still passes. flake8.
- [ ] **Step 5: Commit** — `feat(3d): rounded/slanted furniture primitives and smooth shading`.

### Task 2: Ceiling and light panels (backend + frontend)

**Files:** Modify `backend/qbiq_scene3d.py`, `frontend/index.html`; Test `backend/tests/test_scene_ceiling.py`

**Interfaces — Produces:** `CEILING_TOP = 3.05`; `CEILING_MAT` (type `"ceiling"`), `LIGHT_MAT` (type `"light"`); `_ceiling(plates: list, cores: list, k: float) -> list` (faces); `_light_panels(plates: list, cores: list, k: float) -> list` (faces); both appended in `build_design_scene` right after the cores (before furniture). Frontend: `P3D_TYPE_STYLE.ceiling`, `.light`; `syncCeiling()`.

- [ ] **Step 1: Failing tests** (synthetic `SceneInputs` — reuse the fixture style of `tests/test_qbiq_scene3d.py`): `test_ceiling_covers_the_plate` (ceiling mesh exists, type `ceiling`, its top-cap area ≈ plate area ± 1%, z in [3.0, 3.05]); `test_ceiling_respects_plate_holes`; `test_panels_inside_plate_and_outside_cores` (every `light` vertex's xy inside the plate and outside every core polygon; panel count > 0 on a 20 × 10 m plate; z in [2.99, 2.995]); `test_ceiling_survives_the_vertex_cap` (monkeypatch `_MAX_VERTS` to just above the structure's count; furniture dropped, `ceiling` mesh still present).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** backend (panels: grid of 0.6 × 1.2 m rectangles at 2.4 m pitch from the plate bounds' min corner + 1.2 m, kept when `plate.contains(panel)` and no core intersects). Frontend: style entries `ceiling: { color: 0xf7f7f5, roughness: 0.95 }`, `light: { color: 0xfff6e0 }`; in `buildContractMesh` light meshes use `MeshBasicMaterial({ color })` (unlit, no shadows) and ceiling meshes `castShadow = false`, `receiveShadow = true`; tag both `userData.ceiling = true`; `syncCeiling()` sets `visible = threeCam.position.y < 3.0` on tagged meshes — call it in `render3DLoop` before render and wherever the scene is rendered once outside the loop.
- [ ] **Step 4: Run** → PASS; `node --check` the extracted script. **Step 5: Commit** — `feat(3d): ceiling with recessed light panels, hidden from above`.

### Task 3: Bom parsing and assemblies

**Files:** Modify `backend/qbiq_scene3d.py`; Test `backend/tests/test_scene_bom.py`

**Interfaces — Produces:** `Part = namedtuple("Part", "code length width")` (metres); `parse_bom(bom: str) -> list[Part]` (regex `^([A-Z]+(?:_[A-Z]+)*)_L(\d+)_W(\d+)$` per `|`-part, malformed parts skipped); `_PRIMARY_ORDER` (table/desk/counter/sofa/storage codes first); `_PART_BUILDERS: dict[str, callable]` — each `builder(b: Bounds, k: float, name: str, part: Part) -> list[pieces]` (filled in Tasks 4–5; this task registers placeholders that return the neutral box so assembly is testable); `_assemble(b, k, name, parts) -> list[pieces]`; `classify_furniture(name: str, bom: str = "") -> tuple[kind, build]` — bom path first (kind = the primary part's code), keyword rules next, `("fallback", _fallback)` last; `_component` passes the bom.

- [ ] **Step 1: Failing tests:** `test_parse_bom` (`"T_D_L140_W70|C_E_L60_W58|C_G_L58_W58"` → three Parts in metres; `"junk|C_K_L40_W50"` → one); `test_primary_part_wins` (`C_E|T_D` → kind `T_D`); `test_desk_with_task_chair_layout` (`T_WS_L160_W80|C_W_L48_W45` in a 160 × 160 cm box: desk pieces have y ≥ box.y1 − 80 cm, chair pieces y < that); `test_desk_guest_chairs_only_when_room` (`T_D|C_E|C_G|C_G`: 200 × 250 box → guest-chair pieces on the far side; 200 × 140 box → none); `test_kitchen_counter_layout` (`K_S|K_C|K_R` → three part groups, fridge at one end, sink inside the counter span); `test_unknown_bom_falls_back_to_keywords` (`"X_Y_L1_W1"` with name `"..._CHAIR"` → kind `chair`; unknown code logged once across two calls); `test_mirrored_desk_assembly_keeps_desk_on_drawn_side` (reuse the mirrored-desk fixture of `test_qbiq_scene3d.py`); `test_assembly_stays_inside_box` (every piece ring inside the box ± 1 cm).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; old `test_qbiq_scene3d.py` tests still pass. **Step 5: Commit** — `feat(3d): bom-driven furniture classification and assemblies`.

### Task 4: Seating — chairs, stools, sofas, bench, booth

**Files:** Modify `backend/qbiq_scene3d.py`; Test `backend/tests/test_scene_seating.py`

**Interfaces — Produces:** part builders registered for `C_C, C_K, C_W, C_E, C_G, C_B, L_S, L_B, K_DB` per the spec §3 (shapes, materials, heights).

- [ ] **Step 1: Failing tests** (one synthetic box per part at its bom size; helper `_pieces(code, name, L, W)` returns pieces; helper `_top(pieces)` = max z): seat height 0.45 ± 0.03 for C_C/C_K/C_W/C_E/C_G; back top 0.85–1.0 (C_E 1.15 ± 0.05) and back slanted (some piece with a shift); `#Arms` → exactly 2 arm pieces, `#no_arms` → 0; C_W/C_E five-star base → 5 spoke pieces + castors; C_K/C_C/C_G → 4 legs; C_B seat at 0.75 ± 0.03 with a footrest ring piece; `SOFA_2_SEAT` → 2 seat cushions, `SOFA_3_SEAT` → 3, `ARMCHAIR_1` → 1, two rounded arms; K_DB → two benches with backs + a table between; every piece inside the box ± 1 cm; fabric pieces use smooth materials; a 35 × 35 cm box for any seat part builds without inverted rings (signed area > 0 for every ring).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS. **Step 5: Commit** — `feat(3d): detailed seating models`.

### Task 5: Tables, desks, storage, kitchen, plant, printer

**Files:** Modify `backend/qbiq_scene3d.py`; Test `backend/tests/test_scene_tables.py`

**Interfaces — Produces:** part builders for `T_WS, T_D, T_R, T_C, T_CF, T_DT, T_BR, CO_H, S_LS, S_HS, K_C, K_S, K_R, PH_PR, V_P`; the old box builders (`_chair`, `_desk`, `_table`, `_storage`, `_sofa`, `_kitchen`, `_booth`, `_plant`) are replaced by keyword-fallback wrappers that call the new part builders with a synthetic `Part` from the box size (so the keyword path gets detailed models too); remove the dead box-only code.

- [ ] **Step 1: Failing tests:** desk top at 0.74 ± 0.01 with thickness 0.025; T_WS has a monitor (a dark `SCREEN` piece above the top) and a modesty panel; T_R top 1.05; T_C/T_DT 0.74, T_CF 0.42, T_BR 1.05; ROUND/CIRCLE name → a ≥ 24-gon top + pedestal; CO_H → a three-sided rounded top with 3 legs; S_LS top 0.8, S_HS 1.8, doors = round(width / 0.5) fronts with handles; K_C worktop 0.9 with base doors, K_S basin inside the worktop, K_R 1.8 tall; V_P has a terracotta pot and ≥ 3 foliage pieces; PH_PR builds; every piece inside its box ± 1 cm; a 35 × 35 cm coffee side table builds cleanly. Update `test_desk_tops_out_at_desk_height` / `test_chair_has_a_back_to_085` in `tests/test_qbiq_scene3d.py` to the new heights (0.74; back top within 0.85–1.0).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS (whole `tests/test_qbiq_*.py` + new files). **Step 5: Commit** — `feat(3d): detailed tables, desks, storage, kitchen and accessories`.

### Task 6: Catalogue coverage on real files + visual check

**Files:** Test `backend/tests/test_scene_catalogue_real_files.py` (skip if the JSONs are absent); scratchpad screenshot script (not in the repo).

- [ ] **Step 1: Failing test** (passes only once Tasks 3–5 cover the catalogue): for both real design JSONs, every shown stencil component resolves via the bom path (no `fallback`, no keyword-only kind), the scene builds with fewer than `_MAX_VERTS` vertices and no dropped faces, and contains `ceiling` and `light` meshes. (Write it before Tasks 3–5 conceptually; here, run it and record any uncovered codes — add their builders if any.)
- [ ] **Step 2:** Full suite (`-m pytest -q`) passes; flake8 no new findings.
- [ ] **Step 3: Visual check** — extend the scratchpad `pw/shot3d.js`: eye-level screenshots of a Conference room and an open-plan desk area (`3d-eye-after.png`, `3d-desks-after.png`), one from inside showing the ceiling and panels, one from above (camera y = 30) showing the ceiling hidden; compare with `3d-eye.png` (before). Hand the images to Kevin.
- [ ] **Step 4: Commit** — `test(3d): real-file furniture catalogue coverage`.
