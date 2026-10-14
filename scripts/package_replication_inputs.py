#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the versioned auxiliary-input asset for the replication repository."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import tarfile
from pathlib import Path

from build_database import PACKAGE_DIR, VERSION


ASSET_NAME = f"accidents_radars_replication_inputs-v{VERSION}.tar.gz"


def sha256(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def inputs(analysis_root: Path):
    files = {
        analysis_root / "DATA/result.radar.commune.rda":
            Path("auxiliary/result.radar.commune.rda"),
    }
    for suffix in ("shp", "shx", "dbf", "prj", "cpg"):
        source = analysis_root / f"DATA/DEPARTEMENT/DEPARTEMENT.{suffix}"
        files[source] = Path(f"auxiliary/DEPARTEMENT/DEPARTEMENT.{suffix}")
    cache = analysis_root / "replication-master/output/ign_road_geometry_cache"
    for source in sorted(cache.glob("*.rds")):
        files[source] = Path("roads/ign_road_geometry_cache") / source.name
    output = analysis_root / "replication-master/output"
    for name in (
        "radar_ign_road_matches.csv",
        "radar_ign_road_match_diagnostics.csv",
    ):
        files[output / name] = Path("roads") / name
    traffic = analysis_root / "replication-master/data/traffic"
    files[traffic / "README.md"] = Path("traffic/README.md")
    for source in sorted(traffic.glob("tmja_*.csv")):
        files[source] = Path("traffic") / source.name
    for source in sorted((traffic / "shapefiles").glob("tmja_*_shp.zip")):
        files[source] = Path("traffic/shapefiles") / source.name
    for name in (
        "road_corridor_monthly_counts_network.csv.gz",
        "road_corridor_monthly_counts_network_100m.csv.gz",
        "road_corridor_monthly_counts_100m.csv.gz",
        "road_corridor_monthly_counts_network_100m_with_large_cities.csv.gz",
        "circle_monthly_counts.csv.gz",
        "offroad_circle_monthly_counts_100m.csv.gz",
        "road_corridor_geometry_diagnostics_network.csv",
        "road_corridor_geometry_diagnostics_network_100m.csv",
        "road_corridor_geometry_diagnostics_100m.csv",
        "road_corridor_geometry_diagnostics_network_100m_with_large_cities.csv",
    ):
        files[output / name] = Path("derived") / name
    return files


def add_file(archive: tarfile.TarFile, source: Path, destination: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"Missing replication input: {source}")
    info = archive.gettarinfo(str(source), arcname=str(destination))
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    info.mode = 0o644
    with source.open("rb") as stream:
        archive.addfile(info, stream)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--analysis-root", type=Path, default=PACKAGE_DIR.parent,
        help="Root containing DATA/ and replication-master/",
    )
    args = parser.parse_args()
    release = PACKAGE_DIR / "release"
    release.mkdir(parents=True, exist_ok=True)
    asset = release / ASSET_NAME
    with asset.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for source, destination in sorted(
                    inputs(args.analysis_root.resolve()).items(),
                    key=lambda item: str(item[1]),
                ):
                    add_file(archive, source, destination)
    checksum = sha256(asset)
    (release / "REPLICATION_INPUTS_SHA256.txt").write_text(
        f"{checksum}  {asset.name}\n", encoding="utf-8"
    )
    print(f"Archive créée : {asset}")
    print(f"SHA-256 : {checksum}")


if __name__ == "__main__":
    main()
