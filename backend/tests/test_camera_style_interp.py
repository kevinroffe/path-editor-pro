import math

import pytest

import camera_style as cs
from tests.style_metrics import style_metrics

U = 0.01  # 1 plan unit = 1 cm
FPS = 30.0


def _plan(kfs, units=U):
    return cs.KeyframePlan(keyframes=[cs.Keyframe(*k) for k in kfs], units_to_metres=units)


FOUR = [(0.0, 0.0, 0.0, 0.0), (3.0, 300.0, 0.0, 10.0), (6.0, 600.0, 100.0, 30.0), (9.0, 900.0, 100.0, 30.0)]


def _wrap(d):
    return (d + 180) % 360 - 180


def test_sample_at_hits_keyframes():
    plan = _plan(FOUR)
    for k in plan.keyframes:
        x, y, yaw = cs.sample_at(plan, k.t_s)
        assert math.hypot(x - k.x, y - k.y) <= 1.0
        assert abs(yaw - k.yaw) <= 0.5


def test_interpolate_starts_and_ends_on_keyframes():
    frames = cs.interpolate(_plan(FOUR), FPS)
    assert (frames[0].x, frames[0].y) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert (frames[-1].x, frames[-1].y) == pytest.approx((900.0, 100.0), abs=1e-6)
    assert frames[0].t == 0.0 and frames[-1].t == pytest.approx(1.0)


def test_interpolate_eases_start_and_end():
    frames = cs.interpolate(_plan([(0.0, 0.0, 0.0, 0.0), (20.0, 2000.0, 0.0, 0.0)]), FPS)
    assert len(frames) == pytest.approx(20.0 * FPS, abs=1)
    step = [math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(frames, frames[1:])]
    mid = step[len(step) // 2]
    n = int(0.2 * FPS)
    assert max(step[:n]) < 0.3 * mid
    assert max(step[-n:]) < 0.3 * mid


def test_interpolate_yaw_rate_bounded():
    kfs = [(3.0 * i, 300.0 * i, 0.0, (25.0 * 3.0) * (i % 2)) for i in range(21)]  # secant exactly 25 deg/s
    plan = _plan(kfs)
    frames = cs.interpolate(plan, FPS)
    total = kfs[-1][0]
    bound = 1.5 * 25.0 * total / (total - cs.EASE_S) / FPS + 1e-6
    assert max(abs(b.yaw - a.yaw) for a, b in zip(frames, frames[1:])) <= bound


def test_interpolate_cut_is_jump():
    kfs = [(0.0, 0.0, 0.0, 0.0), (3.0, 300.0, 0.0, 0.0), (3.05, 5000.0, 0.0, 0.0), (6.0, 5300.0, 0.0, 0.0)]
    plan = _plan(kfs)
    plan.keyframes[1].cut_after = True
    frames = cs.interpolate(plan, FPS)
    assert not any(300.0 + 1e-6 < f.x < 5000.0 - 1e-6 for f in frames)
    jump = next(i for i, (a, b) in enumerate(zip(frames, frames[1:])) if b.x - a.x > 1000)
    assert frames[jump].cut


def test_interpolate_height_is_eye_height():
    assert all(f.z == cs.EYE_HEIGHT_M for f in cs.interpolate(_plan(FOUR), FPS))


def test_yaw_stays_continuous_past_180():
    plan = _plan([(0.0, 0.0, 0.0, 170.0), (3.0, 300.0, 0.0, 200.0), (6.0, 600.0, 0.0, 230.0)])
    frames = cs.interpolate(plan, FPS)
    assert max(abs(b.yaw - a.yaw) for a, b in zip(frames, frames[1:])) < 5.0
    assert frames[-1].yaw == pytest.approx(230.0, abs=0.01)


def test_style_metrics_on_reference_like_plan():
    kfs = [cs.Keyframe(3.3 * i, 330.0 * i, 0.0, 0.0) for i in range(10)]
    m = style_metrics(kfs, U)
    assert m["s_per_kf"] == pytest.approx(3.3, abs=0.01)
    assert m["speed_med"] == pytest.approx(1.0, abs=0.01)
    assert m["n_pans"] == 0
    assert m["reversals_per_min"] == 0


def test_style_metrics_counts_pans_and_rates():
    kfs = [cs.Keyframe(0.0, 0.0, 0.0, 0.0), cs.Keyframe(5.0, 0.0, 0.0, 60.0), cs.Keyframe(8.0, 300.0, 0.0, 60.0)]
    m = style_metrics(kfs, U)
    assert m["n_pans"] == 1
    assert m["yaw_rate_max"] == pytest.approx(12.0)
    assert _wrap(m["look_vs_travel_med"]) == pytest.approx(60.0)
