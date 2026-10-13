import copy
import json

import pytest

import qbiq_extractor as qe

_ENCLOSED_ROOM = {
    "space_type": "Conference",
    "geometry": "POLYGON ((0 0, 500 0, 500 500, 0 500, 0 0))",
    "doors": [{"door_line": "LINESTRING (500 0, 500 500)", "show_door": True}],
    "door_geometry": (
        "GEOMETRYCOLLECTION (LINESTRING (492.5 200, 500 200), LINESTRING (500 200, 500 210), "
        "LINESTRING (492.5 300, 500 300), LINESTRING (500 300, 500 290), LINESTRING (500 300, 410 300))"
    ),
    "stencil_geometry": (
        "GEOMETRYCOLLECTION (GEOMETRYCOLLECTION (LINESTRING (100 100, 200 100), "
        "POLYGON ((100 200, 200 200, 200 300, 100 300, 100 200))), "
        "MULTILINESTRING ((300 100, 350 100), (300 150, 350 150)), POINT (50 50))"
    ),
}

_OPEN_ROOM = {
    "space_type": "Kitchen",
    "geometry": "POLYGON ((1500 1000, 2000 1000, 2000 1500, 1500 1500, 1500 1000))",
    "doors": [{"door_line": "LINESTRING (1500 1000, 1500 1500)", "show_door": False}],
    "door_geometry": "GEOMETRYCOLLECTION (LINESTRING (1500 1200, 1500 1300))",
    "stencil_geometry": "GEOMETRYCOLLECTION EMPTY",
}

DESIGN = {
    "job_code": "TEST0001",
    "rooms": [_ENCLOSED_ROOM, _OPEN_ROOM],
    "nfp_data": {
        "fill": "POLYGON ((0 0, 2000 0, 2000 1500, 0 1500, 0 0))",
        "walls": [
            {"uid": "a", "type": "wall", "corner1": [0, 0], "corner2": [2000, 0], "exterior": True},
            {"uid": "b", "type": "wall", "corner1": [2000, 0], "corner2": [2000, 1500], "exterior": True},
            {"uid": "c", "type": "wall", "corner1": [2000, 1500], "corner2": [0, 1500], "exterior": True},
            {"uid": "d", "type": "wall", "corner1": [0, 1500], "corner2": [0, 0], "exterior": True},
        ],
        "interior_walls": [],
        "cores": [],
        "columns": "MULTIPOLYGON (((900 700, 960 700, 960 760, 900 760, 900 700)))",
        "windows": [{"uid": "w", "type": "window", "corner1": [600, 0], "corner2": [900, 0], "exterior": True}],
    },
}


def _extract(tmp_path, data=DESIGN):
    path = tmp_path / "design.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return qe.extract_qbiq_design(str(path))


def _edge_set(walls):
    return {frozenset(map(tuple, w)) for w in walls}


def _with_room(room):
    data = copy.deepcopy(DESIGN)
    data["rooms"] = [room]
    return data


def test_floor_plate_is_first_and_closed(tmp_path):
    geo = _extract(tmp_path)
    plate = geo.spaces[0]
    assert plate[0] == plate[-1]
    assert {tuple(p) for p in plate} == {(0, 0), (2000, 0), (2000, 1500), (0, 1500)}
    assert geo.source == "qbiq" and geo.meshes == []


def test_every_room_is_a_space(tmp_path):
    assert len(_extract(tmp_path).spaces) == 3


def test_enclosed_room_edges_are_walls_and_open_room_edges_are_not(tmp_path):
    edges = _edge_set(_extract(tmp_path).walls)
    assert frozenset({(500.0, 0.0), (500.0, 500.0)}) in edges
    assert frozenset({(0.0, 500.0), (500.0, 500.0)}) in edges
    assert frozenset({(1500.0, 1000.0), (1500.0, 1500.0)}) not in edges
    assert frozenset({(1500.0, 1000.0), (2000.0, 1000.0)}) not in edges
    assert len(edges) == 8  # 4 exterior + 4 enclosed-room edges


def test_all_walls_are_two_point_segments(tmp_path):
    assert all(len(w) == 2 for w in _extract(tmp_path).walls)


def test_door_trimmed_to_jamb_extent_and_hidden_door_skipped(tmp_path):
    doors = _extract(tmp_path).doors
    assert len(doors) == 1
    (a, b), = doors
    assert a == pytest.approx((500, 200)) and b == pytest.approx((500, 300))


def test_door_falls_back_to_90_units_at_midpoint(tmp_path):
    room = dict(_ENCLOSED_ROOM, door_geometry="GEOMETRYCOLLECTION (LINESTRING (250 250, 260 260))")
    (a, b), = _extract(tmp_path, _with_room(room)).doors
    assert a == pytest.approx((500, 205)) and b == pytest.approx((500, 295))


def test_door_moves_to_room_edge_its_geometry_touches(tmp_path):
    room = dict(_ENCLOSED_ROOM, door_geometry="GEOMETRYCOLLECTION (LINESTRING (100 500, 100 492.5), LINESTRING (200 500, 200 492.5))")
    (a, b), = _extract(tmp_path, _with_room(room)).doors
    assert sorted([tuple(a), tuple(b)]) == [pytest.approx((100, 500)), pytest.approx((200, 500))]


def test_door_drawn_a_wall_thickness_inside_another_edge_is_still_found(tmp_path):
    room = dict(_ENCLOSED_ROOM, door_geometry="GEOMETRYCOLLECTION (LINESTRING (100 493, 100 485.5), LINESTRING (200 493, 200 485.5))")
    (a, b), = _extract(tmp_path, _with_room(room)).doors
    assert sorted([tuple(a), tuple(b)]) == [pytest.approx((100, 500)), pytest.approx((200, 500))]


def test_per_door_geometry_overrides_room_geometry(tmp_path):
    room = dict(_ENCLOSED_ROOM, doors=[{
        "door_line": "LINESTRING (500 0, 500 500)", "show_door": True,
        "door_geometry": "GEOMETRYCOLLECTION (LINESTRING (500 50, 500 150))",
    }])
    (a, b), = _extract(tmp_path, _with_room(room)).doors
    assert a == pytest.approx((500, 50)) and b == pytest.approx((500, 150))


def test_door_without_door_line_uses_the_room_edge_its_geometry_touches(tmp_path):
    room = dict(_ENCLOSED_ROOM, doors=[{
        "door_line": None, "show_door": True,
        "door_geometry": "GEOMETRYCOLLECTION (LINESTRING (0 100, 0 180))",
    }])
    (a, b), = _extract(tmp_path, _with_room(room)).doors
    assert sorted([tuple(a), tuple(b)]) == [pytest.approx((0, 100)), pytest.approx((0, 180))]


def test_two_doors_in_one_room_each_get_their_own_opening(tmp_path):
    room = dict(
        _ENCLOSED_ROOM,
        doors=[
            {"door_line": "LINESTRING (500 0, 500 500)", "show_door": True},
            {"door_line": "LINESTRING (0 500, 500 500)", "show_door": True},
        ],
        door_geometry="GEOMETRYCOLLECTION (LINESTRING (500 200, 500 300), LINESTRING (300 500, 400 500))",
    )
    doors = sorted(sorted(tuple(p) for p in d) for d in _extract(tmp_path, _with_room(room)).doors)
    assert doors[0] == [pytest.approx((300, 500)), pytest.approx((400, 500))]
    assert doors[1] == [pytest.approx((500, 200)), pytest.approx((500, 300))]


def test_columns_windows_and_furniture(tmp_path):
    geo = _extract(tmp_path)
    assert len(geo.columns) == 1 and geo.columns[0][0] == geo.columns[0][-1]
    assert len(geo.windows) == 1 and len(geo.windows[0]) == 2
    assert len(geo.furniture) == 4  # line, polygon ring, 2 multiline parts; point ignored


def test_units_are_centimetres(tmp_path):
    assert _extract(tmp_path).units_to_metres == 0.01


def test_malformed_room_is_skipped_without_aborting(tmp_path):
    data = copy.deepcopy(DESIGN)
    data["rooms"].insert(0, {"space_type": "Broken", "geometry": "POLYGON ((garbage", "doors": []})
    geo = _extract(tmp_path, data)
    assert len(geo.spaces) == 3
    assert len(geo.doors) == 1


def test_non_design_json_raises(tmp_path):
    with pytest.raises(ValueError):
        _extract(tmp_path, {"perimeter_ls": []})


def test_is_qbiq_design():
    assert qe.is_qbiq_design(DESIGN)
    assert not qe.is_qbiq_design({"rooms": []})
    assert not qe.is_qbiq_design({"perimeter_ls": [], "columns_ls": []})
