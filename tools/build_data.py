"""
Builds data/pokedex.js from the Google Sheet export (tools/sheet.json)
plus PokeAPI (pictures, gender differences, Mega forms, evolution chains).

Run:  python tools/build_data.py
PokeAPI answers are cached in tools/.cache so re-runs are fast and offline-friendly.

To refresh from the sheet: export the "Full List" tab values to tools/sheet.json
in the shape {"values": [[header...], [row...], ...]} and run again.
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "tools", ".cache")
os.makedirs(CACHE, exist_ok=True)
API = "https://pokeapi.co/api/v2/"


# ---------- PokeAPI with a disk cache ----------
def api(path):
    """GET a PokeAPI path (or full URL), cached on disk. Returns None on 404."""
    if path.startswith("http"):
        path = path[len(API):]
    key = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_") + ".json"
    fp = os.path.join(CACHE, key)
    if os.path.exists(fp):
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    for attempt in range(4):
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "za-pokedex-build"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = None
                break
            time.sleep(1 + attempt)
        except Exception:
            time.sleep(1 + attempt)
    else:
        raise RuntimeError("PokeAPI failed: " + path)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def slug(name):
    """'Mr. Mime' -> 'mr-mime', 'Flabébé' -> 'flabebe', "Farfetch'd" -> 'farfetchd'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace("'", "").replace(".", "").strip()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\r", "").replace("\t", " ")).strip()


def clean_multiline(s):
    lines = [clean(x) for x in (s or "").replace("\r", "").split("\n")]
    return "\n".join(x for x in lines if x)


# ---------- 1. Read the sheet ----------
with open(os.path.join(ROOT, "tools", "sheet.json"), encoding="utf-8") as f:
    values = json.load(f)["values"]
rows = [r + [""] * (17 - len(r)) for r in values[1:] if len(r) > 1 and r[1].strip()]

# Variant words the sheet sometimes puts in the Form column. The app makes the
# Normal / Shiny / Alpha / Shiny Alpha versions itself, so these are stripped
# off and only used to carry over what is already ticked in the sheet.
def split_variant(form):
    f = clean(form)
    shiny = alpha = False
    if re.match(r"(?i)^shiny\b", f):
        shiny, f = True, f[5:].strip()
    if re.match(r"(?i)^alpha\b", f):
        alpha, f = True, f[5:].strip()
    return (f or "Standard"), shiny, alpha


# Sheet typos / shifted cells fixed here (sheet row order is kept).
FORM_FIXES = {
    ("Larvitar", "Jumbo Variety"): "Standard",
    ("Pumpkaboo", "Standard"): "Small Variety",
    ("Gourgeist", "Jumbo Variety"): "Small Variety",
}

species = []          # ordered list of species dicts
by_name = {}
seed = {}             # "speciesKey|form|variant" -> {"caught":bool,"lv100":bool}

# Official dex numbers come from Serebii's Lumiose and Hyperspace Pokédex lists.
# (The sheet's own numbers have a few drag-fill mistakes, e.g. "H#9" for 90.)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import serebii_parse as sp_parse  # noqa: E402

SEREBII_DEX = {}      # name -> (dex, number, serebii page path)
for dex, num, nm, path in sp_parse.dex_lists():
    SEREBII_DEX[nm] = (dex, num, path)
lumiose_order = [n for n, v in sorted(SEREBII_DEX.items(), key=lambda x: x[1][1]) if v[0] == "lumiose"]
hyper_order = [n for n, v in sorted(SEREBII_DEX.items(), key=lambda x: x[1][1]) if v[0] == "hyperspace"]
sheet_names = {clean(r[1]) for r in rows}
for nm in SEREBII_DEX:
    if nm not in sheet_names:
        print(f"WARNING: {nm} is in Serebii's Pokédex but not in the sheet", file=sys.stderr)
for nm in sheet_names - set(SEREBII_DEX):
    print(f"WARNING: {nm} is in the sheet but not in Serebii's Pokédex (skipped)", file=sys.stderr)
rows = [r for r in rows if clean(r[1]) in SEREBII_DEX]

# Pumpkaboo/Gourgeist rows in the sheet are shifted by one; rebuild those lines cleanly.
SIZE_FORMS = ["Small Variety", "Medium Variety", "Large Variety", "Jumbo Variety"]

for r in rows:
    name = clean(r[1])
    form, shiny, alpha = split_variant(r[2])
    form = FORM_FIXES.get((name, form), form)
    if name not in by_name:
        is_h = SEREBII_DEX[name][0] == "hyperspace"
        num = SEREBII_DEX[name][1]
        sp = {
            "key": ("H" if is_h else "L") + str(num),
            "dex": "hyperspace" if is_h else "lumiose",
            "num": num,
            "name": name,
            "forms": [],
        }
        by_name[name] = sp
        species.append(sp)
    sp = by_name[name]
    caught = clean(r[15]).upper() == "TRUE"
    lv100 = clean(r[16]).upper() == "TRUE"
    existing = next((x for x in sp["forms"] if x["form"] == form), None)
    if existing is None:
        existing = {
            "form": form,
            "types": [t for t in (clean(r[3]), clean(r[4])) if t],
            "nature": clean(r[5]),
            "plus": clean(r[6]),
            "minus": clean(r[7]),
            "moves": [clean(m) for m in r[8:12] if clean(m)],
            "item": clean(r[12]),
            "info": clean_multiline(r[14]),
        }
        sp["forms"].append(existing)
    else:
        # Fill gaps from later rows (e.g. a Shiny row that has a location the Standard row lacks)
        if not existing["info"] and clean(r[14]):
            existing["info"] = clean_multiline(r[14])
        if not existing["moves"] and any(clean(m) for m in r[8:12]):
            existing["moves"] = [clean(m) for m in r[8:12] if clean(m)]
            existing["item"] = clean(r[12])
    variant = ("shinyalpha" if shiny and alpha else "shiny" if shiny else "alpha" if alpha else "normal")
    if caught or lv100:
        seed[f"{sp['key']}|{form}|{variant}"] = {"caught": caught, "lv100": lv100}

# Pumpkaboo / Gourgeist: make sure all four sizes exist exactly once, in order.
for nm in ("Pumpkaboo", "Gourgeist"):
    sp = by_name.get(nm)
    if not sp:
        continue
    tmpl = dict(sp["forms"][0])
    have = {f["form"]: f for f in sp["forms"]}
    sp["forms"] = [dict(have.get(s, tmpl), form=s) for s in SIZE_FORMS]

# ---------- 2. PokeAPI lookups ----------
SPECIES_SLUG_FIX = {"mr-rime": "mr-rime", "mime-jr": "mime-jr", "porygon-z": "porygon-z"}


def fetch_species(sp):
    s = slug(sp["name"])
    s = SPECIES_SLUG_FIX.get(s, s)
    return sp["key"], api("pokemon-species/" + s)


print("Fetching species…", file=sys.stderr)
with ThreadPoolExecutor(8) as ex:
    spec_data = dict(ex.map(fetch_species, species))

missing = [sp["name"] for sp in species if not spec_data[sp["key"]]]
if missing:
    print("WARNING: no PokeAPI species for", missing, file=sys.stderr)

# all pokemon (varieties) we need
variety_names = set()
for sp in species:
    d = spec_data[sp["key"]]
    if d:
        for v in d["varieties"]:
            variety_names.add(v["pokemon"]["name"])

print(f"Fetching {len(variety_names)} varieties…", file=sys.stderr)
with ThreadPoolExecutor(8) as ex:
    poke = dict(zip(sorted(variety_names), ex.map(lambda n: api("pokemon/" + n), sorted(variety_names))))

# pokemon-forms (cosmetic forms like Vivillon patterns, Flabébé colours, Furfrou trims)
form_names = set()
for p in poke.values():
    if p:
        for f in p["forms"]:
            form_names.add(f["name"])
print(f"Fetching {len(form_names)} forms…", file=sys.stderr)
with ThreadPoolExecutor(8) as ex:
    pforms = dict(zip(sorted(form_names), ex.map(lambda n: api("pokemon-form/" + n), sorted(form_names))))

# evolution chains
chain_urls = {spec_data[k]["evolution_chain"]["url"] for k in spec_data if spec_data[k] and spec_data[k].get("evolution_chain")}
print(f"Fetching {len(chain_urls)} evolution chains…", file=sys.stderr)
with ThreadPoolExecutor(8) as ex:
    chains = dict(zip(sorted(chain_urls), ex.map(api, sorted(chain_urls))))


def pics_from_pokemon(p, female=False):
    """Best pictures for a pokemon: HOME renders, then official art, then game sprites."""
    s = p["sprites"]
    home = (s.get("other") or {}).get("home") or {}
    art = (s.get("other") or {}).get("official-artwork") or {}
    if female:
        n = home.get("front_female") or s.get("front_female")
        sh = home.get("front_shiny_female") or s.get("front_shiny_female")
        if n:
            return {"n": n, "s": sh or n}
    n = home.get("front_default") or art.get("front_default") or s.get("front_default")
    sh = home.get("front_shiny") or art.get("front_shiny") or s.get("front_shiny") or n
    return {"n": n, "s": sh}


def pics_from_form(fd):
    s = fd["sprites"]
    return {"n": s.get("front_default"), "s": s.get("front_shiny") or s.get("front_default")}


FORM_WORDS = {
    # sheet label -> pokemon-form / pokemon suffix
    "red flower": "red", "yellow flower": "yellow", "orange flower": "orange",
    "blue flower": "blue", "white flower": "white", "eternal flower": "eternal",
    "marine pattern": "marine", "meadow pattern": "meadow",
    "natural form": "", "heart trim": "heart", "star trim": "star", "diamond trim": "diamond",
    "deputante trim": "debutante", "debutante trim": "debutante", "matron trim": "matron",
    "dandy trim": "dandy", "la reine trim": "la-reine", "kabuki trim": "kabuki", "pharaoh trim": "pharaoh",
    "small variety": "small", "medium variety": "average", "large variety": "large", "jumbo variety": "super",
    "galarian": "galar", "alolan": "alola", "hisuian": "hisui", "paldean": "paldea",
    # default looks that only got a clearer name
    "curly form": "", "green plumage": "", "amped form": "", "chest form": "",
    "hoopa confined": "", "ordinary form": "", "50% forme": "",
}
FORM_LABEL_FIX = {"Deputante Trim": "Debutante Trim"}


def resolve_pics(sp, form_label):
    """Find pictures for a sheet form label."""
    d = spec_data[sp["key"]]
    if not d:
        return None
    default_var = next(v["pokemon"]["name"] for v in d["varieties"] if v["is_default"])
    base = poke[default_var]
    lab = form_label.lower()
    if lab in ("standard", "", "no gender", "male"):
        # Species whose male/female are separate pokemon (Meowstic, Indeedee…)
        if lab == "male":
            for v in d["varieties"]:
                if v["pokemon"]["name"].endswith("-male"):
                    return pics_from_pokemon(poke[v["pokemon"]["name"]])
        return pics_from_pokemon(base)
    if lab == "female":
        for v in d["varieties"]:
            if v["pokemon"]["name"].endswith("-female"):
                return pics_from_pokemon(poke[v["pokemon"]["name"]])
        return pics_from_pokemon(base, female=True)
    if lab.startswith("mega"):
        suffix = lab.replace(" ", "-")  # "mega", "mega-x", "mega-y", "mega-z"
        for v in d["varieties"]:
            vn = v["pokemon"]["name"]
            if vn.endswith("-" + suffix) and poke.get(vn):
                return pics_from_pokemon(poke[vn])
        return pics_from_pokemon(base)
    word = FORM_WORDS.get(lab)
    if word is not None:
        sbase = slug(sp["name"])
        if word == "":
            return pics_from_pokemon(base)
        # a full pokemon variety (pumpkaboo-small, slowpoke-galar, floette-eternal)
        for v in d["varieties"]:
            vn = v["pokemon"]["name"]
            if vn == f"{sbase}-{word}" and poke.get(vn):
                return pics_from_pokemon(poke[vn])
        # a cosmetic form (flabebe-blue, vivillon-marine, furfrou-heart)
        fd = pforms.get(f"{sbase}-{word}")
        if fd:
            return pics_from_form(fd)
        if word in ("red", "meadow"):  # default cosmetic form
            return pics_from_pokemon(base)
    print(f"  no picture match for {sp['name']} / {form_label}", file=sys.stderr)
    return pics_from_pokemon(base)


# ---------- 3. Add Megas the sheet doesn't list yet ----------
def mega_label(vn, base_slug):
    """'charizard-mega-x' -> 'Mega X', 'meowstic-female-mega' -> 'Mega (Female)',
    'tatsugiri-curly-mega' -> 'Mega (Curly)', 'magearna-original-mega' -> 'Mega (Original Color)'."""
    rest = vn[len(base_slug) + 1:]
    if rest.startswith("mega"):
        return " ".join(w.upper() if len(w) == 1 else w.capitalize() for w in rest.split("-"))
    pre = rest[: rest.index("-mega")]
    if pre == "male":
        return "Mega"  # the sheet's plain "Mega" is the male one
    pre = {"original": "Original Color"}.get(pre, pre.capitalize())
    return f"Mega ({pre})"


def types_of(vn):
    p = poke.get(vn)
    return [t["type"]["name"].capitalize() for t in p["types"]] if p else []


def new_form(template, label, var, auto=True):
    return {
        "form": label, "types": types_of(var) or template["types"], "nature": template["nature"],
        # forms the sheet doesn't list share the main form's build (Megas get their stone below)
        "plus": template["plus"], "minus": template["minus"], "moves": list(template["moves"]),
        "item": template["item"],
        "info": "", "auto": auto, "var": var,
    }


# Catchable look-different forms the sheet doesn't list yet.
# species -> (new label for the sheet's "Standard" row or None, [(pokeapi variety, label)])
# Only forms known to matter in Z-A (several are needed to evolve, e.g. Galarian Meowth → Perrserker).
# Not added because they may not be in the game: Alolan/Hisuian forms of Raichu, Meowth, Persian,
# Marowak, Sliggoo, Goodra, Avalugg; Galarian Stunfisk; Pikachu caps. Add a sheet row
# (e.g. Form = "Alolan") and rebuild if one turns up.
EXTRA_FORMS = {
    "Meowth": (None, [("meowth-galar", "Galarian")]),
    "Farfetch'd": (None, [("farfetchd-galar", "Galarian")]),
    "Yamask": (None, [("yamask-galar", "Galarian")]),
    "Mr. Mime": (None, [("mr-mime-galar", "Galarian")]),
    "Qwilfish": (None, [("qwilfish-hisui", "Hisuian")]),
    "Rotom": (None, [("rotom-heat", "Heat Rotom"), ("rotom-wash", "Wash Rotom"), ("rotom-frost", "Frost Rotom"),
                     ("rotom-fan", "Fan Rotom"), ("rotom-mow", "Mow Rotom")]),
    "Tatsugiri": ("Curly Form", [("tatsugiri-droopy", "Droopy Form"), ("tatsugiri-stretchy", "Stretchy Form")]),
    "Squawkabilly": ("Green Plumage", [("squawkabilly-blue-plumage", "Blue Plumage"),
                                       ("squawkabilly-yellow-plumage", "Yellow Plumage"),
                                       ("squawkabilly-white-plumage", "White Plumage")]),
    "Toxtricity": ("Amped Form", [("toxtricity-low-key", "Low Key Form")]),
    "Gimmighoul": ("Chest Form", [("gimmighoul-roaming", "Roaming Form")]),
    "Hoopa": ("Hoopa Confined", [("hoopa-unbound", "Hoopa Unbound")]),
    "Keldeo": ("Ordinary Form", [("keldeo-resolute", "Resolute Form")]),
    "Magearna": (None, [("magearna-original", "Original Color")]),
    "Zygarde": ("50% Forme", [("zygarde-10", "10% Forme")]),
}
for nm, (rename, extras) in EXTRA_FORMS.items():
    sp = by_name.get(nm)
    if not sp:
        continue
    if rename:
        for f in sp["forms"]:
            if f["form"] == "Standard":
                f["form"] = rename
    have = [f["form"] for f in sp["forms"]]
    for var, label in extras:
        if label not in have and poke.get(var):
            sp["forms"].append(new_form(sp["forms"][0], label, var))

# Species that look different as male / female but the sheet lists only one row.
for sp in species:
    d = spec_data[sp["key"]]
    if not d or not d["has_gender_differences"]:
        continue
    labels = [f["form"] for f in sp["forms"]]
    if "Male" in labels or "Female" in labels or "Standard" not in labels:
        continue
    i = labels.index("Standard")
    male = dict(sp["forms"][i], form="Male")
    female = dict(sp["forms"][i], form="Female")
    sp["forms"][i:i + 1] = [male, female]

# Drop "Mega" rows for Pokémon that have no Mega Evolution at all (e.g. the sheet's Machamp Mega)
for sp in species:
    d = spec_data[sp["key"]]
    has_mega = d and any("-mega" in v["pokemon"]["name"] for v in d["varieties"])
    if not has_mega:
        bad = [f["form"] for f in sp["forms"] if f["form"].lower().startswith("mega")]
        if bad:
            print(f"Removed {sp['name']} {bad}: no such Mega Evolution", file=sys.stderr)
            sp["forms"] = [f for f in sp["forms"] if not f["form"].lower().startswith("mega")]

added_megas = []
for sp in species:
    d = spec_data[sp["key"]]
    if not d:
        continue
    sbase = slug(sp["name"])
    megas = [v["pokemon"]["name"] for v in d["varieties"] if "-mega" in v["pokemon"]["name"]]
    have = [f["form"] for f in sp["forms"]]
    # base for a mega's nature/stats: the first non-mega form
    template = next(f for f in sp["forms"] if not f["form"].lower().startswith("mega"))
    for vn in megas:
        lab = mega_label(vn, sbase)
        if lab in have:
            continue
        sp["forms"].append(new_form(template, lab, vn))
        have.append(lab)
        added_megas.append(f"{sp['name']} {lab}")
print(f"Added {len(added_megas)} Megas from PokeAPI", file=sys.stderr)

# ---------- 4. Assemble output ----------
name_to_key = {slug(sp["name"]): sp["key"] for sp in species}


def flatten_chain(node, depth=0, out=None):
    out = [] if out is None else out
    det = node["evolution_details"][0] if node["evolution_details"] else None
    out.append({"slug": node["species"]["name"], "depth": depth})
    for c in node["evolves_to"]:
        flatten_chain(c, depth + 1, out)
    return out


# ---------- Serebii: locations, evolution methods, Alpha move, Z-A moves, Mega Stones ----------
print("Reading Serebii pages…", file=sys.stderr)
STONES = sp_parse.mega_stones()
serebii = {sp["key"]: sp_parse.species_page(SEREBII_DEX[sp["name"]][2]) for sp in species}
# Serebii evolution nodes look like "/pokedex-sv/meowth/|052|Galarian" → turn into names
NAT_TO_NAME = {spec_data[s["key"]]["id"]: s["name"] for s in species if spec_data[s["key"]]}
PATH_TO_NAME = {v[2]: n for n, v in SEREBII_DEX.items()}


def node_name(node):
    page, nat, region = node.split("|")
    name = NAT_TO_NAME.get(int(nat)) if nat.isdigit() else None
    name = name or PATH_TO_NAME.get(page)
    if not name:  # not in this game's Pokédex: make a readable name from the page address
        name = page.rstrip("/").split("/")[-1].replace(".shtml", "").replace("-", " ").title()
    return name, region


# every evolution edge Serebii knows: (from, to) -> {"how", "fromRegion"}
EVO_EDGES = {}
for data in serebii.values():
    for a, b, how in data["evolutions"]:
        (an, ar), (bn, br) = node_name(a), node_name(b)
        if how and an != bn:
            EVO_EDGES.setdefault((an, bn), {"how": how, "region": ar, "toRegion": br})
unused_stones = set(STONES)


def stone_for(sp_name, label):
    """Mega form label → Serebii Mega Stone entry ('Mega X' → the X stone)."""
    m = re.match(r"Mega(?: ([XYZ]))?", label)
    k = (sp_name, m.group(1) or "" if m else "")
    if k not in STONES and sp_name == "Floette":
        k = next((x for x in STONES if "Floette" in x[0]), k)
    unused_stones.discard(k)
    if sp_name == "Rayquaza":
        return {"stone": "No Mega Stone needed", "where": "Rayquaza Mega Evolves when it knows Dragon Ascent"}
    return STONES.get(k)


_bp = os.path.join(ROOT, "tools", "builds_final.json")
BUILDS = {n: {"note": b["note"], "url": b["url"]} for n, b in json.load(open(_bp, encoding="utf-8")).items()} if os.path.exists(_bp) else {}

out_species = []
for sp in species:
    d = spec_data[sp["key"]]
    sb = serebii[sp["key"]]
    # "Where to find" lines from Serebii; the sheet's text stays as a fallback
    where = []
    if sb["locations"].get("za"):
        where.append({"label": "Legends: Z-A", "text": sb["locations"]["za"]})
    if sb["locations"].get("zamd"):
        where.append({"label": "Mega Dimension", "text": sb["locations"]["zamd"]})
    # how this Pokémon evolves (regional parents shown, e.g. "Meowth (Galarian)")
    evolves_from = [
        {"from": a + (f" ({e['region']})" if e["region"] else ""), "how": e["how"],
         "into": e["toRegion"]}
        for (a, b), e in EVO_EDGES.items() if b == sp["name"]
    ]

    forms_out = []
    for f in sp["forms"]:
        label = FORM_LABEL_FIX.get(f["form"], f["form"])
        is_mega = label.lower().startswith("mega")
        if f.get("var") and poke.get(f["var"]):
            pics = pics_from_pokemon(poke[f["var"]])
        else:
            pics = resolve_pics(sp, label) or {"n": None, "s": None}
        stone = stone_for(sp["name"], label) if is_mega else None
        item = f["item"]
        if is_mega and f.get("auto") and stone and stone["stone"] != "No Mega Stone needed":
            item = stone["stone"]  # a Mega holds its Mega Stone
        forms_out.append({
            "form": label, "types": f["types"], "nature": f["nature"], "plus": f["plus"],
            "minus": f["minus"], "moves": f["moves"], "item": item,
            "sheetInfo": f["info"],  # the sheet's own location / evolution note
            "stone": stone,          # Mega forms: {"stone", "where"} from Serebii
            "mega": is_mega, "auto": f.get("auto", False), "img": pics["n"], "shinyImg": pics["s"],
        })
    chain = []
    if d and d.get("evolution_chain"):
        flat = flatten_chain(chains[d["evolution_chain"]["url"]]["chain"])
        for i, c in enumerate(flat):
            chain.append({"name": c["slug"], "depth": c["depth"], "key": name_to_key.get(c["slug"])})
    out_species.append({
        "key": sp["key"], "dex": sp["dex"], "num": sp["num"], "name": sp["name"],
        "national": d["id"] if d else None,
        "legendary": bool(d and (d["is_legendary"] or d["is_mythical"])),
        "genderDiff": bool(d and d["has_gender_differences"]),
        "where": where, "evolvesFrom": evolves_from,
        "alphaMove": sb["moves"]["alpha"],
        # where the nature/moveset came from (tools/builds_make.py), shown under the moveset
        "build": BUILDS.get(sp["name"]),
        "learn": {"levelUp": sb["moves"]["levelUp"], "tm": sb["moves"]["tm"]},
        "serebii": "https://www.serebii.net" + SEREBII_DEX[sp["name"]][2],
        "forms": forms_out, "chain": chain,
    })

if unused_stones:
    print("Mega Stones not matched to a form:", sorted(unused_stones), file=sys.stderr)
no_where = [s["name"] for s in out_species if not s["where"]]
if no_where:
    print(f"{len(no_where)} Pokémon have no Serebii location:", no_where[:20], file=sys.stderr)

# Fill chain display names from our own list (keeps sheet spelling like Flabébé)
key_to_name = {s["key"]: s["name"] for s in out_species}
for s in out_species:
    for c in s["chain"]:
        c["name"] = key_to_name.get(c["key"]) or c["name"].replace("-", " ").title()
    # how each chain member evolves (from Serebii), shown under the arrows
    for i, c in enumerate(s["chain"]):
        if c["depth"] == 0:
            continue
        parent = next(p for p in reversed(s["chain"][:i]) if p["depth"] == c["depth"] - 1)
        c["how"] = (EVO_EDGES.get((parent["name"], c["name"])) or {}).get("how", "")

payload = {"built": time.strftime("%Y-%m-%d"), "species": out_species, "seed": seed}
with open(os.path.join(ROOT, "data", "pokedex.js"), "w", encoding="utf-8") as f:
    f.write("// Generated by tools/build_data.py — do not edit by hand; edit the sheet and rebuild.\n")
    f.write("window.ZA_DEX = ")
    json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")

n_forms = sum(len(s["forms"]) for s in out_species)
print(f"Wrote {len(out_species)} species, {n_forms} forms, {len(seed)} ticked entries carried over.", file=sys.stderr)
