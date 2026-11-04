"""Serve the o3viz viewer and one bundle on 127.0.0.1 (no network at view time)."""

from __future__ import annotations

import functools
import http.server
import posixpath
from pathlib import Path
from typing import Any

WEB = Path(__file__).resolve().parent / "web"


class Handler(http.server.SimpleHTTPRequestHandler):
    """`/` is the viewer; `/bundle/...` is the bundle directory."""

    def __init__(self, *args: Any, bundle: Path, **kwargs: Any) -> None:
        self.bundle = bundle
        super().__init__(*args, directory=str(WEB), **kwargs)

    def translate_path(self, path: str) -> str:
        clean = posixpath.normpath(path.split("?", 1)[0].split("#", 1)[0])
        if clean.startswith("/bundle/"):
            rel = clean[len("/bundle/") :]
            full = (self.bundle / rel).resolve()
            return str(full) if full.is_relative_to(self.bundle.resolve()) else str(WEB / "404")
        return super().translate_path(path)

    def log_message(self, format: str, *args: Any) -> None:
        return


def make_server(
    bundle: Path, port: int = 8765, host: str = "127.0.0.1"
) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(Handler, bundle=bundle)
    return http.server.ThreadingHTTPServer((host, port), handler)
