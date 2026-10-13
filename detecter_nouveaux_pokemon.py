#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pokédex Acetique V5.9 — détection prudente de noms dans les titres officiels.
À exécuter APRÈS update_pokedex.py V5.8. Python 3.10+, sans dépendances.
N'ajoute jamais de Pokémon à index.html et ne modifie pas le catalogue.
"""
from __future__ import annotations
import datetime as dt
import html
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
VERSION = '5.9'
OUTPUT = DATA / 'pokemon-a-verifier.json'
REVIEW = DATA / 'validation-pokemon.json'

# Des noms déjà affichés provisoirement dans le site, sans confirmation PokéAPI.
PROVISIONAL = {'browt', 'pombon', 'gecqua'}
# Expressions courantes qui ne doivent pas être considérées comme des espèces.
STOPWORDS = {
    'pokemon', 'pokémon', 'new', 'news', 'official', 'update', 'updates',
    'game', 'games', 'mega', 'evolution', 'evolutions', 'form', 'forms',
    'generation', 'generations', 'first', 'partner', 'partners', 'starter',
    'starters', 'revealed', 'reveal', 'announced', 'announcing', 'introducing',
    'meet', 'discover', 'discovered', 'introduce', 'the', 'and', 'or',
    'a', 'an', 'in', 'of', 'to', 'for', 'with', 'from', 'at', 'on', 'is',
    'are', 'will', 'be', 'your', 'all', 'more', 'latest', 'get', 'ready',
    'winds', 'waves', 'scarlet', 'violet', 'legends', 'za', 'z-a',
    'tcg', 'go', 'unite', 'sleep', 'mobile', 'video', 'world', 'championships',
    'horizons', 'anime', 'series', 'trailer', 'details', 'region',
}
# Contexte obligatoire pour éviter de prendre n'importe quel mot en majuscule.
CONTEXT = re.compile(
    r'\b(?:new|newly discovered|never.before.seen|introducing|meet|revealed|'
    r'unveiled|discover|first.partner|starter|partner)\b', re.I
)
NAME = r'([A-Z][a-zA-ZéÉàÀèÈêÊîÎôÔûÛçÇüÜïÏëË]{2,23}(?:-[A-Z][a-zA-Z]{2,18})?)'
# Extraction explicite seulement. Les noms sont ensuite filtrés et vérifiés.
PATTERNS = [
    (re.compile(r'\b(?:meet|introducing|discover|revealing|revealed|unveiling)\s+(?:the\s+)?' + NAME, re.I), 75, 'Nom après un verbe de présentation'),
    (re.compile(r'\b(?:new|newly discovered|never.before.seen)\s+Pok[eé]mon\s*[:\-–]?\s*' + NAME, re.I), 85, 'Nom après « nouveau Pokémon »'),
    (re.compile(NAME + r'\s*[,!:\-–]?\s+(?:is|joins|arrives|revealed|unveiled)\s+(?:a\s+)?(?:new\s+)?Pok[eé]mon\b', re.I), 90, 'Nom explicitement désigné comme Pokémon'),
    (re.compile(r'\b(?:new|starter|partner)\s+Pok[eé]mon\s+(?:named|called)\s+' + NAME, re.I), 95, 'Nom introduit par « named/called »'),
]
# Détecter aussi des listes dans les titres, seulement si contexte Pokémon explicite.
LIST_PATTERN = re.compile(
    r'\b(?:meet|introducing|discover)\s+' + NAME +
    r'(?:\s*,\s*' + NAME + r')?\s*(?:,?\s+and\s+' + NAME + r')?\b', re.I
)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if not path.exists() or path.read_text(encoding='utf-8') != content:
        path.write_text(content, encoding='utf-8')


def normalize(name):
    return ''.join(c for c in unicodedata.normalize('NFKD', name.casefold())
                   if not unicodedata.combining(c)).strip()


def official(url):
    try:
        p = urlsplit(url)
        return p.scheme == 'https' and p.hostname in ('pokemon.com', 'www.pokemon.com')
    except ValueError:
        return False


def valid_name(name, known):
    key = normalize(name)
    if len(key) < 3 or key in STOPWORDS or key in known:
        return False
    if not re.fullmatch(r'[a-z][a-z\-]{2,35}', key):
        return False
    return True


def extract(title, known):
    title = html.unescape(title or '').strip()
    if not CONTEXT.search(title) or not re.search(r'pok[eé]mon', title, re.I):
        return []
    found = {}
    for regex, score, reason in PATTERNS:
        for match in regex.finditer(title):
            name = match.group(1)
            if valid_name(name, known):
                key = normalize(name)
                if key not in found or score > found[key]['score']:
                    found[key] = {'name': name, 'score': score, 'reason': reason}
    # « Meet Browt, Pombon, and Gecqua: New Pokémon... »
    for match in LIST_PATTERN.finditer(title):
        for name in match.groups():
            if name and valid_name(name, known):
                key = normalize(name)
                if key not in found:
                    found[key] = {'name': name, 'score': 70, 'reason': 'Liste de noms présentés'}
    return list(found.values())


def collect_articles():
    result = {}
    history = read_json(DATA / 'historique-actualites.json', {})
    raw = history.get('articles', {}) if isinstance(history, dict) else {}
    if isinstance(raw, dict):
        items = raw.values()
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    for item in items:
        if isinstance(item, dict) and official(str(item.get('url', ''))):
            result[item['url']] = item
    for filename, key in [('annonces-prioritaires.json', 'announcements'),
                          ('nouveautes-pokemon.json', 'articles')]:
        data = read_json(DATA / filename, {})
        if isinstance(data, dict):
            for item in data.get(key, []):
                if isinstance(item, dict) and official(str(item.get('url', ''))):
                    # Garder le titre le plus informatif, si disponible.
                    previous = result.get(item['url'], {})
                    if len(str(item.get('title', ''))) > len(str(previous.get('title', ''))):
                        result[item['url']] = item
    return list(result.values())


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    cache = read_json(DATA / 'pokeapi-cache.json', {})
    names = cache.get('known_names', []) if isinstance(cache, dict) else []
    if not isinstance(names, list) or len(names) < 1000:
        raise SystemExit('[V5.9] Cache PokéAPI insuffisant : exécuter V5.8 avant V5.9.')
    known = {normalize(str(name)) for name in names}
    articles = collect_articles()
    previous = read_json(OUTPUT, {})
    previous_candidates = previous.get('candidates', []) if isinstance(previous, dict) else []
    previous_by_name = {
        normalize(str(x.get('name', ''))): x
        for x in previous_candidates if isinstance(x, dict) and x.get('name')
    }
    review = read_json(REVIEW, {})
    decisions = review.get('decisions', {}) if isinstance(review, dict) else {}
    if not isinstance(decisions, dict):
        decisions = {}
    by_name = {}
    for article in articles:
        title = str(article.get('title') or '')
        url = str(article.get('url') or '')
        for candidate in extract(title, known):
            key = normalize(candidate['name'])
            old = previous_by_name.get(key, {})
            decision = decisions.get(key, 'a_verifier')
            if decision not in ('a_verifier', 'rejete', 'valide_manuellement'):
                decision = 'a_verifier'
            record = by_name.setdefault(key, {
                'name': candidate['name'],
                'status': decision,
                'score': candidate['score'],
                'reason': candidate['reason'],
                'first_detected': old.get('first_detected') or now(),
                'already_in_site_provisionally': key in PROVISIONAL,
                'verified_by_pokeapi': False,
                'sources': [],
            })
            if candidate['score'] > record['score']:
                record['score'] = candidate['score']
                record['reason'] = candidate['reason']
            if not any(s['url'] == url for s in record['sources']):
                record['sources'].append({'title': title, 'url': url})
    # Ne pas perdre les candidats historiques en cas d'indisponibilité des sources.
    for key, old in previous_by_name.items():
        if key not in known and key not in by_name:
            by_name[key] = old
            by_name[key]['status'] = decisions.get(key, old.get('status', 'a_verifier'))
    candidates = sorted(by_name.values(), key=lambda x: (-x.get('score', 0), x['name'].lower()))
    counts = {s: sum(x.get('status') == s for x in candidates)
              for s in ('a_verifier', 'rejete', 'valide_manuellement')}
    write_json(OUTPUT, {
        'version': VERSION,
        'checked_at': now(),
        'method': 'official_title_patterns_only',
        'known_species_count': len(known),
        'articles_analyzed': len(articles),
        'candidate_count': len(candidates),
        'pending_review_count': counts['a_verifier'],
        'rejected_count': counts['rejete'],
        'manually_validated_count': counts['valide_manuellement'],
        'candidates': candidates,
        'notice': 'Candidats non confirmés. Aucun ajout automatique au Pokédex.',
    })
    if not REVIEW.exists():
        write_json(REVIEW, {
            'version': VERSION,
            'instructions': 'Décisions par nom normalisé : a_verifier, rejete, valide_manuellement.',
            'decisions': {},
        })
    print(f'[POKEDEX V5.9] Espèces connues : {len(known)}')
    print(f'[POKEDEX V5.9] Titres officiels analysés : {len(articles)}')
    print(f'[POKEDEX V5.9] Candidats : {len(candidates)} | à vérifier : {counts["a_verifier"]} | rejetés : {counts["rejete"]}')
    print('[POKEDEX V5.9] Aucun ajout automatique au Pokédex')
    print('[POKEDEX V5.9] TERMINÉ')


if __name__ == '__main__':
    main()
