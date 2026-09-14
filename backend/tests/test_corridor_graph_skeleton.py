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


def test_voronoi_skeleton_of_long_corridor_finds_the_centerline():
    # A long, thin walkable rectangle. The RAW Voronoi skeleton of a
    # rectangle is not just its centerline — it also includes short
    # diagonal "corner bisector" branches near each short end (the real,
    # topologically correct medial axis of any w>h rectangle), which
    # Task 5's cleanup (stub removal) prunes later — NOT this function.
    # So this test only checks that every kept node stays inside the
    # polygon and that the true centerline was actually found, not that
    # every raw node is already centerline-only (that would be false for
    # the correct algorithm, not just a noisy one).
    corridor = box(0, 0, 20, 2)
    boundary_pts = cg._densify_boundary(corridor, spacing=0.5)
    graph = cg._voronoi_skeleton(corridor, boundary_pts)
    assert graph.number_of_nodes() > 0
    assert graph.number_of_edges() > 0
    for (x, y) in graph.nodes():
        assert corridor.buffer(1e-6).contains(Point(x, y))
    # the true centerline, away from the end effects near x=0/x=20, must
    # be represented by at least one node
    assert any(abs(x - 10.0) < 1.0 and abs(y - 1.0) < 0.1 for (x, y) in graph.nodes())
