import json
import logging
import os
from pathlib import Path

import pytest

import qbiq_extractor as qe
import qbiq_scene3d as s3

FILES = [Path(os.environ.get("QBIQ_DESIGN_JSON", r"C:\Users\kevin\Downloads\121937120410001.json")),
         Path(os.environ.get("QBIQ_DESIGN_JSON_2", r"C:\Users\kevin\Downloads\80565468720002.json"))]
FILES = [f for f in FILES if f.exists()]
if not FILES:
    pytest.skip("real qbiq design JSONs not available", allow_module_level=True)


def _components(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return [c for r in data.get("rooms") or [] for c in r.get("stencil_geometry_components") or []
            if isinstance(c, dict) and not s3._flag(c.get("is_remove"), False) and s3._flag(c.get("show"), True)]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_every_catalogue_item_has_a_detailed_bom_model(path):
    uncovered = {str(c.get("name")): str(c.get("bom_data")) for c in _components(path)
                 if s3.classify_furniture(str(c.get("name") or "").split("#")[0], str(c.get("bom_data") or ""))[0]
                 not in s3._PART_BUILDERS}
    assert not uncovered, uncovered


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_real_scene_has_ceiling_lights_and_no_dropped_faces(path, caplog):
    caplog.set_level(logging.WARNING, logger="qbiq_scene3d")
    meshes = qe.extract_qbiq_design(str(path)).meshes
    types = {m["type"] for m in meshes}
    assert {"ceiling", "light", "furniture"} <= types
    assert sum(len(m["verts"]) // 3 for m in meshes) < s3._MAX_VERTS
    assert not [r for r in caplog.records if "vertex cap" in r.message]
