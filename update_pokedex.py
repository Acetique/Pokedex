
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX V5.0
Actualisation automatique depuis PokéAPI
et découverte d'actualités officielles Pokémon.

Fonctions :
- Actualiser le nombre de Pokémon depuis PokéAPI
- Actualiser les plages des générations
- Préserver les trois starters provisoires
- Explorer la page officielle d'actualités
- Lire les données structurées JSON-LD
- Rechercher les liens dans les sitemaps officiels
- Identifier les mentions de Pokémon connus
- Préparer les noms inconnus pour vérification
- Conserver les articles déjà découverts
- Enregistrer les erreurs et diagnostics
- Publier les données JSON pour GitHub Pages

Aucune espèce non vérifiée n'est ajoutée
automatiquement au catalogue principal.
"""

import datetime as dt
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

API = "https://pokeapi.co/api/v2"
OFFICIAL_SITE = "https://www.pokemon.com"
NEWS_URL = OFFICIAL_SITE + "/us/pokemon-news"

USER_AGENT = (
    "CommunityPokedex/5.0 "
    "(automated official news index checker)"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "application/json,application/xml,"
        "text/xml,text/html;q=0.9,*/*;q=0.5"
    ),
}

MAX_ARTICLES = 80
MAX_SITEMAPS = 12
MAX_SITEMAP_URLS = 5000
REQUEST_DELAY = 0.5

NEWS_PATH_MARKERS = (
    "/pokemon-news/",
    "/news/",
)

# Les noms suivants ne sont pas des espèces
# à considérer automatiquement comme confirmées.
GENERIC_WORDS = {
    "Pokemon",
    "Pokémon",
    "News",
    "Video",
    "Game",
    "Games",
    "Official",
    "Nintendo",
    "Trading",
    "Card",
    "Cards",
    "Scarlet",
    "Violet",
    "Legends",
    "Champions",
    "Mega",
    "Evolution",
    "New",
    "Update",
    "October",
    "November",
    "December",
}


def utc_now():
    return dt.datetime.now(
        dt.timezone.utc
    ).isoformat()


def log(message):
    print(
        "[POKEDEX V5.0]",
        message,
        flush=True
    )


def write_json(path, content):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    encoded = json.dumps(
        content,
        ensure_ascii=False,
        indent=2
    ) + "\n"

    if (
        not path.exists()
        or path.read_text(
            encoding="utf-8"
        ) != encoded
    ):
        path.write_text(
            encoded,
            encoding="utf-8"
        )


def read_json(path, default=None):
    if not path.exists():
        return default

    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (ValueError, OSError):
        return default


def download(url, timeout=25):
    request = urllib.request.Request(
        url,
        headers=HEADERS
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout
    ) as response:
        content_type = response.headers.get(
            "Content-Type", ""
        )

        raw = response.read(8_000_000)

        charset = response.headers.get_content_charset()
        charset = charset or "utf-8"

        return (
            raw.decode(
                charset,
                errors="replace"
            ),
            content_type
        )


def get_json(url):
    content, _ = download(url)
    return json.loads(content)


def species_id(url):
    match = re.search(
        r"/pokemon-species/(\d+)/?$",
        url
    )

    if match:
        return int(match.group(1))

    return None


def normalize_url(url, base=OFFICIAL_SITE):
    if not isinstance(url, str):
        return None

    absolute = urllib.parse.urljoin(
        base, url
    )

    parsed = urllib.parse.urlparse(
        absolute
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


def is_news_url(url):
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()

    if path.rstrip("/") in (
        "/us/pokemon-news",
        "/us/news"
    ):
        return False

    return any(
        marker in path
        for marker in NEWS_PATH_MARKERS
    )


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()

        self.links = []
        self.scripts = []
        self.current_link = None
        self.current_text = []
        self.in_jsonld = False
        self.jsonld_text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)

        if tag == "a":
            self.current_link = attributes.get(
                "href"
            )
            self.current_text = []

        if tag == "script":
            script_type = attributes.get(
                "type", ""
            ).lower()

            if "ld+json" in script_type:
                self.in_jsonld = True
                self.jsonld_text = []

    def handle_data(self, data):
        if self.current_link is not None:
            self.current_text.append(data)

        if self.in_jsonld:
            self.jsonld_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            if self.current_link:
                title = " ".join(
                    " ".join(
                        self.current_text
                    ).split()
                )

                self.links.append({
                    "url": self.current_link,
                    "title": html.unescape(title)
                })

            self.current_link = None
            self.current_text = []

        if tag == "script" and self.in_jsonld:
            raw = "".join(
                self.jsonld_text
            ).strip()

            if raw:
                self.scripts.append(raw)

            self.in_jsonld = False
            self.jsonld_text = []


def extract_jsonld_articles(value):
    articles = []

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
            return

        if not isinstance(node, dict):
            return

        kind = node.get("@type", [])
        kinds = kind if isinstance(
            kind, list
        ) else [kind]

        if any(
            k in (
                "NewsArticle",
                "Article",
                "BlogPosting"
            )
            for k in kinds
        ):
            headline = node.get(
                "headline", ""
            )

            url = node.get(
                "url",
                node.get("mainEntityOfPage")
            )

            if isinstance(url, dict):
                url = url.get("@id")

            if isinstance(
                headline, str
            ) and isinstance(url, str):
                articles.append({
                    "title": headline,
                    "url": url,
                    "published_at": node.get(
                        "datePublished"
                    )
                })

        for child in node.values():
            if isinstance(
                child, (list, dict)
            ):
                visit(child)

    visit(value)
    return articles


def discover_html_articles(page_html):
    parser = LinkParser()
    parser.feed(page_html)

    found = []

    for item in parser.links:
        url = normalize_url(
            item["url"], NEWS_URL
        )

        if not url or not is_news_url(url):
            continue

        title = item["title"].strip()

        if len(title) < 8:
            title = url.rstrip("/").split("/")[-1]
            title = title.replace("-", " ").title()

        found.append({
            "title": title[:220],
            "url": url,
            "discovery_method": "html_link"
        })

    for raw in parser.scripts:
        try:
            structured = json.loads(raw)
        except ValueError:
            continue

        for article in extract_jsonld_articles(
            structured
        ):
            url = normalize_url(
                article["url"],
                NEWS_URL
            )

            if not url or not is_news_url(url):
                continue

            found.append({
                "title": article["title"][:220],
                "url": url,
                "published_at": article.get(
                    "published_at"
                ),
                "discovery_method": "json_ld"
            })

    return found


def discover_sitemap_roots():
    roots = [
        OFFICIAL_SITE + "/sitemap.xml"
    ]

    try:
        content, _ = download(
            OFFICIAL_SITE + "/robots.txt"
        )

        for line in content.splitlines():
            if line.lower().startswith(
                "sitemap:"
            ):
                value = line.split(
                    ":", 1
                )[1].strip()

                url = normalize_url(value)

                if url:
                    roots.append(url)

    except Exception as exc:
        log(
            "robots.txt indisponible : "
            + str(exc)
        )

    return list(dict.fromkeys(roots))


def discover_sitemap_articles():
    queue = discover_sitemap_roots()
    visited = set()
    found = []
    errors = []
    inspected_urls = 0

    while (
        queue
        and len(visited) < MAX_SITEMAPS
        and inspected_urls < MAX_SITEMAP_URLS
    ):
        sitemap_url = queue.pop(0)

        if sitemap_url in visited:
            continue

        visited.add(sitemap_url)

        try:
            content, _ = download(
                sitemap_url
            )

            root = ET.fromstring(content)

        except Exception as exc:
            errors.append({
                "url": sitemap_url,
                "error": str(exc)[:200]
            })
            continue

        root_name = root.tag.split("}")[-1]

        if root_name == "sitemapindex":
            for element in root.iter():
                if element.tag.split("}")[-1] != "loc":
                    continue

                value = (
                    element.text or ""
                ).strip()

                url = normalize_url(value)

                if (
                    url
                    and url not in visited
                    and len(queue) < 100
                ):
                    queue.append(url)

        elif root_name == "urlset":
            for entry in root:
                if entry.tag.split("}")[-1] != "url":
                    continue

                inspected_urls += 1

                url = None
                lastmod = None

                for child in entry:
                    key = child.tag.split("}")[-1]

                    if key == "loc":
                        url = normalize_url(
                            child.text or ""
                        )

                    elif key == "lastmod":
                        lastmod = child.text

                if url and is_news_url(url):
                    title = (
                        url.rstrip("/")
                        .split("/")[-1]
                        .replace("-", " ")
                        .title()
                    )

                    found.append({
                        "title": title,
                        "url": url,
                        "published_at": lastmod,
                        "discovery_method": "sitemap"
                    })

                if inspected_urls >= MAX_SITEMAP_URLS:
                    break

        time.sleep(REQUEST_DELAY)

    return found, {
        "sitemaps_checked": len(visited),
        "urls_inspected": inspected_urls,
        "errors": errors
    }


def merge_articles(*collections):
    merged = {}

    for collection in collections:
        for item in collection:
            if not isinstance(item, dict):
                continue

            url = normalize_url(
                item.get("url", "")
            )

            if not url or not is_news_url(url):
                continue

            title = str(
                item.get("title") or ""
            ).strip()

            if not title:
                title = (
                    url.rstrip("/")
                    .split("/")[-1]
                    .replace("-", " ")
                    .title()
                )

            if url not in merged:
                merged[url] = {
                    "title": title[:220],
                    "url": url,
                    "published_at": item.get(
                        "published_at"
                    ),
                    "discovery_method": item.get(
                        "discovery_method",
                        "previous_scan"
                    )
                }

            else:
                old = merged[url]

                if len(title) > len(old["title"]):
                    old["title"] = title[:220]

                if (
                    not old.get("published_at")
                    and item.get("published_at")
                ):
                    old["published_at"] = item[
                        "published_at"
                    ]

    return list(merged.values())


def update_pokeapi():
    log("Vérification de PokéAPI")

    species = get_json(
        API + "/pokemon-species?limit=2000"
    )["results"]

    ids = [
        species_id(p["url"])
        for p in species
    ]

    ids = [
        number
        for number in ids
        if number is not None
    ]

    if not ids:
        raise RuntimeError(
            "Aucune espèce trouvée dans PokéAPI"
        )

    max_id = max(ids)

    generations = get_json(
        API + "/generation?limit=100"
    )["results"]

    ranges = []

    for generation in generations:
        detail = get_json(
            generation["url"]
        )

        values = [
            species_id(p["url"])
            for p in detail.get(
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
        key=lambda pair: pair[0]
    )

    # Conservation des starters provisoires
    # avec les numéros locaux 1026 à 1028.
    if max_id < 1028:
        if len(ranges) < 10:
            ranges.append([
                max(1026, max_id + 1),
                1028
            ])
        else:
            ranges[-1][1] = max(
                ranges[-1][1],
                1028
            )

    page = ROOT / "index.html"

    if not page.exists():
        raise FileNotFoundError(
            "index.html introuvable"
        )

    original = page.read_text(
        encoding="utf-8"
    )

    updated, max_matches = re.subn(
        r"MAX=\d+,PAGE=",
        f"MAX={max_id},PAGE=",
        original,
        count=1
    )

    updated, range_matches = re.subn(
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

    if max_matches != 1:
        raise RuntimeError(
            "Marqueur MAX introuvable dans index.html"
        )

    if range_matches != 1:
        raise RuntimeError(
            "Marqueur genRanges introuvable"
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

        log(
            "index.html actualisé"
        )

    checked_at = utc_now()

    write_json(
        DATA / "catalogue-status.json",
        {
            "checked_at": checked_at,
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


def find_known_pokemon(text, known_names):
    normalized = text.lower()
    normalized = re.sub(
        r"[^a-z0-9 -]",
        " ",
        normalized
    )

    words = set(
        normalized.split()
    )

    return sorted(
        name
        for name in known_names
        if name in words
    )


def find_review_candidates(title):
    """
    Recherche indicative de noms propres.

    Ces candidats ne sont jamais considérés
    comme de nouvelles espèces confirmées.
    """
    candidates = re.findall(
        r"\b[A-Z][a-z]{3,}(?:[- ][A-Z][a-z]{3,})?\b",
        title
    )

    return sorted({
        value
        for value in candidates
        if value not in GENERIC_WORDS
    })[:12]


def update_official_news(known_names):
    log(
        "Recherche des actualités officielles"
    )

    previous = read_json(
        DATA / "nouveautes-pokemon.json",
        {}
    ) or {}

    previous_articles = previous.get(
        "articles", []
    )

    html_articles = []
    sitemap_articles = []
    errors = []

    html_success = False
    sitemap_success = False

    try:
        content, _ = download(
            NEWS_URL
        )

        html_success = True

        html_articles = discover_html_articles(
            content
        )

        log(
            f"Liens HTML détectés : "
            f"{len(html_articles)}"
        )

    except Exception as exc:
        errors.append({
            "source": NEWS_URL,
            "error": str(exc)[:200]
        })

    sitemap_diagnostics = {}

    try:
        (
            sitemap_articles,
            sitemap_diagnostics
        ) = discover_sitemap_articles()

        sitemap_success = (
            sitemap_diagnostics.get(
                "sitemaps_checked", 0
            ) > len(
                sitemap_diagnostics.get(
                    "errors", []
                )
            )
        )

        log(
            f"Liens sitemap détectés : "
            f"{len(sitemap_articles)}"
        )

    except Exception as exc:
        errors.append({
            "source": "sitemaps",
            "error": str(exc)[:200]
        })

    articles = merge_articles(
        html_articles,
        sitemap_articles,
        previous_articles
    )

    # Les articles découverts pendant ce scan
    # passent avant les archives conservées.
    articles = articles[:MAX_ARTICLES]

    for article in articles:
        title = article["title"]

        article["known_pokemon_mentions"] = (
            find_known_pokemon(
                title,
                known_names
            )
        )

        article["name_candidates_for_review"] = (
            find_review_candidates(title)
        )

        article["verified_new_species"] = False

    if html_articles or sitemap_articles:
        status = "ok"

    elif html_success or sitemap_success:
        status = "no_articles_detected"

    else:
        status = "source_unavailable"

    checked_at = utc_now()

    result = {
        "checked_at": checked_at,
        "status": status,
        "source": NEWS_URL,
        "articles": articles,
        "diagnostics": {
            "html_articles_found": len(
                html_articles
            ),
            "sitemap_articles_found": len(
                sitemap_articles
            ),
            "retained_articles": len(
                articles
            ),
            "sitemap": sitemap_diagnostics,
            "errors": errors
        },
        "notice": (
            "Les articles sont issus de sources "
            "officielles accessibles. Les candidats "
            "de noms nécessitent une vérification "
            "humaine avant ajout au Pokédex."
        )
    }

    write_json(
        DATA / "nouveautes-pokemon.json",
        result
    )

    write_json(
        DATA / "official-news-review.json",
        {
            "checked_at": checked_at,
            "status": status,
            "review_required": True,
            "articles_found": len(articles),
            "new_species_confirmed": 0,
            "source": NEWS_URL,
            "diagnostics": result["diagnostics"]
        }
    )

    log(
        f"Statut des actualités : {status}"
    )

    log(
        f"Articles conservés : {len(articles)}"
    )

    return result


def main():
    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    log("================================")
    log("POKEDEX V5.0")
    log("ACTUALISATION AUTOMATIQUE")
    log("================================")

    catalogue = update_pokeapi()

    news = update_official_news(
        catalogue["known_names"]
    )

    log("================================")
    log(
        "Espèces PokéAPI : "
        + str(catalogue["max_id"])
    )
    log(
        "Articles officiels : "
        + str(len(news["articles"]))
    )
    log(
        "Statut : "
        + news["status"]
    )
    log("ACTUALISATION TERMINÉE")
    log("================================")


if __name__ == "__main__":
    main()
