# Accidents corporels et radars fixes en France

Base relationnelle harmonisée destinée à la recherche et à l'enseignement.
La version courante est **1.0.0**.

## Contenu

- Accidents corporels BAAC : 2005-2024.
- Quatre niveaux d'observation préservés : accidents, lieux, véhicules et usagers.
- Radars fixes : inventaire officiel au 30 décembre 2025.
- Archive des radars de 2018, conservée séparément et rapprochée de l'inventaire 2025 par coordonnées.
- Un fichier SQLite, des exports CSV compressés et un extrait pédagogique déterministe.

La base ne reproduit pas les choix empiriques du mémoire présent dans le dossier. Elle constitue une infrastructure générale. Les panels radar × année × rayon doivent être construits comme produits dérivés documentés.

## Fichiers produits

| Fichier | Rôle |
| --- | --- |
| `data/processed/accidents_radars_france_2005_2025.sqlite` | Base complète et vues prêtes à interroger |
| `data/processed/accidents.csv.gz` | Un accident par ligne |
| `data/processed/lieux.csv.gz` | Un enregistrement de lieu par accident |
| `data/processed/vehicules.csv.gz` | Un véhicule impliqué par ligne |
| `data/processed/usagers.csv.gz` | Un usager impliqué par ligne |
| `data/processed/radars.csv.gz` | Inventaires 2018 et 2025 rapprochés |
| `data/teaching/accidents_extrait_pedagogique.csv.gz` | Échantillon reproductible, au plus 2 000 accidents par année |
| `metadata/rapport_qualite.csv` | Contrôles d'intégrité et effectifs |
| `metadata/fichiers_sources_sha256.csv` | Inventaire et empreintes des fichiers bruts |
| `metadata/schema.csv` | Schéma exhaustif des tables et des vues |
| `metadata/variables.csv` | Dictionnaire commenté des variables principales |
| `metadata/sha256.txt` | Empreintes des fichiers versionnés dans le dépôt |

## Schéma relationnel

`id_accident` relie `accidents`, `lieux`, `vehicules` et `usagers`. `cle_vehicule` relie les véhicules aux usagers. Les identifiants absents avant 2019 sont reconstruits de façon déterministe à partir de l'accident et du numéro de véhicule ; ils servent à la jointure interne et ne sont pas des identifiants administratifs. Les fichiers officiels des lieux 2023 et 2024 contiennent plusieurs lignes pour de nombreux accidents. Elles sont toutes conservées avec `rang_lieu`; les vues synthétiques utilisent la première ligne et exposent `nombre_lieux`.

La vue SQLite `bilan_accidents` fournit une ligne par accident avec le nombre de véhicules, d'usagers, de tués et de blessés. La vue `qualite_par_annee` décrit notamment la couverture géographique.

## Construire la base

### Prérequis

- Python 3.9 ou une version ultérieure ;
- environ 3 Go d'espace libre pendant la construction ;
- les fichiers BAAC bruts décrits ci-dessous.

Le constructeur n'utilise aucun paquet Python externe.

### Préparer les sources

Télécharger les fichiers BAAC depuis la [page officielle de
data.gouv.fr](https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-routiere-annees-de-2005-a-2024).
Pour chaque année de 2005 à 2024, placer les quatre tables dans
`data/raw/baac` en appliquant exactement les noms suivants :

```text
data/raw/baac/
├── caracteristiques_AAAA.csv
├── lieux_AAAA.csv
├── vehicules_AAAA.csv
└── usagers_AAAA.csv
```

Les noms sont normalisés, y compris pour les sources de 2021 qui utilisent
initialement des traits d'union et une orthographe différente. Les fichiers
radar 2018 et 2025 nécessaires à la construction sont déjà fournis dans
`data/raw/radars`.

Les fichiers BAAC bruts, volumineux et déjà diffusés par leur producteur, ne
sont pas versionnés dans ce dépôt. Leur taille et leur empreinte attendue sont
consignées dans `metadata/fichiers_sources_sha256.csv`.

### Lancer la construction

Depuis la racine du dépôt :

```bash
python3 scripts/build_database.py
```

Avant de remplacer un livrable existant, le script vérifie la présence et
l'empreinte SHA-256 des 82 fichiers sources. Il exécute ensuite, dans cet ordre :

1. l'harmonisation des quatre tables BAAC ;
2. le chargement et le rapprochement géographique des radars 2018 et 2025 ;
3. la création des index et des vues SQLite ;
4. l'export des CSV compressés et de l'extrait pédagogique ;
5. les contrôles qualité, le schéma exhaustif et les manifestes d'empreintes.

Les CSV compressés sont produits avec des en-têtes gzip déterministes et des
fins de ligne normalisées. À sources et version de code identiques, leur
contenu binaire est donc reproductible. La base SQLite conserve volontairement
la date UTC de sa construction dans la table `construction`.

### Vérifier les livrables

Après une construction complète :

```bash
python3 scripts/check_database.py --require-sqlite
```

Dans une copie du dépôt ne contenant pas la base SQLite de la Release :

```bash
python3 scripts/check_database.py
```

Le contrôle vérifie les empreintes, l'ouverture des exports compressés,
l'intégrité SQLite, les clés étrangères, la version et les principaux
effectifs. Le même contrôle est lancé automatiquement à chaque modification du
dépôt par GitHub Actions.

## Utilisation dans R

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

## Précautions d'interprétation

- La géolocalisation des accidents est très incomplète pour plusieurs premiers millésimes. La variable `geolocalisation_valide` et la vue `qualite_par_annee` permettent de mesurer cette couverture ; aucune coordonnée communale n'est imputée silencieusement.
- La qualification de « blessé hospitalisé » n'est pas comparable avant et après 2018 en raison d'un changement de processus de saisie. L'indicateur n'est plus labellisé depuis 2019.
- À partir de 2021, des usagers en fuite ont été ajoutés ; leur sexe, leur âge et parfois leur gravité peuvent manquer.
- Les fichiers BAAC sont des données brutes non corrigées de toutes les erreurs de saisie.
- Les millésimes `lieux` 2023 et 2024 ne respectent pas toujours la relation attendue d'une ligne par accident. Ne pas agréger ces fichiers sans tenir compte de `rang_lieu` ou de `nombre_lieux`.
- La liste de radars 2025 est un état courant, pas un historique des retraits. Un radar présent en 2018 mais non retrouvé en 2025 ne doit pas être déclaré « fermé » sans source supplémentaire.
- Les identifiants radar de 2018 et de 2025 ne coïncident pas. L'appariement géographique est effectué à moins de 150 mètres et la distance est conservée dans `distance_rapprochement_m`.
- Un rapprochement géographique n'établit pas qu'il s'agit du même appareil physique : un équipement peut avoir été remplacé au même emplacement. Les deux dates sont conservées et les divergences ne sont pas corrigées automatiquement.
- Pour une analyse spatiale, utiliser une distance géodésique ou une projection adaptée. Ne pas appliquer une distance euclidienne directement aux degrés de latitude et longitude.

## Provenance et redistribution

Les données produites sont placées sous Licence Ouverte 2.0 et les scripts sous
licence MIT. Les textes complets et les attributions à reproduire figurent dans
`LICENSE-DATA.md`, `LICENSE-CODE.md` et `LICENCE.md`. Les sources et leurs
licences sont détaillées dans `metadata/sources.csv`.

Lors d'une redistribution, conserver ces quatre fichiers et indiquer le
millésime de la base. Les documents provenant de tiers conservent leurs droits
et conditions propres. Le mémoire de master utilisé lors des travaux
préliminaires ne fait pas partie de ce dépôt redistribuable.

## Téléchargement de la base complète

Les exports CSV compressés, adaptés à R, sont versionnés dans le dépôt. La base
SQLite complète est distribuée séparément comme fichier joint à chaque version
publiée dans la rubrique *Releases* de GitHub. Cette séparation évite de placer
un fichier binaire de plus d'un gigaoctet dans l'historique Git.

Chaque Release accompagne la base compressée d'un fichier `SHA256SUMS.txt`.
Ces deux fichiers sont produits après validation de la base avec :

```bash
python3 scripts/package_release.py
```

Après téléchargement, leur intégrité peut être vérifiée avec :

```bash
shasum -a 256 -c SHA256SUMS.txt
```

## Mise à jour

1. Télécharger les quatre fichiers BAAC du nouveau millésime depuis la page officielle.
2. Les placer dans `data/raw/baac` avec les noms `caracteristiques_AAAA.csv`, `lieux_AAAA.csv`, `vehicules_AAAA.csv` et `usagers_AAAA.csv`.
3. Mettre à jour `YEARS`, `VERSION` et les métadonnées de millésime dans le script.
4. Remplacer l'inventaire radar courant, sans écraser l'archive 2018.
5. Mettre à jour explicitement le manifeste des sources après vérification du
   nouveau millésime.
6. Reconstruire la base, examiner `rapport_qualite.csv`, lancer
   `scripts/check_database.py --require-sqlite`, puis publier les nouvelles
   empreintes SHA-256.
