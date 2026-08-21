#!/usr/bin/env python3
"""Serve the staging frontend, and proxy /api/* to the staging backend.

Two jobs in one process, both for the same reason: staging.upsetalert.ca is the
only hostname with a DNS record, and adding another needs a zone-scoped
Cloudflare token we do not have. So this host has to serve the app AND give it
something to call.

  /api/*  -> the backend, prefix stripped (the backend has no /api)
  /       -> index.html                    (SPA fallback)

The SPA fallback matters as much as the proxy: a plain static server 404s on
/draws/118 because no such file exists — those routes are resolved client-side.
Anything without a file extension returns index.html and lets the app route it,
or every link except the home page breaks.

RUNS AS A COMPOSE SERVICE, beside the backend it proxies to — see
docker-compose.staging.yml. It began as a shell job, which worked and was
invisible: nothing described it, nothing restarted it, and it was parented to
the terminal session that happened to start it. The backend would have survived
a reboot and this would not, leaving a live API behind a dead front door, which
looks exactly like a deploy that broke the site.

Every path it depends on is an environment variable so that it runs the same
way in a container as on the host, and the defaults are the host's.
"""
import http.server
import os
import socketserver
import urllib.error
import urllib.request

ROOT = os.environ.get("STAGING_WEB_ROOT", "/home/paulwiens/upsetalert/staging-web")
PORT = int(os.environ.get("STAGING_WEB_PORT", "8003"))
# In compose this is the backend service by name. On the host it is the port
# that service publishes. Same server either way.
BACKEND = os.environ.get("STAGING_BACKEND_URL", "http://127.0.0.1:8002")
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade",
              "proxy-authenticate", "proxy-authorization", "te", "trailer"}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    # ---- proxy ------------------------------------------------------------
    def _proxy(self):
        target = BACKEND + self.path[len("/api"):]
        body = None
        if (length := self.headers.get("Content-Length")):
            body = self.rfile.read(int(length))
        req = urllib.request.Request(target, data=body, method=self.command)
        for k, v in self.headers.items():
            if k.lower() not in HOP_BY_HOP and k.lower() != "host":
                req.add_header(k, v)
        # An SSE stream never ends, so it must not be read to completion and
        # must not have a timeout. r.read() on /stream would block for ever and
        # take this worker thread with it.
        is_stream = "/stream/" in self.path
        timeout = None if is_stream else 30
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                self.send_response(r.status)
                for k, v in r.headers.items():
                    if k.lower() not in HOP_BY_HOP:
                        self.send_header(k, v)
                self.end_headers()
                if is_stream:
                    # Relay line by line and flush each one. Buffering a stream
                    # is the same as not having one — the browser would receive
                    # nothing until the connection dropped.
                    for line in r:
                        self.wfile.write(line)
                        self.wfile.flush()
                    return
                self.wfile.write(r.read())
        except urllib.error.HTTPError as e:
            # Forward the backend's own error rather than turning a 401 into a
            # 500 — the app distinguishes them.
            payload = e.read()
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in HOP_BY_HOP:
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)
        except Exception:
            self.send_error(502, "staging backend unreachable")

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._proxy()
        path = self.translate_path(self.path)
        if not os.path.exists(path) or os.path.isdir(path):
            if "." not in os.path.basename(self.path.split("?")[0]):
                self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        return self._proxy() if self.path.startswith("/api/") else self.send_error(405)

    def do_PUT(self):
        return self._proxy() if self.path.startswith("/api/") else self.send_error(405)

    def do_DELETE(self):
        return self._proxy() if self.path.startswith("/api/") else self.send_error(405)

    def do_PATCH(self):
        return self._proxy() if self.path.startswith("/api/") else self.send_error(405)

    def log_message(self, *a):
        pass


class Threaded(socketserver.ThreadingMixIn, socketserver.TCPServer):
    # Threaded because the SPA opens an SSE stream and holds it open; a
    # single-threaded server would block every other request behind it.
    daemon_threads = True
    allow_reuse_address = True


with Threaded(("0.0.0.0", PORT), Handler) as httpd:
    httpd.serve_forever()
