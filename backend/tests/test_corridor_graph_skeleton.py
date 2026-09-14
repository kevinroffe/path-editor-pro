from shapely.geometry import box, Point
import corridor_graph as cg


def test_densify_boundary_covers_perimeter_densely():
    square = box(0, 0, 10, 10)  # perimeter = 40
    pts = cg._densify_boundary(square, spacing=1.0)
    assert len(pts) >= 30  # roughly perimeter/spacing, allow slack
    # every point should lie on (or extremely close to) the square's boundary
    for x, y in pts:
        assert square.boundary.distance(Point(x, y)) < 1e-6


def test_densify_boundary_dedupes_points():
    square = box(0, 0, 10, 10)
    pts = cg._densify_boundary(square, spacing=1.0)
    assert len(pts) == len(set(pts))


def test_voronoi_skeleton_of_long_corridor_has_a_center_running_edge():
    # A long, thin walkable rectangle — the medial axis should be a single
    # line running down its horizontal center.
    corridor = box(0, 0, 20, 2)
    boundary_pts = cg._densify_boundary(corridor, spacing=0.5)
    graph = cg._voronoi_skeleton(corridor, boundary_pts)
    assert graph.number_of_nodes() > 0
    assert graph.number_of_edges() > 0
    # every kept node should be near y=1 (the corridor's centerline) and
    # strictly inside the polygon
    for (x, y) in graph.nodes():
        assert corridor.buffer(1e-6).contains(Point(x, y))
        assert abs(y - 1.0) < 0.6  # medial axis of a straight strip is its centerline
