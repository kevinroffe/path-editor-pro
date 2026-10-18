# Ceiling and Detailed Furniture — Design

Date: 2026-10-18 · Branch: `qbiq-design-json` · Status: approved in conversation, awaiting spec review

## Problem

Kevin: "I want to see the ceiling in the 3D and all the furniture in a better quality." Today the 3D preview of a
qbiq design JSON has no ceiling (open sky above 3.0 m walls) and every furniture item is 1–5 boxes from
`backend/qbiq_scene3d.py` (a chair is a slab on stick legs, a sofa is five boxes, a desk is a slab on two panels),
all flat-shaded. Kevin chose **detailed procedural models** (no external assets) and **ceiling + furniture only**
for this round (orbit view and lighting realism are a later round).

## Goal

The 3D walkthrough shows a ceiling with recessed light panels, and every furniture type in qbiq's catalogue is a
recognisable, proportioned model (chairs with shells, cushions and bases; desks with legs, modesty panels and a
monitor; sofas with cushions; real round/triangle tables; storage with doors; kitchens with sink and fridge;
plants in pots), with appropriate materials and smooth shading on curves.

## Non-goals

Orbit/overview navigation, environment-map lighting, ambient occlusion, textures, external 3D model files,
ceiling heights other than the wall height, changes to the camera path or plan routing.

## The catalogue (from both real design JSONs: 48 types)

Each stencil component has `name` (e.g. `QBIQ_FR_CHAIR_CONFERENCE_1#Arms`), `bom_data` (`|`-separated parts,
each `CODE_L<cm>_W<cm>`), `geom_box` + `matrix3d` (placement, already handled by `_canonical_box`). Part codes:

| Code | Part | Code | Part |
|---|---|---|---|
| C_C | conference chair | T_WS | workstation desk |
| C_K | kitchen chair | T_D | office desk |
| C_W | task chair (workstation) | T_C | conference table |
| C_E | executive chair | T_CF | coffee table |
| C_G | guest chair | T_DT | dining table |
| C_B | bar stool | T_BR | bar table |
| L_S | sofa / armchair | T_R | reception desk |
| L_B | lounge bench | CO_H | collaboration (triangle) table |
| S_LS / S_HS | low / high storage | K_C, K_S, K_R | kitchen counter, sink, fridge |
| K_DB | kitchen dining booth | PH_PR | printer |
| V_P | plant | | |

Name details refine a part: `#Arms` / `#no_arms`, `ROUND` / `CIRCLE` / `TRIANGLE` / `RECTANGULAR`, seat counts
(`SOFA_2_SEAT`, `SOFA_3_SEAT`, `ARMCHAIR_n`).

## Design

### 1. Ceiling

- `build_design_scene` adds a **ceiling slab**: the union of the floor plates (`SceneInputs.plates`) at
  `CEILING` (3.0 m) to 3.05 m, material type `ceiling` (white `#f7f7f5`, matte).
- **Recessed light panels**: 0.6 × 1.2 m tiles on a 2.4 m grid aligned to the plate's bounding box, kept only where
  the whole tile lies inside the ceiling polygon and not inside a core; a 5 mm-thick panel just under the ceiling
  (z 2.99–2.995), material type `light` (warm white `#fff6e0`, emissive in the frontend).
- **Frontend**: `ceiling` and `light` get entries in the 3D type styles; the ceiling **casts no shadow** (it
  would darken the whole interior under the sun light) and is double-sided; light panels render emissive and
  unlit. The ceiling and panels are **visible only while the camera is below `CEILING`** (the whole walkthrough)
  and hidden when it is above (the 3D panel's opening bird's-eye view), checked every rendered frame.
- Vertex budget: the ceiling is one polygon plus a few hundred panels (8 verts each after merging) — far below
  the cap. Cores keep rising to 3.0 m (they meet the ceiling).

### 2. Furniture chosen by bom code

`classify_furniture` gains a bom-driven path checked first: parse `bom_data` into parts `(code, L_m, W_m)`; the
item's **primary part** (the table/desk/counter/sofa/storage, else the first part) selects the builder; the other
parts are **sub-items** assembled inside the item's canonical box:

- desk + chair(s) (`T_WS|C_W`, `T_D|C_E|C_G[|C_G]`, `T_R|C_W`): desk along the local +y edge at its L×W; the
  first chair (task/executive) centred in the remaining depth facing the desk; guest chairs (C_G) on the far
  side of the desk facing it, when the box has room (else omitted);
- kitchen counter (`K_S|K_C|K_R`): counter run along +y at its L×W, sink basin set into the counter near one end,
  fridge as a tall unit at the other end;
- everything else: one part filling the box.

Name keywords (today's `_FURNITURE_RULES`) remain the fallback when `bom_data` is missing or unknown; the neutral
box remains the last resort. Unknown codes are logged once per code.

### 3. Detailed models (one builder per part kind)

All dimensions in metres, scaled by the existing `k` (model units per metre), placed in the canonical box
(local +y = back, as today). Representative proportions:

- **Chairs** (C_C, C_K, C_W, C_E, C_G): seat 0.45–0.47 m with a cushion slab (rounded corners), back as a slanted
  panel 0.85–1.0 m tall (executive taller, 1.15 m), **arms** for `#Arms`, C_E and C_W; **five-star base** with
  castors and a gas column for C_W / C_E; four legs for C_C / C_K / C_G; fabric per kind (charcoal task, grey
  conference, warm oak-legged kitchen chair).
- **Bar stool** (C_B): round seat at 0.75 m on a column, footrest ring at 0.3 m, round base.
- **Desks** (T_WS, T_D, T_R): 25 mm white laminate top at 0.74 m (reception 1.05 m with a front panel), metal
  side frames or panel ends, modesty panel at the back; workstation desks get a **monitor** (thin screen on a
  stand) and a keyboard.
- **Tables** (T_C, T_CF, T_DT, T_BR, CO_H): rectangular tops with four legs or a centre beam frame; ROUND /
  CIRCLE tops as 24-gon on a pedestal and base disc; TRIANGLE (CO_H) as a rounded triangle top on three legs;
  heights 0.74 m (conference/dining), 0.42 m (coffee), 1.05 m (bar); light-oak or white tops.
- **Sofas / armchairs / bench** (L_S, L_B): plinth on short legs, base, separate **seat cushions** (one per seat
  from the name, else by width), back cushions, rounded arms; bench = upholstered block on legs.
- **Storage** (S_LS 0.8 m, S_HS 1.8 m): carcass with a recessed plinth, door fronts with 3 mm gaps (one door per
  ~0.5 m of width) and bar handles.
- **Kitchen** (K_C, K_S, K_R, K_DB): base units with door fronts, 40 mm worktop at 0.9 m, recessed sink basin, tall
  fridge (white, 1.8 m); booth = two upholstered benches with backs facing a central table.
- **Plant** (V_P): tapered pot, soil disc, stacked foliage clusters (several overlapping rounded masses).
- **Printer** (PH_PR): grey body with a darker top tray on a low cabinet.

### 4. Geometry and shading

- **New primitives** in `qbiq_scene3d.py`: rounded-rectangle ring (corner radius, segments), n-gon ring (exists),
  **slanted prism** (top ring offset by dx, dy — tilted backs, splayed legs), rotated bar (star-base spokes),
  and a disc/ring for footrests and castors.
- **Smooth shading**: `Mat` gains `smooth: bool` (default False). For smooth materials the merge shares vertices
  between *side* faces (deduplicated by rounded position) so the frontend's `computeVertexNormals` averages them;
  caps keep their own vertices, so tops and bottoms stay crisp. The mesh dict gains `"smooth": true`; the
  frontend needs no change for normals (it already calls `computeVertexNormals`).
- **Materials** (new palette, PBR roughness/metalness): fabric (charcoal `#3b3f46`, grey `#8a8f96`, warm sand
  `#c9b79c`, muted teal `#5b8a8c`), light oak `#c49a6c`, white laminate `#f3f3f1`, brushed metal (`#b8bcc2`,
  metalness 0.7), black plastic `#25282c`, stainless sink (`#c9cdd2`, metalness 0.8), fridge white `#eef0f2`,
  foliage greens (`#4f7d4a`, `#5f9558`), terracotta pot `#b5674d`, screen black `#15171a`.
- **Budget**: about 300–900 vertices per item; the 36-room file (~240 items) stays far below `_MAX_VERTS`
  (400 000). The existing priority drop (furniture first) still protects huge plans.

## Error handling

A builder that raises is caught by the existing `_safe` and falls back to the neutral box (logged). Malformed
`bom_data` parts are ignored; a missing primary part falls back to name keywords.

## Testing

- **Per builder** (synthetic boxes): every vertex lies inside the item's footprint (± 1 cm) and between 0 and
  the kind's height cap; key heights (seat 0.45 ± 0.03, desk 0.74 ± 0.02, coffee 0.42 ± 0.03, bar 1.05 ± 0.03,
  storage 0.8 / 1.8); part counts (five-star base has 5 spokes, armchair has 2 arms, `#no_arms` has none,
  2-seat sofa has 2 seat cushions).
- **Assemblies**: `T_D|C_E|C_G|C_G` produces a desk, one executive chair and two guest chairs where the box allows;
  `K_S|K_C|K_R` produces counter, sink and fridge.
- **Catalogue coverage** (real files, skip if absent): every component in both design JSONs resolves to a bom
  builder — no fallback, no neutral box — and the scene stays under the vertex cap.
- **Ceiling**: ceiling polygon area ≈ floor-plate area; panels all inside the ceiling and outside cores; the
  ceiling mesh is type `ceiling`, panels type `light`.
- **Smooth meshes**: a smooth cylinder's side vertices are shared (vertex count ≈ 2n + caps, not 4n).
- **Visual**: headless before/after screenshots of the Conference room and an open-plan desk area at eye level,
  plus the ceiling visible from inside and hidden from above, for Kevin to judge.
