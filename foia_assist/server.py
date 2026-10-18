"""Minimal web app on the standard library: no framework, no CDN, nothing to
pull over the network, so it runs the same in an enclave as on a laptop.

    python -m foia_assist serve --port 8080
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .pipeline import Assistant

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 64 * 1024


def make_handler(assistant: Assistant):
    class Handler(BaseHTTPRequestHandler):
        server_version = "foia-assist"

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/endpoints":
                eps = [{k: e[k] for k in ("name", "kind", "authorized_level", "description")}
                       for e in assistant.endpoints["endpoints"].values()]
                self._json(200, {"default": assistant.endpoints["default"], "endpoints": eps})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/process":
                return self._json(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                return self._json(413, {"error": "request too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                text = str(body.get("request", "")).strip()
                if not text:
                    return self._json(400, {"error": "request text is required"})
                packet = assistant.process(text, str(body.get("requester_type", "other")),
                                           body.get("endpoint") or None)
                self._json(200, packet)
            except ValueError as e:
                self._json(400, {"error": str(e)})
            except Exception as e:  # surface, don't crash the server
                self._json(502, {"error": f"{type(e).__name__}: {e}"})

        def log_message(self, fmt, *args):
            pass  # requests are in the audit log; keep stdout quiet

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8080, assistant: Assistant | None = None):
    httpd = ThreadingHTTPServer((host, port), make_handler(assistant or Assistant()))
    print(f"FOIA assistant on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return httpd
