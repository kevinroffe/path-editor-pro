import logging

import pytest

import qbiq_scene3d as s3

K = 100.0   # cm per metre
CODES = ["T_WS", "T_D", "T_R", "T_C", "T_CF", "T_DT", "T_BR", "CO_H", "K_C", "K_S", "K_R", "K_DB",
         "L_S", "L_B", "S_LS", "S_HS", "PH_PR", "V_P", "C_C", "C_K", "C_W", "C_E", "C_G", "C_B"]


def _placeholder(code):
    mat = s3._mat("furniture", "#%06x" % (CODES.index(code) + 1))
    return lambda b, k, name, part: [s3._box(mat, b, 0.0, 0.5)]


@pytest.fixture
def builders(monkeypatch):
    monkeypatch.setattr(s3, "_PART_BUILDERS", {c: _placeholder(c) for c in CODES})
    monkeypatch.setattr(s3, "_UNKNOWN_CODES", set())


def _by_code(pieces):
    out = {}
    for mat, ring, *_ in pieces:
        out.setdefault(CODES[int(mat.color[1:], 16) - 1], []).append(ring)
    return out


def _ys(rings):
    return [y for r in rings for _, y in r]


def _xs(rings):
    return [x for r in rings for x, _ in r]


def _inside(pieces, b, tol=1.0):
    return all(b.x0 - tol <= x <= b.x1 + tol and b.y0 - tol <= y <= b.y1 + tol for _, r, *_ in pieces for x, y in r)


def test_parse_bom():
    assert s3.parse_bom("T_D_L140_W70|C_E_L60_W58|C_G_L58_W58") == [
        s3.Part("T_D", 1.4, 0.7), s3.Part("C_E", 0.6, 0.58), s3.Part("C_G", 0.58, 0.58)]
    assert s3.parse_bom("junk|C_K_L40_W50") == [s3.Part("C_K", 0.4, 0.5)]
    assert s3.parse_bom("") == [] and s3.parse_bom(None) == []


def test_primary_part_wins(builders):
    kind, _ = s3.classify_furniture("anything", "C_E_L60_W58|T_D_L140_W70")
    assert kind == "T_D"


def test_desk_with_task_chair_layout(builders):
    b = s3.Bounds(0, 160, 0, 160)
    _, build = s3.classify_furniture("qbiq_fr_os_desk", "T_WS_L160_W80|C_W_L48_W45")
    parts = _by_code(build(b, K, "qbiq_fr_os_desk", ""))
    assert min(_ys(parts["T_WS"])) >= 160 - 80 - 1e-6
    assert max(_ys(parts["C_W"])) <= 80 + 1e-6


def test_desk_guest_chairs_only_when_room(builders):
    bom = "T_D_L200_W80|C_E_L60_W58|C_G_L58_W58|C_G_L58_W58"
    _, build = s3.classify_furniture("qbiq_fr_office_desk", bom)
    roomy = _by_code(build(s3.Bounds(0, 200, 0, 250), K, "qbiq_fr_office_desk", ""))
    assert len(roomy["C_G"]) == 2
    assert min(_ys(roomy["C_G"])) >= max(_ys(roomy["T_D"])) - 1e-6        # guests beyond the desk
    assert max(_ys(roomy["C_E"])) <= min(_ys(roomy["T_D"])) + 1e-6         # executive chair before it
    tight = _by_code(build(s3.Bounds(0, 200, 0, 140), K, "qbiq_fr_office_desk", ""))
    assert "C_G" not in tight and "T_D" in tight and "C_E" in tight


def test_kitchen_counter_layout(builders):
    b = s3.Bounds(0, 360, 0, 70)
    _, build = s3.classify_furniture("qbiq_cw_kitchen counter_63", "K_S_L52_W49|K_C_L360_W63|K_R_L90_W66")
    parts = _by_code(build(b, K, "qbiq_cw_kitchen counter_63", ""))
    assert set(parts) == {"K_C", "K_S", "K_R"}
    fridge, counter, sink = parts["K_R"], parts["K_C"], parts["K_S"]
    assert max(_xs(fridge)) <= min(_xs(counter)) + 1e-6                     # fridge at one end
    assert min(_xs(counter)) - 1e-6 <= min(_xs(sink)) and max(_xs(sink)) <= max(_xs(counter)) + 1e-6


def test_unknown_bom_falls_back_to_keywords(builders, caplog):
    caplog.set_level(logging.WARNING, logger="qbiq_scene3d")
    kind, _ = s3.classify_furniture("qbiq_fr_kitchen_chair", "X_Y_L1_W1")
    assert kind == "chair"
    s3.classify_furniture("qbiq_fr_kitchen_chair", "X_Y_L1_W1")
    assert sum("X_Y" in r.message for r in caplog.records) == 1


def test_missing_bom_uses_keywords(builders):
    assert s3.classify_furniture("qbiq_fr_sofa_2_seat", "")[0] == "sofa"
    assert s3.classify_furniture("mystery", "")[0] == "fallback"


@pytest.mark.parametrize("bom,box", [
    ("T_WS_L160_W80|C_W_L48_W45", (0, 160, 0, 160)),
    ("T_D_L200_W80|C_E_L60_W58|C_G_L58_W58|C_G_L58_W58", (0, 200, 0, 250)),
    ("T_D_L200_W80|C_E_L60_W58|C_G_L58_W58|C_G_L58_W58", (0, 150, 0, 120)),   # box smaller than the parts
    ("K_S_L52_W49|K_C_L360_W63|K_R_L90_W66", (0, 360, 0, 70)),
    ("T_CF_L35_W35", (0, 35, 0, 35)),
])
def test_assembly_stays_inside_box(builders, bom, box):
    b = s3.Bounds(*box)
    _, build = s3.classify_furniture("item", bom)
    pieces = build(b, K, "item", "")
    assert pieces and _inside(pieces, b)


def test_item_with_any_unknown_part_uses_keywords(builders):
    assert s3.classify_furniture("qbiq_fr_kitchen_chair", "C_K_L40_W50|X_Y_L1_W1")[0] == "chair"
