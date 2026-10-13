
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX V5.3 — ACETIQUE
Actualisation automatique + surveillance officielle.

Fonctions :
- Actualiser les espèces de PokéAPI
- Actualiser les générations du Pokédex
- Préserver les entrées provisoires existantes
- Collecter les actualités de pokemon.com
- Analyser les sitemaps officiels
- Récupérer les dates de publication
- Prioriser les annonces de nouvelles espèces
- Éviter les analyses répétées inutiles
- Détecter les contenus HTML incomplets
- Comparer les noms avec PokéAPI
- Conserver un historique permanent
- Générer les fichiers JSON de surveillance

Aucune nouvelle espèce n'est ajoutée automatiquement
à partir d'une simple annonce ou d'un nom candidat.

Python 3.12 — bibliothèque standard uniquement.
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


# ============================================================
# CONFIGURATION
# ============================================================

VERSION = "5.3"

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

API = "https://pokeapi.co/api/v2"

OFFICIAL_SITE = "https://www.pokemon.com"
NEWS_URL = OFFICIAL_SITE + "/us/pokemon-news"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; AcetiquePokedex/5.3)"
    ),
    "Accept": (
        "text/html,application/json,"
        "application/xml,text/xml;q=0.9,*/*;q=0.5"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_VISIBLE_ARTICLES = 100
MAX_INSPECTIONS_PER_RUN = 35
MAX_HISTORY_ENTRIES = 10000
MAX_SITEMAP_URLS = 6000

REQUEST_DELAY = 0.3
REINSPECT_AFTER_DAYS = 14
MIN_ARTICLE_TEXT_LENGTH = 120

NEWS_PREFIXES = (
    "/us/news/",
    "/us/pokemon-news/",
)

SITEMAPS = [
    OFFICIAL_SITE + "/us/news/sitemap.xml",
    OFFICIAL_SITE + "/sitemap.xml",
]

# Expressions annonçant potentiellement
# une nouvelle espèce.
STRONG_PATTERNS = [
    r"\bnewly discovered pok[eé]mon\b",
    r"\bnew species of pok[eé]mon\b",
    r"\bnew pok[eé]mon (?:revealed|unveiled|discovered)\b",
    r"\bmeet (?:the )?new pok[eé]mon\b",
    r"\bintroducing (?:a |the )?new pok[eé]mon\b",
    r"\bnever.before.seen pok[eé]mon\b",
    r"\bnouvelle esp[eè]ce de pok[eé]mon\b",
    r"\bpok[eé]mon in[eé]dit\b",
]

# Indices plus larges : utiles pour sélectionner
# les articles, mais insuffisants pour
# confirmer une nouvelle espèce.
WEAK_PATTERNS = [
    r"\bnew pok[eé]mon\b",
    r"\bnew generation\b",
    r"\bnew starters?\b",
    r"\bstarter pok[eé]mon\b",
    r"\bnew region\b",
    r"\bpok[eé]mon presents\b",
    r"\bpok[eé]mon revealed\b",
    r"\bnew forms?\b",
    r"\bmega evolution\b",
    r"\bnouveaux pok[eé]mon\b",
    r"\bnouvelle g[eé]n[eé]ration\b",
]

EXCLUDED_NAMES = {
    "pokemon", "pokémon", "new", "meet",
    "introducing", "discover", "discovered",
    "official", "news", "update", "updates",
    "game", "games", "nintendo", "switch",
    "center", "store", "home", "community",
    "event", "events", "season", "series",
    "movie", "movies", "netflix", "amazon",
    "apple", "youtube", "trading", "card",
    "cards", "tcg", "scarlet", "violet",
    "legends", "pokopia", "champions",
    "version", "online", "competition",
    "october", "november", "december",
    "january", "february", "march", "april",
    "may", "june", "july", "august",
    "september", "today", "tomorrow",
    "learn", "more", "details", "features",
    "available", "coming", "quality",
    "life", "improvements", "global",
    "challenge", "museum", "world",
    "space", "agency", "pokedex",
    "pokédex", "the", "this", "these",
    "that", "with", "from", "their",
    "your", "ready", "look", "celebrate",
    "during", "into", "first", "next",
    "fans", "players", "adventure",
    "region", "regions", "forms", "form",
    "mega", "evolution", "evolutions",
    "battle", "battles", "type", "types",
    "generation", "starter", "starters",
    "revealed", "unveiled", "species",
    "never", "before", "seen", "and",
    "for", "are", "has", "have", "will",
    "can", "all", "you", "get",
}

MANUAL_POKEMON = {
    "browt", "pombon", "gecqua",
    "broussatif", "caloulou", "ogéko",
}


# ============================================================
# UTILITAIRES
# ============================================================

def now():
    return dt.datetime.now(
        dt.timezone.utc
    ).isoformat()


def log(message):
    print(
        f"[POKEDEX V{VERSION}] {message}",
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


def clean_text(value):
    return " ".join(
        html.unescape(
            str(value or "")
        ).split()
    )


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

        charset = (
            response.headers.get_content_charset()
            or "utf-8"
        )

        return {
            "text": raw.decode(
                charset,
                errors="replace"
            ),
            "content_type": response.headers.get(
                "Content-Type", ""
            ),
            "status": response.status,
        }


def fetch(url):
    return fetch_response(url)["text"]


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


def normalize_url(url, base=NEWS_URL):
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
        parsed.path.rstrip("/"),
        "",
        "",
        ""
    ))


def is_news_article(url):
    path = urllib.parse.urlparse(
        url
    ).path.lower()

    return any(
        path.startswith(prefix)
        for prefix in NEWS_PREFIXES
    )


def parse_date(value):
    if not value:
        return None

    try:
        value = str(value).strip()

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        date = dt.datetime.fromisoformat(
            value
        )

        if date.tzinfo is None:
            date = date.replace(
                tzinfo=dt.timezone.utc
            )

        return date.astimezone(
            dt.timezone.utc
        ).isoformat()

    except (ValueError, TypeError):
        return None


def date_timestamp(value):
    parsed = parse_date(value)

    if not parsed:
        return 0

    return dt.datetime.fromisoformat(
        parsed
    ).timestamp()


def days_since(value):
    parsed = parse_date(value)

    if not parsed:
        return 999999

    date = dt.datetime.fromisoformat(
        parsed
    )

    return (
        dt.datetime.now(dt.timezone.utc)
        - date
    ).total_seconds() / 86400


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
        self.meta = {}

        self.current_href = None
        self.link_text = []

        self.text_tag = None
        self.text_buffer = []

        self.jsonld_active = False
        self.jsonld_buffer = []

        self.ignored = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "meta":
            key = (
                attrs.get("property")
                or attrs.get("name")
                or ""
            ).lower()

            if key:
                self.meta[key] = attrs.get(
                    "content", ""
                )

        if tag == "script":
            if "ld+json" in attrs.get(
                "type", ""
            ).lower():
                self.jsonld_active = True
                self.jsonld_buffer = []
            else:
                self.ignored.append("script")

            return

        if tag in ("style", "noscript"):
            self.ignored.append(tag)
            return

        if self.ignored:
            return

        if tag == "a":
            self.current_href = attrs.get(
                "href"
            )
            self.link_text = []

        if tag in ("p", "h1", "h2", "h3"):
            self.text_tag = tag
            self.text_buffer = []

    def handle_data(self, data):
        if self.jsonld_active:
            self.jsonld_buffer.append(data)
            return

        if self.ignored:
            return

        if self.current_href is not None:
            self.link_text.append(data)

        if self.text_tag is not None:
            self.text_buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.jsonld_active:
            raw = "".join(
                self.jsonld_buffer
            ).strip()

            if raw:
                self.jsonld.append(raw)

            self.jsonld_active = False
            self.jsonld_buffer = []
            return

        if (
            self.ignored
            and self.ignored[-1] == tag
        ):
            self.ignored.pop()
            return

        if self.ignored:
            return

        if tag == "a":
            if self.current_href:
                self.links.append({
                    "url": self.current_href,
                    "title": clean_text(
                        " ".join(self.link_text)
                    )
                })

            self.current_href = None
            self.link_text = []

        if tag == self.text_tag:
            text = clean_text(
                " ".join(self.text_buffer)
            )

            if len(text) >= 12:
                self.paragraphs.append(text)

            self.text_tag = None
            self.text_buffer = []


def parse_html(content):
    parser = PokemonHTMLParser()
    parser.feed(content)
    return parser


# ============================================================
# JSON-LD
# ============================================================

def extract_jsonld_articles(raw_blocks):
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
            url = node.get(
                "url",
                node.get("mainEntityOfPage")
            )

            if isinstance(url, dict):
                url = url.get("@id")

            title = node.get(
                "headline", ""
            )

            if (
                isinstance(url, str)
                and isinstance(title, str)
            ):
                results.append({
                    "url": url,
                    "title": title,
                    "published_at": parse_date(
                        node.get("datePublished")
                    ),
                    "discovery_method": "json_ld"
                })

        for value in node.values():
            if isinstance(
                value, (dict, list)
            ):
                walk(value)

    for raw in raw_blocks:
        try:
            walk(json.loads(raw))
        except ValueError:
            continue

    return results


# ============================================================
# COLLECTE HTML
# ============================================================

def discover_html_articles():
    response = fetch_response(
        NEWS_URL
    )

    parser = parse_html(
        response["text"]
    )

    found = []

    for item in parser.links:
        url = normalize_url(
            item["url"]
        )

        if not url or not is_news_article(url):
            continue

        title = clean_text(
            item["title"]
        )

        if len(title) < 8:
            title = (
                url.rsplit("/", 1)[-1]
                .replace("-", " ")
                .title()
            )

        found.append({
            "url": url,
            "title": title[:220],
            "published_at": None,
            "discovery_method": "html_link"
        })

    for item in extract_jsonld_articles(
        parser.jsonld
    ):
        url = normalize_url(
            item["url"]
        )

        if url and is_news_article(url):
            item["url"] = url
            found.append(item)

    return found


# ============================================================
# COLLECTE SITEMAP
# ============================================================

def discover_sitemap_articles():
    found = []
    errors = []
    checked = 0

    for sitemap in SITEMAPS:
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
                stripped.startswith("<?xml")
                or stripped.startswith("<urlset")
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
                        "Contenu non XML : "
                        + content_type
                    )
                })
                continue

            root = ET.fromstring(
                content
            )

            count = 0

            for node in root.iter():
                if (
                    node.tag.split("}")[-1]
                    != "url"
                ):
                    continue

                url = None
                published_at = None

                for child in node:
                    name = child.tag.split(
                        "}"
                    )[-1]

                    if name == "loc":
                        url = normalize_url(
                            child.text or ""
                        )

                    elif name == "lastmod":
                        published_at = parse_date(
                            child.text
                        )

                if (
                    not url
                    or not is_news_article(url)
                ):
                    continue

                title = (
                    url.rsplit("/", 1)[-1]
                    .replace("-", " ")
                    .title()
                )

                found.append({
                    "url": url,
                    "title": title,
                    "published_at": None,
                    "sitemap_lastmod": published_at,
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

        time.sleep(REQUEST_DELAY)

    return found, {
        "sitemaps_checked": checked,
        "sitemap_links": len(found),
        "errors": errors
    }


# ============================================================
# CLASSEMENT DES ARTICLES
# ============================================================

def article_score(article):
    title = article.get(
        "title", ""
    )

    score = 0

    for pattern in STRONG_PATTERNS:
        if re.search(
            pattern,
            title,
            re.IGNORECASE
        ):
            score += 100

    for pattern in WEAK_PATTERNS:
        if re.search(
            pattern,
            title,
            re.IGNORECASE
        ):
            score += 25

    if re.search(
        r"\b(gen(?:eration)?\s*10|"
        r"new species|starter|"
        r"revealed|unveiled)\b",
        title,
        re.IGNORECASE
    ):
        score += 30

    if article.get(
        "discovery_method"
    ) == "html_link":
        score += 15

    if article.get("published_at"):
        age = days_since(
            article["published_at"]
        )

        if age <= 7:
            score += 30
        elif age <= 30:
            score += 20
        elif age <= 90:
            score += 10

    return score


# ============================================================
# ANALYSE DES ARTICLES
# ============================================================

def announcement_evidence(text):
    sentences = re.split(
        r"(?<=[.!?])\s+",
        text
    )

    results = []

    for sentence in sentences:
        if any(
            re.search(
                pattern,
                sentence,
                re.IGNORECASE
            )
            for pattern in STRONG_PATTERNS
        ):
            results.append(
                clean_text(sentence)[:500]
            )

    return results[:10]


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
    )[:40]


def candidate_names(text, known_names):
    matches = re.findall(
        r"\b[A-Z][a-z]{3,}"
        r"(?:[-'][A-Z]?[a-z]+)?\b",
        text
    )

    results = []

    for name in matches:
        lowered = name.lower()

        if lowered in EXCLUDED_NAMES:
            continue

        if lowered in known_names:
            continue

        if lowered in MANUAL_POKEMON:
            continue

        if len(name) > 22:
            continue

        if name not in results:
            results.append(name)

    return results[:25]


def extract_publication_date(parser):
    keys = (
        "article:published_time",
        "datepublished",
        "date",
        "pubdate",
    )

    for key in keys:
        value = parser.meta.get(
            key
        )

        parsed = parse_date(value)

        if parsed:
            return parsed

    for raw in parser.jsonld:
        try:
            structured = json.loads(raw)
        except ValueError:
            continue

        stack = [structured]

        while stack:
            item = stack.pop()

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            parsed = parse_date(
                item.get("datePublished")
            )

            if parsed:
                return parsed

            stack.extend(
                value
                for value in item.values()
                if isinstance(
                    value, (dict, list)
                )
            )

    return None


def inspect_article(article, known_names):
    result = dict(article)

    result["announcement_evidence"] = []
    result["known_pokemon_mentions"] = []
    result["name_candidates_for_review"] = []
    result["verified_new_species"] = False
    result["inspected_at"] = now()

    try:
        response = fetch_response(
            article["url"]
        )

        parser = parse_html(
            response["text"]
        )

        body = " ".join(
            parser.paragraphs
        )[:40000]

        text = (
            article["title"]
            + ". "
            + body
        )

        publication = extract_publication_date(
            parser
        )

        if publication:
            result[
                "published_at"
            ] = publication

        result[
            "extracted_text_length"
        ] = len(body)

        if len(body) < MIN_ARTICLE_TEXT_LENGTH:
            result[
                "inspection_status"
            ] = "insufficient_content"
            return result

        # Une page avec un petit contenu
        # identique à d'autres pages peut
        # correspondre à une réponse générique.
        result[
            "content_fingerprint"
        ] = __import__(
            "hashlib"
        ).sha256(
            body.encode("utf-8")
        ).hexdigest()[:16]

        evidence = announcement_evidence(
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

        if evidence:
            result[
                "name_candidates_for_review"
            ] = candidate_names(
                " ".join(evidence),
                known_names
            )

        result[
            "inspection_status"
        ] = "ok"

    except Exception as exc:
        result[
            "inspection_status"
        ] = "error"

        result[
            "inspection_error"
        ] = str(exc)[:200]

    return result


# ============================================================
# POKEAPI
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
        number for number in ids
        if number is not None
    ]

    if not ids:
        raise RuntimeError(
            "Aucune espèce récupérée"
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

    if (
        count_max != 1
        or count_ranges != 1
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
# HISTORIQUE ET ACTUALITÉS
# ============================================================

def update_news(known_names):
    log("Collecte des actualités officielles")

    history_path = (
        DATA / "historique-actualites.json"
    )

    previous_history = load_json(
        history_path,
        {}
    ) or {}

    history = previous_history.get(
        "articles", {}
    )

    if not isinstance(history, dict):
        history = {}

    previous_news = load_json(
        DATA / "nouveautes-pokemon.json",
        {}
    ) or {}

    # Migration depuis la V5.2.
    for old in previous_news.get(
        "articles", []
    ):
        if not isinstance(old, dict):
            continue

        url = normalize_url(
            old.get("url", "")
        )

        if not url or not is_news_article(url):
            continue

        if url not in history:
            history[url] = {
                **old,
                "url": url,
                "first_seen": (
                    previous_news.get(
                        "checked_at"
                    ) or now()
                ),
                "last_seen": (
                    previous_news.get(
                        "checked_at"
                    ) or now()
                ),
            }

    errors = []

    try:
        html_articles = discover_html_articles()
    except Exception as exc:
        html_articles = []

        errors.append({
            "source": NEWS_URL,
            "error": str(exc)[:200]
        })

    sitemap_articles, sitemap_info = (
        discover_sitemap_articles()
    )

    discovered = {}

    # Les liens HTML ont priorité sur les
    # titres générés à partir des URL.
    for article in (
        sitemap_articles + html_articles
    ):
        url = article["url"]

        if url not in discovered:
            discovered[url] = article
        elif (
            article["discovery_method"]
            == "html_link"
        ):
            old = discovered[url]

            discovered[url] = {
                **old,
                **article,
                "published_at": (
                    article.get("published_at")
                    or old.get("published_at")
                )
            }

    new_urls = []

    for url, article in discovered.items():
        if url not in history:
            new_urls.append(url)

            history[url] = {
                **article,
                "first_seen": now(),
                "last_seen": now(),
                "inspection_status": (
                    "not_checked"
                ),
                "verified_new_species": False,
            }

        else:
            old = history[url]

            old["last_seen"] = now()

            # Conserver les meilleurs titres.
            if (
                article.get(
                    "discovery_method"
                ) == "html_link"
            ):
                old["title"] = article[
                    "title"
                ]

            if (
                not old.get("published_at")
                and article.get("published_at")
            ):
                old["published_at"] = (
                    article["published_at"]
                )

            if article.get(
                "sitemap_lastmod"
            ):
                old["sitemap_lastmod"] = (
                    article["sitemap_lastmod"]
                )

    # Priorité :
    # 1. Annonces pertinentes
    # 2. Articles jamais inspectés
    # 3. Articles récents
    # 4. Autres articles
    pending = []

    for url, article in history.items():
        if url not in discovered:
            continue

        status = article.get(
            "inspection_status",
            "not_checked"
        )

        last_inspected = article.get(
            "inspected_at"
        )

        needs_inspection = (
            status in (
                "not_checked",
                "error",
                "insufficient_content"
            )
            or days_since(
                last_inspected
            ) >= REINSPECT_AFTER_DAYS
        )

        if not needs_inspection:
            continue

        score = article_score(
            article
        )

        if status == "not_checked":
            score += 20

        if url in new_urls:
            score += 10

        pending.append((
            score,
            date_timestamp(
                article.get("published_at")
            ),
            url
        ))

    pending.sort(
        key=lambda item: (
            item[0],
            item[1]
        ),
        reverse=True
    )

    inspected_count = 0

    for _, _, url in pending[
        :MAX_INSPECTIONS_PER_RUN
    ]:
        inspected = inspect_article(
            history[url],
            known_names
        )

        history[url] = inspected
        inspected_count += 1

        time.sleep(
            REQUEST_DELAY
        )

    # Détection des réponses génériques
    # identiques sur plusieurs URL.
    fingerprints = {}

    for url, article in history.items():
        fingerprint = article.get(
            "content_fingerprint"
        )

        if fingerprint:
            fingerprints.setdefault(
                fingerprint, []
            ).append(url)

    generic_count = 0

    for urls in fingerprints.values():
        if len(urls) < 3:
            continue

        for url in urls:
            history[url][
                "inspection_status"
            ] = "suspected_generic_content"

            generic_count += 1

    candidates = []

    for article in history.values():
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
                "source_title": article.get(
                    "title", ""
                ),
                "source_url": article.get(
                    "url", ""
                ),
                "published_at": article.get(
                    "published_at"
                ),
                "evidence": evidence[:3],
                "status": "requires_manual_review",
                "verified": False
            })

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

    # Conserver les entrées récentes et
    # les annonces importantes.
    if len(history) > MAX_HISTORY_ENTRIES:
        ordered = sorted(
            history.items(),
            key=lambda pair: (
                article_score(pair[1]),
                date_timestamp(
                    pair[1].get("first_seen")
                )
            ),
            reverse=True
        )

        history = dict(
            ordered[:MAX_HISTORY_ENTRIES]
        )

    visible = sorted(
        history.values(),
        key=lambda article: (
            article_score(article),
            date_timestamp(
                article.get("published_at")
            ),
            date_timestamp(
                article.get("first_seen")
            )
        ),
        reverse=True
    )[:MAX_VISIBLE_ARTICLES]

    if discovered:
        status = "ok"
    elif history:
        status = "degraded_archive_only"
    else:
        status = "source_unavailable"

    checked_at = now()

    diagnostics = {
        "html_links": len(
            html_articles
        ),
        "sitemap_links": len(
            sitemap_articles
        ),
        "unique_discovered_urls": len(
            discovered
        ),
        "first_seen_urls": len(
            new_urls
        ),
        "articles_inspected_this_run": (
            inspected_count
        ),
        "history_entries": len(
            history
        ),
        "suspected_generic_content": (
            generic_count
        ),
        "candidates_found": len(
            candidates
        ),
        "sitemap": sitemap_info,
        "errors": errors
    }

    save_json(
        history_path,
        {
            "version": VERSION,
            "checked_at": checked_at,
            "articles": history
        }
    )

    save_json(
        DATA / "nouveautes-pokemon.json",
        {
            "version": VERSION,
            "checked_at": checked_at,
            "status": status,
            "source": NEWS_URL,
            "articles": visible,
            "diagnostics": diagnostics,
            "notice": (
                "Les nouvelles URL ne sont pas "
                "nécessairement de nouvelles "
                "publications. Les noms candidats "
                "doivent être vérifiés."
            )
        }
    )

    save_json(
        DATA / "pokemon-a-verifier.json",
        {
            "version": VERSION,
            "checked_at": checked_at,
            "candidate_count": len(
                candidates
            ),
            "candidates": candidates,
            "notice": (
                "Aucune espèce n'est ajoutée "
                "automatiquement sans validation."
            )
        }
    )

    save_json(
        DATA / "official-news-review.json",
        {
            "version": VERSION,
            "checked_at": checked_at,
            "status": status,
            "review_required": bool(
                candidates
            ),
            "first_seen_urls": len(
                new_urls
            ),
            "articles_inspected": (
                inspected_count
            ),
            "candidate_count": len(
                candidates
            ),
            "new_species_confirmed": 0,
            "source": NEWS_URL
        }
    )

    log(
        "Liens HTML : "
        + str(len(html_articles))
    )

    log(
        "Liens sitemap : "
        + str(len(sitemap_articles))
    )

    log(
        "Nouvelles URL dans l'historique : "
        + str(len(new_urls))
    )

    log(
        "Articles inspectés : "
        + str(inspected_count)
    )

    log(
        "Contenus génériques suspects : "
        + str(generic_count)
    )

    log(
        "Candidats à vérifier : "
        + str(len(candidates))
    )

    log(
        "Statut : " + status
    )


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():
    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    log("================================")
    log("POKEDEX V5.3 — ACETIQUE")
    log("SURVEILLANCE DES NOUVEAUX POKÉMON")
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
