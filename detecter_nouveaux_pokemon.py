
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX ACETIQUE V6.2
Détection anticipée intelligente PRO.

Fonctions :
- Analyse les annonces officielles actuelles et historiques.
- Détecte plusieurs noms de Pokémon dans une annonce.
- Reconnaît les annonces de présentation et de révélation.
- Écarte les noms déjà présents dans PokéAPI.
- Distingue les noms provisoires déjà présents sur le site.
- Filtre les produits, jeux et événements.
- Classe les candidats FORT / MOYEN / FAIBLE.
- Journalise les annonces potentiellement manquées.
- Préserve les décisions de validation manuelle.
- Ne modifie jamais le catalogue principal.

Aucune dépendance Python externe.

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


VERSION = "6.2"
DATA = Path("data")

OUTPUT = DATA / "pokemon-a-verifier.json"
REPORT = DATA / "rapport-detection-v6.json"
MISSED = DATA / "annonces-non-reconnues.json"

VALIDATIONS = DATA / "validation-pokemon.json"
CACHE = DATA / "pokeapi-cache.json"
BILINGUAL = DATA / "noms-pokemon-fr.json"

NEWS_FILES = [
    "nouveautes-pokemon.json",
    "annonces-prioritaires.json",
    "historique-actualites.json",
    "official-news-review.json",
]

POKEAPI_URL = (
    "https://pokeapi.co/api/v2/"
    "pokemon-species?limit=2000"
)

PROVISIONAL = {
    "browt",
    "pombon",
    "gecqua",
}

# Termes qui ne constituent pas des noms de Pokémon.
STOPWORDS = {
    "a", "an", "and", "are", "at",
    "available", "battle", "battles",
    "beauty", "best", "book", "books",
    "card", "cards", "center",
    "champion", "champions",
    "championship", "championships",
    "collection", "collections",
    "contest", "contests",
    "day", "direct", "event", "events",
    "expansion", "expansions",
    "festival", "first", "friends",
    "fundamentals", "game", "games",
    "gallery", "gift", "gifts",
    "guide", "home", "illustration",
    "league", "legends", "live",
    "machine", "movie", "news",
    "new", "now", "of", "on",
    "pack", "packs", "paldea",
    "perfect", "pinball", "plush",
    "presents", "primer", "primers",
    "prize", "prizes", "product",
    "products", "region", "regions",
    "release", "series",
    "sinnoh", "sinnohs",
    "snap", "store", "supplies",
    "tcg", "the", "these", "this",
    "those", "top", "trading",
    "trailer", "update", "updates",
    "video", "videos",
    "winner", "winners",
    "world", "worlds",
}

# Contextes qui désignent généralement un produit
# ou un événement et non une nouvelle espèce.
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

# Expressions précises indiquant qu'un nom est
# présenté explicitement comme une nouvelle espèce.
STRONG_PATTERNS = [
    (
        95,
        "Nouvelle espèce explicitement nommée",
        r"\bnew\s+pokemon\s+species\s+"
        r"(?:named|called)\s+"
        r"(?P<names>[A-Za-z][A-Za-z'-]{2,24}"
        r"(?:\s*,\s*[A-Za-z][A-Za-z'-]{2,24})*"
        r"(?:\s*,?\s+and\s+"
        r"[A-Za-z][A-Za-z'-]{2,24})?)",
    ),
    (
        90,
        "Nouveau Pokémon nommé",
        r"\b(?:new|brand new)\s+pokemon\s+"
        r"(?:named|called)\s+"
        r"(?P<names>[A-Za-z][A-Za-z'-]{2,24}"
        r"(?:\s*,\s*[A-Za-z][A-Za-z'-]{2,24})*"
        r"(?:\s*,?\s+and\s+"
        r"[A-Za-z][A-Za-z'-]{2,24})?)",
    ),
    (
        90,
        "Présentation officielle explicite",
        r"\b(?:meet|introducing|discover)\s+"
        r"(?:the\s+)?(?:brand\s+)?new\s+"
        r"pokemon\s+(?:named|called)\s+"
        r"(?P<names>[A-Za-z][A-Za-z'-]{2,24}"
        r"(?:\s*,\s*[A-Za-z][A-Za-z'-]{2,24})*"
        r"(?:\s*,?\s+and\s+"
        r"[A-Za-z][A-Za-z'-]{2,24})?)",
    ),
    (
        85,
        "Nouvelle espèce révélée",
        r"\b(?P<names>[A-Za-z][A-Za-z'-]{2,24})"
        r"\s+(?:is|has been)\s+"
        r"(?:officially\s+)?revealed\s+"
        r"as\s+a\s+new\s+pokemon\b",
    ),
]

# Expressions plus souples :
# les noms sont retenus comme candidats
# à examiner, pas comme espèces confirmées.
MEDIUM_PATTERNS = [
    (
        78,
        "Présentation de nouveaux Pokémon",
        r"\b(?:meet|discover|introducing)\s+"
        r"(?:the\s+)?new\s+pokemon\s+"
        r"(?P<names>[A-Za-z][A-Za-z'-]{2,24}"
        r"(?:\s*,\s*[A-Za-z][A-Za-z'-]{2,24})*"
        r"(?:\s*,?\s+and\s+"
        r"[A-Za-z][A-Za-z'-]{2,24})?)",
    ),
    (
        75,
        "Présentation d'une nouvelle espèce",
        r"\b(?:meet|introducing|discover)\s+"
        r"(?P<names>[A-Za-z][A-Za-z'-]{2,24})"
        r"\s*[,:\-]\s*(?:a|an)\s+"
        r"(?:brand\s+)?new\s+pokemon\b",
    ),
    (
        72,
        "Noms annoncés comme nouveaux Pokémon",
        r"\b(?P<names>[A-Za-z][A-Za-z'-]{2,24}"
        r"(?:\s*,\s*[A-Za-z][A-Za-z'-]{2,24})*"
        r"(?:\s*,?\s+and\s+"
        r"[A-Za-z][A-Za-z'-]{2,24})?)"
        r"\s+(?:are|have been)\s+"
        r"revealed\s+as\s+new\s+pokemon\b",
    ),
]

# Titres potentiellement intéressants,
# même si aucun nom n'a été extrait.
REVIEW_PATTERNS = [
    r"\bnew\s+pokemon\b",
    r"\bnewly\s+discovered\s+pokemon\b",
    r"\bnew\s+pokemon\s+species\b",
    r"\bpokemon\s+revealed\b",
    r"\bintroducing\s+.*pokemon\b",
    r"\bmeet\s+.*pokemon\b",
    r"\bdiscover\s+.*pokemon\b",
    r"\breveal(?:ed|s)?\s+.*pokemon\b",
]


def now_iso():
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


def read_json(path, default=None):
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
            f"[V6.2] Erreur lecture {path}: {error}"
        )
        return default


def write_json(path, content):
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
            ensure_ascii=False,
            indent=2
        )
        file.write("\n")


def official_url(url):
    try:
        parsed = urlparse(url)

        return (
            parsed.scheme in ("http", "https")
            and (parsed.hostname or "").lower()
            in ("pokemon.com", "www.pokemon.com")
        )

    except (ValueError, TypeError):
        return False


def collect_articles(data):
    found = {}

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
            found[url] = {
                "title": title,
                "url": url
            }

        for item in value.values():
            if isinstance(item, (dict, list)):
                walk(item, depth + 1)

    walk(data)

    return list(found.values())


def load_articles():
    articles = {}
    statistics = {}

    for filename in NEWS_FILES:
        path = DATA / filename

        if not path.exists():
            statistics[filename] = {
                "exists": False,
                "articles": 0,
            }
            continue

        source = read_json(path)
        items = collect_articles(source)

        statistics[filename] = {
            "exists": True,
            "articles": len(items),
        }

        for item in items:
            articles[item["url"]] = item

    return list(articles.values()), statistics


def fetch_species():
    request = Request(
        POKEAPI_URL,
        headers={
            "User-Agent": "PokedexAcetique/6.2",
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

        if value.get("provisional") is True:
            return

        # Réponse PokéAPI.
        if (
            isinstance(value.get("name"), str)
            and isinstance(value.get("url"), str)
            and "pokemon-species" in value["url"]
        ):
            names.add(normalize(value["name"]))

        # Noms bilingues locaux.
        for key in (
            "fr", "en",
            "french", "english",
            "nom_fr", "nom_en",
            "name_fr", "name_en"
        ):
            item = value.get(key)

            if isinstance(item, str):
                names.add(normalize(item))

        # Traductions au format PokéAPI.
        translations = value.get("names")

        if isinstance(translations, list):
            for translation in translations:
                if not isinstance(translation, dict):
                    continue

                language = translation.get("language")

                if isinstance(language, dict):
                    language = language.get("name")

                if language in ("en", "fr"):
                    name = translation.get("name")

                    if isinstance(name, str):
                        names.add(normalize(name))

        for item in value.values():
            if isinstance(item, (list, dict)):
                walk(item, depth + 1)

    walk(data)
    names.discard("")

    return names


def load_known_species():
    names = set()

    names.update(
        collect_known_names(
            read_json(CACHE, {})
        )
    )

    names.update(
        collect_known_names(
            read_json(BILINGUAL, {})
        )
    )

    source = "cache local"

    try:
        response = fetch_species()

        for item in response.get("results", []):
            if isinstance(item, dict):
                name = item.get("name")

                if name:
                    names.add(normalize(name))

        source = "PokéAPI + cache local"

    except Exception as error:
        print(
            "[V6.2] PokéAPI indisponible :",
            error
        )

    return names, source


def load_validations():
    raw = read_json(VALIDATIONS, {})

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
            "valide", "validemanuellement",
            "confirme", "approved", "validated"
        ):
            result[normalize(name)] = "valide"

        elif status in (
            "rejete", "rejected", "refuse"
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


def split_names(text):
    """
    Sépare les noms :
      Browt, Pombon and Gecqua

    Ne découpe pas les noms composés arbitrairement.
    """
    text = text.strip(" ,.:;!?-")

    text = re.sub(
        r"\s*,?\s+\band\b\s+",
        ",",
        text,
        flags=re.I
    )

    result = []

    for item in text.split(","):
        name = item.strip()

        if not re.fullmatch(
            r"[A-Za-z][A-Za-z'-]{2,24}",
            name
        ):
            continue

        key = normalize(name)

        if key in STOPWORDS:
            continue

        result.append(name)

    return result


def extract_candidates(title):
    results = {}

    patterns = (
        STRONG_PATTERNS
        + MEDIUM_PATTERNS
    )

    for score, reason, pattern in patterns:
        for match in re.finditer(
            pattern,
            title,
            flags=re.I
        ):
            raw_names = match.group("names")

            for name in split_names(raw_names):
                key = normalize(name)

                if key not in results:
                    results[key] = {
                        "name": name,
                        "score": score,
                        "reason": reason,
                    }

                elif score > results[key]["score"]:
                    results[key] = {
                        "name": name,
                        "score": score,
                        "reason": reason,
                    }

    return list(results.values())


def confidence_level(score):
    if score >= 85:
        return "FORT"

    if score >= 70:
        return "MOYEN"

    return "FAIBLE"


def should_review(title):
    return any(
        re.search(
            pattern,
            title,
            flags=re.I
        )
        for pattern in REVIEW_PATTERNS
    )


def load_previous():
    raw = read_json(OUTPUT, {})

    if not isinstance(raw, dict):
        return {}

    previous = {}

    for item in raw.get("candidates", []):
        if isinstance(item, dict):
            name = item.get("name")

            if name:
                previous[normalize(name)] = item

    return previous


def detect():
    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 52)
    print("POKEDEX ACETIQUE")
    print("DÉTECTION ANTICIPÉE PRO V6.2")
    print("=" * 52)

    articles, sources = load_articles()

    print("")
    print("SOURCES HISTORIQUES :")

    for filename, stats in sources.items():
        print(
            f"- {filename} : "
            f"{stats['articles']} articles"
        )

    print("")
    print(
        "[V6.2] Articles uniques :",
        len(articles)
    )

    if not articles:
        print(
            "[V6.2] ERREUR : "
            "aucune annonce officielle."
        )
        return 1

    known, known_source = load_known_species()

    print(
        "[V6.2] Noms connus :",
        len(known)
    )

    print(
        "[V6.2] Référence :",
        known_source
    )

    if len(known) < 1000:
        print(
            "[V6.2] ERREUR : "
            "référence des espèces incomplète."
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

    missed = []

    excluded = 0
    matches = 0
    existing = 0
    rejected = 0

    for article in articles:
        title = article["title"]
        url = article["url"]

        if excluded_context(title):
            excluded += 1
            continue

        candidates = extract_candidates(title)

        if not candidates and should_review(title):
            missed.append({
                "title": title,
                "url": url,
                "reason": (
                    "Annonce potentiellement pertinente "
                    "sans nom extrait"
                ),
            })

        for item in candidates:
            matches += 1

            name = item["name"]
            key = normalize(name)

            if key in known:
                existing += 1
                continue

            if validations.get(key) == "rejete":
                rejected += 1
                continue

            candidate = detected[key]

            candidate["name"] = name

            if item["score"] > candidate["score"]:
                candidate["score"] = item["score"]
                candidate["reason"] = item["reason"]

            if not any(
                source["url"] == url
                for source in candidate["sources"]
            ):
                candidate["sources"].append({
                    "title": title,
                    "url": url
                })

    candidates = []

    for key, item in detected.items():
        old = previous.get(key, {})

        score = min(
            95,
            item["score"]
            + min(
                max(len(item["sources"]) - 1, 0) * 3,
                9
            )
        )

        status = (
            "valide_manuellement"
            if validations.get(key) == "valide"
            else "a_verifier"
        )

        candidates.append({
            "name": item["name"],
            "status": status,
            "score": score,
            "confidence": confidence_level(score),
            "reason": item["reason"],
            "first_detected": old.get(
                "first_detected",
                now_iso()
            ),
            "already_in_site_provisionally": (
                key in PROVISIONAL
            ),
            "verified_by_pokeapi": False,
            "sources": item["sources"],
        })

    candidates.sort(
        key=lambda item: (
            -item["score"],
            item["name"].lower()
        )
    )

    missed.sort(
        key=lambda item: item["title"].lower()
    )

    pending = sum(
        item["status"] == "a_verifier"
        for item in candidates
    )

    validated = sum(
        item["status"] == "valide_manuellement"
        for item in candidates
    )

    removed = sorted(
        previous[key].get("name", key)
        for key in previous
        if key not in detected
    )

    checked_at = now_iso()

    output = {
        "version": VERSION,
        "checked_at": checked_at,
        "method": (
            "multi_name_official_announcement_"
            "contextual_detection"
        ),
        "known_species_count": len(known),
        "articles_analyzed": len(articles),
        "candidate_count": len(candidates),
        "pending_review_count": pending,
        "manually_validated_count": validated,
        "candidates": candidates,
        "notice": (
            "Aucun candidat n'est ajouté "
            "automatiquement au Pokédex."
        ),
    }

    report = {
        "version": VERSION,
        "checked_at": checked_at,
        "sources": sources,
        "articles_analyzed": len(articles),
        "excluded_product_event_articles": excluded,
        "pattern_matches": matches,
        "existing_species_matches": existing,
        "rejected_matches": rejected,
        "candidate_count": len(candidates),
        "pending_review_count": pending,
        "validated_count": validated,
        "unrecognized_announcements": len(missed),
        "reference_source": known_source,
        "excluded_old_false_positives": removed,
    }

    missed_output = {
        "version": VERSION,
        "checked_at": checked_at,
        "count": len(missed),
        "announcements": missed,
    }

    write_json(OUTPUT, output)
    write_json(REPORT, report)
    write_json(MISSED, missed_output)

    print("")
    print("=" * 52)
    print("RÉSULTATS V6.2")
    print("=" * 52)

    print(
        "Articles analysés :",
        len(articles)
    )

    print(
        "Articles exclus par contexte :",
        excluded
    )

    print(
        "Correspondances détectées :",
        matches
    )

    print(
        "Espèces déjà connues exclues :",
        existing
    )

    print(
        "Nouveaux candidats :",
        len(candidates)
    )

    print(
        "En attente de vérification :",
        pending
    )

    print(
        "Annonces non reconnues :",
        len(missed)
    )

    print("")
    print("CANDIDATS :")

    if not candidates:
        print(
            "Aucun nouveau Pokémon potentiel détecté."
        )

    for item in candidates:
        print(
            f"- {item['name']} | "
            f"{item['confidence']} | "
            f"score={item['score']} | "
            f"{item['status']}"
        )

    print("")
    print(
        "[V6.2] Rapport :",
        REPORT
    )

    print(
        "[V6.2] Annonces non reconnues :",
        MISSED
    )

    print(
        "[V6.2] Candidats :",
        OUTPUT
    )

    print(
        "[V6.2] Aucun ajout automatique "
        "au Pokédex."
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

        assert not extract_candidates(title), (
            f"Faux positif : {title}"
        )

    positive_tests = [
        (
            "Meet the new Pokemon named Testmon",
            {"testmon"}
        ),
        (
            "Introducing the new Pokemon called Novamon",
            {"novamon"}
        ),
        (
            "New Pokemon species named Floramon",
            {"floramon"}
        ),
        (
            "Meet the new Pokemon Lunamon!",
            {"lunamon"}
        ),
        (
            "Meet Aquamon, a new Pokemon",
            {"aquamon"}
        ),
        (
            "Meet the new Pokemon Browt, Pombon and Gecqua",
            {"browt", "pombon", "gecqua"}
        ),
    ]

    for title, expected in positive_tests:
        found = {
            normalize(item["name"])
            for item in extract_candidates(title)
        }

        assert expected.issubset(found), (
            f"Détection manquée : {title} "
            f"Trouvés : {found}"
        )

    assert official_url(
        "https://www.pokemon.com/us/news/test"
    )

    assert not official_url(
        "https://pokemon.com.example.org/fake"
    )

    duplicate = [
        {
            "title": "Meet the new Pokemon Testmon!",
            "url": "https://www.pokemon.com/us/news/test"
        }
    ]

    assert len(
        collect_articles(duplicate + duplicate)
    ) == 1

    print("=" * 52)
    print("TESTS AUTOMATIQUES V6.2")
    print("=" * 52)

    print("Faux positifs historiques : OK")
    print("Détection de noms fictifs : OK")
    print("Détection de plusieurs noms : OK")
    print("Vérification des URL : OK")
    print("Dédoublonnage : OK")

    print("")
    print("TOUS LES TESTS SONT RÉUSSIS")

    return 0


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--test",
        action="store_true",
        help="Lancer les tests automatiques"
    )

    args = parser.parse_args()

    if args.test:
        return run_tests()

    return detect()


if __name__ == "__main__":
    sys.exit(main())
