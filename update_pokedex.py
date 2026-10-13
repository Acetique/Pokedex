#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pokédex Acetique V5.7 — catalogue PokéAPI et veille officielle sans scraping d'articles.
Python 3.10+, bibliothèque standard uniquement.
"""
from __future__ import annotations
import datetime as dt
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

VERSION = "5.7"
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
API = "https://pokeapi.co/api/v2"
NEWS = "https://www.pokemon.com/us/pokemon-news"
SITEMAP = "https://www.pokemon.com/sitemap.xml"
HEADERS = {"User-Agent": "AcetiquePokedex/5.7 (catalogue public; contact via GitHub)", "Accept": "application/json,text/html,application/xml,text/xml,*/*", "Accept-Language": "en-US,en;q=0.8"}
PROVISIONAL = {"browt", "pombon", "gecqua"}
MAX_PRIORITY = 60
MAX_NEWS_DISPLAY = 100
MAX_HISTORY = 10000


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def log(msg):
    print(f"[POKEDEX V{VERSION}] {msg}", flush=True)


def load(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != data:
        path.write_text(data, encoding="utf-8")


def request(url, timeout=25, attempts=3):
    error = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                raw = res.read(10_000_000)
                return raw.decode(res.headers.get_content_charset() or "utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            error = exc
            if exc.code in (400, 401, 403, 404, 429):
                break  # Respect des refus et limites du serveur.
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = exc
        if i + 1 < attempts:
            time.sleep(min(2 ** (i + 1), 8))
    raise RuntimeError(f"{url}: {error}")


def api_json(url):
    return json.loads(request(url, timeout=40, attempts=4))


def species_id(url):
    match = re.search(r"/pokemon-species/(\d+)/?$", str(url))
    return int(match.group(1)) if match else None


def fetch_catalogue():
    species = api_json(f"{API}/pokemon-species?limit=2000").get("results", [])
    entries = sorted(((species_id(s.get("url")), s.get("name", "")) for s in species), key=lambda x: x[0] or 0)
    entries = [(sid, name.lower()) for sid, name in entries if sid is not None and name]
    if not entries:
        raise RuntimeError("Liste PokéAPI vide")
    gens = api_json(f"{API}/generation?limit=100").get("results", [])
    ranges = []
    for gen in gens:
        detail = api_json(gen["url"])
        ids = [species_id(p.get("url")) for p in detail.get("pokemon_species", [])]
        ids = [sid for sid in ids if sid is not None]
        if ids:
            ranges.append([min(ids), max(ids)])
        time.sleep(0.15)
    ranges.sort(key=lambda r: r[0])
    return {"version": VERSION, "updated_at": now(), "max_id": max(i for i, _ in entries), "ranges": ranges, "known_names": sorted({name for _, name in entries}), "species": [{"id": i, "name": name} for i, name in entries]}


def update_index(catalogue):
    path = ROOT / "index.html"
    if not path.exists():
        raise RuntimeError("index.html introuvable")
    original = path.read_text(encoding="utf-8")
    maximum = catalogue["max_id"]
    ranges = [list(r) for r in catalogue["ranges"]]
    # Réserver la génération provisoire seulement si les IDs sont encore absents de PokéAPI.
    if maximum < 1028:
        ranges.append([max(maximum + 1, 1026), 1028])
    ranges.sort(key=lambda x: x[0])
    text, n_max = re.subn(r"\bMAX\s*=\s*\d+\s*,\s*PAGE\s*=", f"MAX={maximum},PAGE=", original, count=1)
    text, n_ranges = re.subn(r"\bconst\s+genRanges\s*=\s*\[\[.*?\]\]\s*;", "const genRanges=" + json.dumps(ranges, separators=(",", ":")) + ";", text, count=1, flags=re.S)
    if n_max != 1 or n_ranges != 1:
        raise RuntimeError("Marqueurs MAX/PAGE ou genRanges non trouvés dans index.html; aucun changement écrit")
    # Éviter les doublons entre les données officielles et les Pokémon provisoires.
    text = re.sub(r"\.concat\(newPokemon\)(?!\.filter)", ".concat(newPokemon.filter(p=>p.id>MAX))", text)
    if text != original:
        path.write_text(text, encoding="utf-8")
    return text != original, ranges


def update_pokeapi():
    cache_path = DATA / "pokeapi-cache.json"
    previous = load(cache_path, {})
    source, error = "live", None
    try:
        catalogue = fetch_catalogue()
    except Exception as exc:
        error = str(exc)
        if not isinstance(previous, dict) or not all(k in previous for k in ("max_id", "ranges", "known_names")):
            write(DATA / "catalogue-status.json", {"version": VERSION, "checked_at": now(), "status": "unavailable", "source": "none", "error": error, "index_modified": False})
            log("PokéAPI indisponible et cache inutilisable")
            return set(), "unavailable"
        catalogue, source = previous, "cache"
    old_names = set(previous.get("known_names", [])) if isinstance(previous, dict) else set()
    new_names = set(catalogue["known_names"])
    added = sorted(new_names - old_names) if old_names and source == "live" else []
    changed = False
    ranges = catalogue["ranges"]
    try:
        changed, ranges = update_index(catalogue)
    except Exception as exc:
        error = (error + "; " if error else "") + str(exc)
        log(f"Attention index.html : {exc}")
    if source == "live":
        write(cache_path, catalogue)
    status = "ok" if source == "live" and not error else "cached" if source == "cache" and not error else "partial"
    write(DATA / "catalogue-status.json", {"version": VERSION, "checked_at": now(), "status": status, "source": source, "pokeapi_max_species_id": catalogue["max_id"], "previous_max_species_id": previous.get("max_id") if isinstance(previous, dict) else None, "generation_ranges": ranges, "new_species_count": len(added), "new_species_names": added, "index_modified": changed, "error": error})
    write(DATA / "nouvelles-especes-officielles.json", {"version": VERSION, "checked_at": now(), "source": source, "new_species_count": len(added), "new_species_names": added, "verified_by_pokeapi": source == "live", "note": "Comparaison avec le dernier catalogue local; la première exécution initialise la référence."})
    log(f"Espèces PokéAPI : {catalogue['max_id']} | nouvelles depuis cache : {len(added)} | source : {source}")
    return new_names, status


class LinksParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.current, self.parts = [], None, []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = dict(attrs).get("href")
            self.parts = []
    def handle_data(self, data):
        if self.current is not None:
            self.parts.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append((self.current, " ".join(" ".join(self.parts).split())))
            self.current = None
            self.parts = []


def normalize_url(url):
    try:
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(NEWS, url))
        if parsed.hostname not in ("www.pokemon.com", "pokemon.com"):
            return None
        path = parsed.path.rstrip("/")
        if not (path.startswith("/us/news/") or path.startswith("/us/pokemon-news/")):
            return None
        return "https://www.pokemon.com" + path
    except ValueError:
        return None


def title_from_url(url):
    return html.unescape(url.rsplit("/", 1)[-1].replace("-", " ")).strip().title()


def get_news_html():
    parser = LinksParser()
    parser.feed(request(NEWS, attempts=1))
    found = {}
    for href, title in parser.links:
        url = normalize_url(href)
        if url:
            found[url] = {"url": url, "title": title if len(title) >= 8 else title_from_url(url), "discovery_method": "html_link"}
    return found


def get_news_sitemap():
    """Lit le sitemap principal et ses sous-sitemaps officiels (sans pages d'articles)."""
    found = {}
    errors = []
    queue = [SITEMAP]
    seen = set()
    max_sitemaps = 35
    while queue and len(seen) < max_sitemaps:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            root = ET.fromstring(request(url, attempts=1))
            tag = root.tag.rsplit("}", 1)[-1].lower()
            if tag == "sitemapindex":
                for child in root:
                    loc = next((x.text for x in child if x.tag.rsplit("}", 1)[-1] == "loc"), None)
                    if loc and urllib.parse.urlsplit(loc).hostname in ("pokemon.com", "www.pokemon.com") and loc not in seen:
                        queue.append(loc)
            elif tag == "urlset":
                for child in root:
                    loc = next((x.text for x in child if x.tag.rsplit("}", 1)[-1] == "loc"), None)
                    lastmod = next((x.text for x in child if x.tag.rsplit("}", 1)[-1] == "lastmod"), None)
                    normalized = normalize_url(loc) if loc else None
                    if normalized:
                        found[normalized] = {"url": normalized, "title": title_from_url(normalized), "sitemap_lastmod": lastmod, "discovery_method": "sitemap"}
        except Exception as exc:
            errors.append({"source": url, "error": str(exc)[:250]})
        time.sleep(0.1)
    return found, errors, len(seen)


SPECIES = [r"newly discovered pok[eé]mon", r"new pok[eé]mon species", r"new species of pok[eé]mon", r"never.before.seen pok[eé]mon", r"new pok[eé]mon (?:revealed|unveiled)", r"introducing (?:a |the )?new pok[eé]mon", r"new starter pok[eé]mon", r"new partner pok[eé]mon"]
GEN10 = [r"pok[eé]mon winds", r"pok[eé]mon waves", r"generation 10", r"gen 10", r"new first.partner pok[eé]mon"]
FORMS = [r"mega.evolution", r"mega.evolved", r"mega [a-z][a-z-]+", r"regional form", r"new form of", r"gigantamax"]
EXCLUDE = [r"trading card", r"\btcg\b", r"pokemon center", r"pok[eé]mon center", r"championship", r"tournament", r"community day", r"pok[eé]mon go", r"pok[eé]mon sleep", r"pok[eé]mon unite", r"soundtrack", r"plush", r"merchandise", r"pok[eé]mon league", r"prizes", r"promo card"]


def classify(title):
    if any(re.search(p, title, re.I) for p in EXCLUDE):
        return "excluded_news", 0
    if any(re.search(p, title, re.I) for p in SPECIES):
        return "possible_new_species", 300
    if any(re.search(p, title, re.I) for p in GEN10):
        return "generation_10_news", 220
    if any(re.search(p, title, re.I) for p in FORMS):
        return "new_form_or_mega", 140
    return "general_news", 0


def date_score(article):
    raw = article.get("published_at") or article.get("sitemap_lastmod")
    if not raw:
        return 0
    try:
        date = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=dt.timezone.utc)
        days = (dt.datetime.now(dt.timezone.utc) - date).days
        return 60 if days <= 7 else 35 if days <= 30 else 15 if days <= 90 else 0
    except ValueError:
        return 0


def update_news(known_names):
    stored = load(DATA / "historique-actualites.json", {})
    history = stored.get("articles", {}) if isinstance(stored, dict) else {}
    if not isinstance(history, dict):
        history = {}
    errors = []
    try:
        sitemap, sitemap_errors, sitemap_count = get_news_sitemap()
        errors.extend(sitemap_errors)
    except Exception as exc:
        sitemap, sitemap_count = {}, 0
        errors.append({"source": SITEMAP, "error": str(exc)[:250]})
    try:
        page = get_news_html()
    except Exception as exc:
        page = {}
        errors.append({"source": NEWS, "error": str(exc)[:250]})
    discovered = {**sitemap, **page}
    new_urls = 0
    for url, data in discovered.items():
        previous = history.get(url)
        if not isinstance(previous, dict):
            previous = {"first_seen": now()}
            new_urls += 1
        # HTML fournit généralement un meilleur titre que le slug.
        title = page[url]["title"] if url in page else previous.get("title") or data["title"]
        category, score = classify(title)
        previous.update({"url": url, "title": title, "last_seen": now(), "announcement_category": category, "priority_score": score, "inspection_status": "metadata_only", "title_signal_only": True, "verified_new_species": False})
        if data.get("sitemap_lastmod"):
            previous["sitemap_lastmod"] = data["sitemap_lastmod"]
        history[url] = previous
    # Reclassifier les anciens articles, y compris ceux non présents dans le sitemap actuel.
    for article in history.values():
        title = article.get("title") or title_from_url(article.get("url", ""))
        category, score = classify(title)
        article.update({"title": title, "announcement_category": category, "priority_score": score, "inspection_status": "metadata_only", "title_signal_only": True, "verified_new_species": False})
        article.pop("name_candidates_for_review", None)
        article.pop("announcement_evidence", None)
    history = dict(sorted(history.items(), key=lambda pair: pair[1].get("last_seen", ""), reverse=True)[:MAX_HISTORY])
    ordered = sorted(history.values(), key=lambda a: (a.get("priority_score", 0) + date_score(a), a.get("sitemap_lastmod") or "", a.get("title") or ""), reverse=True)
    priority = []
    for article in ordered:
        if article.get("priority_score", 0) <= 0:
            continue
        priority.append({"title": article["title"], "url": article["url"], "published_at": article.get("published_at"), "sitemap_lastmod": article.get("sitemap_lastmod"), "priority_score": article["priority_score"] + date_score(article), "announcement_category": article["announcement_category"], "inspection_status": "metadata_only", "title_signal_only": True, "verified_new_species": False, "name_candidates_for_review": []})
        if len(priority) >= MAX_PRIORITY:
            break
    status = "ok" if discovered else "degraded_archive_only" if history else "source_unavailable"
    diagnostics = {"html_links": len(page), "sitemap_links": len(sitemap), "sitemaps_read": sitemap_count, "unique_discovered_urls": len(discovered), "first_seen_urls": new_urls, "articles_inspected_this_run": 0, "blocked_articles_this_run": 0, "history_entries": len(history), "suspected_generic_content": 0, "candidates_found": 0, "priority_announcements": len(priority), "article_fetching_enabled": False, "metadata_only": True, "errors": errors}
    stamp = now()
    write(DATA / "historique-actualites.json", {"version": VERSION, "checked_at": stamp, "articles": history})
    write(DATA / "nouveautes-pokemon.json", {"version": VERSION, "checked_at": stamp, "status": status, "source": NEWS, "articles": ordered[:MAX_NEWS_DISPLAY], "diagnostics": diagnostics})
    write(DATA / "annonces-prioritaires.json", {"version": VERSION, "checked_at": stamp, "announcement_count": len(priority), "announcements": priority, "notice": "Signaux basés sur les titres et métadonnées, non des espèces confirmées."})
    write(DATA / "pokemon-a-verifier.json", {"version": VERSION, "checked_at": stamp, "candidate_count": 0, "candidates": [], "notice": "Aucun nom d'espèce déduit des titres; confirmation par PokéAPI uniquement."})
    write(DATA / "official-news-review.json", {"version": VERSION, "checked_at": stamp, "status": status, "review_required": bool(priority), "first_seen_urls": new_urls, "articles_inspected": 0, "blocked_articles": 0, "candidate_count": 0, "new_species_confirmed": 0, "source": NEWS, "method": "metadata_only"})
    log(f"Actualités : {len(discovered)} URL | {new_urls} nouvelles | {len(priority)} prioritaires")
    log("Pages d'articles consultées : 0 (mode titres/métadonnées)")
    return status, diagnostics


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    log("======================================")
    log("POKEDEX ACETIQUE V5.7")
    log("======================================")
    known, catalogue_status = update_pokeapi()
    news_status, diagnostics = update_news(known)
    write(DATA / "sante-pokedex.json", {"version": VERSION, "checked_at": now(), "catalogue_status": catalogue_status, "news_status": news_status, "news_mode": "metadata_only", "news_articles_downloaded": 0, "new_species_verification": "pokeapi", "priority_announcements": diagnostics["priority_announcements"], "errors": diagnostics["errors"]})
    log(f"Santé : catalogue={catalogue_status}, actualités={news_status}")
    log("ACTUALISATION TERMINÉE")


if __name__ == "__main__":
    main()
