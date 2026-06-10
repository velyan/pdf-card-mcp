from __future__ import annotations

import html
import json

from .models import ConversionManifest


def render_html(manifest: ConversionManifest) -> str:
    payload = manifest.to_dict(include_data=True)
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(manifest.title)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  color-scheme: light;
  --bg: #f5f2eb;
  --paper: #fffdf8;
  --paper-soft: #f7f2e9;
  --ink: #282522;
  --muted: #746f67;
  --line: #d9d1c7;
  --accent: #6f836e;
  --accent-soft: #e7eee3;
  --plum: #766374;
  --plum-soft: #eee8ec;
  --clay: #a98677;
  --clay-soft: #f0e4de;
  --gold: #a9834d;
  --shadow: 0 12px 30px rgba(59, 51, 43, 0.09);
  --reader-font-size: 22px;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  min-height: 100vh;
  background:
    linear-gradient(180deg, rgba(255, 253, 248, 0.82), rgba(245, 242, 235, 0.96)),
    var(--bg);
  color: var(--ink);
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
button, input {{ font: inherit; }}
button {{
  min-height: 40px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--paper);
  color: var(--ink);
  cursor: pointer;
}}
button:hover, button:focus-visible, input:focus-visible {{
  border-color: var(--accent);
  outline: 3px solid rgba(111, 131, 110, 0.18);
  outline-offset: 1px;
}}
.shell {{
  display: grid;
  grid-template-columns: minmax(250px, 310px) minmax(0, 1fr);
  min-height: 100vh;
}}
.rail {{
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: auto;
  padding: 22px 18px;
  border-right: 1px solid var(--line);
  background: rgba(255, 253, 249, 0.78);
  backdrop-filter: blur(14px);
}}
.brand h1 {{
  margin: 0;
  font-family: ui-serif, Georgia, "Times New Roman", serif;
  font-size: 25px;
  line-height: 1.12;
  letter-spacing: 0;
}}
.brand p {{
  margin: 10px 0 0;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.45;
}}
.controls {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 18px 0 12px;
}}
.search {{
  width: 100%;
  min-height: 42px;
  margin-bottom: 12px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--paper);
  color: var(--ink);
}}
.font-control {{
  margin: 14px 0;
  padding: 12px;
  border: 1px solid rgba(217, 209, 199, 0.78);
  border-radius: 8px;
  background: rgba(255, 253, 248, 0.62);
}}
.font-row {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 650;
}}
.font-row output {{
  color: #475f47;
  font-variant-numeric: tabular-nums;
}}
.font-control input[type="range"] {{
  width: 100%;
  accent-color: var(--accent);
}}
.meter {{
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: #ebe2dd;
}}
.meter span {{
  display: block;
  width: 0;
  height: 100%;
  background: var(--accent);
  transition: width 160ms ease;
}}
.counter {{
  margin: 8px 0 18px;
  color: var(--muted);
  font-size: 14px;
}}
.sections {{
  display: grid;
  gap: 8px;
}}
.sections button {{
  width: 100%;
  padding: 9px 10px;
  text-align: left;
  background: rgba(255, 253, 249, 0.78);
}}
.sections button.active {{
  border-color: var(--accent);
  background: var(--accent-soft);
  color: #415640;
}}
.content {{
  min-width: 0;
  padding: 34px clamp(18px, 5vw, 76px) 76px;
}}
.masthead {{
  max-width: 1050px;
  margin: 0 auto 26px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--line);
}}
.masthead h2 {{
  margin: 0;
  max-width: 950px;
  font-family: ui-serif, Georgia, "Times New Roman", serif;
  font-size: clamp(31px, 5vw, 58px);
  line-height: 1.04;
  letter-spacing: 0;
}}
.masthead p {{
  margin: 12px 0 0;
  color: var(--muted);
  font-size: 17px;
  line-height: 1.45;
}}
.cards {{
  display: grid;
  gap: 16px;
  max-width: 1050px;
  margin: 0 auto;
}}
.card {{
  position: relative;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 253, 249, 0.94);
  box-shadow: 0 8px 22px rgba(59, 51, 43, 0.055);
  overflow: hidden;
  transition: border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease;
}}
.card:hover {{
  border-color: rgba(111, 131, 110, 0.44);
  box-shadow: 0 12px 28px rgba(59, 51, 43, 0.08);
}}
.card.table {{ border-color: rgba(118, 99, 116, 0.45); }}
.card.figure {{ border-color: rgba(111, 131, 110, 0.54); }}
.card.formula {{ border-color: rgba(169, 131, 77, 0.42); }}
.card.footnote {{
  border-color: rgba(111, 131, 110, 0.28);
  background: rgba(247, 242, 233, 0.82);
}}
.card.metadata {{
  border-color: rgba(217, 209, 199, 0.72);
  background: rgba(247, 242, 233, 0.62);
  box-shadow: none;
}}
.card.heading {{
  box-shadow: none;
  background: transparent;
  border-color: transparent;
}}
.card-header {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px 18px 0;
}}
.card-actions {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
}}
.card-type {{
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid rgba(118, 99, 116, 0.24);
  border-radius: 999px;
  background: var(--plum-soft);
  color: #675463;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
.page-chip {{
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 9px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: #475f47;
  font-size: 12px;
  font-weight: 650;
}}
.card-header.plain {{
  justify-content: flex-end;
  padding-bottom: 0;
}}
.card-body {{
  padding: 12px 22px 22px;
}}
.card.heading .card-body {{
  padding: 18px 0 2px;
}}
.card.heading h3 {{
  margin: 0;
  font-family: ui-serif, Georgia, "Times New Roman", serif;
  font-size: clamp(27px, 4vw, 42px);
  line-height: 1.08;
  letter-spacing: 0;
}}
.text {{
  margin: 0;
  font-family: ui-serif, Georgia, "Times New Roman", serif;
  font-size: var(--reader-font-size);
  line-height: 1.52;
  letter-spacing: 0;
  max-width: 78ch;
  overflow-wrap: break-word;
  word-break: normal;
  hyphens: auto;
}}
.card.footnote .text {{
  color: var(--muted);
  font-size: calc(var(--reader-font-size) * 0.82);
}}
.card.metadata .text {{
  max-width: 86ch;
  color: var(--muted);
  font-size: calc(var(--reader-font-size) * 0.78);
  line-height: 1.42;
}}
.caption {{
  margin: 0 0 12px;
  color: var(--muted);
  font-size: 16px;
  line-height: 1.45;
}}
.asset-wrap {{
  width: 100%;
  max-width: 100%;
  margin: 0;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}}
.asset-wrap img {{
  display: block;
  width: auto;
  max-width: 100%;
  height: auto;
  min-width: 0;
  margin: 0 auto;
}}
.card.formula .asset-wrap {{
  width: fit-content;
  margin: 0 auto;
  padding: 10px 16px;
}}
.card.formula .asset-wrap img {{
  margin: 0 auto;
}}
.source-link {{
  min-height: 34px;
  padding: 0 11px;
  border-color: rgba(217, 209, 199, 0.88);
  background: rgba(255, 253, 248, 0.62);
  color: var(--muted);
  font-size: 13px;
}}
.source-link:hover,
.source-link:focus-visible {{
  color: #405840;
  background: var(--accent-soft);
}}
.empty {{
  display: none;
  max-width: 680px;
  margin: 40px auto;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--paper);
  color: var(--muted);
  font-size: 18px;
}}
.modal {{
  position: fixed;
  inset: 0;
  display: none;
  place-items: center;
  z-index: 20;
  padding: 22px;
  background: rgba(39, 36, 35, 0.54);
}}
.modal.open {{ display: grid; }}
.modal-panel {{
  width: min(1100px, 96vw);
  max-height: 92vh;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--paper);
  box-shadow: 0 30px 80px rgba(39, 36, 35, 0.32);
  overflow: hidden;
}}
.modal-head {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-bottom: 1px solid var(--line);
}}
.modal-body {{
  overflow: auto;
  background: #efebe7;
}}
.modal-body img {{
  display: block;
  width: 100%;
  height: auto;
}}
mark {{
  background: #f7e6a8;
  color: inherit;
}}
@media (max-width: 820px) {{
  .shell {{ display: block; }}
  .rail {{
    position: sticky;
    z-index: 5;
    height: auto;
    max-height: 56vh;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }}
  .sections {{
    display: flex;
    gap: 8px;
    overflow-x: auto;
    padding-bottom: 2px;
  }}
  .sections button {{
    min-width: max-content;
  }}
  .content {{ padding-top: 22px; }}
  .asset-wrap img {{ min-width: 0; }}
}}
@media (prefers-reduced-motion: reduce) {{
  html {{ scroll-behavior: auto; }}
  * {{ transition: none !important; }}
}}
</style>
</head>
<body>
<div class="shell">
  <aside class="rail">
    <div class="brand">
      <h1>{title}</h1>
      <p><span id="totalCards">0</span> cards · <span id="totalTables">0</span> tables · <span id="totalFigures">0</span> figures · <span id="totalFormulas">0</span> formulas</p>
    </div>
    <div class="controls">
      <button id="prevBtn" type="button">Previous</button>
      <button id="nextBtn" type="button">Next</button>
    </div>
    <input id="search" class="search" type="search" placeholder="Search the document" aria-label="Search the document">
    <div class="font-control">
      <div class="font-row">
        <label for="fontSize">Font size</label>
        <output id="fontSizeValue" for="fontSize">22px</output>
      </div>
      <input id="fontSize" type="range" min="18" max="32" step="1" value="22" aria-label="Font size">
    </div>
    <div class="meter" aria-hidden="true"><span id="meter"></span></div>
    <div id="counter" class="counter">Card 0 of 0</div>
    <nav id="sections" class="sections" aria-label="Sections"></nav>
  </aside>
  <main class="content">
    <header class="masthead">
      <h2>{title}</h2>
      <p>Standalone reader generated from a local PDF. Tables, figures, and formulas are preserved as embedded images.</p>
    </header>
    <section id="cards" class="cards" aria-live="polite"></section>
    <div id="empty" class="empty">No cards match this search.</div>
  </main>
</div>
<div id="modal" class="modal" role="dialog" aria-modal="true" aria-label="Source page">
  <div class="modal-panel">
    <div class="modal-head">
      <strong id="modalTitle">Source page</strong>
      <button id="closeModal" type="button">Close</button>
    </div>
    <div class="modal-body"><img id="modalImage" alt="Source page"></div>
  </div>
</div>
<script>
const payload = {payload_json};
const assetMap = new Map(payload.assets.map(asset => [asset.id, asset]));
const cards = payload.cards;
let filtered = [...cards];
let activeIndex = 0;

const cardsEl = document.getElementById("cards");
const emptyEl = document.getElementById("empty");
const searchEl = document.getElementById("search");
const fontSizeEl = document.getElementById("fontSize");
const fontSizeValueEl = document.getElementById("fontSizeValue");
const counterEl = document.getElementById("counter");
const meterEl = document.getElementById("meter");
const sectionsEl = document.getElementById("sections");
const modalEl = document.getElementById("modal");
const modalImageEl = document.getElementById("modalImage");
const modalTitleEl = document.getElementById("modalTitle");

document.getElementById("totalCards").textContent = String(payload.card_count);
document.getElementById("totalTables").textContent = String(payload.table_count);
document.getElementById("totalFigures").textContent = String(payload.figure_count);
document.getElementById("totalFormulas").textContent = String(payload.formula_count || 0);

function setFontSize(value) {{
  const size = Math.max(18, Math.min(32, Number(value) || 22));
  document.documentElement.style.setProperty("--reader-font-size", `${{size}}px`);
  fontSizeEl.value = String(size);
  fontSizeValueEl.textContent = `${{size}}px`;
  try {{
    localStorage.setItem("pdf-card-reader-font-size", String(size));
  }} catch (_) {{}}
}}

try {{
  setFontSize(localStorage.getItem("pdf-card-reader-font-size") || fontSizeEl.value);
}} catch (_) {{
  setFontSize(fontSizeEl.value);
}}

function uniqueSections() {{
  const seen = new Set();
  return cards.map(card => card.section || "Document").filter(section => {{
    if (seen.has(section)) return false;
    seen.add(section);
    return true;
  }});
}}

function escapeHtml(value) {{
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}}

function highlighted(text) {{
  const query = searchEl.value.trim();
  const safe = escapeHtml(text || "");
  if (!query) return safe;
  const escapedQuery = query.replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&");
  return safe.replace(new RegExp(`(${{escapedQuery}})`, "ig"), "<mark>$1</mark>");
}}

function renderSections() {{
  sectionsEl.innerHTML = "";
  for (const section of uniqueSections()) {{
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = section;
    button.addEventListener("click", () => {{
      const target = filtered.findIndex(card => (card.section || "Document") === section);
      if (target >= 0) scrollToIndex(target);
    }});
    sectionsEl.appendChild(button);
  }}
}}

function cardSearchText(card) {{
  const asset = card.image_id ? assetMap.get(card.image_id) : null;
  return [card.text, card.section, asset?.caption, asset?.alt].filter(Boolean).join(" ").toLowerCase();
}}

function contentLabel(kind) {{
  if (kind === "table") return "Table";
  if (kind === "figure") return "Figure";
  if (kind === "formula") return "Formula";
  return "";
}}

function applyFilter() {{
  const query = searchEl.value.trim().toLowerCase();
  filtered = query ? cards.filter(card => cardSearchText(card).includes(query)) : [...cards];
  activeIndex = 0;
  renderCards();
}}

function renderCards() {{
  cardsEl.innerHTML = "";
  emptyEl.style.display = filtered.length ? "none" : "block";
  filtered.forEach((card, index) => cardsEl.appendChild(renderCard(card, index)));
  updatePosition();
}}

function renderCard(card, index) {{
  const article = document.createElement("article");
  article.className = `card ${{card.kind}}`;
  article.id = card.id;
  article.dataset.index = String(index);
  article.dataset.section = card.section || "Document";

  const asset = card.image_id ? assetMap.get(card.image_id) : null;
  const sourceAsset = card.source_image_id ? assetMap.get(card.source_image_id) : null;
  const badge = `Page ${{card.page}}`;

  if (card.kind === "heading") {{
    article.innerHTML = `<div class="card-body"><h3>${{highlighted(card.text)}}</h3></div>`;
    return article;
  }}

  let body = "";
  if (asset) {{
    const caption = asset.caption || card.text || asset.alt;
    const captionHtml = card.kind === "formula" ? "" : `<p class="caption">${{highlighted(caption)}}</p>`;
    body = `
      ${{captionHtml}}
      <div class="asset-wrap">
        <img loading="lazy" src="${{asset.data_uri}}" width="${{asset.width}}" height="${{asset.height}}" alt="${{escapeHtml(asset.alt || caption)}}">
      </div>`;
  }} else {{
    body = `<p class="text">${{highlighted(card.text)}}</p>`;
  }}

  const sourceButton = sourceAsset
    ? `<button class="source-link" type="button" data-source="${{sourceAsset.id}}">View source</button>`
    : "";
  const label = contentLabel(card.kind);
  const header = label
    ? `<div class="card-header">
        <div class="card-type">${{escapeHtml(label)}}</div>
        <div class="card-actions">
          <div class="page-chip">${{escapeHtml(badge)}}</div>
          ${{sourceButton}}
        </div>
      </div>`
    : `<div class="card-header plain">
        <div class="card-actions">
          <div class="page-chip">${{escapeHtml(badge)}}</div>
          ${{sourceButton}}
        </div>
      </div>`;

  article.innerHTML = `
    ${{header}}
    <div class="card-body">${{body}}</div>`;

  const button = article.querySelector("[data-source]");
  if (button) {{
    button.addEventListener("click", () => openSource(sourceAsset));
  }}
  return article;
}}

function openSource(asset) {{
  modalImageEl.removeAttribute("src");
  modalImageEl.src = asset.data_uri;
  modalImageEl.alt = asset.alt;
  modalTitleEl.textContent = `Source page ${{asset.page}}`;
  modalEl.classList.add("open");
}}

function closeSource() {{
  modalEl.classList.remove("open");
  modalImageEl.removeAttribute("src");
}}

function updatePosition() {{
  const total = filtered.length;
  const current = total ? activeIndex + 1 : 0;
  counterEl.textContent = `Card ${{current}} of ${{total}}`;
  meterEl.style.width = total ? `${{(current / total) * 100}}%` : "0";

  const active = filtered[activeIndex];
  const activeSection = active?.section || "";
  for (const button of sectionsEl.querySelectorAll("button")) {{
    button.classList.toggle("active", button.textContent === activeSection);
  }}
}}

function scrollToIndex(index) {{
  if (!filtered.length) return;
  activeIndex = Math.max(0, Math.min(index, filtered.length - 1));
  const card = cardsEl.querySelector(`[data-index="${{activeIndex}}"]`);
  if (card) card.scrollIntoView({{ behavior: "smooth", block: "center" }});
  updatePosition();
}}

document.getElementById("prevBtn").addEventListener("click", () => scrollToIndex(activeIndex - 1));
document.getElementById("nextBtn").addEventListener("click", () => scrollToIndex(activeIndex + 1));
document.getElementById("closeModal").addEventListener("click", closeSource);
modalEl.addEventListener("click", event => {{
  if (event.target === modalEl) closeSource();
}});
searchEl.addEventListener("input", applyFilter);
fontSizeEl.addEventListener("input", event => setFontSize(event.target.value));
document.addEventListener("keydown", event => {{
  if (event.key === "Escape" && modalEl.classList.contains("open")) closeSource();
  if (event.key === "ArrowRight" && !modalEl.classList.contains("open")) scrollToIndex(activeIndex + 1);
  if (event.key === "ArrowLeft" && !modalEl.classList.contains("open")) scrollToIndex(activeIndex - 1);
}});

const observer = new IntersectionObserver(entries => {{
  const visible = entries
    .filter(entry => entry.isIntersecting)
    .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
  if (!visible) return;
  activeIndex = Number(visible.target.dataset.index || 0);
  updatePosition();
}}, {{ threshold: [0.35, 0.6, 0.9] }});

renderSections();
renderCards();
for (const card of cardsEl.children) observer.observe(card);
</script>
</body>
</html>
"""
