
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX ACETIQUE V5.4.1
Mise à jour automatique et surveillance officielle.

Python 3.12 — bibliothèque standard uniquement.

Améliorations :
- Connexion avec 5 tentatives et délai de 60 secondes
- Cache local de PokéAPI
- Préservation du site en cas de panne réseau
- Surveillance des annonces officielles
- Priorité aux annonces de nouvelles espèces
- Exclusion des annonces commerciales non pertinentes
- Détection des contenus génériques
- Historique permanent des actualités
- Aucun ajout automatique d'espèce non vérifiée
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


VERSION = "5.4.1"

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

API = "https://pokeapi.co/api/v2"
SITE = "https://www.pokemon.com"
NEWS = SITE + "/us/pokemon-news"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AcetiquePokedex/5.4.1)",
    "Accept": "text/html,application/json,application/xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = 60
MAX_ATTEMPTS = 5
MAX_INSPECTIONS = 35
MAX_VISIBLE = 100
MAX_PRIORITY = 50
MAX_HISTORY = 10000
MIN_TEXT = 150

SITEMAPS = [
    SITE + "/sitemap.xml",
    SITE + "/us/news/sitemap.xml",
]

STRONG = [
    r"\bnewly discovered pok[eé]mon\b",
    r"\bnew species of pok[eé]mon\b",
    r"\bnew pok[eé]mon (?:revealed|unveiled|discovered)\b",
    r"\bmeet (?:the )?new pok[eé]mon\b",
    r"\bintroducing (?:a |the )?new pok[eé]mon\b",
    r"\bnever.before.seen pok[eé]mon\b",
    r"\bnouvelle esp[eè]ce de pok[eé]mon\b",
]

INTEREST = [
    r"\bgen(?:eration)?\s*10\b",
    r"\bnew region\b",
    r"\bnew starters?\b",
    r"\bstarter pok[eé]mon\b",
    r"\bnew pok[eé]mon\b",
    r"\bpok[eé]mon presents\b",
    r"\bnouvelle g[eé]n[eé]ration\b",
]

COMMERCIAL = [
    r"\btcg\b",
    r"\btrading card\b",
    r"\bpromo cards?\b",
    r"\bplush\b",
    r"\bmerchandise\b",
    r"\bpok[eé]mon center\b",
    r"\baccessories\b",
    r"\bproduct showcase\b",
    r"\bpinball\b",
    r"\bfashion\b",
]

EXCLUDED = set("""
pokemon pokémon new newly discovered revealed unveiled
meet introducing official the and from with this these
those your their species generation region starter
starters game games news update updates center trading
card cards mega evolution legends scarlet violet
champions pokopia nintendo switch youtube netflix
world today coming learn more details february january
march april may june july august september october
november december presents quality life improvements
powerful iconic expansion battle battles available
celebrate global challenge museum series season home
event events
""".split())

MANUAL = {
    "browt", "pombon", "gecqua",
    "broussatif", "caloulou", "ogéko",
}


# ============================================================
# OUTILS
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
    path.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(
        value,
        ensure_ascii=False,
        indent=2
    ) + "\n"

    if not path.exists() or path.read_text(
        encoding="utf-8"
    ) != content:
        path.write_text(content, encoding="utf-8")


def load_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def clean(value):
    return " ".join(
        html.unescape(str(value or "")).split()
    )


def parse_date(value):
    if not value:
        return None

    try:
        value = str(value).strip().replace(
            "Z", "+00:00"
        )

        parsed = dt.datetime.fromisoformat(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=dt.timezone.utc
            )

        return parsed.astimezone(
            dt.timezone.utc
        ).isoformat()

    except (TypeError, ValueError):
        return None


def timestamp(value):
    value = parse_date(value)

    if not value:
        return 0

    return dt.datetime.fromisoformat(
        value
    ).timestamp()


def age_days(value):
    if not parse_date(value):
        return 999999

    return max(
        0,
        (
            dt.datetime.now(dt.timezone.utc)
            - dt.datetime.fromisoformat(parse_date(value))
        ).total_seconds() / 86400
    )


# ============================================================
# CONNEXION RÉSEAU AVEC RETENTATIVES
# ============================================================

def fetch_response(url):
    retryable_http = {
        408, 429, 500, 502, 503, 504
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            log(
                f"Connexion {attempt}/{MAX_ATTEMPTS} : {url}"
            )

            request = urllib.request.Request(
                url,
                headers=HEADERS
            )

            with urllib.request.urlopen(
                request,
                timeout=TIMEOUT
            ) as response:
                raw = response.read(8_000_000)

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

        except urllib.error.HTTPError as exc:
            if exc.code not in retryable_http:
                raise

            error = exc

        except (
            TimeoutError,
            socket.timeout,
            urllib.error.URLError,
            ConnectionError,
        ) as exc:
            error = exc

        log(
            f"Échec tentative {attempt} : {error}"
        )

        if attempt == MAX_ATTEMPTS:
            raise RuntimeError(
                f"Connexion impossible après "
                f"{MAX_ATTEMPTS} tentatives : {url}"
            ) from error

        wait = min(2 ** attempt, 30)

        log(
            f"Nouvelle tentative dans {wait} secondes"
        )

        time.sleep(wait)


def fetch(url):
    return fetch_response(url)["text"]


def fetch_json(url):
    return json.loads(fetch(url))


# ============================================================
# URL ET IDENTIFIANTS
# ============================================================

def normalize_url(value, base=NEWS):
    if not isinstance(value, str):
        return None

    parsed = urllib.parse.urlparse(
        urllib.parse.urljoin(base, value)
    )

    if parsed.scheme not in ("http", "https"):
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
        "", "", ""
    ))


def is_article(url):
    path = urllib.parse.urlparse(url).path.lower()

    return (
        path.startswith("/us/news/")
        or path.startswith("/us/pokemon-news/")
    )


def title_from_url(url):
    return clean(
        url.rsplit("/", 1)[-1]
        .replace("-", " ")
        .title()
    )


def species_id(url):
    match = re.search(
        r"/pokemon-species/(\d+)/?$",
        url
    )

    return int(match.group(1)) if match else None


# ============================================================
# ANALYSE HTML
# ============================================================

class ArticleParser(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.links = []
        self.meta = {}
        self.jsonld = []
        self.paragraphs = []

        self.href = None
        self.link_parts = []

        self.text_depth = 0
        self.text_parts = []

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
                self.meta[key] = attrs.get("content", "")

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

        if self.ignored and self.ignored[-1] == tag:
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
                value = clean(
                    " ".join(self.text_parts)
                )

                if len(value) >= 12:
                    self.paragraphs.append(value)

                self.text_parts = []


def parse_html(raw):
    parser = ArticleParser()
    parser.feed(raw)
    return parser


def walk_json(value):
    if isinstance(value, list):
        for item in value:
            yield from walk_json(item)

    elif isinstance(value, dict):
        yield value

        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from walk_json(child)


def metadata(parser):
    title = (
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
    )

    publication = None
    body = ""

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

    for raw in parser.jsonld:
        try:
            root = json.loads(raw)
        except ValueError:
            continue

        for obj in walk_json(root):
            kinds = obj.get("@type", [])

            if not isinstance(kinds, list):
                kinds = [kinds]

            if not any(
                kind in (
                    "Article",
                    "NewsArticle",
                    "BlogPosting"
                )
                for kind in kinds
            ):
                continue

            title = obj.get("headline") or title

            publication = (
                parse_date(obj.get("datePublished"))
                or publication
            )

            candidate = obj.get("articleBody")

            if isinstance(candidate, str):
                if len(candidate) > len(body):
                    body = candidate

    return {
        "title": clean(title),
        "published_at": publication,
        "body": clean(body),
    }


# ============================================================
# POKEAPI AVEC CACHE
# ============================================================

def update_pokeapi():
    log("Actualisation PokéAPI")

    cache_path = DATA / "pokeapi-cache.json"

    cache = load_json(cache_path, {}) or {}

    try:
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
                "Liste des espèces vide"
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
                species_id(item["url"])
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

        ranges.sort(
            key=lambda item: item[0]
        )

        known_names = sorted({
            item["name"].lower()
            for item in species
        })

        cache = {
            "version": VERSION,
            "updated_at": now(),
            "max_id": max_id,
            "ranges": ranges,
            "known_names": known_names,
        }

        save_json(cache_path, cache)

        source = "live"

    except Exception as exc:
        log(
            "PokéAPI indisponible : "
            + str(exc)
        )

        if (
            isinstance(cache.get("max_id"), int)
            and isinstance(cache.get("ranges"), list)
            and isinstance(cache.get("known_names"), list)
        ):
            log(
                "Utilisation du cache local PokéAPI"
            )
            source = "cache"

        else:
            log(
                "Aucun cache valide : "
                "conservation du site actuel"
            )

            save_json(
                DATA / "catalogue-status.json",
                {
                    "version": VERSION,
                    "checked_at": now(),
                    "status": "unavailable",
                    "source": "none",
                    "error": str(exc),
                    "index_modified": False,
                }
            )

            return set()

    max_id = cache["max_id"]
    ranges = [list(pair) for pair in cache["ranges"]]
    known_names = set(cache["known_names"])

    # Conserver les entrées provisoires Gen 10.
    if max_id < 1028 and len(ranges) < 10:
        ranges.append([
            max(1026, max_id + 1),
            1028
        ])

    index_path = ROOT / "index.html"

    original = index_path.read_text(
        encoding="utf-8"
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
        count=1
    )

    if max_count != 1 or range_count != 1:
        raise RuntimeError(
            "Marqueurs MAX/genRanges introuvables "
            "dans index.html"
        )

    # Filtrer les entrées provisoires déjà
    # devenues officielles.
    updated = updated.replace(
        ".concat(newPokemon).sort((a,b)=>a.id-b.id)",
        ".concat(newPokemon.filter(p=>p.id>MAX))"
        ".sort((a,b)=>a.id-b.id)"
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
            "checked_at": now(),
            "status": (
                "ok" if source == "live"
                else "cached"
            ),
            "source": source,
            "pokeapi_max_species_id": max_id,
            "generation_ranges": ranges,
            "index_modified": updated != original,
            "cache_updated_at": cache.get("updated_at"),
        }
    )

    log(
        f"PokéAPI : {max_id} — source {source}"
    )

    return known_names


# ============================================================
# COLLECTE DES ACTUALITÉS
# ============================================================

def discover_html():
    parser = parse_html(fetch(NEWS))
    results = []

    for item in parser.links:
        url = normalize_url(item["url"])

        if not url or not is_article(url):
            continue

        results.append({
            "url": url,
            "title": (
                item["title"]
                or title_from_url(url)
            ),
            "published_at": None,
            "discovery_method": "html_link",
        })

    return results


def discover_sitemaps():
    results = []
    errors = []

    for sitemap in SITEMAPS:
        try:
            root = ET.fromstring(fetch(sitemap))

            for node in root.iter():
                if node.tag.split("}")[-1] != "url":
                    continue

                url = None
                lastmod = None

                for child in node:
                    key = child.tag.split("}")[-1]

                    if key == "loc":
                        url = normalize_url(
                            child.text or ""
                        )

                    elif key == "lastmod":
                        lastmod = parse_date(
                            child.text
                        )

                if url and is_article(url):
                    results.append({
                        "url": url,
                        "title": title_from_url(url),
                        "published_at": None,
                        "sitemap_lastmod": lastmod,
                        "discovery_method": "sitemap",
                    })

                if len(results) >= 7000:
                    break

        except Exception as exc:
            errors.append({
                "source": sitemap,
                "error": str(exc)[:250],
            })

        time.sleep(0.35)

    return results, errors


# ============================================================
# CLASSEMENT DES ARTICLES
# ============================================================

def matches_any(patterns, text):
    return any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in patterns
    )


def article_score(article):
    title = clean(
        article.get("title", "")
    )

    score = 0

    if matches_any(STRONG, title):
        score += 150

    if matches_any(INTEREST, title):
        score += 65

    if re.search(
        r"\b(?:gen(?:eration)?\s*10|"
        r"new species|new starters?|"
        r"newly discovered)\b",
        title,
        re.IGNORECASE
    ):
        score += 100

    if matches_any(COMMERCIAL, title):
        score -= 120

    if re.search(
        r"\b(?:pok[eé]mon go|"
        r"community day|championship|"
        r"tournament|livestream)\b",
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

    if article.get("discovery_method") == "html_link":
        score += 20

    return score


def needs_inspection(article):
    status = article.get(
        "inspection_status",
        "not_checked"
    )

    if status == "not_checked":
        return True

    if status in (
        "suspected_generic_content",
        "insufficient_content"
    ):
        delay = 90

    elif status == "error":
        delay = 7

    else:
        delay = 30

    return age_days(
        article.get("inspected_at")
    ) >= delay


# ============================================================
# ANALYSE DES ARTICLES
# ============================================================

def extract_evidence(text):
    sentences = re.split(
        r"(?<=[.!?])\s+",
        text
    )

    return [
        clean(sentence)[:500]
        for sentence in sentences
        if matches_any(STRONG, sentence)
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
    )[:60]


def candidate_names(evidence, known_names):
    results = []

    for sentence in evidence:
        matches = re.findall(
            r"\b[A-Z][a-z]{3,}"
            r"(?:[-'][A-Z]?[a-z]+)?\b",
            sentence
        )

        for name in matches:
            lower = name.lower()

            if lower in EXCLUDED:
                continue

            if lower in MANUAL:
                continue

            if lower in known_names:
                continue

            if len(name) > 24:
                continue

            if name not in results:
                results.append(name)

    return results[:30]


def inspect_article(article, known_names):
    result = dict(article)

    result["inspected_at"] = now()
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

        info = metadata(parser)

        if info["title"]:
            result["title"] = info["title"]

        if info["published_at"]:
            result["published_at"] = info["published_at"]

        paragraphs = clean(
            " ".join(parser.paragraphs)
        )

        body = max(
            paragraphs,
            info["body"],
            key=len
        )[:60000]

        result["extracted_text_length"] = len(body)

        result["content_fingerprint"] = (
            hashlib.sha256(
                body.encode("utf-8")
            ).hexdigest()[:16]
        )

        if len(body) < MIN_TEXT:
            result["inspection_status"] = (
                "insufficient_content"
            )
            return result

        text = result["title"] + ". " + body

        evidence = extract_evidence(text)

        result["announcement_evidence"] = evidence

        result["known_pokemon_mentions"] = (
            known_mentions(text, known_names)
        )

        if evidence:
            result["name_candidates_for_review"] = (
                candidate_names(
                    evidence,
                    known_names
                )
            )

        result["inspection_status"] = "ok"

    except Exception as exc:
        result["inspection_status"] = "error"
        result["inspection_error"] = str(exc)[:250]

    return result


# ============================================================
# HISTORIQUE ET RAPPORTS
# ============================================================

def update_news(known_names):
    log("Collecte des actualités Pokémon")

    history_path = DATA / "historique-actualites.json"

    stored = load_json(
        history_path,
        {}
    ) or {}

    history = stored.get("articles", {})

    if not isinstance(history, dict):
        history = {}

    previous = load_json(
        DATA / "nouveautes-pokemon.json",
        {}
    ) or {}

    for article in previous.get("articles", []):
        if not isinstance(article, dict):
            continue

        url = normalize_url(
            article.get("url", "")
        )

        if url and is_article(url) and url not in history:
            history[url] = {
                **article,
                "url": url,
                "first_seen": (
                    previous.get("checked_at")
                    or now()
                ),
                "last_seen": now(),
            }

    errors = []

    try:
        html_articles = discover_html()

    except Exception as exc:
        html_articles = []
        errors.append({
            "source": NEWS,
            "error": str(exc)[:250],
        })

    sitemap_articles, sitemap_errors = (
        discover_sitemaps()
    )

    errors.extend(sitemap_errors)

    discovered = {}

    for article in sitemap_articles + html_articles:
        url = article["url"]

        if url not in discovered:
            discovered[url] = article

        elif article["discovery_method"] == "html_link":
            old = discovered[url]

            discovered[url] = {
                **old,
                **article,
                "sitemap_lastmod": old.get(
                    "sitemap_lastmod"
                ),
            }

    new_count = 0

    for url, article in discovered.items():
        if url not in history:
            new_count += 1

            history[url] = {
                **article,
                "first_seen": now(),
                "last_seen": now(),
                "inspection_status": "not_checked",
                "verified_new_species": False,
            }

        else:
            old = history[url]

            old["last_seen"] = now()

            if article["discovery_method"] == "html_link":
                old["title"] = article["title"]

            if article.get("sitemap_lastmod"):
                old["sitemap_lastmod"] = (
                    article["sitemap_lastmod"]
                )

    pending = []

    for url, article in history.items():
        if url not in discovered:
            continue

        if not needs_inspection(article):
            continue

        score = article_score(article)

        if article.get("inspection_status") == "not_checked":
            score += 15

        pending.append((
            score,
            timestamp(
                article.get("published_at")
                or article.get("sitemap_lastmod")
            ),
            url,
        ))

    pending.sort(
        key=lambda item: (item[0], item[1]),
        reverse=True
    )

    inspected_count = 0

    for _, _, url in pending[:MAX_INSPECTIONS]:
        history[url] = inspect_article(
            history[url],
            known_names
        )

        inspected_count += 1
        time.sleep(0.35)

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
            article = history[url]

            article["inspection_status"] = (
                "suspected_generic_content"
            )

            article["announcement_evidence"] = []
            article["name_candidates_for_review"] = []

            generic_count += 1

    candidates = []

    for article in history.values():
        if article.get("inspection_status") != "ok":
            continue

        evidence = article.get(
            "announcement_evidence", []
        )

        for name in article.get(
            "name_candidates_for_review", []
        ):
            candidates.append({
                "name": name,
                "source_title": article.get("title", ""),
                "source_url": article.get("url", ""),
                "published_at": article.get("published_at"),
                "evidence": evidence[:3],
                "verified": False,
                "status": "requires_manual_review",
            })

    unique = {}

    for candidate in candidates:
        key = (
            candidate["name"].lower(),
            candidate["source_url"]
        )

        unique[key] = candidate

    candidates = list(unique.values())

    ordered = sorted(
        history.values(),
        key=lambda article: (
            article_score(article),
            timestamp(
                article.get("published_at")
                or article.get("sitemap_lastmod")
            )
        ),
        reverse=True
    )

    priority = [
        {
            "title": article.get("title", ""),
            "url": article.get("url", ""),
            "published_at": article.get("published_at"),
            "sitemap_lastmod": article.get("sitemap_lastmod"),
            "priority_score": article_score(article),
            "inspection_status": article.get(
                "inspection_status",
                "not_checked"
            ),
            "announcement_evidence": article.get(
                "announcement_evidence", []
            ),
            "name_candidates_for_review": article.get(
                "name_candidates_for_review", []
            ),
        }
        for article in ordered
        if article_score(article) > 0
    ][:MAX_PRIORITY]

    if len(history) > MAX_HISTORY:
        retained = sorted(
            history.items(),
            key=lambda pair: (
                article_score(pair[1]),
                timestamp(pair[1].get("last_seen"))
            ),
            reverse=True
        )

        history = dict(retained[:MAX_HISTORY])

    status = (
        "ok" if discovered
        else "degraded_archive_only" if history
        else "source_unavailable"
    )

    checked_at = now()

    diagnostics = {
        "html_links": len(html_articles),
        "sitemap_links": len(sitemap_articles),
        "unique_discovered_urls": len(discovered),
        "first_seen_urls": new_count,
        "articles_inspected_this_run": inspected_count,
        "history_entries": len(history),
        "suspected_generic_content": generic_count,
        "candidates_found": len(candidates),
        "errors": errors,
    }

    save_json(
        history_path,
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
            "articles": ordered[:MAX_VISIBLE],
            "diagnostics": diagnostics,
        }
    )

    save_json(
        DATA / "pokemon-a-verifier.json",
        {
            "version": VERSION,
            "checked_at": checked_at,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "notice": (
                "Aucun ajout automatique sans "
                "vérification officielle."
            ),
        }
    )

    save_json(
        DATA / "annonces-prioritaires.json",
        {
            "version": VERSION,
            "checked_at": checked_at,
            "announcement_count": len(priority),
            "announcements": priority,
        }
    )

    save_json(
        DATA / "official-news-review.json",
        {
            "version": VERSION,
            "checked_at": checked_at,
            "status": status,
            "review_required": bool(candidates),
            "first_seen_urls": new_count,
            "articles_inspected": inspected_count,
            "candidate_count": len(candidates),
            "new_species_confirmed": 0,
            "source": NEWS,
        }
    )

    log(f"Liens HTML : {len(html_articles)}")
    log(f"Liens sitemap : {len(sitemap_articles)}")
    log(f"Nouvelles URL : {new_count}")
    log(f"Articles inspectés : {inspected_count}")
    log(f"Contenus suspects : {generic_count}")
    log(f"Annonces prioritaires : {len(priority)}")
    log(f"Candidats à vérifier : {len(candidates)}")
    log(f"Statut : {status}")


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():
    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    log("======================================")
    log("POKEDEX ACETIQUE V5.4.1")
    log("MISE À JOUR + CONNEXION ROBUSTE")
    log("======================================")

    known_names = update_pokeapi()

    update_news(known_names)

    log("======================================")
    log("ACTUALISATION TERMINÉE")
    log("======================================")


if __name__ == "__main__":
    main()
