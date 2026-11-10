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

- **Natures, movesets, items, locations, evolution methods:** the Google Sheet
  *Pokemon Legends Z-A Pokedex Tracker* ("Full List" tab).
- **Pictures, types of new forms, Mega forms, gender differences, evolution lines:** [PokeAPI](https://pokeapi.co).

Forms that aren't in the sheet yet (most Megas, some regional forms, Rotom, Tatsugiri, Squawkabilly…)
are added automatically and marked in the app. Their nature is copied from the main form.

## Updating the data

1. Export the sheet's "Full List" values to `tools/sheet.json` as `{"values": [[...], ...]}`.
2. Run `python tools/build_data.py` (needs internet the first time; PokeAPI answers are cached in `tools/.cache`).
3. Bump `?v=` on `data/pokedex.js` in `index.html` so browsers load the new file.

Sheet fixes the build makes on the fly: dex numbers come from row order (the sheet has a few
drag-fill mistakes like `H#9` for 90), the shifted Pumpkaboo / Gourgeist size rows, and
"Deputante" → "Debutante" Trim.

Pokémon and all related names are trademarks of Nintendo / Creatures / GAME FREAK. Fan project, not affiliated.
