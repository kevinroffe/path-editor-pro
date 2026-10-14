import itertools
import math

import pytest

import route_processor as rp

FPS = 30.0


def _wrap(d):
    return (d + 180) % 360 - 180


def _route(stop=None, duration=20.0, glances=None, radius=0.0):
    wps = [(0, 0, 0, ""), (500, 0, 0, "", stop), (1000, 0, 0, "")]
    return rp.process_route(wps, total_duration=duration, fps=FPS, glances=glances, glance_radius=radius)


def _longest_hold(frames):
    xs = [(round(f.x, 6), round(f.y, 6)) for f in frames]
    return max(sum(1 for _ in g) for _, g in itertools.groupby(xs))


def test_dwell_freezes_position_and_faces_room():
    frames = _route({"look_at": [500, 400], "dwell_s": 3.0})
    assert _longest_hold(frames) >= int(3.0 * FPS) - 2
    held = [f for f in frames if abs(f.x - 500) < 30 and abs(f.y) < 1e-6]
    assert any(abs(_wrap(f.yaw - 90.0)) < 2.0 for f in held)


def test_turn_rate_never_exceeds_cap():
    frames = _route({"look_at": [500, -400], "dwell_s": 3.0})
    step = rp._MAX_YAW_RATE_DEG_PER_SEC / FPS + 1e-6
    assert all(abs(_wrap(b.yaw - a.yaw)) <= step for a, b in zip(frames, frames[1:]))


def test_total_duration_respected():
    frames = _route({"look_at": [500, 400], "dwell_s": 3.0}, duration=20.0)
    assert len(frames) == pytest.approx(20.0 * FPS, abs=3)
    assert frames[0].t == 0.0 and frames[-1].t == pytest.approx(1.0)


def test_dwells_capped_at_half_duration():
    frames = _route({"look_at": [500, 400], "dwell_s": 50.0}, duration=10.0)
    assert _longest_hold(frames) <= int(0.5 * 10.0 * FPS) + 2


def test_glance_bounded_and_toward_room():
    base = _route(duration=10.0)
    glanced = _route(duration=10.0, glances=[((500, 50), (500, 400))], radius=120)
    diffs = [_wrap(g.yaw - b.yaw) for g, b in zip(glanced, base)]
    assert max(abs(d) for d in diffs) <= rp.GLANCE_MAX_DEG + 1e-6
    assert max(diffs) > 5.0          # turned left (toward +y) near x=500


def test_glance_suppressed_while_turning():
    wps = [(0, 0, 0, ""), (500, 0, 0, ""), (500, 500, 0, "")]
    base = rp.process_route(wps, total_duration=10.0, fps=FPS)
    glanced = rp.process_route(wps, total_duration=10.0, fps=FPS,
                               glances=[((500, 0), (900, 0))], glance_radius=60)
    corner = [i for i, f in enumerate(base) if math.hypot(f.x - 500, f.y) < 20]
    assert all(abs(_wrap(glanced[i].yaw - base[i].yaw)) < 5.0 for i in corner)


def test_four_element_waypoints_unchanged():
    wps = [(0, 0, 0, ""), (500, 0, 0, ""), (1000, 0, 0, "")]
    a = rp.process_route(wps, total_duration=5.0, fps=FPS)
    assert len(a) == pytest.approx(5.0 * FPS, abs=2)
