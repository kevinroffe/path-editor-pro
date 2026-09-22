import networkx as nx
from shapely.geometry import box, Point
import corridor_graph as cg


def test_bridge_doors_across_components_connects_two_rooms():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (4.0, 0.0), weight=4.0)   # component A
    g.add_edge((6.0, 0.0), (10.0, 0.0), weight=4.0)  # component B
    door = [(5.0, -0.1), (5.0, 0.1)]  # centroid at (5, 0), between the two
    bridged = cg._bridge_doors_across_components(g, [door], max_bridge=2.0)
    assert nx.number_connected_components(bridged) == 1


def test_bridge_doors_across_components_respects_max_bridge_distance():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (4.0, 0.0), weight=4.0)
    g.add_edge((100.0, 0.0), (104.0, 0.0), weight=4.0)
    door = [(50.0, 0.0)]
    bridged = cg._bridge_doors_across_components(g, [door], max_bridge=2.0)
    assert nx.number_connected_components(bridged) == 2


def test_build_corridor_graph_on_simple_room():
    room = box(0, 0, 10, 10)
    graph = cg.build_corridor_graph(room, doors=[])
    assert graph is not None
    assert graph.number_of_nodes() > 0
    assert graph.number_of_edges() > 0
    for (x, y) in graph.nodes():
        assert room.buffer(1e-3).contains(Point(x, y))


def test_build_corridor_graph_none_for_empty_polygon():
    from shapely.geometry import Polygon
    assert cg.build_corridor_graph(Polygon(), doors=[]) is None


def test_build_corridor_graph_default_units_to_metres_matches_pre_fix_behavior():
    """
    No units_to_metres passed -> must default to 1.0 and behave EXACTLY as
    before the units-conversion fix (every existing caller/test that doesn't
    pass units_to_metres relies on this).
    """
    room = box(0, 0, 10, 10)
    graph_default = cg.build_corridor_graph(room, doors=[])
    graph_explicit = cg.build_corridor_graph(room, doors=[], units_to_metres=1.0)
    assert graph_default is not None
    assert set(graph_default.nodes()) == set(graph_explicit.nodes())
    assert set(graph_default.edges()) == set(graph_explicit.edges())


def test_build_corridor_graph_units_to_metres_keeps_node_count_reasonable():
    """
    Full-pipeline version of the same crux: with units_to_metres correctly
    applied, a long thin synthetic corridor (1000 raw units == 100m real,
    matching a millimetre-scale DXF's order of magnitude) must produce a
    graph with a small, reasonable node count — not the ~10x-larger one the
    unconverted (pre-fix) code path would produce for this geometry. Sized
    so even the "wrong" behavior completes in well under a second.
    """
    corridor = box(0, 0, 1000, 20)
    graph = cg.build_corridor_graph(corridor, doors=[], units_to_metres=0.1)
    assert graph is not None
    assert graph.number_of_nodes() < 300
