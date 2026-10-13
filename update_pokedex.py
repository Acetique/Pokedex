
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX V5.2
Actualisation automatique et surveillance officielle.

Compatible :
- Python 3.12
- GitHub Actions
- GitHub Pages
- PokéAPI

Aucune dépendance externe.
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


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

API = "https://pokeapi.co/api/v2"

OFFICIAL_SITE = "https://www.pokemon.com"
NEWS_URL = OFFICIAL_SITE + "/us/pokemon-news"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; "
        "CommunityPokedex/5.2)"
    ),
    "Accept": (
        "text/html,application/json,"
        "application/xml,text/xml;q=0.9,*/*;q=0.5"
    ),
}

MAX_ARTICLES = 80
MAX_ARTICLE_FETCHES = 25
REQUEST_DELAY = 0.4
MAX_SITEMAP_URLS = 5000

NEWS_PREFIXES = (
    "/us/news/",
    "/us/pokemon-news/",
    "/fr/actualites/",
)

ANNOUNCEMENT_PATTERNS = [
    r"\bnewly discovered pok[eé]mon\b",
    r"\bnew pok[eé]mon\b",
    r"\bnew species of pok[eé]mon\b",
    r"\bmeet (?:the )?new pok[eé]mon\b",
    r"\bintroducing (?:a |the )?new pok[eé]mon\b",
    r"\bnever.before.seen pok[eé]mon\b",
    r"\bpok[eé]mon (?:has|have) been revealed\b",
    r"\bnouveaux? pok[eé]mon\b",
    r"\bnouvelles? esp[eè]ces? de pok[eé]mon\b",
    r"\bpok[eé]mon in[eé]dits?\b",
]

MANUAL_POKEMON = {
    "browt",
    "pombon",
    "gecqua",
    "broussatif",
    "caloulou",
    "ogéko",
}

EXCLUDED_NAMES = {
    "Pokemon", "Pokémon", "New", "Meet",
    "Introducing", "Discover", "Discovered",
    "Official", "News", "Update", "Updates",
    "Game", "Games", "Nintendo", "Switch",
    "Center", "Store", "Home", "Community",
    "Event", "Events", "Season", "Series",
    "Movie", "Movies", "Netflix", "Amazon",
    "Apple", "Youtube", "YouTube", "Trading",
    "Card", "Cards", "TCG", "Scarlet",
    "Violet", "Legends", "Pokopia",
    "Champions", "Version", "Online",
    "Competition", "October", "November",
    "December", "January", "February",
    "March", "April", "May", "June", "July",
    "August", "September", "Today",
    "Tomorrow", "Learn", "More", "Details",
    "Features", "Available", "Coming",
    "Quality", "Life", "Improvements",
    "Global", "Challenge", "Museum",
    "World", "Space", "Agency",
    "Pokedex", "Pokédex", "The", "This",
    "These", "That", "With", "From",
    "Their", "Your", "Ready", "Look",
    "Celebrate", "During", "Into",
    "First", "Next", "Fans", "Players",
    "Adventure", "Region", "Regions",
    "Forms", "Form", "Mega", "Evolution",
    "Evolutions", "Battle", "Battles",
    "Type", "Types",
}


# ============================================================
# OUTILS GÉNÉRAUX
# ============================================================

def now():
    return dt.datetime.now(
        dt.timezone.utc
    ).isoformat()


def log(message):
    print(
        "[POKEDEX V5.2] " + str(message),
        flush=True
    )


def save_json(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    content = json.dumps(
        data,
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


def fetch_response(url, timeout=25):
    request = urllib.request.Request(
        url,
        headers=HEADERS
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout
    ) as response:
        raw = response.read(8_000_000)

        content_type = response.headers.get(
            "Content-Type", ""
        )

        charset = (
            response.headers.get_content_charset()
            or "utf-8"
        )

        return {
            "text": raw.decode(
                charset,
                errors="replace"
            ),
            "content_type": content_type,
            "status": response.status,
        }


def fetch(url):
    return fetch_response(url)["text"]


def fetch_json(url):
    return json.loads(fetch(url))


def clean_text(value):
    return " ".join(
        html.unescape(
            str(value or "")
        ).split()
    )


def species_id(url):
    match = re.search(
        r"/pokemon-species/(\d+)/?$",
        url
    )

    return (
        int(match.group(1))
        if match else None
    )


def normalize_url(url, base=NEWS_URL):
    if not isinstance(url, str):
        return None

    absolute = urllib.parse.urljoin(
        base,
        url
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


def is_news_article(url):
    path = urllib.parse.urlparse(
        url
    ).path.lower()

    if path.rstrip("/") in (
        "/us/news",
        "/us/pokemon-news",
        "/fr/actualites"
    ):
        return False

    return any(
        path.startswith(prefix)
        for prefix in NEWS_PREFIXES
    )


# ============================================================
# PARSEUR HTML
# ============================================================

class PokemonHTMLParser(HTMLParser):

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.links = []
        self.paragraphs = []
        self.jsonld = []

        self.current_href = None
        self.current_link_text = []

        self.capture_text_tag = None
        self.current_text = []

        self.capture_jsonld = False
        self.current_jsonld = []

        self.ignored_tags = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)

        if tag == "script":
            if "ld+json" in attributes.get(
                "type", ""
            ).lower():
                self.capture_jsonld = True
                self.current_jsonld = []
            else:
                self.ignored_tags.append(tag)

            return

        if tag in ("style", "noscript"):
            self.ignored_tags.append(tag)
            return

        if self.ignored_tags:
            return

        if tag == "a":
            self.current_href = attributes.get(
                "href"
            )
            self.current_link_text = []

        if tag in ("p", "h1", "h2", "h3"):
            self.capture_text_tag = tag
            self.current_text = []

    def handle_data(self, data):
        if self.capture_jsonld:
            self.current_jsonld.append(data)
            return

        if self.ignored_tags:
            return

        if self.current_href is not None:
            self.current_link_text.append(data)

        if self.capture_text_tag is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.capture_jsonld:
            raw = "".join(
                self.current_jsonld
            ).strip()

            if raw:
                self.jsonld.append(raw)

            self.capture_jsonld = False
            self.current_jsonld = []
            return

        if (
            self.ignored_tags
            and tag == self.ignored_tags[-1]
        ):
            self.ignored_tags.pop()
            return

        if self.ignored_tags:
            return

        if tag == "a":
            if self.current_href:
                self.links.append({
                    "url": self.current_href,
                    "title": clean_text(
                        " ".join(
                            self.current_link_text
                        )
                    )
                })

            self.current_href = None
            self.current_link_text = []

        if tag == self.capture_text_tag:
            text = clean_text(
                " ".join(
                    self.current_text
                )
            )

            if len(text) >= 12:
                self.paragraphs.append(text)

            self.capture_text_tag = None
            self.current_text = []


def parse_html(content):
    parser = PokemonHTMLParser()
    parser.feed(content)
    return parser


# ============================================================
# EXTRACTION DES ARTICLES
# ============================================================

def jsonld_articles(value):
    results = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return

        if not isinstance(node, dict):
            return

        kinds = node.get("@type", [])
        if not isinstance(kinds, list):
            kinds = [kinds]

        if any(
            kind in (
                "Article",
                "NewsArticle",
                "BlogPosting"
            )
            for kind in kinds
        ):
            title = node.get(
                "headline", ""
            )

            url = node.get(
                "url",
                node.get("mainEntityOfPage")
            )

            if isinstance(url, dict):
                url = url.get("@id")

            if (
                isinstance(title, str)
                and isinstance(url, str)
            ):
                results.append({
                    "title": title,
                    "url": url,
                    "published_at": node.get(
                        "datePublished"
                    ),
                    "discovery_method": "json_ld"
                })

        for child in node.values():
            if isinstance(
                child, (dict, list)
            ):
                walk(child)

    walk(value)
    return results


def discover_html_articles():
    response = fetch_response(
        NEWS_URL
    )

    parser = parse_html(
        response["text"]
    )

    articles = []

    for link in parser.links:
        url = normalize_url(
            link["url"]
        )

        if not url or not is_news_article(url):
            continue

        title = clean_text(
            link["title"]
        )

        if len(title) < 8:
            title = (
                url.rstrip("/")
                .split("/")[-1]
                .replace("-", " ")
                .title()
            )

        articles.append({
            "title": title[:220],
            "url": url,
            "published_at": None,
            "discovery_method": "html_link"
        })

    for raw in parser.jsonld:
        try:
            structured = json.loads(raw)
        except ValueError:
            continue

        for article in jsonld_articles(
            structured
        ):
            url = normalize_url(
                article["url"]
            )

            if not url or not is_news_article(url):
                continue

            articles.append({
                **article,
                "url": url
            })

    return articles


# ============================================================
# SITEMAPS
# ============================================================

def discover_sitemap_articles():
    """
    Recherche limitée aux sitemaps utiles.

    Un sitemap n'est analysé que si la réponse
    ressemble réellement à du XML.
    """

    sitemap_urls = [
        OFFICIAL_SITE + "/us/news/sitemap.xml",
        OFFICIAL_SITE + "/sitemap.xml",
    ]

    found = []
    errors = []
    checked = 0

    for sitemap in sitemap_urls:
        checked += 1

        try:
            response = fetch_response(
                sitemap
            )

            content = response["text"]
            content_type = response[
                "content_type"
            ].lower()

            stripped = content.lstrip()

            looks_xml = (
                stripped.startswith(
                    "<?xml"
                )
                or stripped.startswith(
                    "<urlset"
                )
                or stripped.startswith(
                    "<sitemapindex"
                )
            )

            if (
                not looks_xml
                and "xml" not in content_type
            ):
                errors.append({
                    "url": sitemap,
                    "error": (
                        "Réponse non XML : "
                        + content_type
                    )
                })
                continue

            try:
                root = ET.fromstring(
                    content
                )
            except ET.ParseError as exc:
                errors.append({
                    "url": sitemap,
                    "error": (
                        "XML invalide : "
                        + str(exc)
                    )
                })
                continue

            count = 0

            for element in root.iter():
                if (
                    element.tag.split("}")[-1]
                    != "loc"
                ):
                    continue

                url = normalize_url(
                    element.text or ""
                )

                if (
                    not url
                    or not is_news_article(url)
                ):
                    continue

                title = (
                    url.rstrip("/")
                    .split("/")[-1]
                    .replace("-", " ")
                    .title()
                )

                found.append({
                    "title": title,
                    "url": url,
                    "published_at": None,
                    "discovery_method": "sitemap"
                })

                count += 1

                if count >= MAX_SITEMAP_URLS:
                    break

        except Exception as exc:
            errors.append({
                "url": sitemap,
                "error": str(exc)[:200]
            })

        time.sleep(
            REQUEST_DELAY
        )

    return found, {
        "sitemaps_checked": checked,
        "sitemap_articles_found": len(
            found
        ),
        "errors": errors
    }


# ============================================================
# ANALYSE DES ANNONCES
# ============================================================

def find_announcement_evidence(text):
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

    return evidence[:10]


def find_known_pokemon(text, known_names):
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
    )[:40]


def find_candidate_names(text, known_names):
    """
    Recherche indicative de noms propres.

    Les candidats sont toujours soumis
    à une vérification humaine.
    """

    matches = re.findall(
        r"\b[A-Z][a-z]{3,}(?:[-'][A-Z]?[a-z]+)?\b",
        text
    )

    candidates = []

    for name in matches:
        lower = name.lower()

        if name in EXCLUDED_NAMES:
            continue

        if lower in known_names:
            continue

        if lower in MANUAL_POKEMON:
            continue

        if len(name) > 22:
            continue

        if name not in candidates:
            candidates.append(name)

    return candidates[:25]


def inspect_article(article, known_names):
    result = dict(article)

    result["announcement_evidence"] = []
    result["known_pokemon_mentions"] = []
    result["name_candidates_for_review"] = []
    result["verified_new_species"] = False

    try:
        content = fetch(
            article["url"]
        )

        parser = parse_html(
            content
        )

        body = " ".join(
            parser.paragraphs
        )[:40000]

        text = (
            article["title"]
            + ". "
            + body
        )

        evidence = find_announcement_evidence(
            text
        )

        result[
            "announcement_evidence"
        ] = evidence

        result[
            "known_pokemon_mentions"
        ] = find_known_pokemon(
            text,
            known_names
        )

        if evidence:
            result[
                "name_candidates_for_review"
            ] = find_candidate_names(
                " ".join(evidence),
                known_names
            )

        result["inspection_status"] = "ok"
        result["extracted_text_length"] = len(
            body
        )

    except Exception as exc:
        result["inspection_status"] = "error"
        result["inspection_error"] = str(
            exc
        )[:200]

    return result


# ============================================================
# ACTUALISATION POKEAPI
# ============================================================

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
        value for value in ids
        if value is not None
    ]

    if not ids:
        raise RuntimeError(
            "Aucune espèce PokéAPI"
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
            value for value in values
            if value is not None
        ]

        if values:
            ranges.append([
                min(values),
                max(values)
            ])

    ranges.sort(
        key=lambda pair: pair[0]
    )

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

    original = page.read_text(
        encoding="utf-8"
    )

    updated, max_count = re.subn(
        r"MAX=\d+,PAGE=",
        f"MAX={max_id},PAGE=",
        original,
        count=1
    )

    updated, ranges_count = re.subn(
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

    if (
        max_count != 1
        or ranges_count != 1
    ):
        raise RuntimeError(
            "Marqueurs index.html introuvables"
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


# ============================================================
# ACTUALISATION DES ACTUALITÉS
# ============================================================

def update_news(known_names):
    log(
        "Recherche des actualités officielles"
    )

    previous = load_json(
        DATA / "nouveautes-pokemon.json",
        {}
    ) or {}

    previous_articles = previous.get(
        "articles", []
    )

    errors = []

    try:
        html_articles = discover_html_articles()
    except Exception as exc:
        html_articles = []

        errors.append({
            "source": NEWS_URL,
            "error": str(exc)[:200]
        })

    sitemap_articles, sitemap_diagnostics = (
        discover_sitemap_articles()
    )

    current_articles = {}

    for article in (
        html_articles + sitemap_articles
    ):
        url = article["url"]

        if (
            url not in current_articles
            or article["discovery_method"]
            == "html_link"
        ):
            current_articles[url] = article

    previously_known_urls = {
        item.get("url")
        for item in previous_articles
        if isinstance(item, dict)
    }

    newly_discovered = [
        article
        for url, article in current_articles.items()
        if url not in previously_known_urls
    ]

    archive_articles = []

    for item in previous_articles:
        if not isinstance(item, dict):
            continue

        url = normalize_url(
            item.get("url", "")
        )

        if (
            url
            and is_news_article(url)
            and url not in current_articles
        ):
            archive_articles.append({
                "title": item.get(
                    "title", ""
                ),
                "url": url,
                "published_at": item.get(
                    "published_at"
                ),
                "discovery_method": (
                    "previous_scan"
                )
            })

    articles = (
        list(current_articles.values())
        + archive_articles
    )[:MAX_ARTICLES]

    inspected = []

    for index, article in enumerate(
        articles
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

            item["inspection_status"] = (
                "not_checked"
            )

            item["verified_new_species"] = False

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

    unique = {}

    for candidate in candidates:
        key = (
            candidate["name"].lower(),
            candidate["source_url"]
        )

        unique[key] = candidate

    candidates = list(
        unique.values()
    )

    if current_articles:
        status = "ok"
    elif archive_articles:
        status = "degraded_archive_only"
    elif errors:
        status = "source_unavailable"
    else:
        status = "no_articles_detected"

    checked_at = now()

    diagnostics = {
        "html_links": len(
            html_articles
        ),
        "sitemap_links": len(
            sitemap_articles
        ),
        "new_articles": len(
            newly_discovered
        ),
        "archived_articles": len(
            archive_articles
        ),
        "articles_total": len(
            inspected
        ),
        "articles_inspected": sum(
            item.get(
                "inspection_status"
            ) == "ok"
            for item in inspected
        ),
        "candidates_found": len(
            candidates
        ),
        "sitemap": sitemap_diagnostics,
        "errors": errors
    }

    save_json(
        DATA / "nouveautes-pokemon.json",
        {
            "checked_at": checked_at,
            "status": status,
            "source": NEWS_URL,
            "articles": inspected,
            "diagnostics": diagnostics,
            "notice": (
                "Les candidats nécessitent "
                "une validation humaine."
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
                "Aucun candidat n'est ajouté "
                "automatiquement au Pokédex."
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
                inspected
            ),
            "new_articles": len(
                newly_discovered
            ),
            "candidate_count": len(
                candidates
            ),
            "new_species_confirmed": 0,
            "source": NEWS_URL
        }
    )

    log(
        "Nouveaux articles : "
        + str(len(newly_discovered))
    )

    log(
        "Articles analysés : "
        + str(
            diagnostics[
                "articles_inspected"
            ]
        )
    )

    log(
        "Candidats : "
        + str(len(candidates))
    )

    log(
        "Statut : "
        + status
    )


# ============================================================
# EXÉCUTION
# ============================================================

def main():
    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    log("================================")
    log("POKEDEX V5.2")
    log("COLLECTEUR OFFICIEL")
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
