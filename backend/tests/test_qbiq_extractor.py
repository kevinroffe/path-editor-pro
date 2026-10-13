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
