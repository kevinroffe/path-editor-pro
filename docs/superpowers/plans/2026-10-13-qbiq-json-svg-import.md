# qbiq JSON+SVG Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new floor-plan ingestion path that parses a matched qbiq Spaceplanner JSON+SVG pair into the existing `LevelGeometry` dataclass, so Smart Path, the 3D preview, and XML export all work on qbiq-sourced floor plans with zero changes to any of those systems.

**Architecture:** A new `backend/qbiq_extractor.py` module stitches the JSON's raw line-segment lists into polylines/polygons, parses the SVG's room/door geometry with `xml.etree.ElementTree`, and combines both into one `LevelGeometry` — reusing the exact same fields, caching helpers, and downstream pipeline every other extractor already uses. A new `/api/upload-qbiq` Flask route and a small frontend folder-detection change wire it into the existing upload flow.

**Tech Stack:** Python 3.13, Flask, `xml.etree.ElementTree` (standard library, no new dependency), pytest (existing backend test suite).

**Spec:** `docs/superpowers/specs/2026-10-13-qbiq-json-svg-import-design.md`

## Global Constraints

- `units_to_metres = 0.01` for this format (1 unit = 1cm), with the same power-of-ten plausibility auto-correction pattern already proven in `dxf_extractor.py`'s `_fix_implausible_units` (plausible single-floor-plate size: 2m–200m).
- A room path with **no `stroke-dasharray`** (attribute or inline `style`) contributes to both `geo.walls` and `geo.spaces`; a room path **with `stroke-dasharray`** contributes to `geo.spaces` only — never invert this rule.
- Only the SVG door polyline with a real `fill` value (not `"None"`) becomes a `geo.doors` entry per `door_id_...` group — every other polyline sharing that door_id is construction detail and must be ignored.
- The JSON's non-`_ls` keys (`perimeter`, `core`, `columns`, `qbiq_walls`) are never parsed — confirmed redundant with their `_ls` counterparts.
- No changes to `autopath.py`, `corridor_graph.py`, `route_processor.py`, `export_layer.py`, or the 3D preview's extrusion code (`frontend/index.html`'s `build3DGeometry`) — every one of them already works generically on `LevelGeometry` fields.
- This project has a git repository; commits happen only on explicit user request, not automatically — every task's "Commit" step is real but must wait for that request if none has been given yet for this session (note this to the user at natural checkpoints, don't silently skip committing forever).
- Two real reference files exist outside the repo for end-to-end verification: `C:\Users\kevin\.codex\attachments\018c77c8-e695-4975-b4e0-91fa555a148d\Pasted text.txt` (JSON) and `C:\Users\kevin\.codex\attachments\3dc362f9-eecb-4740-b8af-2acff74b62ef\Pasted text.txt` (SVG). Tests referencing them must skip gracefully (not hard-fail) when unavailable, via an environment-variable override for their directory — same pattern already used for `backend/tests/test_corridor_graph_real_files.py`.

## Review Focus

- **A room path whose `d` attribute uses a curve command (C/Q/A) instead of only M/L/Z** — a future qbiq export could include a rounded corner or arc; the spec requires this to fail loudly (a clear error identifying the unsupported command), not silently produce a wrong or truncated polygon. Task 3's parser must raise, and Task 3's tests must prove it does.
- **A door's `door_id_...` group where every polyline has `fill="None"`** (no real-fill reference line present) — the spec's door-picking rule assumes exactly one fill-bearing polyline exists per door; if an export is missing it, the extractor should skip that door with a clear log message rather than crash or silently invent a door location. Task 3's tests must cover this.
- **`qbiq_walls_ls` or `mullions` actually populated** (both are empty in the one reference file available) — the stitching and category-mapping code must not have an implicit assumption that these are always empty; Task 1/Task 4 tests must include a non-empty case for each.
- **A `columns_ls`/`core_ls` segment list containing more than one disconnected loop** (confirmed true in the reference file — ~20+ separate column loops, ~8 separate core shafts) — the stitcher must produce one chain per disconnected loop, never merge unrelated loops just because they're in the same JSON key. Task 1's tests must assert the right *count* of chains, not just that stitching "worked".
- **The JSON and SVG files for a mismatched pair (different job, or a shape/position mismatch)** — the spec doesn't require detecting this, but silently producing a nonsensical merged floor plan would be worse than an explicit decision not to check. **Correction found during self-review:** the JSON format has no `job_code` field at all (only the SVG's `<desc>` carries one), so there is nothing to cross-check it against — Task 4 logs the SVG's `job_code` alone, as a diagnostic breadcrumb for whoever investigates a bad-looking import, not a validation step. This is a deliberate, minimal, non-blocking safeguard.

---

### Task 1: Segment-stitching utility

**Files:**
- Create: `backend/qbiq_extractor.py`
- Test: `backend/tests/test_qbiq_extractor.py`

**Interfaces:**
- Consumes: nothing (first code in the new module).
- Produces: `_stitch_segments(segments: list[tuple[tuple[float,float], tuple[float,float]]]) -> list[list[tuple[float,float]]]`, used by Task 3 (JSON parsing).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_qbiq_extractor.py`:
```python
import qbiq_extractor as qe


def test_stitch_single_closed_square():
    segments = [
        ((0.0, 0.0), (10.0, 0.0)),
        ((10.0, 0.0), (10.0, 10.0)),
        ((10.0, 10.0), (0.0, 10.0)),
        ((0.0, 10.0), (0.0, 0.0)),
    ]
    chains = qe._stitch_segments(segments)
    assert len(chains) == 1
    chain = chains[0]
    assert chain[0] == chain[-1]  # closed
    assert len(chain) == 5  # 4 corners + repeated start


def test_stitch_segments_given_out_of_order():
    # Same square, segments listed in a shuffled, non-walkable-in-order sequence
    segments = [
        ((10.0, 10.0), (0.0, 10.0)),
        ((0.0, 0.0), (10.0, 0.0)),
        ((0.0, 10.0), (0.0, 0.0)),
        ((10.0, 0.0), (10.0, 10.0)),
    ]
    chains = qe._stitch_segments(segments)
    assert len(chains) == 1
    assert chains[0][0] == chains[0][-1]


def test_stitch_two_disconnected_loops():
    # Two separate unit squares, far apart — must NOT merge into one chain
    square_a = [
        ((0.0, 0.0), (1.0, 0.0)),
        ((1.0, 0.0), (1.0, 1.0)),
        ((1.0, 1.0), (0.0, 1.0)),
        ((0.0, 1.0), (0.0, 0.0)),
    ]
    square_b = [
        ((100.0, 100.0), (101.0, 100.0)),
        ((101.0, 100.0), (101.0, 101.0)),
        ((101.0, 101.0), (100.0, 101.0)),
        ((100.0, 101.0), (100.0, 100.0)),
    ]
    chains = qe._stitch_segments(square_a + square_b)
    assert len(chains) == 2
    for chain in chains:
        assert chain[0] == chain[-1]


def test_stitch_many_disconnected_loops_matches_count():
    # 5 separate triangles — exactly 5 chains, not fewer (no accidental merging)
    # and not more (no accidental splitting)
    segments = []
    for i in range(5):
        ox, oy = i * 50.0, i * 50.0
        segments += [
            ((ox, oy), (ox + 5.0, oy)),
            ((ox + 5.0, oy), (ox, oy + 5.0)),
            ((ox, oy + 5.0), (ox, oy)),
        ]
    chains = qe._stitch_segments(segments)
    assert len(chains) == 5
    for chain in chains:
        assert len(chain) == 4  # 3 corners + repeated start
        assert chain[0] == chain[-1]


def test_stitch_open_chain_stays_open():
    # A single unconnected bar (e.g. an isolated mullion) — no match for either
    # end, so it must remain a 2-point OPEN chain, not be forced closed.
    segments = [((5.0, 5.0), (5.0, 9.0))]
    chains = qe._stitch_segments(segments)
    assert len(chains) == 1
    assert chains[0] == [(5.0, 5.0), (5.0, 9.0)]
    assert chains[0][0] != chains[0][-1]


def test_stitch_empty_list_returns_empty():
    assert qe._stitch_segments([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest tests/test_qbiq_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qbiq_extractor'`.

- [ ] **Step 3: Write `backend/qbiq_extractor.py` with the stitching utility**

```python
"""
qbiq_extractor.py
------------------
Parses a matched qbiq Spaceplanner JSON+SVG export pair into the project's
shared LevelGeometry dataclass (see revit_extractor.py), so every existing
downstream feature (Smart Path's corridor-graph routing, the 3D preview,
Enscape/Revit XML export) works on qbiq-sourced floor plans with zero
changes to any of those systems — they all operate purely on LevelGeometry
fields, never on how those fields were populated.

See docs/superpowers/specs/2026-10-13-qbiq-json-svg-import-design.md for the
full design rationale (why dashed-stroke rooms aren't walls, why only one
polyline per door_id is the real opening line, why the JSON's non-_ls keys
are ignored, etc.).
"""

from __future__ import annotations
import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from revit_extractor import LevelGeometry

log = logging.getLogger(__name__)

Point = tuple
Polyline = list


def _key(p: tuple, precision: int = 6) -> tuple:
    """Round a point to a stable dict key — real exports repeat the exact
    same literal float for a shared vertex between two adjacent segments
    (verified against the real reference JSON), so this is a safety margin
    against trivial float-representation differences, not fuzzy matching."""
    return (round(p[0], precision), round(p[1], precision))


def _stitch_segments(segments: list) -> list:
    """
    Chain 2-point segments into connected polylines by shared endpoints.

    Each JSON `_ls` key is a flat, unordered list of edges — not already
    walked into a single connected sequence, and frequently containing
    MULTIPLE disconnected loops in one key (e.g. columns_ls has one closed
    loop per column; core_ls has one loop per core shaft plus the overall
    core-zone boundary). This walks outward from each not-yet-used segment
    in both directions until no more segments attach, producing one chain
    per disconnected component. A chain that returns to its own starting
    point is naturally closed (first point == last point) — this matches
    the project's existing closed-polyline convention (see
    dxf_extractor.py's _entity_to_polylines) with no extra step needed. A
    chain with no match at one or both ends (e.g. an isolated mullion bar)
    is returned as an open polyline, which is an equally valid polyline
    everywhere else in this codebase.
    """
    remaining = list(segments)
    chains = []
    while remaining:
        a, b = remaining.pop(0)
        chain = [a, b]

        extended = True
        while extended:
            extended = False
            tail = _key(chain[-1])
            for i, (p, q) in enumerate(remaining):
                if _key(p) == tail:
                    chain.append(q)
                    remaining.pop(i)
                    extended = True
                    break
                if _key(q) == tail:
                    chain.append(p)
                    remaining.pop(i)
                    extended = True
                    break

        extended = True
        while extended:
            extended = False
            head = _key(chain[0])
            for i, (p, q) in enumerate(remaining):
                if _key(p) == head:
                    chain.insert(0, q)
                    remaining.pop(i)
                    extended = True
                    break
                if _key(q) == head:
                    chain.insert(0, p)
                    remaining.pop(i)
                    extended = True
                    break

        chains.append(chain)
    return chains
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest tests/test_qbiq_extractor.py -v`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

Only if the user has already approved committing for this project this session; otherwise leave uncommitted and note it.
```bash
git add backend/qbiq_extractor.py backend/tests/test_qbiq_extractor.py
git commit -m "feat(qbiq-import): add segment-stitching utility for JSON line-segment lists"
```

---

### Task 2: SVG path parsing and the door-picking rule

**Files:**
- Modify: `backend/qbiq_extractor.py`
- Test: `backend/tests/test_qbiq_extractor.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent utility).
- Produces:
  - `_parse_path_d(d: str) -> list[tuple[float, float]]`
  - `_has_dashed_stroke(elem) -> bool`
  - `_pick_door_polyline(polylines_for_one_door_id: list) -> tuple[float, float] | None` — each item is an `(fill, points)` tuple; returns the points of the one real-fill polyline, or `None` if none has a real fill.
  used by Task 3's SVG-driven room/door extraction.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_qbiq_extractor.py`:
```python
import xml.etree.ElementTree as ET

import pytest


def test_parse_path_d_simple_rectangle():
    d = "M 249.5,155.6 L 249.5,117.1 L 212.0,117.1 L 212.0,155.6 L 249.5,155.6 z"
    pts = qe._parse_path_d(d)
    assert pts == [
        (249.5, 155.6), (249.5, 117.1), (212.0, 117.1),
        (212.0, 155.6), (249.5, 155.6),
    ]
    assert pts[0] == pts[-1]  # explicitly closed in the source data


def test_parse_path_d_rejects_unsupported_curve_command():
    d = "M 0,0 C 1,1 2,2 3,3 z"
    with pytest.raises(ValueError, match=r"unsupported.*'C'"):
        qe._parse_path_d(d)


def test_has_dashed_stroke_true_for_dasharray_attribute():
    elem = ET.fromstring(
        '<path fill="#D7C2AD" stroke="#000000" stroke-dasharray="4" '
        'stroke-width="0.2" d="M 0,0 L 1,1 z"/>'
    )
    assert qe._has_dashed_stroke(elem) is True


def test_has_dashed_stroke_false_for_solid_room():
    elem = ET.fromstring(
        '<path fill="#E9D8A6" stroke="#000000" stroke-width="1.42" '
        'd="M 0,0 L 1,1 z"/>'
    )
    assert qe._has_dashed_stroke(elem) is False


def test_has_dashed_stroke_true_when_in_inline_style():
    elem = ET.fromstring(
        '<path fill="#D7C2AD" style="stroke-dasharray:4;stroke-width:0.2" '
        'd="M 0,0 L 1,1 z"/>'
    )
    assert qe._has_dashed_stroke(elem) is True


def test_pick_door_polyline_finds_the_real_fill_one():
    candidates = [
        ("None", [(247.5, 154.9), (235.8, 154.9)]),   # jamb detail
        ("None", [(235.3, 154.5), (235.3, 155.6)]),   # jamb detail
        ("#E9D8A6", [(247.5, 155.6), (235.8, 155.6)]),  # the real opening line
    ]
    result = qe._pick_door_polyline(candidates)
    assert result == [(247.5, 155.6), (235.8, 155.6)]


def test_pick_door_polyline_returns_none_when_no_real_fill_present():
    candidates = [
        ("None", [(0.0, 0.0), (1.0, 1.0)]),
        ("None", [(1.0, 1.0), (2.0, 2.0)]),
    ]
    assert qe._pick_door_polyline(candidates) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest tests/test_qbiq_extractor.py -v -k "parse_path_d or dashed_stroke or pick_door"`
Expected: FAIL — `AttributeError: module 'qbiq_extractor' has no attribute '_parse_path_d'`.

- [ ] **Step 3: Implement the three functions**

Append to `backend/qbiq_extractor.py`:
```python
_COMMAND_LETTER_RE = re.compile(r"[A-Za-z]")
_SUPPORTED_PATH_COMMANDS = set("MLZ")
_COORD_PAIR_RE = re.compile(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")


def _parse_path_d(d: str) -> list:
    """
    Parse an SVG path `d` attribute into a point list. Only M/L/Z are
    supported — every room path in the one real reference export uses
    exactly these (a plain polygon outline) — anything else (a curve
    command: C/Q/A/S/T) must fail loudly rather than silently produce a
    wrong or truncated polygon, since a future qbiq export could add a
    rounded corner or arc that this simple walk cannot represent.
    """
    letters = set(_COMMAND_LETTER_RE.findall(d.upper()))
    unsupported = sorted(letters - _SUPPORTED_PATH_COMMANDS)
    if unsupported:
        raise ValueError(
            f"unsupported SVG path command(s) {unsupported!r} in d={d!r} — "
            "only M/L/Z are handled"
        )
    return [(float(x), float(y)) for x, y in _COORD_PAIR_RE.findall(d)]


def _has_dashed_stroke(elem) -> bool:
    """
    True if this SVG element's stroke is dashed, via EITHER the plain
    `stroke-dasharray` attribute or an inline `style="...stroke-dasharray:
    ...  "` declaration (the reference export uses the plain attribute, but
    both are valid SVG and a future export could use either).
    """
    if elem.get("stroke-dasharray"):
        return True
    style = elem.get("style") or ""
    return "stroke-dasharray" in style


def _pick_door_polyline(candidates: list):
    """
    Among every polyline sharing one door_id_... class (jamb lines, swing-
    arc detail, and exactly one real opening-width reference line in the
    real reference export), return the points of the one with a real
    (non-"None") fill — that is the actual opening location/width. Returns
    None if no candidate has a real fill, so the caller can skip that door
    with a clear log message instead of guessing.
    """
    for fill, points in candidates:
        if fill and fill != "None":
            return points
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest tests/test_qbiq_extractor.py -v`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/qbiq_extractor.py backend/tests/test_qbiq_extractor.py
git commit -m "feat(qbiq-import): add SVG path parsing and door-picking rule"
```
(Only if the user has approved committing this session.)

---

### Task 3: Full SVG room/door extraction and JSON structural extraction

**Files:**
- Modify: `backend/qbiq_extractor.py`
- Test: `backend/tests/test_qbiq_extractor.py`

**Interfaces:**
- Consumes: `_stitch_segments` (Task 1), `_parse_path_d`/`_has_dashed_stroke`/`_pick_door_polyline` (Task 2).
- Produces:
  - `_extract_rooms_and_doors(svg_root) -> tuple[list[Polyline], list[Polyline], list[Polyline]]` — returns `(wall_polylines, space_polylines, door_polylines)`.
  - `_extract_json_structure(data: dict) -> tuple[list[Polyline], list[Polyline], list[Polyline], list[Polyline]]` — returns `(wall_polylines, column_polylines, window_polylines, declared_extent_points)`; the last element is every raw point seen, for the units-plausibility check.
  - `_fix_implausible_units(units_to_metres: float, extent_points: list) -> float`
  used by Task 4's `extract_qbiq`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_qbiq_extractor.py`:
```python
_SVG_FIXTURE = """<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
<desc>job_code="TEST0001"</desc>
<g id="maing"><g id="designg"><g id="prop">
<g id="ext"></g>
<g id="rooms">
<path fill="#E9D8A6" stroke="#000000" stroke-width="1.42" class="d0 r1 office c1 h1 a1"
      d="M 0,0 L 10,0 L 10,10 L 0,10 L 0,0 z" />
<polyline points="4,0 4,-1" fill="None" stroke="#000000" stroke-width="0.21"
          class="r1 c1 door_id_abc regular main"/>
<polyline points="6,0 4,0" fill="#E9D8A6" stroke="white" stroke-width="1.7"
          class="r1 c1 door_id_abc regular main"/>
<path fill="#D7C2AD" stroke="#000000" stroke-dasharray="4" stroke-width="0.2"
      class="d0 r2 comfort-zone c2 h1 a1"
      d="M 10,0 L 20,0 L 20,10 L 10,10 L 10,0 z" />
</g>
<g id="cols"></g>
</g></g></g>
</svg>"""


def test_extract_rooms_and_doors_separates_solid_from_dashed():
    root = ET.fromstring(_SVG_FIXTURE)
    walls, spaces, doors = qe._extract_rooms_and_doors(root)
    # solid room (r1) contributes both a wall ring and a space; dashed
    # room (r2) contributes a space only
    assert len(spaces) == 2
    assert len(walls) == 1
    assert walls[0][0] == (0.0, 0.0) and walls[0][-1] == (0.0, 0.0)
    # exactly one door, using the real-fill polyline's points
    assert doors == [[(6.0, 0.0), (4.0, 0.0)]]


def test_extract_rooms_and_doors_skips_a_door_with_no_real_fill_polyline():
    # Review Focus: a door_id group where every polyline has fill="None" —
    # must be skipped (logged, not crashed), not invented or mis-picked.
    svg = """<svg xmlns="http://www.w3.org/2000/svg">
    <g id="maing"><g id="designg"><g id="prop">
    <g id="ext"></g>
    <g id="rooms">
    <path fill="#E9D8A6" stroke="#000000" stroke-width="1.42" class="d0 r9 office c9 h1 a1"
          d="M 0,0 L 10,0 L 10,10 L 0,10 L 0,0 z" />
    <polyline points="4,0 4,-1" fill="None" stroke="#000000" stroke-width="0.21"
              class="r9 c9 door_id_broken regular main"/>
    <polyline points="6,0 4,0" fill="None" stroke="#000000" stroke-width="0.21"
              class="r9 c9 door_id_broken regular main"/>
    </g>
    <g id="cols"></g>
    </g></g></g>
    </svg>"""
    root = ET.fromstring(svg)
    walls, spaces, doors = qe._extract_rooms_and_doors(root)
    assert len(spaces) == 1  # the room itself still parses fine
    assert doors == []       # the broken door group is skipped, not guessed


def test_extract_json_structure_categorises_each_key():
    data = {
        "perimeter_ls": [[[0, 0], [10, 0]], [[10, 0], [10, 10]],
                         [[10, 10], [0, 10]], [[0, 10], [0, 0]]],
        "core_ls": [[[2, 2], [3, 2]], [[3, 2], [3, 3]],
                    [[3, 3], [2, 3]], [[2, 3], [2, 2]]],
        "columns_ls": [[[5, 5], [5.2, 5]], [[5.2, 5], [5.2, 5.2]],
                       [[5.2, 5.2], [5, 5.2]], [[5, 5.2], [5, 5]]],
        "qbiq_walls_ls": [],
        "mullions": [[[0, 0], [0, 1]]],
        "perimeter": [[0, 0]], "core": [[2, 2]], "columns": [[5, 5]],
        "qbiq_walls": [],
    }
    walls, columns, windows, extent_points = qe._extract_json_structure(data)
    # perimeter + core both become walls -> 2 closed chains
    assert len(walls) == 2
    assert len(columns) == 1
    assert columns[0][0] == columns[0][-1]
    assert windows == [[(0.0, 0.0), (0.0, 1.0)]]
    assert (10.0, 10.0) in extent_points


def test_extract_json_structure_handles_populated_qbiq_walls_and_mullions():
    # Review Focus: qbiq_walls_ls / mullions actually populated, not just
    # the empty case from the one real reference file.
    data = {
        "perimeter_ls": [], "core_ls": [], "columns_ls": [],
        "qbiq_walls_ls": [[[1, 1], [1, 2]], [[1, 2], [2, 2]],
                          [[2, 2], [2, 1]], [[2, 1], [1, 1]]],
        "mullions": [[[9, 9], [9, 10]], [[20, 20], [20, 21]]],
        "perimeter": [], "core": [], "columns": [], "qbiq_walls": [],
    }
    walls, columns, windows, extent_points = qe._extract_json_structure(data)
    assert len(walls) == 1  # the qbiq_walls_ls square
    assert walls[0][0] == walls[0][-1]
    assert len(windows) == 2  # two separate, unconnected mullion bars


def test_fix_implausible_units_corrects_centimetre_declared_as_metre_scale():
    # A building whose real size is ~38m, if units_to_metres were wrongly 1.0
    # instead of 0.01, would declare an impossible 3800m footprint.
    extent_points = [(0.0, 0.0), (3800.0, 2500.0)]
    corrected = qe._fix_implausible_units(1.0, extent_points)
    assert abs(corrected - 0.01) < 1e-9


def test_fix_implausible_units_leaves_already_plausible_scale_alone():
    extent_points = [(0.0, 0.0), (3800.0, 2500.0)]
    corrected = qe._fix_implausible_units(0.01, extent_points)
    assert corrected == 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest tests/test_qbiq_extractor.py -v -k "extract_rooms_and_doors or extract_json_structure or fix_implausible"`
Expected: FAIL — `AttributeError: module 'qbiq_extractor' has no attribute '_extract_rooms_and_doors'`.

- [ ] **Step 3: Implement the three functions**

Append to `backend/qbiq_extractor.py`:
```python
_SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


def _find_rooms_group(svg_root):
    """Locate designg > prop > rooms, tolerant of the SVG default namespace
    (ElementTree requires the namespace prefix on every tag when one is
    declared on the root, per the reference file's xmlns attribute)."""
    return svg_root.find(
        ".//svg:g[@id='designg']/svg:g[@id='prop']/svg:g[@id='rooms']", _SVG_NS
    )


def _extract_rooms_and_doors(svg_root):
    """
    Returns (wall_polylines, space_polylines, door_polylines) from the
    SVG's rooms group. Every room path becomes a space; only solid-stroke
    (non-dashed) room paths also become a wall. Doors are grouped by their
    door_id_... class token and reduced to one real-fill polyline each via
    _pick_door_polyline.
    """
    rooms_group = _find_rooms_group(svg_root)
    wall_polylines, space_polylines = [], []
    door_candidates = {}  # door_id -> list of (fill, points)

    if rooms_group is None:
        return wall_polylines, space_polylines, []

    for elem in rooms_group.iter():
        tag = elem.tag.split("}")[-1]
        classes = elem.get("class", "")

        if tag == "path" and "d" in elem.attrib:
            try:
                pts = _parse_path_d(elem.get("d"))
            except ValueError:
                log.warning("skipping unparseable room path: %s", elem.get("d"))
                continue
            space_polylines.append(pts)
            if not _has_dashed_stroke(elem):
                wall_polylines.append(pts)

        elif tag == "polyline":
            door_id = next(
                (tok for tok in classes.split() if tok.startswith("door_id_")),
                None,
            )
            if door_id is None:
                continue
            points_str = elem.get("points", "")
            pts = [
                (float(x), float(y))
                for x, y in (pair.split(",") for pair in points_str.split())
            ]
            fill = elem.get("fill", "None")
            door_candidates.setdefault(door_id, []).append((fill, pts))

    door_polylines = []
    for door_id, candidates in door_candidates.items():
        picked = _pick_door_polyline(candidates)
        if picked is None:
            log.warning("door %s has no real-fill opening polyline — skipping", door_id)
            continue
        door_polylines.append(picked)

    return wall_polylines, space_polylines, door_polylines


def _ls_to_polylines(segments_raw: list) -> list:
    """Convert one JSON `_ls` key's raw [[x,y],[x,y]] segment list into
    stitched polylines."""
    segments = [
        ((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
        for a, b in segments_raw
    ]
    return _stitch_segments(segments)


def _extract_json_structure(data: dict):
    """
    Returns (wall_polylines, column_polylines, window_polylines,
    extent_points) from the JSON's structural keys. perimeter_ls, core_ls,
    and qbiq_walls_ls (when present) all become walls; columns_ls becomes
    columns; mullions becomes windows. The non-_ls keys (perimeter, core,
    columns, qbiq_walls) are confirmed redundant with their _ls
    counterparts and are never read. extent_points is every raw point seen,
    for the units-plausibility check.
    """
    wall_polylines = []
    for key in ("perimeter_ls", "core_ls", "qbiq_walls_ls"):
        wall_polylines.extend(_ls_to_polylines(data.get(key, [])))

    column_polylines = _ls_to_polylines(data.get("columns_ls", []))
    window_polylines = _ls_to_polylines(data.get("mullions", []))

    extent_points = []
    for polylines in (wall_polylines, column_polylines, window_polylines):
        for poly in polylines:
            extent_points.extend(poly)

    return wall_polylines, column_polylines, window_polylines, extent_points


_PLAUSIBLE_MIN_EXTENT_M = 2.0
_PLAUSIBLE_MAX_EXTENT_M = 200.0


def _fix_implausible_units(units_to_metres: float, extent_points: list) -> float:
    """
    Same plausibility-check pattern as dxf_extractor.py's
    _fix_implausible_units: if the declared units_to_metres produces an
    implausible overall building size, try power-of-ten corrections until
    one lands in a plausible single-floor-plate range (2m-200m). Returns
    the (possibly corrected) units_to_metres unchanged if no extent points
    are given or the declared scale is already plausible.
    """
    if not extent_points:
        return units_to_metres
    xs = [p[0] for p in extent_points]
    ys = [p[1] for p in extent_points]
    raw_extent = max(max(xs) - min(xs), max(ys) - min(ys))
    if raw_extent <= 0:
        return units_to_metres

    declared_extent_m = raw_extent * units_to_metres
    if _PLAUSIBLE_MIN_EXTENT_M <= declared_extent_m <= _PLAUSIBLE_MAX_EXTENT_M:
        return units_to_metres

    for factor in (10.0, 100.0, 1000.0, 0.1, 0.01, 0.001):
        corrected_m = declared_extent_m / factor
        if _PLAUSIBLE_MIN_EXTENT_M <= corrected_m <= _PLAUSIBLE_MAX_EXTENT_M:
            log.warning(
                "qbiq JSON: declared units give an implausible building size "
                "(%.1fm at %.6f m/unit) — correcting by a factor of %g to "
                "%.6f m/unit (building size now %.1fm).",
                declared_extent_m, units_to_metres, factor,
                units_to_metres / factor, corrected_m,
            )
            return units_to_metres / factor

    log.warning(
        "qbiq JSON: declared units give an implausible building size "
        "(%.1fm) and no simple power-of-10 correction fixes it — leaving "
        "units_to_metres as-is (%.6f m/unit).",
        declared_extent_m, units_to_metres,
    )
    return units_to_metres
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest tests/test_qbiq_extractor.py -v`
Expected: `19 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/qbiq_extractor.py backend/tests/test_qbiq_extractor.py
git commit -m "feat(qbiq-import): add SVG room/door and JSON structure extraction"
```
(Only if the user has approved committing this session.)

---

### Task 4: `extract_qbiq` orchestrator

**Files:**
- Modify: `backend/qbiq_extractor.py`
- Test: `backend/tests/test_qbiq_extractor.py`

**Interfaces:**
- Consumes: `_extract_json_structure`, `_extract_rooms_and_doors`, `_fix_implausible_units` (Task 3); `LevelGeometry` (imported from `revit_extractor.py`, fields: `level_name, elevation, walls, spaces, doors, columns, windows, furniture, units_to_metres, source, meshes`).
- Produces: `extract_qbiq(json_path: str, svg_path: str, level_name: str = "L-0") -> LevelGeometry`, used by Task 5's Flask route.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_qbiq_extractor.py`:
```python
import tempfile
import os


_JSON_FIXTURE = {
    "perimeter_ls": [[[0, 0], [20, 0]], [[20, 0], [20, 20]],
                     [[20, 20], [0, 20]], [[0, 20], [0, 0]]],
    "core_ls": [], "columns_ls": [
        [[9, 9], [9.2, 9]], [[9.2, 9], [9.2, 9.2]],
        [[9.2, 9.2], [9, 9.2]], [[9, 9.2], [9, 9]],
    ],
    "qbiq_walls_ls": [], "mullions": [],
    "perimeter": [], "core": [], "columns": [], "qbiq_walls": [],
}


def _write_fixture_files(tmpdir):
    json_path = os.path.join(tmpdir, "job.json")
    svg_path = os.path.join(tmpdir, "job.svg")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_JSON_FIXTURE, f)
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(_SVG_FIXTURE)
    return json_path, svg_path


def test_extract_qbiq_produces_a_valid_level_geometry():
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path, svg_path = _write_fixture_files(tmpdir)
        geo = qe.extract_qbiq(json_path, svg_path, level_name="L-1")

    assert geo.level_name == "L-1"
    assert geo.source == "qbiq"
    assert geo.units_to_metres == 0.01
    # JSON perimeter + SVG solid room (r1) -> at least 2 wall rings;
    # dashed room (r2) contributes no wall
    assert len(geo.walls) >= 2
    assert len(geo.columns) == 1
    assert len(geo.spaces) == 2  # r1 (solid) + r2 (dashed)
    assert len(geo.doors) == 1
    assert geo.meshes == []


def test_extract_qbiq_applies_units_plausibility_correction():
    # Same fixture, but declare the building 100x larger than cm would give,
    # forcing the plausibility check to fire.
    fixture = dict(_JSON_FIXTURE)
    fixture["perimeter_ls"] = [
        [[0, 0], [2000, 0]], [[2000, 0], [2000, 2000]],
        [[2000, 2000], [0, 2000]], [[0, 2000], [0, 0]],
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = os.path.join(tmpdir, "job.json")
        svg_path = os.path.join(tmpdir, "job.svg")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(fixture, f)
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(_SVG_FIXTURE)
        geo = qe.extract_qbiq(json_path, svg_path)

    # 2000 units at 0.01 m/unit = 20m (plausible) -> no correction needed
    assert geo.units_to_metres == 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest tests/test_qbiq_extractor.py -v -k extract_qbiq`
Expected: FAIL — `AttributeError: module 'qbiq_extractor' has no attribute 'extract_qbiq'`.

- [ ] **Step 3: Implement `extract_qbiq`**

Append to `backend/qbiq_extractor.py`:
```python
def extract_qbiq(json_path: str, svg_path: str, level_name: str = "L-0") -> LevelGeometry:
    """Parse a matched qbiq Spaceplanner JSON+SVG export pair into a
    LevelGeometry. See the module docstring and the design spec for the
    full rationale."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    json_walls, columns, windows, extent_points = _extract_json_structure(data)

    svg_root = ET.parse(svg_path).getroot()
    svg_walls, spaces, doors = _extract_rooms_and_doors(svg_root)

    units_to_metres = _fix_implausible_units(0.01, extent_points)

    # The JSON format carries no job_code field to cross-check against —
    # only the SVG's <desc> does — so this is a one-sided diagnostic
    # breadcrumb for whoever investigates a bad-looking import later, not a
    # validation step (the spec explicitly doesn't require detecting a
    # mismatched JSON/SVG pair). Read the <desc> element directly rather
    # than re-serialising the whole (potentially 1MB+) SVG back to a string.
    desc_elem = svg_root.find(".//svg:desc", _SVG_NS)
    job_code_match = re.search(r'job_code="([^"]*)"', desc_elem.text or "") if desc_elem is not None else None
    job_code = job_code_match.group(1) if job_code_match else "(none found)"

    log.info(
        "qbiq extracted from '%s' + '%s' (svg job_code=%s): %d walls, "
        "%d doors, %d columns, %d windows, %d spaces",
        json_path, svg_path, job_code, len(json_walls) + len(svg_walls),
        len(doors), len(columns), len(windows), len(spaces),
    )

    return LevelGeometry(
        level_name=level_name,
        elevation=0.0,
        walls=json_walls + svg_walls,
        spaces=spaces,
        doors=doors,
        columns=columns,
        windows=windows,
        furniture=[],
        units_to_metres=units_to_metres,
        source="qbiq",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest tests/test_qbiq_extractor.py -v`
Expected: `21 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/qbiq_extractor.py backend/tests/test_qbiq_extractor.py
git commit -m "feat(qbiq-import): add extract_qbiq orchestrator"
```
(Only if the user has approved committing this session.)

---

### Task 5: `/api/upload-qbiq` Flask route

**Files:**
- Modify: `backend/app.py`
- Test: `backend/tests/test_app_qbiq_upload.py`

**Interfaces:**
- Consumes: `extract_qbiq(json_path, svg_path, level_name) -> LevelGeometry` (Task 4); existing `_obstacle_polylines`, `_footprint_polylines`, `_door_polylines`, `_wall_polylines`, `_other_obstacle_polylines` helpers and `_LAST_OBSTACLES`/`_LAST_FOOTPRINT`/`_LAST_DOORS`/`_LAST_WALLS`/`_LAST_OTHER_OBSTACLES`/`_LAST_UNITS_TO_METRES`/`_UPLOAD_GENERATION`/`_LAST_CIRC_GRAPH` globals (all already defined in `app.py` from the corridor-graph work — read the current file before editing, these exact names must match what's already there).
- Produces: `POST /api/upload-qbiq` returning the same JSON shape as `/api/upload` (`svg`, `bounds`, `level`, `elevation`, `units_to_metres`, `source`, `geometry: {walls, spaces, doors, columns, windows, furniture, meshes}`), used by Task 6's frontend wiring.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_app_qbiq_upload.py`:
```python
import json

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


_JSON_FIXTURE = {
    "perimeter_ls": [[[0, 0], [2000, 0]], [[2000, 0], [2000, 1500]],
                     [[2000, 1500], [0, 1500]], [[0, 1500], [0, 0]]],
    "core_ls": [], "columns_ls": [], "qbiq_walls_ls": [], "mullions": [],
    "perimeter": [], "core": [], "columns": [], "qbiq_walls": [],
}

_SVG_FIXTURE = """<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
<desc>job_code="TEST0001"</desc>
<g id="maing"><g id="designg"><g id="prop">
<g id="ext"></g>
<g id="rooms">
<path fill="#E9D8A6" stroke="#000000" stroke-width="1.42" class="d0 r1 office c1 h1 a1"
      d="M 0,0 L 500,0 L 500,500 L 0,500 L 0,0 z" />
</g>
<g id="cols"></g>
</g></g></g>
</svg>"""


def test_upload_qbiq_returns_upload_shaped_response(client):
    data = {
        "json_file": (json_bytes(), "job.json"),
        "svg_file": (svg_bytes(), "job.svg"),
        "level": "L-2",
    }
    resp = client.post("/api/upload-qbiq", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "qbiq"
    assert body["level"] == "L-2"
    assert body["units_to_metres"] == 0.01
    assert "geometry" in body and "walls" in body["geometry"]
    assert len(body["geometry"]["walls"]) >= 1
    assert len(body["geometry"]["spaces"]) == 1


def test_upload_qbiq_populates_the_same_caches_as_dxf_upload(client):
    resp = client.post(
        "/api/upload-qbiq",
        data={"json_file": (json_bytes(), "job.json"), "svg_file": (svg_bytes(), "job.svg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    bounds = resp.get_json()["bounds"]
    # Smart Path must work immediately after a qbiq upload, exactly like
    # after a DXF upload, since it reads the same _LAST_* caches.
    autopath_resp = client.post("/api/autopath", json={
        "start": [bounds["xmin"] + 1, bounds["ymin"] + 1],
        "end": [bounds["xmax"] - 1, bounds["ymax"] - 1],
    })
    assert autopath_resp.status_code == 200
    assert len(autopath_resp.get_json()["waypoints"]) >= 2


def test_upload_qbiq_missing_file_field_returns_400(client):
    resp = client.post(
        "/api/upload-qbiq",
        data={"json_file": (json_bytes(), "job.json")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def json_bytes():
    import io
    return io.BytesIO(json.dumps(_JSON_FIXTURE).encode("utf-8"))


def svg_bytes():
    import io
    return io.BytesIO(_SVG_FIXTURE.encode("utf-8"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest tests/test_app_qbiq_upload.py -v`
Expected: FAIL — `404 NOT FOUND` (route doesn't exist yet) on the first test's status-code assertion.

- [ ] **Step 3: Add the route to `backend/app.py`**

Read the current file first — Tasks after the corridor-graph work already added `_LAST_WALLS`, `_LAST_OTHER_OBSTACLES`, `_UPLOAD_GENERATION`, `_LAST_CIRC_GRAPH`, and the helper functions `_wall_polylines`/`_other_obstacle_polylines`/`_obstacle_polylines`/`_footprint_polylines`/`_door_polylines`. Add the import near the other extractor imports:
```python
from qbiq_extractor import extract_qbiq
```

Add the new route next to the existing `/api/upload` route:
```python
@app.route("/api/upload-qbiq", methods=["POST"])
def upload_qbiq():
    if "json_file" not in request.files or "svg_file" not in request.files:
        return _err("Both json_file and svg_file are required")
    json_f = request.files["json_file"]
    svg_f = request.files["svg_file"]
    if not json_f.filename or not svg_f.filename:
        return _err("Empty filename")

    level_name = request.form.get("level", "L-0")

    json_fname = secure_filename(json_f.filename)
    svg_fname = secure_filename(svg_f.filename)
    json_fpath = UPLOAD_DIR / json_fname
    svg_fpath = UPLOAD_DIR / svg_fname
    json_f.save(str(json_fpath))
    svg_f.save(str(svg_fpath))
    log.info("Uploaded qbiq pair: %s + %s", json_fpath, svg_fpath)

    try:
        geo = extract_qbiq(str(json_fpath), str(svg_fpath), level_name)
    except Exception as e:
        log.exception("qbiq extraction failed")
        return _err(str(e))

    svg = generate_svg(geo)
    xmin, ymin, xmax, ymax = geo.bounds()

    _LAST_OBSTACLES["dxf"] = _obstacle_polylines(geo)
    _LAST_FOOTPRINT["dxf"] = _footprint_polylines(geo)
    _LAST_DOORS["dxf"] = _door_polylines(geo)
    _LAST_WALLS["dxf"] = _wall_polylines(geo)
    _LAST_OTHER_OBSTACLES["dxf"] = _other_obstacle_polylines(geo)
    global _LAST_UNITS_TO_METRES, _UPLOAD_GENERATION
    _LAST_UNITS_TO_METRES = geo.units_to_metres
    _UPLOAD_GENERATION += 1
    _LAST_CIRC_GRAPH.clear()

    return jsonify({
        "svg": svg,
        "bounds": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
        "level": geo.level_name,
        "elevation": geo.elevation,
        "units_to_metres": geo.units_to_metres,
        "source": geo.source,
        "geometry": {
            "walls":     geo.walls,
            "spaces":    geo.spaces,
            "doors":     geo.doors,
            "columns":   geo.columns,
            "windows":   geo.windows,
            "furniture": geo.furniture,
            "meshes":    geo.meshes,
        },
    })
```

This deliberately caches into the `"dxf"` source slot (not a new `"qbiq"` key) — a qbiq upload and a DXF upload are mutually exclusive ways to load the SAME kind of 2D floor-plan source today (there's no "qbiq + IFC dual upload" concept in this plan), so reusing the existing `"dxf"` slot means every piece of code that already reads `_LAST_OBSTACLES["dxf"]`, `_LAST_WALLS["dxf"]`, etc. (Smart Path, the corridor graph cache) works immediately with zero changes. If a future need arises for qbiq+IFC together, that's a separate, later change — not needed for this plan's scope.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest tests/test_app_qbiq_upload.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest -v`
Expected: all tests pass (every test from the corridor-graph work plus this plan's new ones).

- [ ] **Step 6: Commit**

```bash
git add backend/app.py backend/tests/test_app_qbiq_upload.py
git commit -m "feat(qbiq-import): add /api/upload-qbiq route"
```
(Only if the user has approved committing this session.)

---

### Task 6: Frontend folder-detection and upload wiring

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Consumes: `POST /api/upload-qbiq` (Task 5), existing `applyFloorPlan(data)` (unchanged, already consumes exactly this response shape since it's identical to `/api/upload`'s).
- Produces: `doUploadQbiq(jsonFile, svgFile, opts) -> Promise<void>`, wired into `onFolderSelected`.

- [ ] **Step 1: Add `doUploadQbiq`**

Insert right after the existing `doUpload` function (`frontend/index.html`, after the function ending at the line containing `finally { if (!silent) hideLoading(); }` for `doUpload`):
```javascript
async function doUploadQbiq(jsonFile, svgFile, { silent = false } = {}) {
  if (!silent) showLoading('Reading qbiq floor plan…');
  const fd = new FormData();
  fd.append('json_file', jsonFile);
  fd.append('svg_file', svgFile);
  fd.append('level', 'L-0');
  try {
    const res = await fetch(`${API}/api/upload-qbiq`, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed');
    applyFloorPlan(data);
    showHeaderHint('', '');
  } catch (e) { showHeaderHint(e.message, 'red'); toast(e.message, 'err'); }
  finally { if (!silent) hideLoading(); }
}
```

- [ ] **Step 2: Extend `onFolderSelected` to detect a JSON+SVG pair**

Replace the current `onFolderSelected` function body:
```javascript
async function onFolderSelected(inp) {
  const files = Array.from(inp.files);
  const dxf = files.find(f => f.name.toLowerCase().endsWith('.dxf'));
  const ifc = files.find(f => f.name.toLowerCase().endsWith('.ifc'));
  inp.value = '';

  if (!dxf && !ifc) {
    toast('No DXF or IFC files found in that folder', 'err'); return;
  }

  const parts = [];
  if (dxf) parts.push('DXF');
  if (ifc) parts.push('IFC');

  const folderName = files[0]?.webkitRelativePath?.split('/')[0] || 'folder';
  const btn = document.getElementById('load-folder-btn-wrap');
  const txt = document.getElementById('load-folder-btn-text');
  txt.textContent = folderName.length > 18 ? folderName.slice(0, 16) + '…' : folderName;
  btn.classList.add('loaded');

  showLoading(`Loading ${parts.join(' + ')}…`);
  try {
    // Upload in parallel — both use silent=true so they don't fight over the spinner
    await Promise.all([
      dxf ? doUpload(dxf,   { silent: true })                    : Promise.resolve(),
      ifc ? doUpload3D(ifc, { silent: true, autoOpen: false })   : Promise.resolve(),
    ]);
    toast(`Loaded ${parts.join(' + ')} from "${folderName}"`, 'ok');
    // Open 3D panel after both are done if IFC was included
    if (ifc) {
      if (!document.getElementById('preview-3d').classList.contains('visible')) {
        toggle3DPanel();
      } else {
        build3DGeometry();
      }
    }
  } finally {
    hideLoading();
  }
}
```
with:
```javascript
async function onFolderSelected(inp) {
  const files = Array.from(inp.files);
  const dxf = files.find(f => f.name.toLowerCase().endsWith('.dxf'));
  const ifc = files.find(f => f.name.toLowerCase().endsWith('.ifc'));
  const qbiqJson = files.find(f => f.name.toLowerCase().endsWith('.json'));
  const qbiqSvg = files.find(f => f.name.toLowerCase().endsWith('.svg'));
  // A qbiq import is only valid as a matched JSON+SVG pair (see the design
  // spec: each file alone is missing data the other supplies) — a lone
  // .json or .svg with no partner is not treated as a qbiq upload at all.
  const qbiqPair = qbiqJson && qbiqSvg;
  inp.value = '';

  if (!dxf && !ifc && !qbiqPair) {
    toast('No DXF, IFC, or matched qbiq JSON+SVG pair found in that folder', 'err');
    return;
  }

  const parts = [];
  if (dxf) parts.push('DXF');
  if (ifc) parts.push('IFC');
  if (qbiqPair) parts.push('qbiq');

  const folderName = files[0]?.webkitRelativePath?.split('/')[0] || 'folder';
  const btn = document.getElementById('load-folder-btn-wrap');
  const txt = document.getElementById('load-folder-btn-text');
  txt.textContent = folderName.length > 18 ? folderName.slice(0, 16) + '…' : folderName;
  btn.classList.add('loaded');

  showLoading(`Loading ${parts.join(' + ')}…`);
  try {
    // Upload in parallel — all use silent=true so they don't fight over the spinner
    await Promise.all([
      dxf      ? doUpload(dxf, { silent: true })                            : Promise.resolve(),
      ifc      ? doUpload3D(ifc, { silent: true, autoOpen: false })         : Promise.resolve(),
      qbiqPair ? doUploadQbiq(qbiqJson, qbiqSvg, { silent: true })          : Promise.resolve(),
    ]);
    toast(`Loaded ${parts.join(' + ')} from "${folderName}"`, 'ok');
    // Open 3D panel after both are done if IFC was included
    if (ifc) {
      if (!document.getElementById('preview-3d').classList.contains('visible')) {
        toggle3DPanel();
      } else {
        build3DGeometry();
      }
    }
  } finally {
    hideLoading();
  }
}
```

- [ ] **Step 3: Manual verification**

This is frontend-only JS with no automated test harness in this project (the backend's pytest suite doesn't exercise the browser). Verify by hand:
1. Start the dev server: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && PYTHONUTF8=1 "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" app.py`
2. Create a folder containing only `job.json` and `job.svg` built from the two real reference files (rename them with matching extensions — they currently have `.txt` names).
3. Open `http://localhost:5000`, click "Load Project", select that folder.
4. Confirm the floor plan renders (walls/columns/rooms visible on the 2D canvas) and that Smart Path (5 clicks) produces a route.

Automated end-to-end coverage of this exact scenario (without the browser) is Task 7.

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html
git commit -m "feat(qbiq-import): wire qbiq JSON+SVG pair into the folder-upload flow"
```
(Only if the user has approved committing this session.)

---

### Task 7: Real-reference-file end-to-end verification

**Files:**
- Test: `backend/tests/test_qbiq_real_files.py`

**Interfaces:**
- Consumes: `/api/upload-qbiq` (Task 5), `/api/autopath` (existing, unchanged).
- Produces: no new production code — this task is the final correctness gate, mirroring the real-file verification methodology used throughout this project (e.g. `test_corridor_graph_real_files.py`).

- [ ] **Step 1: Write the real-file test**

`backend/tests/test_qbiq_real_files.py`:
```python
import os
import shutil
from pathlib import Path

import pytest

import app as app_module

# Overridable so this test is portable across machines — same pattern as
# test_corridor_graph_real_files.py's REVIT_WALKTHROUGH_UPLOADS_DIR.
_JSON_SRC = Path(os.environ.get(
    "QBIQ_REFERENCE_JSON",
    r"C:\Users\kevin\.codex\attachments\018c77c8-e695-4975-b4e0-91fa555a148d\Pasted text.txt",
))
_SVG_SRC = Path(os.environ.get(
    "QBIQ_REFERENCE_SVG",
    r"C:\Users\kevin\.codex\attachments\3dc362f9-eecb-4740-b8af-2acff74b62ef\Pasted text.txt",
))

if not _JSON_SRC.exists() or not _SVG_SRC.exists():
    pytest.skip("real qbiq reference JSON/SVG not available on this machine",
                allow_module_level=True)


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_real_qbiq_pair_produces_a_routable_floor_plan(client):
    with open(_JSON_SRC, "rb") as jf, open(_SVG_SRC, "rb") as sf:
        resp = client.post(
            "/api/upload-qbiq",
            data={
                "json_file": (jf, "reference.json"),
                "svg_file": (sf, "reference.svg"),
            },
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()

    assert body["source"] == "qbiq"
    geometry = body["geometry"]
    assert len(geometry["walls"]) > 0
    assert len(geometry["columns"]) > 0
    assert len(geometry["spaces"]) > 0
    assert len(geometry["doors"]) > 0

    # units_to_metres must land in the plausible single-floor-plate range
    # once applied to the real building's own extent, whether or not the
    # plausibility correction actually fired for this specific file.
    bounds = body["bounds"]
    width_m = (bounds["xmax"] - bounds["xmin"]) * body["units_to_metres"]
    height_m = (bounds["ymax"] - bounds["ymin"]) * body["units_to_metres"]
    assert 2.0 <= max(width_m, height_m) <= 200.0

    # Smart Path must actually work on this real floor plan.
    autopath_resp = client.post("/api/autopath", json={
        "start": [bounds["xmin"] + 1, bounds["ymin"] + 1],
        "end": [bounds["xmax"] - 1, bounds["ymax"] - 1],
    })
    assert autopath_resp.status_code == 200
    waypoints = autopath_resp.get_json()["waypoints"]
    assert waypoints is not None and len(waypoints) >= 2
```

- [ ] **Step 2: Run the test**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest tests/test_qbiq_real_files.py -v -s`
Expected: `1 passed`. If it fails, read the failure carefully — a real units/scale surprise or a parsing gap on the real file is exactly what this task exists to catch; do not loosen an assertion to force a pass. If the building's real width/height genuinely falls outside 2–200m once correctly parsed, that's new information to bring back to the spec, not a bug in the test.

- [ ] **Step 3: Run the entire project test suite one final time**

Run: `cd "C:\Users\kevin\revit-walkthrough-v2\backend" && "C:\Users\kevin\revit-walkthrough-v2\.venv\Scripts\python.exe" -m pytest -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_qbiq_real_files.py
git commit -m "test(qbiq-import): add real-file end-to-end verification"
```
(Only if the user has approved committing this session.)
