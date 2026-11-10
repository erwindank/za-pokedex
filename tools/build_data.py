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

lumiose_order = []    # base dex in sheet order
hyper_order = []
for r in rows:
    name = clean(r[1])
    is_h = clean(r[0]).upper().startswith("H")
    lst = hyper_order if is_h else lumiose_order
    if name not in lst and name not in (hyper_order if not is_h else lumiose_order):
        lst.append(name)

# Pumpkaboo/Gourgeist rows in the sheet are shifted by one; rebuild those lines cleanly.
SIZE_FORMS = ["Small Variety", "Medium Variety", "Large Variety", "Jumbo Variety"]

for r in rows:
    name = clean(r[1])
    form, shiny, alpha = split_variant(r[2])
    form = FORM_FIXES.get((name, form), form)
    if name not in by_name:
        is_h = clean(r[0]).upper().startswith("H")
        num = (hyper_order.index(name) + 1) if is_h else (lumiose_order.index(name) + 1)
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
        "plus": template["plus"], "minus": template["minus"], "moves": [], "item": "",
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


out_species = []
for sp in species:
    d = spec_data[sp["key"]]
    forms_out = []
    for f in sp["forms"]:
        label = FORM_LABEL_FIX.get(f["form"], f["form"])
        is_mega = label.lower().startswith("mega")
        if f.get("var") and poke.get(f["var"]):
            pics = pics_from_pokemon(poke[f["var"]])
        else:
            pics = resolve_pics(sp, label) or {"n": None, "s": None}
        forms_out.append({
            "form": label, "types": f["types"], "nature": f["nature"], "plus": f["plus"],
            "minus": f["minus"], "moves": f["moves"], "item": f["item"], "info": f["info"],
            "mega": is_mega, "auto": f.get("auto", False), "img": pics["n"], "shinyImg": pics["s"],
        })
    chain = []
    if d and d.get("evolution_chain"):
        for c in flatten_chain(chains[d["evolution_chain"]["url"]]["chain"]):
            chain.append({"name": c["slug"], "depth": c["depth"], "key": name_to_key.get(c["slug"])})
    out_species.append({
        "key": sp["key"], "dex": sp["dex"], "num": sp["num"], "name": sp["name"],
        "national": d["id"] if d else None,
        "legendary": bool(d and (d["is_legendary"] or d["is_mythical"])),
        "genderDiff": bool(d and d["has_gender_differences"]),
        "forms": forms_out, "chain": chain,
    })

# Fill chain display names from our own list (keeps sheet spelling like Flabébé)
key_to_name = {s["key"]: s["name"] for s in out_species}
for s in out_species:
    for c in s["chain"]:
        c["name"] = key_to_name.get(c["key"]) or c["name"].replace("-", " ").title()

payload = {"built": time.strftime("%Y-%m-%d"), "species": out_species, "seed": seed}
with open(os.path.join(ROOT, "data", "pokedex.js"), "w", encoding="utf-8") as f:
    f.write("// Generated by tools/build_data.py — do not edit by hand; edit the sheet and rebuild.\n")
    f.write("window.ZA_DEX = ")
    json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")

n_forms = sum(len(s["forms"]) for s in out_species)
print(f"Wrote {len(out_species)} species, {n_forms} forms, {len(seed)} ticked entries carried over.", file=sys.stderr)
