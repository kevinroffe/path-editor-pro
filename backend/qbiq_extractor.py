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
