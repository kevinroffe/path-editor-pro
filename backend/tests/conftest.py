import sys
from pathlib import Path

import pytest

# Every backend module (app.py, autopath.py, corridor_graph.py, ...) is
# imported as a top-level module, not a package — app.py itself relies on
# this by inserting its own directory onto sys.path at import time. Tests
# need the same thing available BEFORE any test file imports those modules
# directly (e.g. `import corridor_graph`) without going through app.py first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SOURCE_CACHES = ("_LAST_OBSTACLES", "_LAST_FOOTPRINT", "_LAST_DOORS", "_LAST_WALLS", "_LAST_OTHER_OBSTACLES")


@pytest.fixture(autouse=True)
def _reset_app_globals():
    """Start every test with no cached plan, graphs or floor-plan geometry, so test order can't leak state."""
    if (app := sys.modules.get("app")) is not None:
        app._LAST_PLAN = None
        app._LAST_REVIT_RESPONSE = None
        app._LAST_REVIT_MESHES = []
        app._LAST_PLAN_GRAPH.clear()
        app._LAST_CIRC_GRAPH.clear()
        app._LAST_UNITS_TO_METRES = 1.0
        for name in _SOURCE_CACHES:
            getattr(app, name).update(dxf=[], ifc=[])
    yield
