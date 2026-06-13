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
html[data-theme="dark"] {{
  color-scheme: dark;
  --bg: #15130f;
  --bg-rgb: 21 19 15;
  --paper: #1e1a15;
  --paper-rgb: 30 26 21;
  --paper-soft: #25201a;
  --paper-soft-rgb: 37 32 26;
  --ink: #ece7dd;
  --ink-rgb: 236 231 221;
  --muted: #a59d8f;
  --muted-rgb: 165 157 143;
  --line: #38322b;
  --line-rgb: 56 50 43;
  --accent: var(--accent-strong);
  --accent-rgb: var(--accent-strong-rgb);
  --accent-soft: rgb(var(--accent-strong-rgb) / 0.18);
  --plum: var(--plum-strong);
  --plum-rgb: var(--plum-strong-rgb);
  --plum-soft: rgb(var(--plum-strong-rgb) / 0.20);
  --clay-soft: rgb(var(--clay-rgb) / 0.26);
  --mark-bg: rgb(var(--gold-rgb) / 0.32);
  --modal-bg: #15130f;
  --meter-bg: rgb(var(--line-rgb) / 0.9);
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
  transition: background-color 220ms ease, color 220ms ease;
}}
button, input, textarea {{ font: inherit; }}
button {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 40px;
  border: 1px solid rgb(var(--line-rgb) / 0.7);
  border-radius: 14px;
  background: var(--paper);
  color: var(--ink);
  font-weight: 500;
  letter-spacing: 0.01em;
  cursor: pointer;
  transition: border-color 140ms ease, background-color 140ms ease,
    color 140ms ease, box-shadow 140ms ease, transform 80ms ease;
}}
button:hover {{
  border-color: rgb(var(--accent-rgb) / 0.6);
}}
button:active {{ transform: translateY(1px); }}
button:focus-visible, input:focus-visible, textarea:focus-visible {{
  border-color: var(--accent);
  outline: 3px solid rgb(var(--accent-rgb) / 0.2);
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
.rail-top {{
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}}
.rail-tools {{
  display: inline-flex;
  flex-shrink: 0;
  gap: 6px;
}}
.icon-btn {{
  min-width: 38px;
  min-height: 38px;
  padding: 0;
  border-radius: 50%;
  border-color: rgb(var(--line-rgb) / 0.6);
  background: rgb(var(--paper-rgb) / 0.7);
  color: var(--muted);
  font-size: 16px;
  line-height: 1;
}}
.icon-btn:hover {{ background: var(--accent-soft); }}
.icon-btn:hover, .icon-btn:focus-visible {{
  color: var(--accent);
}}
.brand h1 {{
  margin: 0;
  font-family: var(--font-heading);
  font-size: 24px;
  line-height: 1.14;
  letter-spacing: 0;
}}
.brand p {{
  margin: 10px 0 0;
  color: var(--muted);
  font-size: 13.5px;
  line-height: 1.45;
}}
.search-wrap {{
  position: relative;
  margin: 18px 0 12px;
}}
.search-wrap svg {{
  position: absolute;
  top: 50%;
  left: 12px;
  width: 17px;
  height: 17px;
  transform: translateY(-50%);
  color: var(--muted);
  pointer-events: none;
}}
.search {{
  width: 100%;
  min-height: 46px;
  padding: 0 16px 0 40px;
  border: 1px solid rgb(var(--line-rgb) / 0.7);
  border-radius: 999px;
  background: var(--paper);
  color: var(--ink);
}}
.search-wrap svg {{ left: 15px; }}
.controls {{
  display: inline-flex;
  width: 100%;
  margin: 0 0 14px;
  border: 1px solid rgb(var(--line-rgb) / 0.7);
  border-radius: 999px;
  overflow: hidden;
  background: var(--paper);
}}
.controls button {{
  flex: 1;
  min-height: 44px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--muted);
  font-size: 13.5px;
}}
.controls button:first-child {{ border-right: 1px solid rgb(var(--line-rgb) / 0.6); }}
.controls button:hover {{
  color: var(--accent);
  background: var(--accent-soft);
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
  font-weight: 550;
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
  gap: 6px;
}}
.sections button {{
  width: 100%;
  justify-content: flex-start;
  min-height: 38px;
  padding: 8px 14px;
  border-color: transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--muted);
  font-weight: 500;
  text-align: left;
}}
.sections button:hover {{
  background: rgb(var(--paper-rgb) / 0.9);
  color: var(--ink);
}}
.sections button.active {{
  border-color: transparent;
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
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
  border: 1px solid rgb(var(--line-rgb) / 0.55);
  border-radius: var(--radius);
  background: rgb(var(--paper-rgb) / 0.94);
  box-shadow: 0 14px 36px rgb(var(--ink-rgb) / 0.045);
  overflow: hidden;
  transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}}
.card:hover {{
  border-color: rgb(var(--accent-rgb) / 0.38);
  box-shadow: 0 18px 44px rgb(var(--ink-rgb) / 0.07);
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
  border: 1px solid rgb(var(--plum-rgb) / 0.2);
  border-radius: 999px;
  background: var(--plum-soft);
  color: var(--plum);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
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
  font-weight: 550;
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
  min-height: 30px;
  padding: 0 13px;
  border-radius: 999px;
  border-color: rgb(var(--line-rgb) / 0.6);
  background: rgb(var(--paper-rgb) / 0.62);
  color: var(--muted);
  font-size: 12.5px;
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
  grid-template-columns: 1fr;
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
  overscroll-behavior: contain;
}}
.annotation-item {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-rows: auto auto;
  gap: 5px;
  width: 100%;
  height: auto;
  min-height: 0;
  padding: 8px;
  border: 1px solid rgb(var(--line-rgb) / 0.72);
  border-radius: 8px;
  background: rgb(var(--paper-rgb) / 0.74);
  text-align: left;
  overflow: hidden;
  cursor: pointer;
}}
.annotation-item:hover,
.annotation-item:focus-visible {{
  border-color: rgb(var(--accent-rgb) / 0.42);
  outline: 3px solid rgb(var(--accent-rgb) / 0.12);
  outline-offset: 1px;
}}
.annotation-item strong {{
  grid-column: 1;
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.2;
}}
.annotation-item span {{
  grid-column: 1 / -1;
  display: -webkit-box;
  min-width: 0;
  max-height: calc(1.3em * 3);
  overflow: hidden;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.3;
}}
.remove-annotation {{
  grid-column: 2;
  grid-row: 1;
  min-height: 26px;
  padding: 0 8px;
  border-color: rgb(var(--line-rgb) / 0.75);
  background: rgb(var(--paper-rgb) / 0.7);
  color: var(--muted);
  font-size: 12px;
}}
.remove-annotation:hover,
.remove-annotation:focus-visible {{
  color: var(--clay);
  background: var(--clay-soft);
  border-color: rgb(var(--clay-rgb) / 0.45);
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
.note-editor {{
  position: fixed;
  inset: 0;
  z-index: 40;
  display: none;
  place-items: center;
  padding: 18px;
  background: rgb(var(--ink-rgb) / 0.38);
}}
.note-editor.open {{
  display: grid;
}}
.note-editor-panel {{
  display: grid;
  gap: 10px;
  width: min(460px, 94vw);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--paper);
  box-shadow: 0 24px 70px rgb(var(--ink-rgb) / 0.24);
  padding: 14px;
}}
.note-editor-panel h2 {{
  margin: 0;
  font-family: var(--font-ui);
  font-size: 16px;
  line-height: 1.25;
  letter-spacing: 0;
}}
.note-editor-quote {{
  margin: 0;
  max-height: 90px;
  overflow: auto;
  padding: 8px 10px;
  border-left: 3px solid var(--accent);
  background: var(--accent-soft);
  color: var(--muted);
  font-size: 13px;
  line-height: 1.35;
}}
.note-editor textarea {{
  width: 100%;
  min-height: 130px;
  resize: vertical;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--paper);
  color: var(--ink);
  font: inherit;
  font-size: 14px;
  line-height: 1.4;
}}
.note-editor-actions {{
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}}
.note-editor-actions button {{
  min-height: 34px;
  padding: 0 12px;
  font-size: 13px;
}}
.top-progress {{
  position: fixed;
  inset: 0 0 auto 0;
  z-index: 25;
  height: 3px;
  background: transparent;
}}
.top-progress span {{
  display: block;
  width: 0;
  height: 100%;
  background: var(--accent);
  transition: width 120ms ease;
}}
.fab {{
  position: fixed;
  right: 22px;
  bottom: 22px;
  z-index: 15;
  width: 46px;
  height: 46px;
  padding: 0;
  border-radius: 50%;
  background: var(--accent);
  border-color: var(--accent);
  color: var(--paper);
  font-size: 20px;
  box-shadow: 0 10px 26px rgb(var(--ink-rgb) / 0.22);
  opacity: 0;
  transform: translateY(12px);
  pointer-events: none;
  transition: opacity 180ms ease, transform 180ms ease, background-color 140ms ease;
}}
.fab.show {{
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}}
.fab:hover {{ background: var(--accent-strong); }}
.toast-stack {{
  position: fixed;
  left: 50%;
  bottom: 26px;
  z-index: 50;
  display: grid;
  gap: 8px;
  transform: translateX(-50%);
  pointer-events: none;
}}
.toast {{
  padding: 10px 16px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--ink);
  color: var(--paper);
  font-size: 13.5px;
  font-weight: 600;
  box-shadow: 0 12px 30px rgb(var(--ink-rgb) / 0.28);
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 200ms ease, transform 200ms ease;
}}
.toast.show {{ opacity: 1; transform: translateY(0); }}
.shortcuts {{
  margin: 0;
  display: grid;
  gap: 10px;
  padding: 18px;
}}
.shortcuts div {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  color: var(--ink);
  font-size: 14px;
}}
.shortcuts kbd {{
  padding: 3px 9px;
  border: 1px solid var(--line);
  border-bottom-width: 2px;
  border-radius: 7px;
  background: var(--paper-soft);
  color: var(--muted);
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 700;
}}
.modal-panel.compact {{
  width: min(420px, 94vw);
  max-height: none;
  grid-template-rows: auto auto;
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
<div class="top-progress" aria-hidden="true"><span id="topProgress"></span></div>
<div class="shell">
  <aside class="rail">
    <div class="rail-top">
      <div class="brand">
        <h1>{title}</h1>
        <p><span id="totalCards">0</span> cards · <span id="totalTables">0</span> tables · <span id="totalFigures">0</span> figures · <span id="totalFormulas">0</span> formulas</p>
      </div>
      <div class="rail-tools">
        <button id="themeToggle" class="icon-btn" type="button" aria-label="Toggle dark mode" title="Toggle theme">🌙</button>
        <button id="helpToggle" class="icon-btn" type="button" aria-label="Keyboard shortcuts" title="Keyboard shortcuts">?</button>
      </div>
    </div>
    <div class="search-wrap">
      <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="9" cy="9" r="6" stroke="currentColor" stroke-width="2"/><path d="m14 14 4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
      <input id="search" class="search" type="search" placeholder="Search the document" aria-label="Search the document">
    </div>
    <div class="controls">
      <button id="prevBtn" type="button">← Previous</button>
      <button id="nextBtn" type="button">Next →</button>
    </div>
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
      <p id="annotationCountLine" class="annotation-count"><span id="annotationCount">0</span> saved</p>
      <div id="annotationButtons" class="annotation-buttons">
        <button id="exportAnnotations" type="button">Export Markdown</button>
      </div>
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
<button id="scrollTop" class="fab" type="button" aria-label="Back to top" title="Back to top">↑</button>
<div id="toastStack" class="toast-stack" aria-live="polite" aria-atomic="false"></div>
<div id="helpModal" class="modal" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">
  <div class="modal-panel compact">
    <div class="modal-head">
      <strong>Keyboard shortcuts</strong>
      <button id="closeHelp" type="button">Close</button>
    </div>
    <div class="shortcuts">
      <div><span>Next card</span><kbd>→</kbd></div>
      <div><span>Previous card</span><kbd>←</kbd></div>
      <div><span>Search</span><kbd>/</kbd></div>
      <div><span>Toggle theme</span><kbd>T</kbd></div>
      <div><span>Save note</span><kbd>⌘ / Ctrl + ⏎</kbd></div>
      <div><span>Close dialog</span><kbd>Esc</kbd></div>
    </div>
  </div>
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
<div id="noteEditor" class="note-editor" role="dialog" aria-modal="true" aria-labelledby="noteEditorTitle">
  <div class="note-editor-panel">
    <h2 id="noteEditorTitle">Add note</h2>
    <p id="noteEditorQuote" class="note-editor-quote"></p>
    <label for="noteEditorText">Your note</label>
    <textarea id="noteEditorText" placeholder="Type your note"></textarea>
    <div class="note-editor-actions">
      <button id="cancelNote" type="button">Cancel</button>
      <button id="saveNote" type="button">Save note</button>
    </div>
  </div>
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
const annotationButtonsEl = document.getElementById("annotationButtons");
const annotationListEl = document.getElementById("annotationList");
const exportAnnotationsEl = document.getElementById("exportAnnotations");
const annotationPopoverEl = document.getElementById("annotationPopover");
const highlightSelectionEl = document.getElementById("highlightSelection");
const noteSelectionEl = document.getElementById("noteSelection");
const noteEditorEl = document.getElementById("noteEditor");
const noteEditorQuoteEl = document.getElementById("noteEditorQuote");
const noteEditorTextEl = document.getElementById("noteEditorText");
const saveNoteEl = document.getElementById("saveNote");
const cancelNoteEl = document.getElementById("cancelNote");
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

function removeAnnotation(annotationId) {{
  if (annotationReadOnly) return;
  annotations = annotations.filter(item => item.id !== annotationId);
  saveLocalAnnotations();
  renderAnnotationList();
  renderCards();
  showToast("Annotation removed");
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
  if (noteEditorEl.classList.contains("open")) return;
  pendingSelection = selectionWithinAnnotatable();
  if (!pendingSelection) {{
    annotationPopoverEl.classList.remove("open");
    return;
  }}
  annotationPopoverEl.style.left = `${{Math.max(12, pendingSelection.rect.left)}}px`;
  annotationPopoverEl.style.top = `${{Math.max(12, pendingSelection.rect.top - 48)}}px`;
  annotationPopoverEl.classList.add("open");
}}

function createAnnotation(kind, note = "") {{
  if (!pendingSelection) return;
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
    note: note || "",
    tags: [],
    visibility: "private",
    created_at: now,
    updated_at: now,
  }};
  mergeAnnotations([annotation]);
  window.getSelection()?.removeAllRanges();
  annotationPopoverEl.classList.remove("open");
  closeNoteEditor();
  renderCards();
  showToast(kind === "note" ? "Note saved" : "Highlight saved");
}}

function beginNoteAnnotation() {{
  if (!pendingSelection) return;
  annotationPopoverEl.classList.remove("open");
  noteEditorQuoteEl.textContent = pendingSelection.quote;
  noteEditorTextEl.value = "";
  noteEditorEl.classList.add("open");
  noteEditorTextEl.focus();
}}

function saveNoteAnnotation() {{
  const note = noteEditorTextEl.value.trim();
  if (!note) {{
    noteEditorTextEl.focus();
    return;
  }}
  createAnnotation("note", note);
}}

function closeNoteEditor() {{
  noteEditorEl.classList.remove("open");
}}

function renderAnnotationList() {{
  const countLine = document.getElementById("annotationCountLine");
  if (!annotations.length) {{
    countLine.textContent = annotationReadOnly
      ? "No annotations."
      : "Select text to highlight or add a note.";
  }} else {{
    countLine.innerHTML = `<span id="annotationCount">${{annotations.length}}</span> saved`;
  }}
  annotationButtonsEl.style.display = annotationReadOnly || !annotations.length ? "none" : "grid";
  annotationListEl.innerHTML = "";
  const visible = annotations.slice(0, 30);
  for (const annotation of visible) {{
    const item = document.createElement("div");
    item.className = "annotation-item";
    item.role = "button";
    item.tabIndex = 0;
    const label = annotation.kind === "note" ? "Note" : "Highlight";
    const quote = annotation.note || annotation.text_quote || "Annotation";
    const removeButton = annotationReadOnly
      ? ""
      : `<button class="remove-annotation" type="button" data-remove-annotation="${{escapeHtml(annotation.id)}}">Remove</button>`;
    item.innerHTML = `<strong>${{escapeHtml(label)}} · Page ${{escapeHtml(annotation.page || "")}}</strong>${{removeButton}}<span>${{escapeHtml(quote.slice(0, 120))}}</span>`;
    const jumpToAnnotation = () => {{
      const index = filtered.findIndex(card => card.id === annotation.card_id);
      if (index >= 0) scrollToIndex(index);
    }};
    item.addEventListener("click", jumpToAnnotation);
    item.addEventListener("keydown", event => {{
      if (event.key === "Enter" || event.key === " ") {{
        event.preventDefault();
        jumpToAnnotation();
      }}
    }});
    const remove = item.querySelector("[data-remove-annotation]");
    if (remove) {{
      remove.addEventListener("click", event => {{
        event.stopPropagation();
        removeAnnotation(annotation.id);
      }});
    }}
    annotationListEl.appendChild(item);
  }}
}}

function exportAnnotations() {{
  const blob = new Blob([annotationsToMarkdown()], {{
    type: "text/markdown",
  }});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${{documentId}}.annotations.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  showToast(annotations.length ? "Markdown exported" : "Nothing to export yet");
}}

function markdownEscape(value) {{
  return String(value || "").replaceAll("\\r\\n", "\\n").trim();
}}

function annotationsToMarkdown() {{
  const lines = [
    `# ${{markdownEscape(payload.title || "PDF Card Reader")}}`,
    "",
    `Exported: ${{new Date().toISOString()}}`,
    `Document ID: ${{documentId}}`,
    "",
  ];
  const sorted = [...annotations].sort((a, b) => {{
    const pageDiff = Number(a.page || 0) - Number(b.page || 0);
    if (pageDiff) return pageDiff;
    return String(a.card_id).localeCompare(String(b.card_id));
  }});
  if (!sorted.length) {{
    lines.push("_No notes or highlights saved._", "");
    return lines.join("\\n");
  }}
  let currentPage = null;
  for (const annotation of sorted) {{
    const page = annotation.page || "Unknown";
    if (page !== currentPage) {{
      currentPage = page;
      lines.push(`## Page ${{page}}`, "");
    }}
    const label = annotation.kind === "note" ? "Note" : "Highlight";
    lines.push(`### ${{label}}`);
    if (annotation.text_quote) {{
      lines.push("", "> " + markdownEscape(annotation.text_quote).replaceAll("\\n", "\\n> "));
    }}
    if (annotation.kind === "note") {{
      lines.push("", markdownEscape(annotation.note || "_No note text._"));
    }}
    lines.push("", `Source: ${{annotation.card_id}}`, "");
  }}
  return lines.join("\\n");
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
annotationPopoverEl.addEventListener("mousedown", event => event.preventDefault());
annotationPopoverEl.addEventListener("mouseup", event => event.stopPropagation());
highlightSelectionEl.addEventListener("click", () => createAnnotation("highlight"));
noteSelectionEl.addEventListener("click", beginNoteAnnotation);
saveNoteEl.addEventListener("click", saveNoteAnnotation);
cancelNoteEl.addEventListener("click", closeNoteEditor);
noteEditorEl.addEventListener("click", event => {{
  if (event.target === noteEditorEl) closeNoteEditor();
}});
noteEditorTextEl.addEventListener("keydown", event => {{
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") saveNoteAnnotation();
}});
document.addEventListener("mouseup", () => setTimeout(showAnnotationPopover, 0));
document.addEventListener("keyup", event => {{
  if (event.key === "Escape") {{
    annotationPopoverEl.classList.remove("open");
    closeNoteEditor();
    return;
  }}
  setTimeout(showAnnotationPopover, 0);
}});
document.addEventListener("keydown", event => {{
  if (event.key === "Escape" && modalEl.classList.contains("open")) closeSource();
  if (event.key === "Escape" && noteEditorEl.classList.contains("open")) closeNoteEditor();
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

// --- Toast notifications -------------------------------------------------
const toastStackEl = document.getElementById("toastStack");
function showToast(message) {{
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  toastStackEl.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("show"));
  setTimeout(() => {{
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 240);
  }}, 2200);
}}

// --- Theme toggle --------------------------------------------------------
const themeToggleEl = document.getElementById("themeToggle");
function applyTheme(theme) {{
  const dark = theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  themeToggleEl.textContent = dark ? "☀️" : "🌙";
  themeToggleEl.title = dark ? "Switch to light" : "Switch to dark";
}}
function toggleTheme() {{
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  try {{ localStorage.setItem("pdf-card-reader-theme", next); }} catch (_) {{}}
  showToast(next === "dark" ? "Dark theme" : "Light theme");
}}
(function initTheme() {{
  let stored = null;
  try {{ stored = localStorage.getItem("pdf-card-reader-theme"); }} catch (_) {{}}
  if (!stored && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {{
    stored = "dark";
  }}
  applyTheme(stored === "dark" ? "dark" : "light");
}})();
themeToggleEl.addEventListener("click", toggleTheme);

// --- Help / keyboard shortcuts ------------------------------------------
const helpModalEl = document.getElementById("helpModal");
document.getElementById("helpToggle").addEventListener("click", () => helpModalEl.classList.add("open"));
document.getElementById("closeHelp").addEventListener("click", () => helpModalEl.classList.remove("open"));
helpModalEl.addEventListener("click", event => {{
  if (event.target === helpModalEl) helpModalEl.classList.remove("open");
}});

// --- Reading progress + back to top -------------------------------------
const topProgressEl = document.getElementById("topProgress");
const scrollTopEl = document.getElementById("scrollTop");
function updateScrollUi() {{
  const doc = document.documentElement;
  const max = doc.scrollHeight - doc.clientHeight;
  const ratio = max > 0 ? Math.min(1, doc.scrollTop / max) : 0;
  topProgressEl.style.width = `${{ratio * 100}}%`;
  scrollTopEl.classList.toggle("show", doc.scrollTop > 600);
}}
window.addEventListener("scroll", updateScrollUi, {{ passive: true }});
window.addEventListener("resize", updateScrollUi, {{ passive: true }});
scrollTopEl.addEventListener("click", () => window.scrollTo({{ top: 0, behavior: "smooth" }}));

// --- Global shortcuts ----------------------------------------------------
document.addEventListener("keydown", event => {{
  const typing = ["INPUT", "TEXTAREA"].includes(event.target.tagName);
  if (event.key === "Escape") helpModalEl.classList.remove("open");
  if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key === "/") {{
    event.preventDefault();
    searchEl.focus();
    searchEl.select();
  }} else if (event.key === "t" || event.key === "T") {{
    toggleTheme();
  }}
}});

loadLocalAnnotations();
renderAnnotationList();
renderSections();
renderCards();
updateScrollUi();
</script>
</body>
</html>
"""
