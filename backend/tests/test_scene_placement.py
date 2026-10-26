"""Furniture is built where the plan draws it: `matrix` (with original_matrix3d) places a component,
because real exports can carry a stale matrix3d — the first placement of a stencil reused in other rooms."""
import json
from pathlib import Path

import pytest
from shapely import wkt
from shapely.geometry import MultiPoint

import qbiq_scene3d as s3

DOWNLOADS = Path(r"C:\Users\kevin\Downloads")
REAL = [p for p in (DOWNLOADS / f"{n}.json" for n in ("121937120410001", "80600469160002", "80651469900001", "80565468720002")) if p.exists()]


def _centre(comp):
    """Centre of the built faces' footprint, in design units."""
    _, faces = s3._component(comp, 100.0)
    return MultiPoint([(x, y) for _, pts, *_ in faces for x, y, _z in pts]).convex_hull.centroid


def test_matrix_wins_over_a_stale_matrix3d():
    comp = {"name": "QBIQ_CW_STORAGE_100_L#45", "bom_data": "S_LS_L100_W45", "show": True, "is_remove": False,
            "geom_box": "POLYGON ((0 0, 100 0, 100 45, 0 45, 0 0))",
            "matrix": [[1, 0, 5000], [0, 1, 3000], [0, 0, 1]],
            "original_matrix3d": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "matrix3d": [[1, 0, -7000], [0, 1, 800], [0, 0, 1]]}
    c = _centre(comp)
    assert (c.x, c.y) == pytest.approx((5050, 3022.5), abs=1)


def test_matrix3d_alone_still_places_a_component():
    comp = {"name": "QBIQ_CW_STORAGE_100_L#45", "bom_data": "S_LS_L100_W45", "show": True, "is_remove": False,
            "geom_box": "POLYGON ((0 0, 100 0, 100 45, 0 45, 0 0))", "matrix3d": [[1, 0, 200], [0, 1, 100], [0, 0, 1]]}
    c = _centre(comp)
    assert (c.x, c.y) == pytest.approx((250, 122.5), abs=1)


@pytest.mark.skipif(not REAL, reason="real qbiq design JSONs not available")
@pytest.mark.parametrize("path", REAL, ids=lambda p: p.stem)
def test_every_piece_is_built_on_its_drawn_stencil(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    off = [(c.get("name"), round(drawn.distance(centre)))
           for r in data.get("rooms") or [] if r.get("stencil_geometry")
           for drawn in [wkt.loads(r["stencil_geometry"]).envelope]
           for c in r.get("stencil_geometry_components") or []
           if s3._flag(c.get("show"), True) and not s3._flag(c.get("is_remove"), False)
           for centre in [_centre(c)] if drawn.distance(centre) > 5]
    assert not off, off[:10]
