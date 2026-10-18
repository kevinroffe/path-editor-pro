import math

import pytest

import camera_style as cs
from route_processor import _clean_stop
from tests.style_metrics import style_metrics

U = 0.01


def _stop(lx, ly, pan=False, dwell=2.0):
    s = {"room_id": "r", "room_name": "Room", "look_at": [lx, ly], "dwell_s": dwell}
    return s | ({"pan": True} if pan else {})


def _plan(wps, duration, **kw):
    return cs.plan_keyframes(wps, units_to_metres=U, total_duration=duration, **kw)


def _pan_pairs(plan):
    k = plan.keyframes
    return [(a, b) for a, b in zip(k, k[1:]) if math.hypot(b.x - a.x, b.y - a.y) <= 1 and b.t_s - a.t_s > 1]


def test_stop_pan_two_keyframes():
    plan = _plan([(0, 0, 0, "", None), (3000, 0, 0, "", _stop(3000, 400, pan=True)), (6000, 0, 0, "", None)], 65)
    (a, b), = _pan_pairs(plan)
    assert b.t_s - a.t_s == pytest.approx(cs.PAN_DURATION_S, abs=0.05)
    assert 0 < abs(b.yaw - a.yaw) <= cs.PAN_MAX_DEG
    assert abs(b.yaw) > abs(a.yaw)                 # swept further toward the room (left, +y)
    assert abs(b.yaw - a.yaw) / (b.t_s - a.t_s) <= cs.MAX_YAW_RATE_DPS
    assert plan.pans == 1 and plan.keyframes[-1].t_s == pytest.approx(65)


def test_start_pan():
    plan = _plan([(0, 0), (6000, 0)], 60, start_pan=True)
    k0, k1, k2 = plan.keyframes[:3]
    assert (k0.x, k0.y) == pytest.approx((k1.x, k1.y))
    assert k1.t_s - k0.t_s == pytest.approx(cs.PAN_DURATION_S, abs=0.05)
    assert k2.x > k1.x
    assert plan.pans == 1


def test_max_two_pans():
    wps = [(0, 0, 0, "", None)] + [(1500 * i, 0, 0, "", _stop(1500 * i, 400, pan=True)) for i in (1, 2, 3)] \
        + [(6000, 0, 0, "", None)]
    plan = _plan(wps, 75, start_pan=True)
    assert plan.pans == 2
    pairs = _pan_pairs(plan)
    assert len(pairs) == 2
    assert pairs[0][0].x == pytest.approx(0) and pairs[1][0].x == pytest.approx(1500, abs=1)
    assert sum("Only 2 standing pans" in w for w in plan.warnings) == 1


def test_no_pans_by_default():
    wps = [(0, 0, 0, "", None), (3000, 0, 0, "", _stop(3000, 400)), (6000, 0, 0, "", None)]
    plan = _plan(wps, 60)
    assert style_metrics(plan.keyframes, U)["n_pans"] == 0 and plan.pans == 0


def test_pan_respects_cut():
    wps = [(0, 0, 0, "", None), (2000, 0, 0, "", _stop(2000, 400, pan=True)),
           (9000, 0, 0, "", None), (11000, 0, 0, "", None)]
    plan = _plan(wps, 50, cuts=[1])
    (a, b), = _pan_pairs(plan)
    assert a.x == pytest.approx(2000, abs=1) and b.x == pytest.approx(2000, abs=1)
    assert b.cut_after and not a.cut_after
    nxt = plan.keyframes[plan.keyframes.index(b) + 1]
    assert nxt.x == pytest.approx(9000, abs=1) and 0 < nxt.t_s - b.t_s <= 0.1


def test_clean_stop_keeps_pan():
    base = {"look_at": [1, 2], "dwell_s": 2}
    assert _clean_stop(base | {"pan": True})["pan"] is True
    assert _clean_stop(base | {"pan": "yes"})["pan"] is False
    assert _clean_stop(base)["pan"] is False
