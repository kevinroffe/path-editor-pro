import pytest

import qbiq_scene3d as s3

K = 100.0


def _pieces(code, name, length_cm, width_cm):
    b = s3.Bounds(0, length_cm, 0, width_cm)
    return b, s3._PART_BUILDERS[code](b, K, name.lower(), s3.Part(code, length_cm / 100, width_cm / 100))


def _area(ring):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))


def _top(pieces):
    return max(z1 for _, _, _, z1, *_ in pieces)


def _seat_height(pieces, b):
    """Top of the largest horizontal fabric piece below 0.8 m (the seat cushion)."""
    footprint = (b.x1 - b.x0) * (b.y1 - b.y0)
    seats = [z1 for mat, ring, z0, z1, *_ in pieces if mat.smooth and z1 < 0.8 and _area(ring) >= 0.25 * footprint]
    return max(seats)


def _count(pieces, z0, z1):
    return sum(1 for _, _, a, b, *_ in pieces if (a, b) == pytest.approx((z0, z1)))


def _corners(ring, sh):
    """A piece's bottom ring plus its (shifted) top ring."""
    dx, dy = sh[0] if sh else (0.0, 0.0)
    return ring + [(x + dx, y + dy) for x, y in ring]


def _inside(pieces, b, tol=1.0):
    return all(b.x0 - tol <= x <= b.x1 + tol and b.y0 - tol <= y <= b.y1 + tol
               for _, ring, _, _, *sh in pieces for x, y in _corners(ring, sh))


CHAIRS = [("C_C", "QBIQ_FR_CHAIR_CONFERENCE_1#Arms", 55, 58), ("C_K", "QBIQ_FR_KITCHEN_CHAIR", 40, 50),
          ("C_W", "QBIQ_FR_OS_DESK#160x80", 48, 45), ("C_E", "QBIQ_FR_OFFICE_DESK#140X70", 60, 58),
          ("C_G", "QBIQ_FR_OFFICE_DESK#140X70", 58, 58)]


@pytest.mark.parametrize("code,name,length,width", CHAIRS)
def test_chair_seat_back_and_footprint(code, name, length, width):
    b, pieces = _pieces(code, name, length, width)
    assert _seat_height(pieces, b) == pytest.approx(0.46, abs=0.03)
    assert _top(pieces) == pytest.approx(1.15, abs=0.05) if code == "C_E" else 0.85 <= _top(pieces) <= 1.0
    assert any(len(p) == 5 for p in pieces), "the back should be slanted"
    assert _inside(pieces, b)
    assert all(_area(ring) > 0 for _, ring, *_ in pieces)


def test_arms_follow_the_name():
    _, arms = _pieces("C_C", "QBIQ_FR_CHAIR_CONFERENCE_1#Arms", 55, 58)
    _, bare = _pieces("C_C", "QBIQ_FR_LECTURE_CHAIR#no_arms", 50, 48)
    assert _count(arms, *s3.ARM_Z) == 2 and _count(bare, *s3.ARM_Z) == 0


@pytest.mark.parametrize("code", ["C_W", "C_E"])
def test_office_chairs_have_a_five_star_base(code):
    _, pieces = _pieces(code, "x", 60, 58)
    assert _count(pieces, *s3.SPOKE_Z) == 5 and _count(pieces, *s3.CASTOR_Z) == 5
    assert _count(pieces, *s3.ARM_Z) == 2


@pytest.mark.parametrize("code", ["C_C", "C_K", "C_G"])
def test_four_legged_chairs(code):
    _, pieces = _pieces(code, "x", 55, 55)
    legs = [p for p in pieces if p[2] == 0.0 and p[3] >= 0.3]
    assert len(legs) == 4


def test_bar_stool():
    b, pieces = _pieces("C_B", "QBIQ_FR_BAR_STOOL", 50, 60)
    assert _top(pieces) == pytest.approx(0.75, abs=0.03)
    assert _count(pieces, *s3.FOOTREST_Z) == 1
    assert _inside(pieces, b)


SOFAS = [("QBIQ_FR_SOFA_2_SEAT", 200, 2), ("QBIQ_FR_SOFA_3_SEAT", 270, 3), ("QBIQ_FR_ARMCHAIR_1", 80, 1)]


@pytest.mark.parametrize("name,width,seats", SOFAS)
def test_sofa_cushions_and_arms(name, width, seats):
    b, pieces = _pieces("L_S", name, width, 90)
    assert _count(pieces, *s3.SOFA_SEAT_Z) == seats
    assert _count(pieces, *s3.SOFA_ARM_Z) == 2
    assert _inside(pieces, b)


def test_bench_is_a_low_upholstered_block():
    b, pieces = _pieces("L_B", "QBIQ_FR_BENCH_BOARDROOM#120x55", 120, 55)
    assert 0.4 <= _top(pieces) <= 0.5 and _inside(pieces, b)


def test_booth_has_two_benches_and_a_table():
    b, pieces = _pieces("K_DB", "QBIQ_FR_KITCHEN_BOOTH_3P", 110, 122)
    mid = (b.y0 + b.y1) / 2
    table = [p for p in pieces if p[3] == pytest.approx(0.74, abs=0.02) and min(y for _, y in p[1]) < mid < max(y for _, y in p[1])]
    backs = [p for p in pieces if p[3] >= 1.0]
    assert table and len({min(y for _, y in p[1]) < mid for p in backs}) == 2
    assert _inside(pieces, b)


@pytest.mark.parametrize("code", ["C_C", "C_K", "C_W", "C_E", "C_G", "C_B", "L_S", "L_B", "K_DB"])
def test_tiny_box_builds_cleanly(code):
    b, pieces = _pieces(code, "x", 35, 35)
    assert pieces and all(_area(ring) > 0 for _, ring, *_ in pieces) and _inside(pieces, b)


def test_fabric_is_smooth():
    _, pieces = _pieces("L_S", "QBIQ_FR_SOFA_2_SEAT", 200, 90)
    assert any(mat.smooth for mat, *_ in pieces)
