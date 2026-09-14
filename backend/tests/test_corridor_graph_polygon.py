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


def test_compute_bounds_from_walls_and_footprint():
    walls = [[(0, 0), (10, 0)], [(0, 0), (0, 5)]]
    bounds = cg.compute_bounds(walls, [])
    xmin, ymin, xmax, ymax = bounds
    assert xmin < 0 and ymin < 0  # margin applied
    assert xmax > 10 and ymax > 5


def test_build_walkable_polygon_room_with_gap_in_south_wall():
    # A 10x10 room. North/east/west walls solid; south wall has a real 2-unit
    # gap in the middle (an actual doorway drawn as a gap, no door needed
    # to force it open).
    walls = [
        [(0, 10), (10, 10)],   # north
        [(10, 0), (10, 10)],   # east
        [(0, 0), (0, 10)],     # west
        [(0, 0), (4, 0)],      # south-west segment
        [(6, 0), (10, 0)],     # south-east segment (2-unit gap between x=4..6)
    ]
    bounds = cg.compute_bounds(walls, [])
    walkable = cg.build_walkable_polygon(
        walls, doors=[], other_obstacles=[], footprint=[],
        bounds=bounds, clearance_m=0.1, units_to_metres=1.0,
    )
    assert walkable is not None
    assert not walkable.is_empty
    # Room interior should be walkable.
    assert walkable.covers(Point(5, 5))
    # The gap itself should be walkable (it's a real opening, no notch needed).
    assert walkable.covers(Point(5, 0.2))


def test_build_walkable_polygon_no_footprint_uses_bounding_envelope():
    walls = [[(0, 0), (10, 0)]]
    bounds = cg.compute_bounds(walls, [])
    walkable = cg.build_walkable_polygon(
        walls, doors=[], other_obstacles=[], footprint=[],
        bounds=bounds, clearance_m=0.1, units_to_metres=1.0,
    )
    assert walkable is not None
    # A point well within bounds but away from the single wall line is walkable.
    assert walkable.covers(Point(5, 5))


def test_build_walkable_polygon_empty_when_fully_blocked():
    # A footprint fully covered by a buffered obstacle leaves nothing walkable.
    walls = [[(0, 0), (0, 0)]]  # degenerate, ignored (len < 2 after filtering isn't true here but harmless)
    footprint = [[(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]]
    other_obstacles = [[(-1, -1), (3, -1), (3, 3), (-1, 3), (-1, -1)]]  # covers the whole footprint
    bounds = (0, 0, 2, 2)
    walkable = cg.build_walkable_polygon(
        walls, doors=[], other_obstacles=other_obstacles, footprint=footprint,
        bounds=bounds, clearance_m=0.0, units_to_metres=1.0,
    )
    assert walkable is None
