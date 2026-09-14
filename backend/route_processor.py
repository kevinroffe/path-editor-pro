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
import math
from dataclasses import dataclass
from typing import List, Tuple, Optional, Iterable

import numpy as np


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

# Minimum still-frame time (seconds) held at a single-point segment (a cut placed
# on consecutive waypoints, with nothing to move along in between).
_HOLD_SECONDS = 0.4


def process_route(
    waypoints:      List[Tuple],          # (x, y) or (x, y, yaw_offset)
    camera_height:  float = 1.75,
    smoothing:      float = 1.0,
    total_duration: float = 30.0,
    fps:            float = 30.0,
    fov:            float = 90.0,
    uturn_radius:   float = 0.0,
    cuts:           Optional[Iterable[int]] = None,
) -> List[CameraFrame]:
    """
    `cuts` is a set of waypoint indices: a cut at index i means the path breaks
    between waypoint i and i+1 — that segment boundary is a hard jump (no spline
    connects them) rather than a continuous move. Each side of a cut is smoothed
    independently and gets a slice of total_duration proportional to its own arc
    length, so the overall video is still exactly total_duration seconds long.
    """
    if len(waypoints) < 2:
        raise ValueError("Need at least 2 waypoints")

    n = len(waypoints)
    cut_set = {i for i in (cuts or ()) if 0 <= i < n - 1}

    xy_pts      = [(float(p[0]), float(p[1])) for p in waypoints]
    yaw_offsets = [float(p[2]) if len(p) > 2 else 0.0 for p in waypoints]

    if not cut_set:
        return _process_segment(xy_pts, yaw_offsets, camera_height, smoothing,
                                 total_duration, fps, fov, uturn_radius)

    # Split into segments at each cut point
    bounds: List[Tuple[int, int]] = []
    start = 0
    for i in sorted(cut_set):
        bounds.append((start, i))
        start = i + 1
    bounds.append((start, n - 1))

    # Arc length per segment decides how much of total_duration it gets.
    # Single-point (degenerate) segments get a fixed short "hold" instead.
    seg_lengths = []
    for s, e in bounds:
        if e > s:
            pts = np.array(xy_pts[s:e+1])
            d = np.diff(pts, axis=0)
            seg_lengths.append(float(np.sum(np.hypot(d[:, 0], d[:, 1]))))
        else:
            seg_lengths.append(0.0)
    n_holds = sum(1 for s, e in bounds if e == s)

    if n_holds == len(bounds):
        # Every segment is a single point — a pure "slideshow of cuts" with no
        # camera movement anywhere. Split the whole duration evenly instead of
        # reserving only a small hold slice (which would leave most of the
        # requested duration unused).
        seg_durations = [total_duration / n_holds] * n_holds
    else:
        total_len = sum(seg_lengths) or 1.0
        hold_total = min(_HOLD_SECONDS * n_holds, total_duration * 0.3) if n_holds else 0.0
        movable = max(total_duration - hold_total, 0.1)
        seg_durations = []
        for (s, e), length in zip(bounds, seg_lengths):
            if e == s:
                seg_durations.append(hold_total / n_holds)
            else:
                seg_durations.append(movable * (length / total_len))

    all_frames: List[CameraFrame] = []
    t_cursor = 0.0
    for seg_i, ((s, e), seg_duration) in enumerate(zip(bounds, seg_durations)):
        seg_frames = _process_segment(
            xy_pts[s:e+1], yaw_offsets[s:e+1], camera_height, smoothing,
            max(seg_duration, 1e-6), fps, fov, uturn_radius,
        )
        is_last_segment = seg_i == len(bounds) - 1
        for f in seg_frames:
            f.t = t_cursor + f.t * seg_duration
        if not is_last_segment and seg_frames:
            seg_frames[-1].cut = True
        all_frames.extend(seg_frames)
        t_cursor += seg_duration

    for f in all_frames:
        f.t = min(f.t / total_duration, 1.0) if total_duration > 0 else 0.0

    return all_frames


def _process_segment(
    xy_pts:         List[Tuple[float, float]],
    yaw_offsets:    List[float],
    camera_height:  float,
    smoothing:      float,
    total_duration: float,
    fps:            float,
    fov:            float,
    uturn_radius:   float,
) -> List[CameraFrame]:
    if len(xy_pts) < 2:
        # Degenerate single-point "hold" segment — a still frame before a cut.
        n_frames = max(1, int(round(total_duration * fps)))
        x, y = xy_pts[0]
        return [CameraFrame(t=i / max(n_frames - 1, 1), x=x, y=y, z=camera_height,
                             yaw=0.0, pitch=0.0, fov=fov)
                for i in range(n_frames)]

    pts = np.array(xy_pts, dtype=float)

    if uturn_radius > 0 and len(pts) >= 3:
        pts = _preprocess_sharp_turns(pts, uturn_radius)

    smooth_pts = _centripetal_cr(pts, smoothing, samples=20)
    n_frames   = max(2, int(total_duration * fps))
    resampled  = _resample(smooth_pts, n_frames)
    frames     = _build_frames(resampled, camera_height, total_duration, fov)

    if any(o != 0.0 for o in yaw_offsets):
        _apply_yaw_offsets(frames, xy_pts, yaw_offsets)

    return frames


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


# ── arc-length resampling ─────────────────────────────────────────────────────

def _resample(pts: np.ndarray, n: int) -> np.ndarray:
    diffs   = np.diff(pts, axis=0)
    seg_len = np.hypot(diffs[:, 0], diffs[:, 1])
    arc     = np.concatenate([[0.0], np.cumsum(seg_len)])
    total   = arc[-1]
    if total < 1e-10:
        return np.tile(pts[0], (n, 1))
    targets = np.linspace(0, total, n)
    return np.column_stack([
        np.interp(targets, arc, pts[:, 0]),
        np.interp(targets, arc, pts[:, 1]),
    ])


# ── camera frames ─────────────────────────────────────────────────────────────

_MAX_YAW_RATE_DEG_PER_SEC = 180.0  # cinematic cap on how fast the camera may turn


def _build_frames(
    pts:      np.ndarray,
    height:   float,
    duration: float,
    fov:      float,
) -> List[CameraFrame]:
    n  = len(pts)
    la = max(1, int(n * 0.03))   # look-ahead: ~3 % of frames
    raw_yaw = np.empty(n)
    for i, (x, y) in enumerate(pts):
        j  = min(i + la, n - 1)
        dx = pts[j, 0] - x
        dy = pts[j, 1] - y
        if abs(dx) < 1e-9 and abs(dy) < 1e-9 and i > 0:
            dx = x - pts[i-1, 0]
            dy = y - pts[i-1, 1]
        raw_yaw[i] = math.degrees(math.atan2(dy, dx))

    # Rate-limit the yaw signal rather than use the raw look-ahead angle
    # directly. Near a sharp reversal (a real "go out and come back"
    # detour), the look-ahead point crosses from the outbound side to the
    # return side of the apex almost immediately even though the camera's
    # own position has barely moved, so the raw angle can whip through
    # ~180° in a couple of frames — this doesn't fix the geometry (already
    # correct, see _preprocess_sharp_turns) but stops the CAMERA from
    # snapping to face the new direction instantly. A box-filter/circular-
    # mean smoothing pass was tried first and rejected: averaging direction
    # vectors that point in opposite directions (exactly what happens near
    # a reversal) can cancel toward a near-zero vector, making the result
    # MORE erratic, not less — confirmed empirically, larger smoothing
    # windows made the worst-case per-frame jump bigger. A rate limiter
    # instead directly bounds the maximum turn speed by construction, so it
    # degrades a fast reversal into "turns at the cap for longer" rather
    # than any instability.
    dt = duration / max(n - 1, 1)
    max_step = _MAX_YAW_RATE_DEG_PER_SEC * dt
    yaws = np.empty(n)
    yaws[0] = raw_yaw[0]
    for i in range(1, n):
        delta = (raw_yaw[i] - yaws[i-1] + 180) % 360 - 180
        delta = max(-max_step, min(max_step, delta))
        yaws[i] = yaws[i-1] + delta

    frames = []
    for i, (x, y) in enumerate(pts):
        frames.append(CameraFrame(
            t     = i / max(n - 1, 1),
            x     = float(x),
            y     = float(y),
            z     = height,
            yaw   = float(yaws[i]),
            pitch = 0.0,
            fov   = fov,
        ))
    return frames


# ── per-waypoint yaw offsets ──────────────────────────────────────────────────

def _apply_yaw_offsets(
    frames:      List[CameraFrame],
    waypoints:   List[Tuple[float, float]],
    yaw_offsets: List[float],
) -> None:
    """
    Additively blend per-waypoint yaw offsets into the computed frame yaw.
    Offsets are interpolated linearly between waypoints using arc-length
    parameterisation, so transitions are smooth.
    """
    wpts = np.array(waypoints, dtype=float)
    offsets = np.array(yaw_offsets, dtype=float)
    n_wp = len(wpts)

    # Arc-length parameter for each original waypoint (normalised 0→1)
    wp_arc = [0.0]
    for i in range(1, n_wp):
        wp_arc.append(wp_arc[-1] + float(np.linalg.norm(wpts[i] - wpts[i-1])))
    total = wp_arc[-1]
    if total < 1e-10:
        return
    wp_t = np.array(wp_arc) / total

    for frame in frames:
        offset = float(np.interp(frame.t, wp_t, offsets))
        frame.yaw = (frame.yaw + offset) % 360
