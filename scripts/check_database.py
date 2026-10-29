#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate the published files and, when present, the complete SQLite base."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import sqlite3
import sys
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = PACKAGE_DIR / "data" / "processed" / "accidents_radars_france_2005_2025.sqlite"
MANIFEST_PATH = PACKAGE_DIR / "metadata" / "sha256.txt"
QUALITY_PATH = PACKAGE_DIR / "metadata" / "rapport_qualite.csv"
SOURCE_MANIFEST_PATH = PACKAGE_DIR / "metadata" / "fichiers_sources_sha256.csv"
SCHEMA_PATH = PACKAGE_DIR / "metadata" / "schema.csv"
EXPECTED_VERSION = "1.1.0"
COUNTED_TABLES = (
    "accidents", "lieux", "vehicules", "usagers", "radars",
    "radars_inventaires_officiels",
)

GZIP_EXPORTS = {
    "data/processed/accidents.csv.gz": "id_accident",
    "data/processed/lieux.csv.gz": "cle_lieu",
    "data/processed/vehicules.csv.gz": "cle_vehicule",
    "data/processed/usagers.csv.gz": "cle_usager",
    "data/processed/radars.csv.gz": "cle_radar",
    "data/processed/radars_inventaires.csv.gz": "millesime",
    "data/processed/qualite_par_annee.csv.gz": "annee",
    "data/sample/accidents_echantillon.csv.gz": "id_accident",
}


def sha256(path, block_size=1024 * 1024):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def check_manifest(errors):
    for line_number, line in enumerate(MANIFEST_PATH.read_text(encoding="utf-8").splitlines(), 1):
        try:
            expected, relative_path = line.split("  ", 1)
        except ValueError:
            errors.append(f"Ligne invalide dans le manifeste : {line_number}")
            continue
        path = PACKAGE_DIR / relative_path
        if not path.is_file():
            errors.append(f"Fichier absent du paquet : {relative_path}")
        elif sha256(path) != expected:
            errors.append(f"Empreinte incorrecte : {relative_path}")


def check_gzip_exports(errors):
    for relative_path, first_column in GZIP_EXPORTS.items():
        path = PACKAGE_DIR / relative_path
        if not path.is_file():
            errors.append(f"Export absent : {relative_path}")
            continue
        try:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
                reader = csv.reader(stream)
                header = next(reader)
                first_row = next(reader)
            if not header or header[0] != first_column:
                errors.append(f"En-tête inattendu : {relative_path}")
            if len(first_row) != len(header):
                errors.append(f"Première ligne mal formée : {relative_path}")
        except (OSError, EOFError, StopIteration, UnicodeError, csv.Error) as exc:
            errors.append(f"Export illisible {relative_path} : {exc}")


def check_available_sources(errors):
    with SOURCE_MANIFEST_PATH.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        path = PACKAGE_DIR / row["fichier"]
        if path.is_file() and sha256(path) != row["sha256"]:
            errors.append(f"Empreinte de source incorrecte : {row['fichier']}")
    for relative_path in (
        "data/raw/radars/radars_2018.csv",
        "data/raw/radars/radars_fixes_2024-10.csv",
        "data/raw/radars/radars_fixes_2025-12.csv",
    ):
        if not (PACKAGE_DIR / relative_path).is_file():
            errors.append(f"Source radar absente du dépôt : {relative_path}")


def expected_counts():
    with QUALITY_PATH.open("r", encoding="utf-8", newline="") as stream:
        return {
            row["controle"].removeprefix("lignes_"): int(row["valeur"])
            for row in csv.DictReader(stream)
            if row["controle"] in {f"lignes_{table}" for table in COUNTED_TABLES}
        }


def check_sqlite(errors, require_sqlite):
    if not DB_PATH.is_file():
        if require_sqlite:
            errors.append("Base SQLite absente ; exécutez scripts/build_database.py pour la construire.")
        return
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            errors.append("Le contrôle d'intégrité SQLite a échoué.")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            errors.append("Une contrainte de clé étrangère est violée.")
        construction = dict(conn.execute("SELECT cle, valeur FROM construction"))
        if construction.get("version") != EXPECTED_VERSION:
            errors.append(
                f"Version SQLite {construction.get('version')!r}, attendue {EXPECTED_VERSION!r}."
            )
        for table, expected in expected_counts().items():
            actual = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if actual != expected:
                errors.append(f"{table} : {actual} lignes, {expected} attendues.")
        actual_schema = {
            (name, object_type, column, sql_type, not_null, primary_key)
            for name, object_type in conn.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"
            )
            for _, column, sql_type, not_null, _, primary_key in conn.execute(
                f'PRAGMA table_info("{name}")'
            )
        }
        with SCHEMA_PATH.open("r", encoding="utf-8", newline="") as stream:
            documented_schema = {
                (
                    row["objet"],
                    row["type_objet"],
                    row["colonne"],
                    row["type_sql"],
                    int(row["non_nul"]),
                    int(row["cle_primaire"]),
                )
                for row in csv.DictReader(stream)
            }
        if actual_schema != documented_schema:
            errors.append("Le schéma SQLite diffère de metadata/schema.csv.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-sqlite",
        action="store_true",
        help="échouer si la base SQLite construite localement est absente",
    )
    args = parser.parse_args()
    errors = []
    check_manifest(errors)
    check_gzip_exports(errors)
    check_available_sources(errors)
    check_sqlite(errors, args.require_sqlite)
    if errors:
        print("ÉCHEC DES CONTRÔLES", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(1)
    sqlite_status = "avec SQLite" if DB_PATH.is_file() else "sans SQLite (version dépôt)"
    print(f"Paquet valide — version {EXPECTED_VERSION}, {sqlite_status}.")


if __name__ == "__main__":
    main()
