import random
import time
from pathlib import Path

import pytest

import app as app_module

# NOTE: the brief's UPLOADS_DIR computation (parent.parent.parent / "uploads")
# resolves to .worktrees/corridor-graph-routing/uploads/ when this test runs
# from inside a git worktree, which does not exist there — uploads/ is
# gitignored and only exists in the main repo checkout. Point directly at the
# real location instead.
UPLOADS_DIR = Path(r"C:\Users\kevin\revit-walkthrough-v2\uploads")
QQQQ_FILE = UPLOADS_DIR / "QQQQ_TEST-0001_-_Floor_Plan_-_L-0.dxf"
REAL_FLOOD_FILE = UPLOADS_DIR / "Classify_DXF_45715-Sep_02nd_2026_12_38_33_PM.dxf"


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _upload_real_file(client, path: Path):
    """
    Uploads a copy of the real fixture under a DIFFERENT filename than the
    source. app.py's /api/upload saves the incoming file to
    uploads/<secure_filename(f.filename)> — if we uploaded using the
    fixture's own original name, Flask would write the save back to the
    exact same path we're reading it from mid-upload (the fixture lives in
    that same uploads/ directory), corrupting the committed test fixture.
    A harmless differently-named temp copy avoids that entirely.
    """
    assert path.exists(), f"expected real test fixture at {path}"
    temp_name = f"pytest_copy_{path.name}"
    with open(path, "rb") as f:
        data = {"file": (f, temp_name)}
        resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _random_point_within(bounds, rng):
    return [
        rng.uniform(bounds["xmin"], bounds["xmax"]),
        rng.uniform(bounds["ymin"], bounds["ymax"]),
    ]


def _stress_test_file(client, path: Path, n_triples: int, seed: int):
    upload = _upload_real_file(client, path)
    bounds = upload["bounds"]
    rng = random.Random(seed)

    failures = 0
    point_counts = []

    for _ in range(n_triples):
        points = [_random_point_within(bounds, rng) for _ in range(5)]  # 5-point Smart Path
        resp = client.post("/api/autopath", json={"points": points})
        assert resp.status_code == 200
        waypoints = resp.get_json()["waypoints"]
        if not waypoints or len(waypoints) < 2:
            failures += 1
        else:
            point_counts.append(len(waypoints))

    return failures, point_counts


def test_qqqq_test_file_stress_5point_routes(client):
    start = time.time()
    failures, point_counts = _stress_test_file(client, QQQQ_FILE, n_triples=40, seed=42)
    elapsed = time.time() - start
    print(f"\nQQQQ_TEST-0001: {failures}/40 failures, "
          f"avg pts={sum(point_counts)/max(len(point_counts),1):.1f}, "
          f"max pts={max(point_counts, default=0)}, elapsed={elapsed:.1f}s")
    # Same bar as the grid-A* baseline established earlier this project
    # (0/40 failures) — the corridor graph (or its fallback) must not
    # regress this.
    assert failures == 0


def test_real_flood_file_stress_5point_routes(client):
    start = time.time()
    failures, point_counts = _stress_test_file(client, REAL_FLOOD_FILE, n_triples=20, seed=7)
    elapsed = time.time() - start
    print(f"\nreal FLOOD file: {failures}/20 failures, "
          f"avg pts={sum(point_counts)/max(len(point_counts),1):.1f}, "
          f"max pts={max(point_counts, default=0)}, elapsed={elapsed:.1f}s")
    assert failures == 0


def test_corridor_graph_builds_in_reasonable_time_on_largest_real_file(client):
    upload = _upload_real_file(client, REAL_FLOOD_FILE)
    bounds = upload["bounds"]
    start = time.time()
    resp = client.post("/api/autopath", json={
        "start": [bounds["xmin"] + 1, bounds["ymin"] + 1],
        "end": [bounds["xmax"] - 1, bounds["ymax"] - 1],
    })
    elapsed = time.time() - start
    assert resp.status_code == 200
    print(f"\nFirst Smart Path call after upload (graph build + route): {elapsed:.1f}s")
    # Generous ceiling — this is the ONE lazy-build call per (upload,
    # clearance_m); a second call right after should be much faster since
    # the graph is now cached.
    assert elapsed < 30.0

    start2 = time.time()
    resp2 = client.post("/api/autopath", json={
        "start": [bounds["xmin"] + 2, bounds["ymin"] + 2],
        "end": [bounds["xmax"] - 2, bounds["ymax"] - 2],
    })
    elapsed2 = time.time() - start2
    assert resp2.status_code == 200
    print(f"Second Smart Path call (graph cached): {elapsed2:.1f}s")
    assert elapsed2 < elapsed


def test_door_clearing_regression_does_not_erase_nearby_furniture(client, monkeypatch):
    """
    Reproduces the exact real regression found earlier this project: a
    small room (4m, smaller than an over-large blind clearing radius would
    have been) with an off-center door entity (centroid NOT on the true
    gap) and furniture flanking the real opening on both sides. The
    corridor-graph door-notch must open the real gap and must NOT swallow
    the flanking furniture.
    """
    import corridor_graph as cg
    from shapely.geometry import Point

    # A 4m-wide room split by a partition wall with a real 0.9m doorway gap
    # centered at x=2; door entity's own centroid is 1.3m off, on the solid
    # wall (mirrors the real file's misbehaved door geometry).
    partition_left = [(0.0, 2.0), (1.55, 2.0)]
    partition_right = [(2.45, 2.0), (4.0, 2.0)]
    door = [(0.7, 2.0), (0.7, 2.05)]  # centroid ~x=0.7, nowhere near the real gap at x=2
    furniture_left = [(0.3, 1.5), (0.9, 1.5), (0.9, 1.9), (0.3, 1.9), (0.3, 1.5)]
    furniture_right = [(3.1, 1.5), (3.7, 1.5), (3.7, 1.9), (3.1, 1.9), (3.1, 1.5)]

    bounds = cg.compute_bounds([partition_left, partition_right], [])
    walkable = cg.build_walkable_polygon(
        [partition_left, partition_right], [door], [furniture_left, furniture_right], [],
        bounds=bounds, clearance_m=0.1, units_to_metres=1.0,
    )
    assert walkable is not None
    # the real gap is walkable
    assert walkable.covers(Point(2.0, 2.0))
    # both furniture pieces remain solid obstacles (not swallowed by an
    # over-eager notch)
    assert not walkable.covers(Point(0.6, 1.7))
    assert not walkable.covers(Point(3.4, 1.7))
