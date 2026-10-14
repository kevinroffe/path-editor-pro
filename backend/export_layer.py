"""
export_layer.py
---------------
Exports camera route to:
  • JSON  — generic, full fidelity
  • XML   — Enscape VideoPath format (matches real Enscape XML exactly)

Enscape XML format (reverse-engineered from real Enscape exports):
  <VideoPath version="1" easingInOut="1" shakyCam="0">
    <Keyframes count="N">
      <Keyframe order="0" [timestampSeconds="..."]>
        <Position x="..." y="..." z="..." />
        <LookAt x="..." y="..." z="..." />       ← normalised direction vector
      </Keyframe>
    </Keyframes>
  </VideoPath>

Coordinate system mapping
--------------------------
  DXF/model space:  X = East,  Y = North,  Z = Up
  SVG editor space: X = East,  Y = Down (Y flipped for display)
  Enscape space:    X = East,  Y = Up,     Z = South  (right-handed, Y-up)

  So when reading frame coords from the route processor (SVG space):
    Enscape X  =  frame.x  × units_to_metres
    Enscape Y  =  camera_height_m                (constant, in metres)
    Enscape Z  =  frame.y  × units_to_metres     (svg_y = -model_y, Enscape Z = -model_y)

  LookAt direction vector (normalised, Y=0 = horizontal):
    yaw is computed in SVG space as atan2(svg_dy, svg_dx)
    LookAt.x = cos(yaw_rad)
    LookAt.y = sin(pitch_rad)  ≈ 0 for horizontal camera
    LookAt.z = sin(yaw_rad)    (svg_dy already accounts for Y-flip)
"""

from __future__ import annotations
import json
import logging
import math
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import List, Dict, Any
from route_processor import CameraFrame

log = logging.getLogger(__name__)

MAX_KEYFRAMES = 200


# ── JSON ──────────────────────────────────────────────────────────────────────

def to_json(frames: List[CameraFrame], waypoints: list, meta: Dict[str, Any]) -> str:
    payload = {
        "meta": meta,
        "waypoints": waypoints,
        "frames": [
            {
                "t":         round(f.t, 6),
                "x":         round(f.x, 4),
                "y":         round(f.y, 4),
                "z":         round(f.z, 4),
                "yaw_deg":   round(f.yaw, 4),
                "pitch_deg": round(f.pitch, 4),
                "fov":       f.fov,
                "cut":       bool(f.cut),
            }
            for f in frames
        ],
    }
    return json.dumps(payload, indent=2)


# ── Enscape XML ───────────────────────────────────────────────────────────────

def _parse_time_of_day(hhmm: str):
    """Convert 'HH:MM' string to decimal hours (e.g. '14:30' → 14.5). Returns None if blank."""
    if not hhmm or not hhmm.strip():
        return None
    try:
        parts = hhmm.strip().split(':')
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return max(0.0, min(24.0, h + m / 60.0))
    except Exception:
        return None


def _keyframe_indices(frames: List[CameraFrame], duration: float) -> set:
    """Frames to export: ~1 per second (2..MAX_KEYFRAMES) plus every cut and room-stop dwell keyframe.

    Enscape interpolates, so we don't need every frame. Frames flagged `cut`
    (and the frame right after, where the jump lands) are always kept, so a hard
    cut survives thinning as two closely-timed keyframes rather than being
    smoothed away. Dwell start / look-in / end frames are kept the same way, so
    every room stop holds and looks in at any video length; when they and the
    even ones can't all fit under the cap, the even spacing gives way.
    """
    n = len(frames)
    target_kf = max(2, min(MAX_KEYFRAMES, int(duration)))
    forced = {j for i, f in enumerate(frames) if f.cut for j in (i, min(i + 1, n - 1))}
    if not (dwell := {i for i, f in enumerate(frames) if f.dwell}):
        return set(range(0, n, max(1, n // target_kf))) | forced
    forced |= dwell | {n - 1}
    if (budget := min(target_kf, MAX_KEYFRAMES - len(forced))) < 2:
        log.warning("Enscape export: %d stop/cut keyframes exceed the %d keyframe cap; keeping them all",
                    len(forced), MAX_KEYFRAMES)
    return set(range(0, n, max(1, math.ceil(n / max(budget, 1))))) | forced


def to_enscape_xml(frames: List[CameraFrame], waypoints: list, meta: Dict[str, Any]) -> str:
    duration    = float(meta.get("duration",        30.0))
    height_m    = 1.75   # fixed — camera always at 1.75 m
    units_to_m  = float(meta.get("units_to_metres",  1.0))

    # Parse per-waypoint time-of-day values (index 3 in each waypoint tuple if present)
    tod_values = []
    for wp in waypoints:
        raw = wp[3] if len(wp) > 3 else ''
        tod_values.append(_parse_time_of_day(str(raw)))

    # Build arc-length normalised parameter for each waypoint so we can interpolate
    # time-of-day across frames by t position (same logic as route_processor)
    has_tod = any(v is not None for v in tod_values)

    keyframes = [frames[i] for i in sorted(_keyframe_indices(frames, duration))]
    # Always include last frame
    if keyframes[-1] is not frames[-1]:
        keyframes.append(frames[-1])

    walk_mode = int(bool(meta.get("walk_mode", True)))

    # ── XML structure ─────────────────────────────────────────────────────────
    root = ET.Element("VideoPath")
    root.set("version",     "1")
    root.set("easingInOut", "1")
    root.set("shakyCam",    "0")
    root.set("walkMode",    str(walk_mode))

    kfs_el = ET.SubElement(root, "Keyframes")
    kfs_el.set("count", str(len(keyframes)))

    for i, f in enumerate(keyframes):
        kf = ET.SubElement(kfs_el, "Keyframe")
        kf.set("order", str(i))

        # Timestamp in seconds
        ts = f.t * duration
        kf.set("timestampSeconds", f"{ts:.4f}")

        # ── Position ─────────────────────────────────────────────────────────
        # SVG x = model_x,  SVG y = -model_y  → Enscape Z = -model_y = SVG y
        pos = ET.SubElement(kf, "Position")
        pos.set("x", f"{f.x  * units_to_m:.6f}")   # Enscape X = model X
        pos.set("y", f"{height_m:.6f}")              # Enscape Y = camera height (metres)
        pos.set("z", f"{f.y  * units_to_m:.6f}")    # Enscape Z = SVG y = -model_y

        # ── LookAt (normalised direction vector) ──────────────────────────────
        yaw_rad   = math.radians(f.yaw)
        pitch_rad = math.radians(f.pitch)
        lx = math.cos(yaw_rad) * math.cos(pitch_rad)
        ly = math.sin(pitch_rad)
        lz = math.sin(yaw_rad) * math.cos(pitch_rad)
        mag = math.sqrt(lx*lx + ly*ly + lz*lz) or 1.0

        lookat = ET.SubElement(kf, "LookAt")
        lookat.set("x", f"{lx/mag:.6f}")
        lookat.set("y", f"{ly/mag:.6f}")
        lookat.set("z", f"{lz/mag:.6f}")

        # ── Time of Day (optional) ────────────────────────────────────────────
        if has_tod:
            # Interpolate between waypoint tod values using frame's t position.
            # Waypoints without a tod value inherit from their nearest neighbour
            # that has one set.  If none have a value, skip entirely.
            n_wp = len(tod_values)
            # Build a list of (t, tod) pairs only for waypoints that have a value
            known = [(j / max(n_wp-1,1), tod_values[j])
                     for j in range(n_wp) if tod_values[j] is not None]
            if known:
                # Clamp to first/last known value outside their range
                if f.t <= known[0][0]:
                    tod = known[0][1]
                elif f.t >= known[-1][0]:
                    tod = known[-1][1]
                else:
                    # Linear interpolation between surrounding known points
                    for k_idx in range(len(known)-1):
                        t0, v0 = known[k_idx]
                        t1, v1 = known[k_idx+1]
                        if t0 <= f.t <= t1:
                            blend = (f.t - t0) / (t1 - t0) if t1 > t0 else 0.0
                            tod = v0 + (v1 - v0) * blend
                            break
                    else:
                        tod = known[-1][1]
                tod_el = ET.SubElement(kf, "TimeOfDay")
                tod_el.set("value", f"{tod:.6f}")

    # ── Pretty print ─────────────────────────────────────────────────────────
    raw = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(raw)
    pretty = dom.toprettyxml(indent="    ", encoding=None)
    # minidom adds its own declaration; replace it with the exact Enscape one
    lines = pretty.splitlines()
    lines[0] = '<?xml version="1.0" ?>'
    return '\n'.join(lines)
