#!/usr/bin/env python3
"""Deprecated entry point wrapper for HuntStand exporter.

The full implementation lives in :mod:`huntstand_exporter.exporter` and is exposed via the
installed console script ``huntstand-exporter``.

Preferred usage:
    huntstand-exporter --help

This file remains only for backward compatibility and will be removed in a future release.
"""
from __future__ import annotations

import sys
from collections.abc import Sequence

from huntstand_exporter.exporter import main as _main


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin wrapper
    return _main(list(argv) if argv is not None else None)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
