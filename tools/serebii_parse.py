"""
Reads the cached Serebii pages (see serebii_fetch.py) and pulls out the
Legends: Z-A data: dex numbers, locations, evolution methods, the Alpha
guaranteed move, the Z-A level-up and TM moves, and Mega Stone locations.
"""
import html as htmllib
import os
import re

import serebii_fetch as sf


def text(fragment):
    """HTML fragment → clean one-line text."""
    s = re.sub(r"<br\s*/?>", " · ", fragment)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmllib.unescape(s)
    s = re.sub(r"\s+", " ", s).strip(" ·")
    s = re.sub(r"(\s*·\s*)+", " · ", s)
    s = re.sub(r"\s+,", ",", s)
    return s


def dex_lists():
    """[(dex 'lumiose'|'hyperspace', number, name, page path)] in Serebii's order."""
    out = []
    for dex, page in (("lumiose", sf.INDEX_PAGES[0]), ("hyperspace", sf.INDEX_PAGES[1])):
        html, _ = sf.fetch(page)
        for label, name, path in sf.species_links(html):
            out.append((dex, int(label.lstrip("H#")), htmllib.unescape(name), path))
    return out


# ---------- evolution icons → words ----------
def evo_method(src, title):
    """Serebii shows evolution methods as small icons. Turn one into words."""
    f = os.path.basename(src).rsplit(".", 1)[0].lower()
    title = htmllib.unescape(title or "").strip()
    m = re.fullmatch(r"l(\d+)", f)
    if m:
        return f"Level {m.group(1)}"
    if f.startswith("mega"):
        return None  # Mega Evolution, not a real evolution
    if title and title.lower() not in ("level", ""):
        return title
    return EVO_ICON_WORDS.get(f, f.replace("-", " ").replace("_", " ").title())


# Icons whose title is empty or unhelpful. Extended as new icons turn up (the build lists unknown ones).
EVO_ICON_WORDS = {
    "happiness": "Level up with high friendship",
    "friendship": "Level up with high friendship",
    "trade": "Trade",
}


REGION_SUFFIX = {"g": "Galarian", "a": "Alolan", "h": "Hisuian", "p": "Paldean"}


def node_id(cell_html):
    """A Pokémon cell in the evolution table → 'page|Region' (e.g. '/pokedex-sv/meowth/|Galarian').
    The alt text is often missing, so the link (which page) and the picture file
    (052-g.png = Galarian form, 026-m.png = Mega) are used instead. None for Megas."""
    href = re.search(r'<a href="(/pokedex-sv/[^"]+)"', cell_html)
    src = re.search(r'<img[^>]*src="[^"]*/(\d+)(?:-([a-z]+))?\.png"', cell_html)
    page = href.group(1) if href else ""
    if page and not page.endswith("/") and not page.endswith(".shtml"):
        page += "/"
    suffix = src.group(2) if src else None
    if suffix and suffix.startswith("m"):
        return None
    region = REGION_SUFFIX.get(suffix or "", "")
    nat = src.group(1) if src else ""
    return f"{page}|{nat}|{region}"


def parse_evolutions(html):
    """Edges [(from name, to name, method)] from the Evolutionary Chain table."""
    i = html.find('class="evochain"')
    if i == -1:
        return []
    j = html.find("</table>", i)
    chunk = html[i:j]
    edges = []
    # Serebii doesn't always close its <tr>s, so split on the opening tag instead.
    # Layouts handled:
    #   linear:   A  →icon  B  →icon  C                     (one row)
    #   stacked:  A(rowspan) →icon B / next row: →icon C    (Slowpoke → Slowbro / Slowking)
    #   fan-out:  A alone / row of icons / row of Pokémon   (Eevee: icon n belongs to Pokémon n)
    anchor = None          # the Pokémon later rows branch from
    icon_row = []          # methods from a row that had only icons (Eevee layout)
    for row in re.split(r"<tr[^>]*>", chunk)[1:]:
        # 1) read the row as tokens: ("p", id, attrs) for a Pokémon, ("i", method) for an icon
        tokens = []
        for attrs, body in re.findall(r"<td([^>]*)>(.*?)(?=<td|</tr>|$)", row, re.S):
            img = re.search(r'<img[^>]*src="([^"]+)"', body)
            if not img:
                continue
            if "pkmn" in attrs:
                name = node_id(body)
                if name is not None:  # None = a Mega picture, not a real evolution
                    tokens.append(("p", name, attrs))
                elif tokens and tokens[-1][0] == "i":
                    tokens.pop()      # drop the Mega icon in front of it
            else:
                tt = re.search(r'title="([^"]*)"', body)
                al = re.search(r'alt="([^"]*)"', body)
                tokens.append(("i", evo_method(img.group(1), (tt.group(1) if tt else "") or (al.group(1) if al else "")) or ""))
        icons = [t[1] for t in tokens if t[0] == "i"]
        pkmn = [t for t in tokens if t[0] == "p"]
        n_lead_icons = next((k for k, t in enumerate(tokens) if t[0] == "p"), len(tokens))

        # 2) fan-out: k icons followed by k Pokémon (or an icon-only row, then a Pokémon-only row)
        if pkmn and anchor and n_lead_icons == len(icons) and (len(icons) == len(pkmn) > 1 or (not icons and len(icon_row) == len(pkmn) > 1)):
            methods = icons or icon_row
            for (_, name, _), how in zip(pkmn, methods):
                if how:
                    edges.append((anchor, name, how))
            icon_row = []
            continue
        if icons and not pkmn:
            icon_row = icons
            continue

        # 3) linear / stacked: each icon links the Pokémon before it (or the row's anchor) to the one after
        prev, pending = None, None
        for t in tokens:
            if t[0] == "i":
                pending = t[1]
                continue
            _, name, attrs = t
            src_from = prev or anchor
            if pending and src_from:
                edges.append((src_from, name, pending))
            pending = None
            prev = name
            if "rowspan" in attrs or "colspan" in attrs or anchor is None:
                anchor = name
    # keep the first method seen for each pair (regional variants repeat the same names)
    seen, out = set(), []
    for a, b, how in edges:
        if a != b and (a, b) not in seen:
            seen.add((a, b))
            out.append((a, b, re.sub(r"\s+", " ", how).strip()))
    return out


def parse_locations(html):
    """{'za': text, 'zamd': text} — the Legends: Z-A rows of the Locations table."""
    out = {}
    # only look inside the Locations table (the Flavor Text table below uses the same classes)
    i = html.find("<h2>Locations</h2>")
    if i == -1:
        return out
    j = html.find("Flavor Text", i)
    html = html[i:j if j != -1 else None]
    for cls, key in (("fooza", "za"), ("foozamd", "zamd")):
        m = re.search(r'<td class="%s"[^>]*>[^<]*</td>\s*<td class="fooinfo"[^>]*>(.*?)</td>' % cls, html, re.S)
        if m:
            out[key] = text(m.group(1))
    return out


def _move_rows(table_html, first_col):
    rows = []
    # each move row starts with two rowspan="2" cells (level or TM number, then the move link);
    # the rest of the row runs until the next row start (rows can hold a nested "Form" table)
    starts = list(re.finditer(r'<tr>\s*<td rowspan="2" class="fooinfo">(.*?)</td>\s*<td rowspan="2" class="fooinfo">(.*?)</td>', table_html, re.S))
    for k, m in enumerate(starts):
        a, name = m.groups()
        rest = table_html[m.end(): starts[k + 1].start() if k + 1 < len(starts) else len(table_html)]
        t = re.search(r'alt="[^"]* - (\w+)-type"', rest)
        c = re.search(r'alt="[^"]*: (\w+) Move"', rest)
        p = re.findall(r'<td class="cen">([^<]*)</td>', rest)
        lv = text(re.sub(r"<i>.*?</i>", "", a)) if first_col == "level" else text(a)
        plus = re.search(r"<i>(\d+)</i>", a)
        rows.append({
            "at": lv.replace("—", "Start"),
            "name": text(name),
            "type": t.group(1) if t else "",
            "cat": ("Status" if c and c.group(1) == "Other" else c.group(1)) if c else "",
            "power": (p[0].strip() if p else "").replace("--", "—"),
            "plusLv": plus.group(1) if plus else "",
        })
    return rows


def parse_moves(html):
    """Z-A level-up moves, TM moves and the Alpha guaranteed move."""
    out = {"levelUp": [], "tm": [], "alpha": ""}
    # The Z-A attack tables sit in their own block, before the Scarlet/Violet ones
    start = html.find('id="swshbdsp"')
    end = html.find('id="legends"', start)
    za = html[start:end if end != -1 else None] if start != -1 else html
    # cut the block into tables at each <h3> heading
    heads = list(re.finditer(r"<h3>(?:<a[^>]*></a>)?([^<]*)</h3>", za))
    seen_lv, seen_tm = set(), set()
    for k, h in enumerate(heads):
        title = h.group(1)
        body = za[h.end(): heads[k + 1].start() if k + 1 < len(heads) else len(za)]
        if "Level Up" in title:          # "Standard Level Up", "Level Up - Male", "… - Galarian Form"
            for r in _move_rows(body, "level"):
                if r["name"] not in seen_lv:
                    seen_lv.add(r["name"])
                    out["levelUp"].append(r)
        elif "Technical Machine" in title:
            for r in _move_rows(body, "tm"):
                if r["name"] not in seen_tm:
                    seen_tm.add(r["name"])
                    out["tm"].append(r)
    i = html.find("Alpha Guaranteed Move")
    if i != -1:
        j = html.find("</table>", i)
        m = re.search(r'<a href="/attackdex-sv/[^"]+">(.*?)</a>', html[i:j], re.S)
        if m:
            out["alpha"] = text(m.group(1))
    return out


def mega_stones():
    """{(species name, 'X'|'Y'|'Z'|''): {'stone': name, 'where': text}}"""
    html, _ = sf.fetch(sf.INDEX_PAGES[2])
    out = {}
    for m in re.finditer(r'<td class="fooinfo"><a href="/itemdex/[^"]+">([^<]+)</a></td>\s*<td class="fooinfo">([^<]*)</td><td class="fooinfo">(.*?)</td></tr>', html, re.S):
        stone, effect, where = htmllib.unescape(m.group(1)).strip(), m.group(2), m.group(3)
        sp = re.search(r"An? (.+?) holding this stone", effect) or re.search(r"(\w+) will be able to Mega Evolve", effect)
        if not sp:
            continue
        suffix = re.search(r"\s([XYZ])$", stone)
        out[(htmllib.unescape(sp.group(1)), suffix.group(1) if suffix else "")] = {
            "stone": stone,
            "where": text(re.sub(r"<b>Shop</b>\s*(<br\s*/?>)?\s*", "Shop: ", where)),
        }
    return out


def species_page(path):
    html, _ = sf.fetch(path)
    return {
        "locations": parse_locations(html),
        "evolutions": parse_evolutions(html),
        "moves": parse_moves(html),
    }


if __name__ == "__main__":
    import json
    import sys
    for p in sys.argv[1:] or ["/pokedex-sv/meganium/"]:
        print(json.dumps(species_page(p), indent=1, ensure_ascii=False)[:2500])
