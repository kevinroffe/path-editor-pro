import sys
from pathlib import Path

# Every backend module (app.py, autopath.py, corridor_graph.py, ...) is
# imported as a top-level module, not a package — app.py itself relies on
# this by inserting its own directory onto sys.path at import time. Tests
# need the same thing available BEFORE any test file imports those modules
# directly (e.g. `import corridor_graph`) without going through app.py first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
