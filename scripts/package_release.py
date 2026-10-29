#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Optionally compress the local SQLite database and write its checksum."""

from __future__ import annotations

import gzip
import hashlib
import shutil
from pathlib import Path

from build_database import DB_PATH, PACKAGE_DIR, VERSION


RELEASE_DIR = PACKAGE_DIR / "release"
ARCHIVE_PATH = RELEASE_DIR / f"accidents_radars_france_2005_2025-v{VERSION}.sqlite.gz"
CHECKSUM_PATH = RELEASE_DIR / "SHA256SUMS.txt"


def sha256(path, block_size=1024 * 1024):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def main():
    if not DB_PATH.is_file():
        raise SystemExit(f"Base SQLite absente : {DB_PATH}")
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    with DB_PATH.open("rb") as source, ARCHIVE_PATH.open("wb") as raw_output:
        with gzip.GzipFile(
            filename="", fileobj=raw_output, mode="wb", compresslevel=6, mtime=0
        ) as compressed:
            shutil.copyfileobj(source, compressed, length=1024 * 1024)
    CHECKSUM_PATH.write_text(
        f"{sha256(ARCHIVE_PATH)}  {ARCHIVE_PATH.name}\n", encoding="utf-8"
    )
    print(f"Archive créée : {ARCHIVE_PATH}")
    print(f"Empreinte créée : {CHECKSUM_PATH}")


if __name__ == "__main__":
    main()
