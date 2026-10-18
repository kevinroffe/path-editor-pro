"""
export_layer.py
---------------
Exports camera route to:
  • JSON  — generic, full fidelity
  • XML   — Enscape VideoPath format (matches real Enscape XML exactly)

Enscape XML format (reverse-engineered from real Enscape exports):
  <VideoPath version="1" easingInOut="1" shakyCam="0" walkMode="1">
    <Keyframes count="N">
      <Keyframe order="0" [hour="..."] timestampSeconds="...">
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
    Enscape Y  =  EYE_HEIGHT_M (1.57 m, house style)
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
from camera_style import EYE_HEIGHT_M, KeyframePlan
from route_processor import CameraFrame

log = logging.getLogger(__name__)

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

def _look_at(yaw_deg: float, pitch_deg: float = 0.0) -> tuple:
    """Unit LookAt vector (x, y, z) from yaw/pitch in SVG/display space."""
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    return math.cos(yaw) * math.cos(pitch), math.sin(pitch), math.sin(yaw) * math.cos(pitch)


def to_enscape_xml(plan: KeyframePlan, meta: Dict[str, Any]) -> str:
    """Enscape VideoPath XML with exactly the planned house-style keyframes."""
    u = plan.units_to_metres
    root = ET.Element("VideoPath", {"version": "1", "easingInOut": "1", "shakyCam": "0",
                                    "walkMode": str(int(bool(meta.get("walk_mode", True))))})
    kfs_el = ET.SubElement(root, "Keyframes", {"count": str(len(plan.keyframes))})
    for i, k in enumerate(plan.keyframes):
        kf = ET.SubElement(kfs_el, "Keyframe", {"order": str(i)})
        if k.hour is not None:
            kf.set("hour", f"{k.hour:.4f}")
        kf.set("timestampSeconds", f"{k.t_s:.4f}")
        # SVG x = model_x, SVG y = -model_y  ->  Enscape X = model X, Enscape Z = SVG y
        ET.SubElement(kf, "Position", {"x": f"{k.x * u:.6f}", "y": f"{EYE_HEIGHT_M:.6f}", "z": f"{k.y * u:.6f}"})
        lx, ly, lz = _look_at(k.yaw)
        ET.SubElement(kf, "LookAt", {"x": f"{lx:.6f}", "y": f"{ly:.6f}", "z": f"{lz:.6f}"})
    pretty = minidom.parseString(ET.tostring(root, encoding="unicode")).toprettyxml(indent="    ")
    lines = pretty.splitlines()
    lines[0] = '<?xml version="1.0" ?>'
    return "\n".join(lines)
