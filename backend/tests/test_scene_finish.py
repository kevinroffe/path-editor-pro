from pathlib import Path

import pytest

import qbiq_extractor as qe
import qbiq_scene3d as s3

PLAN = Path(r"C:\Users\kevin\Downloads\121937120410001.json")
VOCABULARY = {"carpet", "wood", "concrete", "plaster", "glass", "metal", "steel", "oak", "laminate", "fabric",
              "plastic", "foliage", "ceramic", "screen", "ceiling", "light", "plain"}


@pytest.mark.parametrize("space_type, finish", [
    ("Office - Non Receiving Guests", "carpet"), ("Conference", "carpet"), ("Open Space WorkStation", "carpet"),
    ("Kitchen", "wood"), ("Comfort Zone", "wood"), ("Corridor", "concrete"), ("", "concrete"), (None, "concrete")])
def test_floor_finish_by_space_type(space_type, finish):
    assert s3.floor_finish(space_type) == finish


@pytest.mark.parametrize("mat, finish", [
    (s3.WALL, "plaster"), (s3.GLASS, "glass"), (s3.WINDOW, "glass"), (s3.FABRIC_GREY, "fabric"),
    (s3.OAK_LIGHT, "oak"), (s3.METAL, "metal"), (s3.STAINLESS, "steel"), (s3.CEILING_MAT, "ceiling"),
    (s3.LIGHT_MAT, "light")])
def test_material_constants_carry_their_finish(mat, finish):
    assert mat.finish == finish


def test_mat_defaults_to_plain_and_all_constants_use_the_vocabulary():
    assert s3._mat("furniture", "#000000").finish == "plain"
    assert {m.finish for m in vars(s3).values() if isinstance(m, s3.Mat)} <= VOCABULARY


@pytest.mark.skipif(not PLAN.exists(), reason="real qbiq design JSON not available")
def test_real_scene_meshes_all_have_a_known_finish():
    meshes = qe.extract_qbiq_design(str(PLAN)).meshes
    assert all(m["finish"] in VOCABULARY for m in meshes)
    floors = {m["finish"] for m in meshes if m["type"] == "floor"}
    assert {"carpet", "wood"} <= floors
