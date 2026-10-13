# qbiq JSON+SVG Import — Design Spec

Date: 2026-10-13
Project: revit-walkthrough-v2 (`C:\Users\kevin\revit-walkthrough-v2`)
Status: Approved by user, ready for implementation planning

## Background

qbiq Path Editor currently ingests floor plans from DXF (via `dxf_extractor.py`)
or IFC/RVT (via `revit_extractor.py`), both producing a shared `LevelGeometry`
dataclass (`revit_extractor.py`) that every downstream system (SVG rendering,
Smart Path's corridor-graph routing, the 3D preview, Enscape/Revit XML export)
consumes identically regardless of source.

qbiq's own "Spaceplanner" platform exports floor plans in two companion
formats for the same job: a JSON file describing the building's structural
shell (exterior envelope, core, columns, mullions, and — when present —
classified interior partition walls), and an SVG file describing the
space-planning layout (per-room polygons with a program-type classification,
plus explicit per-door geometry). This spec adds a new ingestion path that
parses both together into one `LevelGeometry`, so every existing downstream
feature (Smart Path, 3D preview, XML export) works on qbiq-sourced floor plans
with no changes to any of those systems.

## Goals

- Parse a matched JSON+SVG pair (same qbiq `job_code`) into one `LevelGeometry`,
  reusing the exact same dataclass and fields every other extractor already
  populates.
- Correctly distinguish real interior walls from virtual space-planning zone
  divisions, using real evidence from the data (not a guess) — see "Wall vs.
  virtual zone" below.
- Make 3D preview and Smart Path routing work automatically for this source,
  by construction, since both already operate purely on `LevelGeometry`
  fields — no new 3D-generation or routing code.
- Follow the same units-safety-net pattern already proven for DXF (a
  plausibility check against the building's overall size, auto-correcting by
  a power-of-ten factor if the declared scale produces an implausible
  building footprint).

## Non-goals

- Room program-type metadata (e.g. `office-non-receiving-guests`,
  `conference`) is parsed and retained on each space polygon for future use,
  but no feature in this spec *acts* on it (e.g. no must-see-room biasing
  here — that's the separate, already-identified sub-project C from the
  corridor-graph work).
- No change to Smart Path, 3D preview, or export logic — they are reused
  unchanged, by design.
- `egress` (present as an empty, hidden group in the reference file) and
  `clearance` (door-swing arcs, `pointer-events:none`) SVG groups are
  recognized as existing but out of scope — not parsed into any
  `LevelGeometry` field in this pass.

## Reference files

Two real example files were used to ground this design (not committed to the
repo — they live outside it):
- `C:\Users\kevin\.codex\attachments\018c77c8-e695-4975-b4e0-91fa555a148d\Pasted text.txt` — the JSON structure export.
- `C:\Users\kevin\.codex\attachments\3dc362f9-eecb-4740-b8af-2acff74b62ef\Pasted text.txt` — the matching SVG space-planning export (`job_code="80229463890003"`).

## JSON format (confirmed from the reference file)

Top-level keys, each a list:
- `perimeter_ls` — 2-point line segments tracing the building's exterior
  envelope. Not pre-ordered into a single walk — segments must be stitched.
- `core_ls` — 2-point line segments forming several separate closed loops:
  individual core elements (elevator/stair/mechanical shafts) plus one larger
  rectangle marking the overall core-zone boundary.
- `columns_ls` — 2-point line segments forming many small closed loops (one
  per structural column), each with slightly chamfered corners.
- `qbiq_walls_ls` — classified interior partition walls, when qbiq has
  classified them for this job. **Empty in the reference file** — the design
  must not depend on this being populated (see "Wall vs. virtual zone").
- `mullions` — curtain-wall/facade framing line segments. Empty in the
  reference file, but the parser must handle it the same way as the other
  `_ls` keys when present.
- `perimeter`, `core`, `columns`, `qbiq_walls` (no `_ls` suffix) — flat,
  unordered point lists. Confirmed (by direct value comparison against their
  `_ls` counterparts) to be the same vertices without segment pairing or
  polygon order. **Not used** — they carry no information the `_ls` keys
  don't already have in a more usable (edge-paired) form.
- No units field anywhere. Confirmed directly with the user: **1 unit = 1cm**
  (`units_to_metres = 0.01`), applied with the same plausibility
  auto-correction safety net as `dxf_extractor.py`'s `_fix_implausible_units`,
  in case a specific export has the same kind of units/scale mismatch found
  earlier this project in a real DXF file.

## SVG format (confirmed from the reference file)

Root structure: `<svg>` → `<g id="maing">` → `<g id="designg">` → `<g id="prop">`
containing sibling groups: `ext` (exterior envelope path, redundant with the
JSON's `perimeter_ls` — JSON is used as the structural source of truth, per
"JSON vs SVG for structure" below), `rooms` (the data this format uniquely
supplies), `cols` (columns — cross-checked against the JSON's `columns_ls` and
confirmed to describe the same geometry), `furniture`, `texts`, `egress`
(empty/hidden in the reference file), `clearance` (door-swing arcs,
`pointer-events:none`, non-structural), `addons`/`addons_draw`, `eg_imgs`.

Only the `rooms` group is parsed for this spec.

### Room paths

Each room is one `<path fill="..." stroke="..." ... class="d0 r<id> <program-type> c<n> h<n> a<n> ..." d="M x,y L x,y ... z"/>`.
The `d` attribute uses only `M`/`L`/`Z` commands in the reference file — the
parser must handle exactly these and log/skip (not silently mis-parse) any
other SVG path command, since a future export could in principle include
curves.

### Wall vs. virtual zone (the key distinction, confirmed with real data)

Directly confirmed in the reference file: **83 rooms** have a solid boundary
stroke (`stroke-width="1.42"`, no `stroke-dasharray`); **exactly 1** room (of
program-type `comfort-zone`) has a **dashed** boundary
(`stroke-dasharray="4" stroke-width="0.2"`). This is a real, load-bearing
signal, not an assumption:

- A room path with **no `stroke-dasharray`** (checked on both the raw
  attribute and an inline `style=""` if present) → its closed boundary
  contributes to `geo.walls` **and** its interior contributes to `geo.spaces`.
- A room path **with `stroke-dasharray`** → its interior still contributes to
  `geo.spaces` (it's still a real, routable area — just not an enclosed
  room), but its boundary contributes **nothing** to `geo.walls`. There is no
  physical wall to route around there.

This is also why `qbiq_walls_ls` being empty in the reference file is not a
gap: real interior partitions still exist via solid-stroke room boundaries —
two rooms sharing an edge is exactly how a real wall between them is encoded
in this format.

### Doors

Every door's geometry is a cluster of SVG `<polyline>` elements sharing one
`door_id_<uuid>` class token (jamb lines, swing-arc detail, the opening-width
reference line — all under the same class). Confirmed in the reference file:
exactly one polyline per `door_id` has a real `fill` value (e.g.
`fill="#E9D8A6"`, matching the room's own fill color — a rendering trick to
visually "erase" the wall line across the opening); every other polyline
sharing that `door_id` has `fill="None"` (jamb/swing construction detail).
**Only the real-fill polyline becomes a `geo.doors` entry** per door — it
directly gives the real opening's location and width, with no detection
logic needed to separate it from the construction-detail lines.

No special handling is needed to cut a gap in the wall geometry at each
door's location: every solid room's boundary path is a complete closed shape
with the door polyline merely overlaid on top, meaning the "wall" at a door's
location is always solid as drawn. This is exactly the same situation already
solved for DXF by the existing, proven `_clear_doors`/corridor-graph
door-bridging mechanism (force each door's location passable from our own
clearance parameters, never trust the drawn wall geometry at that spot) — no
new logic is needed here, only populating `geo.doors` correctly.

## Category mapping

| Source | `LevelGeometry` field | Notes |
|---|---|---|
| JSON `perimeter_ls` (stitched) | `geo.walls` | Exterior envelope |
| JSON `core_ls` (stitched) | `geo.walls` | Core shafts + core-zone boundary |
| JSON `qbiq_walls_ls` (stitched, if present) | `geo.walls` | Classified interior partitions, when qbiq has them |
| JSON `columns_ls` (stitched) | `geo.columns` | One closed loop per column |
| JSON `mullions` (stitched, if present) | `geo.windows` | Curtain-wall framing — transparent, non-routable, same category as glazing for the same reason |
| SVG room path, no `stroke-dasharray` | `geo.walls` + `geo.spaces` | Real enclosed room |
| SVG room path, `stroke-dasharray` present | `geo.spaces` only | Virtual planning zone, no real wall |
| SVG door's real-fill polyline (one per `door_id`) | `geo.doors` | — |
| SVG `ext`, JSON non-`_ls` keys, `egress`, `clearance`, `addons*`, `eg_imgs`, `furniture`, `texts` | *(not parsed)* | `ext` redundant with JSON perimeter; others out of scope per Non-goals |

Room program-type (the class token after `r<id>`, e.g.
`office-non-receiving-guests`) is retained as metadata alongside each space
polygon for future use, per Non-goals — the exact storage mechanism (e.g. a
parallel list on `LevelGeometry`, or deferred until a feature needs it) is an
implementation-planning decision, not fixed by this spec.

## Architecture / implementation shape

New module: `backend/qbiq_extractor.py`

```
def extract_qbiq(json_path: str, svg_path: str, level_name: str = "L-0") -> LevelGeometry
```

Internal shape (names illustrative, not binding on the implementation plan):
- A segment-stitching utility: given a flat list of 2-point segments, chain
  them by shared endpoints into connected polylines, closing a chain into a
  polygon if it returns to its own start. Used for every JSON `_ls` key.
- An SVG room/door parser using `xml.etree.ElementTree` (not regex — this
  file is real, well-formed XML and ElementTree handles attribute/entity
  escaping correctly where regex would be fragile), walking into
  `designg > prop > rooms` and reading each room `<path>` and each door's
  polyline cluster as described above.
- The existing units-plausibility auto-correction pattern from
  `dxf_extractor.py`, applied with a 0.01 declared `units_to_metres` instead
  of a `$INSUNITS`-derived one.

## Upload / frontend flow

Mirrors the existing DXF+IFC dual-upload pattern exactly:
- A new `/api/upload-qbiq` Flask route accepting both files in one
  multipart request, calling `extract_qbiq` and returning the same response
  shape `/api/upload` already returns (`svg`, `bounds`, `geometry`, etc.), so
  every existing frontend consumer of that response shape needs no changes.
- The existing "Load Project" folder-picker (`onFolderSelected` in
  `frontend/index.html`) is extended to also recognize a `.json`+`.svg` pair
  in the selected folder (in addition to its current `.dxf`/`.ifc` detection)
  and route them to the new endpoint. No new UI beyond this detection change.

## Testing / verification plan

- A small, hand-built synthetic JSON+SVG pair (one solid room, one dashed
  comfort-zone, one door with several sibling construction-detail polylines,
  one column) proving: walls come from the solid room + JSON structural
  geometry; the dashed zone contributes no walls but does contribute a space
  polygon; the door's real-fill polyline is correctly picked out among its
  siblings; the result is a valid `LevelGeometry`.
- The two real reference files (above) run through the full extractor,
  verifying a sane `units_to_metres` (0.01, or an auto-corrected value if the
  plausibility check fires), a non-empty wall/column/space/door set, and —
  critically — that the resulting `LevelGeometry` flows unchanged through
  Smart Path (a 5-point route succeeds) and the 3D preview (wall/column
  extrusion renders) with no modification to either system, confirming the
  "reuse, not new code" claim in Goals.

## Rollout notes

- `revit-walkthrough-v2` now has a git repository (initialized during the
  corridor-graph-routing work); per established project practice, commits
  happen on explicit user request, not automatically.
