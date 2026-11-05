"""A stand-in for the real engine: serves GET / and key-guarded /api/* on 127.0.0.1."""
import argparse
import http.server
import os

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--key", default=None)
args = parser.parse_args()
key = args.key or os.environ.get("QBIQ_ENGINE_KEY")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/") and self.headers.get("X-Qbiq-Key") != key:
            self.send_response(403)
            self.end_headers()
            return
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
