# Accidents corporels et radars fixes en France

Base relationnelle harmonisée des accidents corporels de la circulation et des
radars fixes en France. La version courante est **1.1.0**.

Le dépôt fournit une infrastructure de données générale : il conserve les
niveaux d'observation et les variables sources sans imposer les choix
d'échantillon, de distance ou d'estimation d'une étude particulière. Le code
et les données dérivées de l'article sur les radars fixes sont distribués dans
le dépôt séparé
[`jrenne/accidents-radars-replication`](https://github.com/jrenne/accidents-radars-replication).

## Démarrage rapide

Les exports CSV compressés sont directement versionnés dans `data/processed/`.
La base SQLite complète est jointe à la
[Release correspondante](https://github.com/jrenne/accidents-radars-france/releases)
afin de ne pas alourdir l'historique Git. Un échantillon déterministe limité à
2 000 accidents par année est disponible dans
`data/sample/accidents_echantillon.csv.gz` pour une prise en main rapide.

En R, un export peut être lu sans décompression préalable :

```r
accidents <- read.csv("data/processed/accidents.csv.gz")
radars <- read.csv("data/processed/radars.csv.gz")
```

Pour interroger la base relationnelle :

```r
library(DBI)
library(RSQLite)

con <- dbConnect(
  SQLite(),
  "data/processed/accidents_radars_france_2005_2025.sqlite"
)

dbGetQuery(con, "SELECT * FROM qualite_par_annee ORDER BY annee")
accidents_2024 <- dbGetQuery(
  con,
  "SELECT * FROM bilan_accidents WHERE annee = 2024"
)

dbDisconnect(con)
```

## Périmètre

La version 1.1.0 réunit :

- les tables BAAC annuelles de 2005 à 2024 ;
- les quatre niveaux d'observation d'origine : accidents, lieux, véhicules et
  usagers ;
- les inventaires officiels de radars publiés le 18 octobre 2024 et le
  30 décembre 2025 ;
- une archive des radars de 2018, conservée séparément puis rapprochée de
  l'inventaire 2025 par coordonnées ;
- des dictionnaires, rapports de qualité et empreintes permettant de vérifier
  chaque produit.

Le registre de référence des sources est
[`metadata/sources.csv`](metadata/sources.csv). Il indique, pour chaque entrée
utilisée par la base ou par l'archive d'entrées de réplication, le producteur,
la couverture, la licence, l'adresse officielle et la date de consultation.
Les empreintes des fichiers effectivement archivés sont conservées séparément
dans `metadata/fichiers_sources_sha256.csv`.

Les listes de radars sont des états successifs, pas un historique exhaustif de
leur fonctionnement. Une disparition entre deux inventaires est enregistrée
comme une sortie de liste et n'est pas assimilée automatiquement à une
fermeture définitive.

## Organisation des données

| Couche | Produits | Fonction |
| --- | --- | --- |
| Sources | Tables BAAC annuelles et inventaires radar | Fichiers publics conservés avec leur provenance et leur empreinte |
| Harmonisation | SQLite et CSV compressés | Noms, types, clés et codages rendus cohérents entre millésimes |
| Documentation | Schéma, dictionnaire et rapport de qualité | Structure, définitions et contrôles consultables sans relancer la construction |
| Produits dérivés | Échantillon allégé et archive de réplication | Usages spécifiques, séparés des tables harmonisées générales |

### Schéma relationnel

`id_accident` relie `accidents`, `lieux`, `vehicules` et `usagers`.
`cle_vehicule` relie les véhicules aux usagers. Les identifiants de véhicule
absents des premiers millésimes sont reconstruits de façon déterministe à
partir de l'accident et du numéro de véhicule ; ils servent aux jointures
internes et ne sont pas des identifiants administratifs.

Les fichiers `lieux` de 2023 et 2024 comportent plusieurs lignes pour de
nombreux accidents. Toutes sont conservées avec `rang_lieu`. Les vues
synthétiques utilisent la première ligne et exposent `nombre_lieux`, afin que
cette simplification reste visible.

La vue SQLite `bilan_accidents` fournit une ligne par accident avec les nombres
de véhicules, d'usagers, de tués et de blessés. La vue
`qualite_par_annee` décrit notamment la couverture géographique.

### Principaux fichiers

| Fichier | Contenu |
| --- | --- |
| `data/processed/accidents_radars_france_2005_2025.sqlite` | Base complète, index et vues prêtes à interroger |
| `data/processed/accidents.csv.gz` | Une ligne par accident |
| `data/processed/lieux.csv.gz` | Une ou plusieurs lignes de lieu par accident |
| `data/processed/vehicules.csv.gz` | Un véhicule impliqué par ligne |
| `data/processed/usagers.csv.gz` | Un usager impliqué par ligne |
| `data/processed/radars.csv.gz` | Archives 2018 et 2025 rapprochées |
| `data/processed/radars_inventaires.csv.gz` | Inventaires officiels 2024 et 2025 en format longitudinal |
| `data/processed/qualite_par_annee.csv.gz` | Principaux indicateurs annuels de couverture |
| `data/sample/accidents_echantillon.csv.gz` | Échantillon déterministe, au plus 2 000 accidents par année |
| `metadata/schema.csv` | Schéma exhaustif des tables et des vues |
| `metadata/variables.csv` | Dictionnaire commenté des variables principales |
| `metadata/rapport_qualite.csv` | Contrôles d'intégrité et effectifs |
| `metadata/fichiers_sources_sha256.csv` | Inventaire et empreintes des sources brutes |
| `metadata/sha256.txt` | Empreintes des fichiers publiés dans le dépôt |

## Harmonisation et précautions d'interprétation

Les scripts harmonisent les séparateurs, encodages, noms de colonnes et types
qui varient selon les années, tout en conservant les codes sources. Aucune
coordonnée communale n'est imputée silencieusement.

Les principales limites à connaître sont les suivantes :

- la géolocalisation des accidents est incomplète pour plusieurs premiers
  millésimes ; `geolocalisation_valide` et `qualite_par_annee` permettent d'en
  mesurer la couverture ;
- la qualification de « blessé hospitalisé » n'est pas comparable avant et
  après 2018 et n'est plus labellisée depuis 2019 ;
- à partir de 2021, les usagers en fuite peuvent avoir des informations
  manquantes sur le sexe, l'âge ou la gravité ;
- les fichiers BAAC restent exposés aux erreurs de saisie présentes dans les
  sources publiques ;
- les identifiants radar de 2018 et de 2025 ne coïncident pas : le
  rapprochement est géographique, à moins de 150 mètres, et sa distance est
  conservée dans `distance_rapprochement_m` ;
- un rapprochement géographique n'établit pas qu'il s'agit du même appareil
  physique, car un équipement peut être remplacé au même emplacement ;
- toute analyse spatiale doit utiliser une distance géodésique ou une
  projection adaptée, et non une distance euclidienne appliquée directement
  aux degrés de latitude et longitude.

La base ne construit pas de panel causal radar × période × zone spatiale. Ces
choix dépendent de la question étudiée et doivent rester des produits dérivés
documentés.

## Reproduire la base

### Prérequis

- Python 3.9 ou une version ultérieure ;
- environ 3 Go d'espace libre pendant la construction ;
- les fichiers BAAC bruts décrits ci-dessous.

Le constructeur n'utilise aucun paquet Python externe.

### Préparer les sources

Télécharger les fichiers BAAC depuis la [page officielle de
data.gouv.fr](https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-routiere-annees-de-2005-a-2024).
Pour chaque année de 2005 à 2024, placer les quatre tables dans
`data/raw/baac` avec les noms suivants :

```text
data/raw/baac/
├── caracteristiques_AAAA.csv
├── lieux_AAAA.csv
├── vehicules_AAAA.csv
└── usagers_AAAA.csv
```

Les fichiers radar 2018, 2024 et 2025 sont déjà fournis dans
`data/raw/radars`. Les fichiers BAAC bruts, volumineux et déjà diffusés par leur
producteur, ne sont pas dupliqués. Leurs noms, tailles et empreintes attendues
figurent dans `metadata/fichiers_sources_sha256.csv`.

### Construire et vérifier

Depuis la racine du dépôt :

```bash
python3 scripts/build_database.py
python3 scripts/check_database.py --require-sqlite
```

Le constructeur vérifie les 83 fichiers sources avant de remplacer un
livrable. Il harmonise les quatre tables BAAC, traite les inventaires radar,
crée les index et vues SQLite, exporte les CSV et l'échantillon allégé, puis
produit les métadonnées de contrôle.

Les CSV compressés ont des en-têtes gzip déterministes et des fins de ligne
normalisées : à sources et code identiques, leur contenu binaire est
reproductible. La base SQLite conserve volontairement la date UTC de sa
construction. Le vérificateur peut aussi être exécuté sans l'option
`--require-sqlite` dans une copie ne contenant que les fichiers versionnés.

## Releases et réplication de l'article

La base SQLite, compressée, est distribuée comme actif de Release avec
`SHA256SUMS.txt`. Le script `scripts/package_release.py` prépare ces deux
fichiers après validation.

La Release `v1.1.0` fournit également
`accidents_radars_replication_inputs-v1.1.0.tar.gz`. Cette archive contient les
instantanés routiers et de trafic ainsi que les entrées spatiales figées dont
le package de réplication de l'article a besoin. Elle n'est pas nécessaire pour
utiliser la base ou l'échantillon allégé. Son empreinte figure dans
`release/REPLICATION_INPUTS_SHA256.txt`.

## Licences et citation

Les données produites sont placées sous Licence Ouverte 2.0 et les scripts sous
licence MIT. Les textes et attributions à conserver figurent dans
`LICENSE-DATA.md`, `LICENSE-CODE.md`, `LICENCE.md` et `metadata/sources.csv`.
Les documents provenant de tiers conservent leurs conditions propres.

Pour citer la base, utiliser les informations de `CITATION.cff`, préciser la
version employée et citer les producteurs des sources indiqués dans
`metadata/sources.csv`.

## Mettre à jour la base

1. Ajouter les quatre tables BAAC du nouveau millésime dans `data/raw/baac`.
2. Mettre à jour les années, la version et les métadonnées dans le constructeur.
3. Ajouter le nouvel inventaire radar comme un millésime distinct.
4. Mettre à jour explicitement le manifeste des sources.
5. Reconstruire la base et examiner `metadata/rapport_qualite.csv`.
6. Exécuter `scripts/check_database.py --require-sqlite`, puis préparer la
   nouvelle Release et ses empreintes.
