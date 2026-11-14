/* ============================================================
   Z-A Dex Tracker — Google Drive sync
   Keeps a copy of your ticks in your own Google Drive, in the
   hidden "app data" folder (only this site can see it, it doesn't
   clutter your Drive). Uses Google Identity Services for sign-in
   and the Drive REST API — no server needed.

   How it works:
   - Every change is saved in the browser first (like before),
     then sent to Drive a couple of seconds later.
   - When the page opens or comes back into view, it checks Drive
     for changes made on another device and takes them in.
   - If both this device and Drive changed since the last sync,
     the two are combined (anything ticked on either stays ticked).
   ============================================================ */
(function () {
  "use strict";

  // ⚠️ Paste your OAuth Client ID from Google Cloud Console here.
  // (APIs & Services → Credentials → Create credentials → OAuth client ID → Web application,
  //  Authorized JavaScript origin: https://erwindank.github.io)
  const CLIENT_ID = "59223877916-0t4piguecrau83evh69tcak1epu3rbla.apps.googleusercontent.com";

  const SCOPE = "https://www.googleapis.com/auth/drive.appdata";
  const FILE_NAME = "za-dex.json";
  const META_KEY = "zaDex.drive.v1";       // { on, fileId, syncedAt, dirty, email }
  const TOKEN_KEY = "zaDex.driveToken";     // sessionStorage: { token, exp }
  const PUSH_DELAY = 2000;                  // wait this long after the last tick before uploading

  let hooks = null;          // { getState, setState, toast } from app.js
  let tokenClient = null;
  let token = null;          // current access token (lasts ~1 hour)
  let tokenExp = 0;
  let pendingToken = null;   // { resolve, reject } while the Google popup is open
  let pushTimer = null;
  let busy = false;          // a pull/push is running
  let again = false;         // another push was asked for while busy
  let status = "off";        // off | tap | syncing | ok | error

  const meta = Object.assign({ on: false, fileId: null, syncedAt: null, dirty: false }, readJson(localStorage, META_KEY) || {});

  function readJson(store, k) {
    try { return JSON.parse(store.getItem(k)); } catch (e) { return null; }
  }
  function saveMeta() {
    try { localStorage.setItem(META_KEY, JSON.stringify(meta)); } catch (e) { /* not important */ }
  }

  // ---------- status pill in the top bar ----------
  function setStatus(s, title) {
    status = s;
    const pill = document.getElementById("syncPill");
    if (!pill) return;
    pill.hidden = s === "off";
    pill.dataset.state = s;
    const text = { tap: "Tap to sync", syncing: "Syncing…", ok: "Synced", error: "Sync failed" }[s] || "";
    pill.querySelector(".sync-text").textContent = text;
    pill.title = title || (s === "ok" ? "Saved to Google Drive" : s === "tap" ? "Sign in again to keep syncing with Google Drive" : text);
    renderMenu();
  }
  // menu entries change with the connection state
  function renderMenu() {
    const c = document.querySelector('[data-act="drive-connect"]');
    const n = document.querySelector('[data-act="drive-sync"]');
    const d = document.querySelector('[data-act="drive-off"]');
    if (!c) return;
    c.hidden = meta.on;
    n.hidden = d.hidden = !meta.on;
  }

  // ---------- sign-in (access token) ----------
  function loadGis() {
    if (window.google && google.accounts && google.accounts.oauth2) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://accounts.google.com/gsi/client";
      s.async = true;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("Couldn't load Google sign-in"));
      document.head.appendChild(s);
    });
  }
  function initClient() {
    if (tokenClient) return;
    tokenClient = google.accounts.oauth2.initTokenClient({
      client_id: CLIENT_ID,
      scope: SCOPE,
      callback: (resp) => {
        const p = pendingToken; pendingToken = null;
        if (!p) return;
        if (resp.error) return p.reject(new Error(resp.error));
        token = resp.access_token;
        tokenExp = Date.now() + (resp.expires_in - 60) * 1000;
        try { sessionStorage.setItem(TOKEN_KEY, JSON.stringify({ token, exp: tokenExp })); } catch (e) { /* fine */ }
        p.resolve(token);
      },
      error_callback: (err) => {
        const p = pendingToken; pendingToken = null;
        if (p) p.reject(new Error(err && err.type || "popup_failed"));
      },
    });
  }
  // A token from this tab session, if it's still good
  function cachedToken() {
    if (token && Date.now() < tokenExp) return token;
    const t = readJson(sessionStorage, TOKEN_KEY);
    if (t && t.token && Date.now() < t.exp) { token = t.token; tokenExp = t.exp; return token; }
    return null;
  }
  // Must be called from a click (browsers block the Google popup otherwise)
  async function signIn(firstTime) {
    await loadGis();
    initClient();
    return new Promise((resolve, reject) => {
      pendingToken = { resolve, reject };
      // first time: show the account chooser + consent; later: quick re-approve
      tokenClient.requestAccessToken({ prompt: firstTime ? "consent" : "", hint: meta.email || undefined });
    });
  }

  // ---------- Drive REST calls ----------
  async function api(url, opts = {}) {
    const res = await fetch(url, Object.assign({}, opts, {
      headers: Object.assign({ Authorization: "Bearer " + token }, opts.headers || {}),
    }));
    if (res.status === 401) { token = null; tokenExp = 0; throw Object.assign(new Error("signed out"), { auth: true }); }
    if (!res.ok) throw new Error("Drive error " + res.status);
    return res;
  }
  // Find our file in the app data folder (id + when it last changed)
  async function findFile() {
    if (meta.fileId) {
      try {
        const r = await api(`https://www.googleapis.com/drive/v3/files/${meta.fileId}?fields=id,modifiedTime,trashed`);
        const f = await r.json();
        if (!f.trashed) return f;
      } catch (e) { if (e.auth) throw e; /* file gone: look it up by name */ }
    }
    const q = encodeURIComponent(`name='${FILE_NAME}' and trashed=false`);
    const r = await api(`https://www.googleapis.com/drive/v3/files?spaces=appDataFolder&q=${q}&fields=files(id,modifiedTime)&orderBy=modifiedTime desc`);
    const list = (await r.json()).files || [];
    return list[0] || null;
  }
  async function download(id) {
    const r = await api(`https://www.googleapis.com/drive/v3/files/${id}?alt=media`);
    const data = await r.json();
    return data && data.app === "za-dex" && typeof data.state === "object" ? data.state : {};
  }
  async function upload(state) {
    const body = JSON.stringify({ app: "za-dex", saved: new Date().toISOString(), state });
    let r;
    if (meta.fileId) {
      // replace the file's contents
      r = await api(`https://www.googleapis.com/upload/drive/v3/files/${meta.fileId}?uploadType=media&fields=id,modifiedTime`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body,
      });
    } else {
      // first upload: create the file inside the hidden app data folder
      const boundary = "zadex" + Math.random().toString(36).slice(2);
      const multipart =
        `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n` +
        JSON.stringify({ name: FILE_NAME, parents: ["appDataFolder"] }) +
        `\r\n--${boundary}\r\nContent-Type: application/json\r\n\r\n${body}\r\n--${boundary}--`;
      r = await api("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,modifiedTime", {
        method: "POST", headers: { "Content-Type": `multipart/related; boundary=${boundary}` }, body: multipart,
      });
    }
    const f = await r.json();
    meta.fileId = f.id; meta.syncedAt = f.modifiedTime; meta.dirty = false; saveMeta();
  }

  // Combine two saves: ticked on either side stays ticked, marks are joined
  function merge(a, b) {
    const out = {};
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
      const x = a[k] || {}, y = b[k] || {};
      const m = [...new Set([...(x.m || []), ...(y.m || [])])];
      const e = { c: x.c || y.c ? 1 : 0, l: x.l || y.l ? 1 : 0 };
      if (m.length) e.m = m;
      if (e.c || e.l || m.length) out[k] = e;
    }
    return out;
  }

  // ---------- the sync itself ----------
  // Pull changes from Drive, then push ours if we have any.
  async function sync() {
    if (!meta.on) return;
    if (!cachedToken()) { setStatus("tap"); return; }
    if (busy) { again = true; return; }
    busy = true; setStatus("syncing");
    try {
      const f = await findFile();
      if (f) {
        meta.fileId = f.id;
        if (f.modifiedTime !== meta.syncedAt) {
          // Drive changed on another device
          const remote = await download(f.id);
          if (meta.dirty) {
            hooks.setState(merge(remote, hooks.getState()));  // both changed: combine
          } else {
            hooks.setState(remote);                              // only Drive changed: take it
          }
          meta.syncedAt = f.modifiedTime;
          saveMeta();
        }
      } else {
        meta.fileId = null;
        meta.dirty = true;  // nothing on Drive yet: upload what we have
      }
      if (meta.dirty) await upload(hooks.getState());
      setStatus("ok", "Saved to Google Drive · " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
    } catch (e) {
      if (e.auth) setStatus("tap");
      else { setStatus("error", "Couldn't reach Google Drive — your ticks are still saved on this device. Tap to try again."); console.warn(e); }
    } finally {
      busy = false;
      if (again) { again = false; schedule(); }
    }
  }
  function schedule() {
    clearTimeout(pushTimer);
    pushTimer = setTimeout(sync, PUSH_DELAY);
  }

  // Tap on the pill / "Sync now": get a fresh token if needed, then sync
  async function tapSync() {
    try {
      if (!cachedToken()) { setStatus("syncing"); await signIn(false); }
      await sync();
    } catch (e) {
      setStatus("tap");
      hooks.toast("Google sign-in was cancelled");
    }
  }

  async function connect() {
    if (!CLIENT_ID) { hooks.toast("Google Drive isn't set up yet (missing Client ID)"); return; }
    try {
      setStatus("syncing");
      await signIn(true);
      // remember which account, so the next sign-in skips the chooser
      try {
        const r = await api("https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)");
        meta.email = (await r.json()).user.emailAddress;
      } catch (e) { /* not important */ }
      meta.on = true;
      // first connect on this device: anything already ticked here gets combined with Drive
      meta.syncedAt = null;
      meta.dirty = Object.keys(hooks.getState()).length > 0;
      saveMeta();
      await sync();
      if (status === "ok") hooks.toast("Connected — your ticks now save to Google Drive");
    } catch (e) {
      setStatus(meta.on ? "tap" : "off");
      hooks.toast("Google sign-in was cancelled");
    }
  }

  function disconnect() {
    if (token && window.google && google.accounts) google.accounts.oauth2.revoke(token, () => {});
    token = null; tokenExp = 0;
    try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* fine */ }
    Object.assign(meta, { on: false, fileId: null, syncedAt: null, dirty: false, email: null });
    saveMeta();
    setStatus("off");
    hooks.toast("Disconnected — ticks stay on this device and in your Drive copy");
  }

  // ---------- public hooks used by app.js ----------
  window.ZASync = {
    // called once when the app starts
    init(h) {
      hooks = h;
      renderMenu();
      const pill = document.getElementById("syncPill");
      if (pill) pill.addEventListener("click", tapSync);
      // check for changes from other devices when coming back to the tab
      // (sync() does nothing while Drive isn't connected)
      document.addEventListener("visibilitychange", () => { if (!document.hidden) sync(); });
      if (!meta.on) return setStatus("off");
      sync();
    },
    // called after every change to the ticks
    changed() {
      if (!meta.on) return;
      meta.dirty = true; saveMeta();
      if (cachedToken()) schedule(); else setStatus("tap");
    },
    connect, disconnect, syncNow: tapSync,
  };
})();
