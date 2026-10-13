
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX V5.1
Détection des nouveaux Pokémon annoncés officiellement.

Fonctions :
1. Actualisation automatique de PokéAPI
2. Mise à jour du catalogue et des générations
3. Préservation des starters provisoires
4. Recherche d'articles sur pokemon.com
5. Analyse des titres et du contenu des articles
6. Détection des annonces de nouvelles espèces
7. Comparaison avec les Pokémon déjà connus
8. Réduction des faux positifs
9. Création de pokemon-a-verifier.json
10. Journalisation des erreurs et diagnostics

Aucune nouvelle espèce n'est ajoutée au catalogue
sans validation des informations officielles.

Compatible avec Python 3.12 et GitHub Actions.
Aucune dépendance externe.
"""

import datetime as dt
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

API = "https://pokeapi.co/api/v2"
OFFICIAL_SITE = "https://www.pokemon.com"
NEWS_URL = OFFICIAL_SITE + "/us/pokemon-news"

HEADERS = {
    "User-Agent": "CommunityPokedex/5.1",
    "Accept": (
        "application/json,text/html,"
        "application/xml,text/xml;q=0.9,*/*;q=0.5"
    ),
}

MAX_ARTICLES = 60
MAX_ARTICLE_FETCHES = 25
MAX_SITEMAPS = 8
REQUEST_DELAY = 0.5

NEWS_MARKERS = (
    "/us/news/",
    "/us/pokemon-news/",
    "/fr/actualites/",
)

# Indices qu'un article pourrait annoncer
# une nouvelle espèce de Pokémon.
ANNOUNCEMENT_PATTERNS = [
    r"\bnew(?:ly)? discovered pok[eé]mon\b",
    r"\bnew pok[eé]mon (?:revealed|discovered|unveiled)\b",
    r"\bmeet (?:the )?new pok[eé]mon\b",
    r"\bintroducing (?:the )?new pok[eé]mon\b",
    r"\bnew species of pok[eé]mon\b",
    r"\bnever.before.seen pok[eé]mon\b",
    r"\bnouveau[x]? pok[eé]mon\b",
    r"\bnouvelle esp[eè]ce de pok[eé]mon\b",
    r"\bd[eé]couvrez (?:les? )?nouveaux pok[eé]mon\b",
    r"\bpok[eé]mon in[eé]dit[s]?\b",
]

# Mots fréquemment présents dans les titres
# qui ne sont pas des noms de Pokémon.
EXCLUDED_WORDS = {
    "Pokemon", "Pokémon", "New", "Meet", "Introducing",
    "Revealed", "Discover", "Discovered", "Official",
    "News", "Update", "Updates", "Game", "Games",
    "Nintendo", "Switch", "Center", "Store",
    "Home", "Community", "Event", "Events",
    "Season", "Series", "Movie", "Movies",
    "Netflix", "Amazon", "Apple", "YouTube",
    "Trading", "Card", "Cards", "TCG",
    "Scarlet", "Violet", "Legends",
    "Pokopia", "Champions", "GO",
    "Version", "Online", "Competition",
    "October", "November", "December",
    "January", "February", "March", "April",
    "May", "June", "July", "August", "September",
    "Today", "Tomorrow", "Learn", "More",
    "Details", "Features", "Available",
    "Coming", "Get", "Your", "Look",
    "Ready", "Night", "Out", "Celebrate",
    "Quality", "Life", "Improvements",
    "Global", "Challenge", "Museum",
    "World", "Space", "Agency",
    "Pokédex", "Pokedex",
}

# Les trois starters ajoutés manuellement
# sont déjà connus par le site.
MANUAL_POKEMON = {
    "browt", "pombon", "gecqua",
    "broussatif", "caloulou", "ogéko",
}


def now():
    return dt.datetime.now(
        dt.timezone.utc
    ).isoformat()


def log(message):
    print(
        "[POKEDEX V5.1] " + str(message),
        flush=True
    )


def save_json(path, value):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    content = json.dumps(
        value,
        ensure_ascii=False,
        indent=2
    ) + "\n"

    if (
        not path.exists()
        or path.read_text(
            encoding="utf-8"
        ) != content
    ):
        path.write_text(
            content,
            encoding="utf-8"
        )


def load_json(path, default=None):
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError):
        return default


def fetch(url, timeout=25):
    request = urllib.request.Request(
        url,
        headers=HEADERS
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout
    ) as response:
        charset = (
            response.headers.get_content_charset()
            or "utf-8"
        )

        return response.read(
            8_000_000
        ).decode(
            charset,
            errors="replace"
        )


def fetch_json(url):
    return json.loads(fetch(url))


def species_id(url):
    match = re.search(
        r"/pokemon-species/(\d+)/?$",
        url
    )

    return (
        int(match.group(1))
        if match else None
    )


def clean_text(value):
    value = html.unescape(
        str(value or "")
    )

    return " ".join(
        value.split()
    )


def official_url(url, base=NEWS_URL):
    if not isinstance(url, str):
        return None

    parsed = urllib.parse.urlparse(
        urllib.parse.urljoin(base, url)
    )

    if parsed.scheme != "https":
        return None

    if parsed.hostname not in (
        "pokemon.com",
        "www.pokemon.com"
    ):
        return None

    return urllib.parse.urlunparse((
        "https",
        "www.pokemon.com",
        parsed.path,
        "",
        "",
        ""
    ))


def is_article(url):
    path = urllib.parse.urlparse(
        url
    ).path.lower()

    if path.rstrip("/") in (
        "/us/pokemon-news",
        "/us/news",
        "/fr/actualites"
    ):
        return False

    return any(
        marker in path
        for marker in NEWS_MARKERS
    )


class ArticleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.links = []
        self.jsonld = []
        self.paragraphs = []
        self.heading = []

        self.current_link = None
        self.link_text = []

        self.in_jsonld = False
        self.jsonld_text = []

        self.in_text = False
        self.text_buffer = []

        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag in ("script", "style", "nav"):
            if tag == "script" and (
                "ld+json" in attrs.get(
                    "type", ""
                ).lower()
            ):
                self.in_jsonld = True
                self.jsonld_text = []
            else:
                self.ignored_depth += 1

        if tag == "a":
            self.current_link = attrs.get(
                "href"
            )
            self.link_text = []

        if (
            tag in (
                "p", "h1", "h2", "h3"
            )
            and self.ignored_depth == 0
        ):
            self.in_text = True
            self.text_buffer = []

    def handle_data(self, data):
        if self.current_link is not None:
            self.link_text.append(data)

        if self.in_jsonld:
            self.jsonld_text.append(data)

        if (
            self.in_text
            and self.ignored_depth == 0
        ):
            self.text_buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            if self.current_link:
                self.links.append({
                    "url": self.current_link,
                    "title": clean_text(
                        " ".join(self.link_text)
                    )
                })

            self.current_link = None
            self.link_text = []

        if tag == "script":
            if self.in_jsonld:
                raw = "".join(
                    self.jsonld_text
                ).strip()

                if raw:
                    self.jsonld.append(raw)

                self.in_jsonld = False

            elif self.ignored_depth > 0:
                self.ignored_depth -= 1

        if tag in ("style", "nav"):
            if self.ignored_depth > 0:
                self.ignored_depth -= 1

        if tag in ("p", "h1", "h2", "h3"):
            text = clean_text(
                " ".join(self.text_buffer)
            )

            if len(text) >= 15:
                self.paragraphs.append(text)

            if (
                tag.startswith("h")
                and text
            ):
                self.heading.append(text)

            self.in_text = False
            self.text_buffer = []


def parse_html(content):
    parser = ArticleHTMLParser()
    parser.feed(content)
    return parser


def discover_news():
    log("Recherche des articles officiels")

    found = []
    diagnostics = {
        "html_links": 0,
        "sitemap_links": 0,
        "errors": []
    }

    try:
        parser = parse_html(
            fetch(NEWS_URL)
        )

        for item in parser.links:
            url = official_url(
                item["url"]
            )

            if not url or not is_article(url):
                continue

            title = item["title"]

            if len(title) < 8:
                title = (
                    url.rstrip("/")
                    .split("/")[-1]
                    .replace("-", " ")
                    .title()
                )

            found.append({
                "title": title,
                "url": url,
                "discovery_method": "html_link"
            })

        diagnostics["html_links"] = len(
            found
        )

    except Exception as exc:
        diagnostics["errors"].append({
            "source": NEWS_URL,
            "error": str(exc)[:200]
        })

    # On explore uniquement les sitemaps
    # anglophones directement pertinents.
    sitemap_urls = [
        OFFICIAL_SITE + "/us/news/sitemap.xml",
        OFFICIAL_SITE + "/us/pokemon-news/sitemap.xml",
        OFFICIAL_SITE + "/sitemap.xml"
    ]

    for sitemap in sitemap_urls[:MAX_SITEMAPS]:
        try:
            raw = fetch(sitemap)
            root = ET.fromstring(raw)

            for element in root.iter():
                if (
                    element.tag.split("}")[-1]
                    != "loc"
                ):
                    continue

                url = official_url(
                    element.text or ""
                )

                if not url or not is_article(url):
                    continue

                found.append({
                    "title": (
                        url.rstrip("/")
                        .split("/")[-1]
                        .replace("-", " ")
                        .title()
                    ),
                    "url": url,
                    "discovery_method": "sitemap"
                })

                diagnostics[
                    "sitemap_links"
                ] += 1

        except Exception as exc:
            diagnostics["errors"].append({
                "source": sitemap,
                "error": str(exc)[:200]
            })

        time.sleep(REQUEST_DELAY)

    unique = {}

    for article in found:
        url = article["url"]

        if url not in unique:
            unique[url] = article

        elif (
            article["discovery_method"]
            == "html_link"
        ):
            unique[url] = article

    return (
        list(unique.values())[:MAX_ARTICLES],
        diagnostics
    )


def announcement_sentences(text):
    sentences = re.split(
        r"(?<=[.!?])\s+",
        text
    )

    evidence = []

    for sentence in sentences:
        if any(
            re.search(
                pattern,
                sentence,
                re.IGNORECASE
            )
            for pattern in ANNOUNCEMENT_PATTERNS
        ):
            evidence.append(
                sentence[:500]
            )

    return evidence[:8]


def candidate_names(text, known_names):
    """
    Extraction prudente de noms candidats.

    Les noms propres seuls ne sont pas
    une preuve de nouvelle espèce.
    """
    matches = re.findall(
        r"\b[A-Z][a-z]{3,}(?:[-'][A-Z]?[a-z]+)?\b",
        text
    )

    results = []

    for value in matches:
        lowered = value.lower()

        if value in EXCLUDED_WORDS:
            continue

        if lowered in known_names:
            continue

        if lowered in MANUAL_POKEMON:
            continue

        if len(value) > 22:
            continue

        if value not in results:
            results.append(value)

    return results[:30]


def known_mentions(text, known_names):
    normalized = re.sub(
        r"[^a-z0-9-]",
        " ",
        text.lower()
    )

    words = set(
        normalized.split()
    )

    return sorted(
        name
        for name in known_names
        if name in words
    )[:30]


def inspect_article(article, known_names):
    result = dict(article)

    result["published_at"] = None
    result["announcement_evidence"] = []
    result["known_pokemon_mentions"] = []
    result["name_candidates_for_review"] = []
    result["verified_new_species"] = False
    result["inspection_status"] = "not_checked"

    try:
        page = fetch(
            article["url"]
        )

        parser = parse_html(page)

        body = " ".join(
            parser.paragraphs
        )[:30000]

        title = article["title"]

        text = title + ". " + body

        evidence = announcement_sentences(
            text
        )

        result[
            "announcement_evidence"
        ] = evidence

        result[
            "known_pokemon_mentions"
        ] = known_mentions(
            text,
            known_names
        )

        # Les noms candidats sont retenus
        # uniquement s'il existe des indices
        # d'annonce dans l'article.
        if evidence:
            evidence_text = " ".join(
                evidence
            )

            result[
                "name_candidates_for_review"
            ] = candidate_names(
                evidence_text,
                known_names
            )

        result["inspection_status"] = "ok"

    except Exception as exc:
        result["inspection_status"] = "error"
        result["inspection_error"] = str(
            exc
        )[:200]

    return result


def update_pokeapi():
    log("Actualisation PokéAPI")

    species = fetch_json(
        API + "/pokemon-species?limit=2000"
    )["results"]

    ids = [
        species_id(item["url"])
        for item in species
    ]

    ids = [
        number for number in ids
        if number is not None
    ]

    if not ids:
        raise RuntimeError(
            "Aucun Pokémon récupéré"
        )

    max_id = max(ids)

    generations = fetch_json(
        API + "/generation?limit=100"
    )["results"]

    ranges = []

    for generation in generations:
        details = fetch_json(
            generation["url"]
        )

        values = [
            species_id(p["url"])
            for p in details.get(
                "pokemon_species", []
            )
        ]

        values = [
            number
            for number in values
            if number is not None
        ]

        if values:
            ranges.append([
                min(values),
                max(values)
            ])

    ranges.sort(
        key=lambda item: item[0]
    )

    if max_id < 1028:
        if len(ranges) < 10:
            ranges.append([
                max(1026, max_id + 1),
                1028
            ])
        else:
            ranges[-1][1] = max(
                ranges[-1][1], 1028
            )

    page = ROOT / "index.html"

    original = page.read_text(
        encoding="utf-8"
    )

    updated, count_max = re.subn(
        r"MAX=\d+,PAGE=",
        f"MAX={max_id},PAGE=",
        original,
        count=1
    )

    updated, count_ranges = re.subn(
        r"const genRanges=\[\[.*?\]\];",
        "const genRanges="
        + json.dumps(
            ranges,
            separators=(",", ":")
        )
        + ";",
        updated,
        count=1
    )

    if count_max != 1 or count_ranges != 1:
        raise RuntimeError(
            "Structure de index.html incompatible"
        )

    updated = updated.replace(
        ".concat(newPokemon).sort((a,b)=>a.id-b.id)",
        ".concat(newPokemon.filter(p=>p.id>MAX))"
        ".sort((a,b)=>a.id-b.id)"
    )

    if updated != original:
        page.write_text(
            updated,
            encoding="utf-8"
        )

    save_json(
        DATA / "catalogue-status.json",
        {
            "checked_at": now(),
            "pokeapi_max_species_id": max_id,
            "generation_ranges": ranges,
            "source": (
                API + "/pokemon-species"
            )
        }
    )

    known_names = {
        item["name"].lower()
        for item in species
    }

    return {
        "max_id": max_id,
        "known_names": known_names
    }


def update_news(known_names):
    previous = load_json(
        DATA / "nouveautes-pokemon.json",
        {}
    ) or {}

    discovered, diagnostics = discover_news()

    old_articles = previous.get(
        "articles", []
    )

    existing_urls = {
        article["url"]
        for article in discovered
    }

    for article in old_articles:
        if not isinstance(
            article, dict
        ):
            continue

        url = official_url(
            article.get("url", "")
        )

        if (
            url
            and is_article(url)
            and url not in existing_urls
        ):
            discovered.append({
                "title": article.get(
                    "title", ""
                ),
                "url": url,
                "discovery_method": (
                    "previous_scan"
                )
            })

            existing_urls.add(url)

    discovered = discovered[:MAX_ARTICLES]

    inspected = []

    for index, article in enumerate(
        discovered
    ):
        if index < MAX_ARTICLE_FETCHES:
            inspected.append(
                inspect_article(
                    article,
                    known_names
                )
            )

            time.sleep(
                REQUEST_DELAY
            )

        else:
            item = dict(article)

            item[
                "inspection_status"
            ] = "not_checked"

            item[
                "verified_new_species"
            ] = False

            inspected.append(item)

    candidates = []

    for article in inspected:
        evidence = article.get(
            "announcement_evidence", []
        )

        if not evidence:
            continue

        for name in article.get(
            "name_candidates_for_review", []
        ):
            candidates.append({
                "name": name,
                "source_title": article["title"],
                "source_url": article["url"],
                "evidence": evidence[:3],
                "status": "requires_manual_review",
                "verified": False
            })

    # Déduplication par nom et source.
    unique_candidates = {}

    for candidate in candidates:
        key = (
            candidate["name"].lower(),
            candidate["source_url"]
        )

        unique_candidates[key] = candidate

    candidates = list(
        unique_candidates.values()
    )

    checked_at = now()

    if discovered:
        status = "ok"

    elif diagnostics["errors"]:
        status = "source_unavailable"

    else:
        status = "no_articles_detected"

    save_json(
        DATA / "nouveautes-pokemon.json",
        {
            "checked_at": checked_at,
            "status": status,
            "source": NEWS_URL,
            "articles": inspected,
            "diagnostics": {
                **diagnostics,
                "articles_discovered": len(
                    discovered
                ),
                "articles_inspected": sum(
                    a.get("inspection_status")
                    == "ok"
                    for a in inspected
                ),
                "candidates_found": len(
                    candidates
                )
            },
            "notice": (
                "Les noms détectés ne sont pas "
                "automatiquement considérés comme "
                "de nouvelles espèces officielles."
            )
        }
    )

    save_json(
        DATA / "pokemon-a-verifier.json",
        {
            "checked_at": checked_at,
            "candidate_count": len(
                candidates
            ),
            "candidates": candidates,
            "notice": (
                "Tous les candidats nécessitent "
                "une validation humaine."
            )
        }
    )

    save_json(
        DATA / "official-news-review.json",
        {
            "checked_at": checked_at,
            "status": status,
            "review_required": bool(
                candidates
            ),
            "articles_found": len(
                discovered
            ),
            "candidate_count": len(
                candidates
            ),
            "new_species_confirmed": 0,
            "source": NEWS_URL
        }
    )

    log(
        f"Articles trouvés : {len(discovered)}"
    )

    log(
        f"Candidats à vérifier : {len(candidates)}"
    )


def main():
    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    log("================================")
    log("POKEDEX V5.1")
    log("SURVEILLANCE OFFICIELLE")
    log("================================")

    catalogue = update_pokeapi()

    update_news(
        catalogue["known_names"]
    )

    log("================================")
    log(
        "Espèces PokéAPI : "
        + str(catalogue["max_id"])
    )
    log("ACTUALISATION TERMINÉE")
    log("================================")


if __name__ == "__main__":
    main()
