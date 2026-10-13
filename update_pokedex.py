
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX ACETIQUE V5.6
=====================

Actualisation automatique du catalogue Pokémon
et surveillance des annonces officielles.

Python 3.11+
Bibliothèque standard uniquement.
Aucune clé API payante.

Fonctionnalités :
- PokéAPI avec cache et retentatives
- Détection des nouvelles espèces officielles
- Comparaison avec le catalogue précédent
- Actualisation de index.html
- Conservation des Pokémon provisoires
- Collecte des actualités Pokémon
- Extraction HTML et JSON-LD
- Détection des pages antibot
- Analyse des titres en secours
- Priorité aux nouvelles espèces
- Surveillance génération 10
- Distinction espèces / formes / Méga
- Historique permanent
- Limitation des requêtes répétitives
- Rapports JSON
"""

import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


# ============================================================
# CONFIGURATION
# ============================================================

VERSION = "5.6"

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

API = "https://pokeapi.co/api/v2"

SITE = "https://www.pokemon.com"
NEWS = SITE + "/us/pokemon-news"

SITEMAPS = [
    SITE + "/sitemap.xml",
    SITE + "/us/news/sitemap.xml",
]

HEADERS = {
    "User-Agent": (
        "PokedexAcetique/5.6 "
        "(public catalogue updater)"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/json,application/xml,*/*"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

API_TIMEOUT = 40
NEWS_TIMEOUT = 18

API_ATTEMPTS = 4
NEWS_ATTEMPTS = 2

REQUEST_DELAY = 0.5

MAX_ARTICLES_PER_RUN = 20
MAX_VISIBLE_ARTICLES = 100
MAX_PRIORITY_ARTICLES = 60
MAX_HISTORY_ARTICLES = 10000

MIN_ARTICLE_TEXT = 180

RECHECK_OK_DAYS = 30
RECHECK_GENERIC_DAYS = 14
RECHECK_ERROR_DAYS = 7

GENERIC_FINGERPRINT_THRESHOLD = 3

MANUAL_POKEMON = {
    "browt",
    "pombon",
    "gecqua",
}

# Signaux indiquant potentiellement une nouvelle espèce.
SPECIES_PATTERNS = [
    r"\bnewly discovered pok[eé]mon\b",
    r"\bnew pok[eé]mon species\b",
    r"\bnew species of pok[eé]mon\b",
    r"\bnever.before.seen pok[eé]mon\b",
    r"\bnew pok[eé]mon (?:revealed|unveiled)\b",
    r"\bintroducing (?:a |the )?new pok[eé]mon\b",
    r"\bmeet (?:the )?new pok[eé]mon\b",
    r"\bbrand.new pok[eé]mon\b",
    r"\bthree new partner pok[eé]mon\b",
    r"\bnew starter pok[eé]mon\b",
]

GEN10_PATTERNS = [
    r"\bpok[eé]mon winds\b",
    r"\bpok[eé]mon waves\b",
    r"\bgeneration 10\b",
    r"\bgen 10\b",
    r"\bnew first.partner pok[eé]mon\b",
    r"\bnew region\b",
]

FORM_PATTERNS = [
    r"\bmega.evol(?:ved|ution)\b",
    r"\bmega [a-z][a-z-]+\b",
    r"\bnew mega.evolution\b",
    r"\bregional form\b",
    r"\bnew form of\b",
    r"\bgigantamax\b",
    r"\bprimal reversion\b",
]

EXCLUSION_PATTERNS = [
    r"\btrading card\b",
    r"\btcg\b",
    r"\bpromo cards?\b",
    r"\bmerchandise\b",
    r"\bpok[eé]mon center\b",
    r"\bplush\b",
    r"\bchampionships?\b",
    r"\btournament\b",
    r"\bcompetition\b",
    r"\branked battles?\b",
    r"\bcommunity day\b",
    r"\bpok[eé]mon go\b",
    r"\bpok[eé]mon sleep\b",
    r"\bpok[eé]mon unite\b",
    r"\bnetflix\b",
    r"\bspotify\b",
    r"\bsoundtrack\b",
    r"\bmerch\b",
    r"\bbundle\b",
    r"\bprizes?\b",
    r"\bpok[eé]mon league\b",
    r"\blivestream\b",
]

ANTIBOT_PATTERNS = [
    "pardon our interruption",
    "made us think you were a bot",
    "verify you are human",
    "access denied",
    "captcha",
    "enable javascript",
    "please enable cookies",
    "unusual traffic",
    "automated access",
    "checking your browser",
]

STOPWORDS = set("""
about after again also amazon and apple are
available before brand coming discover discovered
edition first for from game games generation
have into introducing latest legends meet mega
more most new news next nintendo now official
our out partner pokemon pokémon region reveal
revealed season see special starter starters
switch their these this three trailer update
version watch what when where which with world
worlds winds waves your
""".split())


# ============================================================
# UTILITAIRES
# ============================================================

def log(message):
    print(
        f"[POKEDEX V{VERSION}] {message}",
        flush=True
    )


def utc_now():
    return dt.datetime.now(
        dt.timezone.utc
    ).isoformat()


def clean(value):
    if value is None:
        return ""

    return " ".join(
        html.unescape(str(value)).split()
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
    except (
        OSError,
        ValueError,
        TypeError
    ):
        return default


def parse_date(value):
    if not value:
        return None

    try:
        raw = str(value).strip()

        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"

        result = dt.datetime.fromisoformat(
            raw
        )

        if result.tzinfo is None:
            result = result.replace(
                tzinfo=dt.timezone.utc
            )

        return result.astimezone(
            dt.timezone.utc
        ).isoformat()

    except (
        ValueError,
        TypeError
    ):
        return None


def age_days(value):
    parsed = parse_date(value)

    if not parsed:
        return 999999

    date = dt.datetime.fromisoformat(
        parsed
    )

    return max(
        0,
        (
            dt.datetime.now(
                dt.timezone.utc
            ) - date
        ).total_seconds() / 86400
    )


def date_timestamp(value):
    parsed = parse_date(value)

    if not parsed:
        return 0

    return dt.datetime.fromisoformat(
        parsed
    ).timestamp()


def fingerprint(value):
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()[:16]


def matches(patterns, value):
    return any(
        re.search(
            pattern,
            value,
            flags=re.IGNORECASE
        )
        for pattern in patterns
    )


def species_id(url):
    result = re.search(
        r"/pokemon-species/(\d+)/?$",
        str(url)
    )

    if result:
        return int(
            result.group(1)
        )

    return None


def normalize_url(value, base=NEWS):
    if not isinstance(value, str):
        return None

    try:
        joined = urllib.parse.urljoin(
            base,
            value
        )

        parsed = urllib.parse.urlparse(
            joined
        )

        if parsed.scheme not in (
            "http", "https"
        ):
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

    except ValueError:
        return None


def is_article_url(url):
    path = urllib.parse.urlparse(
        url
    ).path.lower()

    return (
        path.startswith("/us/news/")
        or path.startswith("/us/pokemon-news/")
    )


def title_from_url(url):
    slug = url.rstrip("/").split("/")[-1]

    return clean(
        slug.replace("-", " ").title()
    )


# ============================================================
# REQUÊTES RÉSEAU
# ============================================================

def fetch_response(
    url,
    timeout=NEWS_TIMEOUT,
    attempts=NEWS_ATTEMPTS
):
    retry_codes = {
        408, 429, 500, 502, 503, 504
    }

    last_error = None

    for attempt in range(
        1,
        attempts + 1
    ):
        try:
            request = urllib.request.Request(
                url,
                headers=HEADERS
            )

            with urllib.request.urlopen(
                request,
                timeout=timeout
            ) as response:

                raw = response.read(
                    8_000_000
                )

                charset = (
                    response.headers.get_content_charset()
                    or "utf-8"
                )

                return {
                    "url": response.geturl(),
                    "status": response.status,
                    "text": raw.decode(
                        charset,
                        errors="replace"
                    ),
                }

        except urllib.error.HTTPError as exc:
            last_error = exc

            # Ne pas insister lorsqu'un serveur
            # interdit explicitement l'accès.
            if exc.code in (
                401, 403, 404
            ):
                raise

            if exc.code not in retry_codes:
                raise

            # 429 : respecter Retry-After lorsqu'il
            # est présent, sans bloquer indéfiniment.
            if exc.code == 429:
                retry_after = (
                    exc.headers.get(
                        "Retry-After"
                    )
                )

                if retry_after:
                    try:
                        wait = min(
                            int(retry_after),
                            60
                        )
                        time.sleep(wait)
                    except ValueError:
                        pass

        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ConnectionError,
            OSError
        ) as exc:
            last_error = exc

        log(
            f"Connexion {attempt}/{attempts} "
            f"échouée : {url} ({last_error})"
        )

        if attempt < attempts:
            time.sleep(
                min(
                    2 ** attempt,
                    10
                )
            )

    raise RuntimeError(
        f"Connexion impossible : {url} "
        f"({last_error})"
    )


def fetch_api_json(url):
    response = fetch_response(
        url,
        timeout=API_TIMEOUT,
        attempts=API_ATTEMPTS
    )

    return json.loads(
        response["text"]
    )


def fetch_news(url):
    return fetch_response(
        url,
        timeout=NEWS_TIMEOUT,
        attempts=NEWS_ATTEMPTS
    )["text"]


# ============================================================
# HTML PARSER
# ============================================================

class PokemonHTMLParser(HTMLParser):

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.links = []
        self.meta = {}
        self.jsonld = []

        self.blocks = []
        self.article_blocks = []

        self.title = ""

        self.ignored = []
        self.article_depth = 0

        self.current_link = None
        self.link_parts = []

        self.current_block = None
        self.block_parts = []
        self.block_depth = 0
        self.block_in_article = False

        self.script_type = None
        self.script_parts = []

        self.in_title = False
        self.title_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "meta":
            key = (
                attrs.get("property")
                or attrs.get("name")
                or ""
            ).lower()

            if key:
                self.meta[key] = (
                    attrs.get("content") or ""
                )

        if tag == "script":
            self.script_type = (
                attrs.get("type") or ""
            ).lower()

            self.script_parts = []
            return

        if tag in (
            "style",
            "noscript",
            "svg",
            "iframe"
        ):
            self.ignored.append(tag)
            return

        if self.ignored:
            return

        if tag == "title":
            self.in_title = True
            self.title_parts = []

        if tag == "article":
            self.article_depth += 1

        if tag == "a":
            self.current_link = attrs.get(
                "href"
            )
            self.link_parts = []

        if tag in (
            "p", "h1", "h2",
            "h3", "h4", "li"
        ):
            if self.current_block is None:
                self.current_block = tag
                self.block_parts = []
                self.block_depth = 1
                self.block_in_article = (
                    self.article_depth > 0
                )

            else:
                self.block_depth += 1

        elif self.current_block is not None:
            self.block_depth += 1

    def handle_data(self, data):
        if self.script_type is not None:
            self.script_parts.append(data)
            return

        if self.ignored:
            return

        if self.in_title:
            self.title_parts.append(data)

        if self.current_link is not None:
            self.link_parts.append(data)

        if self.current_block is not None:
            self.block_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            if (
                self.script_type is not None
                and "ld+json" in self.script_type
            ):
                value = "".join(
                    self.script_parts
                ).strip()

                if value:
                    self.jsonld.append(value)

            self.script_type = None
            self.script_parts = []
            return

        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return

        if tag == "title":
            self.in_title = False
            self.title = clean(
                " ".join(
                    self.title_parts
                )
            )

        if tag == "a":
            if self.current_link:
                self.links.append({
                    "url": self.current_link,
                    "title": clean(
                        " ".join(
                            self.link_parts
                        )
                    )
                })

            self.current_link = None
            self.link_parts = []

        if self.current_block is not None:
            self.block_depth -= 1

            if self.block_depth <= 0:
                value = clean(
                    " ".join(
                        self.block_parts
                    )
                )

                if len(value) >= 20:
                    self.blocks.append(value)

                    if self.block_in_article:
                        self.article_blocks.append(
                            value
                        )

                self.current_block = None
                self.block_parts = []
                self.block_depth = 0

        if tag == "article":
            self.article_depth = max(
                0,
                self.article_depth - 1
            )


def parse_html(raw):
    parser = PokemonHTMLParser()
    parser.feed(raw)
    return parser


# ============================================================
# EXTRACTION DES ARTICLES
# ============================================================

def walk_json(value):
    if isinstance(value, list):
        for item in value:
            yield from walk_json(item)

    elif isinstance(value, dict):
        yield value

        for child in value.values():
            if isinstance(
                child,
                (dict, list)
            ):
                yield from walk_json(child)


def extract_jsonld(parser):
    result = {
        "title": None,
        "published_at": None,
        "body": "",
    }

    for raw in parser.jsonld:
        try:
            root = json.loads(raw)
        except ValueError:
            continue

        for item in walk_json(root):
            kind = item.get(
                "@type", []
            )

            if not isinstance(kind, list):
                kind = [kind]

            if not any(
                str(value).lower() in (
                    "article",
                    "newsarticle",
                    "blogposting"
                )
                for value in kind
            ):
                continue

            if item.get("headline"):
                result["title"] = clean(
                    item["headline"]
                )

            if item.get("datePublished"):
                result["published_at"] = (
                    parse_date(
                        item["datePublished"]
                    )
                )

            body = item.get(
                "articleBody"
            )

            if isinstance(body, str):
                body = clean(body)

                if len(body) > len(
                    result["body"]
                ):
                    result["body"] = body

    return result


def detect_antibot(raw):
    lower = raw.lower()

    return any(
        pattern in lower
        for pattern in ANTIBOT_PATTERNS
    )


def extract_article(raw):
    if detect_antibot(raw):
        return {
            "title": "",
            "published_at": None,
            "body": "",
            "method": "blocked",
            "status": "blocked",
        }

    parser = parse_html(raw)
    structured = extract_jsonld(parser)

    title = (
        structured["title"]
        or parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or parser.title
    )

    published_at = (
        structured["published_at"]
        or parse_date(
            parser.meta.get(
                "article:published_time"
            )
        )
    )

    candidates = [
        (
            "jsonld",
            structured["body"]
        ),
        (
            "article_html",
            clean(
                " ".join(
                    parser.article_blocks
                )
            )
        ),
        (
            "html_blocks",
            clean(
                " ".join(
                    parser.blocks
                )
            )
        ),
    ]

    for method, body in candidates:
        if len(body) >= MIN_ARTICLE_TEXT:
            return {
                "title": clean(title),
                "published_at": published_at,
                "body": body[:60000],
                "method": method,
                "status": "ok",
            }

    return {
        "title": clean(title),
        "published_at": published_at,
        "body": "",
        "method": "title_only",
        "status": "title_only",
    }


# ============================================================
# POKEAPI
# ============================================================

def fetch_pokeapi_catalogue():
    species_data = fetch_api_json(
        API + "/pokemon-species?limit=2000"
    )

    species = species_data.get(
        "results", []
    )

    ids = [
        species_id(
            item.get("url")
        )
        for item in species
    ]

    ids = [
        value for value in ids
        if value is not None
    ]

    if not ids:
        raise RuntimeError(
            "Aucune espèce reçue de PokéAPI"
        )

    max_id = max(ids)

    generation_list = fetch_api_json(
        API + "/generation?limit=100"
    ).get("results", [])

    ranges = []

    for generation in generation_list:
        details = fetch_api_json(
            generation["url"]
        )

        values = [
            species_id(
                item.get("url")
            )
            for item in details.get(
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

        time.sleep(REQUEST_DELAY)

    ranges.sort(
        key=lambda pair: pair[0]
    )

    return {
        "version": VERSION,
        "updated_at": utc_now(),
        "max_id": max_id,
        "ranges": ranges,
        "known_names": sorted({
            item["name"].lower()
            for item in species
        }),
    }


def update_index(catalogue):
    index_path = ROOT / "index.html"

    if not index_path.exists():
        raise RuntimeError(
            "index.html introuvable"
        )

    original = index_path.read_text(
        encoding="utf-8"
    )

    max_id = catalogue["max_id"]

    ranges = [
        list(pair)
        for pair in catalogue["ranges"]
    ]

    if (
        max_id < 1028
        and not any(
            pair[1] >= 1028
            for pair in ranges
        )
    ):
        ranges.append([
            max(1026, max_id + 1),
            1028
        ])

    ranges.sort(
        key=lambda pair: pair[0]
    )

    updated, max_count = re.subn(
        r"MAX=\d+,PAGE=",
        f"MAX={max_id},PAGE=",
        original,
        count=1
    )

    updated, range_count = re.subn(
        r"const genRanges=\[\[.*?\]\];",
        (
            "const genRanges="
            + json.dumps(
                ranges,
                separators=(",", ":")
            )
            + ";"
        ),
        updated,
        count=1,
        flags=re.DOTALL
    )

    if max_count != 1:
        raise RuntimeError(
            "Marqueur MAX introuvable"
        )

    if range_count != 1:
        raise RuntimeError(
            "Marqueur genRanges introuvable"
        )

    updated = updated.replace(
        ".concat(newPokemon).sort((a,b)=>a.id-b.id)",
        (
            ".concat(newPokemon.filter(p=>p.id>MAX))"
            ".sort((a,b)=>a.id-b.id)"
        )
    )

    changed = updated != original

    if changed:
        index_path.write_text(
            updated,
            encoding="utf-8"
        )

    return changed, ranges


def update_pokeapi():
    log("Actualisation PokéAPI")

    cache_path = (
        DATA / "pokeapi-cache.json"
    )

    old_cache = load_json(
        cache_path,
        {}
    ) or {}

    source = "live"
    error = None

    try:
        catalogue = fetch_pokeapi_catalogue()

    except Exception as exc:
        error = str(exc)

        valid_cache = (
            isinstance(
                old_cache.get("max_id"),
                int
            )
            and isinstance(
                old_cache.get("ranges"),
                list
            )
            and isinstance(
                old_cache.get("known_names"),
                list
            )
        )

        if not valid_cache:
            save_json(
                DATA / "catalogue-status.json",
                {
                    "version": VERSION,
                    "checked_at": utc_now(),
                    "status": "unavailable",
                    "source": "none",
                    "error": error,
                    "index_modified": False,
                }
            )

            log(
                "PokéAPI inaccessible sans cache"
            )

            return set()

        catalogue = old_cache
        source = "cache"

        log(
            "Utilisation du cache PokéAPI"
        )

    old_names = set(
        old_cache.get(
            "known_names", []
        )
    )

    new_names = set(
        catalogue["known_names"]
    )

    old_max = old_cache.get(
        "max_id", 0
    )

    newly_detected = []

    # Ne pas traiter tout le catalogue comme
    # nouveau lors du premier lancement.
    if old_names and source == "live":
        newly_detected = sorted(
            new_names - old_names
        )

    changed, ranges = update_index(
        catalogue
    )

    if source == "live":
        save_json(
            cache_path,
            catalogue
        )

    save_json(
        DATA / "catalogue-status.json",
        {
            "version": VERSION,
            "checked_at": utc_now(),
            "status": (
                "ok" if source == "live"
                else "cached"
            ),
            "source": source,
            "pokeapi_max_species_id": (
                catalogue["max_id"]
            ),
            "previous_max_species_id": old_max,
            "generation_ranges": ranges,
            "new_species_count": len(
                newly_detected
            ),
            "new_species_names": newly_detected,
            "index_modified": changed,
            "cache_updated_at": catalogue.get(
                "updated_at"
            ),
            "error": error,
        }
    )

    save_json(
        DATA / "nouvelles-especes-officielles.json",
        {
            "version": VERSION,
            "checked_at": utc_now(),
            "source": source,
            "previous_max_species_id": old_max,
            "current_max_species_id": (
                catalogue["max_id"]
            ),
            "new_species_count": len(
                newly_detected
            ),
            "new_species_names": newly_detected,
            "verified_by_pokeapi": (
                source == "live"
            ),
        }
    )

    log(
        f"Espèces : {catalogue['max_id']}"
    )

    log(
        f"Nouvelles espèces : {len(newly_detected)}"
    )

    log(
        f"Source : {source}"
    )

    return new_names


# ============================================================
# DÉCOUVERTE DES ACTUALITÉS
# ============================================================

def discover_news_page():
    raw = fetch_news(NEWS)
    parser = parse_html(raw)

    articles = []

    for link in parser.links:
        url = normalize_url(
            link["url"]
        )

        if (
            not url
            or not is_article_url(url)
        ):
            continue

        articles.append({
            "url": url,
            "title": (
                link["title"]
                or title_from_url(url)
            ),
            "published_at": None,
            "discovery_method": "html_link",
        })

    return articles


def discover_sitemaps():
    articles = []
    errors = []

    for sitemap in SITEMAPS:
        try:
            raw = fetch_news(sitemap)
            root = ET.fromstring(raw)

            for node in root.iter():
                if (
                    node.tag.split("}")[-1]
                    != "url"
                ):
                    continue

                url = None
                lastmod = None

                for child in node:
                    key = (
                        child.tag.split("}")[-1]
                    )

                    if key == "loc":
                        url = normalize_url(
                            child.text or ""
                        )

                    elif key == "lastmod":
                        lastmod = parse_date(
                            child.text
                        )

                if (
                    url
                    and is_article_url(url)
                ):
                    articles.append({
                        "url": url,
                        "title": title_from_url(
                            url
                        ),
                        "published_at": None,
                        "sitemap_lastmod": lastmod,
                        "discovery_method": "sitemap",
                    })

        except Exception as exc:
            errors.append({
                "source": sitemap,
                "error": str(exc)[:300],
            })

        time.sleep(
            REQUEST_DELAY
        )

    return articles, errors


# ============================================================
# CLASSIFICATION
# ============================================================

def classify_announcement(title, body=""):
    title = clean(title)
    body = clean(body)

    text = title + " " + body

    species = matches(
        SPECIES_PATTERNS,
        text
    )

    gen10 = matches(
        GEN10_PATTERNS,
        text
    )

    form = matches(
        FORM_PATTERNS,
        text
    )

    excluded = matches(
        EXCLUSION_PATTERNS,
        title
    )

    if excluded:
        category = "excluded_news"
        score = -100

    elif species:
        category = "possible_new_species"
        score = 300

    elif gen10:
        category = "generation_10_news"
        score = 220

    elif form:
        category = "new_form_or_mega"
        score = 140

    else:
        category = "general_news"
        score = 0

    return {
        "category": category,
        "priority_score": score,
        "species_pattern": species,
        "generation_10_pattern": gen10,
        "form_pattern": form,
        "excluded": excluded,
    }


def article_score(article):
    title = article.get(
        "title", ""
    )

    body = (
        article.get(
            "body_excerpt", ""
        )
        if article.get(
            "inspection_status"
        ) == "ok"
        else ""
    )

    result = classify_announcement(
        title,
        body
    )

    score = result["priority_score"]

    if score <= 0:
        return score

    date = (
        article.get("published_at")
        or article.get("sitemap_lastmod")
    )

    age = age_days(date)

    if age <= 7:
        score += 70

    elif age <= 30:
        score += 45

    elif age <= 90:
        score += 20

    elif age > 365:
        score -= 30

    return score


def should_inspect(article):
    status = article.get(
        "inspection_status",
        "not_checked"
    )

    if status == "not_checked":
        return True

    if status == "ok":
        days = RECHECK_OK_DAYS

    elif status in (
        "blocked",
        "suspected_generic_content",
        "title_only"
    ):
        days = RECHECK_GENERIC_DAYS

    else:
        days = RECHECK_ERROR_DAYS

    return age_days(
        article.get("inspected_at")
    ) >= days


# ============================================================
# DÉTECTION DES NOMS
# ============================================================

def extract_evidence(text):
    sentences = re.split(
        r"(?<=[.!?])\s+",
        text
    )

    return [
        clean(sentence)[:450]
        for sentence in sentences
        if matches(
            SPECIES_PATTERNS,
            sentence
        )
    ][:12]


def candidate_names(text, known_names):
    names = re.findall(
        r"\b[A-Z][a-z]{3,}"
        r"(?:[-'][A-Z]?[a-z]+)?\b",
        text
    )

    candidates = []

    for name in names:
        lower = name.lower()

        if lower in STOPWORDS:
            continue

        if lower in known_names:
            continue

        if lower in MANUAL_POKEMON:
            continue

        if name not in candidates:
            candidates.append(name)

    return candidates[:30]


# ============================================================
# INSPECTION D'UN ARTICLE
# ============================================================

def inspect_article(article, known_names):
    result = dict(article)

    result["inspected_at"] = utc_now()
    result["verified_new_species"] = False

    result["announcement_evidence"] = []
    result["known_pokemon_mentions"] = []
    result["name_candidates_for_review"] = []

    try:
        raw = fetch_news(
            article["url"]
        )

        extracted = extract_article(
            raw
        )

        if extracted["title"]:
            result["title"] = (
                extracted["title"]
            )

        if extracted["published_at"]:
            result["published_at"] = (
                extracted["published_at"]
            )

        result["extraction_method"] = (
            extracted["method"]
        )

        result["inspection_status"] = (
            extracted["status"]
        )

        body = extracted["body"]

        result["extracted_text_length"] = (
            len(body)
        )

        result["content_fingerprint"] = (
            fingerprint(body)
            if body
            else None
        )

        result["body_excerpt"] = (
            body[:1200]
        )

        result["title_signal_only"] = (
            extracted["status"] != "ok"
        )

        text = (
            result["title"]
            if extracted["status"] != "ok"
            else result["title"] + ". " + body
        )

        classification = classify_announcement(
            result["title"],
            body if extracted["status"] == "ok"
            else ""
        )

        result["announcement_category"] = (
            classification["category"]
        )

        evidence = extract_evidence(
            text
        )

        result["announcement_evidence"] = (
            evidence
        )

        if (
            classification["category"]
            == "possible_new_species"
            and extracted["status"] == "ok"
        ):
            result["name_candidates_for_review"] = (
                candidate_names(
                    " ".join(evidence),
                    known_names
                )
            )

    except urllib.error.HTTPError as exc:
        result["inspection_status"] = (
            "blocked"
            if exc.code in (401, 403, 429)
            else "error"
        )

        result["inspection_error"] = (
            f"HTTP {exc.code}"
        )

    except Exception as exc:
        result["inspection_status"] = "error"
        result["inspection_error"] = (
            str(exc)[:300]
        )

    return result


# ============================================================
# HISTORIQUE
# ============================================================

def load_history():
    stored = load_json(
        DATA / "historique-actualites.json",
        {}
    ) or {}

    history = stored.get(
        "articles", {}
    )

    if not isinstance(history, dict):
        return {}

    return history


def merge_discovered(history, discovered):
    new_count = 0

    for url, article in discovered.items():
        if url not in history:
            history[url] = {
                **article,
                "first_seen": utc_now(),
                "last_seen": utc_now(),
                "inspection_status": "not_checked",
                "verified_new_species": False,
            }

            new_count += 1

        else:
            previous = history[url]

            previous["last_seen"] = utc_now()

            if (
                article.get("discovery_method")
                == "html_link"
            ):
                previous["title"] = (
                    article["title"]
                )

            if article.get(
                "sitemap_lastmod"
            ):
                previous["sitemap_lastmod"] = (
                    article["sitemap_lastmod"]
                )

    return new_count


def mark_duplicate_generic_pages(history):
    fingerprints = {}

    for url, article in history.items():
        fp = article.get(
            "content_fingerprint"
        )

        if fp:
            fingerprints.setdefault(
                fp, []
            ).append(url)

    count = 0

    for urls in fingerprints.values():
        if len(urls) < GENERIC_FINGERPRINT_THRESHOLD:
            continue

        for url in urls:
            article = history[url]

            if article.get(
                "inspection_status"
            ) not in (
                "ok",
                "title_only",
                "suspected_generic_content"
            ):
                continue

            article["inspection_status"] = (
                "suspected_generic_content"
            )

            article["title_signal_only"] = True
            article["name_candidates_for_review"] = []

            count += 1

    return count


# ============================================================
# RAPPORTS
# ============================================================

def build_candidates(history):
    candidates = []
    seen = set()

    for article in history.values():
        if article.get(
            "inspection_status"
        ) != "ok":
            continue

        if article.get(
            "announcement_category"
        ) != "possible_new_species":
            continue

        for name in article.get(
            "name_candidates_for_review",
            []
        ):
            key = (
                name.lower(),
                article.get("url", "")
            )

            if key in seen:
                continue

            seen.add(key)

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
                "evidence": article.get(
                    "announcement_evidence",
                    []
                )[:3],
                "verified": False,
                "status": "requires_manual_review",
            })

    return candidates


def build_priority(history):
    ordered = sorted(
        history.values(),
        key=lambda article: (
            article_score(article),
            date_timestamp(
                article.get("published_at")
                or article.get("sitemap_lastmod")
            )
        ),
        reverse=True
    )

    priority = []

    for article in ordered:
        score = article_score(
            article
        )

        if score <= 0:
            continue

        classification = classify_announcement(
            article.get("title", ""),
            article.get(
                "body_excerpt", ""
            )
            if article.get(
                "inspection_status"
            ) == "ok"
            else ""
        )

        priority.append({
            "title": article.get(
                "title", ""
            ),
            "url": article.get(
                "url", ""
            ),
            "published_at": article.get(
                "published_at"
            ),
            "sitemap_lastmod": article.get(
                "sitemap_lastmod"
            ),
            "priority_score": score,
            "announcement_category": (
                classification["category"]
            ),
            "inspection_status": article.get(
                "inspection_status",
                "not_checked"
            ),
            "title_signal_only": article.get(
                "title_signal_only",
                True
            ),
            "announcement_evidence": article.get(
                "announcement_evidence",
                []
            ),
            "name_candidates_for_review": (
                article.get(
                    "name_candidates_for_review",
                    []
                )
            ),
            "verified_new_species": False,
        })

        if len(priority) >= MAX_PRIORITY_ARTICLES:
            break

    return priority, ordered


# ============================================================
# ACTUALITÉS
# ============================================================

def update_news(known_names):
    log(
        "Surveillance des annonces officielles"
    )

    history = load_history()
    errors = []

    try:
        html_articles = discover_news_page()

    except Exception as exc:
        html_articles = []

        errors.append({
            "source": NEWS,
            "error": str(exc)[:300],
        })

    sitemap_articles, sitemap_errors = (
        discover_sitemaps()
    )

    errors.extend(
        sitemap_errors
    )

    discovered = {}

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
                "sitemap_lastmod": (
                    old.get(
                        "sitemap_lastmod"
                    )
                ),
            }

    new_count = merge_discovered(
        history,
        discovered
    )

    pending = []

    for url, article in history.items():
        if url not in discovered:
            continue

        if not should_inspect(article):
            continue

        score = article_score(article)

        if (
            article.get("inspection_status")
            == "not_checked"
        ):
            score += 20

        pending.append((
            score,
            date_timestamp(
                article.get("published_at")
                or article.get("sitemap_lastmod")
            ),
            url
        ))

    pending.sort(
        reverse=True
    )

    inspected = 0
    blocked = 0

    for _, _, url in pending[
        :MAX_ARTICLES_PER_RUN
    ]:
        history[url] = inspect_article(
            history[url],
            known_names
        )

        inspected += 1

        if history[url].get(
            "inspection_status"
        ) == "blocked":
            blocked += 1

        time.sleep(
            REQUEST_DELAY
        )

    generic_count = (
        mark_duplicate_generic_pages(
            history
        )
    )

    candidates = build_candidates(
        history
    )

    priority, ordered = build_priority(
        history
    )

    if len(history) > MAX_HISTORY_ARTICLES:
        recent = sorted(
            history.items(),
            key=lambda item: (
                article_score(item[1]),
                date_timestamp(
                    item[1].get(
                        "last_seen"
                    )
                )
            ),
            reverse=True
        )

        history = dict(
            recent[:MAX_HISTORY_ARTICLES]
        )

    checked_at = utc_now()

    status = (
        "ok"
        if discovered
        else (
            "degraded_archive_only"
            if history
            else "source_unavailable"
        )
    )

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
        "first_seen_urls": new_count,
        "articles_inspected_this_run": inspected,
        "blocked_articles_this_run": blocked,
        "history_entries": len(
            history
        ),
        "suspected_generic_content": (
            generic_count
        ),
        "candidates_found": len(
            candidates
        ),
        "priority_announcements": len(
            priority
        ),
        "errors": errors,
    }

    save_json(
        DATA / "historique-actualites.json",
        {
            "version": VERSION,
            "checked_at": checked_at,
            "articles": history,
        }
    )

    save_json(
        DATA / "nouveautes-pokemon.json",
        {
            "version": VERSION,
            "checked_at": checked_at,
            "status": status,
            "source": NEWS,
            "articles": ordered[
                :MAX_VISIBLE_ARTICLES
            ],
            "diagnostics": diagnostics,
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
                "Noms potentiels seulement. "
                "Vérification officielle requise "
                "avant ajout au Pokédex."
            ),
        }
    )

    save_json(
        DATA / "annonces-prioritaires.json",
        {
            "version": VERSION,
            "checked_at": checked_at,
            "announcement_count": len(
                priority
            ),
            "announcements": priority,
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
            "first_seen_urls": new_count,
            "articles_inspected": inspected,
            "blocked_articles": blocked,
            "candidate_count": len(
                candidates
            ),
            "new_species_confirmed": 0,
            "source": NEWS,
        }
    )

    log(
        f"Liens HTML : {len(html_articles)}"
    )

    log(
        f"Liens sitemap : {len(sitemap_articles)}"
    )

    log(
        f"Articles découverts : {len(discovered)}"
    )

    log(
        f"Nouvelles URL : {new_count}"
    )

    log(
        f"Articles inspectés : {inspected}"
    )

    log(
        f"Articles bloqués : {blocked}"
    )

    log(
        f"Annonces prioritaires : {len(priority)}"
    )

    log(
        f"Candidats à vérifier : {len(candidates)}"
    )

    log(
        f"Statut actualités : {status}"
    )


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():
    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    log("======================================")
    log("POKEDEX ACETIQUE V5.6")
    log("SURVEILLANCE NOUVELLES ESPÈCES")
    log("======================================")

    known_names = update_pokeapi()

    update_news(
        known_names
    )

    log("======================================")
    log("ACTUALISATION TERMINÉE")
    log("======================================")


if __name__ == "__main__":
    main()
