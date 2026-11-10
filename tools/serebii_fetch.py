"""
Downloads the Serebii pages the build needs, politely (one request at a time,
with a pause) and caches them in tools/.cache/serebii so they are fetched once.

Run:  python tools/serebii_fetch.py          (only fetches pages not cached yet)
      python tools/serebii_fetch.py --fresh  (re-downloads everything, e.g. after a game update)
"""
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "tools", ".cache", "serebii")
os.makedirs(CACHE, exist_ok=True)
BASE = "https://www.serebii.net"
UA = "Mozilla/5.0 (za-pokedex personal tracker build; cached, 1 request at a time)"
PAUSE = 1.2  # seconds between requests — be kind to Serebii

# Section pages: the two Pokédex lists and the Mega Stone locations
INDEX_PAGES = [
    "/legendsz-a/availablepokemon.shtml",    # Lumiose Pokédex
    "/legendsz-a/hyperspacepokedex.shtml",   # Hyperspace Pokédex (Mega Dimension)
    "/legendsz-a/megastones.shtml",
]


def cache_path(url_path):
    return os.path.join(CACHE, re.sub(r"[^a-z0-9.]+", "_", url_path.lower()).strip("_") + ".html")


def fetch(url_path, fresh=False):
    fp = cache_path(url_path)
    if os.path.exists(fp) and not fresh:
        return open(fp, encoding="latin-1").read(), False
    req = urllib.request.Request(BASE + url_path, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("latin-1")
            break
        except Exception as e:  # retry with a longer pause
            print(f"  retry {url_path}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError("Serebii failed: " + url_path)
    with open(fp, "w", encoding="latin-1") as f:
        f.write(html)
    return html, True


def species_links(html):
    """Pokédex page → ordered list of (dex label, name, /pokedex-sv/<slug>/)."""
    out = []
    for m in re.finditer(r'<td align="center" class="fooinfo">\s*(H?#\d+)\s*</td>.*?<a href="(/pokedex-sv/[^"/]+/)">([^<]+)<', html, re.S):
        out.append((m.group(1), m.group(3).strip(), m.group(2)))
    return out


if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    pages = []
    for n, p in enumerate(INDEX_PAGES):
        html, net = fetch(p, fresh)
        if net:
            time.sleep(PAUSE)
        if n < 2:  # the first two are the Lumiose and Hyperspace Pokédex lists
            links = species_links(html)
            print(f"{p}: {len(links)} Pokémon", file=sys.stderr)
            pages += [l[2] for l in links]
    seen = set()
    todo = [p for p in pages if not (p in seen or seen.add(p))]
    for i, p in enumerate(todo, 1):
        _, net = fetch(p, fresh)
        if net:
            print(f"[{i}/{len(todo)}] {p}", file=sys.stderr)
            time.sleep(PAUSE)
    print(f"Done: {len(todo)} Pokémon pages cached.", file=sys.stderr)
