"""
engine_main.py — headless entry point of the packaged engine the Revit add-in starts.

Same Flask app as run.py (which parses --port, --key and the localhost-only guard), with the frozen-exe
paths patched the way main.py patches them for the desktop exe. No window: the add-in is the UI.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault('PYTHONUTF8', '1')

ROOT = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))

import app as app_module  # noqa: E402

UPLOAD_DIR = Path(tempfile.gettempdir()) / 'qbiq-engine-uploads'
UPLOAD_DIR.mkdir(exist_ok=True)
app_module.FRONTEND_DIR = ROOT / 'frontend'
app_module.UPLOAD_DIR = UPLOAD_DIR
app_module.app.static_folder = str(ROOT / 'frontend')

import run  # noqa: E402

if __name__ == '__main__':
    run.main()
