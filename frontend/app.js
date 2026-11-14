"use strict";
const $ = (id) => document.getElementById(id);
let current = null,
  selected = new Set(),
  busy = false,
  evidenceTrigger = null,
  uploadLimits = null,
  view = { di: 0, page: 1 },
  ev = null,
  evOpen = false,
  focusPending = false,
  asking = false,
  pendingQ = null;
const formatLimit = (bytes) =>
  bytes >= 1024 * 1024 ? `${bytes / (1024 * 1024)} MiB` : `${bytes} bytes`;
const element = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const jsonBlock = (value) => element("pre", "", JSON.stringify(value, null, 2));
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok)
    throw Error(data.error || `Request failed (${response.status})`);
  return data;
}
function notice(text = "") {
  $("notice").textContent = text;
}
function chatName(chat) {
  const drawings = chat.drawings || [];
  if (drawings.length)
    return (
      drawings[0].filename +
      (drawings.length > 1 ? ` + ${drawings.length - 1} more` : "")
    );
  return chat.title || "Untitled conversation";
}
const previewUrl = (drawing, page) =>
  drawing.asset_url.replace("/assets/", "/previews/") + "/" + page;
const viewedDrawing = () => current?.drawings[view.di];
const pageMeta = (drawing, page) =>
  drawing?.pages.find((p) => p.page === page) || {};
function controls() {
  const locked = busy || asking;
  document.body.classList.toggle("busy", busy);
  $("upload").disabled = locked || !uploadLimits;
  document
    .querySelectorAll(".dropzone")
    .forEach((n) => n.classList.toggle("disabled", $("upload").disabled));
  $("send").disabled = locked || !current || !selected.size;
  $("question").readOnly = asking;
  $("ask").setAttribute("aria-busy", asking ? "true" : "false");
  $("new-chat").disabled = locked;
  $("delete-chat").disabled = locked;
  // Viewing a different drawing stays possible while a question is in flight.
  document
    .querySelectorAll(".drawing input,.chat-button")
    .forEach((n) => (n.disabled = locked));
  document.querySelectorAll(".drawing-name").forEach((n) => (n.disabled = busy));
  $("scope").textContent = selected.size
    ? `Asking about ${selected.size} selected drawing${selected.size === 1 ? "" : "s"} · Scope carries into follow-ups`
    : current?.drawings.length
      ? "Select a drawing to ask about"
      : "Add a drawing to start asking";
}
async function loadChats() {
  const chats = await api("/api/chats");
  $("chats").replaceChildren();
  for (const chat of chats) {
    const b = element(
      "button",
      "chat-button" + (current?.id === chat.id ? " active" : ""),
    );
    b.setAttribute("aria-current", current?.id === chat.id ? "page" : "false");
    const questions = (chat.messages || []).filter(
        (m) => m.role === "user",
      ).length,
      sources = (chat.drawings || []).length;
    b.title = chatName(chat);
    b.append(
      element("span", "chat-name", chatName(chat)),
      element(
        "span",
        "chat-date",
        `${sources} drawing${sources === 1 ? "" : "s"} · ${questions} question${questions === 1 ? "" : "s"}`,
      ),
    );
    b.onclick = () => {
      $("chat-menu").open = false;
      run(async () => openChat(chat.id));
    };
    $("chats").append(b);
  }
  if (!chats.length)
    $("chats").append(
      element("p", "hint", "Your conversations will appear here."),
    );
  $("chat-menu-label").textContent = current
    ? chatName(current)
    : "Conversations";
  $("delete-chat").hidden = !current;
}
function renderDrawings() {
  $("drawing-list").replaceChildren();
  const drawings = current?.drawings || [];
  drawings.forEach((drawing, i) => {
    const row = element("div", "drawing"),
      input = element("input"),
      name = element("button", "drawing-name", drawing.filename);
    row.classList.toggle("viewing", i === view.di);
    input.type = "checkbox";
    input.checked = selected.has(drawing.id);
    input.dataset.id = drawing.id;
    input.setAttribute("aria-label", `Ask about ${drawing.filename}`);
    input.onchange = () => {
      input.checked ? selected.add(drawing.id) : selected.delete(drawing.id);
      controls();
    };
    name.type = "button";
    name.title = drawing.filename;
    name.setAttribute("aria-pressed", i === view.di ? "true" : "false");
    name.onclick = () => {
      view = { di: i, page: 1 };
      renderDrawings();
      renderPlan();
      controls();
    };
    row.append(input, name, element("span", "filetype", drawing.format));
    $("drawing-list").append(row);
  });
  $("sources").hidden = !drawings.length;
  const limits = uploadLimits
    ? `IFC up to ${formatLimit(uploadLimits.ifc)}; other formats up to ${formatLimit(uploadLimits.default)}.`
    : "";
  $("upload-hint").hidden = !drawings.length;
  $("upload-hint").textContent =
    `Tick the drawings to ask about; click a name to view it. Views can overlap; confirm they are independent before totaling. ${limits}`;
  const dropLimits = document.getElementById("drop-limits");
  if (dropLimits)
    dropLimits.textContent = `PNG, JPEG, PDF, IFC, DXF or SVG. ${limits}`;
}
const labels = {
  supported: "Native · source supported",
  proposal: "Proposal · unreviewed",
  estimate: "Estimate · unreviewed",
  clarification: "Clarification needed",
  abstain: "Abstained · insufficient evidence",
};
function details(label, value) {
  const d = element("details");
  d.append(element("summary", "", label), jsonBlock(value));
  return d;
}
function sampleSheet() {
  const ns = "http://www.w3.org/2000/svg",
    wrap = document.createDocumentFragment(),
    svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "sample-sheet");
  svg.setAttribute("viewBox", "0 0 440 250");
  svg.setAttribute("role", "img");
  svg.setAttribute(
    "aria-label",
    "Sample floor plan with one door outlined by an orange evidence box",
  );
  const add = (tag, attrs) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    svg.append(n);
    return n;
  };
  const wall = { fill: "none", stroke: "#294d3c", "stroke-width": 3 };
  add("rect", { x: 30, y: 30, width: 260, height: 190, ...wall });
  add("line", { x1: 170, y1: 30, x2: 170, y2: 130, ...wall });
  add("line", { x1: 30, y1: 130, x2: 170, y2: 130, ...wall });
  add("line", { x1: 290, y1: 80, x2: 410, y2: 80, stroke: "#8a9a83" });
  add("line", { x1: 290, y1: 120, x2: 380, y2: 120, stroke: "#8a9a83" });
  add("line", { x1: 290, y1: 160, x2: 400, y2: 160, stroke: "#8a9a83" });
  add("path", {
    d: "M170 130 A24 24 0 0 1 194 106",
    fill: "none",
    stroke: "#294d3c",
    "stroke-width": 1.5,
  });
  add("rect", {
    x: 160,
    y: 100,
    width: 42,
    height: 36,
    fill: "#e5aa342c",
    stroke: "#c78416",
    "stroke-width": 2,
  });
  add("text", {
    x: 210,
    y: 98,
    "font-size": 12,
    fill: "#6f4a18",
    "font-family": "sans-serif",
  }).textContent = "Evidence box";
  wrap.append(svg);
  wrap.append(
    element(
      "p",
      "sample-caption",
      "Illustration. Every answer is tied to a box like this on your sheet.",
    ),
  );
  return wrap;
}
function renderWelcome(stage) {
  const welcome = element("div", "welcome");
  welcome.append(
    element("h2", "", "Add a drawing to start."),
    element(
      "p",
      "",
      "Ask how many doors, rooms or square metres a sheet shows. Each answer points to a box on the drawing or an IFC element, and Stoa says so when the drawing does not support an answer.",
    ),
  );
  const zone = element("label", "dropzone");
  zone.htmlFor = "upload";
  zone.append(
    element("strong", "", "Add a drawing"),
    element("span", "", "Choose files or drop them here."),
  );
  const limits = element("span", "");
  limits.id = "drop-limits";
  zone.append(limits);
  zone.ondragover = (e) => {
    e.preventDefault();
    zone.classList.add("dragover");
  };
  zone.ondragleave = () => zone.classList.remove("dragover");
  // The drop itself is handled for the whole workspace by dropFiles below.
  zone.ondrop = () => zone.classList.remove("dragover");
  welcome.append(zone, sampleSheet());
  stage.append(welcome);
}
const hasGeom = (e) => !!(e && (e.bbox || e.polygon || e.dimension_line));
function bounds(e) {
  if (e.bbox) return e.bbox;
  const pts = e.polygon || e.dimension_line;
  if (!pts?.length) return null;
  const xs = pts.map((p) => p[0]),
    ys = pts.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}
function overlay(preview, drawing, page) {
  // Every region of the selected answer on this page; the selected one is
  // emphasised and drawn first in the DOM, the rest are dimmed.
  const items = (ev?.message?.answer?.evidence || (ev ? [ev.data] : []))
    .map((data, index) => ({ data, index }))
    .filter(
      ({ data }) =>
        hasGeom(data) &&
        data.drawing_id === drawing.id &&
        (data.page || 1) === page,
    )
    .sort((a, b) => (b.index === ev.index) - (a.index === ev.index));
  if (!items.length) return;
  const e = items[0].data,
    meta = pageMeta(drawing, page),
    origin = e.transform?.slice(4, 6) || meta.origin || [0, 0],
    w = e.source_width || meta.width,
    h = e.source_height || meta.height;
  if (!w || !h) return;
  const ns = "http://www.w3.org/2000/svg",
    svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `${origin[0]} ${origin[1]} ${w} ${h}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-label", "Highlighted evidence in source coordinates");
  for (const { data, index } of items) {
    const cls = index === ev.index ? "sel" : "dim",
      add = (tag, attrs) => {
        const n = document.createElementNS(ns, tag);
        n.setAttribute("class", cls);
        for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
        svg.append(n);
      };
    if (data.bbox) {
      const [x0, y0, x1, y1] = data.bbox;
      add("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0 });
    }
    for (const [key, tag] of [
      ["polygon", "polygon"],
      ["dimension_line", "polyline"],
    ])
      if (data[key])
        add(tag, { points: data[key].map((p) => p.join(",")).join(" ") });
  }
  preview.append(svg);
}
function renderPlan() {
  const stage = $("plan-stage"),
    previous = stage.querySelector(".preview-viewport"),
    keep = previous && {
      x: previous.scrollLeft,
      y: previous.scrollTop,
    };
  stage.replaceChildren();
  const drawing = viewedDrawing();
  stage.classList.toggle("empty", !drawing);
  if (!drawing) return renderWelcome(stage);
  const page = view.page,
    meta = pageMeta(drawing, page),
    preview = element("div", "preview"),
    img = element("img");
  img.alt = `Source preview for ${drawing.filename}, page ${page}`;
  img.src = previewUrl(drawing, page);
  img.onerror = () => {
    preview.replaceChildren(
      element(
        "p",
        "no-preview",
        "No spatial preview for this source. Open an answer's evidence to inspect its identifiers and properties.",
      ),
    );
    preview.classList.add("failed");
  };
  preview.append(img);
  overlay(preview, drawing, page);
  const viewport = element("div", "preview-viewport");
  viewport.tabIndex = 0;
  viewport.setAttribute("role", "region");
  viewport.setAttribute(
    "aria-label",
    `${drawing.filename}. Use arrow keys or scroll to pan when zoomed.`,
  );
  viewport.append(preview);
  const toolbar = element("div", "preview-tools"),
    zoomLabel = element("span", "hint", "Fit"),
    fit = element("button", "", "Fit"),
    minus = element("button", "", "−"),
    plus = element("button", "", "+"),
    focus = element("button", "", "Focus evidence");
  minus.setAttribute("aria-label", "Zoom out");
  plus.setAttribute("aria-label", "Zoom in");
  focus.dataset.action = "focus-evidence";
  const name = element("span", "plan-name", drawing.filename);
  name.title = drawing.filename;
  toolbar.append(name, element("span", "grow"));
  if (drawing.pages.length > 1) {
    const select = element("select", "page-select");
    select.setAttribute("aria-label", "Page");
    drawing.pages.forEach((p) => {
      const o = element("option", "", "Page " + p.page);
      o.value = p.page;
      select.append(o);
    });
    select.value = page;
    select.onchange = () => {
      view.page = Number(select.value);
      renderPlan();
    };
    toolbar.append(select);
  }
  let zoom = 1;
  const setZoom = (value) => {
    zoom = Math.max(1, Math.min(16, value));
    preview.style.width = zoom * 100 + "%";
    viewport.classList.toggle("pannable", zoom > 1);
    zoomLabel.textContent = zoom === 1 ? "Fit" : zoom.toFixed(1) + "×";
    minus.disabled = zoom === 1;
    plus.disabled = zoom === 16;
  };
  const e = ev?.data,
    hasBox =
      hasGeom(e) && e.drawing_id === drawing.id && (e.page || 1) === page;
  fit.onclick = () => {
    setZoom(1);
    viewport.scrollTo(0, 0);
  };
  minus.onclick = () => setZoom(zoom / 2);
  plus.onclick = () => setZoom(zoom * 2);
  focus.disabled = !hasBox;
  const focusEvidence = (grab) => {
    const [x0, y0, x1, y1] = bounds(e),
      width = e.source_width || meta.width,
      height = e.source_height || meta.height,
      origin = e.transform?.slice(4, 6) || meta.origin || [0, 0];
    setZoom(
      Math.min(width / Math.max(1, x1 - x0), height / Math.max(1, y1 - y0)) *
        0.7,
    );
    requestAnimationFrame(() => {
      viewport.scrollLeft =
        (((x0 + x1) / 2 - origin[0]) / width) * preview.clientWidth -
        viewport.clientWidth / 2;
      viewport.scrollTop =
        (((y0 + y1) / 2 - origin[1]) / height) * preview.clientHeight -
        viewport.clientHeight / 2;
      if (grab) viewport.focus();
    });
  };
  focus.onclick = () => focusEvidence(true);
  // Ctrl/Cmd + wheel (and trackpad pinch) zooms around the pointer.
  viewport.addEventListener(
    "wheel",
    (event) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const before = preview.getBoundingClientRect(),
        fx = (event.clientX - before.left) / before.width,
        fy = (event.clientY - before.top) / before.height;
      setZoom(zoom * Math.exp(-event.deltaY * 0.01));
      const after = preview.getBoundingClientRect();
      viewport.scrollLeft += after.left + fx * after.width - event.clientX;
      viewport.scrollTop += after.top + fy * after.height - event.clientY;
    },
    { passive: false },
  );
  // Mouse drag pans when zoomed; touch keeps native scrolling.
  let drag = null;
  viewport.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "mouse" || event.button !== 0 || zoom === 1)
      return;
    drag = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      left: viewport.scrollLeft,
      top: viewport.scrollTop,
      moved: false,
    };
  });
  viewport.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    const dx = event.clientX - drag.x,
      dy = event.clientY - drag.y;
    if (!drag.moved) {
      if (Math.hypot(dx, dy) < 4) return;
      drag.moved = true;
      viewport.setPointerCapture(drag.id);
      viewport.classList.add("panning");
    }
    viewport.scrollLeft = drag.left - dx;
    viewport.scrollTop = drag.top - dy;
  });
  const endDrag = (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    if (drag.moved && viewport.hasPointerCapture(drag.id))
      viewport.releasePointerCapture(drag.id);
    viewport.classList.remove("panning");
    drag = null;
  };
  viewport.addEventListener("pointerup", endDrag);
  viewport.addEventListener("pointercancel", endDrag);
  viewport.addEventListener("dragstart", (event) => event.preventDefault());
  toolbar.append(fit, minus, plus, focus, zoomLabel);
  stage.append(toolbar, viewport);
  setZoom(1);
  if (hasBox && focusPending) {
    focusPending = false;
    focusEvidence(false);
  } else if (keep)
    requestAnimationFrame(() => {
      viewport.scrollLeft = keep.x;
      viewport.scrollTop = keep.y;
    });
}
function markCitations() {
  document.querySelectorAll(".citation").forEach((b) => {
    b.setAttribute(
      "aria-pressed",
      ev &&
        b.dataset.message === ev.message.id &&
        b.dataset.index === String(ev.index)
        ? "true"
        : "false",
    );
  });
}
const truncate = (text, max) =>
  text.length > max ? text.slice(0, max - 1).trimEnd() + "…" : text;
function pendingText() {
  return ` · ${Math.floor((Date.now() - pendingQ.started) / 1000)} s`;
}
function renderPending(list) {
  if (!pendingQ || pendingQ.chatId !== current?.id) return;
  const q = element("article", "message user");
  q.append(
    element("div", "message-label", "You"),
    element("div", "", pendingQ.question),
  );
  const row = element("article", "message pending"),
    label = element("div", "message-label", "Stoa");
  row.append(label);
  pendingQ.el = null;
  if (pendingQ.error) {
    row.classList.add("failed");
    row.setAttribute("role", "alert");
    label.append(element("span", "badge error", "Question not answered"));
    const dismiss = element("button", "quiet", "Dismiss");
    dismiss.onclick = () => {
      pendingQ = null;
      renderMessages();
    };
    row.append(element("div", "", pendingQ.error), dismiss);
  } else {
    const text = element("div", "processing", "Reading the drawing…");
    pendingQ.el = element("span", "elapsed", pendingText());
    pendingQ.el.setAttribute("aria-hidden", "true");
    text.append(pendingQ.el);
    row.append(
      text,
      element(
        "p",
        "hint",
        "Checking the selected drawings for evidence. This can take up to two minutes; you can keep viewing drawings meanwhile.",
      ),
    );
  }
  list.append(q, row);
  list.scrollTop = list.scrollHeight;
}
function renderMessages() {
  const list = $("messages");
  list.replaceChildren();
  $("chat-title").textContent = current ? chatName(current) : "Drawing desk";
  const waiting = !!pendingQ && pendingQ.chatId === current?.id;
  if (!current?.messages.length && !waiting) {
    const empty = element("div", "thread-empty");
    empty.append(
      element(
        "p",
        "hint",
        current?.drawings.length
          ? "No questions yet. Ask about the drawing on the left."
          : "Questions and answers will appear here once a drawing is added.",
      ),
    );
    if (current?.drawings.length) {
      const examples = element("div", "examples");
      for (const text of [
        "Count the rooms",
        "What is the floor area?",
        "Show drawing details",
      ]) {
        const b = element("button", "", text);
        b.onclick = () => {
          $("question").value = text;
          $("question").focus();
        };
        examples.append(b);
      }
      empty.append(examples);
    }
    list.append(empty);
    return;
  }
  for (const message of current?.messages || []) {
    const card = element("article", "message " + message.role);
    if (message.role === "user") {
      card.append(
        element("div", "message-label", "You"),
        element("div", "", message.content || message.question || ""),
      );
    } else {
      const a = message.answer || {},
        error = a.error || a.error_code;
      if (a.status === "abstain") card.classList.add("abstained");
      const label = element("div", "message-label", "Stoa");
      label.append(
        element(
          "span",
          "badge " + (error ? "error" : a.status),
          error ? "Analysis error · abstained" : labels[a.status] || a.status,
        ),
      );
      card.append(label);
      const hasValue =
        a.value !== null && a.value !== undefined && a.value !== "";
      if (hasValue) {
        const value = element(
          "div",
          "answer-value" + (typeof a.value === "string" ? " text" : ""),
          String(a.value),
        );
        if (a.unit) value.append(element("span", "answer-unit", a.unit));
        card.append(value);
      }
      const primary =
        !hasValue ||
        error ||
        a.status === "abstain" ||
        a.status === "clarification";
      card.append(
        element(
          "div",
          primary ? "answer-main" : "answer-explanation",
          a.explanation || "No explanation available.",
        ),
      );
      if (a.image_processing) {
        const required = a.image_processing.required_views;
        const completed = a.image_processing.completed_views;
        if (Array.isArray(required) && Array.isArray(completed))
          card.append(
            element(
              "p",
              "hint",
              `Image region coverage: ${completed.length} / ${required.length}`,
            ),
          );
      }
      if (error) card.append(element("p", "hint", String(error)));
      const citations = element("div", "citations");
      (a.evidence || []).forEach((e, i) => {
        const drawing = current.drawings.find((d) => d.id === e.drawing_id);
        // Quote only text the answer actually cites; incidental OCR words
        // inside an object box (e.g. a door) are noise, so name the object.
        const quote = String(
          e.printed_text || a.calculation?.facts?.[i]?.printed_text || "",
        )
          .replace(/\s+/g, " ")
          .trim();
        const label = quote ? "" : String(e.label || "").trim();
        const base = `${String(i + 1).padStart(2, "0")} · ${drawing?.filename || "Source"}${e.page ? " · p." + e.page : ""}${label ? " · " + truncate(label, 28) : ""}`;
        const b = element(
          "button",
          "citation",
          quote ? `${base} · “${truncate(quote, 28)}”` : base,
        );
        if (quote) b.title = `${base} · “${quote}”`;
        b.dataset.message = message.id;
        b.dataset.index = i;
        b.onclick = () =>
          run(async () => selectEvidence(message, i, { user: true }));
        citations.append(b);
      });
      card.append(citations);
      if (a.calculation)
        card.append(details("Calculation & supporting facts", a.calculation));
      if (a.contributions?.length)
        card.append(
          details(
            "Contributions by drawing",
            a.contributions.map((c) => ({
              ...c,
              filename: current.drawings.find((d) => d.id === c.drawing_id)
                ?.filename,
            })),
          ),
        );
      if (a.model_provenance)
        card.append(
          details(
            "Model provenance · unreviewed extraction",
            a.model_provenance,
          ),
        );
    }
    list.append(card);
  }
  renderPending(list);
  markCitations();
  list.scrollTop = list.scrollHeight;
}
function renderEvidence() {
  const panel = $("evidence");
  panel.replaceChildren();
  const open = evOpen && !!ev;
  $("evidence-panel").classList.toggle("open", open);
  $("close-evidence").hidden = !open;
  if (!open) return;
  const evidence = ev.data,
    message = ev.message,
    drawing = current.drawings.find((d) => d.id === evidence.drawing_id);
  panel.append(
    element("div", "evidence-heading", drawing?.filename || "Source evidence"),
    element(
      "div",
      "evidence-meta",
      `${drawing?.format?.toUpperCase() || ""}${evidence.page ? " · Page " + evidence.page : ""} · Original source coordinates`,
    ),
  );
  if (!evidence.preview_url)
    panel.append(
      element(
        "p",
        "hint",
        "Native entity evidence. A spatial preview is not available; inspect the source identifiers and properties below.",
      ),
    );
  const links = element("div", "source-links");
  for (const [text, url] of [
    ["Open original", evidence.original_url || drawing?.asset_url],
    ["Evidence JSON", evidence.url],
  ])
    if (url) {
      const a = element("a", "", text);
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      links.append(a);
    }
  panel.append(links);
  if (evidence.entity_id || evidence.global_id)
    panel.append(
      element(
        "p",
        "evidence-meta",
        "Entity: " + (evidence.global_id || evidence.entity_id),
      ),
    );
  if (evidence.native_type)
    panel.append(
      element("p", "evidence-meta", "Type: " + evidence.native_type),
    );
  if (evidence.property)
    panel.append(
      element("p", "evidence-meta", "Property: " + evidence.property),
    );
  if (evidence.source_value !== undefined)
    panel.append(
      element("p", "evidence-meta", "Source value: " + evidence.source_value),
    );
  if (evidence.source_units)
    panel.append(
      element("p", "evidence-meta", "Coordinates: " + evidence.source_units),
    );
  panel.append(details("Source properties & coordinate mapping", evidence));
  if (message.answer.calculation)
    panel.append(
      details("Calculation & supporting facts", message.answer.calculation),
    );
}
async function selectEvidence(
  message,
  index,
  { user = false, focus = false } = {},
) {
  if (user) evidenceTrigger = document.activeElement;
  // The chat payload already carries the full evidence item; fetch only if not.
  const local = message.answer?.evidence?.[index],
    data =
      local?.drawing_id !== undefined
        ? local
        : await api(`/api/chats/${current.id}/evidence/${message.id}/${index}`),
    di = current.drawings.findIndex((d) => d.id === data.drawing_id);
  ev = { message, index, data };
  if (di >= 0) view = { di, page: data.page || 1 };
  else view.page = data.page || 1;
  evOpen = user;
  focusPending = (user || focus) && hasGeom(data);
  renderDrawings();
  renderPlan();
  renderEvidence();
  markCitations();
  controls();
  if (user) $("close-evidence").focus();
}
function closeEvidence() {
  if (!evOpen) return;
  evOpen = false;
  renderEvidence();
  if (evidenceTrigger?.isConnected) evidenceTrigger.focus();
}
async function showLatestEvidence(focus = false) {
  const last = [...(current?.messages || [])]
    .reverse()
    .find((m) => m.role !== "user" && m.answer?.evidence?.length);
  if (!last) return;
  try {
    const first = last.answer.evidence.findIndex(hasGeom);
    await selectEvidence(last, Math.max(first, 0), { focus });
  } catch {
    /* the plan still shows without an overlay */
  }
}
function renderAll() {
  renderDrawings();
  renderMessages();
  renderPlan();
  renderEvidence();
  controls();
}
async function openChat(id) {
  current = await api("/api/chats/" + id);
  selected = new Set(current.selected_drawing_ids || []);
  if (!current.messages.length)
    for (const d of current.drawings) selected.add(d.id);
  view = { di: 0, page: 1 };
  ev = null;
  evOpen = false;
  focusPending = false;
  renderAll();
  await loadChats();
  await showLatestEvidence();
}
async function run(task) {
  if (busy) return;
  busy = true;
  notice();
  controls();
  try {
    await task();
  } catch (error) {
    notice(error.message);
  } finally {
    busy = false;
    controls();
  }
}
$("upload").onclick = (event) => {
  if (busy || !uploadLimits) {
    event.preventDefault();
    notice(
      !uploadLimits
        ? "Upload limits are still loading. Try again in a moment."
        : "Wait for the current action to finish.",
    );
  }
};
const createChat = () =>
  api("/api/chats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title:
        "Drawing review · " +
        new Date().toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }),
    }),
  });
$("new-chat").onclick = () =>
  run(async () => {
    const chat = await createChat();
    await openChat(chat.id);
    $("question").focus();
  });
$("upload").onchange = () =>
  run(async () => {
    const files = [...$("upload").files],
      failures = [];
    if (!files.length) return;
    if (!current) await openChat((await createChat()).id);
    const firstNew = current.drawings.length;
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      notice(`Uploading ${i + 1}/${files.length}: ${file.name}…`);
      try {
        const limit = /\.ifc$/i.test(file.name)
          ? uploadLimits.ifc
          : uploadLimits.default;
        if (file.size > limit) throw Error(`File exceeds ${formatLimit(limit)}`);
        const d = await api(
          `/api/chats/${current.id}/uploads?filename=${encodeURIComponent(file.name)}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/octet-stream" },
            body: file,
          },
        );
        selected.add(d.id);
      } catch (error) {
        failures.push(`${file.name}: ${error.message}`);
      }
    }
    current = await api("/api/chats/" + current.id);
    if (current.drawings.length > firstNew) view = { di: firstNew, page: 1 };
    $("chat-title").textContent = chatName(current);
    renderDrawings();
    if (!current.messages.length) renderMessages();
    renderPlan();
    await loadChats();
    $("upload").value = "";
    notice(
      failures.length
        ? failures.join(" · ")
        : `${files.length} drawing${files.length === 1 ? "" : "s"} added. Ready for your question.`,
    );
  });
$("ask").onsubmit = async (event) => {
  event.preventDefault();
  const question = $("question").value.trim();
  if (busy || asking || !current || !selected.size || !question) return;
  const chatId = current.id,
    drawing_ids = [...selected];
  asking = true;
  notice();
  pendingQ = { chatId, question, started: Date.now(), error: null, el: null };
  $("question").value = "";
  renderMessages();
  controls();
  const tick = setInterval(() => {
    if (pendingQ?.el?.isConnected) pendingQ.el.textContent = pendingText();
  }, 1000);
  let answered = false;
  try {
    await api(`/api/chats/${chatId}/questions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, drawing_ids }),
    });
    answered = true;
  } catch (error) {
    pendingQ.error =
      error instanceof TypeError || error instanceof SyntaxError
        ? "Could not reach the server, or it sent an unreadable reply. Your question is back in the box; check the connection and send it again."
        : `${error.message.replace(/[.\s]+$/, "")}. Your question is back in the box.`;
    $("question").value = question;
  }
  clearInterval(tick);
  if (answered) {
    pendingQ = null;
    try {
      current = await api("/api/chats/" + chatId);
    } catch (error) {
      notice(error.message);
    }
  }
  asking = false;
  renderMessages();
  controls();
  if (!answered) $("question").focus();
  else {
    await loadChats().catch(() => {});
    await showLatestEvidence(true);
  }
};
// Drop files anywhere on the workspace; uploads reuse the #upload change handler.
{
  const area = document.querySelector(".content");
  let depth = 0;
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  const clear = () => {
    depth = 0;
    area.classList.remove("dragging");
  };
  area.addEventListener("dragenter", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth++;
    area.classList.add("dragging");
  });
  area.addEventListener("dragover", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = busy || asking || !uploadLimits ? "none" : "copy";
  });
  area.addEventListener("dragleave", (e) => {
    if (hasFiles(e) && --depth <= 0) clear();
  });
  area.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    clear();
    if (busy || asking || !uploadLimits)
      return notice(
        !uploadLimits
          ? "Upload limits are still loading. Try again in a moment."
          : "Wait for the current action to finish.",
      );
    if (!e.dataTransfer.files.length) return;
    $("upload").files = e.dataTransfer.files;
    $("upload").dispatchEvent(new Event("change"));
  });
}
$("question").onkeydown = (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!busy && !asking) $("ask").requestSubmit();
  }
};
$("delete-chat").onclick = () => $("delete-dialog").showModal();
$("cancel-delete").onclick = () => $("delete-dialog").close();
$("confirm-delete").onclick = () => {
  $("delete-dialog").close();
  run(async () => {
    await api("/api/chats/" + current.id, { method: "DELETE" });
    current = null;
    selected.clear();
    view = { di: 0, page: 1 };
    ev = null;
    evOpen = false;
    renderAll();
    await loadChats();
  });
};
$("close-evidence").onclick = closeEvidence;
document.addEventListener("click", (e) => {
  const menu = $("chat-menu");
  if (menu.open && !menu.contains(e.target)) menu.open = false;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if ($("chat-menu").open) $("chat-menu").open = false;
    else closeEvidence();
  } else if (
    e.key === "/" &&
    !e.metaKey &&
    !e.ctrlKey &&
    !/^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName)
  ) {
    e.preventDefault();
    $("question").focus();
  }
});
renderAll();
run(async () => {
  uploadLimits = (await api("/api/config", { cache: "no-store" })).upload_limits;
  renderDrawings();
  if (!current) renderPlan();
  await loadChats();
});
