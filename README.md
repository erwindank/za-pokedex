# Z-A Dex Tracker

A Pokédex tracker for **Pokémon Legends: Z-A** (Lumiose Pokédex + the Hyperspace Pokédex from Mega Dimension).

- Find a Pokémon by its **Z-A dex number** (`3`, `#003`, `H12` for Hyperspace) or by name, then press Enter.
- See the **best nature** with the stat it raises (▲) and lowers (▼), the **competitive moveset** and held item, **where to find it / how it evolves**, and its **evolution line**.
- Every **form** (male/female differences, patterns, flower colours, sizes, regional forms, Megas) with **Normal, Shiny, Alpha and Shiny Alpha** versions, each with its own picture.
- Tick **Caught** and **Level 100** for every version, plus optional marks (perfect nature, pending to evolve, gift, traded, sentimental).
- Ticks are saved in your browser. Use **⋯ → Save backup file** to keep a copy or move it to another device.

## Use it

Open `index.html` in a browser — no install needed. Or host it free with GitHub Pages
(Settings → Pages → Deploy from branch → `main` / root).

## Where the data comes from

- **[Serebii.net](https://www.serebii.net/legendsz-a/):** official Lumiose and Hyperspace dex numbers,
  where to find each Pokémon (Legends: Z-A and Mega Dimension), evolution methods, the guaranteed
  Alpha move, every move it can learn in Z-A, and where to get each Mega Stone.
- **The Google Sheet** *Pokemon Legends Z-A Pokedex Tracker* ("Full List" tab): best nature,
  competitive moveset and held item, which the site reads from the sheet. These were filled from
  [RankedBoost](https://rankedboost.com)'s Legends: Z-A builds and checked against Serebii: a move
  the Pokémon can't learn in Z-A, or an item that isn't in Z-A, was swapped for a legal one.
  Column R ("Build source") says which rows were fixed. Pokémon without a RankedBoost build got one
  made from their base stats and Z-A moves. The sheet's original values are in the
  "Full List backup 2026-11-10" tab.
- **[PokeAPI](https://pokeapi.co):** pictures (normal, shiny, female, every form), Mega forms the
  sheet doesn't list yet, and gender differences.

Forms that aren't in the sheet yet (most Megas, some regional forms, Rotom, Tatsugiri, Squawkabilly…)
are added automatically and marked in the app. Their nature is copied from the main form.

## Updating the data

1. Export the sheet's "Full List" values to `tools/sheet.json` as `{"values": [[...], ...]}`.
2. `python tools/serebii_fetch.py` downloads the Serebii pages once (one request every 1.2 s) into
   `tools/.cache/serebii`. Add `--fresh` after a game update to download them again.
3. (Optional) `python tools/builds_fetch.py` then `python tools/builds_make.py` refresh the
   recommended builds into `tools/builds_final.json`, ready to paste into the sheet.
4. `python tools/build_data.py` builds `data/pokedex.js` (PokeAPI answers are cached in `tools/.cache`).
5. Bump `?v=` on `data/pokedex.js` in `index.html` so browsers load the new file.

Fixes the build makes on the fly: dex numbers come from Serebii (the sheet has a few drag-fill
mistakes like `H#9` for 90), the shifted Pumpkaboo / Gourgeist size rows, "Deputante" → "Debutante"
Trim, and the sheet's Machamp "Mega" row is dropped (Machamp has no Mega Evolution).

Pokémon and all related names are trademarks of Nintendo / Creatures / GAME FREAK. Fan project, not affiliated.
