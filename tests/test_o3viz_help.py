"""o3viz help page: exists, keys agree with the viewer's bindings, images ship with web/."""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser

from wyrd.o3viz import serve

WEB = serve.WEB


class _Scan(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.keys: set[str] = set()
        self.imgs: list[str] = []
        self.ids: set[str] = set()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "tr" and "data-key" in a:
            self.keys.add(a["data-key"])
        if tag == "img":
            self.imgs.append(a.get("src", ""))
        if tag == "a" and "href" in a:
            self.hrefs.append(a["href"])


def _scan() -> _Scan:
    s = _Scan()
    s.feed((WEB / "help.html").read_text())
    return s


def _keys_in(path: str) -> set[str]:
    text = (WEB / path).read_text()
    m = re.search(r"export const KEYS = \{([^}]*)\}", text)
    assert m, path
    return {k.strip().strip("\"'") for k in re.findall(r"([^,:]+):", m.group(1))}


def _bound_keys() -> set[str]:
    app = (WEB / "app.js").read_text()
    out = _keys_in("layout.js") | _keys_in("graphview.js")
    # app.js binds 0, 1-9 and ? by literal tests inside the keydown handler
    handler = app[app.index('document.addEventListener("keydown"') :]
    handler = handler[: handler.index("});")]
    for lit, key in (('e.key === "0"', "0"), ("[1-9]", "1-9"), ('e.key === "?"', "?")):
        if lit in handler:
            out.add(key)
    return out


class TestHelp(unittest.TestCase):
    def test_exists_with_toc_and_sections(self) -> None:
        s = _scan()
        self.assertIn("toc", s.ids)
        for h in s.hrefs:
            if h.startswith("#"):
                self.assertIn(h[1:], s.ids, h)
        self.assertGreaterEqual(len([h for h in s.hrefs if h.startswith("#")]), 13)

    def test_keys_match_app(self) -> None:
        self.assertEqual(_scan().keys, _bound_keys())

    def test_images_exist(self) -> None:
        s = _scan()
        self.assertTrue(s.imgs)
        for src in s.imgs:
            self.assertFalse(src.startswith(("/", "http", "..")), src)
            self.assertTrue((WEB / src).is_file(), src)

    def test_viewer_links_help(self) -> None:
        self.assertIn('href="help.html"', (WEB / "index.html").read_text())

    def test_self_contained(self) -> None:
        text = (WEB / "help.html").read_text()
        self.assertNotIn("https://", text)
        self.assertNotIn("<script", text)


if __name__ == "__main__":
    unittest.main()
