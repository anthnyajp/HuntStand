#!/usr/bin/env python3
"""CLI entry point for huntstand-exporter."""

import sys

from huntstand_exporter.exporter import main

if __name__ == "__main__":
    sys.exit(main())
