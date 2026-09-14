import networkx as nx
import corridor_graph as cg


def _line_weight(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def test_merge_close_nodes_collapses_near_duplicates():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (5.0, 0.0), weight=5.0)
    g.add_edge((5.0, 0.0), (5.01, 0.02), weight=_line_weight((5.0, 0.0), (5.01, 0.02)))
    g.add_edge((5.01, 0.02), (10.0, 0.0), weight=_line_weight((5.01, 0.02), (10.0, 0.0)))
    merged = cg._merge_close_nodes(g, tol=0.1)
    # the two near-duplicate junction nodes should have collapsed into one
    assert merged.number_of_nodes() == 3


def test_remove_short_stub_segments_drops_dead_end_noise():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (10.0, 0.0), weight=10.0)
    g.add_edge((5.0, 0.0), (5.0, 0.1), weight=0.1)  # short dead-end stub
    cleaned = cg._remove_short_stub_segments(g, min_len=0.5)
    assert (5.0, 0.1) not in cleaned.nodes()
    assert (0.0, 0.0) in cleaned.nodes() and (10.0, 0.0) in cleaned.nodes()


def test_remove_short_stub_segments_keeps_long_dead_ends():
    g = nx.Graph()
    g.add_edge((0.0, 0.0), (10.0, 0.0), weight=10.0)
    g.add_edge((5.0, 0.0), (5.0, 3.0), weight=3.0)  # a real, longer side branch
    cleaned = cg._remove_short_stub_segments(g, min_len=0.5)
    assert (5.0, 3.0) in cleaned.nodes()


def test_rdp_collapses_nearly_collinear_points():
    points = [(0.0, 0.0), (5.0, 0.01), (10.0, 0.0)]
    simplified = cg._rdp(points, epsilon=0.5)
    assert simplified == [(0.0, 0.0), (10.0, 0.0)]


def test_rdp_keeps_a_real_corner():
    points = [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
    simplified = cg._rdp(points, epsilon=0.5)
    assert (5.0, 5.0) in simplified


def test_simplify_branches_reduces_a_noisy_straight_chain():
    g = nx.Graph()
    chain = [(float(i), 0.01 if i % 2 else 0.0) for i in range(11)]
    for a, b in zip(chain, chain[1:]):
        g.add_edge(a, b, weight=_line_weight(a, b))
    simplified = cg._simplify_branches(g, epsilon=0.5)
    assert simplified.number_of_nodes() < g.number_of_nodes()
    assert chain[0] in simplified.nodes() and chain[-1] in simplified.nodes()
