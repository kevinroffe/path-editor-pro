import time

import numpy as np

from mesh_reduce import reduce_meshes

_CUBE = np.array([[x, y, z] for z in (0, 1) for y in (0, 1) for x in (0, 1)], dtype=float)
_FACES = [0, 1, 3, 0, 3, 2, 4, 6, 7, 4, 7, 5, 0, 4, 5, 0, 5, 1, 2, 3, 7, 2, 7, 6, 0, 2, 6, 0, 6, 4, 1, 5, 7, 1, 7, 3]


def box(kind, size=1.0, at=(0.0, 0.0, 0.0), color=None, opacity=None):
    v = (_CUBE * size + np.array(at)).ravel().tolist()
    return {"type": kind, "verts": v, "faces": list(_FACES), "color": color, "opacity": opacity}


def nverts(meshes):
    return sum(len(m["verts"]) // 3 for m in meshes)


def test_merges_by_material():
    out = reduce_meshes([box("furniture", color="#111111"), box("furniture", at=(5, 0, 0), color="#111111"),
                         box("furniture", at=(9, 0, 0), color="#222222")])
    assert sorted(m["color"] for m in out) == ["#111111", "#222222"]
    merged = next(m for m in out if m["color"] == "#111111")
    assert len(merged["verts"]) // 3 == 16 and len(merged["faces"]) == 72
    assert max(merged["faces"]) == 15                      # second box's faces are offset past the first's 8 vertices


def test_drops_tiny_before_big():
    meshes = [box("furniture", 1.0, color="#000000")] + [box("furniture", 0.01, at=(i, 0, 0), color=f"#00000{i}") for i in range(1, 6)]
    out = reduce_meshes(meshes, max_vertices=40)
    assert nverts(out) == 40
    assert any(max(m["verts"][0::3]) - min(m["verts"][0::3]) >= 1.0 for m in out)   # the 1 m piece survives


def test_keeps_walls_and_floors_over_budget():
    meshes = [box("wall", 3, color=f"#10000{i}") for i in range(3)] + [box("floor", 5, color="#300000"),
                                                                       box("furniture", 1, color="#400000")]
    out = reduce_meshes(meshes, max_vertices=5)
    assert sorted(m["type"] for m in out) == ["floor", "wall", "wall", "wall"]


def test_under_budget_unchanged_content():
    meshes = [box("furniture", 1, color="#111111"), box("furniture", 0.001, at=(3, 0, 0), color="#111111")]
    out = reduce_meshes(meshes, max_vertices=1000)
    assert nverts(out) == 16 and sum(len(m["faces"]) for m in out) == 72


def test_huge_payload_is_bounded_and_fast():
    tiny = [box("furniture", 0.02, at=(i * 0.1, 0, 0), color=f"#{i % 7:06x}") for i in range(30000)]   # 240k vertices of detail
    big = [box("furniture", 1.0, at=(i * 2.0, 0, 0), color="#abcdef") for i in range(60000)]          # 480k more
    t = time.perf_counter()
    out = reduce_meshes(tiny + big, max_vertices=400_000)
    assert time.perf_counter() - t < 5
    assert nverts(out) <= 400_000
