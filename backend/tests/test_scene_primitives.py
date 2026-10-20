import math

import numpy as np
import pytest

import qbiq_scene3d as s3

IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
MIRROR_X = (-1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _area(ring):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))


def _normal_z(pts):
    a, b, c = (np.array(p, dtype=float) for p in pts[:3])
    return float(np.cross(b - a, c - a)[2])


def test_round_rect_is_convex_ccw_and_inside_bounds():
    b = s3.Bounds(0, 100, 0, 60)
    ring = s3._round_rect(b, 10, seg=4)
    assert _area(ring) > 0
    assert len(ring) == 4 * (4 + 1)
    assert all(b.x0 - 1e-9 <= x <= b.x1 + 1e-9 and b.y0 - 1e-9 <= y <= b.y1 + 1e-9 for x, y in ring)
    turns = [(q[0] - p[0]) * (r[1] - q[1]) - (q[1] - p[1]) * (r[0] - q[0])
             for p, q, r in zip(ring, ring[1:] + ring[:1], ring[2:] + ring[:2])]
    assert all(t >= -1e-9 for t in turns)


def test_round_rect_radius_is_clamped_to_the_box():
    ring = s3._round_rect(s3.Bounds(0, 10, 0, 4), 50)
    assert _area(ring) > 0 and max(y for _, y in ring) <= 4 + 1e-9


def test_bar_ring_runs_from_centre():
    ring = s3._bar_ring(0, 0, 30, 4, math.pi / 2)
    assert _area(ring) > 0
    ys = [y for _, y in ring]
    assert min(ys) == pytest.approx(0, abs=1e-9) and max(ys) == pytest.approx(30)


def test_slanted_piece_top_is_shifted():
    faces = s3._framed(s3.LAMINATE, IDENT, s3._rect(0, 10, 0, 10), 0.4, 0.9, (0, 5))
    top = [p for f in faces for p in f[1] if p[2] == pytest.approx(0.9)]
    assert min(y for _, y, _ in top) == pytest.approx(5) and max(y for _, y, _ in top) == pytest.approx(15)


def test_slanted_piece_through_mirrored_frame():
    faces = s3._framed(s3.LAMINATE, MIRROR_X, s3._rect(0, 10, 0, 10), 0.4, 0.9, (5, 0))
    top = [p for f in faces for p in f[1] if p[2] == pytest.approx(0.9)]
    assert max(x for x, _, _ in top) == pytest.approx(-5)          # shift mirrored with the frame
    caps = [f[1] for f in faces if len({round(p[2], 6) for p in f[1]}) == 1]
    assert sorted(np.sign(_normal_z(c)) for c in caps) == [-1.0, 1.0]   # bottom faces down, top faces up


def _merged(mat, n=16):
    ring = s3._ngon(s3.Bounds(0, 10, 0, 10), n)
    return s3._merge(s3._prism(mat, ring, 0.0, 1.0), 1.0)[0]


def test_smooth_cylinder_shares_side_vertices():
    mesh = _merged(s3._mat("furniture", "#123456", smooth=True))
    assert len(mesh["verts"]) // 3 == 16 * 2 + 16 + 16
    assert mesh["smooth"] is True


def test_flat_material_unchanged():
    mesh = _merged(s3.LAMINATE)
    assert len(mesh["verts"]) // 3 == 16 * 4 + 16 + 16
    assert mesh["smooth"] is False


def test_palette_matches_the_spec():
    assert s3.FABRIC_CHARCOAL.color == "#3b3f46" and s3.FABRIC_CHARCOAL.smooth
    assert s3.METAL.color == "#b8bcc2" and s3.METAL.metalness == pytest.approx(0.7)
    assert s3.STAINLESS.metalness == pytest.approx(0.8) and s3.TERRACOTTA.color == "#b5674d"
    assert s3.FOLIAGE.smooth and not s3.LAMINATE.smooth
