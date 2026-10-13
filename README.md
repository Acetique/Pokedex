# Pokédex V4.9 — GitHub Pages

Téléverser `index.html`, `update_pokedex.py`, `sw.js`, `manifest.webmanifest`, `data/` et `.github/workflows/actualiser-pokedex.yml` en conservant les chemins.

GitHub → Settings → Actions → General → Workflow permissions : Read and write permissions.

GitHub → Actions → Actualiser le Pokedex → Run workflow.

Le workflow met à jour le maximum d’espèces et les générations selon PokéAPI, puis collecte les liens d’articles accessibles depuis la page d’actualités officielle Pokémon. Les liens s’affichent dans « Nouveautés Pokémon » ; ils ne sont **pas** automatiquement transformés en fiches, faute de preuve structurée du nom, type, numéro et illustration.

Données : `data/catalogue-status.json`, `data/nouveautes-pokemon.json`, `data/official-news-review.json`.

Le site reste bilingue ; l’actualisation est quotidienne à 12:00 UTC (8 h en été / 7 h en hiver au Québec). Aucun fichier `requirements.txt` requis.
