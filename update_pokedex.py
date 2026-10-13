
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
POKEDEX ACETIQUE V5.8
=====================

Mise à jour automatique du Pokédex.

Python 3.10+
Bibliothèque standard uniquement.
Aucune clé API payante.

V5.8 :
- Catalogue PokéAPI
- Comparaison des espèces
- Conservation du cache
- Mise à jour de index.html
- Protection des Pokémon provisoires
- Surveillance des annonces officielles
- Vérification du XML avant analyse
- Détection des pages HTML / antibot
- Nombre limité de sitemaps
- Aucun téléchargement d'article
- Conservation des historiques V5.5 à V5.7
- Diagnostics détaillés
"""

from __future__ import annotations

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


# ==========================================================
# CONFIGURATION
# ==========================================================

VERSION = "5.8"

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

API = "https://pokeapi.co/api/v2"

BASE = "https://www.pokemon.com"
NEWS = BASE + "/us/pokemon-news"

SITEMAP_ROOT = BASE + "/sitemap.xml"

# Seulement les sitemaps susceptibles de contenir
# les annonces recherchées.
TARGET_SITEMAPS = (
    "/us/news/sitemap.xml",
    "/us/features/sitemap.xml",
)

MAX_SITEMAPS = 4
MAX_PRIORITY = 60
MAX_NEWS_DISPLAY = 100
MAX_HISTORY = 10000

REQUEST_DELAY = 0.2

HEADERS = {
    "User-Agent": (
        "AcetiquePokedex/5.8 "
        "(public catalogue updater)"
    ),
    "Accept": (
        "application/json,application/xml,"
        "text/xml,text/html,*/*"
    ),
    "Accept-Language": "en-US,en;q=0.8",
}

PROVISIONAL = {
    "browt",
    "pombon",
    "gecqua",
}

ANTIBOT_MARKERS = (
    "pardon our interruption",
    "made us think you were a bot",
    "verify you are human",
    "access denied",
    "captcha",
    "checking your browser",
    "unusual traffic",
    "enable javascript",
)


# ==========================================================
# UTILITAIRES
# ==========================================================

def now():
    return dt.datetime.now(
        dt.timezone.utc
    ).isoformat()


def log(message):
    print(
        f"[POKEDEX V{VERSION}] {message}",
        flush=True
    )


def load(path, fallback):
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
        return fallback


def write(path, value):
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


def clean(value):
    return " ".join(
        html.unescape(
            str(value or "")
        ).split()
    )


def species_id(url):
    match = re.search(
        r"/pokemon-species/(\d+)/?$",
        str(url)
    )

    return (
        int(match.group(1))
        if match
        else None
    )


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def date_score(article):
    raw = (
        article.get("published_at")
        or article.get("sitemap_lastmod")
    )

    if not raw:
        return 0

    try:
        date = dt.datetime.fromisoformat(
            str(raw).replace(
                "Z", "+00:00"
            )
        )

        if date.tzinfo is None:
            date = date.replace(
                tzinfo=dt.timezone.utc
            )

        days = (
            dt.datetime.now(
                dt.timezone.utc
            ) - date
        ).days

        if days <= 7:
            return 60

        if days <= 30:
            return 35

        if days <= 90:
            return 15

    except ValueError:
        pass

    return 0


# ==========================================================
# RÉSEAU
# ==========================================================

def request(
    url,
    timeout=25,
    attempts=2
):
    last_error = None

    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url,
                headers=HEADERS
            )

            with urllib.request.urlopen(
                req,
                timeout=timeout
            ) as response:

                raw = response.read(
                    10_000_000
                )

                return {
                    "text": raw.decode(
                        response.headers.get_content_charset()
                        or "utf-8",
                        errors="replace"
                    ),
                    "content_type": (
                        response.headers.get(
                            "Content-Type", ""
                        )
                    ),
                    "status": response.status,
                }

        except urllib.error.HTTPError as exc:
            last_error = exc

            # Respecter les refus et limitations.
            if exc.code in (
                400, 401, 403, 404, 429
            ):
                break

        except (
            urllib.error.URLError,
            TimeoutError,
            OSError
        ) as exc:
            last_error = exc

        if attempt + 1 < attempts:
            time.sleep(
                min(
                    2 ** (attempt + 1),
                    8
                )
            )

    raise RuntimeError(
        f"{url}: {last_error}"
    )


def api_json(url):
    response = request(
        url,
        timeout=40,
        attempts=4
    )

    return json.loads(
        response["text"]
    )


# ==========================================================
# CATALOGUE POKEAPI
# ==========================================================

def fetch_catalogue():
    response = api_json(
        f"{API}/pokemon-species?limit=2000"
    )

    species = []

    for item in response.get(
        "results", []
    ):
        sid = species_id(
            item.get("url")
        )

        name = item.get(
            "name", ""
        ).lower()

        if sid is not None and name:
            species.append({
                "id": sid,
                "name": name,
            })

    if not species:
        raise RuntimeError(
            "Catalogue PokéAPI vide"
        )

    species.sort(
        key=lambda item: item["id"]
    )

    generations = api_json(
        f"{API}/generation?limit=100"
    ).get("results", [])

    ranges = []

    for generation in generations:
        detail = api_json(
            generation["url"]
        )

        ids = [
            species_id(
                item.get("url")
            )
            for item in detail.get(
                "pokemon_species", []
            )
        ]

        ids = [
            value
            for value in ids
            if value is not None
        ]

        if ids:
            ranges.append([
                min(ids),
                max(ids)
            ])

        time.sleep(REQUEST_DELAY)

    ranges.sort(
        key=lambda item: item[0]
    )

    return {
        "version": VERSION,
        "updated_at": now(),
        "max_id": max(
            item["id"]
            for item in species
        ),
        "ranges": ranges,
        "known_names": sorted({
            item["name"]
            for item in species
        }),
        "species": species,
    }


def update_index(catalogue):
    path = ROOT / "index.html"

    if not path.exists():
        raise RuntimeError(
            "index.html introuvable"
        )

    original = path.read_text(
        encoding="utf-8"
    )

    maximum = catalogue["max_id"]

    ranges = [
        list(item)
        for item in catalogue["ranges"]
    ]

    # Préserver les IDs provisoires tant
    # qu'ils ne sont pas dans PokéAPI.
    if maximum < 1028:
        ranges.append([
            max(maximum + 1, 1026),
            1028
        ])

    ranges.sort(
        key=lambda item: item[0]
    )

    updated, count_max = re.subn(
        r"\bMAX\s*=\s*\d+\s*,\s*PAGE\s*=",
        f"MAX={maximum},PAGE=",
        original,
        count=1
    )

    updated, count_ranges = re.subn(
        r"\bconst\s+genRanges\s*="
        r"\s*\[\[.*?\]\]\s*;",
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

    if (
        count_max != 1
        or count_ranges != 1
    ):
        raise RuntimeError(
            "Marqueurs MAX/PAGE ou "
            "genRanges introuvables"
        )

    # Empêcher les doublons avec
    # les espèces officielles.
    updated = re.sub(
        r"\.concat\(newPokemon\)"
        r"(?!\.filter)",
        (
            ".concat("
            "newPokemon.filter(p=>p.id>MAX)"
            ")"
        ),
        updated
    )

    changed = (
        updated != original
    )

    if changed:
        path.write_text(
            updated,
            encoding="utf-8"
        )

    return changed, ranges


def update_pokeapi():
    cache_path = (
        DATA / "pokeapi-cache.json"
    )

    previous = load(
        cache_path, {}
    )

    if not isinstance(
        previous, dict
    ):
        previous = {}

    source = "live"
    error = None

    try:
        catalogue = fetch_catalogue()

    except Exception as exc:
        error = str(exc)

        required = (
            "max_id",
            "ranges",
            "known_names"
        )

        if not all(
            key in previous
            for key in required
        ):
            write(
                DATA / "catalogue-status.json",
                {
                    "version": VERSION,
                    "checked_at": now(),
                    "status": "unavailable",
                    "source": "none",
                    "error": error,
                    "index_modified": False,
                }
            )

            log(
                "PokéAPI inaccessible "
                "sans cache valide"
            )

            return set(), "unavailable"

        catalogue = previous
        source = "cache"

    old_names = set(
        previous.get(
            "known_names", []
        )
    )

    new_names = set(
        catalogue["known_names"]
    )

    added = (
        sorted(
            new_names - old_names
        )
        if old_names and source == "live"
        else []
    )

    changed = False
    ranges = catalogue["ranges"]

    try:
        changed, ranges = update_index(
            catalogue
        )

    except Exception as exc:
        message = str(exc)

        error = (
            f"{error}; {message}"
            if error
            else message
        )

        log(
            f"Attention index.html : {message}"
        )

    if source == "live":
        write(
            cache_path,
            catalogue
        )

    if error:
        status = "partial"

    elif source == "cache":
        status = "cached"

    else:
        status = "ok"

    write(
        DATA / "catalogue-status.json",
        {
            "version": VERSION,
            "checked_at": now(),
            "status": status,
            "source": source,
            "pokeapi_max_species_id": (
                catalogue["max_id"]
            ),
            "previous_max_species_id": (
                previous.get("max_id")
            ),
            "generation_ranges": ranges,
            "new_species_count": len(
                added
            ),
            "new_species_names": added,
            "index_modified": changed,
            "error": error,
        }
    )

    write(
        DATA / "nouvelles-especes-officielles.json",
        {
            "version": VERSION,
            "checked_at": now(),
            "source": source,
            "new_species_count": len(
                added
            ),
            "new_species_names": added,
            "verified_by_pokeapi": (
                source == "live"
            ),
        }
    )

    log(
        f"Espèces PokéAPI : "
        f"{catalogue['max_id']} | "
        f"nouvelles : {len(added)} | "
        f"source : {source}"
    )

    return new_names, status


# ==========================================================
# CLASSIFICATION DES ANNONCES
# ==========================================================

SPECIES_PATTERNS = [
    r"newly discovered pok[eé]mon",
    r"new pok[eé]mon species",
    r"new species of pok[eé]mon",
    r"never.before.seen pok[eé]mon",
    r"new pok[eé]mon (?:revealed|unveiled)",
    r"introducing (?:a |the )?new pok[eé]mon",
    r"new starter pok[eé]mon",
    r"new partner pok[eé]mon",
]

GEN10_PATTERNS = [
    r"pok[eé]mon winds",
    r"pok[eé]mon waves",
    r"generation 10",
    r"gen 10",
    r"new first.partner pok[eé]mon",
]

FORM_PATTERNS = [
    r"mega.evolution",
    r"mega.evolved",
    r"mega [a-z][a-z-]+",
    r"regional form",
    r"new form of",
    r"gigantamax",
]

EXCLUDE_PATTERNS = [
    r"trading card",
    r"\btcg\b",
    r"pok[eé]mon center",
    r"championship",
    r"tournament",
    r"community day",
    r"pok[eé]mon go",
    r"pok[eé]mon sleep",
    r"pok[eé]mon unite",
    r"soundtrack",
    r"plush",
    r"merchandise",
    r"pok[eé]mon league",
    r"promo card",
]


def classify(title):
    title = clean(title)

    def found(patterns):
        return any(
            re.search(
                pattern,
                title,
                re.IGNORECASE
            )
            for pattern in patterns
        )

    if found(EXCLUDE_PATTERNS):
        return "excluded_news", 0

    if found(SPECIES_PATTERNS):
        return "possible_new_species", 300

    if found(GEN10_PATTERNS):
        return "generation_10_news", 220

    if found(FORM_PATTERNS):
        return "new_form_or_mega", 140

    return "general_news", 0


# ==========================================================
# DÉCOUVERTE DES LIENS
# ==========================================================

class LinksParser(HTMLParser):

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.links = []
        self.current = None
        self.parts = []

    def handle_starttag(
        self,
        tag,
        attrs
    ):
        if tag == "a":
            self.current = dict(
                attrs
            ).get("href")

            self.parts = []

    def handle_data(self, data):
        if self.current is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if (
            tag == "a"
            and self.current is not None
        ):
            self.links.append((
                self.current,
                clean(
                    " ".join(
                        self.parts
                    )
                )
            ))

            self.current = None
            self.parts = []


def normalize_url(url):
    if not url:
        return None

    try:
        parsed = urllib.parse.urlsplit(
            urllib.parse.urljoin(
                NEWS,
                url
            )
        )

        if parsed.hostname not in (
            "pokemon.com",
            "www.pokemon.com"
        ):
            return None

        path = parsed.path.rstrip("/")

        if not (
            path.startswith("/us/news/")
            or path.startswith(
                "/us/pokemon-news/"
            )
        ):
            return None

        return BASE + path

    except ValueError:
        return None


def title_from_url(url):
    slug = str(url).rstrip(
        "/"
    ).rsplit("/", 1)[-1]

    return clean(
        slug.replace(
            "-", " "
        ).title()
    )


def detect_block(raw):
    lower = raw.lower()

    return any(
        marker in lower
        for marker in ANTIBOT_MARKERS
    )


def response_kind(response):
    """
    Vérifier la nature de la réponse
    avant de tenter une analyse XML.
    """
    text = response["text"].lstrip(
        "\ufeff \r\n\t"
    )

    lower = text[:4000].lower()

    if detect_block(text):
        return "blocked"

    if (
        lower.startswith("<!doctype html")
        or lower.startswith("<html")
    ):
        return "html"

    if (
        lower.startswith("<?xml")
        or lower.startswith("<urlset")
        or lower.startswith("<sitemapindex")
    ):
        return "xml"

    return "unknown"


def get_news_html():
    response = request(
        NEWS,
        attempts=1
    )

    if detect_block(
        response["text"]
    ):
        return {}, "blocked"

    parser = LinksParser()

    parser.feed(
        response["text"]
    )

    found = {}

    for href, title in parser.links:
        url = normalize_url(href)

        if not url:
            continue

        found[url] = {
            "url": url,
            "title": (
                title
                if len(title) >= 8
                else title_from_url(url)
            ),
            "discovery_method": "html_link",
        }

    return found, "ok"


# ==========================================================
# SITEMAPS V5.8
# ==========================================================

def parse_sitemap(response):
    kind = response_kind(
        response
    )

    if kind != "xml":
        raise ValueError(
            f"Réponse non XML : {kind}"
        )

    root = ET.fromstring(
        response["text"]
    )

    root_type = local_name(
        root.tag
    ).lower()

    urls = []
    children = []

    if root_type == "sitemapindex":
        for node in root:
            if local_name(
                node.tag
            ) != "sitemap":
                continue

            loc = next(
                (
                    child.text
                    for child in node
                    if local_name(
                        child.tag
                    ) == "loc"
                ),
                None
            )

            if loc:
                children.append(
                    loc.strip()
                )

    elif root_type == "urlset":
        for node in root:
            if local_name(
                node.tag
            ) != "url":
                continue

            loc = None
            lastmod = None

            for child in node:
                name = local_name(
                    child.tag
                )

                if name == "loc":
                    loc = child.text

                elif name == "lastmod":
                    lastmod = child.text

            if loc:
                urls.append((
                    loc.strip(),
                    lastmod
                ))

    else:
        raise ValueError(
            "Type de sitemap non reconnu : "
            + root_type
        )

    return root_type, urls, children


def safe_sitemap_url(url):
    try:
        parsed = urllib.parse.urlsplit(
            url
        )

        return (
            parsed.scheme == "https"
            and parsed.hostname in (
                "pokemon.com",
                "www.pokemon.com"
            )
            and parsed.path.endswith(
                "/sitemap.xml"
            )
        )

    except ValueError:
        return False


def get_news_sitemap():
    """
    Consulter le sitemap racine,
    puis seulement les sous-sitemaps
    d'actualités pertinents.

    Ne pas analyser du HTML comme du XML.
    Ne pas parcourir toutes les langues.
    """
    found = {}
    errors = []

    queue = [
        SITEMAP_ROOT
    ]

    seen = set()

    counts = {
        "xml_ok": 0,
        "html_instead_of_xml": 0,
        "blocked": 0,
        "invalid_xml": 0,
        "other_errors": 0,
    }

    while (
        queue
        and len(seen) < MAX_SITEMAPS
    ):
        url = queue.pop(0)

        if url in seen:
            continue

        if not safe_sitemap_url(url):
            continue

        seen.add(url)

        try:
            response = request(
                url,
                attempts=1
            )

            kind = response_kind(
                response
            )

            if kind == "blocked":
                counts["blocked"] += 1

                errors.append({
                    "source": url,
                    "type": "blocked",
                    "error": (
                        "Protection ou refus "
                        "du serveur détecté"
                    ),
                })

                continue

            if kind != "xml":
                counts[
                    "html_instead_of_xml"
                ] += 1

                errors.append({
                    "source": url,
                    "type": "not_xml",
                    "error": (
                        "Le serveur a renvoyé "
                        f"du contenu {kind}, "
                        "pas un sitemap XML"
                    ),
                })

                continue

            try:
                root_type, urls, children = (
                    parse_sitemap(
                        response
                    )
                )

            except ET.ParseError as exc:
                counts[
                    "invalid_xml"
                ] += 1

                errors.append({
                    "source": url,
                    "type": "invalid_xml",
                    "error": str(exc),
                })

                continue

            counts["xml_ok"] += 1

            if root_type == "sitemapindex":
                for child in children:
                    parsed = urllib.parse.urlsplit(
                        child
                    )

                    # Ne suivre que les sitemaps
                    # d'actualités anglais.
                    if (
                        parsed.path
                        in TARGET_SITEMAPS
                        and child not in seen
                        and child not in queue
                    ):
                        queue.append(
                            child
                        )

            elif root_type == "urlset":
                for loc, lastmod in urls:
                    normalized = normalize_url(
                        loc
                    )

                    if not normalized:
                        continue

                    found[normalized] = {
                        "url": normalized,
                        "title": title_from_url(
                            normalized
                        ),
                        "sitemap_lastmod": lastmod,
                        "discovery_method": "sitemap",
                    }

        except Exception as exc:
            counts[
                "other_errors"
            ] += 1

            errors.append({
                "source": url,
                "type": "request_error",
                "error": str(exc)[:250],
            })

        time.sleep(
            REQUEST_DELAY
        )

    return (
        found,
        errors,
        len(seen),
        counts
    )


# ==========================================================
# ACTUALISATION DES ANNONCES
# ==========================================================

def update_news():
    stored = load(
        DATA / "historique-actualites.json",
        {}
    )

    history = (
        stored.get(
            "articles", {}
        )
        if isinstance(
            stored, dict
        )
        else {}
    )

    if not isinstance(
        history, dict
    ):
        history = {}

    errors = []

    sitemap, sitemap_errors, sitemap_count, sitemap_counts = (
        get_news_sitemap()
    )

    errors.extend(
        sitemap_errors
    )

    try:
        page, page_status = (
            get_news_html()
        )

    except Exception as exc:
        page = {}
        page_status = "unavailable"

        errors.append({
            "source": NEWS,
            "type": "news_page_error",
            "error": str(exc)[:250],
        })

    discovered = {
        **sitemap,
        **page
    }

    new_urls = 0
    stamp = now()

    for url, data in discovered.items():
        previous = history.get(
            url
        )

        if not isinstance(
            previous, dict
        ):
            previous = {
                "first_seen": stamp
            }

            new_urls += 1

        # Préférer les titres visibles de la
        # page d'actualités lorsqu'ils existent.
        title = (
            page[url]["title"]
            if url in page
            else (
                previous.get("title")
                or data["title"]
            )
        )

        category, score = classify(
            title
        )

        previous.update({
            "url": url,
            "title": title,
            "last_seen": stamp,
            "announcement_category": category,
            "priority_score": score,
            "inspection_status": "metadata_only",
            "title_signal_only": True,
            "verified_new_species": False,
        })

        if data.get(
            "sitemap_lastmod"
        ):
            previous["sitemap_lastmod"] = (
                data["sitemap_lastmod"]
            )

        history[url] = previous

    # Reclassifier les archives sans perdre
    # les anciens articles.
    for url, article in history.items():
        if not isinstance(
            article, dict
        ):
            continue

        title = (
            article.get("title")
            or title_from_url(url)
        )

        category, score = classify(
            title
        )

        article.update({
            "url": url,
            "title": title,
            "announcement_category": category,
            "priority_score": score,
            "inspection_status": "metadata_only",
            "title_signal_only": True,
            "verified_new_species": False,
        })

        # Les anciens noms candidats
        # non vérifiés ne sont pas
        # considérés comme confirmés.
        article.pop(
            "name_candidates_for_review",
            None
        )

    valid_history = [
        (url, article)
        for url, article in history.items()
        if isinstance(
            article, dict
        )
    ]

    valid_history.sort(
        key=lambda item: (
            item[1].get(
                "last_seen", ""
            )
        ),
        reverse=True
    )

    history = dict(
        valid_history[
            :MAX_HISTORY
        ]
    )

    ordered = sorted(
        history.values(),
        key=lambda article: (
            article.get(
                "priority_score", 0
            ) + date_score(article),
            article.get(
                "sitemap_lastmod"
            ) or "",
            article.get(
                "title"
            ) or "",
        ),
        reverse=True
    )

    priority = []

    for article in ordered:
        base_score = article.get(
            "priority_score", 0
        )

        if base_score <= 0:
            continue

        priority.append({
            "title": article["title"],
            "url": article["url"],
            "published_at": article.get(
                "published_at"
            ),
            "sitemap_lastmod": article.get(
                "sitemap_lastmod"
            ),
            "priority_score": (
                base_score
                + date_score(article)
            ),
            "announcement_category": (
                article[
                    "announcement_category"
                ]
            ),
            "inspection_status": (
                "metadata_only"
            ),
            "title_signal_only": True,
            "verified_new_species": False,
            "name_candidates_for_review": [],
        })

        if len(priority) >= MAX_PRIORITY:
            break

    if discovered:
        status = "ok"

    elif history:
        status = "degraded_archive_only"

    else:
        status = "source_unavailable"

    diagnostics = {
        "html_links": len(page),
        "html_page_status": page_status,
        "sitemap_links": len(sitemap),
        "sitemaps_read": sitemap_count,
        "sitemap_response_types": sitemap_counts,
        "unique_discovered_urls": len(
            discovered
        ),
        "first_seen_urls": new_urls,
        "articles_inspected_this_run": 0,
        "blocked_articles_this_run": 0,
        "history_entries": len(history),
        "candidates_found": 0,
        "priority_announcements": len(
            priority
        ),
        "article_fetching_enabled": False,
        "metadata_only": True,
        "errors": errors,
    }

    write(
        DATA / "historique-actualites.json",
        {
            "version": VERSION,
            "checked_at": stamp,
            "articles": history,
        }
    )

    write(
        DATA / "nouveautes-pokemon.json",
        {
            "version": VERSION,
            "checked_at": stamp,
            "status": status,
            "source": NEWS,
            "articles": ordered[
                :MAX_NEWS_DISPLAY
            ],
            "diagnostics": diagnostics,
        }
    )

    write(
        DATA / "annonces-prioritaires.json",
        {
            "version": VERSION,
            "checked_at": stamp,
            "announcement_count": len(
                priority
            ),
            "announcements": priority,
            "notice": (
                "Signaux fondés sur les titres "
                "et métadonnées. "
                "Les espèces ne sont pas "
                "confirmées par ces annonces."
            ),
        }
    )

    write(
        DATA / "pokemon-a-verifier.json",
        {
            "version": VERSION,
            "checked_at": stamp,
            "candidate_count": 0,
            "candidates": [],
            "notice": (
                "Aucun nom d'espèce "
                "déduit automatiquement "
                "des titres."
            ),
        }
    )

    write(
        DATA / "official-news-review.json",
        {
            "version": VERSION,
            "checked_at": stamp,
            "status": status,
            "review_required": bool(
                priority
            ),
            "first_seen_urls": new_urls,
            "articles_inspected": 0,
            "blocked_articles": 0,
            "candidate_count": 0,
            "new_species_confirmed": 0,
            "source": NEWS,
            "method": "metadata_only",
        }
    )

    log(
        f"Sitemaps consultés : "
        f"{sitemap_count}"
    )

    log(
        "Sitemaps XML valides : "
        f"{sitemap_counts['xml_ok']}"
    )

    log(
        "Réponses HTML au lieu de XML : "
        f"{sitemap_counts['html_instead_of_xml']}"
    )

    log(
        "Sitemaps bloqués : "
        f"{sitemap_counts['blocked']}"
    )

    log(
        f"Actualités : "
        f"{len(discovered)} URL | "
        f"{new_urls} nouvelles | "
        f"{len(priority)} prioritaires"
    )

    log(
        "Pages d'articles consultées : "
        "0 (mode métadonnées)"
    )

    return status, diagnostics


# ==========================================================
# PROGRAMME PRINCIPAL
# ==========================================================

def main():
    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    log(
        "======================================"
    )

    log(
        "POKEDEX ACETIQUE V5.8"
    )

    log(
        "======================================"
    )

    known_names, catalogue_status = (
        update_pokeapi()
    )

    news_status, diagnostics = (
        update_news()
    )

    write(
        DATA / "sante-pokedex.json",
        {
            "version": VERSION,
            "checked_at": now(),
            "catalogue_status": (
                catalogue_status
            ),
            "news_status": news_status,
            "news_mode": "metadata_only",
            "news_articles_downloaded": 0,
            "new_species_verification": (
                "pokeapi"
            ),
            "priority_announcements": (
                diagnostics[
                    "priority_announcements"
                ]
            ),
            "sitemaps_read": (
                diagnostics[
                    "sitemaps_read"
                ]
            ),
            "sitemap_response_types": (
                diagnostics[
                    "sitemap_response_types"
                ]
            ),
            "errors": diagnostics[
                "errors"
            ],
        }
    )

    log(
        f"Santé : "
        f"catalogue={catalogue_status}, "
        f"actualités={news_status}"
    )

    log(
        "ACTUALISATION TERMINÉE"
    )


if __name__ == "__main__":
    main()
