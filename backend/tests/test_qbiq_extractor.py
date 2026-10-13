import xml.etree.ElementTree as ET

import pytest

import qbiq_extractor as qe


def test_stitch_single_closed_square():
    segments = [
        ((0.0, 0.0), (10.0, 0.0)),
        ((10.0, 0.0), (10.0, 10.0)),
        ((10.0, 10.0), (0.0, 10.0)),
        ((0.0, 10.0), (0.0, 0.0)),
    ]
    chains = qe._stitch_segments(segments)
    assert len(chains) == 1
    chain = chains[0]
    assert chain[0] == chain[-1]  # closed
    assert len(chain) == 5  # 4 corners + repeated start


def test_stitch_segments_given_out_of_order():
    # Same square, segments listed in a shuffled, non-walkable-in-order sequence
    segments = [
        ((10.0, 10.0), (0.0, 10.0)),
        ((0.0, 0.0), (10.0, 0.0)),
        ((0.0, 10.0), (0.0, 0.0)),
        ((10.0, 0.0), (10.0, 10.0)),
    ]
    chains = qe._stitch_segments(segments)
    assert len(chains) == 1
    assert chains[0][0] == chains[0][-1]


def test_stitch_two_disconnected_loops():
    # Two separate unit squares, far apart — must NOT merge into one chain
    square_a = [
        ((0.0, 0.0), (1.0, 0.0)),
        ((1.0, 0.0), (1.0, 1.0)),
        ((1.0, 1.0), (0.0, 1.0)),
        ((0.0, 1.0), (0.0, 0.0)),
    ]
    square_b = [
        ((100.0, 100.0), (101.0, 100.0)),
        ((101.0, 100.0), (101.0, 101.0)),
        ((101.0, 101.0), (100.0, 101.0)),
        ((100.0, 101.0), (100.0, 100.0)),
    ]
    chains = qe._stitch_segments(square_a + square_b)
    assert len(chains) == 2
    for chain in chains:
        assert chain[0] == chain[-1]


def test_stitch_many_disconnected_loops_matches_count():
    # 5 separate triangles — exactly 5 chains, not fewer (no accidental merging)
    # and not more (no accidental splitting)
    segments = []
    for i in range(5):
        ox, oy = i * 50.0, i * 50.0
        segments += [
            ((ox, oy), (ox + 5.0, oy)),
            ((ox + 5.0, oy), (ox, oy + 5.0)),
            ((ox, oy + 5.0), (ox, oy)),
        ]
    chains = qe._stitch_segments(segments)
    assert len(chains) == 5
    for chain in chains:
        assert len(chain) == 4  # 3 corners + repeated start
        assert chain[0] == chain[-1]


def test_stitch_open_chain_stays_open():
    # A single unconnected bar (e.g. an isolated mullion) — no match for either
    # end, so it must remain a 2-point OPEN chain, not be forced closed.
    segments = [((5.0, 5.0), (5.0, 9.0))]
    chains = qe._stitch_segments(segments)
    assert len(chains) == 1
    assert chains[0] == [(5.0, 5.0), (5.0, 9.0)]
    assert chains[0][0] != chains[0][-1]


def test_stitch_empty_list_returns_empty():
    assert qe._stitch_segments([]) == []


def test_parse_path_d_simple_rectangle():
    d = "M 249.5,155.6 L 249.5,117.1 L 212.0,117.1 L 212.0,155.6 L 249.5,155.6 z"
    pts = qe._parse_path_d(d)
    assert pts == [
        (249.5, 155.6), (249.5, 117.1), (212.0, 117.1),
        (212.0, 155.6), (249.5, 155.6),
    ]
    assert pts[0] == pts[-1]  # explicitly closed in the source data


def test_parse_path_d_rejects_unsupported_curve_command():
    d = "M 0,0 C 1,1 2,2 3,3 z"
    with pytest.raises(ValueError, match=r"unsupported.*'C'"):
        qe._parse_path_d(d)


def test_has_dashed_stroke_true_for_dasharray_attribute():
    elem = ET.fromstring(
        '<path fill="#D7C2AD" stroke="#000000" stroke-dasharray="4" '
        'stroke-width="0.2" d="M 0,0 L 1,1 z"/>'
    )
    assert qe._has_dashed_stroke(elem) is True


def test_has_dashed_stroke_false_for_solid_room():
    elem = ET.fromstring(
        '<path fill="#E9D8A6" stroke="#000000" stroke-width="1.42" '
        'd="M 0,0 L 1,1 z"/>'
    )
    assert qe._has_dashed_stroke(elem) is False


def test_has_dashed_stroke_true_when_in_inline_style():
    elem = ET.fromstring(
        '<path fill="#D7C2AD" style="stroke-dasharray:4;stroke-width:0.2" '
        'd="M 0,0 L 1,1 z"/>'
    )
    assert qe._has_dashed_stroke(elem) is True


def test_pick_door_polyline_finds_the_real_fill_one():
    candidates = [
        ("None", [(247.5, 154.9), (235.8, 154.9)]),   # jamb detail
        ("None", [(235.3, 154.5), (235.3, 155.6)]),   # jamb detail
        ("#E9D8A6", [(247.5, 155.6), (235.8, 155.6)]),  # the real opening line
    ]
    result = qe._pick_door_polyline(candidates)
    assert result == [(247.5, 155.6), (235.8, 155.6)]


def test_pick_door_polyline_returns_none_when_no_real_fill_present():
    candidates = [
        ("None", [(0.0, 0.0), (1.0, 1.0)]),
        ("None", [(1.0, 1.0), (2.0, 2.0)]),
    ]
    assert qe._pick_door_polyline(candidates) is None
