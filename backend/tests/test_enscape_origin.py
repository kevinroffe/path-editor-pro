"""Exported Enscape paths sit where qbiq's Revit models put the floor.

qbiq's own video-path tool (nfp_to_enscape, metres mode) maps a design point to Enscape as
X = (x - fill.xmax) * u - 2 and Z = -((y - fill.ymin) * u + 1.7).
"""
import re
from pathlib import Path

import pytest

import app as app_module
from plan_model import enscape_offset

REAL = Path("C:/Users/kevin/Downloads/121937120410001.json")


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _upload(client, path=None):
    from tests.test_app_plan_cache import _design_json
    f = path.open("rb") if path else _design_json()
    r = client.post("/api/upload-qbiq-design", data={"json_file": (f, "d.json")}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _positions(xml: str) -> list:
    return [tuple(float(v) for v in m) for m in re.findall(r'<Position x="([-\d.]+)" y="([-\d.]+)" z="([-\d.]+)"', xml)]


def test_offset_puts_the_fill_corner_at_qbiqs_revit_origin():
    assert enscape_offset((0, 0, 2000, 1000), 0.01) == pytest.approx((-22.0, -1.7))


def test_plan_carries_the_offset_to_the_frontend(client):
    plan = _upload(client)["plan"]
    assert plan["enscape_offset"] == pytest.approx(list(app_module._LAST_PLAN.enscape_offset))


def test_xml_export_moves_the_path_onto_the_revit_model(client):
    _upload(client)
    u = app_module._LAST_PLAN.units_to_metres
    # display space: model (2000, 0) -> (2000, -0); model (1000, 0) -> (1000, -0)
    body = {"waypoints": [[2000, 0, 0, "", None], [1000, 0, 0, "", None]], "cuts": [],
            "settings": {"duration": 10, "units_to_metres": u}}
    r = client.post("/api/export/xml", json=body)
    assert r.status_code == 200
    x, y, z = _positions(r.data.decode())[0]
    assert (x, z) == pytest.approx((-2.0, -1.7), abs=0.02)
    assert y == pytest.approx(1.57)


def test_xml_without_a_plan_keeps_plain_metres(client):
    body = {"waypoints": [[500, -300, 0, "", None], [900, -300, 0, "", None]], "cuts": [],
            "settings": {"duration": 10, "units_to_metres": 0.01}}
    r = client.post("/api/export/xml", json=body)
    assert r.status_code == 200
    x, _, z = _positions(r.data.decode())[0]
    assert (x, z) == pytest.approx((5.0, -3.0), abs=0.02)


@pytest.mark.skipif(not REAL.exists(), reason="real design file not available")
def test_real_plan_offset_matches_qbiqs_formula(client):
    _upload(client, REAL)
    plan = app_module._LAST_PLAN
    assert plan.enscape_offset == pytest.approx((-(11956.4 * plan.units_to_metres + 2), 11878.8 * plan.units_to_metres - 1.7), abs=1e-3)
