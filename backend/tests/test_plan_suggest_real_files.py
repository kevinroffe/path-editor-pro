"""Suggested tours on real plans, scored against the hand-made Enscape path a designer drew for the same plan."""
import glob
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString, Point

import app as app_module
import plan_suggest as ps

DOWNLOADS = Path(r"C:\Users\kevin\Downloads")
PATHS = Path(r"C:\Users\kevin\Desktop\path learn")
# design id -> least share of the designer's keyframes within 2 m of the suggested route (measured minus ~0.05).
# 265 Franklin's detected entrance is in the core, so it walks the same ring loop the other way round.
FLOORS = {"80651469900001": 0.5, "80686470500001": 0.68, "80748471340000": 0.8, "80751471360002": 0.8,
          "80816472360001": 0.33}
PAIRS = [(pid, DOWNLOADS / f"{pid}.json", next(iter(glob.glob(str(PATHS / f"*{pid}*.xml"))), None)) for pid in FLOORS]
PAIRS = [p for p in PAIRS if p[1].exists() and p[2]]
if not PAIRS:
    pytest.skip("real design JSONs / designer paths not available", allow_module_level=True)


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _designer_points(xml_path: str, plan) -> list:
    """The designer's keyframe positions in plan display units."""
    ox, oz = plan.enscape_offset
    u = plan.units_to_metres
    return [((float(p.get("x")) - ox) / u, (float(p.get("z")) - oz) / u)
            for p in ET.parse(xml_path).getroot().iter("Position")]


@pytest.mark.parametrize("pid, design, xml_path", PAIRS, ids=[p[0] for p in PAIRS])
def test_suggested_tour_walks_like_the_designer(client, pid, design, xml_path):
    with open(design, "rb") as f:
        assert client.post("/api/upload-qbiq-design", data={"json_file": (f, design.name)},
                           content_type="multipart/form-data").status_code == 200
    plan = app_module._LAST_PLAN
    u = plan.units_to_metres
    t0 = time.monotonic()
    tour = client.post("/api/auto-tour", json={"suggest": True}).get_json()
    assert time.monotonic() - t0 < 10, "suggestion too slow"
    route = LineString([p[:2] for p in tour["waypoints"]])
    assert route.length * u <= 1.15 * ps.TOUR_LENGTH_M
    closed = [r.polygon.buffer(-0.3 / u) for r in plan.rooms if not r.is_open]
    samples = [route.interpolate(t, normalized=True) for t in np.linspace(0, 1, 300)]
    assert not any(g.covers(s) for g in closed for s in samples), "the tour walks into a closed room"
    assert any(s["look_at"] == tour["waypoints"][s["index"]][:2] for s in tour["stops"]), "no open area walked into"
    designer = _designer_points(xml_path, plan)
    cover = np.mean([route.distance(Point(p)) * u <= 2.0 for p in designer])
    assert cover >= FLOORS[pid], (pid, round(float(cover), 2))
    assert math.isfinite(tour["suggested_duration_s"]) and tour["suggested_duration_s"] <= 130
