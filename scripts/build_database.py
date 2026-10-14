#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a redistributable BAAC and speed-camera database.

The script uses only the Python standard library. It preserves the four-table
BAAC structure, creates a documented SQLite database, exports compressed CSV
tables and produces a deterministic lightweight sample.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import math
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parents[1]
RAW_BAAC_DIR = PACKAGE_DIR / "data" / "raw" / "baac"
LEGACY_RADAR_FILE = PACKAGE_DIR / "data" / "raw" / "radars" / "radars_2018.csv"
RADAR_2024_FILE = PACKAGE_DIR / "data" / "raw" / "radars" / "radars_fixes_2024-10.csv"
CURRENT_RADAR_FILE = PACKAGE_DIR / "data" / "raw" / "radars" / "radars_fixes_2025-12.csv"
OUTPUT_DIR = PACKAGE_DIR / "data" / "processed"
SAMPLE_DIR = PACKAGE_DIR / "data" / "sample"
METADATA_DIR = PACKAGE_DIR / "metadata"
DB_PATH = OUTPUT_DIR / "accidents_radars_france_2005_2025.sqlite"
YEARS = range(2005, 2025)
VERSION = "1.1.0"
SAMPLE_PER_YEAR = 2000

MISSING_TEXT = {"", "NA", "N/A", "NULL", "NONE", "."}
WS_RE = re.compile(r"[\s\u00a0\u202f]+")


def clean_text(value):
    if value is None:
        return None
    text = WS_RE.sub(" ", str(value)).strip()
    if text.upper() in MISSING_TEXT:
        return None
    return text


def compact_identifier(value):
    value = clean_text(value)
    return WS_RE.sub("", value) if value is not None else None


def official_radar_identifier(value):
    """Normalize IDs shared by the official 2024 and 2025 inventories."""
    value = compact_identifier(value)
    if value is None:
        return None
    value = value.upper()
    return str(int(value)) if value.isdigit() else value


def as_int(value):
    value = clean_text(value)
    if value is None:
        return None
    try:
        return int(float(value.replace(",", ".")))
    except ValueError:
        return None


def as_float(value):
    value = clean_text(value)
    if value is None:
        return None
    try:
        return float(value.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def coordinate(value, latitude=False):
    number = as_float(value)
    if number is None:
        return None
    limit = 90 if latitude else 180
    if abs(number) > limit:
        number /= 100000.0
    if number == 0 or abs(number) > limit:
        return None
    return round(number, 8)


def normalized_header(value):
    value = value.lstrip("\ufeff")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    aliases = {"accident_id": "num_acc", "numero_de_radar": "numero_radar"}
    return aliases.get(value, value)


def open_dict_reader(path):
    raw = path.read_bytes()[:65536]
    encoding = "utf-8-sig"
    try:
        raw.decode(encoding)
    except UnicodeDecodeError:
        # The older BAAC exports mix legacy encodings and may contain bytes
        # undefined in Windows-1252. ISO-8859-1 is lossless for all bytes.
        encoding = "iso-8859-1"
    sample = raw.decode(encoding, errors="replace")
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    stream = path.open("r", encoding=encoding, newline="")
    reader = csv.DictReader(stream, delimiter=delimiter)
    reader.fieldnames = [normalized_header(x) for x in reader.fieldnames]
    return stream, reader, encoding, delimiter


def baac_path(kind, year):
    return RAW_BAAC_DIR / f"{kind}_{year}.csv"


def required_source_files():
    files = [
        baac_path(kind, year)
        for year in YEARS
        for kind in ("caracteristiques", "lieux", "vehicules", "usagers")
    ]
    return files + [LEGACY_RADAR_FILE, RADAR_2024_FILE, CURRENT_RADAR_FILE]


def validate_sources():
    """Fail before overwriting outputs when a source is missing or altered."""
    missing = [path for path in required_source_files() if not path.is_file()]
    if missing:
        details = "\n".join(f"  - {path.relative_to(PACKAGE_DIR)}" for path in missing)
        raise SystemExit(
            "Sources manquantes. Placez les fichiers bruts aux emplacements "
            f"documentés avant de reconstruire la base :\n{details}"
        )

    manifest_path = METADATA_DIR / "fichiers_sources_sha256.csv"
    if not manifest_path.is_file():
        raise SystemExit(f"Manifeste des sources absent : {manifest_path}")
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as stream:
        expected = {
            PACKAGE_DIR / row["fichier"]: row["sha256"]
            for row in csv.DictReader(stream)
        }
    mismatches = []
    for path in required_source_files():
        if expected.get(path) != file_sha256(path):
            mismatches.append(path.relative_to(PACKAGE_DIR))
    if mismatches:
        details = "\n".join(f"  - {path}" for path in mismatches)
        raise SystemExit(
            "L'empreinte de certaines sources diffère du manifeste :\n"
            f"{details}\nMettez à jour les sources et leur manifeste de façon explicite."
        )


def normalize_year(value, fallback):
    year = as_int(value)
    if year is None:
        return fallback
    if year < 100:
        year += 2000
    return year


def normalize_time(value):
    value = clean_text(value)
    if value is None:
        return None, None, None
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None, None, None
    digits = digits.zfill(4)[-4:]
    hour, minute = as_int(digits[:2]), as_int(digits[2:])
    if hour is None or minute is None or hour > 23 or minute > 59:
        return None, None, None
    return f"{hour:02d}:{minute:02d}", hour, minute


def normalize_department(value):
    value = compact_identifier(value)
    if value is None:
        return None
    value = value.upper()
    if value == "201":
        return "2A"
    if value == "202":
        return "2B"
    if len(value) == 3 and value.endswith("0") and value[:2].isdigit():
        return value[:2]
    if value.isdigit() and len(value) <= 2:
        return value.zfill(2)
    return value


def normalize_commune(value, department, year):
    value = compact_identifier(value)
    if value is None:
        return None
    value = value.upper()
    if year >= 2019 and len(value) >= 5:
        return value
    if department is None:
        return value
    if department in {"2A", "2B"}:
        return department + value.zfill(3)[-3:]
    if len(department) == 3:
        return department + value.zfill(2)[-2:]
    return department + value.zfill(3)[-3:]


def iso_date(year, month, day):
    try:
        return date(year, month, day).isoformat()
    except (TypeError, ValueError):
        return None


def source_row(row):
    return {normalized_header(k): clean_text(v) for k, v in row.items() if k is not None}


SCHEMA = """
PRAGMA foreign_keys = OFF;
CREATE TABLE accidents (
  id_accident TEXT PRIMARY KEY,
  annee INTEGER, mois INTEGER, jour INTEGER, date_accident TEXT,
  heure_accident TEXT, heure INTEGER, minute INTEGER,
  luminosite INTEGER, agglomeration INTEGER, intersection INTEGER,
  conditions_atmospheriques INTEGER, type_collision INTEGER,
  code_departement TEXT, code_commune TEXT, adresse TEXT,
  latitude REAL, longitude REAL, geolocalisation_valide INTEGER NOT NULL,
  ancien_systeme_gps TEXT, source_annee INTEGER NOT NULL, source_fichier TEXT NOT NULL
);
CREATE TABLE lieux (
  cle_lieu TEXT PRIMARY KEY, id_accident TEXT NOT NULL, rang_lieu INTEGER NOT NULL,
  categorie_route INTEGER, numero_route TEXT, indice_numero_route TEXT,
  lettre_indice_route TEXT, regime_circulation INTEGER, nombre_voies INTEGER,
  numero_pr TEXT, distance_pr_metres TEXT, voie_reservee INTEGER,
  profil_longitudinal INTEGER, trace_plan INTEGER,
  largeur_terre_plein_central_m REAL, largeur_chaussee_m REAL,
  etat_surface INTEGER, amenagement_infrastructure INTEGER,
  situation_accident INTEGER, environnement_point TEXT,
  vitesse_maximale_autorisee_kmh INTEGER,
  source_annee INTEGER NOT NULL, source_fichier TEXT NOT NULL
);
CREATE TABLE vehicules (
  cle_vehicule TEXT PRIMARY KEY,
  id_accident TEXT NOT NULL, id_vehicule_source TEXT, numero_vehicule TEXT,
  sens_circulation INTEGER, categorie_vehicule INTEGER,
  obstacle_fixe INTEGER, obstacle_mobile INTEGER, point_choc_initial INTEGER,
  manoeuvre_principale INTEGER, type_motorisation INTEGER,
  nombre_occupants_transport_commun INTEGER,
  source_annee INTEGER NOT NULL, source_fichier TEXT NOT NULL
);
CREATE TABLE usagers (
  cle_usager TEXT PRIMARY KEY,
  id_accident TEXT NOT NULL, cle_vehicule TEXT, id_usager_source TEXT,
  id_vehicule_source TEXT, numero_vehicule TEXT, place TEXT,
  categorie_usager INTEGER, gravite INTEGER, sexe INTEGER,
  annee_naissance INTEGER, motif_deplacement INTEGER,
  securite_ancien_code TEXT, equipement_securite_1 INTEGER,
  equipement_securite_2 INTEGER, equipement_securite_3 INTEGER,
  localisation_pieton TEXT, action_pieton TEXT, etat_pieton INTEGER,
  source_annee INTEGER NOT NULL, source_fichier TEXT NOT NULL
);
CREATE TABLE radars_historique_2018 (
  id_radar_2018 TEXT PRIMARY KEY, date_installation TEXT, code_departement TEXT,
  latitude REAL, longitude REAL, direction TEXT, equipement TEXT,
  type_radar_libelle TEXT, emplacement TEXT, route TEXT,
  longueur_troncon_km REAL, vitesse_poids_lourds_kmh INTEGER,
  vitesse_vehicules_legers_kmh INTEGER
);
CREATE TABLE radars_inventaires_officiels (
  millesime TEXT NOT NULL, date_publication TEXT NOT NULL,
  id_radar_officiel TEXT NOT NULL, type_radar_code TEXT,
  date_mise_en_service TEXT, vma_kmh INTEGER,
  latitude REAL, longitude REAL, source_fichier TEXT NOT NULL,
  PRIMARY KEY (millesime, id_radar_officiel)
);
CREATE TABLE radars (
  cle_radar TEXT PRIMARY KEY, id_radar_2025 TEXT, id_radar_2018 TEXT,
  type_radar_code TEXT, type_radar_libelle_2018 TEXT,
  date_mise_en_service TEXT, date_installation_2018 TEXT,
  vma_kmh INTEGER, latitude REAL, longitude REAL,
  code_departement_2018 TEXT, direction_2018 TEXT, emplacement_2018 TEXT,
  route_2018 TEXT, observe_2018 INTEGER NOT NULL, actif_liste_2025 INTEGER NOT NULL,
  statut_rapprochement TEXT NOT NULL, distance_rapprochement_m REAL,
  source_principale TEXT NOT NULL
);
CREATE TABLE sources (
  source_id TEXT PRIMARY KEY, producteur TEXT NOT NULL, titre TEXT NOT NULL,
  couverture TEXT NOT NULL, licence TEXT NOT NULL, url TEXT NOT NULL,
  date_consultation TEXT NOT NULL, note TEXT
);
CREATE TABLE construction (
  cle TEXT PRIMARY KEY, valeur TEXT NOT NULL
);
"""


def insert_chunks(conn, sql, rows, size=10000):
    chunk = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= size:
            conn.executemany(sql, chunk)
            chunk.clear()
    if chunk:
        conn.executemany(sql, chunk)


def accident_rows(year, path):
    stream, reader, _, _ = open_dict_reader(path)
    try:
        for raw in reader:
            row = source_row(raw)
            accident_id = compact_identifier(row.get("num_acc"))
            y = normalize_year(row.get("an"), year)
            month, day = as_int(row.get("mois")), as_int(row.get("jour"))
            time_text, hour, minute = normalize_time(row.get("hrmn"))
            dep = normalize_department(row.get("dep"))
            commune = normalize_commune(row.get("com"), dep, y)
            lat = coordinate(row.get("lat"), latitude=True)
            lon = coordinate(row.get("long"), latitude=False)
            valid_geo = int(lat is not None and lon is not None)
            yield (
                accident_id, y, month, day, iso_date(y, month, day), time_text, hour, minute,
                as_int(row.get("lum")), as_int(row.get("agg")), as_int(row.get("int")),
                as_int(row.get("atm")), as_int(row.get("col")), dep, commune,
                clean_text(row.get("adr")), lat, lon, valid_geo, clean_text(row.get("gps")),
                year, path.name,
            )
    finally:
        stream.close()


def location_rows(year, path):
    stream, reader, _, _ = open_dict_reader(path)
    seen = defaultdict(int)
    try:
        for raw in reader:
            row = source_row(raw)
            accident_id = compact_identifier(row.get("num_acc"))
            seen[accident_id] += 1
            yield (
                f"{accident_id}:{seen[accident_id]}", accident_id, seen[accident_id],
                as_int(row.get("catr")),
                clean_text(row.get("voie")), clean_text(row.get("v1")), clean_text(row.get("v2")),
                as_int(row.get("circ")), as_int(row.get("nbv")), clean_text(row.get("pr")),
                clean_text(row.get("pr1")), as_int(row.get("vosp")), as_int(row.get("prof")),
                as_int(row.get("plan")), as_float(row.get("lartpc")), as_float(row.get("larrout")),
                as_int(row.get("surf")), as_int(row.get("infra")), as_int(row.get("situ")),
                clean_text(row.get("env1")), as_int(row.get("vma")), year, path.name,
            )
    finally:
        stream.close()


def vehicle_key(accident_id, source_id, number):
    return f"{accident_id}:{source_id or number or 'sans-numero'}"


def vehicle_rows(year, path):
    stream, reader, _, _ = open_dict_reader(path)
    seen = defaultdict(int)
    try:
        for raw in reader:
            row = source_row(raw)
            accident_id = compact_identifier(row.get("num_acc"))
            source_id = compact_identifier(row.get("id_vehicule"))
            number = compact_identifier(row.get("num_veh"))
            base_key = vehicle_key(accident_id, source_id, number)
            seen[base_key] += 1
            key = base_key if seen[base_key] == 1 else f"{base_key}:{seen[base_key]}"
            yield (
                key, accident_id, source_id, number, as_int(row.get("senc")), as_int(row.get("catv")),
                as_int(row.get("obs")), as_int(row.get("obsm")), as_int(row.get("choc")),
                as_int(row.get("manv")), as_int(row.get("motor")), as_int(row.get("occutc")),
                year, path.name,
            )
    finally:
        stream.close()


def user_rows(year, path):
    stream, reader, _, _ = open_dict_reader(path)
    seen = defaultdict(int)
    try:
        for raw in reader:
            row = source_row(raw)
            accident_id = compact_identifier(row.get("num_acc"))
            user_source_id = compact_identifier(row.get("id_usager"))
            vehicle_source_id = compact_identifier(row.get("id_vehicule"))
            number = compact_identifier(row.get("num_veh"))
            vkey = vehicle_key(accident_id, vehicle_source_id, number)
            base_key = f"{accident_id}:{user_source_id}" if user_source_id else f"{vkey}:usager"
            seen[base_key] += 1
            user_key = base_key if seen[base_key] == 1 else f"{base_key}:{seen[base_key]}"
            yield (
                user_key, accident_id, vkey, user_source_id, vehicle_source_id, number,
                clean_text(row.get("place")), as_int(row.get("catu")), as_int(row.get("grav")),
                as_int(row.get("sexe")), as_int(row.get("an_nais")), as_int(row.get("trajet")),
                clean_text(row.get("secu")), as_int(row.get("secu1")), as_int(row.get("secu2")),
                as_int(row.get("secu3")), clean_text(row.get("locp")), clean_text(row.get("actp")),
                as_int(row.get("etatp")), year, path.name,
            )
    finally:
        stream.close()


def load_baac(conn):
    accident_sql = "INSERT INTO accidents VALUES (" + ",".join("?" * 22) + ")"
    location_sql = "INSERT INTO lieux VALUES (" + ",".join("?" * 23) + ")"
    vehicle_sql = "INSERT INTO vehicules VALUES (" + ",".join("?" * 14) + ")"
    user_sql = "INSERT INTO usagers VALUES (" + ",".join("?" * 21) + ")"
    for year in YEARS:
        paths = {kind: baac_path(kind, year) for kind in ("caracteristiques", "lieux", "vehicules", "usagers")}
        missing = [str(path) for path in paths.values() if not path.exists()]
        if missing:
            raise FileNotFoundError("Fichiers BAAC manquants:\n" + "\n".join(missing))
        print(f"BAAC {year}", flush=True)
        with conn:
            insert_chunks(conn, accident_sql, accident_rows(year, paths["caracteristiques"]))
            insert_chunks(conn, location_sql, location_rows(year, paths["lieux"]))
            insert_chunks(conn, vehicle_sql, vehicle_rows(year, paths["vehicules"]))
            insert_chunks(conn, user_sql, user_rows(year, paths["usagers"]))


def parse_date(value, formats):
    value = clean_text(value)
    if value is None:
        return None
    value = value[:19]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def load_legacy_radars(conn):
    stream, reader, _, _ = open_dict_reader(LEGACY_RADAR_FILE)
    rows = []
    try:
        for raw in reader:
            row = source_row(raw)
            rows.append({
                "id": compact_identifier(row.get("id")),
                "date": parse_date(row.get("date_installation"), ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")),
                "dep": normalize_department(row.get("departement")),
                "lat": coordinate(row.get("latitude"), latitude=True),
                "lon": coordinate(row.get("longitude"), latitude=False),
                "direction": clean_text(row.get("direction")),
                "equipement": clean_text(row.get("equipement")),
                "type": clean_text(row.get("type")),
                "emplacement": clean_text(row.get("emplacement")),
                "route": clean_text(row.get("route")),
                "longueur": as_float(row.get("longueur_troncon_km")),
                "vma_pl": as_int(row.get("vitesse_poids_lourds_kmh")),
                "vma_vl": as_int(row.get("vitesse_vehicules_legers_kmh")),
            })
    finally:
        stream.close()
    conn.executemany(
        "INSERT INTO radars_historique_2018 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r["id"], r["date"], r["dep"], r["lat"], r["lon"], r["direction"], r["equipement"],
          r["type"], r["emplacement"], r["route"], r["longueur"], r["vma_pl"], r["vma_vl"]) for r in rows],
    )
    return rows


def read_official_radar_inventory(path):
    """Read one official inventory using its normalized cross-vintage schema."""
    stream, reader, _, _ = open_dict_reader(path)
    rows = []
    try:
        for raw in reader:
            row = source_row(raw)
            rows.append({
                "id": official_radar_identifier(row.get("numero_radar")),
                "type": clean_text(row.get("type_de_radar")),
                "date": parse_date(
                    row.get("date_de_mise_en_service"),
                    ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d"),
                ),
                "vma": as_int(row.get("vma")),
                "lat": coordinate(row.get("latitude"), latitude=True),
                "lon": coordinate(row.get("longitude"), latitude=False),
            })
    finally:
        stream.close()
    return rows


def load_official_radar_inventory(conn, path, vintage, publication_date):
    rows = read_official_radar_inventory(path)
    conn.executemany(
        "INSERT INTO radars_inventaires_officiels VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (
                vintage, publication_date, row["id"], row["type"], row["date"],
                row["vma"], row["lat"], row["lon"], path.name,
            )
            for row in rows
        ],
    )
    return rows


def match_radars(old_rows, new_rows, threshold_m=150.0):
    grid = defaultdict(list)
    for i, row in enumerate(old_rows):
        if row["lat"] is not None and row["lon"] is not None:
            grid[(round(row["lat"], 2), round(row["lon"], 2))].append(i)
    pairs = []
    for j, row in enumerate(new_rows):
        if row["lat"] is None or row["lon"] is None:
            continue
        center = (round(row["lat"], 2), round(row["lon"], 2))
        candidates = []
        for di in (-0.01, 0, 0.01):
            for dj in (-0.01, 0, 0.01):
                candidates.extend(grid.get((round(center[0] + di, 2), round(center[1] + dj, 2)), []))
        for i in candidates:
            old = old_rows[i]
            distance = haversine_m(row["lat"], row["lon"], old["lat"], old["lon"])
            if distance <= threshold_m:
                pairs.append((distance, i, j))
    pairs.sort()
    old_used, new_used, matches = set(), set(), {}
    for distance, i, j in pairs:
        if i not in old_used and j not in new_used:
            old_used.add(i)
            new_used.add(j)
            matches[j] = (i, distance)
    return matches, old_used


def load_radars(conn):
    old_rows = load_legacy_radars(conn)
    load_official_radar_inventory(
        conn, RADAR_2024_FILE, "2024-10", "2024-10-18"
    )
    new_rows = load_official_radar_inventory(
        conn, CURRENT_RADAR_FILE, "2025-12", "2025-12-30"
    )
    matches, old_used = match_radars(old_rows, new_rows)
    combined = []
    for j, new in enumerate(new_rows):
        old = None
        distance = None
        if j in matches:
            i, distance = matches[j]
            old = old_rows[i]
        combined.append((
            f"2025:{new['id']}", new["id"], old["id"] if old else None,
            new["type"], old["type"] if old else None, new["date"], old["date"] if old else None,
            new["vma"], new["lat"], new["lon"], old["dep"] if old else None,
            old["direction"] if old else None, old["emplacement"] if old else None,
            old["route"] if old else None, int(old is not None), 1,
            "apparie_geographiquement_150m" if old else "present_2025_non_apparie_2018",
            round(distance, 2) if distance is not None else None, "ministere_interieur_2025",
        ))
    for i, old in enumerate(old_rows):
        if i in old_used:
            continue
        combined.append((
            f"2018:{old['id']}", None, old["id"], None, old["type"], None, old["date"],
            old["vma_vl"], old["lat"], old["lon"], old["dep"], old["direction"],
            old["emplacement"], old["route"], 1, 0, "present_2018_non_retrouve_2025",
            None, "archive_communautaire_2018",
        ))
    conn.executemany("INSERT INTO radars VALUES (" + ",".join("?" * 19) + ")", combined)


def add_sources(conn):
    accessed = date.today().isoformat()
    rows = [
        ("baac", "Ministère de l'Intérieur / ONISR",
         "Bases annuelles des accidents corporels de la circulation routière",
         "France, 2005-2024", "Licence Ouverte / Open Licence 2.0",
         "https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-routiere-annees-de-2005-a-2024",
         accessed, "Quatre tables annuelles: caractéristiques, lieux, véhicules, usagers."),
        ("radars_2025", "Ministère de l'Intérieur / Délégation à la sécurité routière",
         "Liste des radars fixes en France", "France, situation au 30 décembre 2025",
         "Licence Ouverte / Open Licence 2.0",
         "https://www.data.gouv.fr/datasets/liste-des-radars-fixes-en-france",
         accessed, "Inventaire courant; ne constitue pas un historique complet des retraits."),
        ("radars_2024", "Ministère de l'Intérieur / Délégation à la sécurité routière",
         "Liste des radars fixes en France", "France, millésime publié le 18 octobre 2024",
         "Licence Ouverte / Open Licence 2.0",
         "https://www.data.gouv.fr/datasets/liste-des-radars-fixes-en-france",
         accessed, "Premier inventaire officiel archivé sur data.gouv.fr; couverture temporelle déclarée jusqu'au 31 mai 2024."),
        ("radars_2018", "Antoine Augusti, source Ministère de l'Intérieur",
         "Radars automatiques", "France, export du 25 octobre 2018",
         "Licence Ouverte / Open Licence 2.0",
         "https://www.data.gouv.fr/datasets/radars-automatiques",
         accessed, "Archive communautaire conservée pour l'information historique et l'enrichissement."),
    ]
    conn.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)", rows)


def add_indexes_and_views(conn):
    conn.executescript("""
    CREATE INDEX idx_accidents_year ON accidents(annee);
    CREATE INDEX idx_accidents_department ON accidents(code_departement);
    CREATE INDEX idx_accidents_geo ON accidents(latitude, longitude);
    CREATE INDEX idx_lieux_accident ON lieux(id_accident);
    CREATE INDEX idx_vehicules_accident ON vehicules(id_accident);
    CREATE INDEX idx_usagers_accident ON usagers(id_accident);
    CREATE INDEX idx_usagers_vehicle ON usagers(cle_vehicule);
    CREATE INDEX idx_radars_geo ON radars(latitude, longitude);
    CREATE INDEX idx_radars_inventaires_geo ON radars_inventaires_officiels(latitude, longitude);
    CREATE INDEX idx_radars_inventaires_id ON radars_inventaires_officiels(id_radar_officiel);
    CREATE VIEW bilan_accidents AS
    WITH lp AS (
      SELECT * FROM lieux WHERE rang_lieu = 1
    ), lc AS (
      SELECT id_accident, COUNT(*) AS nombre_lieux FROM lieux GROUP BY id_accident
    ), v AS (
      SELECT id_accident, COUNT(*) AS nombre_vehicules
      FROM vehicules GROUP BY id_accident
    ), u AS (
      SELECT id_accident, COUNT(*) AS nombre_usagers,
             SUM(CASE WHEN gravite = 2 THEN 1 ELSE 0 END) AS nombre_tues,
             SUM(CASE WHEN gravite = 3 THEN 1 ELSE 0 END) AS nombre_blesses_hospitalises,
             SUM(CASE WHEN gravite = 4 THEN 1 ELSE 0 END) AS nombre_blesses_legers
      FROM usagers GROUP BY id_accident
    )
    SELECT a.id_accident, a.annee, a.date_accident, a.heure_accident,
           a.code_departement, a.code_commune, a.agglomeration,
           a.latitude, a.longitude, a.geolocalisation_valide,
           lp.categorie_route, lp.vitesse_maximale_autorisee_kmh,
           COALESCE(lc.nombre_lieux, 0) AS nombre_lieux,
           COALESCE(v.nombre_vehicules, 0) AS nombre_vehicules,
           COALESCE(u.nombre_usagers, 0) AS nombre_usagers,
           COALESCE(u.nombre_tues, 0) AS nombre_tues,
           COALESCE(u.nombre_blesses_hospitalises, 0) AS nombre_blesses_hospitalises,
           COALESCE(u.nombre_blesses_legers, 0) AS nombre_blesses_legers
    FROM accidents a
    LEFT JOIN lp ON lp.id_accident = a.id_accident
    LEFT JOIN lc ON lc.id_accident = a.id_accident
    LEFT JOIN v ON v.id_accident = a.id_accident
    LEFT JOIN u ON u.id_accident = a.id_accident;
    CREATE VIEW qualite_par_annee AS
    SELECT a.annee,
           COUNT(*) AS nombre_accidents,
           SUM(a.geolocalisation_valide) AS accidents_geolocalises,
           ROUND(100.0 * SUM(a.geolocalisation_valide) / COUNT(*), 2) AS part_geolocalisee_pct,
           SUM(CASE WHEN a.code_commune IS NULL THEN 1 ELSE 0 END) AS code_commune_manquant,
           SUM(CASE WHEN l.id_accident IS NULL THEN 1 ELSE 0 END) AS lieu_manquant
    FROM accidents a LEFT JOIN lieux l ON l.id_accident = a.id_accident AND l.rang_lieu = 1
    GROUP BY a.annee;
    """)


def deterministic_gzip_text_writer(path):
    """Open a UTF-8 gzip writer with stable headers across operating systems."""
    raw = path.open("wb")
    compressed = gzip.GzipFile(
        filename="", fileobj=raw, mode="wb", compresslevel=6, mtime=0
    )
    return io.TextIOWrapper(compressed, encoding="utf-8", newline="")


def write_csv_gz(conn, query, path):
    cursor = conn.execute(query)
    with deterministic_gzip_text_writer(path) as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow([d[0] for d in cursor.description])
        while True:
            rows = cursor.fetchmany(20000)
            if not rows:
                break
            writer.writerows(rows)


def sampling_score(accident_id):
    return int(hashlib.sha256(accident_id.encode("utf-8")).hexdigest()[:16], 16)


def export_sample(conn, per_year=SAMPLE_PER_YEAR):
    output = SAMPLE_DIR / "accidents_echantillon.csv.gz"
    fields = [
        "id_accident", "annee", "date_accident", "heure_accident", "code_departement",
        "code_commune", "agglomeration", "latitude", "longitude", "geolocalisation_valide",
        "categorie_route", "vitesse_maximale_autorisee_kmh", "nombre_vehicules",
        "nombre_lieux", "nombre_usagers", "nombre_tues", "nombre_blesses_hospitalises", "nombre_blesses_legers",
    ]
    with deterministic_gzip_text_writer(output) as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(fields)
        for year in YEARS:
            rows = list(conn.execute(
                "SELECT " + ",".join(fields) + " FROM bilan_accidents WHERE annee=?", (year,)
            ))
            rows.sort(key=lambda row: sampling_score(row[0]))
            writer.writerows(rows[:per_year])


def export_outputs(conn):
    exports = {
        "accidents.csv.gz": "SELECT * FROM accidents ORDER BY id_accident",
        "lieux.csv.gz": "SELECT * FROM lieux ORDER BY id_accident",
        "vehicules.csv.gz": "SELECT * FROM vehicules ORDER BY id_accident, cle_vehicule",
        "usagers.csv.gz": "SELECT * FROM usagers ORDER BY id_accident, cle_usager",
        "radars.csv.gz": "SELECT * FROM radars ORDER BY cle_radar",
        "radars_inventaires.csv.gz": "SELECT * FROM radars_inventaires_officiels ORDER BY millesime, id_radar_officiel",
        "qualite_par_annee.csv.gz": "SELECT * FROM qualite_par_annee ORDER BY annee",
    }
    for filename, query in exports.items():
        print(f"Export {filename}", flush=True)
        write_csv_gz(conn, query, OUTPUT_DIR / filename)
    export_sample(conn)


def write_quality_report(conn):
    checks = []
    for table in ("accidents", "lieux", "vehicules", "usagers", "radars", "radars_inventaires_officiels"):
        checks.append((f"lignes_{table}", conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], "information"))
    checks.extend([
        ("accidents_sans_lieu", conn.execute("SELECT COUNT(*) FROM accidents a LEFT JOIN lieux l USING(id_accident) WHERE l.id_accident IS NULL").fetchone()[0], "doit_etre_0"),
        ("lieux_sans_accident", conn.execute("SELECT COUNT(*) FROM lieux l LEFT JOIN accidents a USING(id_accident) WHERE a.id_accident IS NULL").fetchone()[0], "doit_etre_0"),
        ("accidents_plusieurs_lieux", conn.execute("SELECT COUNT(*) FROM (SELECT id_accident FROM lieux GROUP BY id_accident HAVING COUNT(*)>1)").fetchone()[0], "information"),
        ("lignes_lieux_supplementaires", conn.execute("SELECT COUNT(*)-COUNT(DISTINCT id_accident) FROM lieux").fetchone()[0], "information"),
        ("vehicules_sans_accident", conn.execute("SELECT COUNT(*) FROM vehicules v LEFT JOIN accidents a USING(id_accident) WHERE a.id_accident IS NULL").fetchone()[0], "doit_etre_0"),
        ("usagers_sans_accident", conn.execute("SELECT COUNT(*) FROM usagers u LEFT JOIN accidents a USING(id_accident) WHERE a.id_accident IS NULL").fetchone()[0], "doit_etre_0"),
        ("usagers_sans_vehicule_apparie", conn.execute("SELECT COUNT(*) FROM usagers u LEFT JOIN vehicules v ON v.cle_vehicule=u.cle_vehicule WHERE v.cle_vehicule IS NULL").fetchone()[0], "a_examiner"),
        ("vehicules_sans_usager_apparie", conn.execute("SELECT COUNT(*) FROM vehicules v LEFT JOIN usagers u ON u.cle_vehicule=v.cle_vehicule WHERE u.cle_vehicule IS NULL").fetchone()[0], "information"),
        ("radars_2025_apparies_2018", conn.execute("SELECT COUNT(*) FROM radars WHERE actif_liste_2025=1 AND observe_2018=1").fetchone()[0], "information"),
        ("radars_2025_non_apparies", conn.execute("SELECT COUNT(*) FROM radars WHERE actif_liste_2025=1 AND observe_2018=0").fetchone()[0], "information"),
        ("radars_2018_non_retrouves_2025", conn.execute("SELECT COUNT(*) FROM radars WHERE actif_liste_2025=0 AND observe_2018=1").fetchone()[0], "information"),
        ("radars_apparies_distance_superieure_75m", conn.execute("SELECT COUNT(*) FROM radars WHERE distance_rapprochement_m>75").fetchone()[0], "a_examiner"),
        ("radars_apparies_dates_differentes", conn.execute("SELECT COUNT(*) FROM radars WHERE observe_2018=1 AND actif_liste_2025=1 AND date_mise_en_service<>date_installation_2018").fetchone()[0], "information"),
        ("radars_inventaire_2024", conn.execute("SELECT COUNT(*) FROM radars_inventaires_officiels WHERE millesime='2024-10'").fetchone()[0], "information"),
        ("radars_inventaire_2025", conn.execute("SELECT COUNT(*) FROM radars_inventaires_officiels WHERE millesime='2025-12'").fetchone()[0], "information"),
        ("radars_communs_2024_2025", conn.execute("SELECT COUNT(*) FROM radars_inventaires_officiels a JOIN radars_inventaires_officiels b USING(id_radar_officiel) WHERE a.millesime='2024-10' AND b.millesime='2025-12'").fetchone()[0], "information"),
        ("radars_sortis_entre_2024_2025", conn.execute("SELECT COUNT(*) FROM radars_inventaires_officiels a LEFT JOIN radars_inventaires_officiels b ON b.id_radar_officiel=a.id_radar_officiel AND b.millesime='2025-12' WHERE a.millesime='2024-10' AND b.id_radar_officiel IS NULL").fetchone()[0], "information"),
        ("radars_entres_entre_2024_2025", conn.execute("SELECT COUNT(*) FROM radars_inventaires_officiels b LEFT JOIN radars_inventaires_officiels a ON a.id_radar_officiel=b.id_radar_officiel AND a.millesime='2024-10' WHERE b.millesime='2025-12' AND a.id_radar_officiel IS NULL").fetchone()[0], "information"),
    ])
    with (METADATA_DIR / "rapport_qualite.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["controle", "valeur", "interpretation"])
        writer.writerows(checks)


def write_schema_dictionary(conn):
    rows = []
    objects = conn.execute(
        "SELECT name, type FROM sqlite_master "
        "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
    )
    for object_name, object_type in objects:
        for _, column, sql_type, not_null, _, primary_key in conn.execute(
            f'PRAGMA table_info("{object_name}")'
        ):
            rows.append((object_name, object_type, column, sql_type, not_null, primary_key))
    with (METADATA_DIR / "schema.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["objet", "type_objet", "colonne", "type_sql", "non_nul", "cle_primaire"])
        writer.writerows(rows)


def sha256_manifest():
    files = sorted(
        path for path in PACKAGE_DIR.rglob("*")
        if path.is_file()
        and path.name != "sha256.txt"
        and "__pycache__" not in path.parts
        and ".git" not in path.parts
        and "release" not in path.parts
        and not (PACKAGE_DIR / "data" / "raw") in path.parents
        and path != DB_PATH
        and not path.name.endswith((".sqlite-wal", ".sqlite-shm"))
    )
    with (METADATA_DIR / "sha256.txt").open("w", encoding="utf-8") as stream:
        for path in files:
            if path.name == "sha256.txt" or not path.is_file():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            stream.write(f"{digest}  {path.relative_to(PACKAGE_DIR)}\n")


def file_sha256(path, block_size=1024 * 1024):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def write_raw_source_manifest():
    rows = []
    for year in YEARS:
        for kind in ("caracteristiques", "lieux", "vehicules", "usagers"):
            path = baac_path(kind, year)
            display = path.relative_to(PACKAGE_DIR)
            rows.append(("baac", year, kind, str(display), path.stat().st_size, file_sha256(path)))
    for source_id, path in (
        ("radars_2018", LEGACY_RADAR_FILE),
        ("radars_2024", RADAR_2024_FILE),
        ("radars_2025", CURRENT_RADAR_FILE),
    ):
        rows.append((source_id, "", "radars", str(path.relative_to(PACKAGE_DIR)), path.stat().st_size, file_sha256(path)))
    with (METADATA_DIR / "fichiers_sources_sha256.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["source_id", "annee", "table", "fichier", "octets", "sha256"])
        writer.writerows(rows)


def main():
    validate_sources()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        load_baac(conn)
        with conn:
            load_radars(conn)
            add_sources(conn)
            conn.executemany("INSERT INTO construction VALUES (?,?)", [
                ("version", VERSION),
                ("date_construction_utc", datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
                ("python", sys.version.split()[0]),
                ("annees_baac", "2005-2024"),
                ("millésimes_radars_officiels", "2024-10,2025-12"),
                ("seuil_appariement_radars_m", "150"),
            ])
            add_indexes_and_views(conn)
        conn.execute("PRAGMA optimize")
        conn.commit()
        export_outputs(conn)
        write_quality_report(conn)
        write_schema_dictionary(conn)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
    finally:
        conn.close()
    write_raw_source_manifest()
    sha256_manifest()
    print(f"Base créée: {DB_PATH}")


if __name__ == "__main__":
    main()
