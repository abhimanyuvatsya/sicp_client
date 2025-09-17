"""Miscellaneous helpers."""

from __future__ import annotations

import re

_slug_regex = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    normalized = value.strip().lower()
    normalized = _slug_regex.sub("-", normalized)
    normalized = normalized.strip("-")
    return normalized or "tablet"
