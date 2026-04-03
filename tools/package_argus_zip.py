#!/usr/bin/env python3
"""
Build argus.zip at the repository root for distribution.
Excludes dependencies, secrets, caches, and the previous zip.
Run from anywhere: python tools/package_argus_zip.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP_NAME = "argus.zip"
ZIP_PATH = ROOT / ZIP_NAME

# Directory name anywhere in the relative path → skip file
EXCLUDE_DIR_NAMES = {
    "node_modules",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".next",
    "pgdata",
    ".venv",
    "venv",
    "dist",
    "htmlcov",
    ".turbo",
    ".cursor",
    "coverage",
    ".mypy_cache",
    ".ruff_cache",
    "eggs",
}

EXCLUDE_FILE_NAMES = {
    ZIP_NAME,
    ".coverage",
    ".DS_Store",
    "Thumbs.db",
}

# Template files we keep in the zip
_ENV_EXAMPLE_OK = frozenset({".env.example", ".env.sample"})

EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".egg-info")


def path_should_exclude(rel: Path) -> bool:
    for part in rel.parts:
        if part in EXCLUDE_DIR_NAMES:
            return True
    if rel.name in EXCLUDE_FILE_NAMES:
        return True
    # Any other .env* (e.g. .env.local, .env.production) — never pack secrets
    n = rel.name
    if n.startswith(".env") and n not in _ENV_EXAMPLE_OK:
        return True
    if rel.suffix == ".egg-info" or str(rel).endswith(".egg-info"):
        return True
    name = rel.name
    if name.endswith(EXCLUDE_SUFFIXES):
        return True
    return False


def main() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    count = 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(ROOT)
            except ValueError:
                continue
            if path_should_exclude(rel):
                continue
            zf.write(path, rel.as_posix())
            count += 1
    size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    print(f"Wrote {ZIP_PATH} — {count} files, {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
