#!/usr/bin/env python3
"""Update the static Pokédex from PokéAPI; collect official news for manual review.
No scraping of third-party encyclopedias; no unverified Pokémon auto-published.
"""
import json, re, urllib.request, pathlib, datetime, html
from html.parser import HTMLParser
ROOT=pathlib.Path(__file__).resolve().parent
HEADERS={'User-Agent':'PokedexCommunityUpdater/4.8 (GitHub Actions; public pages)','Accept':'application/json,text/html'}
def fetch(url):
    req=urllib.request.Request(url,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=25) as r:return r.read()
def get_json(url):return json.loads(fetch(url))
def save_json(path, obj):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
class Titles(HTMLParser):
    def __init__(self):super().__init__();self.in_title=False;self.title=''
    def handle_starttag(self,tag,attrs):
        if tag=='title':self.in_title=True
    def handle_endtag(self,tag):
        if tag=='title':self.in_title=False
    def handle_data(self,data):
        if self.in_title:self.title+=data

def main():
    # The API list contains alternate forms; the species endpoint defines National Pokédex species.
    species=get_json('https://pokeapi.co/api/v2/pokemon-species?limit=2000')['results']
    ids=[int(re.search(r'/pokemon-species/(\d+)/?$',x['url']).group(1)) for x in species]
    max_id=max(ids)
    generations=get_json('https://pokeapi.co/api/v2/generation?limit=100')['results']
    ranges=[]
    for g in generations:
        detail=get_json(g['url'])
        numbers=[int(re.search(r'/pokemon-species/(\d+)/?$',p['url']).group(1)) for p in detail['pokemon_species']]
        if numbers:ranges.append([min(numbers),max(numbers)])
    ranges.sort(key=lambda a:a[0])
    # Preserve the manually announced generation-10 starters as provisional cards,
    # but never let their provisional numbers shadow a future official species.
    if max_id<1028 and len(ranges)<10:ranges.append([max(1026,max_id+1),1028])
    page=ROOT/'index.html'; src=page.read_text(encoding='utf-8')
    src,n=re.subn(r'MAX=\d+,PAGE=',f'MAX={max_id},PAGE=',src,count=1)
    if n!=1:raise RuntimeError('MAX marker not found')
    src,n=re.subn(r'const genRanges=\[\[.*?\]\];',f'const genRanges={json.dumps(ranges,separators=(",",":"))};',src,count=1)
    if n!=1:raise RuntimeError('Generation marker not found')
    # Drop manual cards that have been superseded by official IDs.
    src=src.replace('.concat(newPokemon).sort((a,b)=>a.id-b.id)', '.concat(newPokemon.filter(p=>p.id>MAX)).sort((a,b)=>a.id-b.id)')
    page.write_text(src,encoding='utf-8')
    save_json(ROOT/'data'/'catalogue-status.json',{'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pokeapi_max_species_id':max_id,'generation_ranges':ranges,'source':'https://pokeapi.co/api/v2/pokemon-species'})
    # Official website is monitored for changes; headlines are candidates only.
    # Site structure can change; failures must not block PokéAPI updates.
    entries=[]
    for url in ['https://www.pokemon.com/us/pokemon-news']:
        try:
            parser=Titles();parser.feed(fetch(url).decode('utf-8','replace'))
            entries.append({'url':url,'page_title':html.unescape(parser.title.strip()),'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'review_required'})
        except Exception as exc:entries.append({'url':url,'status':'unavailable','error':str(exc)[:120]})
    save_json(ROOT/'data'/'official-news-review.json',entries)
    print('PokéAPI species:',max_id,'generations:',len(ranges),'official page checks:',len(entries))
if __name__=='__main__':main()
