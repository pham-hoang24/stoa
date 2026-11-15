"use strict";
// PROTOTYPE (throwaway). Read-only against /api; composer is a stub.
const VARIANTS = { A: "Plan + right rail", B: "Left chat + filmstrip", C: "Full-bleed plan + floating chat" };
const q = new URLSearchParams(location.search);
const S = { chats: [], chat: null, di: 0, page: 1, zoom: 1, ev: null, variant: VARIANTS[q.get("variant")] ? q.get("variant") : "A", min: false, local: [], focus: false };
const h = (tag, cls, text, kids) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  (kids || []).forEach((k) => k && n.append(k));
  return n;
};
const api = async (p) => {
  const r = await fetch(p), d = await r.json();
  if (!r.ok) throw Error(d.error || r.status);
  return d;
};
const previewUrl = (d, page) => d.asset_url.replace("/assets/", "/previews/") + "/" + page;
const chatName = (c) => (c.drawings?.length ? c.drawings[0].filename + (c.drawings.length > 1 ? ` + ${c.drawings.length - 1} more` : "") : c.title || "Untitled");
const labels = { supported: "Native · source supported", proposal: "Proposal · unreviewed", estimate: "Estimate · unreviewed", clarification: "Clarification needed", abstain: "Abstained · insufficient evidence" };
const drawing = () => S.chat?.drawings[S.di];
const pageMeta = () => drawing()?.pages.find((p) => p.page === S.page) || {};

async function openChat(id, keepEv) {
  S.chat = await api("/api/chats/" + id);
  S.di = 0; S.page = 1; S.zoom = 1; S.ev = null; S.local = [];
  const last = [...S.chat.messages].reverse().find((m) => m.role !== "user" && m.answer?.evidence?.length);
  if (last && !keepEv) await selectCite(last, 0, false);
  else render();
}
async function selectCite(msg, i, focus = true) {
  const data = await api(`/api/chats/${S.chat.id}/evidence/${msg.id}/${i}`);
  S.ev = { mid: msg.id, i, data, msg };
  const di = S.chat.drawings.findIndex((d) => d.id === data.drawing_id);
  if (di >= 0) S.di = di;
  S.page = data.page || 1;
  S.zoom = 1;
  S.focus = focus && !!data.bbox;
  render();
}

function sheet() {
  const d = drawing(), wrap = h("div", "sheet"), img = document.createElement("img");
  wrap.style.width = S.zoom * 100 + "%";
  img.alt = `Source preview of ${d.filename}, page ${S.page}`;
  img.src = previewUrl(d, S.page);
  img.onerror = () => wrap.replaceChildren(h("p", "empty", "Preview unavailable for this source."));
  wrap.append(img);
  const e = S.ev?.data;
  if (e && e.drawing_id === d.id && (e.page || 1) === S.page) {
    const m = pageMeta(), o = e.transform?.slice(4, 6) || m.origin || [0, 0], w = e.source_width || m.width, hh = e.source_height || m.height;
    if (w && hh) {
      const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
      svg.setAttribute("viewBox", `${o[0]} ${o[1]} ${w} ${hh}`);
      svg.setAttribute("preserveAspectRatio", "none");
      const add = (tag, attrs) => { const n = document.createElementNS(ns, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); svg.append(n); };
      if (e.bbox) { const [x0, y0, x1, y1] = e.bbox; add("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0 }); }
      if (e.polygon) add("polygon", { points: e.polygon.map((p) => p.join(",")).join(" ") });
      if (e.dimension_line) add("polyline", { points: e.dimension_line.map((p) => p.join(",")).join(" ") });
      wrap.append(svg);
    }
  }
  return wrap;
}
function zoomBar() {
  const mk = (t, fn, label, dis) => { const b = h("button", "", t); if (label) b.setAttribute("aria-label", label); b.disabled = !!dis; b.onclick = fn; return b; };
  const z = (v) => { S.zoom = Math.max(1, Math.min(16, v)); S.focus = false; render(); };
  const bar = h("div", "zoom", null, [
    mk("Fit", () => z(1)), mk("−", () => z(S.zoom / 2), "Zoom out", S.zoom === 1), mk("+", () => z(S.zoom * 2), "Zoom in", S.zoom === 16),
    mk("Focus evidence", () => { S.zoom = 1; S.focus = true; S.zoom = zoomForBox(); render(); }, null, !S.ev?.data.bbox),
    h("span", "muted", S.zoom === 1 ? "Fit" : S.zoom.toFixed(1) + "×"),
  ]);
  return bar;
}
function zoomForBox() {
  const e = S.ev?.data, m = pageMeta();
  if (!e?.bbox) return 1;
  const [x0, y0, x1, y1] = e.bbox, w = e.source_width || m.width, hh = e.source_height || m.height;
  return Math.max(1, Math.min(16, Math.min(w / Math.max(1, x1 - x0), hh / Math.max(1, y1 - y0)) * 0.6));
}
function viewer(opts = {}) {
  const v = h("section", "viewer"), d = drawing();
  v.setAttribute("aria-label", "Source preview");
  const bar = h("div", "vbar");
  if (!d) { v.append(h("div", "empty", "This conversation has no drawings yet. Open one that does from the switcher."), ); return v; }
  if (!opts.noTabs)
    S.chat.drawings.forEach((dr, i) => {
      const b = h("button", "tab", dr.filename);
      b.title = dr.filename; b.setAttribute("aria-pressed", i === S.di); 
      b.onclick = () => { S.di = i; S.page = 1; S.zoom = 1; render(); };
      bar.append(b);
    });
  else bar.append(h("strong", "", d.filename));
  if (d.pages.length > 1) {
    const sel = h("select"); sel.setAttribute("aria-label", "Page");
    d.pages.forEach((p) => { const o = h("option", "", "Page " + p.page); o.value = p.page; sel.append(o); });
    sel.value = S.page; sel.onchange = () => { S.page = +sel.value; S.zoom = 1; render(); };
    bar.append(sel);
  }
  bar.append(h("span", "grow"), zoomBar());
  const vp = h("div", "vp"); vp.tabIndex = 0; vp.setAttribute("role", "region"); vp.setAttribute("aria-label", "Drawing. Scroll or use arrow keys to pan.");
  vp.append(sheet());
  v.append(bar, vp);
  if (opts.strip) v.append(strip());
  return v;
}
function strip() {
  const s = h("div", "strip");
  S.chat.drawings.forEach((dr, i) => {
    const img = document.createElement("img"); img.alt = ""; img.src = previewUrl(dr, 1);
    const b = h("button", "thumb", null, [img, h("span", "", dr.filename)]);
    b.title = dr.filename; b.setAttribute("aria-pressed", i === S.di);
    b.onclick = () => { S.di = i; S.page = 1; S.zoom = 1; render(); };
    s.append(b);
  });
  return s;
}

function answerCard(m) {
  const a = m.answer || {}, card = h("article", "msg");
  const who = h("div", "who", "Stoa", [h("span", "badge " + (a.error ? "error" : a.status), a.error ? "Analysis error · abstained" : labels[a.status] || a.status)]);
  card.append(who);
  if (a.value !== null && a.value !== undefined) card.append(h("div", "value", String(a.value), [a.unit ? h("small", "", a.unit) : null]));
  card.append(h("div", "", a.explanation || "No explanation available."));
  const cites = h("div", "cites");
  (a.evidence || []).forEach((e, i) => {
    const dr = S.chat.drawings.find((x) => x.id === e.drawing_id);
    const b = h("button", "cite", `${String(i + 1).padStart(2, "0")} · ${dr?.filename || "Source"}${e.page ? " · p." + e.page : ""}`);
    b.setAttribute("aria-pressed", S.ev?.mid === m.id && S.ev.i === i);
    b.onclick = () => selectCite(m, i).catch((x) => alert(x.message));
    cites.append(b);
  });
  card.append(cites);
  return card;
}
function thread() {
  const t = h("div", "thread"); t.setAttribute("aria-live", "polite");
  for (const m of S.chat.messages) {
    if (m.role === "user") t.append(h("article", "msg user", null, [h("div", "who", "You"), h("div", "", m.content || m.question || "")]));
    else t.append(answerCard(m));
  }
  for (const m of S.local) t.append(h("article", "msg" + (m.role === "user" ? " user" : ""), null, [h("div", "who", m.role === "user" ? "You" : "Stoa"), h("div", "", m.text)]));
  if (!S.chat.messages.length && !S.local.length) t.append(h("p", "muted", "No questions yet. Ask something about the plan."));
  queueMicrotask(() => (t.scrollTop = t.scrollHeight));
  return t;
}
function composer() {
  const c = h("form", "composer"), ta = h("textarea"), send = h("button", "primary", "Ask question");
  ta.rows = 2; ta.placeholder = "Ask about this drawing…"; ta.setAttribute("aria-label", "Question");
  send.type = "submit";
  c.append(ta, h("div", "row", null, [h("span", "muted", "Prototype: nothing is sent"), send]));
  const go = () => { const v = ta.value.trim(); if (!v) return; S.local.push({ role: "user", text: v }, { role: "stoa", text: "Prototype only. In the real app this goes to the backend and the evidence box appears on the plan." }); render(); };
  c.onsubmit = (e) => { e.preventDefault(); go(); };
  ta.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); } };
  return c;
}
function chatPane(cls = "", extra) {
  const head = h("div", "chat-head", null, [h("h1", "", chatName(S.chat))]);
  if (extra) head.append(extra);
  return h("aside", "chat " + cls, null, [head, thread(), composer()]);
}
function callout() {
  const m = S.ev?.msg; if (!m) return null;
  const a = m.answer;
  return h("div", "callout", null, [h("div", "who", "Selected answer", [h("span", "badge " + a.status, labels[a.status] || a.status)]),
    a.value !== null && a.value !== undefined ? h("div", "value", String(a.value), [a.unit ? h("small", "", a.unit) : null]) : null,
    h("div", "muted", (a.explanation || "").slice(0, 140))]);
}

function render() {
  const root = document.getElementById("root"), old = root.querySelector(".vp");
  const keep = old && { x: old.scrollLeft, y: old.scrollTop };
  root.replaceChildren();
  if (!S.chat) { root.append(h("div", "empty", "No conversations found. Create one in the main app first.")); return switcher(); }
  const wrap = h("div", S.variant);
  if (S.variant === "A") wrap.append(viewer(), chatPane());
  else if (S.variant === "B") wrap.append(chatPane(), viewer({ strip: true, noTabs: true }));
  else {
    const min = h("button", "", S.min ? "Open chat" : "Minimise"); min.onclick = () => { S.min = !S.min; render(); };
    const fl = chatPane("float" + (S.min ? " min" : ""), min);
    wrap.append(viewer(), fl, S.min ? callout() : null);
  }
  root.append(wrap);
  const vp = root.querySelector(".vp");
  if (vp) requestAnimationFrame(() => {
    if (S.focus && S.ev?.data.bbox) {
      const e = S.ev.data, m = pageMeta(), o = e.transform?.slice(4, 6) || m.origin || [0, 0], w = e.source_width || m.width, hh = e.source_height || m.height, sh = vp.querySelector(".sheet");
      S.zoom = zoomForBox(); sh.style.width = S.zoom * 100 + "%";
      const [x0, y0, x1, y1] = e.bbox;
      vp.scrollLeft = (((x0 + x1) / 2 - o[0]) / w) * sh.clientWidth - vp.clientWidth / 2;
      vp.scrollTop = (((y0 + y1) / 2 - o[1]) / hh) * sh.clientHeight - vp.clientHeight / 2;
      S.focus = false;
    } else if (keep) { vp.scrollLeft = keep.x; vp.scrollTop = keep.y; }
  });
  switcher();
}
function setVariant(v) {
  S.variant = v; q.set("variant", v); history.replaceState(null, "", "?" + q); render();
}
function switcher() {
  const keys = Object.keys(VARIANTS), sw = document.getElementById("switcher");
  const step = (d) => setVariant(keys[(keys.indexOf(S.variant) + d + keys.length) % keys.length]);
  const l = h("button", "", "←"), r = h("button", "", "→");
  l.setAttribute("aria-label", "Previous variant"); r.setAttribute("aria-label", "Next variant");
  l.onclick = () => step(-1); r.onclick = () => step(1);
  const sel = h("select"); sel.setAttribute("aria-label", "Conversation");
  S.chats.forEach((c) => { const o = h("option", "", chatName(c)); o.value = c.id; sel.append(o); });
  if (S.chat) sel.value = S.chat.id;
  sel.onchange = () => { q.set("chat", sel.value); history.replaceState(null, "", "?" + q); openChat(sel.value); };
  sw.replaceChildren(l, h("span", "", `${S.variant} · ${VARIANTS[S.variant]}`), r, sel);
}
document.addEventListener("keydown", (e) => {
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) return;
  const keys = Object.keys(VARIANTS), i = keys.indexOf(S.variant);
  if (e.key === "ArrowRight") setVariant(keys[(i + 1) % 3]);
  if (e.key === "ArrowLeft") setVariant(keys[(i + 2) % 3]);
  if (e.key === "c" && S.variant === "C") { S.min = !S.min; render(); }
});
(async () => {
  try {
    S.chats = await api("/api/chats");
    const score = (c) => c.drawings?.length * 2 + (c.messages || []).filter((m) => m.answer?.evidence?.length).length * 5;
    const pick = S.chats.find((c) => c.id === q.get("chat")) || [...S.chats].sort((a, b) => score(b) - score(a))[0];
    if (pick) await openChat(pick.id); else render();
  } catch (e) { document.getElementById("root").textContent = "Could not load: " + e.message; }
})();
