"""
main.py — exe entry point
Starts the Flask server in a background thread, opens the browser,
and shows a small status window. Does NOT modify any existing source files.
"""
import sys
import os
import threading
import webbrowser
import time
import tkinter as tk
from pathlib import Path

os.environ['PYTHONUTF8'] = '1'

# ── Resolve paths (works both frozen and from source) ─────────────────────────
if getattr(sys, 'frozen', False):
    # Running as PyInstaller exe — files extracted to sys._MEIPASS
    ROOT      = Path(sys._MEIPASS)
    EXE_DIR   = Path(sys.executable).parent
    UPLOAD_DIR = EXE_DIR / 'uploads'
else:
    ROOT      = Path(__file__).parent
    EXE_DIR   = ROOT
    UPLOAD_DIR = ROOT / 'uploads'

FRONTEND_DIR = ROOT / 'frontend'
BACKEND_DIR  = ROOT / 'backend'
UPLOAD_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(BACKEND_DIR))

PORT = 5001

# ── Import Flask app and patch its paths ──────────────────────────────────────
import app as app_module
app_module.FRONTEND_DIR = FRONTEND_DIR
app_module.UPLOAD_DIR   = UPLOAD_DIR
app_module.app.static_folder = str(FRONTEND_DIR)

flask_app = app_module.app

# ── Server thread ─────────────────────────────────────────────────────────────
def run_server():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    flask_app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False)

server = threading.Thread(target=run_server, daemon=True)
server.start()

# Give the server a moment to start before opening the browser
time.sleep(1.2)
webbrowser.open(f'http://127.0.0.1:{PORT}')

# ── Status window ─────────────────────────────────────────────────────────────
root = tk.Tk()
root.title('qbiq Path Editor')
root.geometry('340x150')
root.resizable(False, False)
root.configure(bg='#f4f7fd')

try:
    root.iconbitmap(default='')
except Exception:
    pass

tk.Label(root, text='qbiq Path Editor', font=('Segoe UI', 15, 'bold'),
         bg='#f4f7fd', fg='#1a2340').pack(pady=(22, 4))

tk.Label(root, text=f'Running at  http://127.0.0.1:{PORT}',
         font=('Segoe UI', 10), bg='#f4f7fd', fg='#2563eb').pack()

tk.Label(root, text='Close this window to shut down the server.',
         font=('Segoe UI', 9), bg='#f4f7fd', fg='#9aaac8').pack(pady=(6, 14))

btn_frame = tk.Frame(root, bg='#f4f7fd')
btn_frame.pack()

def open_browser():
    webbrowser.open(f'http://127.0.0.1:{PORT}')

tk.Button(btn_frame, text='Open in Browser', command=open_browser,
          bg='#2563eb', fg='white', font=('Segoe UI', 10, 'bold'),
          relief='flat', padx=14, pady=6, cursor='hand2').pack(side='left', padx=6)

tk.Button(btn_frame, text='Quit', command=root.destroy,
          bg='#eef2fa', fg='#4e5d80', font=('Segoe UI', 10),
          relief='flat', padx=14, pady=6, cursor='hand2').pack(side='left', padx=6)

root.mainloop()
