import json
import os
import tempfile
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


def test_has_dashed_stroke_false_for_literal_none_value():
    elem = ET.fromstring(
        '<path fill="#E9D8A6" stroke-dasharray="none" d="M 0,0 L 1,1 z"/>'
    )
    assert qe._has_dashed_stroke(elem) is False


def test_has_dashed_stroke_false_for_none_in_inline_style():
    elem = ET.fromstring(
        '<path fill="#E9D8A6" style="stroke-dasharray:none" d="M 0,0 L 1,1 z"/>'
    )
    assert qe._has_dashed_stroke(elem) is False


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


_SVG_FIXTURE = """<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
<desc>job_code="TEST0001"</desc>
<g id="maing"><g id="designg"><g id="prop">
<g id="ext"></g>
<g id="rooms">
<path fill="#E9D8A6" stroke="#000000" stroke-width="1.42" class="d0 r1 office c1 h1 a1"
      d="M 0,0 L 10,0 L 10,10 L 0,10 L 0,0 z" />
<polyline points="4,0 4,-1" fill="None" stroke="#000000" stroke-width="0.21"
          class="r1 c1 door_id_abc regular main"/>
<polyline points="6,0 4,0" fill="#E9D8A6" stroke="white" stroke-width="1.7"
          class="r1 c1 door_id_abc regular main"/>
<path fill="#D7C2AD" stroke="#000000" stroke-dasharray="4" stroke-width="0.2"
      class="d0 r2 comfort-zone c2 h1 a1"
      d="M 10,0 L 20,0 L 20,10 L 10,10 L 10,0 z" />
</g>
<g id="cols"></g>
</g></g></g>
</svg>"""


def test_extract_rooms_and_doors_separates_solid_from_dashed():
    root = ET.fromstring(_SVG_FIXTURE)
    walls, spaces, doors = qe._extract_rooms_and_doors(root)
    # solid room (r1) contributes both a wall ring and a space; dashed
    # room (r2) contributes a space only
    assert len(spaces) == 2
    assert len(walls) == 1
    assert walls[0][0] == (0.0, 0.0) and walls[0][-1] == (0.0, 0.0)
    # exactly one door, using the real-fill polyline's points
    assert doors == [[(6.0, 0.0), (4.0, 0.0)]]


def test_extract_rooms_and_doors_skips_a_door_with_no_real_fill_polyline():
    # Review Focus: a door_id group where every polyline has fill="None" —
    # must be skipped (logged, not crashed), not invented or mis-picked.
    svg = """<svg xmlns="http://www.w3.org/2000/svg">
    <g id="maing"><g id="designg"><g id="prop">
    <g id="ext"></g>
    <g id="rooms">
    <path fill="#E9D8A6" stroke="#000000" stroke-width="1.42" class="d0 r9 office c9 h1 a1"
          d="M 0,0 L 10,0 L 10,10 L 0,10 L 0,0 z" />
    <polyline points="4,0 4,-1" fill="None" stroke="#000000" stroke-width="0.21"
              class="r9 c9 door_id_broken regular main"/>
    <polyline points="6,0 4,0" fill="None" stroke="#000000" stroke-width="0.21"
              class="r9 c9 door_id_broken regular main"/>
    </g>
    <g id="cols"></g>
    </g></g></g>
    </svg>"""
    root = ET.fromstring(svg)
    walls, spaces, doors = qe._extract_rooms_and_doors(root)
    assert len(spaces) == 1  # the room itself still parses fine
    assert doors == []       # the broken door group is skipped, not guessed


def test_extract_json_structure_categorises_each_key():
    data = {
        "perimeter_ls": [[[0, 0], [10, 0]], [[10, 0], [10, 10]],
                         [[10, 10], [0, 10]], [[0, 10], [0, 0]]],
        "core_ls": [[[2, 2], [3, 2]], [[3, 2], [3, 3]],
                    [[3, 3], [2, 3]], [[2, 3], [2, 2]]],
        "columns_ls": [[[5, 5], [5.2, 5]], [[5.2, 5], [5.2, 5.2]],
                       [[5.2, 5.2], [5, 5.2]], [[5, 5.2], [5, 5]]],
        "qbiq_walls_ls": [],
        "mullions": [[[0, 0], [0, 1]]],
        "perimeter": [[0, 0]], "core": [[2, 2]], "columns": [[5, 5]],
        "qbiq_walls": [],
    }
    walls, columns, windows, extent_points = qe._extract_json_structure(data)
    # perimeter + core both become walls -> 2 closed chains
    assert len(walls) == 2
    assert len(columns) == 1
    assert columns[0][0] == columns[0][-1]
    assert windows == [[(0.0, 0.0), (0.0, 1.0)]]
    assert (10.0, 10.0) in extent_points


def test_extract_json_structure_handles_populated_qbiq_walls_and_mullions():
    # Review Focus: qbiq_walls_ls / mullions actually populated, not just
    # the empty case from the one real reference file.
    data = {
        "perimeter_ls": [], "core_ls": [], "columns_ls": [],
        "qbiq_walls_ls": [[[1, 1], [1, 2]], [[1, 2], [2, 2]],
                          [[2, 2], [2, 1]], [[2, 1], [1, 1]]],
        "mullions": [[[9, 9], [9, 10]], [[20, 20], [20, 21]]],
        "perimeter": [], "core": [], "columns": [], "qbiq_walls": [],
    }
    walls, columns, windows, extent_points = qe._extract_json_structure(data)
    assert len(walls) == 1  # the qbiq_walls_ls square
    assert walls[0][0] == walls[0][-1]
    assert len(windows) == 2  # two separate, unconnected mullion bars


def test_fix_implausible_units_corrects_centimetre_declared_as_metre_scale():
    # A building whose real size is ~38m, if units_to_metres were wrongly 1.0
    # instead of 0.01, would declare an impossible 3800m footprint.
    extent_points = [(0.0, 0.0), (3800.0, 2500.0)]
    corrected = qe._fix_implausible_units(1.0, extent_points)
    assert abs(corrected - 0.01) < 1e-9


def test_fix_implausible_units_leaves_already_plausible_scale_alone():
    extent_points = [(0.0, 0.0), (3800.0, 2500.0)]
    corrected = qe._fix_implausible_units(0.01, extent_points)
    assert corrected == 0.01


_JSON_FIXTURE = {
    "perimeter_ls": [[[0, 0], [2000, 0]], [[2000, 0], [2000, 2000]],
                     [[2000, 2000], [0, 2000]], [[0, 2000], [0, 0]]],
    "core_ls": [], "columns_ls": [
        [[900, 900], [920, 900]], [[920, 900], [920, 920]],
        [[920, 920], [900, 920]], [[900, 920], [900, 900]],
    ],
    "qbiq_walls_ls": [], "mullions": [],
    "perimeter": [], "core": [], "columns": [], "qbiq_walls": [],
}


def _write_fixture_files(tmpdir, fixture=_JSON_FIXTURE):
    json_path = os.path.join(tmpdir, "job.json")
    svg_path = os.path.join(tmpdir, "job.svg")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(fixture, f)
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(_SVG_FIXTURE)
    return json_path, svg_path


def test_extract_qbiq_includes_closed_perimeter_as_first_space():
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path, svg_path = _write_fixture_files(tmpdir)
        geo = qe.extract_qbiq(json_path, svg_path)

    plate = geo.spaces[0]
    assert plate[0] == plate[-1]
    assert set(plate) == {(0.0, 0.0), (2000.0, 0.0), (2000.0, 2000.0), (0.0, 2000.0)}


def test_to_segments_explodes_closed_ring():
    ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    segs = qe._to_segments([ring])
    assert len(segs) == 4
    assert all(len(sg) == 2 for sg in segs)


def test_extract_qbiq_walls_are_two_point_segments():
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path, svg_path = _write_fixture_files(tmpdir)
        geo = qe.extract_qbiq(json_path, svg_path)

    assert all(len(w) == 2 for w in geo.walls)


def test_floor_plates_ignores_open_perimeter_chain():
    assert qe._floor_plates({"perimeter_ls": [[[0, 0], [10, 0]], [[10, 0], [10, 10]]]}) == []


def test_extract_qbiq_produces_a_valid_level_geometry():
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path, svg_path = _write_fixture_files(tmpdir)
        geo = qe.extract_qbiq(json_path, svg_path, level_name="L-1")

    assert geo.level_name == "L-1"
    assert geo.source == "qbiq"
    assert geo.units_to_metres == 0.01
    # JSON perimeter + SVG solid room (r1) -> at least 2 wall rings;
    # dashed room (r2) contributes no wall
    assert len(geo.walls) == 8  # 4 perimeter segments + 4 for r1's ring
    assert len(geo.columns) == 1
    assert len(geo.spaces) == 3  # floor plate + r1 (solid) + r2 (dashed)
    assert len(geo.doors) == 1
    assert geo.meshes == []


def test_extract_qbiq_applies_units_plausibility_correction():
    fixture = dict(_JSON_FIXTURE)
    fixture["perimeter_ls"] = [
        [[0, 0], [400000, 0]], [[400000, 0], [400000, 400000]],
        [[400000, 400000], [0, 400000]], [[0, 400000], [0, 0]],
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path, svg_path = _write_fixture_files(tmpdir, fixture)
        geo = qe.extract_qbiq(json_path, svg_path)

    # 400000 units at 0.01 m/unit = 4000m (implausible) -> corrected by /100 to 40m
    assert geo.units_to_metres == pytest.approx(0.0001)
