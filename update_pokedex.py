
#!/usr/bin/env python3
"""Pokédex V4.9 : PokéAPI et actualités officielles Pokémon."""

import datetime as dt
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
API = "https://pokeapi.co/api/v2"
NEWS_URL = "https://www.pokemon.com/us/pokemon-news"

HEADERS = {
    "User-Agent": "CommunityPokedex/4.9 (+GitHub Actions)",
    "Accept": "application/json,text/html",
}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def download(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def api_json(url):
    return json.loads(download(url))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")


def species_id(url):
    match = re.search(r"/pokemon-species/(\d+)/?$", url)
    return int(match.group(1)) if match else None


class OfficialNewsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            url = urllib.parse.urljoin(NEWS_URL, self.href)
            parsed = urllib.parse.urlparse(url)
            title = html.unescape(
                " ".join(" ".join(self.text).split())
            )

            if (
                parsed.hostname in {"www.pokemon.com", "pokemon.com"}
                and "/pokemon-news/" in parsed.path
                and len(title) >= 12
            ):
                self.links.append({
                    "title": title[:180],
                    "url": urllib.parse.urlunparse((
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        "",
                        "",
                        ""
                    ))
                })

            self.href = None
            self.text = []


def update_pokeapi():
    species = api_json(
        f"{API}/pokemon-species?limit=2000"
    )["results"]

    ids = [
        species_id(item["url"])
        for item in species
    ]

    max_id = max(
        i for i in ids if i is not None
    )

    generations = api_json(
        f"{API}/generation?limit=100"
    )["results"]

    ranges = []

    for item in generations:
        detail = api_json(item["url"])

        values = [
            species_id(p["url"])
            for p in detail["pokemon_species"]
        ]

        values = [
            i for i in values if i is not None
        ]

        if values:
            ranges.append([
                min(values),
                max(values)
            ])

    ranges.sort(key=lambda pair: pair[0])

    # Conserver les 3 Pokémon provisoires
    # jusqu'à leur remplacement par PokéAPI.
    if max_id < 1028:
        if len(ranges) < 10:
            ranges.append([
                max(1026, max_id + 1),
                1028
            ])
        else:
            ranges[-1][1] = max(
                ranges[-1][1], 1028
            )

    page = ROOT / "index.html"
    original = page.read_text(encoding="utf-8")

    changed, count = re.subn(
        r"MAX=\d+,PAGE=",
        f"MAX={max_id},PAGE=",
        original,
        count=1
    )

    if count != 1:
        raise RuntimeError(
            "MAX marker not found in index.html"
        )

    changed, count = re.subn(
        r"const genRanges=\[\[.*?\]\];",
        "const genRanges="
        + json.dumps(ranges, separators=(",", ":"))
        + ";",
        changed,
        count=1
    )

    if count != 1:
        raise RuntimeError(
            "genRanges marker not found in index.html"
        )

    changed = changed.replace(
        ".concat(newPokemon).sort((a,b)=>a.id-b.id)",
        ".concat(newPokemon.filter(p=>p.id>MAX))"
        ".sort((a,b)=>a.id-b.id)"
    )

    if changed != original:
        page.write_text(changed, encoding="utf-8")

    save(
        ROOT / "data/catalogue-status.json",
        {
            "checked_at": now(),
            "pokeapi_max_species_id": max_id,
            "generation_ranges": ranges,
            "source": f"{API}/pokemon-species"
        }
    )

    return max_id


def update_news():
    output = ROOT / "data/nouveautes-pokemon.json"
    previous = {}

    if output.exists():
        try:
            previous = json.loads(
                output.read_text(encoding="utf-8")
            )
        except (ValueError, OSError):
            pass

    try:
        parser = OfficialNewsParser()
        parser.feed(download(NEWS_URL))

        dedup = {
            entry["url"]: entry
            for entry in parser.links
        }

        articles = list(dedup.values())[:40]

        # Conserver les articles déjà trouvés.
        for old in previous.get("articles", []):
            if (
                isinstance(old, dict)
                and old.get("url", "").startswith(
                    "https://www.pokemon.com/"
                )
            ):
                dedup.setdefault(old["url"], old)

        articles = list(dedup.values())[:60]

        result = {
            "checked_at": now(),
            "status": (
                "ok" if articles
                else "no_articles_detected"
            ),
            "source": NEWS_URL,
            "articles": articles,
            "notice": (
                "Official news links only; "
                "articles are not automatically "
                "classified as new Pokemon species."
            )
        }

    except Exception as exc:
        result = {
            "checked_at": now(),
            "status": "source_unavailable",
            "source": NEWS_URL,
            "articles": previous.get("articles", []),
            "error": str(exc)[:200],
            "notice": (
                "Previous news retained; "
                "official source could not be checked."
            )
        }

    save(output, result)

    save(
        ROOT / "data/official-news-review.json",
        {
            "checked_at": result["checked_at"],
            "status": result["status"],
            "review_required": True,
            "articles_found": len(result["articles"]),
            "source": NEWS_URL
        }
    )

    return len(result["articles"])


def main():
    max_id = update_pokeapi()
    count = update_news()

    print(
        f"PokéAPI max species ID: {max_id}; "
        f"official news links: {count}"
    )


if __name__ == "__main__":
    main()
