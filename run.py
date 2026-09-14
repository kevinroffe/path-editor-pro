#!/usr/bin/env python3
"""
run.py  —  Launch the Revit Walkthrough Tool

Usage:
    python run.py              # default port 5000
    python run.py --port 8080  # custom port
"""
import sys
import os
import argparse
import subprocess

def check_deps():
    missing = []
    for pkg in ['flask', 'flask_cors', 'numpy', 'scipy', 'werkzeug']:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"Missing packages: {', '.join(missing)}")
        print("Run:  pip install -r requirements.txt")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Revit Walkthrough Tool')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()

    check_deps()

    # Add backend to path so sibling modules resolve correctly
    backend = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend')
    sys.path.insert(0, backend)

    # Import after path is set so revit_extractor / svg_generator etc. resolve
    from app import app  # noqa: E402

    print(f"\n  Revit Walkthrough Tool")
    print(f"  ─────────────────────────────────")
    print(f"  Open in browser:  http://{args.host}:{args.port}")
    print(f"  Press Ctrl+C to stop\n")
    app.run(host=args.host, port=args.port, debug=False)

if __name__ == '__main__':
    main()
