#!/usr/bin/env python3
"""Run this on your Mac when the Jarvis API runs in Docker or on another machine.

The HUD (browser) will POST file paths here so Finder / default apps open locally.

  cd /path/to/JARVIS
  python3 scripts/jarvis_file_bridge.py

Optional env:
  JARVIS_FILE_BRIDGE_PORT=17834   (default)
  JARVIS_FILE_BRIDGE_BIND=127.0.0.1
  JARVIS_ALLOWED_ROOTS=/Users/you,...  (optional; when unset on macOS, any path under / is allowed)

Frontend: set NEXT_PUBLIC_FILE_BRIDGE_URL=http://127.0.0.1:17834
Backend: JARVIS_FILE_ACTIONS_MODE=auto (default) uses delegation in Docker / non-macOS API.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

PORT = int(os.environ.get("JARVIS_FILE_BRIDGE_PORT", "17834"))


def _mac_unrestricted_bridge_paths() -> bool:
    """Match backend desktop defaults: unset roots => allow whole local disk on macOS."""
    return sys.platform == "darwin" and not os.environ.get(
        "JARVIS_ALLOWED_ROOTS", ""
    ).strip()


def _roots() -> list[Path]:
    raw = os.environ.get("JARVIS_ALLOWED_ROOTS", "").strip()
    if not raw:
        if sys.platform == "darwin":
            return [Path("/")]
        return [Path.home().resolve()]
    out: list[Path] = []
    for p in raw.split(","):
        p = p.strip()
        if p:
            out.append(Path(p).expanduser().resolve())
    return out or [Path.home().resolve()]


def _bridge_blocked_mac(s: str) -> bool:
    if s in ("/dev", "/proc", "/sys"):
        return True
    return s.startswith(("/dev/", "/proc/", "/sys/"))


def path_ok(p: Path) -> bool:
    try:
        r = p.expanduser().resolve()
    except OSError:
        return False
    if not r.exists():
        return False
    if _mac_unrestricted_bridge_paths():
        s = str(r)
        if not s.startswith("/"):
            return False
        if _bridge_blocked_mac(s):
            return False
        return True
    for root in _roots():
        try:
            r.relative_to(root)
            return True
        except ValueError:
            continue
    return False


class Handler(BaseHTTPRequestHandler):
    server_version = "JarvisFileBridge/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in ("/open", "/reveal"):
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"error":"invalid json"}')
            return
        path_s = str(body.get("path", "")).strip()
        if not path_s:
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"error":"missing path"}')
            return
        p = Path(path_s).expanduser()
        if not path_ok(p):
            self.send_response(403)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"error":"path not allowed"}')
            return
        ps = str(p.resolve())
        opener = "/usr/bin/open" if Path("/usr/bin/open").is_file() else "open"
        try:
            if parsed.path == "/reveal":
                subprocess.run([opener, "-R", ps], check=False, timeout=60)
            else:
                subprocess.run([opener, ps], check=False, timeout=60)
        except OSError as e:
            self.send_response(500)
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


def main() -> None:
    if sys.platform != "darwin":
        print("jarvis_file_bridge: macOS only (Finder / open).", file=sys.stderr)
        sys.exit(1)
    bind = os.environ.get("JARVIS_FILE_BRIDGE_BIND", "127.0.0.1")
    server = HTTPServer((bind, PORT), Handler)
    print(
        f"Jarvis file bridge — http://{bind}:{PORT}  POST /reveal | /open  JSON {{\"path\":\"...\"}}",
        file=sys.stderr,
    )
    print(f"Allowed under: {_roots()}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
