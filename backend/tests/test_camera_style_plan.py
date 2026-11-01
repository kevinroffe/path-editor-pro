import math

import numpy as np
import pytest

import camera_style as cs
from tests.style_metrics import style_metrics

U = 0.01
L_ROUTE = [(0, 0), (6000, 0), (6000, 4000)]  # 100 m L in cm


def _plan(wps, duration, **kw):
    return cs.plan_keyframes(wps, units_to_metres=U, total_duration=duration, **kw)


def _dense(plan, n=2000):
    t = np.linspace(plan.keyframes[0].t_s, plan.keyframes[-1].t_s, n)
    return np.array([cs.sample_at(plan, x)[:2] for x in t])


def test_spacing_matches_house_style():
    plan = _plan(L_ROUTE, cs.suggest_duration_s(100))
    m = style_metrics(plan.keyframes, U)
    assert 2.8 <= m["s_per_kf"] <= 4.0
    assert 2.1 <= m["m_per_kf_med"] <= 4.0


def test_corner_gets_keyframe():
    plan = _plan(L_ROUTE, cs.suggest_duration_s(100))
    assert min(math.hypot(k.x - 6000, k.y) for k in plan.keyframes) <= 50


def test_mandatory_keyframes():
    wps = [(0, 0, 0, ""), (3000, 0, 0, "14:30"), (6000, 0, 0, "")]
    plan = _plan(wps, cs.suggest_duration_s(60))
    k = min(plan.keyframes, key=lambda k: math.hypot(k.x - 3000, k.y))
    assert math.hypot(k.x - 3000, k.y) <= 50 and k.hour == 14.5
    assert (plan.keyframes[0].x, plan.keyframes[0].y) == pytest.approx((0, 0), abs=1e-6)
    assert (plan.keyframes[-1].x, plan.keyframes[-1].y) == pytest.approx((6000, 0), abs=1e-6)


def test_duration_and_speed():
    dur = cs.suggest_duration_s(100)
    plan = _plan(L_ROUTE, dur)
    assert plan.keyframes[-1].t_s == pytest.approx(dur)
    assert 0.8 <= style_metrics(plan.keyframes, U)["speed_med"] <= 1.45
    assert plan.warnings == []


def test_too_short_video_warns():
    plan = _plan([(0, 0), (8500, 0)], 10)
    times = [k.t_s for k in plan.keyframes]
    assert all(b > a for a, b in zip(times, times[1:]))
    assert len(plan.warnings) == 1 and "too short" in plan.warnings[0]
    assert f"{cs.suggest_duration_s(85)} s" in plan.warnings[0]


def test_two_point_route():
    plan = _plan([(0, 0), (1000, 500)], 15)
    assert len(plan.keyframes) >= 2
    yaws = [k.yaw for k in plan.keyframes]
    assert max(yaws) - min(yaws) <= 0.5


def test_uturn_radius_is_metres():
    wps = [(0, 0), (3000, 0), (0, 100)]
    sharp = _dense(_plan(wps, 60))
    rounded = _dense(_plan(wps, 60, uturn_radius_m=3.0))
    assert sharp[:, 0].max() >= 2950          # sparse keyframes come within ~25 cm of the apex
    assert rounded[:, 0].max() <= 2750        # a 3 m radius (not 3 cm) keeps the camera well off it


def test_cut_splits_into_jump():
    plan = _plan([(0, 0), (2000, 0), (9000, 0), (11000, 0)], 40, cuts=[1])
    i = next(i for i, k in enumerate(plan.keyframes) if k.cut_after)
    a, b = plan.keyframes[i], plan.keyframes[i + 1]
    assert (a.x, b.x) == pytest.approx((2000, 9000), abs=1e-6)
    assert 0 < b.t_s - a.t_s <= 0.1


def test_stop_near_route_start_keeps_its_look():
    stop = {"room_id": "r", "room_name": "Room", "look_at": [60, 400], "dwell_s": 3.0}
    plan = _plan([(0, 0, 0, "", None), (60, 0, 0, "", stop), (5000, 0, 0, "", None)], 50)
    assert max(k.yaw for k in plan.keyframes[:4]) >= 30


def test_room_looks_do_not_crowd_keyframes():
    stop = {"room_id": "r", "room_name": "Room", "dwell_s": 3.0}
    wps = [(0, 0, 0, "", None)] + [(1500 * i, 0, 0, "", stop | {"look_at": [1500 * i, 400]}) for i in range(1, 7)] \
        + [(9000, 0, 0, "", None)]
    plan = _plan(wps, cs.suggest_duration_s(90))
    assert style_metrics(plan.keyframes, U)["s_per_kf"] >= 2.8


def test_suggest_duration():
    assert cs.suggest_duration_s(95) == 100            # designers walk 0.95 m/s (312-path median)
    assert cs.suggest_duration_s(5) == 10
    assert cs.suggest_duration_s(95, n_pans=2) == 110
    assert cs.suggest_duration_s(95, look_s=12) == 115      # 82 m + glances = the designers' 104 s median


def test_slow_designer_walk_does_not_warn():
    assert _plan([(0, 0), (7000, 0)], 100).warnings == []     # 0.7 m/s


def test_too_long_video_warns():
    plan = _plan([(0, 0), (5000, 0)], 100)                    # 0.5 m/s
    assert len(plan.warnings) == 1 and "too long" in plan.warnings[0]


def _office_row(n=20, gap=200):
    """A straight 40 m walk past n offices, each with a 2 s look."""
    stop = {"room_id": "r", "room_name": "Office", "dwell_s": 2.0}
    return [(0, 0, 0, "", None)] + [(gap * i, 0, 0, "", stop | {"look_at": [gap * i, 400]}) for i in range(1, n)] \
        + [(gap * n, 0, 0, "", None)]


def test_suggested_length_of_a_room_dense_route_does_not_warn():
    assert _plan(_office_row(), cs.suggest_duration_s(40, look_s=38)).warnings == []


def test_too_long_warning_suggests_walking_plus_looking_time():
    (w,) = _plan(_office_row(), 200).warnings
    assert "too long" in w and f"try {cs.suggest_duration_s(40, look_s=38)} s" in w
