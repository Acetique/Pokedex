# Pokédex V4.8 — Mise à jour automatique

Déposez **tout le contenu** du ZIP à la racine du dépôt GitHub Pages, y compris le dossier `.github/workflows/` et `update_pokedex.py`.

Dans GitHub, ouvrez **Actions > Actualiser le Pokedex > Run workflow** pour la première exécution. Ensuite, le contrôle est planifié quotidiennement (GitHub peut retarder ou suspendre les tâches programmées). Autorisez les workflows à écrire dans le dépôt : **Settings > Actions > General > Workflow permissions > Read and write permissions**. Si la branche est protégée, les commits automatiques peuvent échouer.

Le script détecte les nouveaux Pokémon **officiellement intégrés à PokéAPI** et met à jour la limite et les plages de générations de l'application. Il surveille aussi la page officielle d'actualités Pokémon et écrit le résultat dans `data/official-news-review.json`, **sans créer automatiquement des fiches depuis les annonces**. Cette surveillance de page n'est pas un moteur de recherche général du Web. Elle ne permet pas à elle seule d'extraire les noms de nouveaux Pokémon. Les informations issues d'autres sites ou non structurées nécessitent une vérification et une intégration distinctes.

Les trois starters de génération 10 déjà inclus restent des entrées provisoires; leurs numéros locaux ne doivent pas être considérés comme des numéros nationaux officiels. Si PokéAPI attribue un de ces identifiants à un autre Pokémon, l'entrée manuelle est masquée.

Les noms français et les images dépendent de la disponibilité des données et des services de traduction. Les nouveaux Pokémon peuvent donc avoir des fiches incomplètes. Un ajout majeur de génération peut nécessiter un ajustement manuel du site.
