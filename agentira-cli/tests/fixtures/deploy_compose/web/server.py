"""Answers 200 with the api's body — proves both services are up and talking."""
import http.server
import urllib.request


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body = urllib.request.urlopen("http://api:9000/", timeout=3).read()
            code = 200
        except Exception as exc:  # noqa: BLE001
            body, code = str(exc).encode(), 502
        self.send_response(code)
        self.end_headers()
        self.wfile.write(body)


http.server.ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
