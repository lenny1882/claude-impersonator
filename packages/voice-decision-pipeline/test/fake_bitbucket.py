"""A fake Bitbucket REST API for the tests: serves the routes fixtures.py
wrote, needs basic auth matching the test ~/.netrc, and refuses any path not
listed with 404. Prints its port, then serves until killed.

    python3 fake_bitbucket.py <routes.json>
"""

import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

ROUTES = json.load(open(sys.argv[1]))
AUTH = "Basic " + base64.b64encode(b"tester:secret-token").decode()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.headers.get("Authorization") != AUTH:
            self.send_response(401); self.end_headers(); return
        path = urlparse(self.path).path
        body = ROUTES.get(path)
        if body is None:
            self.send_response(404); self.end_headers(); return
        if isinstance(body, dict) and "__raw__" in body:
            data, ctype = body["__raw__"].encode(), "text/plain"
        else:
            data, ctype = json.dumps(body).encode(), "application/json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_address[1], flush=True)
srv.serve_forever()
