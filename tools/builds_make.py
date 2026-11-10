"""
Turns RankedBoost's builds (tools/builds.json, from builds_fetch.py) into builds
that actually work in Legends: Z-A, using Serebii's Z-A data:

- nature: RankedBoost's pick
- moves: RankedBoost's moves the Pokémon can learn in Z-A are kept; any it can't
  learn in Z-A are swapped for the strongest legal fit from Serebii's Z-A move list
- item: kept if it exists in Z-A, otherwise swapped for a Z-A item with the same job
- Pokémon with no RankedBoost page get a build made from their stats + Z-A moves

Writes tools/builds_final.json: {name: {nature, plus, minus, moves[4], item, note}}
"""
import html as htmllib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import serebii_parse as sp_parse  # noqa: E402
from builds_fetch import NATURES, norm_move  # noqa: E402

CACHE = os.path.join(ROOT, "tools", ".cache")

# Moves that look strong on paper but are bad picks (recharge, faint, charge turn…)
AVOID = {norm_move(m) for m in [
    "Hyper Beam", "Giga Impact", "Explosion", "Self-Destruct", "Solar Beam", "Solar Blade", "Sky Attack",
    "Razor Wind", "Skull Bash", "Focus Punch", "Dream Eater", "Last Resort", "Frenzy Plant", "Blast Burn",
    "Hydro Cannon", "Rock Wrecker", "Future Sight", "Belch", "Steel Beam", "Mind Blown", "Natural Gift",
    "Fling", "Memento", "Final Gambit", "Head Smash", "Prismatic Laser", "Eternabeam", "Meteor Assault",
    "Roar of Time", "Shadow Force", "Phantom Force", "Fly", "Dig", "Dive", "Bounce", "Freeze Shock", "Ice Burn",
    "Synchronoise", "Snore", "Spit Up", "Stomping Tantrum", "Rollout", "Ice Ball", "Uproar", "Thrash", "Outrage",
    "Petal Dance", "Bide", "Counter", "Mirror Coat", "Metal Burst", "Endeavor", "Super Fang", "Seismic Toss",
    "Night Shade", "Dragon Rage", "Sonic Boom", "Present", "Magnitude", "Return", "Frustration",
]}

# Items that don't exist in Z-A → a Z-A item that does the same job
ITEM_SWAP = {
    "Choice Band": "Life Orb", "Choice Specs": "Life Orb", "Choice Scarf": "Life Orb",
    "Heavy Duty Boots": "Leftovers", "Heavy-Duty Boots": "Leftovers", "Air Balloon": "Leftovers",
    "Black Sludge": "Leftovers", "Light Clay": "Leftovers", "Flame Orb": "Leftovers", "Toxic Orb": "Leftovers",
    "Throat Spray": "Life Orb", "Icy Rock": "Leftovers", "Smooth Rock": "Leftovers", "Damp Rock": "Leftovers",
    "Ability Shield": "Leftovers", "Mirror Herb": "White Herb", "Lagging Tail": "Leftovers",
    "Eject Pack": "Leftovers", "Loaded Dice": "Life Orb", "Wide Lens": "Scope Lens", "Nothing": "",
}


def za_items():
    html, _ = __import__("serebii_fetch").fetch("/legendsz-a/items.shtml")
    return {htmllib.unescape(m).strip() for m in re.findall(r'<a href="/itemdex/[^"]+">([^<]+)</a>', html)}


def pokeapi(path):
    fp = os.path.join(CACHE, re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_") + ".json")
    return json.load(open(fp, encoding="utf-8")) if os.path.exists(fp) else None


def base_stats(name):
    """Base stats + types of the species' default form, from the cached PokeAPI data."""
    s = re.sub(r"[^a-z0-9]+", "-", __import__("unicodedata").normalize("NFKD", name)
               .encode("ascii", "ignore").decode().lower().replace("'", "").replace(".", "")).strip("-")
    spec = pokeapi("pokemon-species/" + s)
    if not spec:
        return None, []
    default = next(v["pokemon"]["name"] for v in spec["varieties"] if v["is_default"])
    p = pokeapi("pokemon/" + default)
    stats = {x["stat"]["name"]: x["base_stat"] for x in p["stats"]}
    return stats, [t["type"]["name"].capitalize() for t in p["types"]]


# Status moves worth a slot, best first. Setup moves only go on the matching kind of attacker.
SETUP = {
    "Physical": ["Swords Dance", "Dragon Dance", "Bulk Up", "Shell Smash", "Coil", "Hone Claws"],
    "Special": ["Nasty Plot", "Quiver Dance", "Calm Mind", "Shell Smash", "Tail Glow"],
}
SUPPORT = ["Recover", "Roost", "Slack Off", "Soft-Boiled", "Synthesis", "Moonlight", "Morning Sun", "Milk Drink",
           "Wish", "Protect", "Will-O-Wisp", "Thunder Wave", "Toxic", "Leech Seed", "Spikes", "Stealth Rock",
           "Reflect", "Light Screen", "Substitute", "Yawn", "Taunt", "Encore", "Trick Room", "Agility", "Rest"]


def power(m):
    try:
        return int(m["power"])
    except (TypeError, ValueError):
        return 0


def pick_moves(kept, legal, types, cat):
    """Fill up to 4 moves: keep `kept`; add a STAB move of each type; one setup/support
    move if the set has none; then coverage of new types; then support moves."""
    by_name = {norm_move(m["name"]): m for m in legal}
    # use Serebii's spelling for kept moves ("Will O Wisp" → "Will-O-Wisp")
    chosen = [by_name[norm_move(m)]["name"] if norm_move(m) in by_name else m for m in kept]
    names = {norm_move(m) for m in chosen}
    have_types = {by_name[norm_move(m)]["type"] for m in chosen if norm_move(m) in by_name and power(by_name[norm_move(m)])}
    has_status = any(norm_move(m) in by_name and not power(by_name[norm_move(m)]) for m in chosen)

    attacks = [m for m in legal if power(m) > 0 and m["cat"] == cat and norm_move(m["name"]) not in AVOID]

    def score(m):
        return power(m) * (1.5 if m["type"] in types else 1)

    def add(name):
        m = by_name[norm_move(name)]
        chosen.append(m["name"])
        names.add(norm_move(m["name"]))
        if power(m):
            have_types.add(m["type"])

    def first_legal(lst):
        return next((x for x in lst if norm_move(x) in by_name and norm_move(x) not in names), None)

    # 1) a STAB move for each of its types
    for t in types:
        if len(chosen) >= 4 or t in have_types:
            continue
        pool = [m for m in attacks if m["type"] == t and norm_move(m["name"]) not in names]
        if pool:
            add(max(pool, key=score)["name"])
    # 2) one setup or support move if the set has no status move yet
    if len(chosen) < 4 and not has_status:
        s = first_legal(SETUP.get(cat, [])) or (first_legal(SUPPORT) if len(attacks) < 3 else None)
        if s:
            add(s)
    # 3) coverage: strongest move of a type not covered yet
    while len(chosen) < 4:
        pool = [m for m in attacks if norm_move(m["name"]) not in names]
        new_type = [m for m in pool if m["type"] not in have_types]
        if not new_type:
            break
        add(max(new_type, key=score)["name"])
    # 4) still short (few attacks of this kind): support moves, then any remaining attack
    while len(chosen) < 4:
        s = first_legal(SUPPORT)
        if s:
            add(s)
            continue
        pool = [m for m in attacks if norm_move(m["name"]) not in names]
        if not pool:
            break
        add(max(pool, key=score)["name"])
    return chosen[:4]


def main():
    rb = json.load(open(os.path.join(ROOT, "tools", "builds.json"), encoding="utf-8"))
    items = za_items()
    evolves = set()
    dex = sp_parse.dex_lists()
    pages = {name: path for _, _, name, path in dex}
    data = {name: sp_parse.species_page(path) for name, path in pages.items()}
    # a Pokémon that evolves further benefits from Eviolite
    for d in data.values():
        for a, b, how in d["evolutions"]:
            evolves.add(a.split("|")[1])  # national number of the one evolving
    out = {}
    stats_summary = {"rb": 0, "swapped": 0, "generated": 0, "item_swapped": 0}
    for name, d in data.items():
        moves = d["moves"]
        legal = moves["levelUp"] + moves["tm"]
        # the Alpha move counts as learnable too (look up its details in the lists if possible)
        legal_names = {norm_move(m["name"]) for m in legal}
        stats, types = base_stats(name)
        b = rb.get(name)
        nat_id = None
        spec = pokeapi("pokemon-species/" + re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "").replace(".", "")).strip("-"))
        if spec:
            nat_id = f"{spec['id']:03d}"
        note = []
        if b and b.get("nature") in NATURES:
            nature = b["nature"]
            kept = []
            for m in b["moves"]:  # legal in Z-A and not listed twice
                if norm_move(m) in legal_names and norm_move(m) not in {norm_move(k) for k in kept}:
                    kept.append(m)
            gone = [m for m in b["moves"] if norm_move(m) not in legal_names]
            plus = NATURES[nature][0]
            cat = "Physical" if plus == "Attack" else "Special" if plus == "Sp. Atk" else (
                "Physical" if stats and stats["attack"] > stats["special-attack"] else "Special")
            final = pick_moves(kept, legal, types, cat)
            added = [m for m in final if norm_move(m) not in {norm_move(k) for k in kept}]
            item = b.get("item", "")
            if item and item not in items:
                new_item = ITEM_SWAP.get(item, "Leftovers")
                note.append(f"item {item} isn't in Z-A → {new_item or 'none'}")
                item = new_item
                stats_summary["item_swapped"] += 1
            if gone:
                note.insert(0, f"not learnable in Z-A: {', '.join(gone)} → {', '.join(added) or 'nothing'}")
                stats_summary["swapped"] += 1
            src = "RankedBoost" + (" (fixed for Z-A: " + "; ".join(note) + ")" if note else "")
            stats_summary["rb"] += 1
        else:
            # No RankedBoost build: make one from base stats + Serebii's Z-A move list
            physical = stats["attack"] > stats["special-attack"]  # a tie goes special
            fast = stats["speed"] >= 90
            nature = ("Jolly" if fast else "Adamant") if physical else ("Timid" if fast else "Modest")
            final = pick_moves([], legal, types, "Physical" if physical else "Special")
            item = "Eviolite" if nat_id in evolves and "Eviolite" in items else "Life Orb"
            src = "Made from base stats + Serebii's Z-A move list (no RankedBoost build)"
            stats_summary["generated"] += 1
        plus, minus = NATURES[nature]
        out[name] = {"nature": nature, "plus": plus or "—", "minus": minus or "—",
                     "moves": final, "item": item, "note": src,
                     "url": (b or {}).get("source", "")}
    json.dump(out, open(os.path.join(ROOT, "tools", "builds_final.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(stats_summary, file=sys.stderr)
    short = [n for n, v in out.items() if len(v["moves"]) < 4]
    print("fewer than 4 moves:", short, file=sys.stderr)


if __name__ == "__main__":
    main()
