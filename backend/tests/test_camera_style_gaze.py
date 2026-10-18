import math

import numpy as np
import pytest

import camera_style as cs
from tests.style_metrics import style_metrics

U = 0.01


def _stop(lx, ly, dwell=3.0, **kw):
    return {"room_id": "r", "room_name": "Room", "look_at": [lx, ly], "dwell_s": dwell, **kw}


def _plan(wps, duration, **kw):
    return cs.plan_keyframes(wps, units_to_metres=U, total_duration=duration, **kw)


def _rates(plan):
    k = plan.keyframes
    return [abs(b.yaw - a.yaw) / (b.t_s - a.t_s) for a, b in zip(k, k[1:]) if not a.cut_after and b.t_s > a.t_s]


def test_gaze_leads_turn():
    plan = _plan([(0, 0), (3000, 0), (3000, 3000)], cs.suggest_duration_s(60))
    corner = min(plan.keyframes, key=lambda k: math.hypot(k.x - 3000, k.y))
    yaw = cs.sample_at(plan, corner.t_s - 1.5)[2]
    assert yaw >= 0.2 * 90


def test_room_look_reaches_room():
    plan = _plan([(0, 0, 0, "", None), (2000, 0, 0, "", _stop(2000, 300)), (5000, 0, 0, "", None)], 50)
    window = [k for k in plan.keyframes if 1000 <= k.x <= 3000]
    best = min(abs(k.yaw - 90.0) for k in window)
    assert best <= 15 or 55 <= max(abs(k.yaw) for k in window) <= 60.5   # head rule may trim the cap a little


def test_room_look_capped_at_60():
    plan = _plan([(0, 0, 0, "", None), (2000, 0, 0, "", _stop(1000, 10)), (5000, 0, 0, "", None)], 50)
    assert 55 <= max(abs(k.yaw) for k in plan.keyframes) <= 60.5


def test_look_is_held_for_its_look_time():
    plan = _plan([(0, 0, 0, "", None), (2000, 0, 0, "", _stop(2000, 300, dwell=3.0)), (6000, 0, 0, "", None)], 60)
    peak = max(abs(k.yaw) for k in plan.keyframes)
    held = [k for k in plan.keyframes if abs(k.yaw) >= peak - 5]   # the 25 deg/s rule may trim the edges a little
    assert held[-1].t_s - held[0].t_s == pytest.approx(3.0, abs=0.3)


def test_turn_rate_never_exceeds_cap():
    wps = [(0, 0, 0, "", None), (2000, 0, 0, "", _stop(2000, 300, dwell=1.0)),
           (2300, 0, 0, "", _stop(2300, -300, dwell=1.0)), (4000, 0, 0, "", None), (4000, 3000, 0, "", None)]
    plan = _plan(wps, 60)
    assert max(_rates(plan)) <= cs.MAX_YAW_RATE_DPS + 1e-6


def _speed_into_window(plan, x_from):
    a = min(plan.keyframes, key=lambda k: abs(k.x - x_from))
    b = plan.keyframes[plan.keyframes.index(a) + 1]
    return (b.x - a.x) * U / (b.t_s - a.t_s), b


def test_slow_down_before_turning_less():
    # look window edge at x = 2945 (stop at 3000, dwell 1 s at 1.1 m/s); a time-of-day keyframe 2 m earlier
    wps = [(0, 0, 0, "", None), (745, 0, 0, "", None), (2745, 0, 0, "12:00", None),
           (3000, 0, 0, "", _stop(3000, 1000, dwell=1.0)), (5500, 0, 0, "", None)]
    plan = _plan(wps, 50)
    speed, edge = _speed_into_window(plan, 2745)
    assert cs.MIN_LOOK_SPEED_MPS - 0.01 <= speed < 1.0
    assert abs(edge.yaw) == pytest.approx(60, abs=0.5)
    assert plan.keyframes[-1].t_s == pytest.approx(50)


def test_turn_less_when_slowing_is_not_enough():
    wps = [(0, 0, 0, "", None), (745, 0, 0, "", None), (2840, 0, 0, "12:00", None),
           (3000, 0, 0, "", _stop(3000, 1000, dwell=1.0)), (5500, 0, 0, "", None)]
    plan = _plan(wps, 50)
    speed, edge = _speed_into_window(plan, 2840)
    assert speed == pytest.approx(cs.MIN_LOOK_SPEED_MPS, abs=0.01)
    assert 0 < abs(edge.yaw) < 60
    assert plan.keyframes[-1].t_s == pytest.approx(50)


def test_adjacent_rooms_blend():
    wps = [(0, 0, 0, "", None), (2000, 0, 0, "", _stop(2000, 300, dwell=1.5)),
           (2200, 0, 0, "", _stop(2200, -300, dwell=1.5)), (5000, 0, 0, "", None)]
    plan = _plan(wps, 50)
    k = plan.keyframes
    a = min(range(len(k)), key=lambda i: abs(k[i].x - 2000))
    b = min(range(len(k)), key=lambda i: abs(k[i].x - 2200))
    seg = [x.yaw for x in k[a:b + 1]]
    assert all(y2 <= y1 + 0.5 for y1, y2 in zip(seg, seg[1:]))
    assert style_metrics(k, U)["reversals_per_min"] <= 8


def test_uturn_head_turn():
    plan = _plan([(0, 0), (3000, 0), (0, 150)], cs.suggest_duration_s(60))
    assert max(_rates(plan)) <= cs.MAX_YAW_RATE_DPS + 1e-6
    k = plan.keyframes
    speeds = [(math.hypot(b.x - a.x, b.y - a.y) * U) / (b.t_s - a.t_s) for a, b in zip(k, k[1:])]
    assert min(speeds) >= cs.MIN_LOOK_SPEED_MPS - 0.01


def test_user_yaw_offset_eased():
    wps = [(0, 0, 0, ""), (2500, 0, 45, ""), (6000, 0, 0, "")]
    plan = _plan(wps, 60)
    k = min(plan.keyframes, key=lambda k: abs(k.x - 2500))
    assert k.yaw == pytest.approx(45, abs=1)
    assert max(_rates(plan)) <= cs.MAX_YAW_RATE_DPS + 1e-6
    wrapped = _plan([(0, 0, 0, ""), (2500, 0, 350, ""), (6000, 0, 0, "")], 60)
    k = min(wrapped.keyframes, key=lambda k: abs(k.x - 2500))
    assert k.yaw == pytest.approx(-10, abs=1)


def test_reversal_limit():
    wps = [(0, 0, 0, "", None)] + [
        (800 + 400 * i, 0, 0, "", _stop(800 + 400 * i, 300 if i % 2 else -300, dwell=0.5)) for i in range(6)
    ] + [(3300, 0, 0, "", None)]
    plan = _plan(wps, 30)
    assert style_metrics(plan.keyframes, U)["reversals_per_min"] <= cs.MAX_REVERSALS_PER_MIN + 1e-9
    assert np.all(np.isfinite([k.yaw for k in plan.keyframes]))


def test_uturn_at_a_room_turns_through_the_room():
    # out along +x to a door at the dead end, back along y=+10 cm; the room is on the -y side
    stop = {"room_id": "r", "room_name": "Room", "look_at": [3000, -400], "dwell_s": 2.0}
    plan = _plan([(0, 0, 0, "", None), (3000, 0, 0, "", stop), (0, 10, 0, "", None)], cs.suggest_duration_s(60))
    near = [k for k in plan.keyframes if math.hypot(k.x - 3000, k.y) <= 300]
    err = min(abs((k.yaw - math.degrees(math.atan2(-400 - k.y, 3000 - k.x)) + 180) % 360 - 180) for k in near)
    assert err <= 30


def test_gaze_drifts_toward_passing_rooms():
    rooms = [(500 + 600 * i, 350) for i in range(10)]   # offices along one wall
    plan = _plan([(0, 0), (6500, 0)], cs.suggest_duration_s(65), interests=rooms)
    m = style_metrics(plan.keyframes, U)
    assert 8 <= m["look_vs_travel_med"] <= 32
    assert m["reversals_per_min"] <= cs.MAX_REVERSALS_PER_MIN + 1e-9
    assert max(abs(k.yaw) for k in plan.keyframes) <= cs.INTEREST_MAX_DEG + 1e-6


def test_no_interests_means_straight_gaze():
    plan = _plan([(0, 0), (6500, 0)], cs.suggest_duration_s(65))
    assert max(abs(k.yaw) for k in plan.keyframes) <= 0.5


def test_dead_end_door_is_reached_not_stood_short_of():
    stop = {"room_id": "r", "room_name": "Room", "look_at": [3000, 400], "dwell_s": 3.0}
    plan = _plan([(0, 0, 0, "", None), (3000, 0, 0, "", stop), (0, 0, 0, "", None)], cs.suggest_duration_s(60))
    assert max(k.x for k in plan.keyframes) >= 2950
    assert style_metrics(plan.keyframes, U)["n_pans"] == 0
