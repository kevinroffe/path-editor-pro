import copy
import json

import pytest
from shapely.affinity import affine_transform
from shapely.geometry import Point, Polygon

import qbiq_extractor as qe
from tests.test_qbiq_design import DESIGN

_IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def _component(name, box, matrix, bom=""):
    """A stencil component dict with a rectangular local geom_box."""
    x0, y0, x1, y1 = box
    ring = f"POLYGON (({x1} {y1}, {x0} {y1}, {x0} {y0}, {x1} {y0}, {x1} {y1}))"
    return {"name": name, "geom_box": ring, "simple_geom": ring, "matrix3d": matrix,
            "primary": True, "is_remove": False, "show": True, "bom_data": bom}


def _translate(tx, ty, rot90=False):
    """A matrix3d translating (and optionally rotating 90 degrees)."""
    return [[0, -1, tx], [1, 0, ty], [0, 0, 1]] if rot90 else [[1, 0, tx], [0, 1, ty], [0, 0, 1]]


def _grouped(name, box_in_group, matrix, original, bom=""):
    """A grouped component as real exports write it: geom_box already has original_matrix3d
    applied, `matrix` is the group placement and matrix3d = matrix @ original_matrix3d."""
    (a, b, tx), (c, d, ty), _ = matrix
    (oa, ob, otx), (oc, od, oty), _ = original
    matrix3d = [[a * oa + b * oc, a * ob + b * od, a * otx + b * oty + tx],
                [c * oa + d * oc, c * ob + d * od, c * otx + d * oty + ty], [0, 0, 1]]
    return dict(_component(name, box_in_group, matrix3d, bom), matrix=matrix, original_matrix3d=original)


_MIRROR_OFFSET = [[1, 0, 100], [0, -1, 0], [0, 0, 1]]

_DESK = _component("QBIQ_FR_OS_DESK#1", (-80, -40, 80, 40), _translate(1700, 1200), "T_WS_L160_W80")
_CHAIR = _component("QBIQ_FR_CHAIR_CONFERENCE_1#1", (-29, 0, 29, 53), _translate(250, 250))
_STORAGE = _grouped("QBIQ_CW_STORAGE_100_L#45", (100, 0, 200, 45), _translate(1600, 1300, rot90=True), _MIRROR_OFFSET, "S_LS_L100_W45")
_HIDDEN = dict(_component("QBIQ_FR_SOFA_3_SEAT#1", (0, 0, 200, 90), _translate(1550, 1050)), is_remove=True)
_MIRRORED_DESK = _grouped("QBIQ_FR_OS_DESK#160x80", (-60, 0, 100, 116), _translate(300, 100),
                          _MIRROR_OFFSET, "T_WS_L160_W80|C_W_L48_W45")


def _design():
    """The shared synthetic design plus desks, a chair, storage and a removed sofa."""
    data = copy.deepcopy(DESIGN)
    data["rooms"][0]["stencil_geometry_components"] = [_CHAIR, _MIRRORED_DESK]
    data["rooms"][1]["stencil_geometry_components"] = [_DESK, _STORAGE, _HIDDEN]
    return data


@pytest.fixture
def meshes(tmp_path):
    path = tmp_path / "design.json"
    path.write_text(json.dumps(_design()), encoding="utf-8")
    return qe.extract_qbiq_design(str(path)).meshes


def _verts(mesh):
    """A mesh's verts as (x, y, z) tuples."""
    v = mesh["verts"]
    return list(zip(v[::3], v[1::3], v[2::3]))


def _of(meshes, mesh_type, color=None):
    """All verts of meshes of one type (and colour, when given)."""
    return [p for m in meshes if m["type"] == mesh_type and color in (None, m["color"]) for p in _verts(m)]


def _near(points, polygon_m, tol=0.005):
    """Points whose x/y lie within `tol` metres of a polygon given in metres."""
    region = polygon_m.buffer(tol)
    return [p for p in points if region.contains(Point(p[0], p[1]))]


def test_every_mesh_is_valid(meshes):
    assert meshes
    for m in meshes:
        n = len(m["verts"]) // 3
        assert len(m["verts"]) % 3 == 0 and len(m["faces"]) % 3 == 0
        assert m["faces"] and all(0 <= i < n for i in m["faces"])
        assert m["type"] in {"floor", "wall", "glass", "frame", "column", "door", "window", "furniture", "ceiling", "light"}
        assert m["color"].startswith("#") and len(m["color"]) == 7
        assert 0 <= m["opacity"] <= 1 and 0 <= m["roughness"] <= 1 and 0 <= m["metalness"] <= 1


def test_meshes_are_merged_one_per_material(meshes):
    keys = [(m["type"], m["color"], m["opacity"], m["roughness"], m["metalness"]) for m in meshes]
    assert len(keys) == len(set(keys))


def test_interior_partitions_are_glass_and_frame_only(meshes):
    partition = Polygon([(4.9, 0.2), (5.1, 0.2), (5.1, 4.9), (4.9, 4.9)])
    types = {m["type"] for m in meshes if _near(_verts(m), partition, 0)}
    assert types and types <= {"glass", "frame", "floor"}
    assert _near(_of(meshes, "glass"), partition, 0)


def test_glass_has_a_gap_at_the_door_opening(meshes):
    glass_on_door_edge = [p for p in _of(meshes, "glass") if abs(p[0] - 5.0) < 0.05]
    assert glass_on_door_edge
    assert not [p for p in glass_on_door_edge if 2.0 + 1e-6 < p[1] < 3.0 - 1e-6]


def test_exterior_window_spans_sill_to_head(meshes):
    window = _of(meshes, "window")
    assert window
    assert min(p[2] for p in window) == pytest.approx(0.9)
    assert max(p[2] for p in window) == pytest.approx(2.4)
    assert min(p[0] for p in window) == pytest.approx(6.0, abs=0.01)
    assert max(p[0] for p in window) == pytest.approx(9.0, abs=0.01)


def test_desk_tops_out_at_desk_height(meshes):
    desk = _near(_of(meshes, "furniture"), Polygon([(16.2, 11.6), (17.8, 11.6), (17.8, 12.4), (16.2, 12.4)]))
    assert desk and max(p[2] for p in desk) == pytest.approx(0.75)


def test_chair_has_a_back_to_085(meshes):
    chair = _near(_of(meshes, "furniture"), Polygon([(2.21, 2.5), (2.79, 2.5), (2.79, 3.03), (2.21, 3.03)]))
    assert chair and max(p[2] for p in chair) == pytest.approx(0.85)


def test_storage_lies_inside_its_transformed_footprint(meshes):
    (a, b, tx), (c, d, ty), _ = _STORAGE["matrix"]
    footprint = affine_transform(Polygon([(100, 0), (200, 0), (200, 45), (100, 45)]), [a, b, c, d, tx, ty])
    footprint_m = affine_transform(footprint, [0.01, 0, 0, 0.01, 0, 0])
    storage = [m for m in meshes if m["type"] == "furniture" and m["color"] == "#d8c3a0"]
    assert storage
    assert all(footprint_m.buffer(1e-3).contains(Point(p[0], p[1])) for m in storage for p in _verts(m))


def test_grouped_mirrored_desk_keeps_its_top_on_the_drawn_side(meshes):
    zone = Polygon([(2.4, 1.0), (4.0, 1.0), (4.0, 2.16), (2.4, 2.16)])
    pieces = _near(_of(meshes, "furniture"), zone)
    top = [p for p in pieces if p[2] == pytest.approx(0.75)]
    back = [p for p in pieces if p[2] == pytest.approx(0.85)]
    assert top and all(1.0 - 1e-6 <= p[1] <= 1.8 + 1e-6 for p in top)
    assert back and all(1.8 - 1e-6 <= p[1] <= 2.16 + 1e-6 for p in back)


def test_removed_component_is_skipped(meshes):
    assert not [m for m in meshes if m["type"] == "furniture" and m["color"] == "#4a6fd1"]


def test_each_room_gets_a_slab_in_its_type_colour(meshes):
    conference = _of(meshes, "floor", "#cfc9c2")
    kitchen = _of(meshes, "floor", "#e7d3b3")
    assert conference and max(p[2] for p in conference) == pytest.approx(0.03)
    assert kitchen and min(p[0] for p in kitchen) == pytest.approx(15.0)
    assert _of(meshes, "floor", "#e9e7e2")


def test_columns_are_extruded_to_ceiling(meshes):
    column = _of(meshes, "column")
    assert column and max(p[2] for p in column) == pytest.approx(3.0)
    assert {round(p[0], 2) for p in column} == {9.0, 9.6}


def test_verts_are_in_metres(meshes):
    xs = [p[0] for m in meshes for p in _verts(m)]
    ys = [p[1] for m in meshes for p in _verts(m)]
    assert min(xs) == pytest.approx(0.0, abs=0.2) and max(xs) == pytest.approx(20.0, abs=0.2)
    assert min(ys) == pytest.approx(0.0, abs=0.2) and max(ys) == pytest.approx(15.0, abs=0.2)
    assert all(v == round(v, 4) for m in meshes for v in m["verts"])
