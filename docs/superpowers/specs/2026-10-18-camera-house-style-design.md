# Camera House Style — Design

Date: 2026-10-18 · Branch: `qbiq-design-json` · Status: approved in conversation, awaiting spec review

## Problem

Kevin: "the path is still not very smooth, there is some head movement that looks not good." He supplied 60
hand-authored Enscape walkthrough paths (`xml learn.zip`, qbiq visualisation team, 2025) as the standard to
learn from. Measured against them (analysis scripts + numbers: scratchpad `xml-analysis/`, summary below),
our generated paths differ in ways that explain the complaint.

| Measure | Reference p10 / median / p90 | Ours (two real design JSONs) |
|---|---|---|
| Seconds between keyframes | 2.8 / **3.3** / 4.0 | 0.7–0.8 |
| Keyframes per video | 16 / 30 / 41 | 86–162 |
| Head-turn speed p90 (°/s) | 15 / **19** / 27 | ~175 (dwell turns at our 180°/s cap) |
| Head-turn speed median (°/s) | 5 / 9 / 13 | 5–22 |
| Look-direction reversals / min | 4 / **6** / 8 | 12–21 |
| Look vs travel angle, median (°) | 13 / **21** / 31 | 2–6 |
| Share of time looking > 30° off travel | 19% / 33% / 50% | 6–13% |
| Standing pans per video | 0 / 1 / 2, ~5 s, ~58° | 37–42 holds of ~0.4 s |
| Pan at the very start | 22% of paths | — |
| Walking speed (m/s) | 0.78 / **1.17** / 1.46 | 1.0 (2–2.9 when the video is set short) |
| Eye height (m) | **1.57** in all 60 | 1.75 |
| Pitch | 0 (≤1.4° in a few) | 0 |
| XML attributes | `easingInOut="1" shakyCam="0"` always | same |

Causes, ranked: (1) room-stop dwells snap the head at the 180°/s cap; (2) dense keyframes (every 0.7 s) bake
small yaw wobble into the path and give Enscape's easing many segments; (3) gaze is locked to the travel
direction except for snaps, while professionals look gently sideways while walking; (4) passing glances double
the left-right wobble; (5) eye height.

## Goal

Generated paths (Smart Path, Auto Tour, hand-clicked) look like the reference library: sparse eased keyframes,
slow deliberate head movement, gaze that leads turns and drifts toward rooms while walking, rare standing pans,
1.57 m eye height. The 3D preview shows the same motion Enscape will render.

## Non-goals

3D scene changes (ceiling, orbit navigation, realism) — separate spec (sub-project B). Changing routing
(corridor graph, stops placement, tour ordering). Pitch / vertical look.

## Design

### Keyframes first

Today: route → dense 30 fps frames (spline + look-ahead yaw + rate limiter + dwells + glances) → XML thins
frames to ~1/s. New: route → **sparse keyframe list** (the house style) → both outputs derive from it:

- **Enscape XML** writes exactly these keyframes.
- **Preview frames / JSON export** are produced by an **interpolator** that evaluates the keyframes the way
  Enscape does, so the preview is what Enscape renders.

New module `backend/camera_style.py` owns the style constants (from the data), the keyframe planner, the gaze
model and the interpolator. `route_processor.process_route` keeps its signature and `CameraFrame` output
(frontend and export callers unchanged) but becomes: plan keyframes → interpolate at fps. The old dwell,
glance and 180°/s machinery (`_insert_dwells`, `_dwell_frames`, `_scaled_dwells`, `_apply_glances`,
`_build_frames` look-ahead yaw, `_MAX_YAW_RATE_DEG_PER_SEC`, GLANCE_*, MAX_DWELL_FRACTION) is deleted.

### Style constants (from the reference data)

`EYE_HEIGHT_M = 1.57`, `KF_SPACING_S ≈ 3.3` (target; allowed 2.8–4.0), `KF_SPACING_M ≈ 3.2`,
`WALK_SPEED_MPS = 1.1` (allowed 0.8–1.45), `MAX_YAW_RATE_DPS = 25`, `MAX_REVERSALS_PER_MIN = 6`,
`ROOM_LOOK_MAX_DEG = 60` (gaze off travel when looking at a room), `TURN_LEAD_S ≈ 1.5` (gaze anticipates a turn),
`PAN_DURATION_S = 5`, `PAN_MAX_DEG = 90`, `MAX_PANS = 2`. Constants live in one place; tests assert the outputs,
not the constants.

### Keyframe planner

1. Smooth the route (existing centripetal Catmull-Rom with the user's smoothing and U-turn radius).
2. Walk it at `WALK_SPEED_MPS` (or the speed implied by the chosen video length, see Timing) and place
   keyframes every ~3.2 m / ~3.3 s, plus mandatory keyframes at: route start/end, sharp corners (heading change
   ≥ ~25° within a few metres), each room-look anchor, each cut boundary (as today: two closely-timed keyframes
   = a jump), and each waypoint that carries a user heading offset or time of day.
3. Each keyframe gets a position (on the smoothed path), a timestamp, a gaze yaw (below), optional `hour`.

### Gaze model

Gaze yaw at each keyframe = travel direction, with three deliberate additions, then two limits:

- **Lead into turns:** use the travel direction ~1.5 s ahead, so the head turns before the body at corners.
- **Room looks (replace stops/dwells and glances):** each stop on the route (room clicked in Smart Path or
  picked in Auto Tour) becomes a *walk-by look*: centred on the stop's position, the gaze eases toward the
  room's `look_at` over the stop's look time (`dwell_s`, per-type defaults unchanged: 3 / 2 / 1.5 s), capped
  at `ROOM_LOOK_MAX_DEG` off the travel direction, then eases back. The camera keeps walking (it may slow to
  0.8 m/s inside the look window). Passing glances are removed.
- **User heading offsets:** a waypoint's yaw offset is added at its keyframe and eased in/out across
  neighbouring keyframes (fixes the old `% 360` wrap spin by construction).
- **Limit — reversals:** if gaze direction alternates more than `MAX_REVERSALS_PER_MIN`, the smaller
  oscillations are flattened.
- **Limit — turn speed:** consecutive keyframes may not differ by more than `MAX_YAW_RATE_DPS × Δt`;
  violations reduce the gaze offset (never speed the head up). Yaw stays continuous (unwrapped).

### Standing pans (optional, off by default)

- **Per room:** a "stand & look" toggle on a stop row in Your Points. The camera stops at the stop point,
  pans toward the room over `PAN_DURATION_S` (≤ `PAN_MAX_DEG`), and continues. Encoded as two keyframes at the
  same position, like the references.
- **Start pan:** a Video Settings checkbox "Look around at start" (default off) — a ~5 s pan before walking.
- At most `MAX_PANS` per video; extra requests are ignored with a toast.

Wire format: the stop dict gains optional `pan: true`. Old 5-element waypoints keep working (pan absent = false).

### Timing

Video length stays user-controlled. Walking speed = path length ÷ (duration − pan time). The response carries
`warnings` when speed falls outside 0.8–1.45 m/s ("video too short — walking at 2.3 m/s; suggest 95 s"),
shown as a toast. Auto Tour's suggested duration uses 1.1 m/s + pans, rounded up to 5 s (replaces 1.0 m/s +
dwells). Easing: the preview applies ease-in at the start and ease-out at the end of the whole path (the most
likely meaning of `easingInOut="1"`; exact Enscape behaviour unverified — Kevin compares one render).

### Interpolator (preview + JSON export)

Position: centripetal Catmull-Rom through keyframe positions, parameterised by keyframe timestamps (with the
path-level ease). Gaze: the same spline over unwrapped yaw. Height constant 1.57 m. Output `CameraFrame`s at the
requested fps with `t` normalised as today. The frontend camera reads height from the frames' `z` (today it
hard-codes 1.75 m).

### Enscape XML

`<VideoPath version="1" easingInOut="1" shakyCam="0">`, one `<Keyframe>` per planned keyframe with
`timestampSeconds` on every keyframe, `Position` (x, 1.57, z — same axis mapping as today), `LookAt` unit
vector from yaw, `hour` where a time of day is set. No 200-cap thinning (a 10-minute path is ~180 keyframes).

## Error handling

Routes with < 2 points: unchanged behaviour. Degenerate segments (zero length) are skipped by the planner.
Invalid stops are already dropped by `_clean_stops`. Speed warnings never block export.

## Testing

- **Style conformance (both real design JSONs, Auto Tour of 5–8 rooms at the suggested duration):** seconds
  per keyframe within 2.8–4.0; head-turn speed p90 ≤ 27°/s and max ≤ 30°/s; reversals ≤ 8/min; median
  look-vs-travel 8–32°; eye height 1.57; speed 0.8–1.45 m/s; zero standing pans unless requested. Reuses the
  scratchpad analysis metrics, ported into a test helper.
- **Room looks:** for each stop, some keyframe within its look window has gaze within 15° of the room
  direction or exactly `ROOM_LOOK_MAX_DEG` off travel.
- **Preview = export:** interpolated frames at keyframe timestamps match the keyframes (position ≤ 1 cm, yaw
  ≤ 0.5°); frame-to-frame yaw change ≤ 25°/s ÷ fps + ε.
- **Pans:** requested pan → two same-position keyframes ~5 s apart, ≤ 90°; more than 2 → only 2.
- **Compatibility:** 4- and 5-element waypoints, cuts, time of day, `uturn_radius`, export JSON shape.
- Existing tests that assert dwell/glance mechanics are replaced by the above.

## Rollout

One branch (`qbiq-design-json`), local commits, Kevin renders one exported path in Enscape to confirm the
easing assumption before merge.
