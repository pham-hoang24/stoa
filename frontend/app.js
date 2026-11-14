"use strict";
const $ = (id) => document.getElementById(id);
let current = null,
  selected = new Set(),
  busy = false,
  evidenceTrigger = null,
  uploadLimits = null,
  sourcesOpen = true;
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
function setSourcesOpen(open) {
  sourcesOpen = open;
  $("sources").classList.toggle("collapsed", !open);
  $("sources-toggle").setAttribute("aria-expanded", open ? "true" : "false");
  updateSourcesSummary();
}
function updateSourcesSummary() {
  const total = current?.drawings.length || 0;
  const picked = selected.size;
  $("sources-summary").textContent = total
    ? `${picked} of ${total} selected`
    : "";
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
function controls() {
  document.body.classList.toggle("busy", busy);
  $("upload").disabled = busy || !uploadLimits;
  document
    .querySelectorAll(".dropzone")
    .forEach((n) => n.classList.toggle("disabled", $("upload").disabled));
  $("send").disabled = busy || !current || !selected.size;
  $("new-chat").disabled = busy;
  $("delete-chat").disabled = busy;
  $("sources-toggle").disabled = busy;
  document
    .querySelectorAll(".drawing input,.chat-button")
    .forEach((n) => (n.disabled = busy));
  $("scope").textContent = selected.size
    ? `Asking about ${selected.size} selected drawing${selected.size === 1 ? "" : "s"} · Scope carries into follow-ups`
    : current?.drawings.length
      ? "Select a drawing to ask about"
      : "Add a drawing to start asking";
  updateSourcesSummary();
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
    b.onclick = () => run(async () => openChat(chat.id));
    $("chats").append(b);
  }
  if (!chats.length)
    $("chats").append(
      element("p", "hint", "Your conversations will appear here."),
    );
}
function renderDrawings() {
  $("drawing-list").replaceChildren();
  for (const drawing of current?.drawings || []) {
    const label = element("label", "drawing"),
      input = element("input");
    input.type = "checkbox";
    input.checked = selected.has(drawing.id);
    input.dataset.id = drawing.id;
    input.onchange = () => {
      input.checked ? selected.add(drawing.id) : selected.delete(drawing.id);
      controls();
    };
    const name = element("span", "", drawing.filename);
    name.title = drawing.filename;
    label.append(input, name, element("span", "filetype", drawing.format));
    $("drawing-list").append(label);
  }
  $("drawing-count").textContent = `(${current?.drawings.length || 0})`;
  $("sources").hidden = !current?.drawings.length;
  const limits = uploadLimits
    ? `IFC up to ${formatLimit(uploadLimits.ifc)}; other formats up to ${formatLimit(uploadLimits.default)}.`
    : "";
  $("upload-hint").textContent =
    `Select the drawings relevant to your next question. Views can overlap; confirm they are independent before totaling. ${limits}`;
  const dropLimits = document.getElementById("drop-limits");
  if (dropLimits)
    dropLimits.textContent = `PNG, JPEG, PDF, IFC, DXF or SVG. ${limits}`;
  updateSourcesSummary();
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
  const label = add("text", {
    x: 210,
    y: 98,
    "font-size": 12,
    fill: "#6f4a18",
    "font-family": "sans-serif",
  });
  label.textContent = "Evidence box";
  wrap.append(svg);
  const caption = element(
    "p",
    "sample-caption",
    "Illustration. Every answer is tied to a box like this on your sheet.",
  );
  wrap.append(caption);
  return wrap;
}
function renderMessages() {
  const list = $("messages");
  list.replaceChildren();
  if (!current?.messages.length) {
    const hasDrawings = !!current?.drawings.length,
      welcome = element("div", "welcome");
    welcome.append(
      element(
        "h2",
        "",
        hasDrawings
          ? "Ask about the selected drawings."
          : "Add a drawing to start.",
      ),
      element(
        "p",
        "",
        "Ask how many doors, rooms or square metres a sheet shows. Each answer points to a box on the drawing or an IFC element, and Stoa says so when the drawing does not support an answer.",
      ),
    );
    if (hasDrawings) {
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
      welcome.append(examples);
    } else {
      const zone = element("label", "dropzone");
      zone.htmlFor = "upload";
      zone.append(
        element("strong", "", "Add a drawing"),
        element("span", "", "Choose files or drop them here."),
      );
      const limits = element("span", "", "");
      limits.id = "drop-limits";
      zone.append(limits);
      zone.ondragover = (e) => {
        e.preventDefault();
        zone.classList.add("dragover");
      };
      zone.ondragleave = () => zone.classList.remove("dragover");
      zone.ondrop = (e) => {
        e.preventDefault();
        zone.classList.remove("dragover");
        if (busy || !uploadLimits || !e.dataTransfer?.files.length) return;
        $("upload").files = e.dataTransfer.files;
        $("upload").dispatchEvent(new Event("change"));
      };
      welcome.append(zone, sampleSheet());
    }
    list.append(welcome);
    renderDrawings();
    controls();
    return;
  }
  for (const message of current.messages) {
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
      if (a.value !== null && a.value !== undefined) {
        const value = element("div", "answer-value", String(a.value));
        if (a.unit) value.append(element("span", "answer-unit", a.unit));
        card.append(value);
      }
      card.append(
        element("div", "", a.explanation || "No explanation available."),
      );
      if (a.image_processing) {
        const required = a.image_processing.required_views;
        const completed = a.image_processing.completed_views;
        if (Array.isArray(required) && Array.isArray(completed))
          card.append(element("p", "hint", `Image region coverage: ${completed.length} / ${required.length}`));
      }
      if (error) card.append(element("p", "hint", String(error)));
      const citations = element("div", "citations");
      (a.evidence || []).forEach((e, i) => {
        const drawing = current.drawings.find((d) => d.id === e.drawing_id);
        const b = element(
          "button",
          "citation",
          `${String(i + 1).padStart(2, "0")} · ${drawing?.filename || "Source"}${e.page ? " · p." + e.page : ""}`,
        );
        b.onclick = () => run(async () => inspectEvidence(message, i));
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
  list.scrollTop = list.scrollHeight;
}
function resetEvidence() {
  $("evidence").replaceChildren();
  closeEvidence();
}
async function openChat(id) {
  current = await api("/api/chats/" + id);
  selected = new Set(current.selected_drawing_ids || []);
  if (!current.messages.length)
    for (const d of current.drawings) selected.add(d.id);
  $("chat-title").textContent = chatName(current);
  $("delete-chat").hidden = false;
  setSourcesOpen(!current.messages.length);
  renderDrawings();
  renderMessages();
  await loadChats();
  controls();
  resetEvidence();
}
function closeEvidence() {
  $("evidence-panel").classList.remove("open");
  $("close-evidence").hidden = true;
  if (evidenceTrigger?.isConnected) evidenceTrigger.focus();
}
async function inspectEvidence(message, index) {
  evidenceTrigger = document.activeElement;
  const evidence = await api(
      `/api/chats/${current.id}/evidence/${message.id}/${index}`,
    ),
    drawing = current.drawings.find((d) => d.id === evidence.drawing_id),
    panel = $("evidence");
  panel.replaceChildren();
  panel.append(
    element("h2", "evidence-heading", drawing?.filename || "Source evidence"),
    element(
      "div",
      "evidence-meta",
      `${drawing?.format?.toUpperCase() || ""}${evidence.page ? " · Page " + evidence.page : ""} · Original source coordinates`,
    ),
  );
  if (evidence.preview_url) {
    const preview = element("div", "preview"),
      img = element("img");
    img.alt = `Source preview for ${drawing?.filename || "drawing"}, page ${evidence.page || 1}`;
    img.src = evidence.preview_url;
    img.onerror = () => {
      preview.replaceChildren(
        element(
          "p",
          "hint",
          "Preview unavailable. Inspect the source properties and original below.",
        ),
      );
    };
    preview.append(img);
    const page = drawing?.pages.find((p) => p.page === evidence.page) || {},
      origin = evidence.transform?.slice(4, 6) || page.origin || [0, 0],
      w = evidence.source_width || page.width,
      h = evidence.source_height || page.height;
    if (w && h) {
      const ns = "http://www.w3.org/2000/svg",
        svg = document.createElementNS(ns, "svg");
      svg.setAttribute("viewBox", `${origin[0]} ${origin[1]} ${w} ${h}`);
      svg.setAttribute("preserveAspectRatio", "none");
      svg.setAttribute(
        "aria-label",
        "Highlighted evidence in source coordinates",
      );
      if (evidence.bbox) {
        const [x0, y0, x1, y1] = evidence.bbox,
          r = document.createElementNS(ns, "rect");
        Object.entries({
          x: x0,
          y: y0,
          width: x1 - x0,
          height: y1 - y0,
        }).forEach(([k, v]) => r.setAttribute(k, v));
        svg.append(r);
      }
      for (const [key, tag] of [
        ["polygon", "polygon"],
        ["dimension_line", "polyline"],
      ])
        if (evidence[key]) {
          const shape = document.createElementNS(ns, tag);
          shape.setAttribute(
            "points",
            evidence[key].map((p) => p.join(",")).join(" "),
          );
          svg.append(shape);
        }
      preview.append(svg);
    }
    const viewport = element("div", "preview-viewport");
    viewport.tabIndex = 0;
    viewport.setAttribute("role", "region");
    viewport.setAttribute(
      "aria-label",
      "Drawing preview. Use arrow keys or scroll to pan when zoomed.",
    );
    viewport.append(preview);
    const toolbar = element("div", "preview-tools"),
      zoomLabel = element("span", "hint", "Fit"),
      fit = element("button", "", "Fit"),
      minus = element("button", "", "−"),
      plus = element("button", "", "＋"),
      focus = element("button", "", "Focus evidence");
    minus.setAttribute("aria-label", "Zoom out");
    plus.setAttribute("aria-label", "Zoom in");
    focus.dataset.action = "focus-evidence";
    let zoom = 1;
    const setZoom = (value) => {
      zoom = Math.max(1, Math.min(16, value));
      preview.style.width = zoom * 100 + "%";
      zoomLabel.textContent = zoom === 1 ? "Fit" : zoom.toFixed(1) + "×";
      minus.disabled = zoom === 1;
      plus.disabled = zoom === 16;
    };
    fit.onclick = () => {
      setZoom(1);
      viewport.scrollTo(0, 0);
    };
    minus.onclick = () => setZoom(zoom / 2);
    plus.onclick = () => setZoom(zoom * 2);
    focus.disabled = !evidence.bbox;
    focus.onclick = () => {
      const [x0, y0, x1, y1] = evidence.bbox;
      const width = evidence.source_width || page.width,
        height = evidence.source_height || page.height;
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
        viewport.focus();
      });
    };
    toolbar.append(fit, minus, plus, focus, zoomLabel);
    panel.append(
      toolbar,
      viewport,
      element(
        "p",
        "hint",
        "Zoom or focus the cited region. Scroll or use arrow keys to pan.",
      ),
    );
    setZoom(1);
  } else
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
  $("evidence-panel").classList.add("open");
  $("close-evidence").hidden = false;
  $("close-evidence").focus();
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
$("sources-toggle").onclick = () => {
  if (!busy) setSourcesOpen(!sourcesOpen);
};
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
    setSourcesOpen(true);
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
    $("chat-title").textContent = chatName(current);
    renderDrawings();
    if (!current.messages.length) renderMessages();
    await loadChats();
    $("upload").value = "";
    notice(
      failures.length
        ? failures.join(" · ")
        : `${files.length} drawing${files.length === 1 ? "" : "s"} added. Ready for your question.`,
    );
  });
$("ask").onsubmit = (event) => {
  event.preventDefault();
  if (!current || !selected.size || !$("question").value.trim()) return;
  run(async () => {
    const question = $("question").value.trim(),
      pending = element(
        "div",
        "processing",
        "Reading selected drawings and checking evidence…",
      );
    setSourcesOpen(false);
    $("messages").append(pending);
    try {
      await api(`/api/chats/${current.id}/questions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, drawing_ids: [...selected] }),
      });
      $("question").value = "";
      current = await api("/api/chats/" + current.id);
      renderMessages();
      await loadChats();
    } finally {
      pending.remove();
    }
  });
};
$("question").onfocus = () => {
  if (current?.drawings.length) setSourcesOpen(false);
};
$("question").onkeydown = (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!busy) $("ask").requestSubmit();
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
    $("chat-title").textContent = "Drawing desk";
    $("delete-chat").hidden = true;
    setSourcesOpen(true);
    renderDrawings();
    renderMessages();
    resetEvidence();
    await loadChats();
  });
};
$("close-evidence").onclick = closeEvidence;
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeEvidence();
  else if (
    e.key === "/" &&
    !e.metaKey &&
    !e.ctrlKey &&
    !/^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName)
  ) {
    e.preventDefault();
    $("question").focus();
  }
});
setSourcesOpen(true);
renderMessages();
run(async () => {
  uploadLimits = (await api("/api/config", { cache: "no-store" })).upload_limits;
  renderDrawings();
  if (!current) renderMessages();
  await loadChats();
});
