#!/usr/bin/env python3
"""Crée/actualise data/noms-pokemon-fr.json depuis PokéAPI (noms officiels).
Exécuter après update_pokedex.py. Python standard 3.10+, sans dépendance.
Conserve les entrées déjà connues en cas d'indisponibilité réseau.
"""
import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'data' / 'noms-pokemon-fr.json'
INDEX = ROOT / 'index.html'
BASE = 'https://pokeapi.co/api/v2'


def get_json(url):
    last = None
    for retry in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'AcetiquePokedex/5.9 (GitHub Pages)', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=22) as response:
                return json.load(response)
        except (OSError, ValueError) as exc:
            last = exc
            time.sleep(min(2 ** retry, 8))
    raise RuntimeError(f'{url}: {last}')


def read_existing():
    try:
        raw = json.loads(OUT.read_text(encoding='utf-8'))
        return {str(k): v for k, v in raw.get('pokemon', {}).items() if isinstance(v, dict)}
    except (OSError, ValueError, TypeError):
        return {}


def get_one(item):
    pid, english = item
    species = get_json(f'{BASE}/pokemon-species/{pid}/')
    names = {x['language']['name']: x['name'] for x in species.get('names', [])}
    french = names.get('fr')
    english = names.get('en') or english.replace('-', ' ').title()
    if not french:
        raise ValueError(f'Pas de nom français pour #{pid}')
    return str(pid), {'fr': french, 'en': english}


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    known = read_existing()
    # Le catalogue PokéAPI est la seule source pour les espèces officielles.
    try:
        catalogue = get_json(f'{BASE}/pokemon-species/?limit=2000')
        items = []
        for x in catalogue['results']:
            match = re.search(r'/pokemon-species/(\d+)/?$', x['url'])
            if match:
                items.append((int(match.group(1)), x['name']))
        items.sort()
    except Exception as exc:
        print('[NOMS V5.9] Catalogue indisponible :', exc)
        if known:
            print('[NOMS V5.9] Fichier précédent conservé.')
            return
        raise
    pending = [(pid, en) for pid, en in items if not known.get(str(pid), {}).get('fr') or not known.get(str(pid), {}).get('en')]
    print(f'[NOMS V5.9] Espèces officielles : {len(items)} | noms à récupérer : {len(pending)}')
    errors = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(get_one, item): item for item in pending}
        for fut in concurrent.futures.as_completed(futures):
            try:
                key, value = fut.result()
                known[key] = value
            except Exception as exc:
                errors += 1
                print('[NOMS V5.9] Avertissement :', exc)
    official_ids = {str(pid) for pid, _ in items}
    pokemon = {key: known[key] for key in sorted(official_ids, key=int) if key in known}
    # Ne jamais écraser un fichier sain avec un fichier vide.
    if not pokemon:
        raise RuntimeError('Aucun nom disponible; fichier existant non écrasé')
    output = {'version': '5.9', 'updated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'count': len(pokemon), 'pokemon': pokemon}
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'[NOMS V5.9] Noms enregistrés : {len(pokemon)} | erreurs : {errors} | {OUT.relative_to(ROOT)}')
    if INDEX.exists():
        match = re.search(r'\bMAX=(\d+)', INDEX.read_text(encoding='utf-8'))
        if match and len(pokemon) < int(match.group(1)):
            print('[NOMS V5.9] ATTENTION : certains noms manquent; nouvelle exécution conseillée.')


if __name__ == '__main__':
    main()
