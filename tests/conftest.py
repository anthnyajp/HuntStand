"""Pytest configuration to ensure local workspace 'src' path is prioritized.

This avoids importing an already-installed huntstand_exporter distribution outside the workspace
that may be missing newer functions added during development.
"""
from __future__ import annotations

import sys
import importlib
import importlib.machinery
from pathlib import Path

# Determine workspace root by locating this file's parent (tests/) and then adding 'src'
TESTS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = TESTS_DIR.parent  # .../HuntStand
# Ensure we reference the nested src under this workspace root (not a sibling "src" one level up)
SRC_DIR = WORKSPACE_ROOT / "src"

if SRC_DIR.exists():
    # Prepend so it takes precedence over any site-packages installed version
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))

    # If a different huntstand_exporter was already imported (e.g., from another src outside workspace), purge it
    for mod_name in list(sys.modules):
        if mod_name.startswith("huntstand_exporter"):
            del sys.modules[mod_name]

    exporter_path = SRC_DIR / "huntstand_exporter" / "exporter.py"
    if exporter_path.exists():
        loader = importlib.machinery.SourceFileLoader("huntstand_exporter.exporter", str(exporter_path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)  # type: ignore[arg-type]
        # Register module explicitly so that 'from huntstand_exporter import main' sees updated code
        pkg_path = SRC_DIR / "huntstand_exporter"
        if (pkg_path / "__init__.py").exists():
            # Load package __init__ normally
            pkg_loader = importlib.machinery.SourceFileLoader("huntstand_exporter", str(pkg_path / "__init__.py"))
            pkg_spec = importlib.util.spec_from_loader(pkg_loader.name, pkg_loader)
            pkg_module = importlib.util.module_from_spec(pkg_spec)
            pkg_loader.exec_module(pkg_module)  # type: ignore[arg-type]
            # Ensure package __path__ points only to workspace version
            pkg_module.__path__ = [str(pkg_path)]  # type: ignore[attr-defined]
            # Inject exporter submodule
            sys.modules["huntstand_exporter"] = pkg_module
        sys.modules["huntstand_exporter.exporter"] = module
        # Optionally expose frequently used functions at package level for tests
        for attr in ("main", "as_dict", "json_or_list_to_objects", "is_safe_id", "fetch_members_for_area"):
            if hasattr(module, attr):
                setattr(sys.modules["huntstand_exporter"], attr, getattr(module, attr))
