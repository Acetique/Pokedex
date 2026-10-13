
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX ACETIQUE V5.4

Mise à jour automatique du Pokédex et surveillance
des annonces officielles de nouveaux Pokémon.

Python 3.12
Aucune bibliothèque externe nécessaire.

Fichiers produits :
 data/catalogue-status.json
 data/nouveautes-pokemon.json
 data/historique-actualites.json
 data/pokemon-a-verifier.json
 data/official-news-review.json
 data/annonces-prioritaires.json

Sécurité :
 Les articles officiels peuvent produire des candidats
 à vérifier, mais ne modifient jamais automatiquement
 le catalogue des espèces.
"""

import datetime as datetime
import hashlib
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

VERSION = "5.4"

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

POKEAPI = "https://pokeapi.co/api/v2"
OFFICIAL = "https://www.pokemon.com"
NEWS_URL = OFFICIAL + "/us/pokemon-news"

SITEMAPS = [
    OFFICIAL + "/sitemap.xml",
    OFFICIAL + "/us/news/sitemap.xml",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; AcetiquePokedex/5.4)"
    ),
    "Accept": (
        "text/html,application/json,"
        "application/xml,text/xml;q=0.9,*/*;q=0.5"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_ARTICLES_PER_RUN = 35
MAX_VISIBLE_ARTICLES = 100
MAX_PRIORITY_ARTICLES = 50
MAX_HISTORY = 10000
MAX_SITEMAP_URLS = 7000

REQUEST_DELAY = 0.35
REQUEST_TIMEOUT = 25

RECHECK_OK_DAYS = 30
RECHECK_GENERIC_DAYS = 90
RECHECK_ERROR_DAYS = 7

MIN_TEXT_LENGTH = 150
GENERIC_REPEAT_THRESHOLD = 3

NEWS_PREFIXES = (
    "/us/news/",
    "/us/pokemon-news/",
)

# Espèces provisoires déjà intégrées au site.
MANUAL_SPECIES = {
    "browt",
    "pombon",
    "gecqua",
    "broussatif",
    "caloulou",
    "ogéko",
}

# Expressions indiquant potentiellement
# l'annonce d'une nouvelle espèce.
STRONG_PATTERNS = [
    r"\bnewly discovered pok[eé]mon\b",
    r"\bnew species of pok[eé]mon\b",
    r"\bnew pok[eé]mon (?:revealed|unveiled|discovered)\b",
    r"\bmeet (?:the )?new pok[eé]mon\b",
    r"\bintroducing (?:a |the )?new pok[eé]mon\b",
    r"\bnever.before.seen pok[eé]mon\b",
    r"\bbrand.new pok[eé]mon\b",
    r"\bnouveaux pok[eé]mon d[eé]voil[eé]s\b",
    r"\bnouvelle esp[eè]ce de pok[eé]mon\b",
    r"\bpok[eé]mon in[eé]dits?\b",
]

# Expressions utiles pour repérer les annonces.
INTEREST_PATTERNS = [
    r"\bgeneration\s*(?:10|ten|x)\b",
    r"\bgen\s*10\b",
    r"\bnew region\b",
    r"\bstarter pok[eé]mon\b",
    r"\bnew starters?\b",
    r"\bnew pok[eé]mon\b",
    r"\bpok[eé]mon (?:revealed|unveiled)\b",
    r"\bnew pok[eé]mon games?\b",
    r"\bpok[eé]mon presents\b",
    r"\bnouvelle g[eé]n[eé]ration\b",
    r"\bnouveaux pok[eé]mon\b",
]

# Articles commerciaux moins pertinents.
COMMERCIAL_PATTERNS = [
    r"\btcg\b",
    r"\btrading card\b",
    r"\bpromo cards?\b",
    r"\bcard game\b",
    r"\bplush\b",
    r"\bmerchandise\b",
    r"\bpok[eé]mon center\b",
    r"\baccessories\b",
    r"\bcollectibles\b",
    r"\bproduct showcase\b",
    r"\bpinball\b",
    r"\bfashion\b",
    r"\bshopping\b",
    r"\bpre.?release\b",
]

EXCLUDED_WORDS = {
    "pokemon", "pokémon", "new", "newly",
    "discovered", "revealed", "unveiled",
    "meet", "introducing", "official",
    "the", "and", "from", "with", "this",
    "these", "those", "your", "their",
    "species", "generation", "region",
    "starter", "starters", "game",
    "games", "news", "update", "updates",
    "center", "trading", "card", "cards",
    "mega", "evolution", "legends",
    "scarlet", "violet", "champions",
    "pokopia", "nintendo", "switch",
    "youtube", "netflix", "amazon",
    "apple", "world", "today", "coming",
    "learn", "more", "details",
    "february", "january", "march",
    "april", "may", "june", "july",
    "august", "september", "october",
    "november", "december", "presents",
    "quality", "life", "improvements",
    "powerful", "iconic", "expansion",
    "battle", "battles", "type", "types",
    "available", "celebrate", "global",
    "challenge", "museum", "series",
    "season", "home", "event", "events",
}


# ============================================================
# FICHIERS ET RÉSEAU
# ============================================================

def utcnow():
    return datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()


def log(message):
    print(
        f"[POKEDEX V{VERSION}] {message}",
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


def clean(value):
    return " ".join(
        html.unescape(
            str(value or "")
        ).split()
    )


def fetch_response(url):
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
            "text": raw.decode(
                charset,
                errors="replace"
            ),
            "content_type": response.headers.get(
                "Content-Type", ""
            ),
            "final_url": response.geturl(),
        }


def fetch(url):
    return fetch_response(url)["text"]


def fetch_json(url):
    return json.loads(fetch(url))


def parse_date(value):
    if not value:
        return None

    try:
        value = str(value).strip()

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        parsed = datetime.datetime.fromisoformat(
            value
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=datetime.timezone.utc
            )

        return parsed.astimezone(
            datetime.timezone.utc
        ).isoformat()

    except (TypeError, ValueError):
        return None


def timestamp(value):
    parsed = parse_date(value)

    if not parsed:
        return 0

    return datetime.datetime.fromisoformat(
        parsed
    ).timestamp()


def age_days(value):
    parsed = parse_date(value)

    if not parsed:
        return 999999

    point = datetime.datetime.fromisoformat(
        parsed
    )

    return max(
        0,
        (
            datetime.datetime.now(
                datetime.timezone.utc
            ) - point
        ).total_seconds() / 86400
    )


def normalize_url(url, base=NEWS_URL):
    if not isinstance(url, str):
        return None

    parsed = urllib.parse.urlparse(
        urllib.parse.urljoin(base, url)
    )

    if parsed.scheme not in ("https", "http"):
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


def is_article(url):
    path = urllib.parse.urlparse(
        url
    ).path.lower()

    return any(
        path.startswith(prefix)
        and path.rstrip("/") != prefix.rstrip("/")
        for prefix in NEWS_PREFIXES
    )


def title_from_url(url):
    slug = url.rsplit("/", 1)[-1]

    return clean(
        slug.replace("-", " ").title()
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


# ============================================================
# EXTRACTION HTML
# ============================================================

class ArticleParser(HTMLParser):

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.links = []
        self.meta = {}
        self.jsonld = []
        self.paragraphs = []

        self.href = None
        self.link_parts = []

        self.text_depth = 0
        self.text_parts = []
        self.text_tag = None

        self.script_type = None
        self.script_parts = []

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
            self.script_type = attrs.get(
                "type", ""
            ).lower()

            self.script_parts = []
            return

        if tag in ("style", "noscript", "svg"):
            self.ignored.append(tag)
            return

        if self.ignored:
            return

        if tag == "a":
            self.href = attrs.get("href")
            self.link_parts = []

        if tag in ("p", "h1", "h2", "h3"):
            if self.text_depth == 0:
                self.text_tag = tag
                self.text_parts = []

            self.text_depth += 1

        elif self.text_depth > 0:
            self.text_depth += 1

    def handle_data(self, data):
        if self.script_type is not None:
            self.script_parts.append(data)
            return

        if self.ignored:
            return

        if self.href is not None:
            self.link_parts.append(data)

        if self.text_depth > 0:
            self.text_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            if (
                self.script_type is not None
                and "ld+json" in self.script_type
            ):
                raw = "".join(
                    self.script_parts
                ).strip()

                if raw:
                    self.jsonld.append(raw)

            self.script_type = None
            self.script_parts = []
            return

        if (
            self.ignored
            and tag == self.ignored[-1]
        ):
            self.ignored.pop()
            return

        if self.ignored:
            return

        if tag == "a":
            if self.href:
                self.links.append({
                    "url": self.href,
                    "title": clean(
                        " ".join(self.link_parts)
                    )
                })

            self.href = None
            self.link_parts = []

        if self.text_depth > 0:
            self.text_depth -= 1

            if self.text_depth == 0:
                text = clean(
                    " ".join(self.text_parts)
                )

                if len(text) >= 12:
                    self.paragraphs.append(text)

                self.text_parts = []
                self.text_tag = None


def parse_html(raw):
    parser = ArticleParser()
    parser.feed(raw)
    return parser


def jsonld_objects(parser):
    results = []

    for raw in parser.jsonld:
        try:
            results.append(
                json.loads(raw)
            )
        except ValueError:
            continue

    return results


def walk_json(value):
    if isinstance(value, list):
        for item in value:
            yield from walk_json(item)

    elif isinstance(value, dict):
        yield value

        for child in value.values():
            if isinstance(
                child, (dict, list)
            ):
                yield from walk_json(child)


def extract_article_metadata(parser):
    title = (
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
    )

    publication = None
    article_body = ""

    for key in (
        "article:published_time",
        "datepublished",
        "pubdate",
        "date",
    ):
        publication = parse_date(
            parser.meta.get(key)
        )

        if publication:
            break

    for root in jsonld_objects(parser):
        for obj in walk_json(root):
            types = obj.get("@type", [])

            if not isinstance(types, list):
                types = [types]

            if not any(
                item in (
                    "Article",
                    "NewsArticle",
                    "BlogPosting"
                )
                for item in types
            ):
                continue

            title = (
                obj.get("headline")
                or title
            )

            publication = (
                parse_date(
                    obj.get("datePublished")
                )
                or publication
            )

            body = obj.get(
                "articleBody"
            )

            if isinstance(body, str):
                if len(body) > len(article_body):
                    article_body = body

    return {
        "title": clean(title),
        "published_at": publication,
        "article_body": clean(
            article_body
        ),
    }


# ============================================================
# COLLECTE DES ACTUALITÉS
# ============================================================

def discover_html():
    raw = fetch(NEWS_URL)
    parser = parse_html(raw)

    results = []

    for link in parser.links:
        url = normalize_url(
            link["url"]
        )

        if not url or not is_article(url):
            continue

        results.append({
            "url": url,
            "title": (
                link["title"]
                or title_from_url(url)
            ),
            "published_at": None,
            "discovery_method": "html_link",
        })

    return results


def discover_sitemaps():
    articles = []
    errors = []

    for sitemap in SITEMAPS:
        try:
            response = fetch_response(
                sitemap
            )

            raw = response["text"]

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
                    name = child.tag.split(
                        "}"
                    )[-1]

                    if name == "loc":
                        url = normalize_url(
                            child.text or ""
                        )

                    elif name == "lastmod":
                        lastmod = parse_date(
                            child.text
                        )

                if not url or not is_article(url):
                    continue

                articles.append({
                    "url": url,
                    "title": title_from_url(url),
                    "published_at": None,
                    "sitemap_lastmod": lastmod,
                    "discovery_method": "sitemap",
                })

                if len(articles) >= MAX_SITEMAP_URLS:
                    break

        except Exception as exc:
            errors.append({
                "source": sitemap,
                "error": str(exc)[:250],
            })

        time.sleep(REQUEST_DELAY)

    return articles, errors


# ============================================================
# CLASSEMENT INTELLIGENT
# ============================================================

def article_score(article):
    title = clean(
        article.get("title", "")
    )

    score = 0

    strong = any(
        re.search(
            pattern,
            title,
            re.IGNORECASE
        )
        for pattern in STRONG_PATTERNS
    )

    interest = any(
        re.search(
            pattern,
            title,
            re.IGNORECASE
        )
        for pattern in INTEREST_PATTERNS
    )

    commercial = any(
        re.search(
            pattern,
            title,
            re.IGNORECASE
        )
        for pattern in COMMERCIAL_PATTERNS
    )

    if strong:
        score += 150

    if interest:
        score += 65

    if re.search(
        r"\b(?:gen(?:eration)?\s*10|"
        r"new species|new starters?|"
        r"newly discovered)\b",
        title,
        re.IGNORECASE
    ):
        score += 100

    if commercial:
        score -= 120

    if re.search(
        r"\b(?:pok[eé]mon go|"
        r"community day|"
        r"championship|"
        r"tournament|"
        r"museum|"
        r"livestream)\b",
        title,
        re.IGNORECASE
    ):
        score -= 35

    date = (
        article.get("published_at")
        or article.get("sitemap_lastmod")
    )

    age = age_days(date)

    if age <= 7:
        score += 90
    elif age <= 30:
        score += 70
    elif age <= 90:
        score += 45
    elif age <= 180:
        score += 20
    elif age > 365:
        score -= 30

    if article.get(
        "discovery_method"
    ) == "html_link":
        score += 20

    return score


def reinspection_delay(article):
    status = article.get(
        "inspection_status",
        "not_checked"
    )

    if status in (
        "suspected_generic_content",
        "insufficient_content"
    ):
        return RECHECK_GENERIC_DAYS

    if status == "error":
        return RECHECK_ERROR_DAYS

    return RECHECK_OK_DAYS


def needs_inspection(article):
    if article.get(
        "inspection_status"
    ) in (None, "not_checked"):
        return True

    return age_days(
        article.get("inspected_at")
    ) >= reinspection_delay(article)


# ============================================================
# ANALYSE DES NOUVELLES ESPÈCES
# ============================================================

def extract_evidence(text):
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
            for pattern in STRONG_PATTERNS
        ):
            evidence.append(
                clean(sentence)[:500]
            )

    return evidence[:12]


def known_mentions(text, known_names):
    words = set(
        re.findall(
            r"[a-z][a-z'-]+",
            text.lower()
        )
    )

    return sorted(
        words & known_names
    )[:60]


def extract_candidates(evidence, known_names):
    results = []

    for sentence in evidence:
        names = re.findall(
            r"\b[A-Z][a-z]{3,}"
            r"(?:[-'][A-Z]?[a-z]+)?\b",
            sentence
        )

        for name in names:
            lowered = name.lower()

            if lowered in EXCLUDED_WORDS:
                continue

            if lowered in known_names:
                continue

            if lowered in MANUAL_SPECIES:
                continue

            if len(name) > 24:
                continue

            if name not in results:
                results.append(name)

    return results[:30]


def inspect_article(article, known_names):
    result = dict(article)

    result["inspected_at"] = utcnow()
    result["verified_new_species"] = False
    result["announcement_evidence"] = []
    result["known_pokemon_mentions"] = []
    result["name_candidates_for_review"] = []

    try:
        response = fetch_response(
            article["url"]
        )

        parser = parse_html(
            response["text"]
        )

        metadata = extract_article_metadata(
            parser
        )

        if metadata["title"]:
            result["title"] = metadata[
                "title"
            ]

        if metadata["published_at"]:
            result["published_at"] = metadata[
                "published_at"
            ]

        paragraphs = " ".join(
            parser.paragraphs
        )

        body = max(
            (
                paragraphs,
                metadata["article_body"]
            ),
            key=len
        )

        body = clean(body)[:60000]

        result[
            "extracted_text_length"
        ] = len(body)

        result[
            "content_fingerprint"
        ] = hashlib.sha256(
            body.encode("utf-8")
        ).hexdigest()[:16]

        if len(body) < MIN_TEXT_LENGTH:
            result[
                "inspection_status"
            ] = "insufficient_content"

            return result

        text = (
            result["title"]
            + ". "
            + body
        )

        evidence = extract_evidence(
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
            ] = extract_candidates(
                evidence,
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
        ] = str(exc)[:250]

    return result


# ============================================================
# ACTUALISATION POKEAPI
# ============================================================

def update_pokeapi():
    log("Connexion à PokéAPI")

    species = fetch_json(
        POKEAPI
        + "/pokemon-species?limit=2000"
    )["results"]

    ids = [
        species_id(item["url"])
        for item in species
    ]

    ids = [
        number
        for number in ids
        if number is not None
    ]

    if not ids:
        raise RuntimeError(
            "PokéAPI ne retourne aucune espèce."
        )

    max_id = max(ids)

    known_names = {
        item["name"].lower()
        for item in species
    }

    generations = fetch_json(
        POKEAPI + "/generation?limit=100"
    )["results"]

    ranges = []

    for generation in generations:
        details = fetch_json(
            generation["url"]
        )

        values = [
            species_id(item["url"])
            for item in details.get(
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

    # Conserver les trois Pokémon provisoires
    # de génération 10 déjà présents dans
    # la version actuelle du site.
    if max_id < 1028:
        if len(ranges) < 10:
            ranges.append([
                max(1026, max_id + 1),
                1028
            ])

    index_path = ROOT / "index.html"

    original = index_path.read_text(
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
        (
            "const genRanges="
            + json.dumps(
                ranges,
                separators=(",", ":")
            )
            + ";"
        ),
        updated,
        count=1
    )

    if max_matches != 1:
        raise RuntimeError(
            "Marqueur MAX introuvable dans index.html"
        )

    if range_matches != 1:
        raise RuntimeError(
            "Marqueur genRanges introuvable."
        )

    # Éviter les doublons avec les espèces
    # provisoires déjà intégrées.
    updated = updated.replace(
        ".concat(newPokemon).sort((a,b)=>a.id-b.id)",
        (
            ".concat(newPokemon.filter(p=>p.id>MAX))"
            ".sort((a,b)=>a.id-b.id)"
        )
    )

    if updated != original:
        index_path.write_text(
            updated,
            encoding="utf-8"
        )

    save_json(
        DATA / "catalogue-status.json",
        {
            "version": VERSION,
            "checked_at": utcnow(),
            "pokeapi_max_species_id": max_id,
            "generation_ranges": ranges,
            "source": (
                POKEAPI + "/pokemon-species"
            )
        }
    )

    log(
        "Espèce maximale PokéAPI : "
        + str(max_id)
    )

    return known_names


# ============================================================
# HISTORIQUE DES ARTICLES
# ============================================================

def update_news(known_names):
    log("Collecte des actualités officielles")

    history_path = (
        DATA / "historique-actualites.json"
    )

    history_file = load_json(
        history_path,
        {}
    ) or {}

    history = history_file.get(
        "articles", {}
    )

    if not isinstance(history, dict):
        history = {}

    previous = load_json(
        DATA / "nouveautes-pokemon.json",
        {}
    ) or {}

    # Migration depuis les anciennes versions.
    for article in previous.get(
        "articles", []
    ):
        if not isinstance(article, dict):
            continue

        url = normalize_url(
            article.get("url", "")
        )

        if not url or not is_article(url):
            continue

        if url not in history:
            history[url] = {
                **article,
                "url": url,
                "first_seen": (
                    previous.get("checked_at")
                    or utcnow()
                ),
                "last_seen": utcnow(),
            }

    errors = []

    try:
        html_articles = discover_html()
    except Exception as exc:
        html_articles = []

        errors.append({
            "source": NEWS_URL,
            "error": str(exc)[:250]
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

        elif article.get(
            "discovery_method"
        ) == "html_link":
            old = discovered[url]

            discovered[url] = {
                **old,
                **article,
                "sitemap_lastmod": old.get(
                    "sitemap_lastmod"
                )
            }

    first_seen_count = 0

    for url, article in discovered.items():
        if url not in history:
            first_seen_count += 1

            history[url] = {
                **article,
                "first_seen": utcnow(),
                "last_seen": utcnow(),
                "inspection_status": "not_checked",
                "verified_new_species": False,
            }

        else:
            old = history[url]

            old["last_seen"] = utcnow()

            if (
                article.get("discovery_method")
                == "html_link"
            ):
                old["title"] = article["title"]

            if article.get(
                "sitemap_lastmod"
            ):
                old["sitemap_lastmod"] = (
                    article["sitemap_lastmod"]
                )

    # Préparer les articles à inspecter.
    pending = []

    for url, article in history.items():
        if url not in discovered:
            continue

        if not needs_inspection(article):
            continue

        score = article_score(article)

        if article.get(
            "inspection_status"
        ) == "not_checked":
            score += 15

        pending.append((
            score,
            timestamp(
                article.get("published_at")
                or article.get(
                    "sitemap_lastmod"
                )
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
        :MAX_ARTICLES_PER_RUN
    ]:
        history[url] = inspect_article(
            history[url],
            known_names
        )

        inspected_count += 1

        time.sleep(
            REQUEST_DELAY
        )

    # Détecter les réponses identiques
    # retournées par des URL différentes.
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
        if len(urls) < GENERIC_REPEAT_THRESHOLD:
            continue

        for url in urls:
            article = history[url]

            article[
                "inspection_status"
            ] = "suspected_generic_content"

            article[
                "announcement_evidence"
            ] = []

            article[
                "name_candidates_for_review"
            ] = []

            generic_count += 1

    # Récupérer les candidats potentiels.
    candidates = []

    for article in history.values():
        if article.get(
            "inspection_status"
        ) != "ok":
            continue

        evidence = article.get(
            "announcement_evidence", []
        )

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
                "verified": False,
                "status": (
                    "requires_manual_review"
                ),
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

    # Rapport des annonces prioritaires.
    priority = sorted(
        history.values(),
        key=lambda item: (
            article_score(item),
            timestamp(
                item.get("published_at")
                or item.get(
                    "sitemap_lastmod"
                )
            )
        ),
        reverse=True
    )

    priority = [
        {
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
            "priority_score": article_score(
                article
            ),
            "inspection_status": article.get(
                "inspection_status",
                "not_checked"
            ),
            "announcement_evidence": article.get(
                "announcement_evidence", []
            ),
            "name_candidates_for_review": (
                article.get(
                    "name_candidates_for_review",
                    []
                )
            ),
        }
        for article in priority
        if article_score(article) > 0
    ][:MAX_PRIORITY_ARTICLES]

    # Limiter la taille de l'historique.
    if len(history) > MAX_HISTORY:
        ordered = sorted(
            history.items(),
            key=lambda pair: (
                article_score(pair[1]),
                timestamp(
                    pair[1].get("last_seen")
                )
            ),
            reverse=True
        )

        history = dict(
            ordered[:MAX_HISTORY]
        )

    visible = sorted(
        history.values(),
        key=lambda article: (
            article_score(article),
            timestamp(
                article.get("published_at")
                or article.get(
                    "sitemap_lastmod"
                )
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

    checked_at = utcnow()

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
        "first_seen_urls": first_seen_count,
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
        "errors": errors,
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
                "Les candidats nécessitent "
                "une vérification humaine."
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
                "Aucune espèce ajoutée "
                "sans validation officielle."
            )
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
            "first_seen_urls": first_seen_count,
            "articles_inspected": (
                inspected_count
            ),
            "candidate_count": len(
                candidates
            ),
            "new_species_confirmed": 0,
            "source": NEWS_URL,
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
        "Nouvelles URL : "
        + str(first_seen_count)
    )

    log(
        "Articles inspectés : "
        + str(inspected_count)
    )

    log(
        "Contenus suspects : "
        + str(generic_count)
    )

    log(
        "Annonces prioritaires : "
        + str(len(priority))
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

    log("======================================")
    log("POKEDEX ACETIQUE V5.4")
    log("MISE À JOUR + ANNONCES OFFICIELLES")
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
