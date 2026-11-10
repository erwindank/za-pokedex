"""
Gets a recommended competitive build (nature, held item, ability, 4 moves) for
every Pokémon from RankedBoost's Legends: Z-A pages, checks every move against
Serebii's Z-A move list (so a move it can't learn in Z-A never gets through),
and writes the result to tools/builds.json — ready to go into the Google Sheet.

Run:  python tools/builds_fetch.py          (only fetches pages not cached yet)
      python tools/builds_fetch.py --fresh  (download all again)
Only the build section of each page is cached (tools/.cache/rankedboost), one
request at a time with a pause.
"""
import html as htmllib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import serebii_parse as sp_parse  # noqa: E402

CACHE = os.path.join(ROOT, "tools", ".cache", "rankedboost")
os.makedirs(CACHE, exist_ok=True)
UA = "Mozilla/5.0 (za-pokedex personal tracker build; cached, 1 request at a time)"
PAUSE = 1.5

NATURES = {
    "Lonely": ("Attack", "Defense"), "Brave": ("Attack", "Speed"), "Adamant": ("Attack", "Sp. Atk"),
    "Naughty": ("Attack", "Sp. Def"), "Bold": ("Defense", "Attack"), "Relaxed": ("Defense", "Speed"),
    "Impish": ("Defense", "Sp. Atk"), "Lax": ("Defense", "Sp. Def"), "Timid": ("Speed", "Attack"),
    "Hasty": ("Speed", "Defense"), "Jolly": ("Speed", "Sp. Atk"), "Naive": ("Speed", "Sp. Def"),
    "Modest": ("Sp. Atk", "Attack"), "Mild": ("Sp. Atk", "Defense"), "Quiet": ("Sp. Atk", "Speed"),
    "Rash": ("Sp. Atk", "Sp. Def"), "Calm": ("Sp. Def", "Attack"), "Gentle": ("Sp. Def", "Defense"),
    "Sassy": ("Sp. Def", "Speed"), "Careful": ("Sp. Def", "Sp. Atk"),
    "Hardy": ("", ""), "Docile": ("", ""), "Serious": ("", ""), "Bashful": ("", ""), "Quirky": ("", ""),
}


def rb_slug(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("'", "").replace(".", "").replace(" ", "-")
    return re.sub(r"[^a-z0-9-]+", "", s).strip("-")


def page_url(name):
    return f"https://rankedboost.com/pokemon/{rb_slug(name)}/legends-z-a/"


def fetch_block(name, fresh=False):
    """The 'Best Moveset' section of the page (cached). '' if the page has none."""
    fp = os.path.join(CACHE, rb_slug(name) + ".html")
    if os.path.exists(fp) and not fresh:
        return open(fp, encoding="utf-8").read(), False
    req = urllib.request.Request(page_url(name), headers={"User-Agent": UA})
    page = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                page = r.read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            time.sleep(5 * (attempt + 1))
        except Exception:
            time.sleep(5 * (attempt + 1))
    i = page.find("Best Moveset")
    j = page.find("pcombat-build-teammates", i)
    block = page[i:j] if i != -1 else ""
    with open(fp, "w", encoding="utf-8") as f:
        f.write(block)
    return block, True


def parse_block(block):
    if not block:
        return None
    def one(pat):
        m = re.search(pat, block, re.S)
        return htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
    nature = one(r'class="pcombat-choice-value pcombat-nature-link"[^>]*>(.*?)</a>')
    item = ""
    ability = ""
    for label, val in re.findall(r'<span class="pcombat-choice-label">(.*?)</span>\s*<div class="pcombat-choice-content">\s*<(?:span|a)[^>]*class="pcombat-choice-value[^"]*"[^>]*>(.*?)</(?:span|a)>', block, re.S):
        if label.strip() == "Item":
            item = htmllib.unescape(val).strip()
        elif label.strip() == "Ability":
            ability = htmllib.unescape(val).strip()
    moves = [htmllib.unescape(m).strip() for m in re.findall(r'<span class="pcombat-move-name">(.*?)</span>', block)]
    return {
        "nature": nature, "item": item, "ability": ability, "moves": moves[:4],
        "role": one(r'<span class="pcombat-role-badge[^"]*"[^>]*>(.*?)</span>'),
        "confidence": one(r'<span class="pcombat-conf-label"[^>]*>(.*?)</span>'),
    }


def norm_move(m):
    return re.sub(r"[^a-z0-9]", "", m.lower())


if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    dex = sp_parse.dex_lists()
    out = {}
    fetched = 0
    for k, (dexname, num, name, path) in enumerate(dex, 1):
        block, net = fetch_block(name, fresh)
        if net:
            fetched += 1
            print(f"[{k}/{len(dex)}] {name}", file=sys.stderr)
            time.sleep(PAUSE)
        build = parse_block(block)
        if not build or not build["nature"]:
            out[name] = None
            continue
        # every move must be learnable in Z-A according to Serebii
        learn = sp_parse.species_page(path)["moves"]
        can = {norm_move(m["name"]) for m in learn["levelUp"] + learn["tm"]}
        if learn["alpha"]:
            can.add(norm_move(learn["alpha"]))
        build["notLearnable"] = [m for m in build["moves"] if norm_move(m) not in can]
        plus, minus = NATURES.get(build["nature"], ("", ""))
        build["plus"], build["minus"] = plus, minus
        build["source"] = page_url(name)
        out[name] = build
    with open(os.path.join(ROOT, "tools", "builds.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    have = sum(1 for v in out.values() if v)
    bad = {n: v["notLearnable"] for n, v in out.items() if v and v["notLearnable"]}
    print(f"Fetched {fetched} pages. Builds for {have}/{len(out)} Pokémon.", file=sys.stderr)
    print(f"{len(bad)} builds have moves Serebii says it can't learn in Z-A:", file=sys.stderr)
    for n, b in list(bad.items())[:40]:
        print(f"  {n}: {b}", file=sys.stderr)
    missing = [n for n, v in out.items() if not v]
    print(f"No build found for {len(missing)}:", missing[:40], file=sys.stderr)
