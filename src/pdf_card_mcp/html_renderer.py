from __future__ import annotations

import html
import json

from .annotations import (
    AnnotationBundle,
    annotation_bundle_to_client_dict,
    empty_annotation_bundle,
)
from .models import ConversionManifest
from .style import reader_style_css_variables


def render_html(
    manifest: ConversionManifest,
    *,
    annotation_bundle: AnnotationBundle | None = None,
    annotation_read_only: bool = False,
) -> str:
    payload = manifest.to_dict(include_data=True)
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    annotations = annotation_bundle or empty_annotation_bundle(manifest)
    annotation_config = {
        "read_only": annotation_read_only,
        "bundle": annotation_bundle_to_client_dict(annotations),
    }
    annotation_config_json = json.dumps(annotation_config, ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(manifest.title)
    style_vars = reader_style_css_variables(manifest.style)
    style_css = "\n".join(f"  {name}: {value};" for name, value in style_vars.items())

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  color-scheme: light;
{style_css}
  --reader-font-size: 22px;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  min-height: 100vh;
  background:
    linear-gradient(180deg, rgb(var(--paper-rgb) / 0.82), rgb(var(--bg-rgb) / 0.96)),
    var(--bg);
  color: var(--ink);
  font-family: var(--font-ui);
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
  outline: 3px solid rgb(var(--accent-rgb) / 0.18);
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
  background: rgb(var(--paper-rgb) / 0.78);
  backdrop-filter: blur(14px);
}}
.brand h1 {{
  margin: 0;
  font-family: var(--font-heading);
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
  border: 1px solid rgb(var(--line-rgb) / 0.78);
  border-radius: var(--radius);
  background: rgb(var(--paper-rgb) / 0.62);
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
  color: var(--accent);
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
  background: var(--meter-bg);
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
  background: rgb(var(--paper-rgb) / 0.78);
}}
.sections button.active {{
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
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
  font-family: var(--font-heading);
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
  gap: var(--card-gap);
  max-width: 1050px;
  margin: 0 auto;
}}
.card {{
  position: relative;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: rgb(var(--paper-rgb) / 0.94);
  box-shadow: 0 8px 22px rgb(var(--ink-rgb) / 0.055);
  overflow: hidden;
  transition: border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease;
}}
.card:hover {{
  border-color: rgb(var(--accent-rgb) / 0.44);
  box-shadow: 0 12px 28px rgb(var(--ink-rgb) / 0.08);
}}
.card.table {{ border-color: rgb(var(--plum-rgb) / 0.45); }}
.card.figure {{ border-color: rgb(var(--accent-rgb) / 0.54); }}
.card.formula {{ border-color: rgb(var(--gold-rgb) / 0.42); }}
.card.contents {{ border-color: rgb(var(--accent-rgb) / 0.38); }}
.card.footnote {{
  border-color: rgb(var(--accent-rgb) / 0.28);
  background: rgb(var(--paper-soft-rgb) / 0.82);
}}
.card.metadata {{
  border-color: rgb(var(--line-rgb) / 0.72);
  background: rgb(var(--paper-soft-rgb) / 0.62);
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
  border: 1px solid rgb(var(--plum-rgb) / 0.24);
  border-radius: 999px;
  background: var(--plum-soft);
  color: var(--plum);
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
  color: var(--accent);
  font-size: 12px;
  font-weight: 650;
}}
.card-header.plain {{
  justify-content: flex-end;
  padding-bottom: 0;
}}
.card-body {{
  padding: var(--card-body-padding);
}}
.card.heading .card-body {{
  padding: 18px 0 2px;
}}
.card.heading h3 {{
  margin: 0;
  font-family: var(--font-heading);
  font-size: clamp(27px, 4vw, 42px);
  line-height: 1.08;
  letter-spacing: 0;
}}
.text {{
  margin: 0;
  font-family: var(--font-text);
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
.toc-list {{
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
  font-family: var(--font-text);
  font-size: calc(var(--reader-font-size) * 0.86);
  line-height: 1.32;
}}
.toc-entry {{
  display: grid;
  grid-template-columns: minmax(0, auto) minmax(28px, 1fr) auto;
  align-items: end;
  gap: 8px;
  padding-left: calc(var(--toc-level, 0) * 18px);
}}
.toc-label {{
  min-width: 0;
  color: var(--ink);
  text-decoration: none;
}}
.toc-label:hover,
.toc-label:focus-visible {{
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 3px;
}}
.toc-leader {{
  min-width: 28px;
  border-bottom: 2px dotted rgb(var(--muted-rgb) / 0.48);
  transform: translateY(-0.34em);
}}
.toc-page {{
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}}
.page-anchor {{
  display: block;
  height: 0;
  scroll-margin-top: 28px;
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
  border-radius: var(--radius);
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
  border-color: rgb(var(--line-rgb) / 0.88);
  background: rgb(var(--paper-rgb) / 0.62);
  color: var(--muted);
  font-size: 13px;
}}
.source-link:hover,
.source-link:focus-visible {{
  color: var(--accent);
  background: var(--accent-soft);
}}
.empty {{
  display: none;
  max-width: 680px;
  margin: 40px auto;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
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
  background: rgb(var(--ink-rgb) / 0.54);
}}
.modal.open {{ display: grid; }}
.modal-panel {{
  width: min(1100px, 96vw);
  max-height: 92vh;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  border-radius: var(--radius);
  border: 1px solid var(--line);
  background: var(--paper);
  box-shadow: 0 30px 80px rgb(var(--ink-rgb) / 0.32);
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
  background: var(--modal-bg);
}}
.modal-body img {{
  display: block;
  width: 100%;
  height: auto;
}}
mark {{
  background: var(--mark-bg);
  color: inherit;
}}
.annotation-controls {{
  display: grid;
  gap: 8px;
  margin: 14px 0;
  padding: 12px;
  border: 1px solid rgb(var(--line-rgb) / 0.78);
  border-radius: var(--radius);
  background: rgb(var(--paper-rgb) / 0.62);
}}
.annotation-controls h2 {{
  margin: 0;
  color: var(--muted);
  font-family: var(--font-ui);
  font-size: 13px;
  line-height: 1.3;
  letter-spacing: 0;
}}
.annotation-buttons {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}}
.annotation-buttons button {{
  min-height: 34px;
  padding: 0 10px;
  font-size: 13px;
}}
.annotation-count {{
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.4;
}}
.annotation-list {{
  display: grid;
  gap: 8px;
  max-height: 230px;
  overflow: auto;
}}
.annotation-item {{
  display: grid;
  gap: 5px;
  width: 100%;
  padding: 8px;
  border: 1px solid rgb(var(--line-rgb) / 0.72);
  border-radius: 8px;
  background: rgb(var(--paper-rgb) / 0.74);
  text-align: left;
}}
.annotation-item strong {{
  color: var(--ink);
  font-size: 13px;
  line-height: 1.2;
}}
.annotation-item span {{
  color: var(--muted);
  font-size: 12px;
  line-height: 1.3;
}}
.annotation-mark {{
  border-radius: 3px;
  padding: 0 1px;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}}
.annotation-yellow {{ background: rgb(255 224 130 / 0.58); }}
.annotation-green {{ background: rgb(173 220 172 / 0.52); }}
.annotation-blue {{ background: rgb(153 205 246 / 0.48); }}
.annotation-pink {{ background: rgb(246 176 210 / 0.48); }}
.annotation-purple {{ background: rgb(202 184 238 / 0.48); }}
.note-pin {{
  display: inline-flex;
  align-items: center;
  min-width: 1.3em;
  min-height: 1.3em;
  margin-left: 0.12em;
  padding: 0 0.28em;
  border-radius: 999px;
  background: var(--accent);
  color: var(--paper);
  font-family: var(--font-ui);
  font-size: 0.62em;
  font-weight: 800;
  vertical-align: 0.18em;
}}
.note-text {{
  display: block;
  margin: 10px 0 0;
  padding: 8px 10px;
  border-left: 3px solid var(--accent);
  background: var(--accent-soft);
  color: var(--ink);
  font-size: calc(var(--reader-font-size) * 0.78);
  line-height: 1.38;
}}
.annotation-popover {{
  position: fixed;
  z-index: 30;
  display: none;
  gap: 6px;
  padding: 6px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--paper);
  box-shadow: 0 10px 32px rgb(var(--ink-rgb) / 0.18);
}}
.annotation-popover.open {{
  display: inline-flex;
}}
.annotation-popover button {{
  min-height: 32px;
  padding: 0 10px;
  font-size: 13px;
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
    <section class="annotation-controls" aria-label="Annotations">
      <h2>Annotations</h2>
      <p class="annotation-count"><span id="annotationCount">0</span> saved</p>
      <div id="annotationButtons" class="annotation-buttons">
        <button id="exportAnnotations" type="button">Export</button>
        <button id="importAnnotations" type="button">Import</button>
      </div>
      <input id="annotationFile" type="file" accept="application/json,.json" hidden>
      <div id="annotationList" class="annotation-list"></div>
    </section>
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
<div id="annotationPopover" class="annotation-popover" role="toolbar" aria-label="Annotation actions">
  <button id="highlightSelection" type="button">Highlight</button>
  <button id="noteSelection" type="button">Note</button>
</div>
<script>
const payload = {payload_json};
const assetMap = new Map(payload.assets.map(asset => [asset.id, asset]));
const annotationConfig = {annotation_config_json};
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
const annotationCountEl = document.getElementById("annotationCount");
const annotationButtonsEl = document.getElementById("annotationButtons");
const annotationListEl = document.getElementById("annotationList");
const exportAnnotationsEl = document.getElementById("exportAnnotations");
const importAnnotationsEl = document.getElementById("importAnnotations");
const annotationFileEl = document.getElementById("annotationFile");
const annotationPopoverEl = document.getElementById("annotationPopover");
const highlightSelectionEl = document.getElementById("highlightSelection");
const noteSelectionEl = document.getElementById("noteSelection");
const annotationBundle = annotationConfig.bundle || {{}};
const annotationReadOnly = Boolean(annotationConfig.read_only);
const documentId = annotationBundle.document_id || `${{payload.title || "reader"}}-${{payload.page_count || 0}}-${{payload.card_count || 0}}`;
const annotationStorageKey = `pdf-card-reader:${{documentId}}:annotations`;
let annotations = normalizeAnnotations(annotationBundle.annotations || []);
let pendingSelection = null;

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

function normalizeAnnotations(items) {{
  const seen = new Set();
  return (Array.isArray(items) ? items : []).filter(item => {{
    if (!item || typeof item !== "object") return false;
    if (!item.id || seen.has(item.id)) return false;
    if (!["highlight", "note"].includes(item.kind)) return false;
    if (!item.card_id) return false;
    seen.add(item.id);
    return true;
  }}).map(item => ({{
    id: String(item.id),
    kind: item.kind,
    card_id: String(item.card_id),
    page: item.page ? Number(item.page) : null,
    bbox: Array.isArray(item.bbox) ? item.bbox : null,
    text_quote: String(item.text_quote || ""),
    text_start: Number.isInteger(item.text_start) ? item.text_start : null,
    text_end: Number.isInteger(item.text_end) ? item.text_end : null,
    text_hash: item.text_hash ? String(item.text_hash) : null,
    color: ["yellow", "green", "blue", "pink", "purple"].includes(item.color) ? item.color : "yellow",
    note: String(item.note || ""),
    tags: Array.isArray(item.tags) ? item.tags.map(String) : [],
    visibility: item.visibility === "public" ? "public" : "private",
    created_at: item.created_at || new Date().toISOString(),
    updated_at: item.updated_at || new Date().toISOString(),
  }}));
}}

function loadLocalAnnotations() {{
  if (annotationReadOnly) return;
  try {{
    const raw = localStorage.getItem(annotationStorageKey);
    if (!raw) return;
    const payload = JSON.parse(raw);
    mergeAnnotations(payload.annotations || payload, false);
  }} catch (_) {{}}
}}

function saveLocalAnnotations() {{
  if (annotationReadOnly) return;
  try {{
    localStorage.setItem(annotationStorageKey, JSON.stringify(currentAnnotationBundle()));
  }} catch (_) {{}}
}}

function mergeAnnotations(items, persist = true) {{
  const byId = new Map(annotations.map(item => [item.id, item]));
  for (const item of normalizeAnnotations(items)) byId.set(item.id, item);
  annotations = [...byId.values()];
  if (persist) saveLocalAnnotations();
  renderAnnotationList();
}}

function currentAnnotationBundle() {{
  const now = new Date().toISOString();
  return {{
    schema_version: annotationBundle.schema_version || "pdf-card-annotations/v1",
    document_id: documentId,
    manifest_hash: annotationBundle.manifest_hash || "",
    created_at: annotationBundle.created_at || now,
    updated_at: now,
    annotations,
  }};
}}

function annotationsForCard(card) {{
  return annotations
    .filter(item => item.card_id === card.id)
    .map(item => resolveClientAnnotation(item, card))
    .filter(Boolean)
    .sort((a, b) => (a.text_start ?? 0) - (b.text_start ?? 0));
}}

function resolveClientAnnotation(annotation, card) {{
  const text = card.text || "";
  let start = annotation.text_start;
  let end = annotation.text_end;
  if (
    Number.isInteger(start) &&
    Number.isInteger(end) &&
    start >= 0 &&
    end <= text.length &&
    start < end
  ) {{
    return {{ ...annotation, text_start: start, text_end: end, text_quote: text.slice(start, end) }};
  }}
  if (annotation.text_quote) {{
    const index = text.indexOf(annotation.text_quote);
    if (index >= 0) {{
      return {{
        ...annotation,
        text_start: index,
        text_end: index + annotation.text_quote.length,
      }};
    }}
  }}
  return null;
}}

function annotatedText(card) {{
  const text = card.text || "";
  const ranges = annotationsForCard(card);
  if (!ranges.length) return highlighted(text);
  let htmlParts = "";
  let cursor = 0;
  for (const annotation of ranges) {{
    const start = Math.max(cursor, annotation.text_start || 0);
    const end = Math.max(start, annotation.text_end || start);
    if (start > cursor) htmlParts += highlighted(text.slice(cursor, start));
    const selected = highlighted(text.slice(start, end));
    const title = annotation.note ? ` title="${{escapeHtml(annotation.note)}}"` : "";
    const notePin = annotation.kind === "note" ? `<sup class="note-pin">N</sup>` : "";
    htmlParts += `<span class="annotation-mark annotation-${{annotation.color}}" data-annotation-id="${{escapeHtml(annotation.id)}}"${{title}}>${{selected}}</span>${{notePin}}`;
    if (annotation.note) {{
      htmlParts += `<span class="note-text">${{escapeHtml(annotation.note)}}</span>`;
    }}
    cursor = end;
  }}
  if (cursor < text.length) htmlParts += highlighted(text.slice(cursor));
  return htmlParts;
}}

function selectionWithinAnnotatable() {{
  if (annotationReadOnly) return null;
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  const element = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
    ? range.commonAncestorContainer
    : range.commonAncestorContainer.parentElement;
  const container = element?.closest?.("[data-annotatable='true']");
  if (!container) return null;
  const article = container.closest(".card");
  const card = cards.find(item => item.id === article?.id);
  if (!card) return null;
  const preRange = range.cloneRange();
  preRange.selectNodeContents(container);
  preRange.setEnd(range.startContainer, range.startOffset);
  const start = preRange.toString().length;
  const quote = selection.toString();
  const end = start + quote.length;
  if (!quote.trim() || start < 0 || end > (card.text || "").length) return null;
  return {{ card, quote, start, end, rect: range.getBoundingClientRect() }};
}}

function showAnnotationPopover() {{
  pendingSelection = selectionWithinAnnotatable();
  if (!pendingSelection) {{
    annotationPopoverEl.classList.remove("open");
    return;
  }}
  annotationPopoverEl.style.left = `${{Math.max(12, pendingSelection.rect.left)}}px`;
  annotationPopoverEl.style.top = `${{Math.max(12, pendingSelection.rect.top - 48)}}px`;
  annotationPopoverEl.classList.add("open");
}}

function createAnnotation(kind) {{
  if (!pendingSelection) return;
  const note = kind === "note" ? window.prompt("Note") || "" : "";
  const now = new Date().toISOString();
  const annotation = {{
    id: `ann-${{Date.now()}}-${{Math.random().toString(16).slice(2)}}`,
    kind,
    card_id: pendingSelection.card.id,
    page: pendingSelection.card.page,
    bbox: pendingSelection.card.bbox || null,
    text_quote: pendingSelection.quote,
    text_start: pendingSelection.start,
    text_end: pendingSelection.end,
    text_hash: null,
    color: kind === "note" ? "blue" : "yellow",
    note,
    tags: [],
    visibility: "private",
    created_at: now,
    updated_at: now,
  }};
  mergeAnnotations([annotation]);
  window.getSelection()?.removeAllRanges();
  annotationPopoverEl.classList.remove("open");
  renderCards();
}}

function renderAnnotationList() {{
  annotationCountEl.textContent = String(annotations.length);
  annotationButtonsEl.style.display = annotationReadOnly ? "none" : "grid";
  annotationListEl.innerHTML = "";
  const visible = annotations.slice(0, 30);
  for (const annotation of visible) {{
    const button = document.createElement("button");
    button.type = "button";
    button.className = "annotation-item";
    const label = annotation.kind === "note" ? "Note" : "Highlight";
    const quote = annotation.note || annotation.text_quote || "Annotation";
    button.innerHTML = `<strong>${{escapeHtml(label)}} · Page ${{escapeHtml(annotation.page || "")}}</strong><span>${{escapeHtml(quote.slice(0, 120))}}</span>`;
    button.addEventListener("click", () => {{
      const index = filtered.findIndex(card => card.id === annotation.card_id);
      if (index >= 0) scrollToIndex(index);
    }});
    annotationListEl.appendChild(button);
  }}
}}

function exportAnnotations() {{
  const blob = new Blob([JSON.stringify(currentAnnotationBundle(), null, 2)], {{
    type: "application/json",
  }});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${{documentId}}.annotations.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}}

function importAnnotationsFile(file) {{
  if (!file) return;
  const reader = new FileReader();
  reader.addEventListener("load", () => {{
    try {{
      const payload = JSON.parse(String(reader.result || "{{}}"));
      mergeAnnotations(payload.annotations || []);
      renderCards();
    }} catch (_) {{
      window.alert("Could not import annotations JSON.");
    }}
  }});
  reader.readAsText(file);
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
  const itemText = Array.isArray(card.items)
    ? card.items.map(item => [item.label, item.title, item.page_label].filter(Boolean).join(" ")).join(" ")
    : "";
  return [card.text, card.section, itemText, asset?.caption, asset?.alt].filter(Boolean).join(" ").toLowerCase();
}}

function contentLabel(kind) {{
  if (kind === "contents") return "Contents";
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
  const anchoredPages = new Set();
  filtered.forEach((card, index) => {{
    if (card.page && !anchoredPages.has(card.page)) {{
      const anchor = document.createElement("span");
      anchor.id = `page-${{card.page}}`;
      anchor.className = "page-anchor";
      cardsEl.appendChild(anchor);
      anchoredPages.add(card.page);
    }}
    cardsEl.appendChild(renderCard(card, index));
  }});
  if (typeof observer !== "undefined") {{
    for (const card of cardsEl.querySelectorAll(".card")) observer.observe(card);
  }}
  updatePosition();
}}

function safeHref(href) {{
  if (typeof href !== "string") return "";
  if (/^#page-[0-9]+$/.test(href)) return href;
  if (/^(https?:\\/\\/|mailto:)/i.test(href)) return href;
  return "";
}}

function renderContents(card) {{
  const items = Array.isArray(card.items) ? card.items : [];
  const entries = items.map(item => {{
    const label = item.label || item.title || "";
    const page = item.page_label || item.target_page || "";
    const level = Math.max(0, Math.min(6, Number(item.level || 0)));
    const href = safeHref(item.href);
    const labelHtml = href
      ? `<a class="toc-label" href="${{escapeHtml(href)}}">${{highlighted(label)}}</a>`
      : `<span class="toc-label">${{highlighted(label)}}</span>`;
    return `<li class="toc-entry" style="--toc-level: ${{level}}">${{labelHtml}}<span class="toc-leader" aria-hidden="true"></span><span class="toc-page">${{escapeHtml(String(page))}}</span></li>`;
  }}).join("");
  return `<ol class="toc-list">${{entries}}</ol>`;
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
    article.innerHTML = `<div class="card-body"><h3 data-annotatable="true">${{annotatedText(card)}}</h3></div>`;
    return article;
  }}

  let body = "";
  if (card.kind === "contents") {{
    body = renderContents(card);
  }} else if (asset) {{
    const caption = asset.caption || card.text || asset.alt;
    const captionHtml = card.kind === "formula" ? "" : `<p class="caption">${{highlighted(caption)}}</p>`;
    body = `
      ${{captionHtml}}
      <div class="asset-wrap">
        <img loading="lazy" src="${{asset.data_uri}}" width="${{asset.width}}" height="${{asset.height}}" alt="${{escapeHtml(asset.alt || caption)}}">
      </div>`;
  }} else {{
    body = `<p class="text" data-annotatable="true">${{annotatedText(card)}}</p>`;
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
exportAnnotationsEl.addEventListener("click", exportAnnotations);
importAnnotationsEl.addEventListener("click", () => annotationFileEl.click());
annotationFileEl.addEventListener("change", event => {{
  importAnnotationsFile(event.target.files?.[0]);
  annotationFileEl.value = "";
}});
highlightSelectionEl.addEventListener("click", () => createAnnotation("highlight"));
noteSelectionEl.addEventListener("click", () => createAnnotation("note"));
document.addEventListener("mouseup", () => setTimeout(showAnnotationPopover, 0));
document.addEventListener("keyup", event => {{
  if (event.key === "Escape") {{
    annotationPopoverEl.classList.remove("open");
    return;
  }}
  setTimeout(showAnnotationPopover, 0);
}});
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

loadLocalAnnotations();
renderAnnotationList();
renderSections();
renderCards();
</script>
</body>
</html>
"""
