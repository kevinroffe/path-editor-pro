import logging
import math
import xml.etree.ElementTree as ET

import route_processor as rp
from export_layer import MAX_KEYFRAMES, to_enscape_xml

FPS = 30.0


def _stops_route(n, duration, dwell=2.0):
    """n stops along +x, each looking up (+y) into a room."""
    wps = [(0, 0, 0, "")] + [(i * 300, 0, 0, "", {"look_at": [i * 300, 400], "dwell_s": dwell}) for i in range(1, n + 1)]
    wps.append(((n + 1) * 300, 0, 0, ""))
    return wps, rp.process_route(wps, total_duration=duration, fps=FPS)


def _keyframes(xml):
    """(x, z, yaw_deg) of every exported keyframe."""
    return [(float(k.find("Position").get("x")), float(k.find("Position").get("z")),
             math.degrees(math.atan2(float(k.find("LookAt").get("z")), float(k.find("LookAt").get("x")))))
            for k in ET.fromstring(xml).find("Keyframes")]


def _stop_coverage(frames, kfs):
    """Per dwell: (keyframes at its held position, whether one of them faces its look-in yaw)."""
    out = []
    for i, f in enumerate(frames):
        if f.dwell != "start":
            continue
        look = next(g.yaw for g in frames[i:] if g.dwell == "look")
        held = [k for k in kfs if abs(k[0] - f.x) < 1e-3 and abs(k[1] - f.y) < 1e-3]
        out.append((len(held), any(abs((k[2] - look + 180) % 360 - 180) < 1.0 for k in held)))
    return out


def test_xml_keeps_every_stop_when_thinned():
    wps, frames = _stops_route(12, 20.0)
    cov = _stop_coverage(frames, _keyframes(to_enscape_xml(frames, wps, {"duration": 20.0})))
    assert len(cov) == 12
    assert all(n >= 2 and look for n, look in cov)


def test_xml_keeps_every_stop_on_long_video():
    wps, frames = _stops_route(12, 400.0, dwell=1.0)
    kfs = _keyframes(to_enscape_xml(frames, wps, {"duration": 400.0}))
    assert len(kfs) <= MAX_KEYFRAMES
    assert all(n >= 2 and look for n, look in _stop_coverage(frames, kfs))


def test_xml_stop_keyframes_beat_even_spacing_at_the_cap(caplog):
    wps, frames = _stops_route(60, 400.0, dwell=2.0)
    with caplog.at_level(logging.WARNING, logger="export_layer"):
        kfs = _keyframes(to_enscape_xml(frames, wps, {"duration": 400.0}))
    assert all(n >= 2 and look for n, look in _stop_coverage(frames, kfs))
    assert "keyframe cap" in caplog.text


def test_xml_without_stops_unchanged():
    wps = [(0, 0, 0, ""), (500, 0, 0, ""), (1000, 300, 0, "")]
    frames = rp.process_route(wps, total_duration=30.0, fps=FPS)
    step = max(1, len(frames) // 30)
    expected = len(range(0, len(frames), step)) + (1 if (len(frames) - 1) % step else 0)
    assert len(_keyframes(to_enscape_xml(frames, wps, {"duration": 30.0}))) == expected
