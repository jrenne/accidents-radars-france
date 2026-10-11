# Historique des versions

## 1.1.0 - 2026-10-11

- Ajout de l'inventaire officiel des radars publié le 18 octobre 2024.
- Création d'une table longitudinale des inventaires officiels 2024 et 2025.
- Identification de 3 174 radars communs, 94 sorties de liste et 135 entrées entre
  les deux millésimes, sans assimiler automatiquement les sorties à des fermetures.
- Ajout d'un export CSV dédié et de contrôles de cohérence inter-millésimes.

## 1.0.0 - 2026-10-11

- Première version publique de la base harmonisée BAAC 2005-2024.
- Ajout de l'inventaire officiel des radars fixes au 30 décembre 2025 et de
  l'archive 2018.
- Publication des exports CSV compressés et de la base relationnelle SQLite.
- Ajout des licences, des métadonnées de provenance et des contrôles qualité.
- Ajout d'un schéma exhaustif, d'un vérificateur autonome et d'une validation
  continue du paquet.
- Stabilisation binaire des exports compressés et contrôle préalable des
  empreintes des sources avant toute reconstruction.

## 0.1.0 - 2026-10-11

- Harmonisation des quatre tables BAAC de 2005 à 2024.
- Ajout des millésimes BAAC 2022, 2023 et 2024 depuis data.gouv.fr.
- Ajout de la liste officielle des radars fixes au 30 décembre 2025.
- Conservation de l'archive radar 2018 et rapprochement géographique à 150 mètres.
- Création de la base SQLite, des CSV compressés et de l'extrait pédagogique.
- Conservation des lignes multiples des fichiers `lieux` 2023 et 2024.
- Ajout des contrôles d'intégrité, de la documentation et des empreintes SHA-256.
