"""House-style metrics of a keyframe list (port of the reference-path analysis)."""
import numpy as np

_PAN_M = 0.05      # a keyframe pair closer than this is a standing pan
_REVERSAL_DEG = 3  # yaw steps smaller than this don't count toward reversals


def _wrap(a):
    return (np.asarray(a) + 180.0) % 360.0 - 180.0


def style_metrics(keyframes: list, units_to_metres: float) -> dict:
    """Keyframe spacing, speed, head-turn rate, reversals, look-vs-travel and pan count."""
    t = np.array([k.t_s for k in keyframes])
    xy = np.array([(k.x, k.y) for k in keyframes]) * units_to_metres
    yaw = np.array([k.yaw for k in keyframes])
    seg, dt, dyaw = np.hypot(*np.diff(xy, axis=0).T), np.diff(t), np.diff(yaw)
    moving = seg > _PAN_M
    travel = np.degrees(np.arctan2(*np.diff(xy, axis=0).T[::-1]))
    rate = np.abs(dyaw) / np.maximum(dt, 1e-6)
    sign = np.sign(dyaw[np.abs(dyaw) > _REVERSAL_DEG])
    reversals = int(np.sum(sign[1:] != sign[:-1])) if len(sign) > 1 else 0
    look = np.abs(_wrap(yaw[:-1][moving] - travel[moving]))
    return {
        "s_per_kf": float(t[-1] / max(len(t) - 1, 1)),
        "m_per_kf_med": float(np.median(seg[moving])) if moving.any() else 0.0,
        "speed_med": float(np.median(seg[moving] / np.maximum(dt[moving], 1e-6))) if moving.any() else 0.0,
        "yaw_rate_p90": float(np.percentile(rate, 90)),
        "yaw_rate_max": float(rate.max()),
        "reversals_per_min": reversals / max(t[-1] / 60.0, 1e-9),
        "look_vs_travel_med": float(np.median(look)) if len(look) else 0.0,
        "n_pans": int(np.sum(~moving & (dt > 0.5))),
    }
