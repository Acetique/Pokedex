
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX ACETIQUE V6.0
Détection anticipée intelligente des nouveaux Pokémon.

Fonctions :
- Analyse les titres des annonces officielles collectées.
- Détecte les noms potentiels de nouvelles espèces.
- Élimine les faux positifs liés aux produits, jeux et événements.
- Compare les noms avec PokéAPI.
- Conserve les validations manuelles.
- Nettoie les faux positifs historiques.
- Ne modifie jamais le catalogue principal.
- Fonctionne sans bibliothèque Python externe.

Entrées :
  data/nouveautes-pokemon.json
  data/annonces-prioritaires.json
  data/pokeapi-cache.json
  data/validation-pokemon.json (facultatif)

Sorties :
  data/pokemon-a-verifier.json
  data/rapport-detection-v6.json

Exécution :
  python detecter_nouveaux_pokemon.py
"""

import json
import re
import sys
import unicodedata

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


VERSION = "6.0"

DATA = Path("data")

NEWS_FILE = DATA / "nouveautes-pokemon.json"
PRIORITY_FILE = DATA / "annonces-prioritaires.json"
CACHE_FILE = DATA / "pokeapi-cache.json"

VALIDATION_FILE = DATA / "validation-pokemon.json"

OUTPUT_FILE = DATA / "pokemon-a-verifier.json"
REPORT_FILE = DATA / "rapport-detection-v6.json"

OLD_OUTPUT_FILE = OUTPUT_FILE

POKEAPI_URL = (
    "https://pokeapi.co/api/v2/"
    "pokemon-species?limit=2000"
)

TIMEOUT = 20

# Noms provisoires déjà présents dans le site.
# Ils peuvent être signalés comme déjà affichés,
# mais jamais considérés comme validés par PokéAPI.
PROVISIONAL_NAMES = {
    "browt",
    "pombon",
    "gecqua",
}

# Termes qui ne désignent pas une nouvelle espèce.
EXCLUDED_WORDS = {
    "animated", "animation", "anime",
    "app", "apps",
    "battle", "battles",
    "beauty",
    "book", "books",
    "card", "cards",
    "center",
    "champion", "champions",
    "championship", "championships",
    "collection", "collections",
    "contest", "contests",
    "day",
    "direct",
    "event", "events",
    "expansion", "expansions",
    "festival",
    "friends",
    "fundamentals",
    "game", "games",
    "gallery",
    "gift", "gifts",
    "guide",
    "home",
    "illustration",
    "league",
    "legends",
    "live",
    "machine",
    "movie",
    "news",
    "pack", "packs",
    "paldea",
    "perfect",
    "pinball",
    "plush",
    "presents",
    "primer", "primers",
    "prize", "prizes",
    "product", "products",
    "region", "regions",
    "release",
    "series",
    "sinnoh", "sinnohs",
    "snap",
    "store",
    "supplies",
    "tcg",
    "top",
    "trading",
    "trailer",
    "update", "updates",
    "video", "videos",
    "winner", "winners",
    "world", "worlds",
}

# Articles qui présentent généralement un produit,
# un événement ou une activité plutôt qu'une espèce.
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

# Ces expressions sont volontairement précises.
# On ne considère PAS "New Pokémon X" comme une
# preuve suffisante, car X peut être un produit.
DETECTION_PATTERNS = [
    (
        90,
        "Présentation explicite d'une nouvelle espèce",
        r"\b(?:meet|introducing|discover|revealing|"
        r"revealed|introduce)\s+"
        r"(?:the\s+)?(?:brand[\s-]+)?new\s+"
        r"pokemon\s+(?:named|called)\s+"
        r"([A-Za-z][A-Za-z'-]{2,24})\b",
    ),
    (
        90,
        "Nom présenté comme nouveau Pokémon",
        r"\bnew\s+pokemon\s+"
        r"(?:named|called)\s+"
        r"([A-Za-z][A-Za-z'-]{2,24})\b",
    ),
    (
        85,
        "Nouvelle espèce nommée",
        r"\bnew\s+pokemon\s+species\s+"
        r"(?:named|called)\s+"
        r"([A-Za-z][A-Za-z'-]{2,24})\b",
    ),
    (
        85,
        "Nouvelle espèce révélée",
        r"\b([A-Za-z][A-Za-z'-]{2,24})\s+"
        r"(?:is|has\s+been)\s+"
        r"(?:officially\s+)?revealed\s+"
        r"as\s+a\s+new\s+pokemon\b",
    ),
    (
        80,
        "Présentation d'un nouveau Pokémon",
        r"\b(?:meet|introducing)\s+"
        r"([A-Za-z][A-Za-z'-]{2,24})\s*"
        r"[,:\-]\s*(?:a|the)\s+"
        r"(?:brand[\s-]+)?new\s+pokemon\b",
    ),
]

# Une mention générique d'un nouveau Pokémon
# sans nom explicite ne produit aucun candidat.


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize(value):
    value = str(value or "").strip().lower()

    value = unicodedata.normalize("NFKD", value)

    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )

    value = value.replace("’", "'")

    return re.sub(
        r"[^a-z0-9]+", "",
        value
    )


def clean_title(value):
    value = str(value or "")

    value = value.replace("’", "'")
    value = value.replace("é", "e")
    value = value.replace("É", "E")

    return re.sub(r"\s+", " ", value).strip()


def load_json(path, default=None):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    except (OSError, ValueError) as error:
        print(
            f"[V6.0] Lecture impossible : "
            f"{path} : {error}"
        )
        return default


def save_json(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )
        file.write("\n")


def fetch_json(url):
    request = Request(
        url,
        headers={
            "User-Agent": (
                "PokedexAcetique/6.0 "
                "(GitHub Actions)"
            ),
            "Accept": "application/json",
        }
    )

    with urlopen(
        request,
        timeout=TIMEOUT
    ) as response:
        return json.load(response)


def collect_articles(obj):
    """
    Recherche les articles dans les structures JSON
    courantes sans supposer un format unique.

    Une annonce doit contenir :
    - un titre
    - une URL officielle pokemon.com

    On évite ainsi de traiter des chaînes arbitraires
    comme des annonces.
    """
    found = []

    def walk(value, depth=0):
        if depth > 12:
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
            "headline", "name"
        ):
            candidate = value.get(key)

            if isinstance(candidate, str):
                title = candidate.strip()
                if title:
                    break

        for key in (
            "url", "link", "lien"
        ):
            candidate = value.get(key)

            if isinstance(candidate, str):
                url = candidate.strip()
                if url:
                    break

        if title and url:
            if re.match(
                r"^https?://(?:www\.)?"
                r"pokemon\.com/",
                url,
                flags=re.I
            ):
                found.append({
                    "title": title,
                    "url": url,
                })

        for item in value.values():
            if isinstance(item, (dict, list)):
                walk(item, depth + 1)

    walk(obj)

    unique = {}

    for article in found:
        unique[article["url"]] = article

    return list(unique.values())


def load_articles():
    articles = {}

    for path in (
        NEWS_FILE,
        PRIORITY_FILE,
    ):
        data = load_json(path)

        if data is None:
            continue

        for article in collect_articles(data):
            articles[article["url"]] = article

    return list(articles.values())


def collect_known_names(data):
    """
    Extrait les noms de Pokémon de plusieurs
    structures JSON possibles.

    Le cache V5.8 peut avoir une structure
    différente selon la version utilisée.
    """
    known = set()

    def walk(value, depth=0):
        if depth > 12:
            return

        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
            return

        if not isinstance(value, dict):
            return

        # Noms sous forme de listes de traductions.
        names = value.get("names")

        if isinstance(names, list):
            for entry in names:
                if not isinstance(entry, dict):
                    continue

                name = entry.get("name")
                language = entry.get("language")

                if isinstance(language, dict):
                    language = language.get("name")

                if (
                    isinstance(name, str)
                    and language in ("en", "fr")
                ):
                    known.add(normalize(name))

        # Structure PokéAPI species.
        if (
            isinstance(value.get("name"), str)
            and (
                isinstance(value.get("url"), str)
                and "pokemon-species" in value["url"]
            )
        ):
            known.add(normalize(value["name"]))

        for item in value.values():
            if isinstance(item, (dict, list)):
                walk(item, depth + 1)

    walk(data)

    return known


def get_known_species():
    """
    PokéAPI est la source de référence.

    Le cache local est utilisé en secours si
    PokéAPI n'est pas accessible.
    """
    cached = load_json(CACHE_FILE, {})

    known = collect_known_names(cached)

    source = "cache"

    try:
        data = fetch_json(POKEAPI_URL)

        results = data.get("results", [])

        api_names = {
            normalize(item.get("name"))
            for item in results
            if isinstance(item, dict)
            and item.get("name")
        }

        if api_names:
            known.update(api_names)
            source = "pokeapi"

    except (
        URLError,
        HTTPError,
        TimeoutError,
        ValueError,
        OSError
    ) as error:
        print(
            "[V6.0] PokéAPI indisponible : "
            f"{error}"
        )

    # Ajout éventuel des noms FR/EN locaux.
    local_names = load_json(
        DATA / "noms-pokemon-fr.json",
        {}
    )

    known.update(
        collect_local_bilingual_names(local_names)
    )

    return known, source


def collect_local_bilingual_names(data):
    known = set()

    def walk(value, depth=0):
        if depth > 12:
            return

        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
            return

        if not isinstance(value, dict):
            return

        # Ne pas traiter les noms provisoires
        # comme des espèces officielles.
        if value.get("provisional") is True:
            return

        for key in (
            "fr", "en",
            "french", "english",
            "nom_fr", "nom_en",
            "name_fr", "name_en"
        ):
            name = value.get(key)

            if isinstance(name, str) and name.strip():
                known.add(normalize(name))

        for item in value.values():
            if isinstance(item, (dict, list)):
                walk(item, depth + 1)

    walk(data)

    return known


def get_validations():
    """
    Accepte deux formats :

    {
      "validations": {
        "Nom": "valide"
      }
    }

    ou

    {
      "Nom": "rejete"
    }

    Valeurs reconnues :
    valide, valide_manuellement, confirme,
    rejete, rejected.
    """
    raw = load_json(VALIDATION_FILE, {})

    if not isinstance(raw, dict):
        return {}

    validations = raw.get("validations", raw)

    if not isinstance(validations, dict):
        return {}

    result = {}

    for name, entry in validations.items():
        if isinstance(entry, str):
            status = entry

        elif isinstance(entry, dict):
            status = entry.get("status", "")

        else:
            continue

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


def is_excluded_context(title):
    lower = clean_title(title).lower()

    return any(
        re.search(pattern, lower)
        for pattern in EXCLUDED_CONTEXTS
    )


def extract_candidates(title):
    """
    Extrait uniquement les noms dans des
    formulations suffisamment explicites.

    Renvoie :
      [(nom, score, raison), ...]
    """
    cleaned = clean_title(title)

    results = []

    for score, reason, pattern in DETECTION_PATTERNS:
        matches = re.finditer(
            pattern,
            cleaned,
            flags=re.I
        )

        for match in matches:
            name = match.group(1).strip(
                ".,:;!?- "
            )

            normalized = normalize(name)

            if not normalized:
                continue

            if normalized in EXCLUDED_WORDS:
                continue

            if len(normalized) < 3:
                continue

            if normalized.isdigit():
                continue

            results.append((
                name,
                score,
                reason
            ))

    unique = {}

    for name, score, reason in results:
        key = normalize(name)

        if (
            key not in unique
            or score > unique[key][1]
        ):
            unique[key] = (
                name,
                score,
                reason
            )

    return list(unique.values())


def load_previous_candidates():
    previous = load_json(
        OLD_OUTPUT_FILE,
        {}
    )

    if not isinstance(previous, dict):
        return {}

    candidates = previous.get(
        "candidates",
        []
    )

    if not isinstance(candidates, list):
        return {}

    result = {}

    for item in candidates:
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

    print("=" * 48)
    print("POKEDEX ACETIQUE")
    print("DÉTECTION ANTICIPÉE V6.0")
    print("=" * 48)

    articles = load_articles()

    print(
        f"[V6.0] Articles chargés : "
        f"{len(articles)}"
    )

    if not articles:
        print(
            "[V6.0] ERREUR : aucune annonce "
            "officielle disponible."
        )
        return 1

    known, source = get_known_species()

    print(
        f"[V6.0] Noms connus : "
        f"{len(known)}"
    )

    print(
        f"[V6.0] Source espèces : {source}"
    )

    if len(known) < 1000:
        print(
            "[V6.0] ERREUR : catalogue "
            "de référence incomplet."
        )
        return 1

    validations = get_validations()

    previous = load_previous_candidates()

    detected = defaultdict(
        lambda: {
            "name": "",
            "score": 0,
            "reason": "",
            "sources": [],
        }
    )

    excluded_context_count = 0
    existing_species_count = 0
    pattern_matches = 0

    for article in articles:
        title = article["title"]
        url = article["url"]

        # Bloque les articles clairement consacrés
        # à des produits ou événements.
        if is_excluded_context(title):
            excluded_context_count += 1
            continue

        matches = extract_candidates(title)

        for name, score, reason in matches:
            pattern_matches += 1

            key = normalize(name)

            if key in known:
                existing_species_count += 1
                continue

            if validations.get(key) == "rejete":
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

    for key, item in detected.items():
        old = previous.get(key, {})

        manual_status = validations.get(key)

        if manual_status == "valide":
            status = "valide_manuellement"
        else:
            status = "a_verifier"

        # Plusieurs sources indépendantes augmentent
        # légèrement la confiance, sans valider
        # automatiquement l'espèce.
        source_count = len(item["sources"])

        score = min(
            95,
            item["score"]
            + min(
                max(source_count - 1, 0) * 3,
                9
            )
        )

        candidates.append({
            "name": item["name"],
            "status": status,
            "score": score,
            "reason": item["reason"],
            "first_detected": old.get(
                "first_detected",
                now_iso()
            ),
            "already_in_site_provisionally": (
                key in PROVISIONAL_NAMES
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

    pending_count = sum(
        item["status"] == "a_verifier"
        for item in candidates
    )

    validated_count = sum(
        item["status"] == "valide_manuellement"
        for item in candidates
    )

    output = {
        "version": VERSION,
        "checked_at": now_iso(),
        "method": (
            "official_explicit_species_patterns"
            "_with_context_filters"
        ),
        "known_species_count": len(known),
        "articles_analyzed": len(articles),
        "candidate_count": len(candidates),
        "pending_review_count": pending_count,
        "rejected_count": sum(
            status == "rejete"
            for status in validations.values()
        ),
        "manually_validated_count": validated_count,
        "candidates": candidates,
        "notice": (
            "Candidats non confirmés. "
            "Aucun ajout automatique au Pokédex."
        )
    }

    report = {
        "version": VERSION,
        "checked_at": output["checked_at"],
        "articles_analyzed": len(articles),
        "excluded_product_event_articles": (
            excluded_context_count
        ),
        "pattern_matches": pattern_matches,
        "existing_species_matches": (
            existing_species_count
        ),
        "candidate_count": len(candidates),
        "pending_review_count": pending_count,
        "validated_count": validated_count,
        "reference_source": source,
        "excluded_old_false_positives": sorted(
            [
                old["name"]
                for key, old in previous.items()
                if key not in detected
                and isinstance(
                    old.get("name"),
                    str
                )
            ]
        ),
    }

    save_json(
        OUTPUT_FILE,
        output
    )

    save_json(
        REPORT_FILE,
        report
    )

    print("")
    print("=" * 48)
    print("RÉSULTATS V6.0")
    print("=" * 48)

    print(
        "Articles analysés :",
        len(articles)
    )

    print(
        "Articles exclus par contexte :",
        excluded_context_count
    )

    print(
        "Correspondances détectées :",
        pattern_matches
    )

    print(
        "Espèces déjà connues exclues :",
        existing_species_count
    )

    print(
        "Nouveaux candidats :",
        len(candidates)
    )

    print(
        "En attente de vérification :",
        pending_count
    )

    print(
        "Validés manuellement :",
        validated_count
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
        "[V6.0] Rapport :",
        REPORT_FILE
    )

    print(
        "[V6.0] Résultats :",
        OUTPUT_FILE
    )

    print(
        "[V6.0] Aucun Pokémon ajouté "
        "automatiquement."
    )

    print("=" * 48)

    return 0


def run_tests():
    """
    Tests internes sans accès Internet.

    Vérifie notamment les faux positifs
    observés dans la V5.9.
    """
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
    ]

    for title in false_positives:
        if is_excluded_context(title):
            continue

        matches = extract_candidates(title)

        assert not matches, (
            f"Faux positif détecté : {title} "
            f"-> {matches}"
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
    ]

    for title, expected in positive_tests:
        matches = extract_candidates(title)

        names = {
            normalize(item[0])
            for item in matches
        }

        assert expected in names, (
            f"Détection manquée : {title}"
        )

    print(
        "[V6.0] TESTS RÉUSSIS : "
        "faux positifs exclus et "
        "nouveaux noms détectés."
    )

    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(run_tests())

    sys.exit(detect())
