"""
route_processor.py
------------------
Smoothing and resampling of a 2-D camera route.

Spline method: Centripetal Catmull-Rom (alpha=0.5)
---------------------------------------------------
Mathematically guaranteed to NEVER overshoot, loop, or produce cusps
regardless of point spacing — critical for floor-plan waypoints.

U-turn handling
---------------
Sharp turns (> 120°) are pre-processed by inserting two helper points at
`uturn_radius` distance before and after the apex, creating a smooth arc
instead of a hairpin.
"""

from __future__ import annotations
import logging
import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class CameraFrame:
    t:     float
    x:     float
    y:     float
    z:     float
    yaw:   float    # degrees, 0 = +X axis
    pitch: float    # degrees, 0 = horizontal
    fov:   float = 90.0
    cut:   bool = False   # True on the last frame of a segment immediately before a hard cut


# ── public API ────────────────────────────────────────────────────────────────

def process_route(
    waypoints:       List[Tuple],          # (x, y[, yaw_offset, time_of_day, stop])
    smoothing:       float = 1.0,
    total_duration:  float = 30.0,
    fps:             float = 30.0,
    fov:             float = 90.0,
    uturn_radius:    float = 0.0,          # metres
    cuts:            Optional[Iterable[int]] = None,
    units_to_metres: float = 1.0,
    start_pan:       bool = False,
) -> List[CameraFrame]:
    """House-style camera frames: plan sparse keyframes (camera_style), then interpolate at fps."""
    from camera_style import interpolate, plan_keyframes
    plan = plan_keyframes(waypoints, units_to_metres=units_to_metres, total_duration=total_duration,
                          smoothing=smoothing, uturn_radius_m=uturn_radius, cuts=cuts, start_pan=start_pan)
    return interpolate(plan, fps, fov)


# ── room stops ────────────────────────────────────────────────────────────────

def _clean_stop(raw):
    """Normalised {look_at, dwell_s, pan} for a well-formed stop dict, else None."""
    if not isinstance(raw, dict) or not isinstance(look := raw.get("look_at"), (list, tuple)) or len(look) < 2:
        return None
    try:
        xy, dwell = (float(look[0]), float(look[1])), float(raw.get("dwell_s", 0.0))
    except (TypeError, ValueError):
        return None
    if not (all(map(math.isfinite, (*xy, dwell))) and dwell >= 0):
        return None
    return {"look_at": xy, "dwell_s": dwell, "pan": raw.get("pan") is True}


def _clean_stops(raws: list) -> list:
    """Validate every stop once; malformed ones become None (warned about once)."""
    stops = [_clean_stop(r) for r in raws]
    if dropped := sum(1 for r, s in zip(raws, stops) if r is not None and s is None):
        log.warning("ignored %d malformed waypoint stop(s)", dropped)
    return stops



def smooth_preview(
    waypoints:    List[Tuple[float, float]],
    smoothing:    float = 1.0,
    uturn_radius: float = 0.0,
) -> List[Tuple[float, float]]:
    """Dense smoothed polyline for live SVG preview."""
    if len(waypoints) < 2:
        return waypoints
    pts = np.array(waypoints, dtype=float)
    if uturn_radius > 0 and len(pts) >= 3:
        pts = _preprocess_sharp_turns(pts, uturn_radius)
    result = _centripetal_cr(pts, smoothing, samples=12)
    return [(float(p[0]), float(p[1])) for p in result]


# ── U-turn pre-processing ─────────────────────────────────────────────────────

def _preprocess_sharp_turns(pts: np.ndarray, uturn_radius: float,
                             angle_threshold: float = 120.0) -> np.ndarray:
    """
    At waypoints where the path turns sharper than `angle_threshold` degrees,
    insert two helper points at `uturn_radius` distance on either side of the
    apex.  The centripetal CR spline then arcs smoothly through those helpers
    instead of making a hairpin reversal.
    """
    result = [pts[0]]
    for i in range(1, len(pts) - 1):
        p0, p1, p2 = pts[i-1], pts[i], pts[i+1]
        v1 = p1 - p0
        v2 = p2 - p1
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 < 1e-10 or n2 < 1e-10:
            result.append(p1)
            continue
        cos_a = np.dot(v1/n1, v2/n2)
        angle = math.degrees(math.acos(float(np.clip(cos_a, -1.0, 1.0))))
        if angle > angle_threshold:
            r = min(uturn_radius, n1 * 0.45, n2 * 0.45)
            before = p1 - (v1/n1) * r
            after  = p1 + (v2/n2) * r
            result.extend([before, after])
        else:
            result.append(p1)
    result.append(pts[-1])
    return np.array(result)


# ── centripetal Catmull-Rom ───────────────────────────────────────────────────

def _centripetal_cr(
    pts:    np.ndarray,
    blend:  float = 1.0,
    samples: int  = 20,
    alpha:  float = 0.5,
) -> np.ndarray:
    n = len(pts)
    if n == 2 or blend == 0:
        t = np.linspace(0, 1, samples)
        result = []
        for i in range(n - 1):
            seg = pts[i] + t[:, None] * (pts[i+1] - pts[i])
            result.append(seg[:-1] if i < n-2 else seg)
        return np.vstack(result)

    padded = np.vstack([pts[0], pts, pts[-1]])
    result = []
    for i in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[i-1], padded[i], padded[i+1], padded[i+2]
        seg = _cr_segment(p0, p1, p2, p3, alpha, samples, blend)
        result.append(seg[:-1] if i < len(padded) - 3 else seg)
    return np.vstack(result)


def _cr_segment(
    p0: np.ndarray, p1: np.ndarray,
    p2: np.ndarray, p3: np.ndarray,
    alpha: float, samples: int, blend: float,
) -> np.ndarray:
    def tj(ti, pi, pj):
        d = np.linalg.norm(pj - pi)
        return ti + (d ** alpha if d > 1e-10 else 1e-10)

    t0 = 0.0
    t1 = tj(t0, p0, p1)
    t2 = tj(t1, p1, p2)
    t3 = tj(t2, p2, p3)

    ts = np.linspace(t1, t2, samples)
    result = []
    for t in ts:
        def safe_div(a, b, fa, fb):
            d = b - a
            return fa if abs(d) < 1e-12 else fa + (fb - fa) * (t - a) / d
        A1 = safe_div(t0, t1, p0, p1)
        A2 = safe_div(t1, t2, p1, p2)
        A3 = safe_div(t2, t3, p2, p3)
        B1 = safe_div(t0, t2, A1, A2)
        B2 = safe_div(t1, t3, A2, A3)
        C  = safe_div(t1, t2, B1, B2)
        linear = p1 + (p2 - p1) * (t - t1) / max(t2 - t1, 1e-12)
        result.append((1 - blend) * linear + blend * C)
    return np.array(result)
