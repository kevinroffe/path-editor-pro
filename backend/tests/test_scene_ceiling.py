import pytest
from shapely.geometry import Point, Polygon, box

import qbiq_scene3d as s3

U = 0.01   # cm plans
PLATE = box(0, 0, 2000, 1000)                        # 20 m x 10 m
CORE = [(800, 300), (1200, 300), (1200, 700), (800, 700), (800, 300)]


def _scene(plates=(PLATE,), cores=(CORE,), rooms=()):
    inp = s3.SceneInputs(plates=list(plates), rooms=list(rooms), exterior=[], windows=[], partitions=[],
                         doors=[], columns=[], cores=list(cores))
    return s3.build_design_scene(inp, U)


def _faces(mesh):
    v, f = mesh["verts"], mesh["faces"]
    pts = list(zip(v[::3], v[1::3], v[2::3]))
    return [(pts[f[i]], pts[f[i + 1]], pts[f[i + 2]]) for i in range(0, len(f), 3)]


def _area_at(mesh, z):
    tris = [t for t in _faces(mesh) if all(p[2] == pytest.approx(z) for p in t)]
    return sum(Polygon([p[:2] for p in t]).area for t in tris)


def _one(meshes, kind):
    found = [m for m in meshes if m["type"] == kind]
    assert len(found) == 1, f"expected one {kind} mesh, got {len(found)}"
    return found[0]


def test_ceiling_covers_the_plate():
    ceiling = _one(_scene(cores=()), "ceiling")
    assert _area_at(ceiling, s3.CEILING) == pytest.approx(PLATE.area * U * U, rel=0.01)   # underside seen from the room
    zs = ceiling["verts"][2::3]
    assert min(zs) == pytest.approx(s3.CEILING) and max(zs) == pytest.approx(s3.CEILING_TOP)


def test_ceiling_respects_plate_holes():
    holed = PLATE.difference(box(100, 100, 300, 300))
    ceiling = _one(_scene(plates=(holed,), cores=()), "ceiling")
    assert _area_at(ceiling, s3.CEILING) == pytest.approx(holed.area * U * U, rel=0.01)


def test_panels_inside_plate_and_outside_cores():
    light = _one(_scene(), "light")
    plate_m, core_m = box(0, 0, 20, 10), Polygon(CORE).buffer(0)
    core_m = Polygon([(x * U, y * U) for x, y in core_m.exterior.coords])
    pts = list(zip(light["verts"][::3], light["verts"][1::3], light["verts"][2::3]))
    assert len(pts) >= 8 * 4
    assert all(plate_m.buffer(1e-6).covers(Point(x, y)) for x, y, _ in pts)
    assert not any(core_m.buffer(-1e-6).contains(Point(x, y)) for x, y, _ in pts)
    assert all(2.99 - 1e-9 <= z <= 2.995 + 1e-9 for _, _, z in pts)


def test_ceiling_survives_the_vertex_cap(monkeypatch):
    chair = {"name": "QBIQ_FR_CHAIR_CONFERENCE_1#Arms", "show": True, "is_remove": False,
             "geom_box": "POLYGON ((0 0, 55 0, 55 58, 0 58, 0 0))", "matrix3d": [[1, 0, 500], [0, 1, 500], [0, 0, 1]],
             "bom_data": "C_C_L55_W58"}
    rooms = [([list(PLATE.exterior.coords)], "Open Space WorkStation", [chair] * 40)]
    structure = sum(len(m["verts"]) // 3 for m in _scene(rooms=rooms[:0]))
    monkeypatch.setattr(s3, "_MAX_VERTS", structure + 10)
    meshes = _scene(rooms=rooms)
    assert any(m["type"] == "ceiling" for m in meshes) and any(m["type"] == "light" for m in meshes)
