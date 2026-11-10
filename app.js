/* ============================================================
   Z-A Dex Tracker — app logic
   Data comes from data/pokedex.js (window.ZA_DEX), built from the
   Google Sheet by tools/build_data.py. Ticks are saved in this
   browser (localStorage) and can be backed up to a file.
   ============================================================ */
(function () {
  "use strict";

  const DEX = window.ZA_DEX;
  const STORE_KEY = "zaDex.v1";
  const UI_KEY = "zaDex.ui.v1";

  // ---------- versions ----------
  const VERSIONS = [
    { id: "normal", label: "Normal", short: "Normal", color: "var(--accent)" },
    { id: "shiny", label: "Shiny", short: "Shiny", color: "var(--shiny)" },
    { id: "alpha", label: "Alpha", short: "Alpha", color: "var(--alpha)" },
    { id: "shinyalpha", label: "Shiny Alpha", short: "Shiny α", color: "#ff9f43" },
  ];
  // Megas are a battle form and legendaries can't be Alphas: only Normal + Shiny for those.
  function versionsFor(sp, form) {
    if (form.mega || sp.legendary) return VERSIONS.slice(0, 2);
    return VERSIONS;
  }

  // Extra marks, same idea as the "Markings" tab in the sheet.
  const MARKS = [
    { id: "perfect", label: "💙 Perfect nature" },
    { id: "evolve", label: "🟦 Pending to evolve" },
    { id: "gift", label: "🔷 Mission / gift" },
    { id: "traded", label: "♦️ Traded" },
    { id: "love", label: "❤️ Sentimental" },
  ];

  // ---------- natures: the game's fixed table, used to double-check the sheet ----------
  const NATURES = {
    Hardy: [], Docile: [], Serious: [], Bashful: [], Quirky: [],
    Lonely: ["Attack", "Defense"], Brave: ["Attack", "Speed"], Adamant: ["Attack", "Sp. Atk"], Naughty: ["Attack", "Sp. Def"],
    Bold: ["Defense", "Attack"], Relaxed: ["Defense", "Speed"], Impish: ["Defense", "Sp. Atk"], Lax: ["Defense", "Sp. Def"],
    Timid: ["Speed", "Attack"], Hasty: ["Speed", "Defense"], Jolly: ["Speed", "Sp. Atk"], Naive: ["Speed", "Sp. Def"],
    Modest: ["Sp. Atk", "Attack"], Mild: ["Sp. Atk", "Defense"], Quiet: ["Sp. Atk", "Speed"], Rash: ["Sp. Atk", "Sp. Def"],
    Calm: ["Sp. Def", "Attack"], Gentle: ["Sp. Def", "Defense"], Sassy: ["Sp. Def", "Speed"], Careful: ["Sp. Def", "Sp. Atk"],
  };
  function natureStats(form) {
    const n = NATURES[form.nature];
    if (n) return { plus: n[0] || null, minus: n[1] || null };
    return { plus: form.plus || null, minus: form.minus || null };
  }

  // ---------- saved state ----------
  // state[key] = { c: 1 (caught), l: 1 (level 100), m: ["perfect", …] }
  // key = "<speciesKey>|<form>|<version>", e.g. "L3|Female|shiny"
  let state = load(STORE_KEY);
  if (!state) {
    state = {};
    // First visit: carry over what is already ticked in the sheet.
    for (const [k, v] of Object.entries(DEX.seed || {})) {
      state[k] = { c: v.caught ? 1 : 0, l: v.lv100 ? 1 : 0 };
    }
    save();
  }
  const ui = Object.assign({ dex: "lumiose", show: "all", vers: ["normal", "shiny", "alpha", "shinyalpha"], type: "" }, load(UI_KEY) || {});

  function load(k) {
    try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; }
  }
  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) { toast("Couldn't save — is storage blocked?"); }
  }
  function saveUi() {
    try { localStorage.setItem(UI_KEY, JSON.stringify(ui)); } catch (e) { /* not important */ }
  }
  const key = (sp, form, ver) => `${sp.key}|${form.form}|${ver}`;
  const get = (sp, form, ver) => state[key(sp, form, ver)] || {};
  function setFlag(sp, form, ver, flag, on) {
    const k = key(sp, form, ver);
    const cur = Object.assign({}, state[k]);
    cur[flag] = on ? 1 : 0;
    // Level 100 implies caught
    if (flag === "l" && on) cur.c = 1;
    if (flag === "c" && !on) cur.l = 0;
    if (!cur.c && !cur.l && !(cur.m && cur.m.length)) delete state[k]; else state[k] = cur;
    save();
  }
  function toggleMark(sp, form, ver, mark) {
    const k = key(sp, form, ver);
    const cur = Object.assign({ m: [] }, state[k]);
    cur.m = cur.m.includes(mark) ? cur.m.filter((x) => x !== mark) : cur.m.concat(mark);
    if (!cur.c && !cur.l && !cur.m.length) delete state[k]; else state[k] = cur;
    save();
  }

  // ---------- helpers ----------
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const numLabel = (sp) => (sp.dex === "hyperspace" ? "H" : "#") + String(sp.num).padStart(3, "0");
  const typeBadges = (types) => types.map((t) => `<span class="type t-${esc(t)}">${esc(t)}</span>`).join("");
  const byKey = new Map(DEX.species.map((s) => [s.key, s]));

  // Every (species, form, version) slot — used for counting
  function slots(sp, vers) {
    const out = [];
    for (const f of sp.forms) {
      for (const v of versionsFor(sp, f)) {
        if (!vers || vers.includes(v.id)) out.push({ sp, f, v });
      }
    }
    return out;
  }

  // ---------- search ----------
  // "3", "#003", "003" → that number; "h12" → Hyperspace #12; text → name or form contains
  function parseQuery(q) {
    q = q.trim().toLowerCase();
    if (!q) return null;
    let m = q.match(/^h\s*#?\s*0*(\d+)$/);
    if (m) return { num: +m[1], dex: "hyperspace" };
    m = q.match(/^[#n]?\s*0*(\d+)$/);
    if (m) return { num: +m[1], dex: null };
    return { text: q };
  }
  function matchesQuery(sp, pq) {
    if (!pq) return true;
    if (pq.num != null) {
      if (sp.num !== pq.num) return false;
      if (pq.dex) return sp.dex === pq.dex;
      return true;
    }
    const t = pq.text.normalize("NFD").replace(/[̀-ͯ]/g, "");
    const name = sp.name.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    return name.includes(t) || sp.forms.some((f) => f.form.toLowerCase().includes(t));
  }

  // ---------- list ----------
  function visibleSpecies() {
    const pq = parseQuery($("#q").value);
    // A dex-number search with no "H" looks in the current tab (both tabs when "All")
    return DEX.species.filter((sp) => {
      if (ui.dex !== "all" && sp.dex !== ui.dex && !(pq && pq.dex)) return false;
      if (pq && pq.dex && sp.dex !== pq.dex) return false;
      if (!matchesQuery(sp, pq)) return false;
      if (ui.type && !sp.forms.some((f) => f.types.includes(ui.type))) return false;
      if (ui.show !== "all") {
        const s = slots(sp, ui.vers);
        if (!s.length) return false;
        if (ui.show === "missing" && s.every((x) => get(x.sp, x.f, x.v.id).c)) return false;
        if (ui.show === "done" && !s.some((x) => get(x.sp, x.f, x.v.id).c)) return false;
        if (ui.show === "lv" && s.every((x) => get(x.sp, x.f, x.v.id).l)) return false;
      }
      return true;
    });
  }

  function cardHtml(sp) {
    const f0 = sp.forms[0];
    const all = slots(sp);
    const got = all.filter((x) => get(x.sp, x.f, x.v.id).c).length;
    // one dot per version type: lit if any form of that version is caught
    const dots = VERSIONS.map((v) => {
      const has = all.some((x) => x.v.id === v.id && get(x.sp, x.f, v.id).c);
      const exists = all.some((x) => x.v.id === v.id);
      return exists ? `<i class="${has ? "on" : ""}" style="--c:${v.color}" title="${v.label}"></i>` : "";
    }).join("");
    const types = [...new Set(sp.forms.filter((f) => !f.mega).flatMap((f) => f.types))].slice(0, 2);
    return `<button class="card${got === all.length ? " complete" : ""}" data-key="${sp.key}">
      <span class="num">${numLabel(sp)}</span>
      <img class="pic" loading="lazy" src="${esc(f0.img)}" alt="">
      <span class="name">${esc(sp.name)}</span>
      <span class="types">${typeBadges(types)}</span>
      <span class="count"><span class="dots">${dots}</span>${got}/${all.length} caught${sp.forms.length > 1 ? ` · ${sp.forms.length} forms` : ""}</span>
    </button>`;
  }

  function renderGrid() {
    const list = visibleSpecies();
    const grid = $("#grid");
    grid.innerHTML = list.length ? list.map(cardHtml).join("") : `<p class="empty">No Pokémon match. Try another number or name.</p>`;
    const q = $("#q").value.trim();
    $("#resultNote").textContent = q
      ? `${list.length} result${list.length === 1 ? "" : "s"} — press Enter to open ${list.length ? list[0].name : "…"}`
      : `${list.length} Pokémon`;
    renderProgress();
  }

  function renderProgress() {
    const pool = DEX.species.filter((s) => ui.dex === "all" || s.dex === ui.dex);
    const all = pool.flatMap((sp) => slots(sp));
    const box = (label, list, flag, color) => {
      const done = list.filter((x) => get(x.sp, x.f, x.v.id)[flag]).length;
      const pct = list.length ? Math.round((done / list.length) * 100) : 0;
      return `<div class="pbox"><small>${label}</small><b>${done}</b><small style="display:inline"> / ${list.length}</small>
        <div class="pbar"><i style="width:${pct}%;--c:${color}"></i></div></div>`;
    };
    // "Dex" = species with at least one version caught
    const speciesDone = pool.filter((sp) => slots(sp).some((x) => get(x.sp, x.f, x.v.id).c)).length;
    const pct = pool.length ? Math.round((speciesDone / pool.length) * 100) : 0;
    $("#progress").innerHTML =
      `<div class="pbox"><small>Pokédex</small><b>${speciesDone}</b><small style="display:inline"> / ${pool.length}</small><div class="pbar"><i style="width:${pct}%"></i></div></div>` +
      box("Normal", all.filter((x) => x.v.id === "normal"), "c", "var(--accent)") +
      box("Shiny", all.filter((x) => x.v.id === "shiny"), "c", "var(--shiny)") +
      box("Alpha", all.filter((x) => x.v.id === "alpha"), "c", "var(--alpha)") +
      box("Shiny Alpha", all.filter((x) => x.v.id === "shinyalpha"), "c", "#ff9f43") +
      box("Level 100", all, "l", "var(--good)");
  }

  // ---------- detail drawer ----------
  let cur = null; // { sp, fi (form index), ver }

  function open(spKey, formIdx = 0, ver = "normal") {
    const sp = byKey.get(spKey);
    if (!sp) return;
    cur = { sp, fi: Math.min(formIdx, sp.forms.length - 1), ver };
    const vs = versionsFor(sp, sp.forms[cur.fi]);
    if (!vs.some((v) => v.id === cur.ver)) cur.ver = "normal";
    renderDrawer();
    const d = $("#drawer");
    if (!d.classList.contains("open")) {
      d.classList.add("open");
      d.setAttribute("aria-hidden", "false");
      $("#scrim").hidden = false;
      $("#dBody").scrollTop = 0;
      // focus after the current key event finishes, so a held Enter can't close it again
      setTimeout(() => $("#closeBtn").focus({ preventScroll: true }), 0);
    }
    history.replaceState(null, "", "#" + sp.key);
  }
  function close() {
    const d = $("#drawer");
    d.classList.remove("open");
    d.setAttribute("aria-hidden", "true");
    $("#scrim").hidden = true;
    history.replaceState(null, "", location.pathname + location.search);
    const card = cur && document.querySelector(`.card[data-key="${cur.sp.key}"]`);
    cur = null;
    if (card) card.focus({ preventScroll: true });
    renderGrid();
  }
  function step(dir) {
    if (!cur) return;
    const list = visibleSpecies();
    let i = list.findIndex((s) => s.key === cur.sp.key);
    const pool = i === -1 ? DEX.species : list;
    if (i === -1) i = pool.findIndex((s) => s.key === cur.sp.key);
    const next = pool[(i + dir + pool.length) % pool.length];
    open(next.key);
    $("#dBody").scrollTop = 0;
  }

  function renderDrawer() {
    const { sp } = cur;
    const form = sp.forms[cur.fi];
    const vs = versionsFor(sp, form);
    const ver = VERSIONS.find((v) => v.id === cur.ver);
    const st = get(sp, form, ver.id);
    const shiny = ver.id === "shiny" || ver.id === "shinyalpha";
    const alpha = ver.id === "alpha" || ver.id === "shinyalpha";
    const ns = natureStats(form);

    $("#dNum").textContent = numLabel(sp) + (sp.dex === "hyperspace" ? " · Hyperspace" : " · Lumiose");
    $("#dTitle").textContent = sp.name;

    // form tabs (only when there's more than one)
    const tabs = sp.forms.length > 1
      ? `<div class="formtabs">${sp.forms.map((f, i) => {
          const s = versionsFor(sp, f);
          const n = s.filter((v) => get(sp, f, v.id).c).length;
          return `<button data-form="${i}" aria-pressed="${i === cur.fi}">${esc(f.form)} <span class="mini">${n}/${s.length}</span></button>`;
        }).join("")}</div>`
      : "";

    const hero = `<div class="hero">
      <div class="hero-pic${shiny ? " is-shiny" : ""}${alpha ? " is-alpha" : ""}">
        <img src="${esc(shiny ? form.shinyImg : form.img)}" alt="${esc(`${ver.label} ${sp.name} ${form.form}`)}">
        ${alpha ? `<span class="alpha-badge" title="Alpha">α</span>` : ""}
      </div>
      <div class="vers${vs.length === 2 ? " two" : ""}">${vs.map((v) =>
        `<button data-ver="${v.id}" aria-pressed="${v.id === ver.id}" class="${get(sp, form, v.id).c ? "got" : ""}">${v.short}</button>`).join("")}</div>
      <div class="ticks">
        <button class="tick" data-flag="c" aria-pressed="${!!st.c}"><span class="box"></span>Caught</button>
        <button class="tick" data-flag="l" aria-pressed="${!!st.l}"><span class="box"></span>Level 100</button>
      </div>
      <div class="marks">${MARKS.map((m) =>
        `<button data-mark="${m.id}" aria-pressed="${!!(st.m && st.m.includes(m.id))}">${m.label}</button>`).join("")}</div>
      <div class="types">${typeBadges(form.types)}</div>
    </div>`;

    const nature = `<div class="panel"><h3>Best nature</h3>
      ${form.nature ? `<div class="nature"><span class="nm">${esc(form.nature)}</span>
        ${ns.plus ? `<span class="stat up">▲ ${esc(ns.plus)}</span><span class="stat down">▼ ${esc(ns.minus)}</span>` : `<span class="stat neutral">No stat change</span>`}
      </div>` : `<p class="none">Not in the sheet yet.</p>`}
    </div>`;

    const moves = `<div class="panel"><h3>Competitive moveset</h3>
      ${form.moves.length ? `<div class="moves">${form.moves.map((m) => `<div>${esc(m)}</div>`).join("")}</div>` : `<p class="none">No moveset in the sheet yet for this form.</p>`}
      ${form.item ? `<p class="item">Held item: <b>${esc(form.item)}</b></p>` : ""}
      ${sp.alphaMove && !form.mega && !sp.legendary ? `<p class="item${alpha ? " alpha-hl" : ""}">Alphas always know: <b>${esc(sp.alphaMove)}</b></p>` : ""}
      ${sp.build ? `<p class="auto-note" style="margin-top:8px">Build: ${sp.build.url
        ? `<a href="${esc(sp.build.url)}" target="_blank" rel="noopener">${esc(sp.build.note)} ↗</a>`
        : esc(sp.build.note)}. Every move checked against Serebii's Z-A move list.</p>` : ""}
    </div>`;

    // Where to find / how to evolve — from Serebii; the sheet's own note is shown under it
    const lines = [];
    if (form.mega) {
      if (form.stone) lines.push({ label: form.stone.stone, text: form.stone.where });
    } else {
      for (const w of sp.where) lines.push(w);
      // a Pokémon can evolve from more than one (Slowking: Slowpoke, or Galarian Slowbro)
      for (const e of sp.evolvesFrom || []) {
        const into = e.into ? ` → ${e.into} ${sp.name}` : "";
        lines.push({ label: "Evolves from " + e.from + into, text: e.how });
      }
    }
    const sheetNote = form.sheetInfo || (!form.mega && (sp.forms.find((f) => f.sheetInfo && !f.mega) || {}).sheetInfo) || "";
    const where = `<div class="panel"><h3>${form.mega ? "How to get the Mega Stone" : "Where to find · How to evolve"}</h3>
      ${lines.length ? `<ul class="info-lines">${lines.map((l) => `<li><span class="lbl">${esc(l.label)}</span>${esc(l.text)}</li>`).join("")}</ul>`
        : `<p class="none">Serebii doesn't list this one.</p>`}
      ${sheetNote ? `<details class="sheet-note"><summary>Your sheet's note</summary><p>${esc(sheetNote).replace(/\n/g, "<br>")}</p></details>` : ""}
      ${form.auto ? `<p class="auto-note" style="margin-top:6px">This form isn't in your sheet yet — it was added automatically. Build copied from the main form.</p>` : ""}
      <p class="auto-note" style="margin-top:8px">Source: <a href="${esc(sp.serebii)}" target="_blank" rel="noopener">${esc(sp.name)} on Serebii.net ↗</a></p>
    </div>`;

    // every move it can learn in Z-A (Serebii), folded away by default
    const moveRows = (list) => list.map((m) => `<tr><td class="at">${esc(m.at)}</td><td><b>${esc(m.name)}</b>${m.plusLv ? ` <span class="plus" title="Becomes a Plus Move at level ${esc(m.plusLv)}">+${esc(m.plusLv)}</span>` : ""}</td>
      <td>${m.type ? `<span class="type t-${esc(m.type)}">${esc(m.type)}</span>` : ""}</td><td class="cat">${esc(m.cat)}</td><td class="pow">${esc(m.power)}</td></tr>`).join("");
    const learn = (sp.learn.levelUp.length || sp.learn.tm.length) ? `<div class="panel"><details class="learn">
      <summary><h3>All moves it can learn in Z-A</h3></summary>
      ${sp.learn.levelUp.length ? `<h4>Level up</h4><table class="mtable"><thead><tr><th>Lv</th><th>Move</th><th>Type</th><th>Cat.</th><th>Pow</th></tr></thead><tbody>${moveRows(sp.learn.levelUp)}</tbody></table>` : ""}
      ${sp.learn.tm.length ? `<h4>TMs</h4><table class="mtable"><thead><tr><th>TM</th><th>Move</th><th>Type</th><th>Cat.</th><th>Pow</th></tr></thead><tbody>${moveRows(sp.learn.tm)}</tbody></table>` : ""}
      <p class="auto-note">+N = the level it becomes a Plus Move.</p>
    </details></div>` : "";

    const evo = sp.chain.length > 1 ? `<div class="panel"><h3>Evolution line</h3>${evoHtml(sp)}</div>` : "";

    // every version of every form, quick to tick
    const table = `<div class="panel"><h3>All versions</h3>
      <table class="vtable"><thead><tr><th>Form · version</th><th style="text-align:center">Caught</th><th style="text-align:center">Lv 100</th></tr></thead><tbody>
      ${sp.forms.map((f, fi) => versionsFor(sp, f).map((v) => {
        const s = get(sp, f, v.id);
        return `<tr><td><span class="fname">${esc(f.form)}</span> <span class="vname">· ${v.label}</span></td>
          <td class="c"><input type="checkbox" data-t="${fi}|${v.id}|c" ${s.c ? "checked" : ""} aria-label="${esc(`${f.form} ${v.label} caught`)}"></td>
          <td class="c"><input type="checkbox" data-t="${fi}|${v.id}|l" ${s.l ? "checked" : ""} aria-label="${esc(`${f.form} ${v.label} level 100`)}"></td></tr>`;
      }).join("")).join("")}
      </tbody></table></div>`;

    $("#dBody").innerHTML = tabs + hero + nature + moves + where + evo + learn + table;
  }

  function evoHtml(sp) {
    // group the chain by depth: stage 1 → stage 2 → stage 3 (branches stack)
    const stages = [];
    for (const c of sp.chain) (stages[c.depth] = stages[c.depth] || []).push(c);
    // the method (from Serebii) sits under the arrow; with branches each one shows its own
    return `<div class="evo">${stages.map((st, i) =>
      (i ? `<span class="arrow">→${st.length === 1 && st[0].how ? `<small>${esc(st[0].how)}</small>` : ""}</span>` : "") +
      `<div class="branch">${st.map((c) => {
        const target = c.key && byKey.get(c.key);
        const img = target ? target.forms[0].img : "";
        return `<button data-evo="${c.key || ""}" class="${c.key === sp.key ? "cur" : ""}" ${target ? "" : "disabled title=\"Not in this game's Pokédex\""}>
          ${img ? `<img src="${esc(img)}" alt="" loading="lazy">` : ""}${esc(c.name)}${target ? `<small style="color:var(--muted)">${numLabel(target)}</small>` : ""}
          ${st.length > 1 && c.how ? `<small class="how">${esc(c.how)}</small>` : ""}</button>`;
      }).join("")}</div>`).join("")}</div>`;
  }

  // ---------- events ----------
  function bind() {
    // build the type filter list
    const types = [...new Set(DEX.species.flatMap((s) => s.forms.flatMap((f) => f.types)))].sort();
    $("#typeSel").insertAdjacentHTML("beforeend", types.map((t) => `<option ${t === ui.type ? "selected" : ""}>${esc(t)}</option>`).join(""));
    $("#nL").textContent = DEX.species.filter((s) => s.dex === "lumiose").length;
    $("#nH").textContent = DEX.species.filter((s) => s.dex === "hyperspace").length;

    const syncSegs = () => {
      document.querySelectorAll("#dexTabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.dex === ui.dex));
      document.querySelectorAll("#showSeg button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.show === ui.show));
      document.querySelectorAll("#verChips button").forEach((b) => b.setAttribute("aria-pressed", ui.vers.includes(b.dataset.ver)));
    };
    syncSegs();

    $("#dexTabs").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      ui.dex = b.dataset.dex; saveUi(); syncSegs(); renderGrid();
    });
    $("#showSeg").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      ui.show = b.dataset.show; saveUi(); syncSegs(); renderGrid();
    });
    $("#verChips").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      const v = b.dataset.ver;
      ui.vers = ui.vers.includes(v) ? ui.vers.filter((x) => x !== v) : ui.vers.concat(v);
      if (!ui.vers.length) ui.vers = [v]; // keep at least one
      saveUi(); syncSegs(); renderGrid();
    });
    $("#typeSel").addEventListener("change", (e) => { ui.type = e.target.value; saveUi(); renderGrid(); });

    const q = $("#q");
    q.addEventListener("input", renderGrid);
    q.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        // stop this Enter from also pressing the drawer's close button once focus moves there
        e.preventDefault();
        const first = visibleSpecies()[0];
        if (first) open(first.key);
      }
    });

    $("#grid").addEventListener("click", (e) => {
      const c = e.target.closest(".card"); if (c) open(c.dataset.key);
    });

    // drawer interactions
    $("#dBody").addEventListener("click", (e) => {
      if (!cur) return;
      const b = e.target.closest("button");
      if (!b) return;
      const form = cur.sp.forms[cur.fi];
      if (b.dataset.form != null) { open(cur.sp.key, +b.dataset.form, cur.ver); return; }
      if (b.dataset.ver) { cur.ver = b.dataset.ver; renderDrawer(); return; }
      if (b.dataset.flag) {
        setFlag(cur.sp, form, cur.ver, b.dataset.flag, b.getAttribute("aria-pressed") !== "true");
        renderDrawer(); return;
      }
      if (b.dataset.mark) { toggleMark(cur.sp, form, cur.ver, b.dataset.mark); renderDrawer(); return; }
      if (b.dataset.evo) { open(b.dataset.evo); $("#dBody").scrollTop = 0; }
    });
    $("#dBody").addEventListener("change", (e) => {
      const t = e.target.dataset.t; if (!t || !cur) return;
      const [fi, ver, flag] = t.split("|");
      const top = $("#dBody").scrollTop;
      setFlag(cur.sp, cur.sp.forms[+fi], ver, flag, e.target.checked);
      renderDrawer();
      $("#dBody").scrollTop = top;
    });
    $("#closeBtn").addEventListener("click", close);
    $("#scrim").addEventListener("click", close);
    $("#prevBtn").addEventListener("click", () => step(-1));
    $("#nextBtn").addEventListener("click", () => step(1));

    document.addEventListener("keydown", (e) => {
      const typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName) && document.activeElement.type !== "checkbox";
      if (e.key === "Escape") {
        if (!$("#confirm").hidden) { $("#confirm").hidden = true; return; }
        if (cur) { close(); return; }
        if (document.activeElement === q) { q.value = ""; renderGrid(); }
      }
      if (typing) return;
      if (e.key === "/") { e.preventDefault(); q.focus(); q.select(); }
      if (cur && e.key === "ArrowLeft") step(-1);
      if (cur && e.key === "ArrowRight") step(1);
    });

    // menu: backup / restore / reset
    const menu = $("#menu"), menuBtn = $("#menuBtn");
    menuBtn.addEventListener("click", () => {
      menu.hidden = !menu.hidden; menuBtn.setAttribute("aria-expanded", !menu.hidden);
    });
    document.addEventListener("click", (e) => {
      if (!menu.hidden && !e.target.closest(".menu-wrap")) { menu.hidden = true; menuBtn.setAttribute("aria-expanded", "false"); }
    });
    menu.addEventListener("click", (e) => {
      const act = e.target.dataset.act; if (!act) return;
      menu.hidden = true;
      if (act === "export") exportBackup();
      if (act === "import") $("#importFile").click();
      if (act === "reset") { $("#confirm").hidden = false; $("#cNo").focus(); }
    });
    $("#importFile").addEventListener("change", importBackup);
    $("#cNo").addEventListener("click", () => { $("#confirm").hidden = true; });
    $("#cYes").addEventListener("click", () => {
      state = {}; save(); $("#confirm").hidden = true; renderGrid(); if (cur) renderDrawer(); toast("All ticks cleared");
    });
  }

  function exportBackup() {
    const blob = new Blob([JSON.stringify({ app: "za-dex", saved: new Date().toISOString(), state }, null, 1)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `za-dex-backup-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast("Backup saved");
  }
  function importBackup(e) {
    const file = e.target.files[0]; if (!file) return;
    file.text().then((txt) => {
      const data = JSON.parse(txt);
      if (!data || data.app !== "za-dex" || typeof data.state !== "object") throw new Error("bad file");
      state = data.state; save(); renderGrid(); if (cur) renderDrawer();
      toast(`Backup loaded (${Object.keys(state).length} entries)`);
    }).catch(() => toast("That file isn't a Z-A Dex backup"));
    e.target.value = "";
  }

  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 2200);
  }

  // ---------- start ----------
  bind();
  renderGrid();
  // open straight to a Pokémon from a link like index.html#L3
  const h = location.hash.slice(1);
  if (h && byKey.has(h)) open(h);
})();
