
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX ACETIQUE V5.5
=====================

Mise à jour du Pokédex et surveillance des annonces
officielles de nouveaux Pokémon.

Python 3.11+.
Bibliothèque standard uniquement.
Aucune clé API payante.

Fonctions :
- PokéAPI avec retentatives et cache local
- Actualisation des générations dans index.html
- Préservation des Pokémon provisoires de génération 10
- Découverte des articles officiels Pokémon
- Extraction HTML, JSON-LD et données structurées
- Détection des pages génériques
- Analyse de secours à partir des titres officiels
- Classement prioritaire des annonces de nouveaux Pokémon
- Distinction espèces, formes et Méga-Évolutions
- Historique permanent
- Aucun ajout automatique d'espèce non confirmée
- Rapports JSON compatibles avec la V5.4.1
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

VERSION = "5.5"

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

API = "https://pokeapi.co/api/v2"
SITE = "https://www.pokemon.com"
NEWS = SITE + "/us/pokemon-news"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/json,application/xml,*/*"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 35
MAX_ATTEMPTS = 4
REQUEST_DELAY = 0.30

MAX_ARTICLES_PER_RUN = 35
MAX_VISIBLE_ARTICLES = 100
MAX_PRIORITY_ARTICLES = 60
MAX_HISTORY_ARTICLES = 10000

MIN_ARTICLE_TEXT = 180
GENERIC_FINGERPRINT_THRESHOLD = 3

# Ne pas réinspecter quotidiennement les anciennes pages
RECHECK_OK_DAYS = 30
RECHECK_GENERIC_DAYS = 14
RECHECK_ERROR_DAYS = 3

SITEMAPS = [
    SITE + "/sitemap.xml",
    SITE + "/us/news/sitemap.xml",
]

# Entrées provisoires déjà prévues dans le site.
MANUAL_POKEMON = {
    "browt",
    "pombon",
    "gecqua",
}

# Indices forts d'une nouvelle espèce.
SPECIES_PATTERNS = [
    r"\bnewly discovered pok[eé]mon\b",
    r"\bnew pok[eé]mon species\b",
    r"\bnew species of pok[eé]mon\b",
    r"\bbrand.new pok[eé]mon\b",
    r"\bnever.before.seen pok[eé]mon\b",
    r"\bnew pok[eé]mon (?:revealed|unveiled)\b",
    r"\bmeet (?:the )?new pok[eé]mon\b",
    r"\bintroducing (?:a |the )?new pok[eé]mon\b",
    r"\bthree new partner pok[eé]mon\b",
]

# Indices généraux de génération 10.
GEN10_PATTERNS = [
    r"\bpok[eé]mon winds\b",
    r"\bpok[eé]mon waves\b",
    r"\bgeneration 10\b",
    r"\bgen 10\b",
    r"\bnew starter pok[eé]mon\b",
    r"\bnew first.partner pok[eé]mon\b",
    r"\bnew region\b",
    r"\bnew pok[eé]mon game\b",
]

# Les formes ne sont pas des espèces supplémentaires.
FORM_PATTERNS = [
    r"\bmega.evol(?:ved|ution)\b",
    r"\bmega [a-z][a-z-]+\b",
    r"\bgigantamax\b",
    r"\bdynamax\b",
    r"\bregional form\b",
    r"\bnew form of\b",
    r"\bprimal reversion\b",
    r"\bterastal\b",
]

LOW_PRIORITY_PATTERNS = [
    r"\btrading card\b",
    r"\btcg\b",
    r"\bmerchandise\b",
    r"\bplush\b",
    r"\bpok[eé]mon center\b",
    r"\bchampionship\b",
    r"\btournament\b",
    r"\bcommunity day\b",
    r"\bpok[eé]mon go\b",
    r"\bnetflix\b",
    r"\bsoundtrack\b",
    r"\bspotify\b",
]

STOPWORDS = set("""
a about after all also an and are as at available
be been before by can coming day discover discovered
edition for from game games get has have here how
in into is it its latest learn legends more most
new news next now of official on or our out
pokemon pokémon presents region reveal revealed
see season show showing soon special starter starters
the their these this three to trailer two update
updates version watch what when where which with
world worlds you your introducing meet first partner
nintendo switch mega evolution evolved generation
winds waves
""".split())


# ============================================================
# FICHIERS ET JOURNAL
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
        or path.read_text(encoding="utf-8") != content
    ):
        path.write_text(
            content,
            encoding="utf-8"
        )


def load_json(path, default=None):
    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError):
        return default


def clean(value):
    if value is None:
        return ""

    return " ".join(
        html.unescape(str(value)).split()
    )


def parse_date(value):
    if not value:
        return None

    try:
        raw = str(value).strip()

        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"

        parsed = dt.datetime.fromisoformat(raw)

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=dt.timezone.utc
            )

        return parsed.astimezone(
            dt.timezone.utc
        ).isoformat()

    except (ValueError, TypeError):
        return None


def age_days(value):
    parsed = parse_date(value)

    if not parsed:
        return 999999

    date = dt.datetime.fromisoformat(parsed)

    return max(
        0,
        (
            dt.datetime.now(dt.timezone.utc) - date
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


# ============================================================
# CONNEXION RÉSEAU
# ============================================================

def fetch_response(url):
    retryable_codes = {
        408, 429, 500, 502, 503, 504
    }

    last_error = None

    for attempt in range(
        1,
        MAX_ATTEMPTS + 1
    ):
        try:
            request = urllib.request.Request(
                url,
                headers=HEADERS
            )

            with urllib.request.urlopen(
                request,
                timeout=REQUEST_TIMEOUT
            ) as response:

                raw = response.read(
                    8_000_000
                )

                charset = (
                    response.headers.get_content_charset()
                    or "utf-8"
                )

                return {
                    "status": response.status,
                    "url": response.geturl(),
                    "text": raw.decode(
                        charset,
                        errors="replace"
                    ),
                    "content_type": response.headers.get(
                        "Content-Type",
                        ""
                    ),
                }

        except urllib.error.HTTPError as exc:
            last_error = exc

            if exc.code not in retryable_codes:
                raise

        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ConnectionError,
            OSError,
        ) as exc:
            last_error = exc

        log(
            f"Échec réseau {attempt}/{MAX_ATTEMPTS} "
            f"sur {url}: {last_error}"
        )

        if attempt < MAX_ATTEMPTS:
            time.sleep(
                min(2 ** attempt, 15)
            )

    raise RuntimeError(
        f"Connexion impossible : {url} "
        f"({last_error})"
    )


def fetch(url):
    return fetch_response(url)["text"]


def fetch_json(url):
    return json.loads(
        fetch(url)
    )


# ============================================================
# NORMALISATION URL
# ============================================================

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


def species_id(url):
    result = re.search(
        r"/pokemon-species/(\d+)/?$",
        str(url)
    )

    if not result:
        return None

    return int(
        result.group(1)
    )


# ============================================================
# HTML PARSER V5.5
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

        self.tag_stack = []
        self.ignored_depth = 0

        self.current_link = None
        self.link_parts = []

        self.current_block = None
        self.block_parts = []
        self.block_depth = 0
        self.block_in_article = False

        self.article_depth = 0

        self.script_type = None
        self.script_parts = []

        self.in_title = False
        self.title_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        self.tag_stack.append(tag)

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
            self.ignored_depth += 1
            return

        if self.ignored_depth:
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

        if self.ignored_depth:
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

        elif self.ignored_depth:
            if tag in (
                "style",
                "noscript",
                "svg",
                "iframe"
            ):
                self.ignored_depth = max(
                    0,
                    self.ignored_depth - 1
                )

        else:
            if tag == "title":
                self.in_title = False
                self.title = clean(
                    " ".join(self.title_parts)
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

        if self.tag_stack:
            self.tag_stack.pop()


def parse_html(raw):
    parser = PokemonHTMLParser()
    parser.feed(raw)
    return parser


# ============================================================
# EXTRACTION JSON-LD
# ============================================================

def walk_json(value):
    if isinstance(value, list):
        for item in value:
            yield from walk_json(item)

    elif isinstance(value, dict):
        yield value

        for child in value.values():
            if isinstance(child, (dict, list)):
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


# ============================================================
# EXTRACTION MULTI-MÉTHODES
# ============================================================

def extract_embedded_article(raw):
    """
    Recherche de contenu dans certaines données
    JSON intégrées aux pages modernes.

    Ne suppose pas qu'une structure particulière
    existe toujours.
    """

    candidates = []

    patterns = [
        r'"articleBody"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"body"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"content"\s*:\s*"((?:\\.|[^"\\])*)"',
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            raw,
            flags=re.IGNORECASE
        ):
            try:
                decoded = json.loads(
                    '"' + match.group(1) + '"'
                )

                if not isinstance(decoded, str):
                    continue

                decoded = re.sub(
                    r"<[^>]+>",
                    " ",
                    decoded
                )

                decoded = clean(decoded)

                if (
                    MIN_ARTICLE_TEXT
                    <= len(decoded)
                    <= 100000
                ):
                    candidates.append(decoded)

            except ValueError:
                continue

    return max(
        candidates,
        key=len,
        default=""
    )


def is_generic_text(text):
    lower = text.lower()

    indicators = [
        "enable javascript",
        "please enable javascript",
        "cookies are required",
        "access denied",
        "verify you are human",
        "something went wrong",
        "page not found",
        "the pokémon company international",
    ]

    hits = sum(
        indicator in lower
        for indicator in indicators
    )

    if hits >= 2 and len(text) < 1500:
        return True

    if len(text) < MIN_ARTICLE_TEXT:
        return True

    return False


def extract_article(raw):
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
        or parse_date(
            parser.meta.get(
                "datepublished"
            )
        )
    )

    methods = {
        "jsonld": structured["body"],
        "article_html": clean(
            " ".join(
                parser.article_blocks
            )
        ),
        "embedded_json": extract_embedded_article(
            raw
        ),
        "html_blocks": clean(
            " ".join(
                parser.blocks
            )
        ),
    }

    # Favoriser un vrai article plutôt qu'une
    # longue navigation ou un pied de page.
    order = [
        "jsonld",
        "article_html",
        "embedded_json",
        "html_blocks",
    ]

    body = ""
    method = "none"

    for candidate_method in order:
        candidate = methods[candidate_method]

        if (
            len(candidate) >= MIN_ARTICLE_TEXT
            and not is_generic_text(candidate)
        ):
            body = candidate
            method = candidate_method
            break

    if not body:
        body = max(
            methods.values(),
            key=len,
            default=""
        )

        method = "fallback"

    return {
        "title": clean(title),
        "published_at": published_at,
        "body": body[:60000],
        "method": method,
        "is_generic": is_generic_text(body),
        "body_length": len(body),
    }


# ============================================================
# POKEAPI ET CACHE
# ============================================================

def fetch_pokeapi_catalogue():
    species_data = fetch_json(
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
        number for number in ids
        if number is not None
    ]

    if not ids:
        raise RuntimeError(
            "Aucune espèce reçue de PokéAPI"
        )

    max_id = max(ids)

    generation_list = fetch_json(
        API + "/generation?limit=100"
    ).get("results", [])

    ranges = []

    for generation in generation_list:
        details = fetch_json(
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
        key=lambda item: item[0]
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

    # Conserver les trois entrées provisoires.
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
            "Marqueur MAX introuvable dans index.html"
        )

    if range_count != 1:
        raise RuntimeError(
            "Marqueur genRanges introuvable "
            "dans index.html"
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
    log("Connexion à PokéAPI")

    cache_path = (
        DATA / "pokeapi-cache.json"
    )

    cache = load_json(
        cache_path,
        {}
    ) or {}

    source = "live"
    error = None

    try:
        catalogue = fetch_pokeapi_catalogue()

        save_json(
            cache_path,
            catalogue
        )

    except Exception as exc:
        error = str(exc)

        log(
            "PokéAPI inaccessible : "
            + error
        )

        valid_cache = (
            isinstance(
                cache.get("max_id"),
                int
            )
            and isinstance(
                cache.get("ranges"),
                list
            )
            and isinstance(
                cache.get("known_names"),
                list
            )
        )

        if valid_cache:
            catalogue = cache
            source = "cache"

            log(
                "Utilisation du cache PokéAPI"
            )

        else:
            log(
                "Aucun cache valide disponible"
            )

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

            return set()

    changed, ranges = update_index(
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
            "generation_ranges": ranges,
            "index_modified": changed,
            "cache_updated_at": catalogue.get(
                "updated_at"
            ),
            "error": error,
        }
    )

    log(
        "Espèces PokéAPI : "
        + str(catalogue["max_id"])
    )

    log(
        "Source : " + source
    )

    return set(
        catalogue["known_names"]
    )


# ============================================================
# DÉCOUVERTE DES ACTUALITÉS
# ============================================================

def discover_news_page():
    raw = fetch(NEWS)
    parser = parse_html(raw)

    articles = []

    for link in parser.links:
        url = normalize_url(
            link["url"]
        )

        if not url or not is_article_url(url):
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
            raw = fetch(sitemap)
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
# CLASSEMENT DES ANNONCES
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

    commercial = matches(
        LOW_PRIORITY_PATTERNS,
        title
    )

    if form:
        category = "new_form_or_mega"

    elif species:
        category = "possible_new_species"

    elif gen10:
        category = "generation_10_news"

    else:
        category = "general_news"

    score = 0

    if species:
        score += 150

    if gen10:
        score += 110

    if form:
        score += 35

    if commercial:
        score -= 100

    if category == "possible_new_species":
        score += 50

    return {
        "category": category,
        "priority_score": score,
        "species_pattern": species,
        "generation_10_pattern": gen10,
        "form_pattern": form,
        "commercial_pattern": commercial,
    }


def article_score(article):
    result = classify_announcement(
        article.get("title", ""),
        article.get("body_excerpt", "")
    )

    score = result["priority_score"]

    date = (
        article.get("published_at")
        or article.get("sitemap_lastmod")
    )

    age = age_days(date)

    if age <= 7:
        score += 90

    elif age <= 30:
        score += 65

    elif age <= 90:
        score += 40

    elif age <= 180:
        score += 15

    elif age > 365:
        score -= 30

    if (
        article.get("discovery_method")
        == "html_link"
    ):
        score += 20

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
        "suspected_generic_content",
        "insufficient_content",
        "title_only"
    ):
        days = RECHECK_GENERIC_DAYS

    else:
        days = RECHECK_ERROR_DAYS

    return age_days(
        article.get("inspected_at")
    ) >= days


# ============================================================
# EXTRACTION DES NOMS POTENTIELS
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


def known_mentions(text, known_names):
    words = set(
        re.findall(
            r"[a-z][a-z'-]+",
            text.lower()
        )
    )

    return sorted(
        words & known_names
    )[:80]


def candidate_names(text, known_names):
    """
    Extraction prudente de noms propres.

    Ces résultats ne sont jamais considérés
    automatiquement comme de nouveaux Pokémon.
    """

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

        if len(name) > 24:
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
        response = fetch_response(
            article["url"]
        )

        extracted = extract_article(
            response["text"]
        )

        if extracted["title"]:
            result["title"] = (
                extracted["title"]
            )

        if extracted["published_at"]:
            result["published_at"] = (
                extracted["published_at"]
            )

        body = extracted["body"]

        result["extracted_text_length"] = (
            len(body)
        )

        result["extraction_method"] = (
            extracted["method"]
        )

        result["content_fingerprint"] = (
            fingerprint(body)
        )

        result["body_excerpt"] = (
            body[:1200]
        )

        if extracted["is_generic"]:
            result["inspection_status"] = (
                "title_only"
            )

            result["extraction_warning"] = (
                "Contenu générique ou incomplet. "
                "Analyse limitée au titre officiel."
            )

            text = result["title"]

        else:
            result["inspection_status"] = "ok"

            text = (
                result["title"]
                + ". "
                + body
            )

        classification = classify_announcement(
            result["title"],
            "" if extracted["is_generic"] else body
        )

        result["announcement_category"] = (
            classification["category"]
        )

        result["title_signal_only"] = (
            extracted["is_generic"]
        )

        evidence = extract_evidence(
            text
        )

        result["announcement_evidence"] = (
            evidence
        )

        result["known_pokemon_mentions"] = (
            known_mentions(
                text,
                known_names
            )
        )

        if (
            classification["category"]
            == "possible_new_species"
        ):
            result["name_candidates_for_review"] = (
                candidate_names(
                    " ".join(evidence),
                    known_names
                )
            )

    except Exception as exc:
        result["inspection_status"] = "error"
        result["inspection_error"] = (
            str(exc)[:300]
        )

    return result


# ============================================================
# DÉTECTION DES CONTENUS GÉNÉRIQUES
# ============================================================

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
        if (
            len(urls)
            < GENERIC_FINGERPRINT_THRESHOLD
        ):
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

            article["extraction_warning"] = (
                "Même contenu extrait sur plusieurs "
                "articles différents. Le titre "
                "reste utilisable comme indice."
            )

            article["announcement_evidence"] = (
                extract_evidence(
                    article.get("title", "")
                )
            )

            article["name_candidates_for_review"] = []

            count += 1

    return count


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


# ============================================================
# RAPPORTS DE SURVEILLANCE
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

    results = []

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

        results.append({
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
                False
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

        if len(results) >= MAX_PRIORITY_ARTICLES:
            break

    return results, ordered


# ============================================================
# SURVEILLANCE PRINCIPALE
# ============================================================

def update_news(known_names):
    log(
        "Surveillance des actualités officielles"
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

    # Priorité aux articles nouveaux, récents,
    # et aux annonces de génération 10.
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

    for _, _, url in pending[
        :MAX_ARTICLES_PER_RUN
    ]:
        history[url] = inspect_article(
            history[url],
            known_names
        )

        inspected += 1

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
                "avant tout ajout au Pokédex."
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
        f"Contenus génériques : {generic_count}"
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
# MAIN
# ============================================================

def main():
    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    log("======================================")
    log("POKEDEX ACETIQUE V5.5")
    log("SURVEILLANCE OFFICIELLE AMÉLIORÉE")
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
