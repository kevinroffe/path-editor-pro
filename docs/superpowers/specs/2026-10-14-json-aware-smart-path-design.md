# JSON-Aware Smart Path — Design Spec

Date: 2026-10-14
Project: revit-walkthrough-v2 (qbiq Path Editor), branch `qbiq-design-json`
Status: Design approved section-by-section in chat; awaiting written-spec review

## Background

The app already imports the single-file qbiq **design JSON** (`extract_qbiq_design`,
`/api/upload-qbiq-design`) into the shared `LevelGeometry`, with a rich 3D scene.
Smart Path, however, still treats the result as plain geometry: walkable area =
floor plate minus walls/furniture, routed by the corridor-graph engine
(`corridor_graph.py`, grid A* fallback).

The user wants path generation — and the app generally — to understand the plan's
semantics from the JSON: rooms and their types, doors, the corridor, the entrance,
open areas, furniture — and to generate walkthroughs intelligently, staying
exclusively inside the corridor.

Reference files (outside the repo, read-only):
- `C:\Users\kevin\Downloads\121937120410001.json` — 17 rooms, 599 m² floor
- `C:\Users\kevin\Downloads\80565468720002.json` — 36 rooms, 871 m² floor

## Findings that shape the design (measured on 80565468720002.json)

| JSON layer | Area | Overlap with rooms | Meaning |
|---|---|---|---|
| top-level `circulation` | 166 m² | 0 m² | **The real corridor**: covers 99.3 % of floor-minus-rooms; 22 of 23 visible doors within 0.6 m |
| `zones.circulation` ("ZONES CIRCULATION" in qbiq's viewer) | 854 m² | 687 m² | Pre-room planning zone ≈ whole floor — not a corridor |
| `zones.circulation_graph.center_line` | 409 m long | 82 % inside rooms | Skeleton of the planning zone — unusable as corridor centrelines |

- `nfp_data.main_entrance` lies 1.08 m outside the corridor (inside an open area).
- 9 of 36 rooms have no visible door (`show_door` false on all doors): open areas
  (reception, open-space workstations, kitchen, lounge, …).

## User decisions

1. Routes are confined to the **top-level `circulation`** polygon (the real
   corridor), not `zones.circulation`.
2. A Smart Path point clicked inside a room snaps to **that room's door stop**;
   the camera pauses there and looks into the room.
3. **Strict corridor only**: open areas are not walkable; they are visited like
   rooms (stop at their corridor edge, look in). The entrance snaps to the nearest
   corridor point.
4. In scope: **Auto tour**, **Room-aware camera**, **Room labels & info**.
   (Explicit corridor-centreline routing was not selected as a separate feature;
   the existing corridor-graph engine already follows corridor middles.)

## Goals

- A semantic **plan model** built from the design JSON and shared by routing, the
  auto tour, the camera and the UI.
- Every Smart Path / auto-tour route lies entirely inside the corridor.
- One-click auto tour from the entrance visiting selected room types efficiently.
- A camera that stops at rooms and looks in, and glances into rooms it passes.
- Room names and info visible on the plan (and optionally in 3D).

## Non-goals

- No change for DXF, IFC or the JSON+SVG pair: without a plan model, behaviour is
  exactly as today.
- No walking inside rooms or open areas.
- No use of qbiq's `circulation_graph` (measured unsuitable).
- No real 3D furniture models, ceilings, or Enscape XML format changes.

## Section 1 — Plan model and corridor-only routing

**`backend/plan_model.py`** — `PlanModel` built from the design JSON at upload,
cached server-side beside the existing route caches (invalidated by the upload
generation counter like the corridor-graph cache).

Fields:
- `corridor`: top-level `circulation` polygon (model units).
- `rooms[]`: `id`, `name`/`space_type`, `area_m2`, headcount (planned/assigned
  from `program`/room fields when present), department, polygon, `is_open`
  (no visible door), doors (trimmed openings, as computed by the extractor),
  `label_point` (pole of inaccessibility), and a **stop**.
- `entrance`: corridor point nearest `nfp_data.main_entrance`.

Stops:
- **Enclosed room**: corridor point ~0.6 m from the door line, in front of the
  door that faces the corridor (multiple doors: the one opening onto the corridor;
  ties → nearest the room centre). `look_at` = room interior centre.
- **Open area**: corridor point on the corridor/area shared boundary nearest the
  area centre. `look_at` = area centre.
- **Room whose door doesn't reach the corridor**: corridor point nearest the door;
  flagged as a warning.

Routing (when a plan model exists):
- Walkable area = corridor polygon only, shrunk by the clearance; the existing
  corridor-graph engine runs on it unchanged. Rooms, open areas and furniture lie
  outside it, so routes cannot enter them.
- The clearance back-off (full → smaller → 0) still applies; if the corridor still
  does not connect two points, the route fails with "corridor blocked near (x, y)"
  — it never leaves the corridor.

Snapping of clicked points (`/api/autopath` input and auto-tour points):
- In the corridor → unchanged.
- Inside a room or open area → that room's stop (carries `look_at` + dwell).
- Anywhere else (wall, outside the building) → nearest corridor point.

Responses expose the plan model to the frontend as a `plan` field on the design
upload response: corridor polygon, rooms (id, name, type, area, headcount,
department, polygon, label point, stop, `is_open`), entrance.

## Section 2 — Auto tour, room-aware camera, labels

**Auto tour** (`POST /api/auto-tour`, toolbar button beside Smart Path):
- Panel with room-type checkboxes built from the plan. Default: all types except
  back-of-house (Storage Room, IT Room, Print Hub, Other).
- Start at the entrance stop; visit each selected room's stop once; ordering by
  nearest-neighbour + 2-opt on corridor shortest-path distances (computed once per
  tour); end at the last stop.
- Result is loaded into **Your Points** as normal editable points; stop points are
  tagged with their room name, look-at and dwell.
- Video length is set automatically to fit: walking ~1 m/s along the corridor
  route + dwell times. If the user shortens it, dwells scale proportionally down to
  a minimum.
- Unreachable rooms (corridor split, or stop not connected) are listed in the
  panel, not silently dropped; the tour still covers what is reachable from the
  entrance.

**Room-aware camera** (`route_processor.py`):
- Waypoints may carry optional stop metadata `{look_at: [x, y], dwell_s}`.
- At a stop the camera position freezes for the dwell; yaw turns toward
  `look_at`, holds, and turns back to the walking direction — always within the
  existing 180°/s turn-rate cap. Total video duration is respected: moving time =
  duration − dwells.
- Dwell by importance: Reception, Executive Office, Conference, Open Space 3 s;
  Office, Kitchen, Comfort Zone 2 s; others 1.5 s.
- **Glances**: passing within ~1.2 m of a room's door, or along a room's glass
  front, blends yaw up to ~30° toward the room for ~1 s; suppressed while the path
  itself is turning.
- Otherwise the camera faces along the corridor as today.
- Applies equally to manual Smart Path points snapped into rooms.
- Enscape XML export unchanged (stops are frames that hold position while turning).

**Labels & info** (frontend):
- 2D: room names at `label_point`, scaled to room size, toolbar toggle; hover
  tooltip with type, area m², headcount (planned/assigned), department; the
  corridor drawn as a subtle tint.
- 3D: optional floating room labels, hidden during walkthrough playback.

## Section 3 — Edge cases

- Door not touching the corridor → nearest-corridor stop + panel warning.
- Corridor narrower than clearance → clearance back-off; still blocked → explicit
  error with location; never leaves the corridor.
- Corridor in several disconnected pieces → tour covers the piece containing the
  entrance; unreachable rooms listed.
- No `circulation` in the file → no plan model: routing falls back to current
  design-JSON routing (floor plate minus walls), and auto tour, stops and labels
  are unavailable, with a warning. (Stops need a corridor; a design JSON without
  one has not been seen.)
- Large plans → corridor distances computed once per tour; fine for hundreds of
  rooms.

## Testing

Unit:
- Plan model: corridor selection; open vs enclosed rooms; stops inside the corridor
  in front of the correct door; open-area edge stops; entrance snapping.
- Snapping: corridor / room / outside clicks.
- Corridor constraint: every route waypoint **and every smoothed path sample**
  inside the corridor.
- Auto tour: each selected room visited exactly once; ordering length ≤ naive
  order; unreachable rooms reported.
- Camera: position frozen during dwell; yaw reaches look-at within tolerance; turn
  rate ≤ 180°/s; total duration respected; glances bounded at 30° and suppressed in
  turns.

Real-file (both design JSONs, env-overridable paths, skip if missing):
- Full auto tour succeeds; 100 % of the path inside the corridor; stops at the
  right doors; sensible video length.

Manual: browser click-through on the branch's dev server.

## Rollout

All work on branch `qbiq-design-json` (open PR). Commits per task. The frontend
redesign currently applied uncommitted in this worktree is committed first, as
its own commit, so later frontend tasks build on it.
