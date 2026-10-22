"""Citations and credits shown by the GUI and rendered to docs/CITATIONS.md (spec section 12)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

_KINDS = ("paper", "software", "project", "font")


@dataclass(frozen=True)
class Citation:
    id: str
    name: str
    kind: str
    role: str = ""
    authors: str = ""
    year: int | None = None
    title: str = ""
    venue: str = ""
    url: str = ""
    license: str = ""


def _text(item: dict[str, object], key: str) -> str:
    val = item.get(key, "")
    return val if isinstance(val, str) else ""


def _year(item: dict[str, object], ident: str) -> int | None:
    val = item.get("year")
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        raise ValueError(f"citation {ident!r}: year must be an integer")
    return val


def _one(item: dict[str, object], n: int) -> Citation:
    ident = _text(item, "id")
    where = repr(ident) if ident else f"#{n + 1}"
    for key in ("id", "name", "kind"):
        if not _text(item, key):
            raise ValueError(f"citation {where}: missing {key!r}")
    kind = _text(item, "kind")
    if kind not in _KINDS:
        raise ValueError(f"citation {where}: kind {kind!r} not in {'|'.join(_KINDS)}")
    return Citation(
        id=ident,
        name=_text(item, "name"),
        kind=kind,
        role=_text(item, "role"),
        authors=_text(item, "authors"),
        year=_year(item, ident),
        title=_text(item, "title"),
        venue=_text(item, "venue"),
        url=_text(item, "url"),
        license=_text(item, "license"),
    )


def load(path: Path | None = None) -> list[Citation]:
    """Read the packaged citations (or ``path``); raise ValueError naming a bad id."""
    if path is None:
        raw = (resources.files("wyrd") / "data" / "citations.toml").read_text(encoding="utf-8")
    else:
        raw = path.read_text(encoding="utf-8")
    items = tomllib.loads(raw).get("item", [])
    out: list[Citation] = []
    seen: set[str] = set()
    for n, item in enumerate(items):
        cite = _one(item, n)
        if cite.id in seen:
            raise ValueError(f"citation {cite.id!r}: duplicate id")
        seen.add(cite.id)
        out.append(cite)
    return out


def _reference(c: Citation) -> str:
    head = c.authors
    if c.year is not None:
        head = f"{head} ({c.year})" if head else f"({c.year})"
    parts = [p for p in (head, c.title, c.venue) if p]
    return ". ".join(parts) + ("." if parts else "")


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_markdown(items: list[Citation]) -> str:
    """A Markdown table of the citations."""
    lines = [
        "# Citations",
        "",
        "| Name | Kind | Role | Reference | Link |",
        "|---|---|---|---|---|",
    ]
    for c in items:
        cells = [c.name, c.kind, c.role, _reference(c), c.url]
        lines.append("| " + " | ".join(_cell(x) for x in cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    print(render_markdown(load()), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
