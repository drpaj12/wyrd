"""Byte-size parsing."""

from __future__ import annotations

import re

_UNITS = {"": 1, "K": 2**10, "M": 2**20, "G": 2**30, "T": 2**40}
_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMGT]?)B?\s*$", re.IGNORECASE)


def parse_bytes(text: str, total: int | None = None) -> int:
    """Parse "4G", "512M" or "60%" (of `total`) into bytes. Binary units."""
    s = text.strip()
    if s.endswith("%"):
        if total is None:
            raise ValueError(f"percentage {text!r} needs a total")
        try:
            pct = float(s[:-1])
        except ValueError:
            raise ValueError(f"bad size {text!r}") from None
        return int(total * pct / 100)
    m = _PATTERN.match(s)
    if m is None:
        raise ValueError(f"bad size {text!r}")
    return int(float(m.group(1)) * _UNITS[m.group(2).upper()])
