"use strict";
const $ = (id) => document.getElementById(id);
let current = null,
  selected = new Set(),
  busy = false,
  evidenceTrigger = null,
  uploadLimits = null;
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
function controls() {
  $("upload").disabled = busy || !current || !uploadLimits;
  $("send").disabled = busy || !current || !selected.size;
  $("new-chat").disabled = busy;
  $("delete-chat").disabled = busy;
  document
    .querySelectorAll(".drawing input,.chat-button")
    .forEach((n) => (n.disabled = busy));
  $("scope").textContent = selected.size
    ? `Asking about ${selected.size} selected drawing${selected.size === 1 ? "" : "s"} · Scope carries into follow-ups`
    : "Select drawings to ask a question";
}
async function loadChats() {
  const chats = await api("/api/chats");
  $("chats").replaceChildren();
  for (const chat of chats) {
    const b = element(
      "button",
      "chat-button" + (current?.id === chat.id ? " active" : ""),
      chat.title || "Untitled conversation",
    );
    b.setAttribute("aria-current", current?.id === chat.id ? "page" : "false");
    b.append(element("span", "chat-date", "Saved locally"));
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
    label.append(
      input,
      element("span", "", drawing.filename),
      element("span", "filetype", drawing.format),
    );
    $("drawing-list").append(label);
  }
  $("drawing-count").textContent = current?.drawings.length || 0;
  const limits = uploadLimits
    ? `IFC up to ${formatLimit(uploadLimits.ifc)}; other formats up to ${formatLimit(uploadLimits.default)}.`
    : "Loading upload limits…";
  $("upload-hint").textContent = current
    ? `Select the drawings relevant to your next question. Multiple views may overlap; confirm independence before totaling. ${limits}`
    : `PNG · JPEG · PDF · IFC · DXF · SVG. ${limits} Create a conversation to begin.`;
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
function renderMessages() {
  const list = $("messages");
  list.replaceChildren();
  if (!current?.messages.length) {
    const welcome = element("div", "welcome");
    welcome.append(
      element("div", "eyebrow", "FROM DRAWING TO UNDERSTANDING"),
      element(
        "h2",
        "",
        current
          ? "Start with a drawing.\nFollow the evidence."
          : "Your drawings.\nA conversation away.",
      ),
      element(
        "p",
        "",
        "Upload a drawing set and ask about quantities, rooms, dimensions or construction details. Inspect the source behind every answer.",
      ),
    );
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
    list.append(welcome);
    return;
  }
  for (const message of current.messages) {
    const card = element("article", "message " + message.role);
    if (message.role === "user") {
      card.append(
        element("div", "message-label", "YOU"),
        element("div", "", message.content || message.question || ""),
      );
    } else {
      const a = message.answer || {},
        error = a.error || a.error_code;
      const label = element("div", "message-label", "STOA");
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
  $("evidence").replaceChildren(
    element(
      "div",
      "evidence-empty",
      "Select an answer reference to inspect its source and calculation.",
    ),
  );
  closeEvidence();
}
async function openChat(id) {
  current = await api("/api/chats/" + id);
  selected = new Set(current.selected_drawing_ids || []);
  if (!current.messages.length)
    for (const d of current.drawings) selected.add(d.id);
  $("chat-title").textContent = current.title || "Untitled conversation";
  $("delete-chat").hidden = false;
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
$("new-chat").onclick = () =>
  run(async () => {
    const chat = await api("/api/chats", {
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
    await openChat(chat.id);
    $("question").focus();
  });
$("upload").onchange = () =>
  run(async () => {
    const files = [...$("upload").files],
      failures = [];
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
    renderDrawings();
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
    $("chat-title").textContent = "A clearer view of your drawings.";
    $("delete-chat").hidden = true;
    renderDrawings();
    renderMessages();
    resetEvidence();
    await loadChats();
  });
};
$("close-evidence").onclick = closeEvidence;
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeEvidence();
});
renderMessages();
run(async () => {
  uploadLimits = (await api("/api/config", { cache: "no-store" })).upload_limits;
  renderDrawings();
  await loadChats();
});
