#!/usr/bin/env python3
"""Compatibility wrapper around the new SICP CLI."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from sicp.cli import main  # noqa: E402


if __name__ == "__main__":
    main()
