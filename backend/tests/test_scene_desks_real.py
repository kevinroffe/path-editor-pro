"""Desk assemblies at the real qbiq box proportions (chairs are drawn tucked under the desk)."""
import pytest

import qbiq_scene3d as s3

K = 100.0


def _build(name, bom, box):
    b = s3.Bounds(*box)
    _, build = s3.classify_furniture(name, bom)
    return b, build(b, K, name.lower(), bom)


def _area(ring):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))


def _cushions(pieces, code):
    seat = s3._SEAT_H[code]
    return [p for p in pieces if p[2:4] == pytest.approx((seat - 0.06, seat)) and p[0] == s3._CHAIR_FABRIC[code]]


def _depth(ring):
    ys = [y for _, y in ring]
    return max(ys) - min(ys)


def test_workstation_chair_keeps_its_real_depth_and_faces_the_desk():
    b, pieces = _build("QBIQ_FR_OS_DESK#160x80", "T_WS_L160_W80|C_W_L48_W45", (-80, 80, 0, 116))
    (cushion,) = _cushions(pieces, "C_W")
    assert _depth(cushion[1]) >= 30                              # a 45 cm chair is not squashed into 36 cm
    spokes = [p for p in pieces if p[2:4] == pytest.approx(s3.SPOKE_Z)]
    assert len(spokes) == 5 and max(x for p in spokes for x, _ in p[1]) - min(x for p in spokes for x, _ in p[1]) >= 35
    backs = [p for p in pieces if len(p) == 5 and p[0] == s3._CHAIR_FABRIC["C_W"]]
    assert backs and all(p[4][1] < 0 for p in backs)            # back leans away from the desk (+y)
    assert all(b.y0 - 1 <= y <= b.y1 + 1 for _, ring, *_ in pieces for _, y in ring)


@pytest.mark.parametrize("box", [(-174, 26, -132, 53.8), (-70, 70, -100, 85.8)])
def test_office_desk_keeps_its_guest_chair(box):
    b, pieces = _build("QBIQ_FR_OFFICE_DESK#140X70", "T_D_L140_W70|C_E_L60_W58|C_G_L58_W58", box)
    assert len(_cushions(pieces, "C_E")) == 1 and len(_cushions(pieces, "C_G")) == 1


def test_os_desk_us_is_an_l_desk_with_its_chair_in_the_notch():
    b, pieces = _build("QBIQ_FR_OS_DESK_US#72x96", "T_D_L182_W243|C_E_L48_W58", (-182, 0, -243, 0))
    tops = [p for p in pieces if p[3] == pytest.approx(s3.DESK_H) and p[0] == s3.LAMINATE and _area(p[1]) > 1000]
    box_area = (b.x1 - b.x0) * (b.y1 - b.y0)
    assert len(tops) == 2 and sum(_area(p[1]) for p in tops) <= 0.6 * box_area
    (cushion,) = _cushions(pieces, "C_E")
    assert max(x for x, _ in cushion[1]) <= b.x1 - 46 + 1      # the chair sits in the notch, not on the return
    assert min(y for _, y in cushion[1]) >= b.y1 - 72 - 70     # ... right in front of the desk top


def test_reception_counter_faces_the_visitors_and_keeps_the_chair():
    b, pieces = _build("QBIQ_CW_RECEPTION#200", "T_R_L200_W70|C_W_L48_W58", (-200, 0, -98, 0))
    tall = [p for p in pieces if p[3] >= 1.0]
    assert tall and min(y for p in tall for _, y in p[1]) >= b.y1 - 35   # the 1.05 m counter is on the +y side
    assert len(_cushions(pieces, "C_W")) == 1


def test_unknown_secondary_part_is_skipped_not_fatal():
    kind, build = s3.classify_furniture("qbiq_fr_os_desk", "T_WS_L160_W80|C_X_L40_W40")
    assert kind == "T_WS" and build(s3.Bounds(-80, 80, 0, 116), K, "qbiq_fr_os_desk", "")
