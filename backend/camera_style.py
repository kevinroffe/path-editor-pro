"""Camera house style: sparse eased keyframes learned from qbiq's hand-made Enscape paths.

The keyframe plan is the single source for the Enscape XML (written as-is) and the
preview / JSON frames (interpolated here the way Enscape eases between keyframes).
"""
from __future__ import annotations

import bisect
import logging
import math
from dataclasses import dataclass, field

import numpy as np

from route_processor import CameraFrame

log = logging.getLogger(__name__)

EYE_HEIGHT_M = 1.57
KF_SPACING_S = 3.3
KF_SPACING_M = 3.2
WALK_SPEED_MPS = 1.1
MIN_SPEED_MPS = 0.8
MAX_SPEED_MPS = 1.45
MAX_YAW_RATE_DPS = 25.0
MAX_REVERSALS_PER_MIN = 6
ROOM_LOOK_MAX_DEG = 60.0
MIN_LOOK_SPEED_MPS = 0.8
TURN_LEAD_S = 1.5
PAN_DURATION_S = 5.0
PAN_MAX_DEG = 90.0
MAX_PANS = 2
EASE_S = 1.5
CORNER_DEG = 25.0
MERGE_M = 1.0


@dataclass
class Keyframe:
    t_s: float
    x: float
    y: float
    yaw: float
    hour: float | None = None
    cut_after: bool = False


@dataclass
class KeyframePlan:
    keyframes: list
    units_to_metres: float
    warnings: list = field(default_factory=list)
    pans: int = 0


# ── interpolation ─────────────────────────────────────────────────────────────

def _cr_point(p0, p1, p2, p3, u: float, alpha: float = 0.5) -> np.ndarray:
    """Centripetal Catmull-Rom point between p1 and p2 at u in [0, 1] (Barry-Goldman)."""
    def knot(ti, a, b):
        return ti + max(float(np.linalg.norm(b - a)) ** alpha, 1e-9)

    def lerp(ta, tb, a, b, t):
        return a if abs(tb - ta) < 1e-12 else a + (b - a) * (t - ta) / (tb - ta)

    t0 = 0.0
    t1 = knot(t0, p0, p1)
    t2 = knot(t1, p1, p2)
    t3 = knot(t2, p2, p3)
    t = t1 + (t2 - t1) * u
    a1, a2, a3 = lerp(t0, t1, p0, p1, t), lerp(t1, t2, p1, p2, t), lerp(t2, t3, p2, p3, t)
    b1, b2 = lerp(t0, t2, a1, a2, t), lerp(t1, t3, a2, a3, t)
    return lerp(t1, t2, b1, b2, t)


def _chain_bounds(kfs: list, i: int) -> tuple:
    """First and last keyframe index of the cut-free chain containing segment i."""
    lo = i
    while lo > 0 and not kfs[lo - 1].cut_after:
        lo -= 1
    hi = i + 1
    while hi < len(kfs) - 1 and not kfs[hi].cut_after:
        hi += 1
    return lo, hi


def _secant(kfs: list, k: int) -> float:
    return (kfs[k + 1].yaw - kfs[k].yaw) / max(kfs[k + 1].t_s - kfs[k].t_s, 1e-9)


def _tangent(kfs: list, k: int, lo: int, hi: int) -> float:
    """Min-mod yaw tangent at keyframe k: never overshoots, peak slope <= 1.5x the secant."""
    if k == lo:
        return _secant(kfs, k) if hi > lo else 0.0
    if k == hi:
        return _secant(kfs, k - 1)
    a, b = _secant(kfs, k - 1), _secant(kfs, k)
    return 0.0 if a * b <= 0 else math.copysign(min(abs(a), abs(b)), a)


def _segment(kfs: list, t_s: float) -> int:
    """Index i of the keyframe segment [t_i, t_i+1] containing t_s (clamped)."""
    times = [k.t_s for k in kfs]
    return min(max(bisect.bisect_right(times, t_s) - 1, 0), len(kfs) - 2)


def sample_at(plan: KeyframePlan, t_s: float) -> tuple:
    """(x, y, yaw) on the keyframe curve at path time t_s (no ease)."""
    kfs = plan.keyframes
    if len(kfs) == 1:
        return kfs[0].x, kfs[0].y, kfs[0].yaw
    i = _segment(kfs, t_s)
    a, b = kfs[i], kfs[i + 1]
    if a.cut_after:
        return a.x, a.y, a.yaw
    lo, hi = _chain_bounds(kfs, i)
    h = max(b.t_s - a.t_s, 1e-9)
    u = min(max((t_s - a.t_s) / h, 0.0), 1.0)
    pts = [np.array([k.x, k.y]) for k in (kfs[max(i - 1, lo)], a, b, kfs[min(i + 2, hi)])]
    x, y = _cr_point(*pts, u)
    m0, m1 = _tangent(kfs, i, lo, hi) * h, _tangent(kfs, i + 1, lo, hi) * h
    h00, h10, h01, h11 = 2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u, -2 * u**3 + 3 * u**2, u**3 - u**2
    return float(x), float(y), h00 * a.yaw + h10 * m0 + h01 * b.yaw + h11 * m1


def _eased(tau: float, total: float) -> float:
    """Path time at playback time tau: trapezoid speed with EASE_S ramps, same total length."""
    r = min(EASE_S, total / 2)
    if r <= 0:
        return tau
    vmax = total / (total - r)
    if tau < r:
        return vmax * tau * tau / (2 * r)
    if tau > total - r:
        return total - vmax * (total - tau) ** 2 / (2 * r)
    return vmax * (tau - r / 2)


def interpolate(plan: KeyframePlan, fps: float, fov: float = 90.0) -> list:
    """Camera frames at fps along the eased keyframe curve, t normalised to [0, 1]."""
    kfs = plan.keyframes
    total = kfs[-1].t_s - kfs[0].t_s
    n = max(2, int(round(total * fps)) + 1)
    frames, segs = [], []
    for j in range(n):
        p = kfs[0].t_s + _eased(total * j / (n - 1), total)
        x, y, yaw = sample_at(plan, p)
        segs.append(_segment(kfs, p) if len(kfs) > 1 else 0)
        frames.append(CameraFrame(t=j / (n - 1), x=x, y=y, z=EYE_HEIGHT_M, yaw=yaw, pitch=0.0, fov=fov))
    for j in range(n - 1):
        frames[j].cut = segs[j + 1] > segs[j] and any(kfs[k].cut_after for k in range(segs[j], segs[j + 1]))
    return frames
