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
KF_FILL_S = 3.6      # fill target; corner and look keyframes pull the average toward KF_SPACING_S
KF_SPACING_M = 3.2
WALK_SPEED_MPS = 0.95
MIN_SPEED_MPS = 0.6
MAX_SPEED_MPS = 1.45
MAX_YAW_RATE_DPS = 25.0
MAX_REVERSALS_PER_MIN = 6
ROOM_LOOK_MAX_DEG = 60.0
MIN_LOOK_SPEED_MPS = 0.8
TURN_LEAD_S = 1.5
PAN_DURATION_S = 4.0
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
    kind: str = "fill"


@dataclass
class _Leg:
    """Smoothed geometry of one cut-free route segment (plan units)."""
    pts: np.ndarray
    arc: np.ndarray
    heading: np.ndarray
    wps: list
    s0_m: float


def suggest_duration_s(length_m: float, n_pans: int = 0, look_s: float = 0.0) -> int:
    """House-style video length: walking at WALK_SPEED_MPS plus pans and room looks, rounded up to 5 s, min 10 s."""
    return max(10, 5 * math.ceil((length_m / WALK_SPEED_MPS + PAN_DURATION_S * n_pans + look_s) / 5 - 1e-9))


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


def _corner_arcs(raw_pts: np.ndarray, arcs: list) -> list:
    """Arc lengths of route waypoints where the route turns >= CORNER_DEG (the spline passes through them)."""
    out = []
    for i in range(1, len(raw_pts) - 1):
        a, b = raw_pts[i] - raw_pts[i - 1], raw_pts[i + 1] - raw_pts[i]
        if np.linalg.norm(a) > 1e-9 and np.linalg.norm(b) > 1e-9:
            turn = abs(_wrap(math.degrees(math.atan2(b[1], b[0]) - math.atan2(a[1], a[0]))))
            if turn >= CORNER_DEG:
                out.append(arcs[i])
    return out


CORNER_MERGE_M = 2.5
MIN_SPACING_M = 2.1   # reference keyframe spacing p10..p90
MAX_SPACING_M = 4.0


def _merge(kept: list, mark: tuple, u: float, ends: tuple) -> None:
    """Add (arc, wp, kind, important) to kept, merging corners and unimportant anchors that crowd it."""
    s, wp, kind, important = mark
    if not kept:
        kept.append(mark)
        return
    ps, pwp, pkind, pimp = kept[-1]
    gap = (s - ps) * u
    if kind == "corner" and gap < CORNER_MERGE_M:
        return
    if pkind == "corner" and gap < CORNER_MERGE_M:
        kept[-1] = mark
        return
    if gap >= MERGE_M or (important and pimp):
        kept.append(mark)
    elif important:                            # takes over a crowding plain anchor, keeping a leg end in place
        kept[-1] = (ps if ps in ends else s, wp, kind, True)
    elif s in ends and not pimp:
        kept[-1] = (s, wp, kind, False)


def _stations(leg: _Leg, anchors: dict, corners: list, important: set, u: float, spacing_m: float) -> list:
    """Sorted (arc, waypoint|None, kind): anchors and corners merged, gaps filled every spacing_m."""
    marks = sorted([(s, wp, "anchor", wp in important) for wp, s in anchors.items()]
                   + [(s, None, "corner", False) for s in corners],
                   key=lambda m: (m[0], m[2] == "corner"))
    ends, kept = (0.0, float(leg.arc[-1])), []
    for m in marks:
        _merge(kept, m, u, ends)
    if kept[-1][0] < leg.arc[-1]:
        kept[-1] = (float(leg.arc[-1]),) + kept[-1][1:]
    out = [kept[0][:3]]
    for (a, *_), (b, wp, kind, _) in zip(kept, kept[1:]):
        n = max(1, round((b - a) * u / spacing_m))
        out += [(a + (b - a) * k / n, None, "fill") for k in range(1, n)] + [(b, wp, kind)]
    return out


def _drafts_for_leg(leg: _Leg, seg: int, wps: list, important: set, u: float, spacing_m: float) -> list:
    """Draft keyframes along one leg (or a short hold for a single-point segment)."""
    if len(leg.pts) < 2 or leg.arc[-1] <= 0:
        x, y = leg.pts[0]
        return [_Draft(float(x), float(y), leg.s0_m, 0.0, seg, wps[0], kind="anchor"),
                _Draft(float(x), float(y), leg.s0_m, 0.0, seg, None, kind="anchor")]
    raw = np.array([[w[0], w[1]] for w in leg.wps], dtype=float)
    arcs = _waypoint_arcs(leg, raw)
    anchors = {wps[0]: 0.0} | {i: s for i, s in zip(wps, arcs) if i in important} | {wps[-1]: float(leg.arc[-1])}
    drafts = []
    for s, wp, kind in _stations(leg, anchors, _corner_arcs(raw, arcs), important, u, spacing_m):
        x, y, h = _at(leg, s)
        drafts.append(_Draft(x, y, leg.s0_m + s * u, h, seg, wp, kind=kind))
    return drafts


def _route(waypoints: list, smoothing: float, uturn_radius_m: float, cuts, u: float, duration: float) -> tuple:
    """Legs and draft keyframes for the whole route, plus per-waypoint stops and yaw offsets."""
    stops = _clean_stops([p[4] if len(p) > 4 else None for p in waypoints])
    look_s = sum(s["dwell_s"] for s in stops if s)
    stops = [None if s and s["walk_in"] and not s["pan"] else s for s in stops]   # inside the room: walking in is the look
    offsets = [float(p[2]) if len(p) > 2 else 0.0 for p in waypoints]
    hours = [_parse_hour(p[3]) if len(p) > 3 else None for p in waypoints]
    important = {i for i in range(len(waypoints)) if stops[i] or offsets[i] != 0.0 or hours[i] is not None}

    legs, s0 = [], 0.0
    for a, b in _bounds(len(waypoints), cuts):
        pts = np.array([[float(p[0]), float(p[1])] for p in waypoints[a:b + 1]])
        legs.append(_leg(pts, waypoints[a:b + 1], smoothing, uturn_radius_m / u, s0))
        s0 += float(legs[-1].arc[-1]) * u
    spacing = min(max(KF_FILL_S * s0 / max(duration, 1e-9), MIN_SPACING_M), MAX_SPACING_M)
    drafts = []
    for seg, ((a, b), leg) in enumerate(zip(_bounds(len(waypoints), cuts), legs)):
        if drafts:
            drafts[-1].cut_after = True
        drafts += _drafts_for_leg(leg, seg, list(range(a, b + 1)), important, u, spacing)
    for d in drafts:
        d.hour = hours[d.wp] if d.wp is not None else None
    return legs, drafts, stops, offsets, spacing, look_s


def _speed_warning(v: float, length_m: float, pans: int, look_s: float) -> list:
    """House-style speed warning with a suggested video length, or none; room looks get their time as in
    suggest_duration_s, so the walking pace is judged without it."""
    if v <= 0:
        return []
    pace = length_m / max(length_m / v - look_s, 1e-9)
    if pace > MAX_SPEED_MPS:
        return [f"Video too short — walking at {v:.1f} m/s; try {suggest_duration_s(length_m, pans, look_s)} s"]
    if pace < MIN_SPEED_MPS:
        return [f"Video too long — walking at {v:.1f} m/s; try {suggest_duration_s(length_m, pans, look_s)} s"]
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
_EDGE_DEDUP_M = MERGE_M


def _wrap(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def _smoothstep(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def _with_look_edges(drafts: list, legs: list, stops: list, v: float, u: float, spacing_m: float) -> list:
    """Drafts plus keyframes at each room look's window edges; fill keyframes crowding an edge are dropped."""
    extra = []
    for a in drafts:
        if a.wp is None or not (stop := stops[a.wp]) or stop["dwell_s"] <= 0:
            continue
        leg = legs[a.seg]
        for sign in (-1, 1):
            s_m = a.s_m + sign * v * stop["dwell_s"] / 2
            local = min(max((s_m - leg.s0_m) / u, 0.0), float(leg.arc[-1]))
            s_m = leg.s0_m + local * u
            if all(abs(d.s_m - s_m) >= _EDGE_DEDUP_M for d in drafts + extra if d.seg == a.seg and d is not a):
                x, y, h = _at(leg, local)
                extra.append(_Draft(x, y, s_m, h, a.seg, kind="edge"))
    keep = [d for d in drafts if d.kind != "fill" or all(
        e.seg != d.seg or abs(e.s_m - d.s_m) >= spacing_m / 2 for e in extra)]
    merged = sorted(keep + extra, key=lambda d: (d.seg, d.s_m, d.pan))
    for a, b in zip(merged, merged[1:]):
        a.cut_after = a.seg != b.seg
    merged[-1].cut_after = False
    return merged


_STRAIGHT_RATIO = 0.8


def _straight(a: _Draft, b: _Draft, u: float) -> bool:
    """True when the walk from a to b is nearly a straight line (not into a dead end and back)."""
    return math.hypot(b.x - a.x, b.y - a.y) * u >= _STRAIGHT_RATIO * (b.s_m - a.s_m)


def _drop_look_anchors(drafts: list, stops: list, offsets: list, u: float) -> list:
    """Drop a plain room-look anchor sitting between its two look edges (the edges hold the look)."""
    def redundant(i):
        d = drafts[i]
        return (d.kind == "anchor" and d.wp is not None and stops[d.wp] and not stops[d.wp]["pan"]
                and d.hour is None and offsets[d.wp] == 0.0 and 0 < i < len(drafts) - 1
                and drafts[i - 1].kind == "edge" and drafts[i + 1].kind == "edge"
                and drafts[i - 1].seg == d.seg == drafts[i + 1].seg and _straight(drafts[i - 1], drafts[i + 1], u))
    return [d for i, d in enumerate(drafts) if not redundant(i)]


def _lead_yaw(drafts: list, legs: list, v: float, u: float) -> list:
    """Travel direction TURN_LEAD_S ahead (the head turns before the body), continuous."""
    out = [_at(legs[d.seg], (d.s_m - legs[d.seg].s0_m + TURN_LEAD_S * v) / u)[2] for d in drafts]
    return list(np.degrees(np.unwrap(np.radians(out))))


INTEREST_MAX_DEG = 15.0
INTEREST_RADIUS_M = 6.0
_INTEREST_FULL_M = 4.0
_INTEREST_FOV_DEG = 100.0


def _interest_offsets(drafts: list, base: list, interests, u: float) -> list:
    """Gentle gaze drift toward the nearest room ahead within INTEREST_RADIUS_M (<= INTEREST_MAX_DEG)."""
    if not interests:
        return [0.0] * len(drafts)
    pts = np.asarray(interests, dtype=float)
    out = []
    for d, b in zip(drafts, base):
        dist = np.hypot(pts[:, 0] - d.x, pts[:, 1] - d.y) * u
        rel = (np.degrees(np.arctan2(pts[:, 1] - d.y, pts[:, 0] - d.x)) - b + 180) % 360 - 180
        near = np.where((dist <= INTEREST_RADIUS_M) & (np.abs(rel) <= _INTEREST_FOV_DEG), dist, np.inf)
        if not np.isfinite(j := int(np.argmin(near))) or not np.isfinite(near[j]):
            out.append(0.0)
            continue
        weight = min(1.0, (INTEREST_RADIUS_M - dist[j]) / (INTEREST_RADIUS_M - _INTEREST_FULL_M))
        out.append(float(np.clip(rel[j], -INTEREST_MAX_DEG, INTEREST_MAX_DEG)) * weight)
    return out


_UTURN_WINDOW_M = 3.0
_UTURN_DEG = 120.0


def _turn_through_rooms(drafts: list, base: list, stops: list) -> list:
    """At a U-turn inside a room look, rotate the head through the room's side, like a person at a door."""
    b = list(base)
    for a, d in enumerate(drafts):
        if d.wp is None or not stops[d.wp]:
            continue
        idx = [i for i, e in enumerate(drafts) if e.seg == d.seg and abs(e.s_m - d.s_m) <= _UTURN_WINDOW_M]
        i0, i1 = max(idx[0] - 1, 0), min(idx[-1] + 1, len(drafts) - 1)   # the lead starts the turn early
        while drafts[i0].seg != d.seg:
            i0 += 1
        while drafts[i1].seg != d.seg:
            i1 -= 1
        if abs(delta := b[i1] - b[i0]) < _UTURN_DEG:
            continue
        look = stops[d.wp]["look_at"]
        bearing = math.degrees(math.atan2(look[1] - d.y, look[0] - d.x))
        alt = delta - math.copysign(360.0, delta)
        if abs(_wrap(bearing - b[i0] - alt / 2)) < abs(_wrap(bearing - b[i0] - delta / 2)):   # face the door mid-turn
            for k in range(i0 + 1, i1 + 1):
                b[k] = b[i0] + (b[k] - b[i0]) * alt / delta
            for k in range(i1 + 1, len(b)):
                b[k] += alt - delta
    return b


def _room_look_offsets(drafts: list, base: list, stops: list, v: float) -> list:
    """Per-draft (gaze offset, weight) toward the nearest active room look (clamped, eased by walking time)."""
    anchors = [(d.s_m, d.seg, stops[d.wp]) for d in drafts if d.wp is not None and stops[d.wp]]
    out = []
    for d, b in zip(drafts, base):
        best = None
        for s_a, seg, stop in anchors:
            dist, half = abs(d.s_m - s_a) / max(v, 1e-9), stop["dwell_s"] / 2
            w = 1.0 if dist <= half + 1e-6 else _smoothstep(1 - (dist - half) / _LOOK_EASE_S)
            if seg == d.seg and w > 0 and (best is None or dist < best[0]):
                bearing = math.degrees(math.atan2(stop["look_at"][1] - d.y, stop["look_at"][0] - d.x))
                best = (dist, w * max(-ROOM_LOOK_MAX_DEG, min(ROOM_LOOK_MAX_DEG, _wrap(bearing - b))), w)
        out.append(best[1:] if best else (0.0, 0.0))
    return out


LOOK_BRIDGE_S = 4.0


def _look_offset(d: _Draft, base: float, stop: dict) -> float:
    """Clamped gaze offset from base toward a stop's look target."""
    bearing = math.degrees(math.atan2(stop["look_at"][1] - d.y, stop["look_at"][0] - d.x))
    return max(-ROOM_LOOK_MAX_DEG, min(ROOM_LOOK_MAX_DEG, _wrap(bearing - base)))


def _look_runs(drafts: list, base: list, stops: list, v: float) -> list:
    """Runs of look anchors (draft indices) on one side of the walk, each under LOOK_BRIDGE_S from the next."""
    anchors = [i for i, d in enumerate(drafts) if d.wp is not None and stops[d.wp]]
    runs = [[a] for a in anchors[:1]]
    for a, b in zip(anchors, anchors[1:]):
        da, db = drafts[a], drafts[b]
        gap_m = db.s_m - da.s_m - v * (stops[da.wp]["dwell_s"] + stops[db.wp]["dwell_s"]) / 2
        same_side = _look_offset(da, base[a], stops[da.wp]) * _look_offset(db, base[b], stops[db.wp]) > 0
        if da.seg == db.seg and db.s_m > da.s_m and gap_m <= v * LOOK_BRIDGE_S and same_side:
            runs[-1].append(b)
        else:
            runs.append([b])
    return [r for r in runs if len(r) > 1]


def _bridge_looks(drafts: list, base: list, stops: list, v: float, looks: list) -> list:
    """A run of close looks to one side becomes one steady sweep from its first room to its last."""
    out = list(looks)
    for run in _look_runs(drafts, base, stops, v):
        a, b = run[0], run[-1]
        ya = base[a] + _look_offset(drafts[a], base[a], stops[drafts[a].wp])
        yb = base[b] + _look_offset(drafts[b], base[b], stops[drafts[b].wp])
        for i in range(a, b + 1):
            f = (drafts[i].s_m - drafts[a].s_m) / (drafts[b].s_m - drafts[a].s_m)
            out[i] = (ya + (yb - ya) * f - base[i], 1.0)
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
    at_stops = [i for i, d in enumerate(drafts) if d.wp is not None and stops[d.wp] and stops[d.wp]["pan"]]
    wanted = ([None] if start_pan and 0 not in at_stops else []) + at_stops   # a pan at the start is the start pan
    extra = ["Only 2 standing pans per video — extra ones are ignored"] if len(wanted) > MAX_PANS else []
    return wanted[:MAX_PANS], extra


def _insert_pans(drafts: list, chosen: list) -> list:
    """Drafts with a pan-end duplicate after each chosen anchor (start pan = after the first draft)."""
    out = []
    for i, d in enumerate(drafts):
        out.append(d)
        if i in chosen or (i == 0 and None in chosen):
            out.append(_Draft(d.x, d.y, d.s_m, d.travel, d.seg, None, cut_after=d.cut_after, pan=True, kind="pan"))
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


def _significant_steps(yaws: list) -> list:
    """(start index, signed change) of each keyframe step larger than _REVERSAL_STEP_DEG."""
    return [(i, b - a) for i, (a, b) in enumerate(zip(yaws, yaws[1:])) if abs(b - a) > _REVERSAL_STEP_DEG]


def _segments(drafts: list) -> list:
    """Index ranges of the cut-free segments."""
    out, lo = [], 0
    for i, d in enumerate(drafts):
        if d.cut_after or i == len(drafts) - 1:
            out.append(range(lo, i + 1))
            lo = i + 1
    return out


def _flips(drafts: list) -> list:
    """(amplitude, start, end) of each left-right head reversal, never spanning a cut."""
    out = []
    for seg in _segments(drafts):
        steps = _significant_steps([drafts[i].yaw for i in seg])
        out += [(min(abs(s1), abs(s2)), seg[i1], seg[i2 + 1])
                for (i1, s1), (i2, s2) in zip(steps, steps[1:]) if s1 * s2 < 0]
    return out


def _limit_reversals(drafts: list) -> None:
    """Flatten the smallest background (lead/drift) wobbles until reversals <= MAX_REVERSALS_PER_MIN."""
    minutes = max((drafts[-1].t_s - drafts[0].t_s) / 60.0, 1e-9)
    for _ in range(len(drafts) * 2):
        flips = _flips(drafts)
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


def _slow_for_turns(drafts: list) -> set:
    """Give each too-fast head turn more time by walking slower there (down to MIN_LOOK_SPEED_MPS)."""
    warnings = set()
    for i, (a, b) in enumerate(zip(drafts, drafts[1:])):
        dt, need = b.t_s - a.t_s, abs(b.yaw - a.yaw) / MAX_YAW_RATE_DPS
        if a.cut_after or need <= dt + 1e-9 or (ds := b.s_m - a.s_m) <= 0:
            continue
        if (grow := min(need, ds / MIN_LOOK_SPEED_MPS) - dt) > 1e-9 and _borrow_time(drafts, i, grow) < grow - 1e-6:
            warnings.add("Video too short for smooth head turns — some looks are shortened")
    return warnings


def _slew(drafts: list, order: range, ahead: int) -> None:
    """Clamp each yaw to within MAX_YAW_RATE_DPS of its already-processed neighbour (ahead = -1 or +1)."""
    for i in order:
        a, b = drafts[i], drafts[i + ahead]
        if (a if ahead > 0 else b).cut_after:
            continue
        limit = MAX_YAW_RATE_DPS * abs(b.t_s - a.t_s)
        a.yaw = min(max(a.yaw, b.yaw - limit), b.yaw + limit)


def _limit_turn_rate(drafts: list) -> list:
    """Kevin's rule: slow the walk (to MIN_LOOK_SPEED_MPS) first, then turn less; never faster."""
    warnings = _slow_for_turns(drafts)
    n = len(drafts)
    _slew(drafts, range(1, n), -1)          # forward: each keyframe within reach of the previous one
    _slew(drafts, range(n - 2, -1, -1), 1)  # backward: guarantees every pair, turning early into U-turns
    return sorted(warnings)


def _to_keyframes(drafts: list) -> list:
    """Public keyframes (yaw already continuous)."""
    return [Keyframe(d.t_s, d.x, d.y, float(d.yaw), d.hour, d.cut_after) for d in drafts]


def plan_keyframes(waypoints: list, *, units_to_metres: float, total_duration: float, smoothing: float = 1.0,
                   uturn_radius_m: float = 0.0, cuts=None, start_pan: bool = False,
                   interests=None) -> KeyframePlan:
    """House-style keyframe plan for a route of (x, y[, yaw_offset, time_of_day, stop]) waypoints."""
    if len(waypoints) < 2:
        raise ValueError("Need at least 2 waypoints")
    if not (math.isfinite(total_duration) and total_duration > 0):
        raise ValueError("Video length must be a positive number of seconds")
    if not (math.isfinite(units_to_metres) and units_to_metres > 0):
        raise ValueError("units_to_metres must be positive")
    u = units_to_metres
    legs, drafts, stops, offsets, spacing, look_s = _route(waypoints, smoothing, uturn_radius_m, cuts, u, total_duration)
    chosen, warnings = _choose_pans(drafts, stops, start_pan)
    drafts = _insert_pans(drafts, chosen)
    v, _ = _assign_times(drafts, total_duration)
    drafts = _with_look_edges(drafts, legs, stops, v, u, spacing)
    v, length_m = _assign_times(drafts, total_duration)
    base = _turn_through_rooms(drafts, _lead_yaw(drafts, legs, v, u), stops)
    for d, b, drift in zip(drafts, base, _interest_offsets(drafts, base, interests, u)):
        d.yaw = b + drift
    _limit_reversals(drafts)                        # background gaze only: deliberate looks and pans are exempt
    looks = _bridge_looks(drafts, base, stops, v, _room_look_offsets(drafts, base, stops, v))
    user = _user_offsets(drafts, offsets)
    for d, b, (r, w), o in zip(drafts, base, looks, user):
        d.yaw = b + r + (1 - w) * (d.yaw - b) + o
    _apply_pan_yaws(drafts, base, stops)
    drafts = _drop_look_anchors(drafts, stops, offsets, u)
    warnings = _speed_warning(v, length_m, len(chosen), look_s) + warnings + _limit_turn_rate(drafts)
    return KeyframePlan(_to_keyframes(drafts), u, warnings, len(chosen))
