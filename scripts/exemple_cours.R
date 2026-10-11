# SPDX-License-Identifier: MIT
# Exemple minimal sans dépendance : lire l'extrait pédagogique compressé.
chemin <- "data-package/data/teaching/accidents_extrait_pedagogique.csv.gz"
accidents <- read.csv(gzfile(chemin), stringsAsFactors = FALSE)

# Nombre d'accidents et de tués dans l'extrait, par année.
bilan <- aggregate(
  cbind(nombre_accidents = rep(1, nrow(accidents)), nombre_tues) ~ annee,
  data = accidents,
  FUN = sum
)
print(bilan)

# La part géolocalisée varie fortement selon le millésime.
couverture_geo <- aggregate(
  geolocalisation_valide ~ annee,
  data = accidents,
  FUN = mean
)
plot(
  couverture_geo$annee,
  100 * couverture_geo$geolocalisation_valide,
  type = "b",
  xlab = "Année",
  ylab = "Accidents géolocalisés (%)"
)
