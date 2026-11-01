# Designer Tour — Design

Date: 2026-11-01 · Branch: `main-entrance` · Status: Kevin said "go" (skipped questions); calls below are Claude's

## Why

Kevin: "learn more how to do the path and improve the path algo from this path file" — 313 hand-made Enscape
paths by qbiq's visualisation team (`C:\Users\kevin\Desktop\path learn`, one unreadable). The camera house
style (2026-10-18 spec) was learned from 60 of them and left routing alone. This round learns the *route*.

## What the data says

All 312 paths (scratchpad `learn/analyse.py`, same metrics as `tests/style_metrics.py`):

| Measure | p10 / median / p90 | Today's constant |
|---|---|---|
| Walking speed (m/s) | 0.55 / **0.95** / 1.26 | `WALK_SPEED_MPS = 1.1`, warn below 0.8 |
| Video length (s) | 46 / **104** / 123 (36 end at exactly 120) | length ÷ 1.1 |
| Route length (m) | 25 / **82** / 141 | — |
| Look vs travel (°) | 12 / 25 / 37 | test band 8–32 |
| Standing pan | 38 / **74** / 112 °, 2.5 / **4** / 6 s; 10% open with one | 5 s, ≤ 90° |
| Paths with ≥ 1 U-turn | 54% | — |

Five paths have their design JSON locally (Kraft, 1117 California, Gusto, Birmingham, 265 Franklin). Overlaid
on the plans (scratchpad `learn/pairs.py`, `learn/*.png`):

- **Closed rooms are never entered** (0 of 102 conference/office/storage/…); 28 of 34 conference rooms are
  looked at from the corridor while walking past.
- **Open highlight areas are walked into**: kitchens 3/5, comfort zones 7/17, reception 1/2, open workspace 3/11.
- **Wings are walked to their end and back** (the U-turns), seeing the rooms along them.
- **Highlights, not everything**: 70–120 m. Today's Auto Tour visits every picked room's door, giving 131–137 m
  with spurs on big plans and corridor-only 44–50 m on small ones.
- Designers start at the entrance (4 of 5; Franklin's detected entrance is in the core — Kevin can drag it).

A throwaway spike (`learn/spike2.py`) routing through open areas (minus furniture) and choosing targets by
"rooms seen per metre" within a 95 m budget took the share of designer keyframes within 2 m of our route from
36→96% (Gusto), 36→56% (Kraft), 81→85% (Birmingham), and cut 1117 from 131 m to 86 m at 77% cover. Franklin
walks the same ring loop mirrored (wrong start).

## Goal

A **Suggest a tour** button that fills the pick list with a designer-like tour: entrance → walk into the open
highlight areas → down wings, glancing at closed rooms on the way → about 100 s. Every route (suggested or
hand-picked) may walk through open areas around furniture instead of stopping at their edge. Camera constants
follow the 312-path numbers.

## Non-goals / anti-goals

- Not changing entrance detection, the 3D scene, or the hand-picked order (`room_ids` stays exact order).
- Anti-goal: a route through furniture, into a closed room, or a tour that is a list of spurs to doors.

## Design

1. **Walkable area.** `PlanModel.walkable` = corridor ∪ (open rooms not back-of-house, ≥ 8 m², minus furniture
   footprints grown by 0.35 m), keeping only pieces touching the corridor. All routing (graph, spline
   containment, click snapping) uses it; the corridor stays as drawn for display. Furniture footprints come
   from the stencil components' placement already used by the 3D scene (`matrix @ original_matrix3d`).
2. **Stop points.** An open room whose walkable part is ≥ 4 m² gets its stop *inside* (the walkable piece's
   pole of inaccessibility); its look target is the room's label point, and the camera skips a look whose target
   is within 1.5 m of where it stands. A closed room's route point is the corridor centre-line point nearest
   its door stop when that is within 2 m (no zig-zag to the door); the look still aims into the room.
3. **Suggested tour.** Greedy budgeted orienteering: targets = every non-back-of-house room's route point; a
   route *sees* a closed room when it passes within 3 m of its stop and an open room when it passes within 1 m
   of its inside stop. Value = sum of type weights of rooms seen (Reception 5, Kitchen 4, Open Space / Comfort
   Zone 3, Conference / Executive Office 2, other offices 1.5, Phone Booth / other 1). Repeatedly insert the
   target (at its best position) with the highest value gained per metre added, while the route stays within
   the budget (100 s × walking speed = 95 m). The answer is the room ids in route order: the chosen targets
   plus the rooms seen on the way, thinned so consecutive looks are ≥ 5 m apart (higher weight wins). The
   frontend puts these into the pick list and builds the route the normal way.
4. **Camera constants.** `WALK_SPEED_MPS` 0.95; the "video too long" warning below 0.6 m/s; `PAN_DURATION_S` 4.

## Testing

Synthetic plans for each rule; the five real pairs (skipped when files are absent): suggested route length
≤ budget + 10%, never inside a closed room, enters an open highlight when one is reachable, and the share of
designer keyframes within 2 m of the route is at least the spike's (Gusto ≥ 0.8, Kraft ≥ 0.5, Birmingham ≥ 0.75,
1117 ≥ 0.7). Existing camera style tests keep passing.
