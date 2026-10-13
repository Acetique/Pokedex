
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX ACETIQUE V6.1
Détection anticipée des nouveaux Pokémon.

- Recherche les annonces actuelles et historiques.
- Analyse uniquement les annonces officielles.
- Exclut les produits, événements et faux positifs.
- Détecte les noms potentiels de nouvelles espèces.
- Compare les candidats avec PokéAPI et les noms FR/EN.
- Conserve les décisions manuelles.
- Génère un rapport détaillé.
- Inclut des tests automatiques.
- N'ajoute jamais de Pokémon au catalogue.

Bibliothèque standard Python uniquement.

Commandes :
    python detecter_nouveaux_pokemon.py
    python detecter_nouveaux_pokemon.py --test
"""

import argparse
import json
import re
import sys
import unicodedata

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


VERSION = "6.1"
DATA = Path("data")

OUTPUT = DATA / "pokemon-a-verifier.json"
REPORT = DATA / "rapport-detection-v6.json"
VALIDATIONS = DATA / "validation-pokemon.json"

POKEAPI_CACHE = DATA / "pokeapi-cache.json"
BILINGUAL_NAMES = DATA / "noms-pokemon-fr.json"

POKEAPI_URL = (
    "https://pokeapi.co/api/v2/"
    "pokemon-species?limit=2000"
)

# Fichiers produits ou susceptibles d'être produits
# par le collecteur. Seuls les fichiers existants
# seront utilisés.
NEWS_FILES = [
    "nouveautes-pokemon.json",
    "annonces-prioritaires.json",
    "historique-actualites.json",
    "official-news-review.json",
]

PROVISIONAL = {
    "browt",
    "pombon",
    "gecqua",
}

EXCLUDED_NAMES = {
    "animated", "animation", "anime",
    "app", "apps", "battle", "battles",
    "beauty", "book", "books",
    "card", "cards", "center",
    "champion", "champions",
    "championship", "championships",
    "collection", "collections",
    "contest", "contests",
    "day", "direct", "event", "events",
    "expansion", "expansions",
    "festival", "friends",
    "fundamentals", "game", "games",
    "gallery", "gift", "gifts",
    "guide", "home", "illustration",
    "league", "legends", "live",
    "machine", "movie", "news",
    "pack", "packs", "paldea",
    "perfect", "pinball", "plush",
    "presents", "primer", "primers",
    "prize", "prizes",
    "product", "products",
    "region", "regions",
    "release", "series",
    "sinnoh", "sinnohs",
    "snap", "store", "supplies",
    "tcg", "top", "trading",
    "trailer", "update", "updates",
    "video", "videos",
    "winner", "winners",
    "world", "worlds",
    "the", "this", "these",
    "those", "new", "first",
}

EXCLUDED_CONTEXTS = [
    r"\bpokemon\s+home\b",
    r"\bpokemon\s+presents\b",
    r"\bpokemon\s+snap\b",
    r"\bpokemon\s+pinball\b",
    r"\bpokemon\s+trading\s+card\b",
    r"\bpokemon\s+tcg\b",
    r"\bpokemon\s+league\b",
    r"\bpokemon\s+center\b",
    r"\bpokemon\s+go\b",
    r"\bpokemon\s+unite\b",
    r"\bpokemon\s+masters\b",
    r"\banimated\s+series\b",
    r"\btrading\s+card\s+game\b",
    r"\billustration\s+contest\b",
    r"\bschool\s+supplies\b",
]

# Règles de détection, classées par fiabilité.
# Les scores sont heuristiques : ils ne représentent
# pas une probabilité de confirmation officielle.
PATTERNS = [
    (
        95,
        "Espèce explicitement nommée",
        r"\b(?:new|brand new)\s+"
        r"pokemon\s+species\s+"
        r"(?:named|called)\s+"
        r"([A-Za-z][A-Za-z'-]{2,24})\b",
    ),
    (
        90,
        "Nouveau Pokémon nommé",
        r"\b(?:new|brand new)\s+"
        r"pokemon\s+(?:named|called)\s+"
        r"([A-Za-z][A-Za-z'-]{2,24})\b",
    ),
    (
        90,
        "Présentation explicite",
        r"\b(?:meet|introducing|discover)\s+"
        r"(?:the\s+)?(?:brand\s+)?new\s+"
        r"pokemon\s+(?:named|called)\s+"
        r"([A-Za-z][A-Za-z'-]{2,24})\b",
    ),
    (
        85,
        "Révélation d'une nouvelle espèce",
        r"\b([A-Za-z][A-Za-z'-]{2,24})\s+"
        r"(?:is|has been)\s+"
        r"(?:officially\s+)?revealed\s+"
        r"as\s+a\s+new\s+pokemon\b",
    ),
    (
        80,
        "Présentation avec description",
        r"\b(?:meet|introducing)\s+"
        r"([A-Za-z][A-Za-z'-]{2,24})\s*"
        r"[,:\-]\s*(?:a|the)\s+"
        r"(?:brand\s+)?new\s+pokemon\b",
    ),
    (
        75,
        "Nouvelle espèce présentée",
        r"\b(?:meet|introducing)\s+"
        r"(?:the\s+)?(?:new|newly discovered)\s+"
        r"pokemon\s+([A-Za-z][A-Za-z'-]{2,24})"
        r"(?=\s*[,.:;!?-]|\s*$)",
    ),
    (
        70,
        "Nom présenté comme Pokémon",
        r"\b(?:meet|introducing)\s+"
        r"([A-Za-z][A-Za-z'-]{2,24})\s*"
        r"[,:\-]\s*(?:a|an)\s+pokemon\b",
    ),
]


def timestamp():
    return datetime.now(
        timezone.utc
    ).isoformat()


def normalize(value):
    value = unicodedata.normalize(
        "NFKD",
        str(value or "").lower()
    )

    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )

    return re.sub(
        r"[^a-z0-9]+",
        "",
        value
    )


def load_json(path, default=None):
    if not path.exists():
        return default

    try:
        with path.open(
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except (OSError, ValueError) as error:
        print(
            f"[V6.1] Erreur lecture "
            f"{path}: {error}"
        )
        return default


def save_json(path, content):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with path.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            content,
            file,
            indent=2,
            ensure_ascii=False
        )
        file.write("\n")


def official_url(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()

        return (
            parsed.scheme in ("http", "https")
            and host in (
                "pokemon.com",
                "www.pokemon.com"
            )
        )

    except (TypeError, ValueError):
        return False


def collect_articles(data):
    """
    Recherche récursivement les objets contenant
    un titre et une URL officielle.

    Les listes de simples URL sans titres ne
    suffisent pas pour une détection de noms.
    """
    results = {}

    def walk(value, depth=0):
        if depth > 20:
            return

        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
            return

        if not isinstance(value, dict):
            return

        title = None
        url = None

        for key in (
            "title", "titre",
            "headline", "titre_article"
        ):
            item = value.get(key)

            if isinstance(item, str) and item.strip():
                title = item.strip()
                break

        for key in (
            "url", "link", "lien",
            "article_url"
        ):
            item = value.get(key)

            if isinstance(item, str) and item.strip():
                url = item.strip()
                break

        if title and url and official_url(url):
            results[url] = {
                "title": title,
                "url": url
            }

        for item in value.values():
            if isinstance(item, (dict, list)):
                walk(item, depth + 1)

    walk(data)

    return list(results.values())


def load_all_articles():
    """
    Charge tous les fichiers historiques connus.
    Aucun plafond artificiel de 100 articles.
    """
    all_articles = {}
    statistics = {}

    for filename in NEWS_FILES:
        path = DATA / filename

        if not path.exists():
            statistics[filename] = {
                "exists": False,
                "articles": 0
            }
            continue

        content = load_json(path)
        articles = collect_articles(content)

        statistics[filename] = {
            "exists": True,
            "articles": len(articles)
        }

        for article in articles:
            all_articles[article["url"]] = article

    return list(all_articles.values()), statistics


def fetch_pokeapi():
    request = Request(
        POKEAPI_URL,
        headers={
            "User-Agent": "PokedexAcetique/6.1",
            "Accept": "application/json",
        }
    )

    with urlopen(
        request,
        timeout=25
    ) as response:
        return json.load(response)


def collect_known_names(data):
    names = set()

    def walk(value, depth=0):
        if depth > 20:
            return

        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
            return

        if not isinstance(value, dict):
            return

        # Structure PokéAPI.
        if (
            isinstance(value.get("name"), str)
            and isinstance(value.get("url"), str)
            and "pokemon-species" in value["url"]
        ):
            names.add(normalize(value["name"]))

        # Noms bilingues.
        if value.get("provisional") is not True:
            for key in (
                "fr", "en",
                "french", "english",
                "nom_fr", "nom_en",
                "name_fr", "name_en"
            ):
                name = value.get(key)

                if isinstance(name, str):
                    names.add(normalize(name))

        # Noms officiels par langue.
        entries = value.get("names")

        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                language = entry.get("language")

                if isinstance(language, dict):
                    language = language.get("name")

                if language in ("fr", "en"):
                    name = entry.get("name")

                    if isinstance(name, str):
                        names.add(normalize(name))

        for item in value.values():
            if isinstance(item, (dict, list)):
                walk(item, depth + 1)

    walk(data)

    names.discard("")

    return names


def load_known_species():
    names = set()

    names.update(
        collect_known_names(
            load_json(POKEAPI_CACHE, {})
        )
    )

    names.update(
        collect_known_names(
            load_json(BILINGUAL_NAMES, {})
        )
    )

    source = "cache local"

    try:
        response = fetch_pokeapi()

        api_names = {
            normalize(item["name"])
            for item in response.get(
                "results", []
            )
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
        }

        if api_names:
            names.update(api_names)
            source = "PokéAPI + cache local"

    except Exception as error:
        print(
            "[V6.1] PokéAPI indisponible :",
            error
        )

    return names, source


def load_validations():
    raw = load_json(VALIDATIONS, {})

    if not isinstance(raw, dict):
        return {}

    entries = raw.get("validations", raw)

    if not isinstance(entries, dict):
        return {}

    result = {}

    for name, entry in entries.items():
        if isinstance(entry, dict):
            status = entry.get("status", "")
        else:
            status = entry

        status = normalize(status)

        if status in (
            "valide",
            "validemanuellement",
            "confirme",
            "approved",
            "validated"
        ):
            result[normalize(name)] = "valide"

        elif status in (
            "rejete",
            "rejected",
            "refuse"
        ):
            result[normalize(name)] = "rejete"

    return result


def excluded_context(title):
    return any(
        re.search(
            pattern,
            title,
            flags=re.I
        )
        for pattern in EXCLUDED_CONTEXTS
    )


def extract_names(title):
    results = {}

    title = re.sub(
        r"\s+",
        " ",
        str(title).replace("’", "'")
    ).strip()

    for score, reason, pattern in PATTERNS:
        for match in re.finditer(
            pattern,
            title,
            flags=re.I
        ):
            name = match.group(1).strip(
                " ,.:;!?-"
            )

            key = normalize(name)

            if not key:
                continue

            if len(key) < 3:
                continue

            if key in EXCLUDED_NAMES:
                continue

            if key not in results:
                results[key] = (
                    name, score, reason
                )

            elif score > results[key][1]:
                results[key] = (
                    name, score, reason
                )

    return list(results.values())


def load_previous():
    raw = load_json(OUTPUT, {})

    if not isinstance(raw, dict):
        return {}

    result = {}

    for item in raw.get("candidates", []):
        if not isinstance(item, dict):
            continue

        name = item.get("name", "")

        if name:
            result[normalize(name)] = item

    return result


def detect():
    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 50)
    print("POKEDEX ACETIQUE")
    print("DÉTECTION ANTICIPÉE V6.1")
    print("=" * 50)

    articles, file_stats = load_all_articles()

    print("")
    print("SOURCES D'ANNONCES :")

    for filename, stats in file_stats.items():
        state = (
            "OK"
            if stats["exists"]
            else "ABSENT"
        )

        print(
            f"- {filename} : "
            f"{stats['articles']} articles "
            f"({state})"
        )

    print("")
    print(
        "[V6.1] Articles uniques :",
        len(articles)
    )

    if not articles:
        print(
            "[V6.1] ERREUR : aucune annonce "
            "officielle exploitable."
        )
        return 1

    known, known_source = load_known_species()

    print(
        "[V6.1] Noms connus :",
        len(known)
    )

    print(
        "[V6.1] Source espèces :",
        known_source
    )

    if len(known) < 1000:
        print(
            "[V6.1] ERREUR : référence "
            "des espèces incomplète."
        )
        return 1

    validations = load_validations()
    previous = load_previous()

    detected = defaultdict(
        lambda: {
            "name": "",
            "score": 0,
            "reason": "",
            "sources": [],
        }
    )

    excluded_articles = 0
    matches_count = 0
    known_matches = 0
    rejected_matches = 0

    for article in articles:
        title = article["title"]
        url = article["url"]

        if excluded_context(title):
            excluded_articles += 1
            continue

        matches = extract_names(title)

        for name, score, reason in matches:
            matches_count += 1
            key = normalize(name)

            if key in known:
                known_matches += 1
                continue

            if validations.get(key) == "rejete":
                rejected_matches += 1
                continue

            candidate = detected[key]

            candidate["name"] = name

            if score > candidate["score"]:
                candidate["score"] = score
                candidate["reason"] = reason

            if not any(
                source["url"] == url
                for source in candidate["sources"]
            ):
                candidate["sources"].append({
                    "title": title,
                    "url": url
                })

    candidates = []

    for key, candidate in detected.items():
        previous_candidate = previous.get(
            key, {}
        )

        status = (
            "valide_manuellement"
            if validations.get(key) == "valide"
            else "a_verifier"
        )

        sources_count = len(
            candidate["sources"]
        )

        score = min(
            95,
            candidate["score"]
            + min(
                max(sources_count - 1, 0) * 3,
                9
            )
        )

        candidates.append({
            "name": candidate["name"],
            "status": status,
            "score": score,
            "reason": candidate["reason"],
            "first_detected": (
                previous_candidate.get(
                    "first_detected",
                    timestamp()
                )
            ),
            "already_in_site_provisionally": (
                key in PROVISIONAL
            ),
            "verified_by_pokeapi": False,
            "sources": candidate["sources"],
        })

    candidates.sort(
        key=lambda item: (
            -item["score"],
            item["name"].lower()
        )
    )

    pending = sum(
        item["status"] == "a_verifier"
        for item in candidates
    )

    validated = sum(
        item["status"] == "valide_manuellement"
        for item in candidates
    )

    old_false_positives = sorted(
        previous[key].get("name", key)
        for key in previous
        if key not in detected
    )

    checked_at = timestamp()

    output = {
        "version": VERSION,
        "checked_at": checked_at,
        "method": (
            "historical_official_titles_"
            "contextual_detection"
        ),
        "known_species_count": len(known),
        "articles_analyzed": len(articles),
        "candidate_count": len(candidates),
        "pending_review_count": pending,
        "rejected_count": sum(
            value == "rejete"
            for value in validations.values()
        ),
        "manually_validated_count": validated,
        "candidates": candidates,
        "notice": (
            "Candidats non confirmés. "
            "Aucun ajout automatique au Pokédex."
        )
    }

    report = {
        "version": VERSION,
        "checked_at": checked_at,
        "sources": file_stats,
        "articles_analyzed": len(articles),
        "excluded_product_event_articles": (
            excluded_articles
        ),
        "pattern_matches": matches_count,
        "existing_species_matches": known_matches,
        "rejected_matches": rejected_matches,
        "candidate_count": len(candidates),
        "pending_review_count": pending,
        "validated_count": validated,
        "reference_source": known_source,
        "excluded_old_false_positives": (
            old_false_positives
        ),
    }

    save_json(OUTPUT, output)
    save_json(REPORT, report)

    print("")
    print("=" * 50)
    print("RÉSULTATS V6.1")
    print("=" * 50)

    print(
        "Articles analysés :",
        len(articles)
    )

    print(
        "Articles exclus par contexte :",
        excluded_articles
    )

    print(
        "Correspondances détectées :",
        matches_count
    )

    print(
        "Espèces déjà connues exclues :",
        known_matches
    )

    print(
        "Candidats potentiels :",
        len(candidates)
    )

    print(
        "En attente de vérification :",
        pending
    )

    print(
        "Validés manuellement :",
        validated
    )

    print("")
    print("CANDIDATS :")

    if not candidates:
        print(
            "Aucun nouveau Pokémon potentiel "
            "détecté."
        )

    for candidate in candidates:
        print(
            f"- {candidate['name']} | "
            f"score={candidate['score']} | "
            f"{candidate['status']}"
        )

    print("")
    print(
        "[V6.1] Rapport :",
        REPORT
    )

    print(
        "[V6.1] Résultats :",
        OUTPUT
    )

    print(
        "[V6.1] Aucun Pokémon ajouté "
        "automatiquement."
    )

    return 0


def run_tests():
    false_positives = [
        "A New Pokemon Animated Series Is Coming",
        "New Pokemon Home Update",
        "Watch A New Pokemon Presents",
        "Memorable Moments From New Pokemon Snap",
        "Check Out New Pokémon League Prizes",
        "Meet The Winners Of The Championships",
        "Discover The Beauty Of Pokemon TCG",
        "New Pokemon Primer Books",
        "New Pokemon Trading Card Game",
        "Stern Pinballs New Pokemon Pinball Machine",
        "Meet The Top 300 Artists",
        "Discover Plush Pokemon Friends",
        "New Pokemon Fundamentals School Supplies",
    ]

    for title in false_positives:
        if excluded_context(title):
            continue

        assert not extract_names(title), (
            f"Faux positif : {title}"
        )

    positive_tests = [
        (
            "Meet the new Pokemon named Testmon",
            "testmon"
        ),
        (
            "Introducing the new Pokemon called Novamon",
            "novamon"
        ),
        (
            "New Pokemon species named Floramon",
            "floramon"
        ),
        (
            "Meet the new Pokemon Lunamon!",
            "lunamon"
        ),
        (
            "Meet Aquamon, a new Pokemon",
            "aquamon"
        ),
    ]

    for title, expected in positive_tests:
        names = {
            normalize(item[0])
            for item in extract_names(title)
        }

        assert expected in names, (
            f"Détection manquée : {title}"
        )

    # Vérification du dédoublonnage.
    example = [
        {
            "title": "Meet the new Pokemon Testmon!",
            "url": (
                "https://www.pokemon.com/"
                "us/news/testmon"
            )
        }
    ]

    assert len(
        collect_articles(example + example)
    ) == 1

    # Vérification du domaine officiel.
    assert not official_url(
        "https://pokemon.com.example.org/fake"
    )

    print("=" * 50)
    print("TESTS AUTOMATIQUES V6.1")
    print("=" * 50)
    print("Faux positifs : OK")
    print("Détection de noms fictifs : OK")
    print("Dédoublonnage : OK")
    print("Vérification du domaine : OK")
    print("")
    print("TOUS LES TESTS SONT RÉUSSIS")

    return 0


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test",
        action="store_true",
        help="Exécuter les tests automatiques"
    )

    args = parser.parse_args()

    if args.test:
        return run_tests()

    return detect()


if __name__ == "__main__":
    sys.exit(main())
