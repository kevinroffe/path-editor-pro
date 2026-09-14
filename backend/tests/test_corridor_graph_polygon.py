from shapely.geometry import Point
import corridor_graph as cg


def test_polyline_to_shape_closed_polygon_keeps_real_area():
    # A 2x2 square, closed (first point repeated at the end)
    square = [(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]
    shape = cg._polyline_to_shape(square, buffer_amt=0.0)
    assert shape.area > 3.9  # ~4, allow for float slop


def test_polyline_to_shape_open_line_needs_buffer_for_area():
    line = [(0, 0), (5, 0)]
    shape = cg._polyline_to_shape(line, buffer_amt=0.5)
    assert shape.area > 0
    # buffering a 5-unit line by 0.5 gives a stadium shape close to 5*1 + pi*0.25^2... just check it's reasonably sized
    assert 4.0 < shape.area < 6.5


def test_polyline_to_shape_open_line_gets_minimum_thickness_even_at_zero_buffer():
    # A raw 2-point wall "line" (zero-width) must not vanish entirely even
    # when the caller passes buffer_amt=0.0 (the last clearance-retry level
    # in autopath.py's find_path uses exactly this) — otherwise a wall
    # represented as a bare LINE entity would silently stop blocking
    # anything at the most permissive retry level, unlike the grid approach
    # where rasterizing a line's bbox always yields at least one blocked
    # grid cell's worth of thickness.
    line = [(0, 0), (5, 0)]
    shape = cg._polyline_to_shape(line, buffer_amt=0.0, min_line_buffer=0.05)
    assert shape.area > 0


def test_build_wall_polygon_door_notch_creates_real_gap():
    # A single long wall line with a door at its midpoint.
    wall = [(0, 0), (10, 0)]
    door = [(5, -0.05), (5, 0.05)]
    wall_poly = cg._build_wall_polygon([wall], [door], clearance=0.3, door_half=0.6,
                                        min_line_buffer=0.05)
    # The door's own location must now be OUTSIDE the (notched) wall shape.
    assert not wall_poly.covers(Point(5, 0))
    # A point far from the door, still on the wall line, must still be blocked.
    assert wall_poly.covers(Point(1, 0))


def test_build_wall_polygon_no_doors_is_solid():
    wall = [(0, 0), (10, 0)]
    wall_poly = cg._build_wall_polygon([wall], [], clearance=0.3, door_half=0.6,
                                        min_line_buffer=0.05)
    assert wall_poly.covers(Point(5, 0))
