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

from route_processor import CameraFrame, _centripetal_cr, _clean_stops, _preprocess_sharp_turns

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


# ── keyframe planning ─────────────────────────────────────────────────────────

CUT_GAP_S = 0.05
HOLD_S = 0.4
_CORNER_WINDOW_M = 1.5


@dataclass
class _Draft:
    """A keyframe being planned: global arc length (m), travel heading, owning waypoint."""
    x: float
    y: float
    s_m: float
    travel: float
    seg: int
    wp: int | None = None
    t_s: float = 0.0
    yaw: float = 0.0
    hour: float | None = None
    cut_after: bool = False
    pan: bool = False


@dataclass
class _Leg:
    """Smoothed geometry of one cut-free route segment (plan units)."""
    pts: np.ndarray
    arc: np.ndarray
    heading: np.ndarray
    wps: list
    s0_m: float


def suggest_duration_s(length_m: float, n_pans: int = 0) -> int:
    """House-style video length: walking at WALK_SPEED_MPS plus pans, rounded up to 5 s, min 10 s."""
    return max(10, 5 * math.ceil((length_m / WALK_SPEED_MPS + PAN_DURATION_S * n_pans) / 5 - 1e-9))


def _parse_hour(raw) -> float | None:
    """'HH:MM' -> decimal hours, else None."""
    try:
        h, m = (str(raw).strip().split(":") + ["0"])[:2]
        return max(0.0, min(24.0, int(h) + int(m) / 60.0))
    except (TypeError, ValueError):
        return None


def _bounds(n: int, cuts) -> list:
    """(start, end) waypoint index ranges between cuts."""
    out, start = [], 0
    for i in sorted({c for c in (cuts or ()) if 0 <= c < n - 1}):
        out.append((start, i))
        start = i + 1
    return out + [(start, n - 1)]


def _leg(pts: np.ndarray, wps: list, smoothing: float, uturn_units: float, s0_m: float) -> _Leg:
    """Smoothed polyline, arc length and unwrapped heading of one segment."""
    if len(pts) >= 3 and uturn_units > 0:
        pts = _preprocess_sharp_turns(pts, uturn_units)
    dense = _centripetal_cr(pts, smoothing, samples=20) if len(pts) >= 2 else pts
    arc = np.r_[0.0, np.cumsum(np.hypot(*np.diff(dense, axis=0).T))] if len(dense) > 1 else np.zeros(1)
    d = np.diff(dense, axis=0) if len(dense) > 1 else np.zeros((1, 2))
    head = np.degrees(np.unwrap(np.arctan2(d[:, 1], d[:, 0])))
    return _Leg(dense, arc, np.r_[head, head[-1]] if len(dense) > 1 else np.zeros(1), wps, s0_m)


def _at(leg: _Leg, s: float) -> tuple:
    """(x, y, heading) at arc length s (plan units) on a leg."""
    s = min(max(s, 0.0), float(leg.arc[-1]))
    return (float(np.interp(s, leg.arc, leg.pts[:, 0])), float(np.interp(s, leg.arc, leg.pts[:, 1])),
            float(np.interp(s, leg.arc, leg.heading)))


def _waypoint_arcs(leg: _Leg, raw_pts: np.ndarray) -> list:
    """Arc length of each original waypoint along the leg, searched forward in order."""
    out, k = [], 0
    for p in raw_pts:
        k += int(np.argmin(np.hypot(*(leg.pts[k:] - p).T)))
        out.append(float(leg.arc[k]))
    return out


def _corner_arcs(leg: _Leg, u: float) -> list:
    """Arc lengths of corner apexes: heading change >= CORNER_DEG within +-_CORNER_WINDOW_M."""
    w = _CORNER_WINDOW_M / u
    change = np.abs(np.interp(leg.arc + w, leg.arc, leg.heading) - np.interp(leg.arc - w, leg.arc, leg.heading))
    runs, i, hot = [], 0, change >= CORNER_DEG
    while i < len(hot):
        if not hot[i]:
            i += 1
            continue
        j = i
        while j < len(hot) and hot[j]:
            j += 1
        runs.append(float(leg.arc[i + int(np.argmax(change[i:j]))]))
        i = j
    return runs


def _stations(leg: _Leg, anchors: dict, u: float) -> list:
    """Sorted (arc, waypoint|None): anchors + corners merged within MERGE_M, gaps filled every KF_SPACING_M."""
    marks = sorted([(s, wp) for wp, s in anchors.items()] + [(s, None) for s in _corner_arcs(leg, u)],
                   key=lambda m: (m[0], m[1] is None))
    kept = []
    for s, wp in marks:
        if kept and (s - kept[-1][0]) * u < MERGE_M:
            if wp is not None and kept[-1][1] is None:
                kept[-1] = (s, wp)
            continue
        kept.append((s, wp))
    if kept[-1][0] < leg.arc[-1]:
        kept[-1] = (float(leg.arc[-1]), kept[-1][1])
    out = [kept[0]]
    for (a, _), (b, wp) in zip(kept, kept[1:]):
        n = max(1, round((b - a) * u / KF_SPACING_M))
        out += [(a + (b - a) * k / n, None) for k in range(1, n)] + [(b, wp)]
    return out


def _drafts_for_leg(leg: _Leg, seg: int, wps: list, needs_anchor, u: float) -> list:
    """Draft keyframes along one leg (or a short hold for a single-point segment)."""
    if len(leg.pts) < 2 or leg.arc[-1] <= 0:
        x, y = leg.pts[0]
        return [_Draft(float(x), float(y), leg.s0_m, 0.0, seg, wps[0]),
                _Draft(float(x), float(y), leg.s0_m, 0.0, seg, None)]
    arcs = _waypoint_arcs(leg, np.array([[w[0], w[1]] for w in leg.wps], dtype=float))
    anchors = {wps[0]: 0.0} | {i: s for i, s in zip(wps, arcs) if needs_anchor(i)} | {wps[-1]: float(leg.arc[-1])}
    drafts = []
    for s, wp in _stations(leg, anchors, u):
        x, y, h = _at(leg, s)
        drafts.append(_Draft(x, y, leg.s0_m + s * u, h, seg, wp))
    return drafts


def _route(waypoints: list, smoothing: float, uturn_radius_m: float, cuts, u: float) -> tuple:
    """Legs and draft keyframes for the whole route, plus per-waypoint stops and yaw offsets."""
    stops = _clean_stops([p[4] if len(p) > 4 else None for p in waypoints])
    offsets = [float(p[2]) if len(p) > 2 else 0.0 for p in waypoints]
    hours = [_parse_hour(p[3]) if len(p) > 3 else None for p in waypoints]

    def needs_anchor(i):
        return stops[i] is not None or offsets[i] != 0.0 or hours[i] is not None

    legs, drafts, s0 = [], [], 0.0
    for seg, (a, b) in enumerate(_bounds(len(waypoints), cuts)):
        pts = np.array([[float(p[0]), float(p[1])] for p in waypoints[a:b + 1]])
        leg = _leg(pts, waypoints[a:b + 1], smoothing, uturn_radius_m / u, s0)
        if drafts:
            drafts[-1].cut_after = True
        drafts += _drafts_for_leg(leg, seg, list(range(a, b + 1)), needs_anchor, u)
        legs.append(leg)
        s0 += float(leg.arc[-1]) * u
    for d in drafts:
        d.hour = hours[d.wp] if d.wp is not None else None
    return legs, drafts, stops, offsets


def _speed_warning(v: float, length_m: float, pans: int) -> list:
    """House-style speed warning with a suggested video length, or none."""
    if v > MAX_SPEED_MPS:
        return [f"Video too short — walking at {v:.1f} m/s; try {suggest_duration_s(length_m, pans)} s"]
    if 0 < v < MIN_SPEED_MPS:
        return [f"Video too long — walking at {v:.1f} m/s; try {suggest_duration_s(length_m, pans)} s"]
    return []


def _still_s(a: _Draft, b: _Draft) -> float:
    """Seconds spent between two drafts without walking: cut gap, pan or hold (0 if walking)."""
    if a.cut_after:
        return CUT_GAP_S
    if b.s_m - a.s_m > 0:
        return 0.0
    return PAN_DURATION_S if b.pan else HOLD_S


def _assign_times(drafts: list, duration: float) -> tuple:
    """Constant-speed timestamps (holds, pans and cut gaps reserved), scaled to end at duration."""
    length_m = drafts[-1].s_m - drafts[0].s_m
    fixed = sum(_still_s(a, b) for a, b in zip(drafts, drafts[1:]))
    v = length_m / max(duration - fixed, 0.1 * duration) if length_m > 0 else 0.0
    t = 0.0
    for a, b in zip(drafts, drafts[1:]):
        t += _still_s(a, b) or ((b.s_m - a.s_m) / v if v > 0 else HOLD_S)
        b.t_s = t
    scale = duration / t if t > 0 else 1.0
    for d in drafts:
        d.t_s *= scale
    return v, length_m


# ── gaze ──────────────────────────────────────────────────────────────────────

_LOOK_EASE_S = 1.5
_EDGE_DEDUP_M = 0.2


def _wrap(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def _smoothstep(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def _with_look_edges(drafts: list, legs: list, stops: list, v: float, u: float) -> list:
    """Drafts plus keyframes at each room look's window edges (anchor +- half its look time)."""
    extra = []
    for a in drafts:
        if a.wp is None or not (stop := stops[a.wp]) or stop["dwell_s"] <= 0:
            continue
        leg = legs[a.seg]
        for sign in (-1, 1):
            s_m = a.s_m + sign * v * stop["dwell_s"] / 2
            local = min(max((s_m - leg.s0_m) / u, 0.0), float(leg.arc[-1]))
            s_m = leg.s0_m + local * u
            if all(abs(d.s_m - s_m) >= _EDGE_DEDUP_M for d in drafts + extra if d.seg == a.seg):
                x, y, h = _at(leg, local)
                extra.append(_Draft(x, y, s_m, h, a.seg))
    merged = sorted(drafts + extra, key=lambda d: (d.seg, d.s_m, d.pan))
    for a, b in zip(merged, merged[1:]):
        a.cut_after = a.seg != b.seg
    merged[-1].cut_after = False
    return merged


def _lead_yaw(drafts: list, legs: list, v: float, u: float) -> list:
    """Travel direction TURN_LEAD_S ahead (the head turns before the body), continuous."""
    out = [_at(legs[d.seg], (d.s_m - legs[d.seg].s0_m + TURN_LEAD_S * v) / u)[2] for d in drafts]
    return list(np.degrees(np.unwrap(np.radians(out))))


def _room_look_offsets(drafts: list, base: list, stops: list, v: float) -> list:
    """Per-draft gaze offset toward the nearest active room look (clamped, eased by walking time)."""
    anchors = [(d.s_m, d.seg, stops[d.wp]) for d in drafts if d.wp is not None and stops[d.wp]]
    out = []
    for d, b in zip(drafts, base):
        best = None
        for s_a, seg, stop in anchors:
            dist, half = abs(d.s_m - s_a) / max(v, 1e-9), stop["dwell_s"] / 2
            w = 1.0 if dist <= half + 1e-6 else _smoothstep(1 - (dist - half) / _LOOK_EASE_S)
            if seg == d.seg and w > 0 and (best is None or dist < best[0]):
                bearing = math.degrees(math.atan2(stop["look_at"][1] - d.y, stop["look_at"][0] - d.x))
                best = (dist, w * max(-ROOM_LOOK_MAX_DEG, min(ROOM_LOOK_MAX_DEG, _wrap(bearing - b))))
        out.append(best[1] if best else 0.0)
    return out


def _user_offsets(drafts: list, offsets: list) -> list:
    """User heading offsets at their waypoint keyframe, half on each neighbour (short way round)."""
    out = [0.0] * len(drafts)
    for i, d in enumerate(drafts):
        if d.wp is None or not (o := _wrap(offsets[d.wp])):
            continue
        out[i] += o
        for j in (i - 1, i + 1):
            if 0 <= j < len(drafts) and drafts[j].seg == d.seg:
                out[j] += o / 2
    return out


_START_PAN_FROM_DEG = -60.0
_MIN_PAN_SWEEP_DEG = 30.0


def _choose_pans(drafts: list, stops: list, start_pan: bool) -> tuple:
    """Draft indices that get a standing pan (None = start), at most MAX_PANS, plus warnings."""
    wanted = ([None] if start_pan else []) + [
        i for i, d in enumerate(drafts) if d.wp is not None and stops[d.wp] and stops[d.wp]["pan"]]
    extra = ["Only 2 standing pans per video — extra ones are ignored"] if len(wanted) > MAX_PANS else []
    return wanted[:MAX_PANS], extra


def _insert_pans(drafts: list, chosen: list) -> list:
    """Drafts with a pan-end duplicate after each chosen anchor (start pan = after the first draft)."""
    out = []
    for i, d in enumerate(drafts):
        out.append(d)
        if i in chosen or (i == 0 and None in chosen):
            out.append(_Draft(d.x, d.y, d.s_m, d.travel, d.seg, None, cut_after=d.cut_after, pan=True))
            d.cut_after = False
    return out


def _apply_pan_yaws(drafts: list, base: list, stops: list) -> None:
    """Start pan sweeps from travel-60 to travel; a stop pan sweeps on toward its room (<= PAN_MAX_DEG)."""
    for i, d in enumerate(drafts):
        if not d.pan:
            continue
        a = drafts[i - 1]
        if a.wp is None or not stops[a.wp]:
            a.yaw, d.yaw = base[i - 1] + _START_PAN_FROM_DEG, base[i]
            continue
        look = stops[a.wp]["look_at"]
        rel = _wrap(math.degrees(math.atan2(look[1] - d.y, look[0] - d.x)) - base[i])
        target = max(-PAN_MAX_DEG, min(PAN_MAX_DEG, rel))
        if abs(base[i] + target - a.yaw) < _MIN_PAN_SWEEP_DEG:
            target = max(-PAN_MAX_DEG, min(PAN_MAX_DEG, a.yaw - base[i] + math.copysign(_MIN_PAN_SWEEP_DEG, rel)))
        d.yaw = base[i] + target


_REVERSAL_STEP_DEG = 3.0
_LIMIT_PASSES = 50


def _significant_steps(yaws: list) -> list:
    """(start index, signed change) of each keyframe step larger than _REVERSAL_STEP_DEG."""
    return [(i, b - a) for i, (a, b) in enumerate(zip(yaws, yaws[1:])) if abs(b - a) > _REVERSAL_STEP_DEG]


def _limit_reversals(drafts: list) -> None:
    """Flatten the smallest left-right head wobbles until reversals <= MAX_REVERSALS_PER_MIN."""
    minutes = max((drafts[-1].t_s - drafts[0].t_s) / 60.0, 1e-9)
    for _ in range(len(drafts) * 2):
        steps = _significant_steps([d.yaw for d in drafts])
        flips = [(min(abs(s1), abs(s2)), i1, i2 + 1) for (i1, s1), (i2, s2) in zip(steps, steps[1:]) if s1 * s2 < 0]
        if len(flips) / minutes <= MAX_REVERSALS_PER_MIN:
            return
        _, a, b = min(flips)
        for k in range(a + 1, b):
            drafts[k].yaw = drafts[a].yaw + (drafts[b].yaw - drafts[a].yaw) * (k - a) / (b - a)


def _segment_indices(drafts: list, i: int) -> range:
    """Indices of the cut-free segment containing draft i."""
    lo = i
    while lo > 0 and not drafts[lo - 1].cut_after:
        lo -= 1
    hi = i
    while hi < len(drafts) - 1 and not drafts[hi].cut_after:
        hi += 1
    return range(lo, hi + 1)


def _borrow_time(drafts: list, i: int, grow: float) -> float:
    """Lengthen interval i by up to grow seconds, taken from the segment's other walking intervals."""
    idx = _segment_indices(drafts, i)
    lo = idx[0]
    dts = [drafts[k + 1].t_s - drafts[k].t_s for k in idx[:-1]]
    floor = [(drafts[k + 1].s_m - drafts[k].s_m) / MAX_SPEED_MPS for k in idx[:-1]]
    slack = [max(dt - f, 0.0) if k != i and drafts[k + 1].s_m > drafts[k].s_m else 0.0
             for k, dt, f in zip(idx[:-1], dts, floor)]
    take = min(grow, sum(slack))
    if take <= 0:
        return 0.0
    dts = [dt - take * s / sum(slack) for dt, s in zip(dts, slack)]
    dts[i - lo] += take
    for k, dt in zip(idx[:-1], dts):
        drafts[k + 1].t_s = drafts[k].t_s + dt
    return take


def _limit_turn_rate(drafts: list, base: list) -> list:
    """Kevin's rule: slow the walk (to MIN_LOOK_SPEED_MPS) first, then turn less; never faster."""
    warnings = set()
    for _ in range(_LIMIT_PASSES):
        violated = False
        for i, (a, b) in enumerate(zip(drafts, drafts[1:])):
            dt = b.t_s - a.t_s
            need = abs(b.yaw - a.yaw) / MAX_YAW_RATE_DPS
            if a.cut_after or need <= dt + 1e-9:
                continue
            violated = True
            if (ds := b.s_m - a.s_m) > 0 and (grow := min(need, ds / MIN_LOOK_SPEED_MPS) - dt) > 1e-9:
                got = _borrow_time(drafts, i, grow)
                if got < grow - 1e-6:
                    warnings.add("Video too short for smooth head turns — some looks are shortened")
                dt += got
            if need > dt + 1e-9:
                k, other = (i + 1, i) if abs(b.yaw - base[i + 1]) >= abs(a.yaw - base[i]) else (i, i + 1)
                diff = drafts[k].yaw - drafts[other].yaw
                drafts[k].yaw = drafts[other].yaw + math.copysign(MAX_YAW_RATE_DPS * dt, diff)
        if not violated:
            return sorted(warnings)
    log.warning("head-turn limiter did not converge in %d passes", _LIMIT_PASSES)
    return sorted(warnings)


def _to_keyframes(drafts: list) -> list:
    """Public keyframes (yaw already continuous)."""
    return [Keyframe(d.t_s, d.x, d.y, float(d.yaw), d.hour, d.cut_after) for d in drafts]


def plan_keyframes(waypoints: list, *, units_to_metres: float, total_duration: float, smoothing: float = 1.0,
                   uturn_radius_m: float = 0.0, cuts=None, start_pan: bool = False) -> KeyframePlan:
    """House-style keyframe plan for a route of (x, y[, yaw_offset, time_of_day, stop]) waypoints."""
    if len(waypoints) < 2:
        raise ValueError("Need at least 2 waypoints")
    u = units_to_metres
    legs, drafts, stops, offsets = _route(waypoints, smoothing, uturn_radius_m, cuts, u)
    chosen, warnings = _choose_pans(drafts, stops, start_pan)
    drafts = _insert_pans(drafts, chosen)
    v, _ = _assign_times(drafts, total_duration)
    drafts = _with_look_edges(drafts, legs, stops, v, u)
    v, length_m = _assign_times(drafts, total_duration)
    base = _lead_yaw(drafts, legs, v, u)
    gaze = np.add(_room_look_offsets(drafts, base, stops, v), _user_offsets(drafts, offsets))
    for d, b, g in zip(drafts, base, gaze):
        d.yaw = b + g
    _apply_pan_yaws(drafts, base, stops)
    _limit_reversals(drafts)
    warnings = _speed_warning(v, length_m, len(chosen)) + warnings + _limit_turn_rate(drafts, base)
    return KeyframePlan(_to_keyframes(drafts), u, warnings, len(chosen))
