import networkx as nx
from shapely.geometry import box, Point
import corridor_graph as cg


def test_bridge_doors_across_components_connects_two_rooms():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (4.0, 0.0), weight=4.0)   # component A
    g.add_edge((6.0, 0.0), (10.0, 0.0), weight=4.0)  # component B
    door = [(5.0, -0.1), (5.0, 0.1)]  # centroid at (5, 0), between the two
    bridged = cg._bridge_doors_across_components(g, [door], max_bridge_m=2.0)
    assert nx.number_connected_components(bridged) == 1


def test_bridge_doors_across_components_respects_max_bridge_distance():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (4.0, 0.0), weight=4.0)
    g.add_edge((100.0, 0.0), (104.0, 0.0), weight=4.0)
    door = [(50.0, 0.0)]
    bridged = cg._bridge_doors_across_components(g, [door], max_bridge_m=2.0)
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
