import pytest

import qbiq_scene3d as s3

K = 100.0


def _pieces(code, name, length_cm, width_cm):
    b = s3.Bounds(0, length_cm, 0, width_cm)
    return b, s3._PART_BUILDERS[code](b, K, name.lower(), s3.Part(code, length_cm / 100, width_cm / 100))


def _area(ring):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))


def _span(ring, axis):
    vals = [p[axis] for p in ring]
    return max(vals) - min(vals)


def _top_slab(pieces, b, share=0.5):
    """(z0, z1) of the largest horizontal piece covering >= share of the footprint."""
    footprint = (b.x1 - b.x0) * (b.y1 - b.y0)
    slabs = [(z0, z1) for _, ring, z0, z1, *_ in pieces if _area(ring) >= share * footprint]
    return max(slabs, key=lambda z: z[1])


def _top(pieces):
    return max(z1 for _, _, _, z1, *_ in pieces)


def _inside(pieces, b, tol=1.0):
    return all(b.x0 - tol <= x <= b.x1 + tol and b.y0 - tol <= y <= b.y1 + tol for _, ring, *_ in pieces for x, y in ring)


def _clean(pieces, b):
    return pieces and _inside(pieces, b) and all(_area(ring) > 0 for _, ring, *_ in pieces)


@pytest.mark.parametrize("code,name,length,width", [("T_WS", "QBIQ_FR_OS_DESK#160x80", 160, 80),
                                                    ("T_D", "QBIQ_FR_OFFICE_DESK#140X70", 140, 70)])
def test_desk_top(code, name, length, width):
    b, pieces = _pieces(code, name, length, width)
    z0, z1 = _top_slab(pieces, b)
    assert z1 == pytest.approx(0.74, abs=0.01) and z1 - z0 == pytest.approx(0.025, abs=0.002)
    assert _clean(pieces, b)


def test_workstation_desk_has_monitor_and_modesty_panel():
    b, pieces = _pieces("T_WS", "QBIQ_FR_OS_DESK#160x80", 160, 80)
    assert any(mat == s3.SCREEN and z0 >= 0.74 for mat, _, z0, _, *_ in pieces)
    assert any(_span(ring, 1) <= 3 and _span(ring, 0) >= 0.6 * 160 and z1 < 0.74 for _, ring, _, z1, *_ in pieces)


def test_reception_desk_counter_height():
    b, pieces = _pieces("T_R", "QBIQ_CW_RECEPTION#200", 200, 70)
    assert _top(pieces) == pytest.approx(1.05, abs=0.02) and _clean(pieces, b)


@pytest.mark.parametrize("code,name,length,width,height", [
    ("T_C", "QBIQ_FR_TABLE_CONFERENCE_RECTANGULAR#120x300", 300, 120, 0.74),
    ("T_DT", "QBIQ_FR_TABLE_KITCHEN_CIRCLE#100", 100, 100, 0.74),
    ("T_CF", "QBIQ_FR_TABLE_COFFEE_RECTANGULAR#55x90", 90, 55, 0.42),
    ("T_BR", "QBIQ_CW_KITCHEN_BAR#90x360", 360, 90, 1.05),
])
def test_table_heights(code, name, length, width, height):
    b, pieces = _pieces(code, name, length, width)
    assert _top(pieces) == pytest.approx(height, abs=0.02) and _clean(pieces, b)


@pytest.mark.parametrize("name", ["QBIQ_FR_TABLE_CONFERENCE_ROUND#90", "QBIQ_FR_TABLE_KITCHEN_CIRCLE#100"])
def test_round_tables_have_round_tops_and_a_pedestal(name):
    b, pieces = _pieces("T_C", name, 90, 90)
    top = max(pieces, key=lambda p: p[3])
    assert len(top[1]) >= 24
    assert sum(1 for p in pieces if p[2] == 0.0) <= 2      # pedestal + base, no legs


def test_collaboration_triangle_table():
    b, pieces = _pieces("CO_H", "QBIQ_FR_TABLE_COLLABORATION_TRIANGLE#D73", 132, 120)
    top = max(pieces, key=lambda p: p[3])
    assert len(top[1]) == 6                                 # a triangle with its three corners cut round
    legs = [p for p in pieces if p[2] == 0.0]
    assert len(legs) == 3 and _clean(pieces, b)


@pytest.mark.parametrize("code,name,width,height,doors", [("S_LS", "QBIQ_CW_STORAGE_100_L#60", 100, 0.8, 2),
                                                          ("S_HS", "QBIQ_CW_STORAGE_50_H#30", 50, 1.8, 1)])
def test_storage_heights_doors_and_handles(code, name, width, height, doors):
    b, pieces = _pieces(code, name, width, 45)
    assert _top(pieces) == pytest.approx(height, abs=0.02)
    assert sum(1 for mat, *_ in pieces if mat == s3.OAK_LIGHT) == doors
    assert sum(1 for mat, *_ in pieces if mat == s3.METAL) == doors
    assert _clean(pieces, b)


def test_kitchen_counter_sink_and_fridge():
    b, counter = _pieces("K_C", "QBIQ_CW_KITCHEN COUNTER_63#360", 270, 63)
    assert _top(counter) == pytest.approx(0.9, abs=0.01) and _clean(counter, b)
    assert any(z1 - z0 == pytest.approx(0.04, abs=0.002) and z1 == pytest.approx(0.9) for _, _, z0, z1, *_ in counter)
    sb, sink = _pieces("K_S", "QBIQ_CW_KITCHEN COUNTER_63#360", 52, 49)
    assert any(mat == s3.STAINLESS for mat, *_ in sink) and _clean(sink, sb)
    fb, fridge = _pieces("K_R", "QBIQ_CW_KITCHEN COUNTER_63#360", 90, 66)
    assert _top(fridge) == pytest.approx(1.8, abs=0.01) and _clean(fridge, fb)


def test_plant_and_printer():
    pb, plant = _pieces("V_P", "QBIQ_PL_ PLANT_50", 51, 50)
    assert any(mat == s3.TERRACOTTA for mat, *_ in plant)
    assert sum(1 for mat, *_ in plant if mat in (s3.FOLIAGE, s3.FOLIAGE_LIGHT)) >= 3 and _clean(plant, pb)
    rb, printer = _pieces("PH_PR", "QBIQ_EL_PRINTER#60x100", 100, 61)
    assert _clean(printer, rb)


@pytest.mark.parametrize("code", ["T_WS", "T_D", "T_R", "T_C", "T_CF", "T_DT", "T_BR", "CO_H", "S_LS", "S_HS",
                                  "K_C", "K_S", "K_R", "PH_PR", "V_P"])
def test_tiny_box_builds_cleanly(code):
    b, pieces = _pieces(code, "x", 35, 35)
    assert _clean(pieces, b)


def test_keyword_fallback_builds_detailed_models():
    for name in ("qbiq_fr_kitchen_chair", "qbiq_fr_sofa_2_seat", "qbiq_cw_storage_100_l#45", "qbiq_fr_table_coffee"):
        kind, build = s3.classify_furniture(name, "")
        pieces = build(s3.Bounds(0, 100, 0, 60), K, name, "")
        assert kind != "fallback" and len(pieces) >= 5
