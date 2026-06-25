from __future__ import annotations

import base64
import io
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

import pdfplumber
from PIL import Image

from .html_renderer import render_html
from .models import BBox, Card, ConversionManifest, ImageAsset
from .pdf_backend import PageRect, PdfTocEntry, PdfiumDocument, PdfiumPage
from .style import collect_font_summary, extract_style_hints, reader_style_from_hints, soft_reader_style


@dataclass(slots=True)
class ConversionOptions:
    pdf_path: Path
    output_path: Path | None = None
    title: str | None = None
    standalone: bool = True
    ocr: bool = False
    max_pages: int | None = None
    theme: str = "soft"
    style_engine: str = "pdf"
    table_engine: str = "auto"
    text_engine: str = "char_geometry"
    model_cache_dir: Path | None = None
    offline: bool = False
    page_scale: float = 1.8
    crop_scale: float = 2.8
    max_words_per_card: int = 95


@dataclass(slots=True)
class ConversionResult:
    html_path: Path
    manifest_path: Path
    page_count: int
    card_count: int
    table_count: int
    figure_count: int
    formula_count: int
    warnings: list[str] = field(default_factory=list)
    style_engine: str = "pdf"

    def to_dict(self) -> dict[str, Any]:
        return {
            "html_path": str(self.html_path),
            "manifest_path": str(self.manifest_path),
            "page_count": self.page_count,
            "card_count": self.card_count,
            "table_count": self.table_count,
            "figure_count": self.figure_count,
            "formula_count": self.formula_count,
            "warnings": self.warnings,
            "style_engine": self.style_engine,
        }


@dataclass(slots=True)
class TextBlock:
    page: int
    bbox: BBox
    text: str
    kind: str = "text"
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class TableCandidate:
    bbox: BBox
    source: str = "pdfplumber"
    confidence: float = 1.0
    cell_count: int | None = None
    non_empty_cells: int | None = None


def convert_pdf_to_card_html(
    pdf_path: str | Path,
    output_path: str | Path | None = None,
    title: str | None = None,
    standalone: bool = True,
    ocr: bool = False,
    max_pages: int | None = None,
    theme: str = "soft",
    style_engine: str = "pdf",
    table_engine: str = "auto",
    text_engine: str = "char_geometry",
    model_cache_dir: str | Path | None = None,
    offline: bool = False,
) -> ConversionResult:
    """Convert a PDF into a card-based HTML reader and return output metadata."""
    options = ConversionOptions(
        pdf_path=Path(pdf_path).expanduser(),
        output_path=Path(output_path).expanduser() if output_path else None,
        title=title,
        standalone=standalone,
        ocr=ocr,
        max_pages=max_pages,
        theme=theme,
        style_engine=style_engine,
        table_engine=table_engine,
        text_engine=text_engine,
        model_cache_dir=Path(model_cache_dir).expanduser() if model_cache_dir else None,
        offline=offline,
    )
    return PdfCardConverter(options).convert()


class PdfCardConverter:
    def __init__(self, options: ConversionOptions) -> None:
        self.options = options
        self.warnings: list[str] = []
        self.assets: list[ImageAsset] = []
        self.cards: list[Card] = []
        self._card_number = 0
        self._asset_ids: set[str] = set()
        self._ligature_repair_pages: set[int] = set()
        self._toc_targets_by_title: dict[str, PdfTocEntry] = {}
        self._repeating_top_keys: frozenset[str] = frozenset()
        self._repeating_bottom_keys: frozenset[str] = frozenset()
        self._page_lines_cache: dict[int, list[dict[str, Any]]] = {}

    def convert(self) -> ConversionResult:
        pdf_path = self.options.pdf_path
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF does not exist: {pdf_path}")
        if pdf_path.suffix.lower() != ".pdf":
            raise ValueError(f"Input must be a PDF: {pdf_path}")
        if not self.options.standalone:
            self.warnings.append("Asset-folder output is not implemented yet; wrote standalone HTML.")
        if self.options.table_engine not in {"auto", "pdfplumber", "gmft"}:
            raise ValueError("table_engine must be one of: auto, pdfplumber, gmft")
        if self.options.text_engine not in {"char_geometry", "pdfplumber_words"}:
            raise ValueError("text_engine must be one of: char_geometry, pdfplumber_words")
        if self.options.style_engine not in {"fixed", "pdf"}:
            raise ValueError("style_engine must be one of: fixed, pdf")

        output_path = self._default_output_path(pdf_path)
        manifest_path = output_path.with_suffix(".manifest.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with PdfiumDocument(pdf_path) as document, pdfplumber.open(pdf_path) as plumber_pdf:
            page_count = len(document)
            processed_pages = min(page_count, self.options.max_pages or page_count)
            title = self._title(plumber_pdf)
            self._toc_targets_by_title = toc_targets_by_title(document.toc_entries())
            self._repeating_top_keys, self._repeating_bottom_keys = (
                self._detect_repeating_margins(plumber_pdf, processed_pages)
            )
            gmft_tables = self._detect_gmft_tables(processed_pages)
            for index in range(processed_pages):
                page_number = index + 1
                pdf_page = document[index]
                plumber_page = plumber_pdf.pages[index]
                source_asset = self._render_source_page(pdf_page, page_number)
                self.assets.append(source_asset)
                page_card_start = len(self.cards)

                table_regions = self._extract_tables(
                    pdf_page,
                    plumber_page,
                    page_number,
                    gmft_tables.get(page_number, []),
                )
                figure_regions = self._extract_figures(
                    pdf_page,
                    plumber_page,
                    page_number,
                    table_regions,
                )
                suppressed_regions = [*table_regions, *figure_regions]

                text_blocks = self._extract_text_blocks(
                    pdf_page,
                    plumber_page,
                    page_number,
                    suppressed_regions,
                    title,
                )
                if not text_blocks and self.options.ocr:
                    text_blocks = self._ocr_page(source_asset, page_number)
                for block in text_blocks:
                    self._append_text_cards(block, source_asset.id, pdf_page)
                self._reorder_recent_page_cards(
                    start_index=page_card_start,
                    page_number=page_number,
                    page_width=float(pdf_page.rect.width),
                )

            self.cards = smooth_reader_cards(self.cards, self.options.max_words_per_card)
            page_widths = {
                asset.page: asset.width / self.options.page_scale
                for asset in self.assets
                if asset.kind == "source_page" and asset.page is not None and asset.width
            }
            self.cards = sanitize_cross_column_card_bboxes(self.cards, page_widths)

            if not self.cards:
                warning = "No readable cards were produced from this PDF."
                if not self.options.ocr:
                    warning += (
                        " If this is a scanned or image-only document, install the OCR extra "
                        "and rerun with ocr=true."
                    )
                self.warnings.append(warning)

            if not any(asset.kind == "table" for asset in self.assets):
                if self._pdf_mentions_tables(plumber_pdf, processed_pages):
                    self.warnings.append(
                        "The PDF mentions tables, but no reliable table regions were detected."
                    )

            if self.options.style_engine == "pdf":
                style_hints = extract_style_hints(
                    self.assets,
                    self.cards,
                    font_summary=collect_font_summary(plumber_pdf.pages[:processed_pages]),
                )
                reader_style = reader_style_from_hints(style_hints)
            else:
                style_hints = None
                reader_style = soft_reader_style()

            manifest = ConversionManifest(
                title=title,
                source_pdf=pdf_path,
                page_count=page_count,
                processed_pages=processed_pages,
                cards=self.cards,
                assets=self.assets,
                warnings=self.warnings,
                theme=self.options.theme,
                style_engine=self.options.style_engine,
                style_hints=style_hints,
                style=reader_style,
            )

        output_path.write_text(render_html(manifest), encoding="utf-8")
        manifest_path.write_text(
            json.dumps(manifest.to_dict(include_data=False), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return ConversionResult(
            html_path=output_path,
            manifest_path=manifest_path,
            page_count=manifest.page_count,
            card_count=manifest.card_count,
            table_count=manifest.table_count,
            figure_count=manifest.figure_count,
            formula_count=manifest.formula_count,
            warnings=manifest.warnings,
            style_engine=manifest.style_engine,
        )

    def _default_output_path(self, pdf_path: Path) -> Path:
        if self.options.output_path:
            return self.options.output_path
        return pdf_path.with_name(f"{slugify(pdf_path.stem)}_card_reader.html")

    def _title(self, plumber_pdf: pdfplumber.PDF) -> str:
        if self.options.title:
            return self.options.title.strip()
        visual_title = infer_visual_title_from_first_page(plumber_pdf.pages[0]) if plumber_pdf.pages else None
        metadata_title = (plumber_pdf.metadata or {}).get("Title") or ""
        metadata_title = normalize_text(metadata_title)
        if visual_title:
            if not usable_metadata_title(metadata_title):
                return visual_title
            if len(normalized_key(visual_title)) > len(normalized_key(metadata_title)) * 1.18:
                return visual_title
        if usable_metadata_title(metadata_title):
            return normalize_text(metadata_title)
        if plumber_pdf.pages:
            text = plumber_pdf.pages[0].extract_text() or ""
            for line in text.splitlines():
                cleaned = normalize_text(line)
                if cleaned and len(cleaned) > 5 and not looks_like_title_noise(cleaned):
                    return cleaned[:180]
        return self.options.pdf_path.stem.replace("_", " ").replace("-", " ").title()

    def _render_source_page(self, page: PdfiumPage, page_number: int) -> ImageAsset:
        data, width, height = page.render_page_png(self.options.page_scale)
        return ImageAsset(
            id=f"source-page-{page_number}",
            kind="source_page",
            page=page_number,
            alt=f"Source page {page_number}",
            caption="",
            data_uri=png_data_uri(data),
            width=width,
            height=height,
            bbox=None,
        )

    def _detect_gmft_tables(self, processed_pages: int) -> dict[int, list[BBox]]:
        if self.options.table_engine == "pdfplumber":
            return {}

        if self.options.model_cache_dir:
            cache_dir = str(self.options.model_cache_dir)
            os.environ.setdefault("HF_HOME", cache_dir)
            os.environ.setdefault("TRANSFORMERS_CACHE", cache_dir)
        if self.options.offline:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        try:
            from gmft.auto import AutoTableDetector
            from gmft.pdf_bindings import PyPDFium2Document
        except Exception as error:
            if self.options.table_engine == "gmft":
                self.warnings.append(f"gmft table engine requested but unavailable: {error}")
            return {}

        tables_by_page: dict[int, list[BBox]] = {}
        detector = AutoTableDetector()
        document = None
        try:
            document = PyPDFium2Document(str(self.options.pdf_path))
            for page_index, page in enumerate(document):
                if page_index >= processed_pages:
                    break
                page_number = page_index + 1
                for table in detector.extract(page):
                    bbox = normalize_gmft_bbox(getattr(table, "bbox", None))
                    if bbox is not None:
                        tables_by_page.setdefault(page_number, []).append(bbox)
        except Exception as error:
            self.warnings.append(f"gmft table detection failed: {error}")
        finally:
            if document is not None:
                try:
                    document.close()
                except Exception:
                    pass
        return tables_by_page

    def _extract_tables(
        self,
        pdf_page: PdfiumPage,
        plumber_page: pdfplumber.page.Page,
        page_number: int,
        gmft_bboxes: list[BBox],
    ) -> list[BBox]:
        table_regions: list[BBox] = []
        try:
            plumber_tables = plumber_page.find_tables()
        except Exception as error:
            self.warnings.append(f"Page {page_number}: table detection failed: {error}")
            plumber_tables = []

        words = extract_words(plumber_page)
        tables: list[TableCandidate] = []
        for table in plumber_tables:
            if caption_near_bbox(words, table.bbox, "Figure"):
                continue
            tables.append(plumber_table_candidate(table))
        for bbox in gmft_bboxes:
            if caption_near_bbox(words, bbox, "Figure"):
                continue
            if any(overlap_ratio(bbox, candidate.bbox) > 0.72 for candidate in tables):
                continue
            tables.append(TableCandidate(bbox, source="gmft"))
        caption_lines = find_caption_lines_for_page(plumber_page, "Table")
        consumed_table_indexes: set[int] = set()

        caption_bboxes = [caption["bbox"] for caption in caption_lines]
        for caption_index, caption in enumerate(caption_lines, start=1):
            near_indexes = nearby_table_indexes(caption_index - 1, caption_bboxes, tables)
            consumed_table_indexes.update(near_indexes)
            caption_anchor_bbox = (
                tuple(float(value) for value in caption["line_bbox"])
                if embedded_table_caption_has_row_prefix(caption) and caption.get("line_bbox") is not None
                else caption["bbox"]
            )
            plumber_bbox = (
                union_bboxes([tables[index].bbox for index in near_indexes])
                if near_indexes
                else None
            )
            heuristic_bbox = heuristic_table_bbox(
                caption_anchor_bbox,
                plumber_page,
                words,
                caption_text=str(caption.get("text", "")),
            )
            if plumber_bbox is not None and heuristic_bbox is not None:
                plumber_bbox = merge_plumber_and_heuristic_table_bboxes(
                    plumber_bbox,
                    heuristic_bbox,
                    plumber_page,
                )
            if len(near_indexes) == 0:
                if heuristic_bbox is None:
                    self.warnings.append(
                        f"Page {page_number}: found table caption but could not infer crop: "
                        f"{caption['text'][:80]}"
                    )
                    continue
                plumber_bbox = heuristic_bbox
                self.warnings.append(
                    f"Page {page_number}: used heuristic crop for table caption "
                    f"'{caption['text'][:80]}'."
                )
            if plumber_bbox is None:
                continue
            if embedded_table_caption_has_row_prefix(caption):
                source_line_bbox = caption.get("line_bbox")
                if source_line_bbox is not None:
                    plumber_bbox = union_bboxes(
                        [plumber_bbox, tuple(float(value) for value in source_line_bbox)]
                    )

            bbox = self._scale_plumber_bbox(plumber_bbox, plumber_page, pdf_page)
            caption_region = self._scale_plumber_bbox(caption["bbox"], plumber_page, pdf_page)
            if embedded_table_caption_has_row_prefix(caption) and caption.get("line_bbox") is not None:
                caption_region = self._scale_plumber_bbox(
                    tuple(float(value) for value in caption["line_bbox"]),
                    plumber_page,
                    pdf_page,
                )
            caption_text = caption["text"]
            local_caption = local_caption_for_visual(
                words,
                prefix="Table",
                caption_bbox=caption["bbox"],
                fallback_text=caption["text"],
                visual_bbox=bbox,
                plumber_page=plumber_page,
                pdf_page=pdf_page,
            )
            if local_caption is not None:
                caption_text, local_caption_bbox = local_caption
                caption_region = self._scale_plumber_bbox(local_caption_bbox, plumber_page, pdf_page)
            if embedded_table_caption_has_row_prefix(caption) and caption.get("line_bbox") is not None:
                caption_region = self._scale_plumber_bbox(
                    tuple(float(value) for value in caption["line_bbox"]),
                    plumber_page,
                    pdf_page,
                )
            suppression_bbox = union_bboxes([caption_region, bbox])
            if any(overlap_ratio(bbox, region) > 0.65 for region in table_regions):
                continue
            if not valid_bbox(bbox, pdf_page.rect):
                self.warnings.append(f"Page {page_number}: skipped invalid table bbox {plumber_bbox}.")
                continue
            table_regions.append(suppression_bbox)
            self._append_cropped_asset_card(
                pdf_page=pdf_page,
                page_number=page_number,
                kind="table",
                bbox=bbox,
                caption=caption_text,
                fallback_label=f"Table {caption_index} on page {page_number}",
            )

        for table_index, table in enumerate(tables):
            if table_index in consumed_table_indexes:
                continue
            if caption_near_bbox(words, table.bbox, "Figure"):
                continue
            if not substantial_table_bbox(table.bbox, plumber_page):
                continue
            if not useful_uncaptioned_table_candidate(table, plumber_page, words, page_number):
                continue
            bbox = self._scale_plumber_bbox(table.bbox, plumber_page, pdf_page)
            if any(overlap_ratio(bbox, region) > 0.35 for region in table_regions):
                continue
            if not valid_bbox(bbox, pdf_page.rect):
                continue
            table_regions.append(bbox)
            self._append_cropped_asset_card(
                pdf_page=pdf_page,
                page_number=page_number,
                kind="table",
                bbox=bbox,
                caption=f"Table on page {page_number}",
                fallback_label=f"Table {table_index + 1} on page {page_number}",
            )

        prompt_blocks = detect_uncaptioned_prompt_blocks(plumber_page, words)
        for prompt_index, prompt_block in enumerate(prompt_blocks, start=1):
            plumber_bbox = tuple(float(value) for value in prompt_block["bbox"])
            bbox = self._scale_plumber_bbox(plumber_bbox, plumber_page, pdf_page)
            if any(bboxes_substantially_overlap(bbox, region, threshold=0.35) for region in table_regions):
                continue
            if not valid_bbox(bbox, pdf_page.rect):
                continue
            table_regions.append(bbox)
            self.warnings.append(
                f"Page {page_number}: used heuristic crop for uncaptioned prompt block."
            )
            self._append_cropped_asset_card(
                pdf_page=pdf_page,
                page_number=page_number,
                kind="table",
                bbox=bbox,
                caption=prompt_block.get("caption") or f"Prompt block on page {page_number}",
                fallback_label=f"Prompt block {prompt_index} on page {page_number}",
            )

        return table_regions

    def _extract_figures(
        self,
        pdf_page: PdfiumPage,
        plumber_page: pdfplumber.page.Page,
        page_number: int,
        table_regions: list[BBox],
    ) -> list[BBox]:
        figure_regions: list[BBox] = []
        words = extract_words(plumber_page)
        figure_captions = find_caption_lines_for_page(plumber_page, "Figure")
        raw_image_bboxes = [
            bbox
            for raw_bbox in pdf_page.visual_bboxes()
            if (bbox := normalize_detected_visual_bbox(raw_bbox, pdf_page.rect)) is not None
        ]
        image_bboxes = [
            bbox
            for bbox in raw_image_bboxes
            if self._useful_image_bbox(bbox, pdf_page.rect, table_regions)
        ]
        caption_bboxes = [caption["bbox"] for caption in figure_captions]
        consumed_image_indexes: set[int] = set()

        for caption_index, caption in enumerate(figure_captions, start=1):
            near_indexes = nearby_bbox_indexes(caption_index - 1, caption_bboxes, image_bboxes)
            consumed_image_indexes.update(near_indexes)
            caption_region = self._scale_plumber_bbox(caption["bbox"], plumber_page, pdf_page)
            candidate_boxes = [image_bboxes[index] for index in near_indexes]
            if candidate_boxes and caption_region[1] > float(pdf_page.rect.height) * 0.55:
                heuristic_bbox = heuristic_figure_bbox(caption["bbox"], plumber_page, pdf_page, words)
                if (
                    heuristic_bbox is not None
                    and heuristic_bbox[1] < union_bboxes(candidate_boxes)[1] - 48.0
                    and caption_region[1] - heuristic_bbox[1] <= float(pdf_page.rect.height) * 0.78
                ):
                    candidate_boxes.append(heuristic_bbox)
            if len(near_indexes) == 0:
                heuristic_bbox = heuristic_figure_bbox(caption["bbox"], plumber_page, pdf_page, words)
                if heuristic_bbox is None:
                    self.warnings.append(
                        f"Page {page_number}: found figure caption but could not infer crop: "
                        f"{caption['text'][:80]}"
                    )
                    continue
                candidate_boxes.append(heuristic_bbox)
            if caption.get("embedded"):
                caption_region = self._scale_plumber_bbox(caption["bbox"], plumber_page, pdf_page)
                raw_near_indexes = nearby_bbox_indexes(
                    caption_index - 1,
                    caption_bboxes,
                    raw_image_bboxes,
                )
                raw_candidate_boxes = [raw_image_bboxes[index] for index in raw_near_indexes]
                column_boxes = [
                    box
                    for box in [*raw_candidate_boxes, *candidate_boxes]
                    if embedded_caption_visual_candidate(box, caption_region, pdf_page.rect)
                ]
                if column_boxes:
                    candidate_boxes = column_boxes

            bbox = union_bboxes(candidate_boxes)
            bbox = trim_bbox_away_from_caption(bbox, caption_region, minimum_gap=7.0)
            search_band = figure_search_band(caption_region, pdf_page.rect)
            label_boxes = nearby_graphic_text_bboxes(
                words,
                bbox,
                search_band,
                caption_region=caption_region,
            )
            if label_boxes:
                bbox = union_bboxes([bbox, *label_boxes])
            bbox = trim_bbox_around_blockers(bbox, table_regions, caption_region)
            caption_text = caption["text"]
            local_caption = local_caption_for_visual(
                words,
                prefix="Figure",
                caption_bbox=caption["bbox"],
                fallback_text=caption["text"],
                visual_bbox=bbox,
                plumber_page=plumber_page,
                pdf_page=pdf_page,
            )
            if local_caption is not None:
                caption_text, local_caption_bbox = local_caption
                caption_region = self._scale_plumber_bbox(local_caption_bbox, plumber_page, pdf_page)
            bbox = trim_bbox_away_from_caption(bbox, caption_region, minimum_gap=7.0)
            if not valid_bbox(bbox, pdf_page.rect):
                self.warnings.append(f"Page {page_number}: skipped invalid figure bbox {bbox}.")
                continue
            suppression_bbox = union_bboxes([caption_region, bbox])
            if any(bboxes_substantially_overlap(bbox, region, threshold=0.65) for region in figure_regions):
                continue
            figure_regions.append(suppression_bbox)
            self._append_cropped_asset_card(
                pdf_page=pdf_page,
                page_number=page_number,
                kind="figure",
                bbox=bbox,
                caption=caption_text,
                fallback_label=f"Figure {caption_index} on page {page_number}",
            )

        for image_index, bbox in enumerate(image_bboxes, start=1):
            if image_index - 1 in consumed_image_indexes:
                continue
            if not self._useful_image_bbox(bbox, pdf_page.rect, table_regions):
                continue
            if any(bboxes_substantially_overlap(bbox, region, threshold=0.35) for region in figure_regions):
                continue
            caption = caption_near_bbox(words, bbox, "Figure")
            if not caption:
                continue
            figure_regions.append(bbox)
            self._append_cropped_asset_card(
                pdf_page=pdf_page,
                page_number=page_number,
                kind="figure",
                bbox=bbox,
                caption=caption,
                fallback_label=f"Figure {image_index} on page {page_number}",
            )
        return figure_regions

    def _page_reading_lines(
        self, plumber_page: pdfplumber.page.Page, page_number: int
    ) -> list[dict[str, Any]]:
        cached = self._page_lines_cache.get(page_number)
        if cached is not None:
            return cached
        if self.options.text_engine == "pdfplumber_words":
            lines = split_words_into_reading_order_segments(
                extract_words(plumber_page),
                float(plumber_page.width),
            )
        else:
            lines = split_chars_into_reading_order_segments(
                plumber_page.chars,
                float(plumber_page.width),
                float(plumber_page.height),
            )
            if not lines:
                lines = split_words_into_reading_order_segments(
                    extract_words(plumber_page),
                    float(plumber_page.width),
                )
        self._page_lines_cache[page_number] = lines
        return lines

    def _detect_repeating_margins(
        self, plumber_pdf: pdfplumber.PDF, processed_pages: int
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Find header/footer text that repeats in the page margins.

        Returns the set of normalized keys seen in the top margin and the set
        seen in the bottom margin on enough pages to be treated as running
        headers/footers. Single-page documents are left untouched.
        """
        if processed_pages < 2:
            return frozenset(), frozenset()
        top_pages: dict[str, set[int]] = {}
        bottom_pages: dict[str, set[int]] = {}
        for index in range(processed_pages):
            plumber_page = plumber_pdf.pages[index]
            height = float(plumber_page.height)
            if height <= 0:
                continue
            top_limit = height * HEADER_BAND_FRACTION
            bottom_limit = height * (1.0 - FOOTER_BAND_FRACTION)
            for line in self._page_reading_lines(plumber_page, index + 1):
                key = margin_repeat_key(str(line.get("text", "")))
                if not key:
                    continue
                bbox = line.get("bbox")
                if bbox is None:
                    continue
                if float(bbox[1]) <= top_limit:
                    top_pages.setdefault(key, set()).add(index)
                elif float(bbox[3]) >= bottom_limit:
                    bottom_pages.setdefault(key, set()).add(index)
        top_keys = frozenset(
            key
            for key, pages in top_pages.items()
            if margin_text_repeats(len(pages), processed_pages)
        )
        bottom_keys = frozenset(
            key
            for key, pages in bottom_pages.items()
            if margin_text_repeats(len(pages), processed_pages)
        )
        return top_keys, bottom_keys

    def _is_repeating_margin_line(self, line: dict[str, Any], page_height: float) -> bool:
        if not (self._repeating_top_keys or self._repeating_bottom_keys):
            return False
        if page_height <= 0:
            return False
        bbox = line.get("bbox")
        if bbox is None:
            return False
        key = margin_repeat_key(str(line.get("text", "")))
        if not key:
            return False
        top = float(bbox[1])
        bottom = float(bbox[3])
        if top <= page_height * HEADER_BAND_FRACTION and key in self._repeating_top_keys:
            return True
        if (
            bottom >= page_height * (1.0 - FOOTER_BAND_FRACTION)
            and key in self._repeating_bottom_keys
        ):
            return True
        return False

    def _extract_text_blocks(
        self,
        pdf_page: PdfiumPage,
        plumber_page: pdfplumber.page.Page,
        page_number: int,
        suppressed_regions: list[BBox],
        document_title: str,
    ) -> list[TextBlock]:
        text_blocks: list[TextBlock] = []
        lines = self._page_reading_lines(plumber_page, page_number)
        page_height = float(plumber_page.height)

        filtered_lines: list[dict[str, Any]] = []
        for line in lines:
            if self._is_repeating_margin_line(line, page_height):
                continue
            bbox = tuple(float(value) for value in line["bbox"])
            filtered_line = dict(line)
            filtered_line["bbox"] = bbox
            suppressed = False
            for region in suppressed_regions:
                if region_contains_text_block(bbox, region):
                    suppressed = True
                    break
                clipped_line = clip_line_left_of_suppressed_region(filtered_line, region)
                if clipped_line is None:
                    suppressed = True
                    break
                filtered_line = clipped_line
                bbox = tuple(float(value) for value in filtered_line["bbox"])
            if suppressed:
                continue
            filtered_lines.append(filtered_line)

        contents_block = extract_contents_block(
            filtered_lines,
            page_number,
            self._toc_targets_by_title,
            extract_page_links(plumber_page),
        )
        if contents_block is not None:
            return [contents_block]

        non_footnote_lines = [
            line for line in filtered_lines if str(line.get("kind", "text")) != "footnote"
        ]
        algorithm_blocks = extract_algorithm_blocks(
            non_footnote_lines,
            page_number,
            pdf_page.rect,
        )
        formula_blocks = extract_formula_blocks(
            [
                line
                for line in non_footnote_lines
                if containing_text_block_index(
                    tuple(float(value) for value in line["bbox"]),
                    algorithm_blocks,
                )
                is None
            ],
            page_number,
            pdf_page.rect,
        )
        inserted_algorithm_indexes: set[int] = set()
        inserted_formula_indexes: set[int] = set()

        for line in filtered_lines:
            bbox = tuple(float(value) for value in line["bbox"])
            algorithm_index = containing_text_block_index(bbox, algorithm_blocks)
            if algorithm_index is not None:
                if algorithm_index not in inserted_algorithm_indexes:
                    text_blocks.append(algorithm_blocks[algorithm_index])
                    inserted_algorithm_indexes.add(algorithm_index)
                continue
            formula_index = containing_text_block_index(bbox, formula_blocks)
            if formula_index is not None:
                if formula_index not in inserted_formula_indexes:
                    text_blocks.append(formula_blocks[formula_index])
                    inserted_formula_indexes.add(formula_index)
                continue
            raw_text = str(line["text"])
            text = normalize_text(raw_text)
            text = repair_segment_text_with_pdfium(pdf_page, bbox, raw_text, text)
            text = strip_wrapped_title_continuation(text, document_title, page_number)
            text = strip_orphan_math_prefix(text)
            kind = str(line.get("kind", "text"))
            repaired_ligatures = bool(line.get("repaired_ligatures")) or has_misdecoded_pdf_ligatures(
                raw_text
            )
            if text and kind != "footnote" and is_formula_text_line(bbox, pdf_page.rect, text):
                if repaired_ligatures:
                    self._record_ligature_repair(page_number)
                text_blocks.append(
                    TextBlock(
                        page=page_number,
                        bbox=bbox,
                        text=text,
                        kind="formula",
                        items=[{"text": text, "bbox": bbox}],
                    )
                )
                continue
            if (
                text
                and not is_metadata_or_noise(text, page_number, document_title, line)
                and not looks_like_visual_label_noise(text)
            ):
                if repaired_ligatures:
                    self._record_ligature_repair(page_number)
                text_blocks.append(
                    TextBlock(
                        page=page_number,
                        bbox=bbox,
                        text=text,
                        kind=kind,
                        items=[{"text": text, "bbox": bbox}],
                    )
                )
        for index, block in enumerate(algorithm_blocks):
            if index not in inserted_algorithm_indexes:
                text_blocks.append(block)
        for index, block in enumerate(formula_blocks):
            if index not in inserted_formula_indexes:
                text_blocks.append(block)
        if formula_blocks and not looks_like_two_column_text_flow_segments(
            non_footnote_lines,
            pdf_page.rect,
        ):
            text_blocks = sorted(text_blocks, key=lambda block: (block.page, block.bbox[1], block.bbox[0]))
        return merge_text_blocks(text_blocks)

    def _reorder_recent_page_cards(
        self,
        start_index: int,
        page_number: int,
        page_width: float,
    ) -> None:
        page_cards = self.cards[start_index:]
        if len(page_cards) <= 1 or not any(card.page == page_number for card in page_cards):
            return
        self.cards[start_index:] = order_page_cards_for_reader(
            page_cards,
            page_number=page_number,
            page_width=page_width,
        )

    def _record_ligature_repair(self, page_number: int) -> None:
        if page_number in self._ligature_repair_pages:
            return
        self._ligature_repair_pages.add(page_number)
        self.warnings.append(
            f"Page {page_number}: repaired suspicious ligature glyph mappings in extracted text."
        )

    def _ocr_page(self, source_asset: ImageAsset, page_number: int) -> list[TextBlock]:
        try:
            import pytesseract
        except Exception:
            self.warnings.append("OCR requested, but pytesseract is not installed.")
            return []

        try:
            image_bytes = base64.b64decode(source_asset.data_uri.split(",", 1)[1])
            with Image.open(io.BytesIO(image_bytes)) as image:
                text = normalize_text(pytesseract.image_to_string(image))
        except Exception as error:
            self.warnings.append(f"Page {page_number}: OCR failed: {error}")
            return []
        if not text:
            return []
        return [TextBlock(page=page_number, bbox=(0, 0, 0, 0), text=text)]

    def _append_text_cards(
        self,
        block: TextBlock,
        source_image_id: str,
        pdf_page: PdfiumPage,
    ) -> None:
        if block.kind == "footnote":
            return

        if block.kind == "contents":
            self.cards.append(
                Card(
                    id=self._next_card_id(),
                    kind="contents",
                    page=block.page,
                    section="Contents",
                    text=block.text,
                    source_image_id=source_image_id,
                    bbox=block.bbox,
                    items=block.items,
                )
            )
            return

        if block.kind == "formula":
            self._append_cropped_asset_card(
                pdf_page=pdf_page,
                page_number=block.page,
                kind="formula",
                bbox=block.bbox,
                caption=block.text,
                fallback_label=f"Formula on page {block.page}",
                padding=2.0,
            )
            return

        kind = "heading" if looks_like_heading(block.text) else "paragraph"
        if kind == "heading":
            text_parts = [(block.text, block.bbox, text_block_line_items(block))]
            section = block.text
        else:
            text_parts = split_text_block_by_items(
                block,
                self.options.max_words_per_card,
                page_width=float(pdf_page.rect.width),
            )
            section = self._current_section()
        for text, bbox, items in text_parts:
            self.cards.append(
                Card(
                    id=self._next_card_id(),
                    kind=kind,
                    page=block.page,
                    section=section,
                    text=text,
                    source_image_id=source_image_id,
                    bbox=bbox,
                    items=items,
                )
            )

    def _append_cropped_asset_card(
        self,
        pdf_page: PdfiumPage,
        page_number: int,
        kind: str,
        bbox: BBox,
        caption: str,
        fallback_label: str,
        padding: float = 5.0,
    ) -> None:
        clipped_bbox = clamp_bbox_to_page(bbox, pdf_page.rect)
        if clipped_bbox is None:
            self.warnings.append(f"Page {page_number}: skipped invalid {kind} bbox {bbox}.")
            return
        bbox = clipped_bbox
        try:
            data, width, height = pdf_page.render_clip_png(
                bbox,
                self.options.crop_scale,
                padding=padding,
            )
        except Exception as error:
            self.warnings.append(f"Page {page_number}: failed to crop {kind}: {error}")
            return
        asset_id = self._next_asset_id(kind, page_number)
        asset = ImageAsset(
            id=asset_id,
            kind=kind,
            page=page_number,
            alt=caption or fallback_label,
            caption=caption or fallback_label,
            data_uri=png_data_uri(data),
            width=width,
            height=height,
            bbox=bbox,
        )
        self.assets.append(asset)
        self.cards.append(
            Card(
                id=self._next_card_id(),
                kind=kind,
                page=page_number,
                section=self._current_section(),
                text=asset.caption,
                image_id=asset.id,
                source_image_id=f"source-page-{page_number}",
                bbox=bbox,
            )
        )

    def _current_section(self) -> str:
        for card in reversed(self.cards):
            if card.kind == "heading" and card.text:
                return card.text
        return "Document"

    def _next_card_id(self) -> str:
        self._card_number += 1
        return f"card-{self._card_number}"

    def _next_asset_id(self, kind: str, page_number: int) -> str:
        index = 1
        while True:
            candidate = f"{kind}-{page_number}-{index}"
            if candidate not in self._asset_ids:
                self._asset_ids.add(candidate)
                return candidate
            index += 1

    def _scale_plumber_bbox(
        self,
        bbox: BBox,
        plumber_page: pdfplumber.page.Page,
        pdf_page: PdfiumPage,
    ) -> BBox:
        x_scale = pdf_page.rect.width / float(plumber_page.width)
        y_scale = pdf_page.rect.height / float(plumber_page.height)
        x0, top, x1, bottom = bbox
        return (
            max(0.0, x0 * x_scale),
            max(0.0, top * y_scale),
            min(float(pdf_page.rect.width), x1 * x_scale),
            min(float(pdf_page.rect.height), bottom * y_scale),
        )

    def _useful_image_bbox(
        self,
        bbox: BBox,
        page_rect: PageRect,
        table_regions: list[BBox],
    ) -> bool:
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width < 72 or height < 48:
            return False
        area_ratio = (width * height) / max(1.0, page_rect.width * page_rect.height)
        if area_ratio < 0.018:
            return False
        if any(overlap_ratio(bbox, table_bbox) > 0.15 for table_bbox in table_regions):
            return False
        return True

    def _pdf_mentions_tables(self, plumber_pdf: pdfplumber.PDF, processed_pages: int) -> bool:
        for page in plumber_pdf.pages[:processed_pages]:
            text = page.extract_text() or ""
            if re.search(r"\bTable\s+(?:[A-Z]\s*)?\d+[A-Za-z]?\b", text, re.IGNORECASE):
                return True
        return False


def png_data_uri(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def infer_visual_title_from_first_page(plumber_page: pdfplumber.page.Page) -> str | None:
    segments = split_chars_into_reading_order_segments(
        plumber_page.chars,
        float(plumber_page.width),
        float(plumber_page.height),
    )
    if not segments:
        return None
    body_font_size = dominant_body_font_size(segments, float(plumber_page.height))
    title_lines: list[dict[str, Any]] = []
    title_window_bottom = min(float(plumber_page.height) * 0.32, 220.0)
    previous_bottom: float | None = None

    for segment in segments:
        text = normalize_text(str(segment.get("text", "")))
        if not text:
            continue
        bbox = tuple(float(value) for value in segment["bbox"])
        top = bbox[1]
        if top > title_window_bottom:
            if title_lines:
                break
            continue
        if looks_like_title_stop_line(text):
            if title_lines:
                break
            continue
        if looks_like_title_noise(text) or looks_like_author_affiliation_line(text):
            if title_lines and top - (previous_bottom or top) > 6:
                break
            continue

        font_size = float(segment.get("font_size") or 0)
        high_confidence = font_size >= max(13.0, body_font_size * 1.22)
        uppercase_title = mostly_uppercase_words(text) and font_size >= max(12.0, body_font_size * 1.05)
        if high_confidence or uppercase_title:
            if title_lines and previous_bottom is not None and top - previous_bottom > max(12.0, font_size * 1.2):
                break
            title_lines.append({"text": text, "bbox": bbox, "font_size": font_size})
            previous_bottom = bbox[3]
        elif title_lines:
            break

    if not title_lines:
        return None
    title = join_wrapped_title_lines([str(line["text"]) for line in title_lines])
    title = normalize_text(title)
    if len(title) < 8 or looks_like_title_noise(title) or looks_like_author_affiliation_line(title):
        return None
    return title[:180]


def join_wrapped_title_lines(lines: list[str]) -> str:
    title = ""
    for line in lines:
        cleaned = normalize_text(line)
        if not cleaned:
            continue
        if title.endswith("-"):
            title = title[:-1] + cleaned
        elif title:
            title = f"{title} {cleaned}"
        else:
            title = cleaned
    return normalize_text(title)


def usable_metadata_title(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned or normalized_key(cleaned) in {"untitled", "none"}:
        return False
    return not looks_like_title_noise(cleaned)


def looks_like_title_noise(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return True
    compact = normalized_key(cleaned)
    if compact in {"untitled", "none"}:
        return True
    if "publishedasaconferencepaper" in compact:
        return True
    if re.search(r"\bconference\s+paper\s+at\s+(?:iclr|neurips|nips|icml|acl|emnlp|cvpr|eccv|iccv)\b", cleaned, re.IGNORECASE):
        return True
    if re.match(r"^(?:under review|preprint|accepted|submitted)\b", cleaned, re.IGNORECASE):
        return True
    if re.match(r"^arXiv:\d{4}\.\d+(?:v\d+)?\b", cleaned, re.IGNORECASE):
        return True
    return False


def looks_like_title_stop_line(text: str) -> bool:
    return normalized_key(text) in {"abstract", "summary", "introduction", "keywords"}


def looks_like_author_affiliation_line(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    if "@" in cleaned or re.search(r"\b(?:University|Institute|College|Corporation|Google|Microsoft|DeepSeek-AI)\b", cleaned):
        return True
    if re.search(r"\b(?:Department|School|Laboratory|Lab)\s+of\b", cleaned, re.IGNORECASE):
        return True
    comma_count = cleaned.count(",")
    if comma_count >= 3 and not mostly_uppercase_words(cleaned):
        return True
    return False


def mostly_uppercase_words(text: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z-]*", text)
    if not words:
        return False
    long_words = [word for word in words if len(word) >= 3]
    if not long_words:
        return False
    uppercase = [word for word in long_words if word.upper() == word]
    return len(uppercase) / len(long_words) >= 0.72


def normalize_text(text: str) -> str:
    ligatures = {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
    }
    for source, replacement in ligatures.items():
        text = text.replace(source, replacement)
    text = repair_misdecoded_pdf_ligatures(text)
    text = repair_residual_pdf_ligature_words(text)
    text = replace_common_cid_glyphs(text)
    text = replace_private_use_pdf_glyphs(text)
    text = repair_formula_label_collisions(text)
    text = text.replace("\x00", "")
    text = text.replace("\ufffd", "")
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def repair_formula_label_collisions(text: str) -> str:
    return re.sub(r"\b[ILP]{1,2}emma\b", "Lemma", text)


def strip_wrapped_title_continuation(text: str, document_title: str, page_number: int) -> str:
    """Drop all-caps title continuation fragments that leak into page-one bylines."""

    cleaned = normalize_text(text)
    title = normalize_text(document_title)
    if page_number != 1 or not cleaned or not title:
        return cleaned
    title_key = normalized_key(title)
    tokens = cleaned.split()
    for token_count in range(min(8, len(tokens)), 0, -1):
        prefix = " ".join(tokens[:token_count])
        prefix_key = normalized_key(prefix)
        if len(prefix_key) < 8 or prefix_key not in title_key:
            continue
        if not all(token.strip(",:;()[]{}").upper() == token.strip(",:;()[]{}") for token in tokens[:token_count]):
            continue
        return normalize_text(" ".join(tokens[token_count:]))
    if not title.endswith("-"):
        return cleaned
    title_prefix = re.search(r"([A-Z]{2,})-\s*$", title.upper())
    if title_prefix is None:
        return cleaned
    if cleaned.lower().startswith(title.lower()):
        cleaned = normalize_text(cleaned[len(title) :])

    tokens = cleaned.split()
    drop_count = 0
    for token in tokens[:8]:
        stripped = token.strip(",:;()[]{}")
        if not re.fullmatch(r"[A-Z][A-Z-]{1,}", stripped):
            break
        drop_count += 1
        if len(stripped) >= 3 and stripped.endswith("S"):
            # Most wrapped scientific titles end with a plural noun such as MODELS.
            break
    if drop_count == 0:
        return cleaned
    return normalize_text(" ".join(tokens[drop_count:]))


MISDECODED_PDF_LIGATURES = {
    "!": "fi",
    '"': "ffi",
    "”": "ffi",
    "#": "ff",
    "$": "fl",
    "%": "ffl",
}

MISDECODED_PDF_LIGATURE_RE = re.compile(
    r'(?:(?<=[A-Za-z])!(?=[ceglnrtv])|(?<![A-Za-z])!(?=[a-z])|(?<=[A-Za-z])["”](?=[cils])|'
    r"(?<=[A-Za-z])\#(?=[eilos])|(?<=[A-Za-z])\$(?=[aeiouly])|"
    r"(?<=[A-Za-z])%(?=[aeiouy]))"
)

FUSED_LEADING_FI_WORD_RE = re.compile(r"(?<=[a-z])!ve\b")
CONTEXTUAL_MISDECODED_LIGATURE_RE = re.compile(r"(?<=o)!(?=s)|(?<=-o)!(?=$)")
CID_GLYPH_RE = re.compile(r"\(cid:(\d+)\)")
SUSPICIOUS_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd\ufffe]")
COMMON_CID_GLYPHS = {
    "0": "(",
    "1": ")",
    "2": "[",
    "3": "]",
    "8": "{",
    "9": "}",
    "16": "(",
    "17": ")",
    "18": "(",
    "19": ")",
    "20": "[",
    "21": "]",
    "33": ")",
    "35": "]",
    "40": "{",
    "54": "≠",
    "55": "↦",
    "80": "∑",
    "88": "∑",
    "89": "∏",
    "116": "√",
    "122": "z",
    "123": "{",
    "124": "|",
    "125": "}",
}


def has_misdecoded_pdf_ligatures(text: str) -> bool:
    return bool(
        MISDECODED_PDF_LIGATURE_RE.search(text)
        or CONTEXTUAL_MISDECODED_LIGATURE_RE.search(text)
    )


def has_unreadable_pdf_glyphs(text: str) -> bool:
    return bool(CID_GLYPH_RE.search(text) or SUSPICIOUS_CONTROL_RE.search(text))


def unreadable_pdf_glyph_score(text: str) -> int:
    return len(CID_GLYPH_RE.findall(text)) * 3 + len(SUSPICIOUS_CONTROL_RE.findall(text))


def replace_common_cid_glyphs(text: str) -> str:
    return CID_GLYPH_RE.sub(
        lambda match: COMMON_CID_GLYPHS.get(match.group(1), match.group(0)),
        text,
    )


PRIVATE_USE_PDF_GLYPHS = {
    "\uf8ee": " ",
    "\uf8ef": " ",
    "\uf8f0": " ",
    "\uf8f1": " ",
    "\uf8f2": " ",
    "\uf8f3": " ",
    "\uf8f4": " ",
    "\uf8f5": " ",
    "\uf8f6": " ",
    "\uf8f7": " ",
    "\uf8f8": " ",
    "\uf8f9": " ",
    "\uf8fa": " ",
    "\uf8fb": " ",
    "\uf8fc": " ",
    "\uf8fd": " ",
    "\uf8fe": " ",
    "\uf8ff": " ",
}


def replace_private_use_pdf_glyphs(text: str) -> str:
    for source, replacement in PRIVATE_USE_PDF_GLYPHS.items():
        text = text.replace(source, replacement)
    return text


def repair_segment_text_with_pdfium(
    pdf_page: PdfiumPage,
    bbox: BBox,
    raw_text: str,
    normalized_text: str,
) -> str:
    if not (has_unreadable_pdf_glyphs(raw_text) or has_unreadable_pdf_glyphs(normalized_text)):
        return normalized_text
    candidate = normalize_text(normalize_pdfium_control_chars(pdf_page.extract_text_bounded(bbox)))
    if not candidate:
        return normalized_text
    if unreadable_pdf_glyph_score(candidate) >= unreadable_pdf_glyph_score(normalized_text):
        return normalized_text
    if not plausible_pdfium_replacement(normalized_text, candidate):
        return normalized_text
    return candidate


def plausible_pdfium_replacement(original: str, candidate: str) -> bool:
    candidate_words = re.findall(r"\b[A-Za-z0-9]{2,}\b", candidate)
    candidate_math = count_mathish_chars(candidate) + true_formula_operator_count(candidate)
    if len(candidate_words) == 0 and candidate_math == 0:
        return False
    original_length = max(1, len(original))
    if len(candidate) > max(240, original_length * 5):
        return False
    return True


def normalize_pdfium_control_chars(text: str) -> str:
    cleaned = text.replace("\ufffe", "")
    cleaned = re.sub(r"(?<=[A-Za-z])[\x02\x03](?=[A-Za-z])", "", cleaned)
    cleaned = cleaned.replace("\x02", "[").replace("\x03", "]")
    cleaned = re.sub(r"[\x00\x01\x04-\x08\x0b\x0c\x0e-\x1f\ufffd]", "", cleaned)
    return cleaned


def strip_orphan_math_prefix(text: str) -> str:
    cleaned = normalize_text(text)
    cleaned = strip_leading_math_scrap_before_prose(cleaned)
    cleaned = re.sub(
        r"^\)\s*[A-Za-z]\([^)]{1,50}\)\s*[.,]\s+(?=[A-Z][a-z])",
        "",
        cleaned,
    )
    return normalize_text(
        re.sub(
            r"^(?:(?:\(cid:\d+\)|[()[\]{}|∑∏√≠↦,;:.])\s*)+(?=[A-Z][a-z])",
            "",
            cleaned,
        )
    )


def strip_leading_math_scrap_before_prose(text: str) -> str:
    cleaned = normalize_text(text)
    match = re.match(r"^(.{1,40}?)(?=\b[A-Z][a-z]{2,}\b)", cleaned)
    if match is None:
        return cleaned
    prefix = match.group(1).strip()
    if not prefix:
        return cleaned
    if not (has_math_unicode(prefix) or true_formula_operator_count(prefix) > 0):
        return cleaned
    words = re.findall(r"\b[A-Za-z]{1,12}\b", prefix)
    allowed_words = {"a", "b", "c", "d", "i", "j", "k", "l", "m", "n", "p", "q", "r", "t", "x", "y", "z"}
    if words and any(word.lower() not in allowed_words for word in words):
        return cleaned
    return normalize_text(cleaned[match.end(1) :])


def repair_misdecoded_pdf_ligatures(text: str) -> str:
    """Repair common PDF font maps that expose ligature glyphs as ASCII punctuation."""

    text = FUSED_LEADING_FI_WORD_RE.sub(" five", text)
    text = CONTEXTUAL_MISDECODED_LIGATURE_RE.sub("ff", text)
    return MISDECODED_PDF_LIGATURE_RE.sub(
        lambda match: MISDECODED_PDF_LIGATURES[match.group(0)],
        text,
    )


def repair_residual_pdf_ligature_words(text: str) -> str:
    replacements = {
        "parflameters%": "parameters",
        "TPable": "Table",
        "fPor": "for",
        "wPhen": "when",
    }
    for source, replacement in replacements.items():
        text = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(source)}(?![A-Za-z0-9])",
            replacement,
            text,
        )
    return text


def normalized_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(text).lower())


HEADER_BAND_FRACTION = 0.12
FOOTER_BAND_FRACTION = 0.12
MARGIN_REPEAT_RATIO = 0.4


def margin_repeat_key(text: str) -> str:
    """Stable key for matching running headers/footers across pages.

    Digit runs (page numbers, dates) are collapsed so otherwise-identical
    running text matches even when the page number differs.
    """
    cleaned = normalize_text(text)
    if not cleaned:
        return ""
    collapsed = re.sub(r"\d+", " ", cleaned)
    return normalized_key(collapsed)


def margin_text_repeats(occurrence_pages: int, processed_pages: int) -> bool:
    """Whether margin text seen on ``occurrence_pages`` counts as a header/footer."""
    if processed_pages < 2 or occurrence_pages < 2:
        return False
    return occurrence_pages >= max(2, round(processed_pages * MARGIN_REPEAT_RATIO))


def is_metadata_or_noise(
    text: str,
    page_number: int,
    document_title: str,
    line: dict[str, Any] | None = None,
) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return True
    if re.fullmatch(r"\d{1,4}", cleaned):
        return True
    if normalized_key(cleaned) == normalized_key(document_title):
        return True
    if looks_like_repeating_page_header_noise(cleaned):
        return True
    if page_number == 1 and looks_like_title_noise(cleaned):
        return True
    if page_number == 1 and is_document_title_fragment(cleaned, document_title, line):
        return True
    if cleaned.startswith("*Equal contribution"):
        return True
    if "Correspondence to:" in cleaned:
        return True
    if "Project lead" in cleaned and re.search(r"\bUniversity\b|\bInstitute\b|\bCollege\b", cleaned):
        return True
    if re.match(r"^arXiv:\d{4}\.\d+(?:v\d+)?\b", cleaned, re.IGNORECASE):
        return True
    if re.match(r"^Proceedings of the\b", cleaned, re.IGNORECASE) and "Copyright" in cleaned:
        return True
    if re.fullmatch(r"copyright\s+\d{4}.*", cleaned, re.IGNORECASE):
        return True
    return False


def looks_like_repeating_page_header_noise(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    compact = normalized_key(cleaned)
    if "publishedasaconferencepaper" in compact:
        return True
    if re.match(r"^arXiv:\d{4}\.\d+(?:v\d+)?\b", cleaned, re.IGNORECASE):
        return True
    return False


def is_document_title_fragment(
    text: str,
    document_title: str,
    line: dict[str, Any] | None = None,
) -> bool:
    if looks_like_title_stop_line(text):
        return False
    title_key = normalized_key(document_title)
    text_key = normalized_key(text)
    if len(text_key) < 8 or len(title_key) < 8 or text_key not in title_key:
        return False
    if line is not None:
        bbox = line.get("bbox")
        if bbox is not None and float(bbox[1]) > 185:
            return False
        font_size = float(line.get("font_size") or 0)
        if font_size and font_size < 11:
            return False
    if len(text_key) / len(title_key) >= 0.18:
        return True
    return mostly_uppercase_words(text)


def normalize_block_lines(lines: list[str]) -> str:
    result = ""
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if not result:
            result = line
            continue
        result = join_wrapped_text(result, line)
    return normalize_text(result)


TOC_DOT_LEADER_RE = re.compile(r"(?:\s*[.·]\s*){3,}")
TOC_SECTION_LABEL_RE = re.compile(
    r"^(?P<number>\d+(?:\.\d+)*)(?:\.|\s)+(?P<title>.+)$"
)


def toc_targets_by_title(entries: list[PdfTocEntry]) -> dict[str, PdfTocEntry]:
    targets: dict[str, PdfTocEntry | None] = {}
    for entry in entries:
        key = toc_title_key(entry.title)
        if not key:
            continue
        existing = targets.get(key)
        if existing is None and key in targets:
            continue
        if existing is not None and existing.page != entry.page:
            targets[key] = None
            continue
        targets[key] = entry
    return {key: entry for key, entry in targets.items() if entry is not None}


def toc_title_key(text: str) -> str:
    cleaned = normalize_text(text).strip()
    cleaned = TOC_SECTION_LABEL_RE.sub(lambda match: match.group("title"), cleaned)
    return normalized_key(cleaned)


def extract_page_links(plumber_page: pdfplumber.page.Page) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    try:
        annots = plumber_page.annots or []
    except Exception:
        return links
    for annot in annots:
        uri = annot.get("uri")
        if not isinstance(uri, str) or not safe_external_href(uri):
            continue
        try:
            bbox = (
                float(annot["x0"]),
                float(annot["top"]),
                float(annot["x1"]),
                float(annot["bottom"]),
            )
        except Exception:
            continue
        links.append({"bbox": bbox, "href": uri})
    return links


def extract_contents_block(
    segments: list[dict[str, Any]],
    page_number: int,
    toc_targets: dict[str, PdfTocEntry],
    page_links: list[dict[str, Any]] | None = None,
) -> TextBlock | None:
    rows = group_segments_into_rows(segments)
    if not rows:
        return None

    page_links = page_links or []
    header_boxes = [
        union_bboxes([segment["bbox"] for segment in row])
        for row in rows
        if is_contents_heading(row_text(row))
    ]
    items: list[dict[str, Any]] = []
    item_boxes: list[BBox] = []
    leader_rows = 0

    for row in rows:
        parsed = parse_toc_row(row)
        if parsed is None:
            continue
        if parsed["had_leader"]:
            leader_rows += 1
        target_entry = resolve_toc_entry(parsed["title"], toc_targets)
        target_page = parsed["target_page"] or (target_entry.page if target_entry else None)
        href = external_href_for_bbox(parsed["bbox"], page_links)
        if not href and target_page:
            href = f"#page-{target_page}"

        item: dict[str, Any] = {
            "label": parsed["label"],
            "title": parsed["title"],
            "page_label": parsed["page_label"],
            "level": parsed["level"],
        }
        if parsed["number"]:
            item["number"] = parsed["number"]
        if target_page:
            item["target_page"] = target_page
        if href:
            item["href"] = href
        items.append(item)
        item_boxes.append(parsed["bbox"])

    if len(items) < 3:
        return None
    has_header = bool(header_boxes)
    if not has_header and leader_rows < 3:
        return None

    text = "\n".join(
        f"{item['label']} {item['page_label']}".strip()
        for item in items
        if item.get("label")
    )
    if not text:
        return None

    bbox = union_bboxes([*header_boxes, *item_boxes] if header_boxes else item_boxes)
    return TextBlock(
        page=page_number,
        bbox=bbox,
        text=text,
        kind="contents",
        items=items,
    )


def group_segments_into_rows(segments: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    sorted_segments = sorted(
        segments,
        key=lambda segment: (float(segment["bbox"][1]), float(segment["bbox"][0])),
    )
    rows: list[list[dict[str, Any]]] = []
    row_tops: list[float] = []
    for segment in sorted_segments:
        top = float(segment["bbox"][1])
        if rows and abs(top - row_tops[-1]) <= 3.5:
            rows[-1].append(segment)
            row_tops[-1] = median([float(item["bbox"][1]) for item in rows[-1]])
            continue
        rows.append([segment])
        row_tops.append(top)
    return [sorted(row, key=lambda segment: float(segment["bbox"][0])) for row in rows]


def row_text(row: list[dict[str, Any]]) -> str:
    return normalize_text(" ".join(str(segment.get("text", "")) for segment in row))


def is_contents_heading(text: str) -> bool:
    return normalized_key(text) in {"contents", "tableofcontents"}


def parse_toc_row(row: list[dict[str, Any]]) -> dict[str, Any] | None:
    text = row_text(row)
    if not text or is_contents_heading(text):
        return None
    if re.fullmatch(r"\d{1,4}", text):
        return None

    sorted_row = sorted(row, key=lambda segment: float(segment["bbox"][0]))
    last_text = normalize_text(str(sorted_row[-1].get("text", "")))
    body = text
    page_label = ""
    had_leader = bool(TOC_DOT_LEADER_RE.search(text))

    if len(sorted_row) > 1 and re.fullmatch(r"\d{1,4}", last_text):
        body = normalize_text(" ".join(str(segment.get("text", "")) for segment in sorted_row[:-1]))
        page_label = last_text
    else:
        leader_match = re.match(
            rf"^(?P<body>.+?){TOC_DOT_LEADER_RE.pattern}\s*(?P<page>\d{{1,4}})$",
            text,
        )
        if leader_match:
            body = normalize_text(leader_match.group("body"))
            page_label = leader_match.group("page")
            had_leader = True
        else:
            trailing_page = re.match(r"^(?P<body>.+?)\s+(?P<page>\d{1,4})$", text)
            if trailing_page and looks_like_toc_label(trailing_page.group("body")):
                body = trailing_page.group("body")
                page_label = trailing_page.group("page")

    label = clean_toc_label(body)
    if not label or not page_label or not re.fullmatch(r"\d{1,4}", page_label):
        return None
    if not had_leader and not looks_like_toc_label(label):
        return None

    number, title = split_toc_label(label)
    if not title:
        return None
    target_page = int(page_label) if page_label.isdigit() else None
    level = max(0, number.count(".")) if number else 0
    return {
        "number": number,
        "title": title,
        "label": label,
        "page_label": page_label,
        "target_page": target_page,
        "level": level,
        "had_leader": had_leader,
        "bbox": union_bboxes([segment["bbox"] for segment in row]),
    }


def clean_toc_label(text: str) -> str:
    cleaned = TOC_DOT_LEADER_RE.sub(" ", text)
    cleaned = re.sub(r"\s+\.+\s*$", "", cleaned)
    return normalize_text(cleaned)


def looks_like_toc_label(text: str) -> bool:
    cleaned = clean_toc_label(text)
    if not cleaned or len(cleaned) > 160:
        return False
    if TOC_SECTION_LABEL_RE.match(cleaned):
        return True
    return bool(re.search(r"[A-Za-z]{3,}", cleaned)) and len(cleaned.split()) <= 14


def split_toc_label(label: str) -> tuple[str, str]:
    match = TOC_SECTION_LABEL_RE.match(label)
    if match is None:
        return "", label.strip()
    return match.group("number"), normalize_text(match.group("title"))


def resolve_toc_entry(
    title: str,
    toc_targets: dict[str, PdfTocEntry],
) -> PdfTocEntry | None:
    return toc_targets.get(toc_title_key(title))


def external_href_for_bbox(bbox: BBox, links: list[dict[str, Any]]) -> str:
    for link in links:
        link_bbox = link.get("bbox")
        href = link.get("href")
        if not isinstance(link_bbox, tuple) or not isinstance(href, str):
            continue
        if vertical_gap(bbox, link_bbox) <= 3 and horizontal_overlap_ratio(bbox, link_bbox) > 0:
            return href
    return ""


def safe_external_href(href: str) -> bool:
    return bool(re.match(r"^(?:https?://|mailto:)", href, re.IGNORECASE))


@dataclass(frozen=True, slots=True)
class AlgorithmRow:
    row: list[dict[str, Any]]
    bbox: BBox
    text: str
    score: int
    strong: bool


@dataclass(frozen=True, slots=True)
class FormulaRow:
    row: list[dict[str, Any]]
    bbox: BBox
    text: str
    score: int
    strong: bool


FORMULA_OPERATOR_RE = re.compile(
    r"(?:->|=>|←|→|↔|=|≤|≥|≠|≈|∈|∉|∑|∏|∫|√|±|∂|∞|"
    r"\b(?:arg\s*max|arg\s*min|min|max|clip|log|mean|std)\b)"
)
BINARY_MATH_OPERATOR_RE = re.compile(
    r"(?:(?<=[A-Za-z0-9)\]}])\s*[+*/]\s*(?=[A-Za-z0-9({\[])|"
    r"(?<=[A-Za-z0-9)\]}])\s+-\s+(?=[A-Za-z0-9({\[]))"
)
URLISH_TEXT_RE = re.compile(
    r"(?:https?://|www\.|(?:^|\s)(?:url|doi):|"
    r"(?:github|arxiv|aclanthology|openreview|codeforces|aider)\.(?:com|org|net|chat)\b|"
    r"\.(?:com|org|net|edu|gov|io|pdf)\b)",
    re.IGNORECASE,
)
PATHLIKE_TEXT_RE = re.compile(r"(?:^|\s)[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]{3,}")
ALGORITHM_HEADER_RE = re.compile(
    r"^\s*(?:Algorithm|ALGORITHM)\s+\d+[A-Za-z]?\b(?:\s+[A-Z][A-Za-z0-9_-]+|\s*$)",
)
ALGORITHM_IO_RE = re.compile(
    r"^(?:Require|Inputs?|Outputs?|Ensure|Initialize|Init)\s*:",
    re.IGNORECASE,
)
ALGORITHM_IO_ANY_RE = re.compile(
    r"\b(?:Require|Inputs?|Outputs?|Ensure|Initialize|Init)\s*:",
    re.IGNORECASE,
)
ALGORITHM_LINE_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*:")
ALGORITHM_CONTROL_RE = re.compile(
    r"^(?:"
    r"\d{1,3}\s*:\s*)?"
    r"(?:for\b.+\bdo\b|while\b.+\bdo\b|if\b.+\bthen\b|else\b|"
    r"end\s+(?:if|for|while|function|procedure)\b|return\b|repeat\b|until\b|"
    r"function\b|procedure\b)"
    r"",
    re.IGNORECASE,
)
ALGORITHM_ASSIGNMENT_RE = re.compile(
    r"(?:←|<-|:=|\barg\s*max\b|\barg\s*min\b|\bclip\b|\bmin\b|\bmax\b)", re.IGNORECASE
)
ALGORITHM_KEYWORD_RE = re.compile(
    r"\b(?:DRAFT|VERIFY|CORRECT|STANDARDNMS|SHOULDMERGE|MERGE|NMS|CALL|BREAK|CONTINUE)\b"
)


def extract_algorithm_blocks(
    segments: list[dict[str, Any]],
    page_number: int,
    page_rect: PageRect,
) -> list[TextBlock]:
    column_blocks = extract_column_algorithm_blocks(segments, page_number, page_rect)
    if column_blocks:
        return column_blocks

    rows = group_segments_into_rows(segments)
    blocks: list[TextBlock] = []
    current: list[AlgorithmRow] = []

    def flush_current() -> None:
        nonlocal current
        if algorithm_group_is_block(current):
            bbox = trim_algorithm_group_bbox(current, page_rect)
            blocks.append(
                TextBlock(
                    page=page_number,
                    bbox=bbox,
                    text=normalize_block_lines([row.text for row in current]),
                    kind="formula",
                )
            )
        current = []

    previous_bbox: BBox | None = None
    for row in rows:
        algorithm_row = classify_algorithm_row(row, page_rect)
        if algorithm_row is None:
            flush_current()
            previous_bbox = None
            continue
        if current and previous_bbox is not None and vertical_gap(previous_bbox, algorithm_row.bbox) > 18:
            flush_current()
        current.append(algorithm_row)
        previous_bbox = algorithm_row.bbox
    flush_current()
    return blocks


def extract_column_algorithm_blocks(
    segments: list[dict[str, Any]],
    page_number: int,
    page_rect: PageRect,
) -> list[TextBlock]:
    rows = group_segments_into_rows(segments)
    anchors: list[tuple[int, dict[str, Any]]] = []
    for row_index, row in enumerate(rows):
        for segment in row:
            if ALGORITHM_HEADER_RE.search(normalize_text(str(segment.get("text", "")))):
                anchors.append((row_index, segment))
    if not anchors:
        return []

    blocks: list[TextBlock] = []
    for anchor_index, (row_index, anchor) in enumerate(anchors):
        x_range = algorithm_anchor_x_range(anchor, anchors, anchor_index, page_rect)
        block_rows = collect_algorithm_column_rows(rows, row_index, x_range)
        if len(block_rows) < 2:
            continue
        bbox = trim_algorithm_column_bbox(block_rows, page_rect)
        text = normalize_block_lines([row["text"] for row in block_rows])
        blocks.append(TextBlock(page=page_number, bbox=bbox, text=text, kind="formula"))
    return merge_overlapping_algorithm_blocks(blocks)


def algorithm_anchor_x_range(
    anchor: dict[str, Any],
    anchors: list[tuple[int, dict[str, Any]]],
    anchor_index: int,
    page_rect: PageRect,
) -> tuple[float, float]:
    same_band = [
        segment
        for row_index, segment in anchors
        if abs(float(segment["bbox"][1]) - float(anchor["bbox"][1])) <= 8
    ]
    same_band = sorted(same_band, key=lambda segment: float(segment["bbox"][0]))
    if len(same_band) >= 2 and anchor in same_band:
        band_index = same_band.index(anchor)
        centers = [(float(segment["bbox"][0]) + float(segment["bbox"][2])) / 2 for segment in same_band]
        left = page_rect.x0
        right = page_rect.x1
        if band_index > 0:
            left = (centers[band_index - 1] + centers[band_index]) / 2
        if band_index < len(same_band) - 1:
            right = (centers[band_index] + centers[band_index + 1]) / 2
        return (left, right)

    bbox = tuple(float(value) for value in anchor["bbox"])
    width = max(page_rect.width * 0.32, bbox[2] - bbox[0] + 80)
    center = (bbox[0] + bbox[2]) / 2
    return (
        max(page_rect.x0, center - width / 2),
        min(page_rect.x1, center + width / 2),
    )


def collect_algorithm_column_rows(
    rows: list[list[dict[str, Any]]],
    start_index: int,
    x_range: tuple[float, float],
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    previous_bbox: BBox | None = None
    started = False
    ended = False

    for row in rows[start_index:]:
        column_segments = segments_in_x_range(row, x_range)
        if not column_segments:
            if started and previous_bbox is not None:
                row_bbox = union_bboxes([segment["bbox"] for segment in row])
                if float(row_bbox[1]) - previous_bbox[3] > 18:
                    break
                continue
            if started:
                break
            continue
        column_text = normalize_text(" ".join(str(segment.get("text", "")) for segment in column_segments))
        if not column_text:
            continue
        column_bbox = union_bboxes([segment["bbox"] for segment in column_segments])
        gap = vertical_gap(previous_bbox, column_bbox) if previous_bbox is not None else 0.0
        qualifies = algorithm_column_row_qualifies(column_text, started, ended, gap)
        if not qualifies:
            if started and gap > 10:
                break
            continue

        collected.append({"bbox": column_bbox, "text": column_text})
        previous_bbox = column_bbox
        started = True
        if algorithm_column_row_ends_block(column_text):
            ended = True
    return collected


def segments_in_x_range(
    row: list[dict[str, Any]],
    x_range: tuple[float, float],
) -> list[dict[str, Any]]:
    left, right = x_range
    result: list[dict[str, Any]] = []
    for segment in row:
        bbox = tuple(float(value) for value in segment["bbox"])
        center = (bbox[0] + bbox[2]) / 2
        if left - 2 <= center <= right + 2:
            result.append(segment)
    return result


def algorithm_column_row_qualifies(
    text: str,
    started: bool,
    ended: bool,
    gap: float,
) -> bool:
    cleaned = normalize_text(text)
    if not started:
        return bool(ALGORITHM_HEADER_RE.search(cleaned))
    if ended and gap > 4:
        return False
    if row_has_algorithm_marker(cleaned) or algorithm_segment_score(cleaned) >= 2:
        return True
    if gap > 14:
        return False
    if looks_like_algorithm_continuation(cleaned):
        return True
    if gap <= 4 and len(cleaned) <= 90 and not looks_like_formula_boundary_prose(cleaned):
        return True
    return False


def looks_like_algorithm_continuation(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    if len(cleaned) > 130 and looks_like_formula_boundary_prose(cleaned):
        return False
    if cleaned.startswith("//"):
        return True
    if re.match(r"^\.\s*[A-Z]", cleaned):
        return True
    if re.search(r"(?:←|<-|:=|∼|~|\bDRAFT\b|\bVERIFY\b|\bCORRECT\b)", cleaned):
        return True
    if true_formula_operator_count(cleaned) >= 1 and count_mathish_chars(cleaned) >= 2:
        return True
    if len(cleaned.split()) <= 10 and count_mathish_chars(cleaned) >= 2:
        return True
    return False


def algorithm_column_row_ends_block(text: str) -> bool:
    cleaned = normalize_text(text)
    return bool(re.match(r"^\s*\d{1,3}\s*:\s*end\s+(?:while|for|if|function|procedure)\b", cleaned, re.IGNORECASE))


def trim_algorithm_column_bbox(rows: list[dict[str, Any]], page_rect: PageRect) -> BBox:
    bbox = union_bboxes([row["bbox"] for row in rows])
    return (
        max(page_rect.x0, bbox[0] - 4),
        max(page_rect.y0, bbox[1] - 2),
        min(page_rect.x1, bbox[2] + 4),
        min(page_rect.y1, bbox[3] + 2),
    )


def merge_overlapping_algorithm_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    merged: list[TextBlock] = []
    for block in sorted(blocks, key=lambda candidate: (candidate.bbox[1], candidate.bbox[0])):
        if merged and overlap_ratio(block.bbox, merged[-1].bbox) > 0.85:
            previous = merged[-1]
            merged[-1] = TextBlock(
                page=previous.page,
                bbox=union_bboxes([previous.bbox, block.bbox]),
                text=normalize_block_lines([previous.text, block.text]),
                kind=previous.kind,
            )
            continue
        merged.append(block)
    return merged


def classify_algorithm_row(
    row: list[dict[str, Any]],
    page_rect: PageRect,
) -> AlgorithmRow | None:
    text = row_text(row)
    if not text or re.fullmatch(r"\d{1,4}", text):
        return None
    if looks_like_formula_boundary_prose(text) and not row_has_algorithm_marker(text):
        return None

    hit_boxes: list[BBox] = []
    score = algorithm_text_score(text)
    for segment in row:
        segment_text = normalize_text(str(segment.get("text", "")))
        if algorithm_segment_score(segment_text) >= 2:
            hit_boxes.append(tuple(float(value) for value in segment["bbox"]))

    if not hit_boxes and score < 3:
        return None

    bbox = union_bboxes(hit_boxes) if hit_boxes else union_bboxes([segment["bbox"] for segment in row])
    width = bbox[2] - bbox[0]
    if width > page_rect.width * 0.92 and not row_has_algorithm_marker(text):
        return None

    strong = row_has_algorithm_marker(text) or score >= 4
    return AlgorithmRow(row=row, bbox=bbox, text=text, score=score, strong=strong)


def row_has_algorithm_marker(text: str) -> bool:
    cleaned = normalize_text(text)
    return bool(
        ALGORITHM_HEADER_RE.search(cleaned)
        or ALGORITHM_IO_RE.search(cleaned)
        or ALGORITHM_IO_ANY_RE.search(cleaned)
        or ALGORITHM_LINE_NUMBER_RE.search(cleaned)
        or ALGORITHM_CONTROL_RE.search(cleaned)
    )


def algorithm_text_score(text: str) -> int:
    cleaned = normalize_text(text)
    score = algorithm_segment_score(cleaned)
    if looks_like_formula_prose(cleaned) and not row_has_algorithm_marker(cleaned):
        score -= 3
    word_count = len(re.findall(r"\b[A-Za-z]{3,}\b", cleaned))
    if word_count >= 12 and not ALGORITHM_HEADER_RE.search(cleaned):
        score -= 2
    return max(0, score)


def algorithm_segment_score(text: str) -> int:
    cleaned = normalize_text(text)
    if not cleaned:
        return 0
    score = 0
    if ALGORITHM_HEADER_RE.search(cleaned):
        score += 5
    if ALGORITHM_IO_RE.search(cleaned) or ALGORITHM_IO_ANY_RE.search(cleaned):
        score += 4
    if ALGORITHM_LINE_NUMBER_RE.search(cleaned):
        score += 3
    if ALGORITHM_CONTROL_RE.search(cleaned):
        score += 4
    if ALGORITHM_ASSIGNMENT_RE.search(cleaned):
        score += 2
    if ALGORITHM_KEYWORD_RE.search(cleaned):
        score += 2
    if looks_like_code_line(cleaned):
        score += 2
    if cleaned.startswith("//"):
        score += 2
    if re.search(r"\b(?:do|then)\s*$", cleaned, re.IGNORECASE):
        score += 2
    if re.search(r"\b(?:state|score|token|draft|verify|candidate)s?\b", cleaned, re.IGNORECASE):
        score += 1
    return score


def algorithm_group_is_block(rows: list[AlgorithmRow]) -> bool:
    if len(rows) < 2:
        return False
    text = normalize_block_lines([row.text for row in rows])
    if ALGORITHM_HEADER_RE.search(text):
        return len(rows) >= 2 and sum(1 for row in rows if row.score >= 3) >= 2
    strong_count = sum(1 for row in rows if row.strong)
    numbered_count = sum(1 for row in rows if ALGORITHM_LINE_NUMBER_RE.search(row.text))
    return strong_count >= 2 and (numbered_count >= 2 or len(rows) >= 3)


def trim_algorithm_group_bbox(rows: list[AlgorithmRow], page_rect: PageRect) -> BBox:
    bbox = union_bboxes([row.bbox for row in rows])
    x0 = max(page_rect.x0, bbox[0] - 4)
    top = max(page_rect.y0, bbox[1] - 2)
    x1 = min(page_rect.x1, bbox[2] + 4)
    bottom = min(page_rect.y1, bbox[3] + 2)
    return (x0, top, x1, bottom)


def extract_formula_blocks(
    segments: list[dict[str, Any]],
    page_number: int,
    page_rect: PageRect,
) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    boundary_prose_bboxes = formula_boundary_prose_bboxes(segments, page_rect)
    for rows in formula_row_streams(segments, page_rect):
        blocks.extend(
            extract_formula_blocks_from_rows(
                rows,
                page_number,
                page_rect,
                boundary_prose_bboxes=boundary_prose_bboxes,
            )
        )
    return merge_adjacent_formula_blocks(
        sorted(blocks, key=lambda block: (block.bbox[1], block.bbox[0])),
        page_rect,
        boundary_prose_bboxes=boundary_prose_bboxes,
    )


def formula_boundary_prose_bboxes(
    segments: list[dict[str, Any]],
    page_rect: PageRect,
) -> list[BBox]:
    bboxes: list[BBox] = []
    for row in group_segments_into_rows(segments):
        if classify_formula_row(row, page_rect) is not None:
            continue
        text = row_text(row)
        if looks_like_formula_boundary_prose(text) and not looks_like_formula_annotation_text(text):
            bboxes.append(union_bboxes([segment["bbox"] for segment in row]))
    return bboxes


def formula_row_streams(
    segments: list[dict[str, Any]],
    page_rect: PageRect,
) -> list[list[list[dict[str, Any]]]]:
    all_rows = group_segments_into_rows(segments)
    streams = formula_column_streams(segments, page_rect)
    display_segments = [
        segment
        for segment in segments
        if formula_display_segment(segment, page_rect)
    ]
    if display_segments:
        display_rows = group_segments_into_rows(display_segments)
        display_formula_rows = sum(
            1 for row in display_rows if classify_formula_row(row, page_rect) is not None
        )
        stream_formula_rows = sum(
            1
            for rows in streams
            for row in rows
            if classify_formula_row(row, page_rect) is not None
        )
        all_formula_rows = sum(1 for row in all_rows if classify_formula_row(row, page_rect) is not None)
        if (
            all_formula_rows > display_formula_rows + 2
            and not looks_like_two_column_text_flow_segments(segments, page_rect)
        ):
            return [all_rows]
        if display_formula_rows and stream_formula_rows <= display_formula_rows + 2:
            return [display_rows]

    return streams


def formula_column_streams(
    segments: list[dict[str, Any]],
    page_rect: PageRect,
) -> list[list[list[dict[str, Any]]]]:
    streams: dict[str, list[dict[str, Any]]] = {"left": [], "right": [], "full": []}
    for segment in segments:
        side = segment_column_side(tuple(float(value) for value in segment["bbox"]), page_rect.width)
        streams.setdefault(side, []).append(segment)
    return [
        rows
        for side in ("left", "right", "full")
        if (rows := group_segments_into_rows(streams.get(side, [])))
    ]


def formula_display_segment(segment: dict[str, Any], page_rect: PageRect) -> bool:
    text = normalize_text(str(segment.get("text", "")))
    if not text:
        return False
    bbox = tuple(float(value) for value in segment["bbox"])
    if looks_like_formula_noise(text) or looks_like_formula_prose(text):
        return False
    if re.fullmatch(r"\(\d{1,3}\)", text) and bbox[0] >= page_rect.width * 0.72:
        return True
    if looks_like_formula_bridge_fragment(text, bbox, page_rect):
        return True
    if is_formula_text_line(bbox, page_rect, text):
        return True
    center = (bbox[0] + bbox[2]) / 2
    if not (page_rect.width * 0.12 <= center <= page_rect.width * 0.90):
        return False
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*\([^)]{1,40}\)", text):
        return True
    return count_mathish_chars(text) >= 2 and has_formula_structure(text)


def extract_formula_blocks_from_rows(
    rows: list[list[dict[str, Any]]],
    page_number: int,
    page_rect: PageRect,
    *,
    boundary_prose_bboxes: list[BBox] | None = None,
) -> list[TextBlock]:
    classified_rows = [(row, classify_formula_row(row, page_rect)) for row in rows]
    prose_bboxes = list(boundary_prose_bboxes or [])
    prose_bboxes.extend(
        [
        union_bboxes([segment["bbox"] for segment in row])
        for row, formula_row in classified_rows
        if formula_row is None
        and not any(formula_display_segment(segment, page_rect) for segment in row)
        and looks_like_formula_boundary_prose(row_text(row))
        ]
    )
    blocks: list[TextBlock] = []
    current: list[FormulaRow] = []
    pending: list[FormulaRow] = []

    def flush_current(next_prose_bbox: BBox | None = None) -> None:
        nonlocal current
        if current and formula_group_is_display_formula(current):
            bbox = trim_formula_group_bbox(current, page_rect, next_prose_bbox)
            blocks.append(
                TextBlock(
                    page=page_number,
                    bbox=bbox,
                    text=normalize_block_lines([row.text for row in current]),
                    kind="formula",
                )
            )
        current = []

    previous_bbox: BBox | None = None
    for row, formula_row in classified_rows:
        row_bbox = union_bboxes([segment["bbox"] for segment in row])
        if formula_row is None:
            next_prose_bbox = row_bbox if looks_like_formula_boundary_prose(row_text(row)) else None
            flush_current(next_prose_bbox)
            if (
                pending
                and formula_group_is_display_formula(pending)
                and not formula_group_overlaps_boundary_prose(pending, prose_bboxes)
            ):
                current = pending
                flush_current(next_prose_bbox)
            pending = []
            previous_bbox = None
            continue

        if current:
            if previous_bbox is not None:
                boundary_prose = formula_boundary_between(previous_bbox, formula_row.bbox, prose_bboxes)
                allowed_gap = (
                    30.0
                    if not formula_row.strong
                    and looks_like_formula_bridge_fragment(formula_row.text, formula_row.bbox, page_rect)
                    else 18.0
                )
                if boundary_prose is not None:
                    flush_current(boundary_prose)
                    pending = []
                elif vertical_gap(previous_bbox, formula_row.bbox) > allowed_gap:
                    flush_current()
                    pending = []
            if not current:
                pending = []
            else:
                current.append(formula_row)
                previous_bbox = formula_row.bbox
                continue

        if formula_row.strong:
            attachable = [
                weak
                for weak in pending
                if weak_formula_row_attaches_to_strong(weak, formula_row, prose_bboxes)
            ]
            current = [*attachable, formula_row]
            pending = []
            previous_bbox = formula_row.bbox
            continue

        pending.append(formula_row)
        pending = pending[-6:]
    flush_current()
    return blocks


def formula_group_overlaps_boundary_prose(
    rows: list[FormulaRow],
    prose_bboxes: list[BBox],
) -> bool:
    if not rows:
        return False
    bbox = union_bboxes([row.bbox for row in rows])
    return any(
        vertical_gap(bbox, prose_bbox) <= 0
        and horizontal_overlap_ratio(bbox, prose_bbox) >= 0.08
        for prose_bbox in prose_bboxes
    )


def formula_boundary_between(first: BBox, second: BBox, prose_bboxes: list[BBox]) -> BBox | None:
    top = min(first[3], second[3])
    bottom = max(first[1], second[1])
    candidates = [
        prose_bbox
        for prose_bbox in prose_bboxes
        if prose_bbox[1] <= bottom + 2
        and prose_bbox[3] >= top - 2
        and horizontal_overlap_ratio(union_bboxes([first, second]), prose_bbox) >= 0.08
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda bbox: abs(bbox[1] - first[3]))


def merge_adjacent_formula_blocks(
    blocks: list[TextBlock],
    page_rect: PageRect,
    *,
    boundary_prose_bboxes: list[BBox] | None = None,
) -> list[TextBlock]:
    merged: list[TextBlock] = []
    current: TextBlock | None = None
    for block in blocks:
        if current is None:
            current = block
            continue
        if should_merge_formula_blocks(
            current,
            block,
            page_rect,
            boundary_prose_bboxes=boundary_prose_bboxes or [],
        ):
            current = TextBlock(
                page=current.page,
                bbox=union_bboxes([current.bbox, block.bbox]),
                text=normalize_text(join_wrapped_text(current.text, block.text)),
                kind="formula",
                items=[*text_block_line_items(current), *text_block_line_items(block)],
            )
            continue
        merged.append(current)
        current = block
    if current is not None:
        merged.append(current)
    return merged


def should_merge_formula_blocks(
    first: TextBlock,
    second: TextBlock,
    page_rect: PageRect,
    *,
    boundary_prose_bboxes: list[BBox] | None = None,
) -> bool:
    if first.page != second.page or first.kind != "formula" or second.kind != "formula":
        return False
    if re.search(r"\bAlgorithm\s+\d+", f"{first.text} {second.text}", re.IGNORECASE):
        return False
    if formula_boundary_between(first.bbox, second.bbox, boundary_prose_bboxes or []) is not None:
        return False
    gap = vertical_gap(first.bbox, second.bbox)
    if gap > 18:
        return False
    horizontal_gap = max(0.0, max(first.bbox[0], second.bbox[0]) - min(first.bbox[2], second.bbox[2]))
    if horizontal_gap <= max(24.0, float(page_rect.width) * 0.04):
        return True
    if horizontal_overlap_ratio(first.bbox, second.bbox) >= 0.08:
        return True
    first_center_y = bbox_center(first.bbox)[1]
    second_center_y = bbox_center(second.bbox)[1]
    return abs(first_center_y - second_center_y) <= 14 and gap <= 4


def containing_text_block_index(bbox: BBox, blocks: list[TextBlock]) -> int | None:
    for index, block in enumerate(blocks):
        if region_contains_text_block(bbox, block.bbox):
            return index
    return None


def containing_formula_block_index(bbox: BBox, formula_blocks: list[TextBlock]) -> int | None:
    return containing_text_block_index(bbox, formula_blocks)


def classify_formula_row(
    row: list[dict[str, Any]],
    page_rect: PageRect,
) -> FormulaRow | None:
    text = row_text(row)
    if not text or re.fullmatch(r"\d{1,4}", text):
        return None
    bbox = union_bboxes([segment["bbox"] for segment in row])
    score = formula_row_score(row, bbox, page_rect, text)
    if score < 3 and looks_like_formula_bridge_fragment(text, bbox, page_rect):
        score = 3
    if score < 3 and looks_like_dense_formula_fragment_row(text, bbox, page_rect):
        score = 3
    if score < 3 and looks_like_formula_continuation_row(text, bbox, page_rect):
        score = 3
    if score < 3:
        return None
    strong = is_strong_formula_row(row, bbox, page_rect, text, score)
    return FormulaRow(row=row, bbox=bbox, text=text, score=score, strong=strong)


def formula_row_score(
    row: list[dict[str, Any]],
    bbox: BBox,
    page_rect: PageRect,
    text: str,
) -> int:
    cleaned = normalize_text(text)
    if looks_like_formula_noise(cleaned) or looks_like_formula_prose(cleaned):
        return 0

    math_chars = count_mathish_chars(cleaned)
    operators = true_formula_operator_count(cleaned)
    equation_number = has_equation_number(row, page_rect)
    ascii_words = len(re.findall(r"\b[A-Za-z]{3,}\b", cleaned))
    if not equation_number and looks_like_inline_formula_fragment(cleaned, bbox, page_rect):
        return 0
    short_symbol_segments = sum(
        1
        for segment in row
        if len(normalize_text(str(segment.get("text", ""))).split()) <= 3
        and count_mathish_chars(str(segment.get("text", ""))) > 0
    )
    centered = abs(((bbox[0] + bbox[2]) / 2) - (page_rect.width / 2)) <= page_rect.width * 0.28

    score = 0
    if math_chars >= 2:
        score += 2
    if math_chars >= 6:
        score += 1
    score += min(operators, 3)
    if equation_number:
        score += 2
    if short_symbol_segments >= 2:
        score += 1
    if centered or equation_number:
        score += 1
    if ascii_words >= 6 and not equation_number:
        score -= 3
    if ascii_words >= 10 and operators < 2:
        score -= 3
    if not has_formula_structure(cleaned) and not equation_number:
        score -= 2
    return max(0, score)


def looks_like_formula_noise(text: str) -> bool:
    cleaned = normalize_text(text)
    if len(CID_GLYPH_RE.findall(cleaned)) >= 2:
        return True
    if URLISH_TEXT_RE.search(cleaned):
        return True
    if PATHLIKE_TEXT_RE.search(cleaned) and not has_math_unicode(cleaned) and "=" not in cleaned:
        return True
    if re.match(r"^(?:website|action input)\s*:", cleaned, re.IGNORECASE):
        return True
    if re.search(
        r"(?:\$[\d.,]+|/\s*1M\b|\binput tokens\b|\boutput tokens\b|"
        r"<\s*MODEL\b|\bSAMPLED HERE\b|Don[’']t paraphrase|\\dbname=)",
        cleaned,
        re.IGNORECASE,
    ):
        return True
    if looks_like_code_line(cleaned):
        return True
    if looks_like_numeric_table_row(cleaned):
        return True
    return False


def looks_like_code_line(text: str) -> bool:
    return bool(
        re.search(
            r"(?:\bdef\s+\w+\(|\breturn\b|#\s+\w|->\s*(?:List|Dict|str|int|float)\b|"
            r"\bif\s+.+(?:[:{]\s*$|\{)|==\s*[\"']|:=|\binput\s*\.\s*\w+|"
            r"github\s*\.\s*com\s*/|\binput\s*\(|"
            r"\b[a-z][A-Za-z0-9_]*\s*=\s*[A-Za-z_][A-Za-z0-9_]*\s*\(|"
            r"\b[a-z][A-Za-z0-9_]*\s*=\s*-?[A-Za-z_][A-Za-z0-9_]*\s*\.)",
            text,
        )
    )


def looks_like_numeric_table_row(text: str) -> bool:
    cleaned = normalize_text(text)
    number_count = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", cleaned))
    if number_count < 5:
        return False
    if has_math_unicode(cleaned) or re.search(r"[_=∑∏∫√±≈∂]", cleaned):
        return False
    words = len(re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", cleaned))
    if words >= 2:
        return True
    return true_formula_operator_count(cleaned) == 0


def looks_like_formula_prose(text: str) -> bool:
    cleaned = normalize_text(text)
    if cleaned.endswith(".") and re.search(r"\b(?:for\s+all|where|such\s+that)\b", cleaned):
        return True
    if re.search(r"\bfor\s+[A-Za-z]\s*=", cleaned, re.IGNORECASE):
        return True
    if re.match(
        r"^(?:where|specifically|policy|group|relative|typically|in|the|this|we|for|and|"
        r"holds?|composition)\b",
        cleaned,
        re.IGNORECASE,
    ):
        return True
    ascii_words = len(re.findall(r"\b[A-Za-z]{3,}\b", cleaned))
    if ascii_words < 5:
        return False
    if re.match(r"^\([^)]{1,24}\)\.\s+(?:We|The|This|These|It|In|For)\b", cleaned):
        return True
    if re.search(
        r"\b(?:observe|speedups?|summarization|translation|empirical|results?|task|"
        r"sampled|initialize|available|procedure|mitigate|distribution)\b",
        cleaned,
        re.IGNORECASE,
    ) and true_formula_operator_count(cleaned) <= 2:
        return True
    if re.search(
        r"\b(?:model|parameterization|emphasized|amplification|factor)\b",
        cleaned,
        re.IGNORECASE,
    ) and true_formula_operator_count(cleaned) <= 2:
        return True
    capitalized_words = len(re.findall(r"\b[A-Z][a-z]{2,}\b", cleaned))
    if "*" in cleaned and capitalized_words >= 3 and true_formula_operator_count(cleaned) <= 2:
        return True
    if looks_like_alphabetic_title_line(cleaned):
        return True
    if ascii_words >= 6 and re.search(
        r"\b(?:and|then|denote|number|tokens?|generated|assumption|variable)\b",
        cleaned,
        re.IGNORECASE,
    ):
        return True
    if (
        ascii_words >= 8
        and true_formula_operator_count(cleaned) <= 2
        and not has_math_unicode(cleaned)
        and not re.search(r"[=∑∏∫√±≈∂≤≥≠∈∉_{}]", cleaned)
    ):
        return True
    if cleaned.endswith(":") or cleaned.endswith("."):
        return True
    return False


def looks_like_inline_formula_fragment(text: str, bbox: BBox, page_rect: PageRect) -> bool:
    cleaned = normalize_text(text)
    width = bbox[2] - bbox[0]
    if width >= page_rect.width * 0.24:
        return False
    if re.search(r"\(\d{1,3}\)\s*$", cleaned):
        return False
    if re.search(r"\b(?:where|when|while|which)\b", cleaned, re.IGNORECASE):
        return True
    return bool(re.match(r"^[A-Za-z]\s*\([^)]{1,16}\)\s*=", cleaned))


def looks_like_alphabetic_title_line(text: str) -> bool:
    cleaned = normalize_text(text)
    if has_math_unicode(cleaned):
        return False
    if re.search(r"[=∑∏∫√±≈∂≤≥≠∈∉_{}()[\\]/]", cleaned):
        return False
    if re.search(r"\d", cleaned):
        return False
    words = re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", cleaned)
    if len(words) < 5:
        return False
    if true_formula_operator_count(cleaned) > 2:
        return False
    return bool(re.search(r"\s[-–—]\s", cleaned))


def looks_like_formula_boundary_prose(text: str) -> bool:
    cleaned = normalize_text(text)
    return len(re.findall(r"\b[A-Za-z]{3,}\b", cleaned)) >= 4


def looks_like_formula_annotation_text(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned or re.search(r"[.!?:;]", cleaned):
        return False
    words = re.findall(r"\b[A-Za-z]{3,}\b", cleaned)
    if not (2 <= len(words) <= 12):
        return False
    if re.match(r"^(?:where|which|this|these|the|we|in|for|as|our|it)\b", cleaned, re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"\b(?:likelihood|reward|estimate|weight|increase|decrease|accepted|rejected)\b",
            cleaned,
            re.IGNORECASE,
        )
    )


def looks_like_formula_bridge_fragment(text: str, bbox: BBox, page_rect: PageRect) -> bool:
    cleaned = normalize_text(text)
    if not cleaned or len(cleaned) > 36:
        return False
    words = [word.lower() for word in re.findall(r"\b[A-Za-z]{1,8}\b", cleaned)]
    allowed_words = {
        "d",
        "e",
        "l",
        "m",
        "p",
        "q",
        "x",
        "y",
        "z",
        "lq",
        "mp",
        "mq",
        "dpo",
        "ppo",
        "sft",
        "pi",
        "kl",
        "ref",
        "log",
        "exp",
        "min",
        "max",
    }
    if words and any(word not in allowed_words for word in words):
        return False
    has_math_signal = (
        count_mathish_chars(cleaned) > 0
        or has_math_unicode(cleaned)
        or has_formula_structure(cleaned)
        or bool(
            re.fullmatch(
                r"(?:ref|pi|kl|log|exp|min|max|d|e|l|m|p|q|x|y|z|lq|mp|mq)",
                cleaned,
                re.IGNORECASE,
            )
        )
    )
    if not has_math_signal:
        return False
    center = (bbox[0] + bbox[2]) / 2
    return page_rect.width * 0.14 <= center <= page_rect.width * 0.90


def looks_like_dense_formula_fragment_row(text: str, bbox: BBox, page_rect: PageRect) -> bool:
    cleaned = normalize_text(text)
    if not cleaned or looks_like_formula_boundary_prose(cleaned):
        return False
    center = (bbox[0] + bbox[2]) / 2
    if not (page_rect.width * 0.10 <= center <= page_rect.width * 0.92):
        return False
    words = [word.lower() for word in re.findall(r"\b[A-Za-z]{1,8}\b", cleaned)]
    allowed_words = {
        "d",
        "e",
        "l",
        "m",
        "p",
        "q",
        "x",
        "y",
        "z",
        "lq",
        "mp",
        "mq",
        "dpo",
        "ppo",
        "sft",
        "pi",
        "kl",
        "ref",
        "log",
        "exp",
        "min",
        "max",
    }
    if words and any(word not in allowed_words for word in words):
        return False
    function_terms = len(re.findall(r"[A-Za-z][A-Za-z0-9_]*\([^)]{1,40}\)", cleaned))
    operators = true_formula_operator_count(cleaned)
    return function_terms >= 2 or (function_terms >= 1 and operators >= 1)


def looks_like_formula_continuation_row(text: str, bbox: BBox, page_rect: PageRect) -> bool:
    cleaned = normalize_text(text)
    if not cleaned or len(cleaned) > 120:
        return False
    if looks_like_formula_noise(cleaned) or looks_like_formula_prose(cleaned):
        return False
    center = (bbox[0] + bbox[2]) / 2
    if not (page_rect.width * 0.10 <= center <= page_rect.width * 0.90):
        return False
    words = [word.lower() for word in re.findall(r"\b[A-Za-z]{1,12}\b", cleaned)]
    allowed_words = {
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
        "g",
        "h",
        "i",
        "j",
        "k",
        "l",
        "m",
        "n",
        "o",
        "p",
        "q",
        "r",
        "s",
        "t",
        "u",
        "v",
        "w",
        "x",
        "y",
        "z",
        "kl",
        "dpo",
        "ppo",
        "sft",
        "ref",
        "exp",
        "log",
        "min",
        "max",
        "arg",
        "std",
        "mean",
        "norm",
        "clip",
        "softmax",
        "sigmoid",
    }
    if words and any(word not in allowed_words for word in words):
        return False
    has_formula_function = bool(
        re.search(r"\b(?:exp|log|min|max|arg|std|mean|norm|clip|softmax|sigmoid)\s*\(", cleaned)
    )
    has_math_signal = (
        has_math_unicode(cleaned)
        or true_formula_operator_count(cleaned) > 0
        or has_formula_function
        or bool(re.search(r"[∑∏]", cleaned))
    )
    if not has_math_signal:
        return False
    return has_formula_structure(cleaned) or count_mathish_chars(cleaned) >= 2 or bool(
        re.search(r"[∑∏]", cleaned)
    )


def true_formula_operator_count(text: str) -> int:
    return len(FORMULA_OPERATOR_RE.findall(text)) + len(BINARY_MATH_OPERATOR_RE.findall(text))


def has_formula_structure(text: str) -> bool:
    if has_math_unicode(text):
        return True
    if re.search(r"[A-Za-z]\s*[_^][A-Za-z0-9{(]", text):
        return True
    if re.search(r"[A-Za-z]\s*\([^)]{0,80}\)", text):
        return True
    if re.search(
        r"[A-Za-z0-9)\]}]\s*(?:=|≤|≥|≠|≈|∈|∉|\+|\*|\s-\s|->|=>)\s*[A-Za-z0-9({\[]",
        text,
    ):
        return True
    if (
        true_formula_operator_count(text) >= 2
        and re.search(r"[A-Za-z]\s*\([^)]{0,80}\)\s*/\s*[A-Za-z0-9({\[]", text)
    ):
        return True
    return False


def has_math_unicode(text: str) -> bool:
    for character in text:
        codepoint = ord(character)
        if (
            0x0370 <= codepoint <= 0x03FF
            or 0x2070 <= codepoint <= 0x209F
            or 0x2100 <= codepoint <= 0x22FF
            or 0x1D400 <= codepoint <= 0x1D7FF
            or 0xF000 <= codepoint <= 0xF8FF
        ):
            return True
    return False


def count_mathish_chars(text: str) -> int:
    count = 0
    for character in text:
        codepoint = ord(character)
        if (
            0x0370 <= codepoint <= 0x03FF
            or 0x2070 <= codepoint <= 0x209F
            or 0x2100 <= codepoint <= 0x22FF
            or 0x1D400 <= codepoint <= 0x1D7FF
            or 0xF000 <= codepoint <= 0xF8FF
            or character in "_{}[]|=+-*/<>"
        ):
            count += 1
    return count


def has_equation_number(row: list[dict[str, Any]], page_rect: PageRect) -> bool:
    for segment in row:
        text = normalize_text(str(segment.get("text", "")))
        if not re.fullmatch(r"\(\d{1,3}\)", text):
            continue
        bbox = tuple(float(value) for value in segment["bbox"])
        if bbox[0] >= page_rect.width * 0.72:
            return True
    return bool(re.search(r"\(\d{1,3}\)\s*$", row_text(row)))


def is_strong_formula_row(
    row: list[dict[str, Any]],
    bbox: BBox,
    page_rect: PageRect,
    text: str,
    score: int,
) -> bool:
    if is_formula_text_line(bbox, page_rect, text):
        return True
    if score < 5:
        width = bbox[2] - bbox[0]
        centered = abs(((bbox[0] + bbox[2]) / 2) - (page_rect.width / 2)) <= page_rect.width * 0.28
        if (
            score >= 4
            and width >= page_rect.width * 0.35
            and centered
            and true_formula_operator_count(text) >= 1
            and has_formula_structure(text)
        ):
            return True
        return False
    if has_equation_number(row, page_rect):
        return True
    if true_formula_operator_count(text) >= 1 and has_formula_structure(text):
        return True
    return False


def weak_formula_row_attaches_to_strong(
    weak: FormulaRow,
    strong: FormulaRow,
    prose_bboxes: list[BBox],
) -> bool:
    if any(
        vertical_gap(weak.bbox, prose_bbox) <= 0
        and horizontal_overlap_ratio(weak.bbox, prose_bbox) >= 0.08
        for prose_bbox in prose_bboxes
    ):
        return False
    if vertical_gap(weak.bbox, strong.bbox) > 10:
        return False
    return horizontal_overlap_ratio(weak.bbox, strong.bbox) >= 0.08


def formula_group_is_display_formula(rows: list[FormulaRow]) -> bool:
    if not rows:
        return False
    if any(row.strong for row in rows):
        return True
    total_score = sum(row.score for row in rows)
    return len(rows) >= 2 and total_score >= 7


def trim_formula_group_bbox(
    rows: list[FormulaRow],
    page_rect: PageRect,
    next_prose_bbox: BBox | None = None,
) -> BBox:
    bbox = union_bboxes([row.bbox for row in rows])
    x0 = max(page_rect.x0, bbox[0] - 4)
    top = max(page_rect.y0, bbox[1] - 1)
    x1 = min(page_rect.x1, bbox[2] + 4)
    bottom = min(page_rect.y1, bbox[3] + 1)
    if next_prose_bbox is not None and next_prose_bbox[1] <= bottom + 4:
        bottom = max(top + 18, min(bottom, next_prose_bbox[1] - 3))
    return (x0, top, x1, bottom)


def is_formula_text_line(bbox: BBox, page_rect: PageRect, text: str) -> bool:
    cleaned = normalize_text(text)
    if not looks_like_display_formula_text(cleaned):
        return False
    if looks_like_inline_formula_fragment(cleaned, bbox, page_rect):
        return False

    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    if width <= 12 or height <= 6:
        return False
    if width > page_rect.width * 0.70:
        return False

    center_x = (bbox[0] + bbox[2]) / 2
    centered = abs(center_x - (page_rect.width / 2)) <= page_rect.width * 0.24
    if not centered:
        return False

    return strong_formula_syntax(cleaned)


def looks_like_display_formula_text(text: str) -> bool:
    if len(text) < 3 or len(text) > 180:
        return False
    if looks_like_formula_noise(text) or looks_like_formula_prose(text):
        return False
    if re.match(r"^(?:[•*-]|\d+[\.)])\s+", text):
        return False
    if len(text.split()) > 18:
        return False
    if re.fullmatch(r"\d{1,4}", text):
        return False
    return true_formula_operator_count(text) > 0 and has_formula_structure(text)


def strong_formula_syntax(text: str) -> bool:
    math_marks = count_mathish_chars(text) + true_formula_operator_count(text)
    alpha_tokens = len(re.findall(r"[A-Za-z]+", text))
    return math_marks >= 3 and alpha_tokens <= 14 and has_formula_structure(text)


def is_math_font(font_name: str) -> bool:
    upper = font_name.upper()
    return (
        upper.startswith("CM")
        or "MATH" in upper
        or "SYMBOL" in upper
        or "MTEXTRA" in upper
        or "STIX" in upper
    )


def count_smaller_formula_spans(spans: list[dict[str, Any]]) -> int:
    sizes = [float(span.get("size", 0) or 0) for span in spans]
    positive = [size for size in sizes if size > 0]
    if len(positive) < 2:
        return 0
    largest = max(positive)
    return sum(1 for size in positive if size <= largest * 0.78)


def split_text(text: str, max_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = sentence if not current else f"{current} {sentence}"
        if current and len(candidate.split()) > max_words:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    final: list[str] = []
    for chunk in chunks:
        if len(chunk.split()) <= max_words + 20:
            final.append(chunk)
            continue
        tokens = chunk.split()
        for start in range(0, len(tokens), max_words):
            final.append(" ".join(tokens[start : start + max_words]))
    return final


def split_text_block_by_items(
    block: TextBlock,
    max_words: int,
    page_width: float | None = None,
) -> list[tuple[str, BBox | None, list[dict[str, Any]]]]:
    items = text_block_line_items(block)
    if len(items) <= 1:
        return [
            (text, block.bbox, text_block_line_items(block))
            for text in split_text(block.text, max_words)
        ]

    chunks: list[tuple[str, BBox | None, list[dict[str, Any]]]] = []
    current_text = ""
    current_items: list[dict[str, Any]] = []
    current_words = 0
    target_words = max(24, max_words)

    for item in items:
        item_text = normalize_text(str(item.get("text", "")))
        item_bbox = tuple(float(value) for value in item.get("bbox", block.bbox))
        if not item_text:
            continue
        item_words = len(item_text.split())
        would_exceed = current_words > 0 and current_words + item_words > target_words
        if would_exceed and should_close_line_item_chunk(current_text, current_words, target_words):
            chunks.append(
                (
                    current_text,
                    safe_text_chunk_bbox(current_items, page_width),
                    current_items,
                )
            )
            current_text = ""
            current_items = []
            current_words = 0

        current_text = item_text if not current_text else join_wrapped_text(current_text, item_text)
        current_items.append({"text": item_text, "bbox": item_bbox})
        current_words += item_words

    if current_text and current_items:
        chunks.append(
            (
                current_text,
                safe_text_chunk_bbox(current_items, page_width),
                current_items,
            )
        )
    return chunks or [(block.text, block.bbox, text_block_line_items(block))]


def safe_text_chunk_bbox(
    items: list[dict[str, Any]],
    page_width: float | None,
) -> BBox | None:
    boxes = [
        tuple(float(value) for value in item["bbox"])
        for item in items
        if item.get("bbox") is not None
    ]
    if not boxes:
        return None
    if text_block_items_span_columns(items, page_width):
        return None
    return union_bboxes(boxes)


def text_block_items_span_columns(
    items: list[dict[str, Any]],
    page_width: float | None,
) -> bool:
    if not page_width or page_width <= 0:
        return False
    left = 0
    right = 0
    for item in items:
        bbox = item.get("bbox")
        if bbox is None:
            continue
        side = segment_column_side(tuple(float(value) for value in bbox), page_width)
        if side == "left":
            left += 1
        elif side == "right":
            right += 1
    return left > 0 and right > 0


def text_block_line_items(block: TextBlock) -> list[dict[str, Any]]:
    if block.items:
        return block.items
    return [{"text": block.text, "bbox": block.bbox}]


def should_close_line_item_chunk(
    text: str,
    word_count: int,
    target_words: int,
) -> bool:
    if word_count >= target_words:
        return True
    if word_count >= int(target_words * 0.72) and re.search(r"[.!?:;)]$", text):
        return True
    return word_count >= int(target_words * 0.85)


def order_page_cards_for_reader(
    cards: list[Card],
    *,
    page_number: int,
    page_width: float,
) -> list[Card]:
    """Insert pre-extracted visuals into the already ordered text stream for a page."""

    movable_visuals = [
        card
        for card in cards
        if card.page == page_number and card.kind in {"table", "figure"} and card.image_id
    ]
    if not movable_visuals:
        return cards

    text_stream = [card for card in cards if card not in movable_visuals]
    if not text_stream:
        return cards

    visual_set = set(id(card) for card in movable_visuals)
    untouched_prefix = [card for card in cards if card.page != page_number]
    if untouched_prefix:
        page_cards = [card for card in cards if card.page == page_number]
        ordered_page = order_page_cards_for_reader(
            page_cards,
            page_number=page_number,
            page_width=page_width,
        )
        return [*untouched_prefix, *ordered_page]

    minimum_anchor = first_page_visual_minimum_anchor(text_stream, page_number)
    placements: dict[int, list[Card]] = {}
    for visual in sorted(movable_visuals, key=visual_position_key):
        anchor = visual_anchor_index(visual, text_stream, page_width)
        anchor = max(anchor, minimum_anchor)
        anchor = min(anchor, len(text_stream))
        placements.setdefault(anchor, []).append(visual)

    ordered: list[Card] = []
    for index in range(len(text_stream) + 1):
        ordered.extend(sorted(placements.get(index, []), key=visual_position_key))
        if index < len(text_stream):
            ordered.append(text_stream[index])

    # Preserve any unexpected duplicate object that was not handled above.
    handled = {id(card) for card in ordered}
    return [*ordered, *[card for card in cards if id(card) not in handled and id(card) not in visual_set]]


def first_page_visual_minimum_anchor(text_stream: list[Card], page_number: int) -> int:
    if page_number != 1:
        return 0
    for index, card in enumerate(text_stream):
        if card.kind == "heading" and normalized_key(card.text) == "abstract":
            for following_index in range(index + 1, len(text_stream)):
                if text_stream[following_index].kind == "paragraph":
                    return following_index + 1
            return index + 1
    return 1 if text_stream else 0


def visual_anchor_index(visual: Card, text_stream: list[Card], page_width: float) -> int:
    if visual.bbox is None:
        return len(text_stream)
    anchor = 0
    for index, card in enumerate(text_stream):
        if card.bbox is None:
            continue
        if card_precedes_visual(card, visual, page_width):
            anchor = index + 1
    return anchor


def card_precedes_visual(card: Card, visual: Card, page_width: float) -> bool:
    if card.bbox is None or visual.bbox is None:
        return False
    card_top = card.bbox[1]
    visual_top = visual.bbox[1]
    card_bottom = card.bbox[3]
    if card_bottom <= visual_top + 3.0:
        return True
    card_side = segment_column_side(card.bbox, page_width)
    visual_side = segment_column_side(visual.bbox, page_width)
    if "full" in {card_side, visual_side}:
        return card_top <= visual_top
    if card_side == visual_side:
        return card_top <= visual_top
    return False


def visual_position_key(card: Card) -> tuple[float, float, str]:
    if card.bbox is None:
        return (float("inf"), float("inf"), card.id)
    return (card.bbox[1], card.bbox[0], card.id)


def smooth_reader_cards(cards: list[Card], max_words_per_card: int) -> list[Card]:
    """Apply a conservative reader-oriented cleanup pass to paragraph cards."""
    formula_cards = [card for card in cards if card.kind == "formula" and card.bbox is not None]
    smoothed: list[Card] = []
    for card in cards:
        text = strip_orphan_math_prefix(normalize_text(card.text))
        if card.kind == "paragraph" and looks_like_reader_noise(text):
            continue
        if card.kind == "paragraph" and looks_like_formula_adjacent_fragment(card, formula_cards):
            continue
        kind = card.kind
        if kind == "heading" and not looks_like_heading(text):
            kind = "paragraph"
        candidate = Card(
            id=card.id,
            kind=kind,
            page=card.page,
            section=card.section,
            text=text,
            image_id=card.image_id,
            source_image_id=card.source_image_id,
            bbox=card.bbox,
            items=card.items,
        )
        if (
            candidate.kind == "paragraph"
            and smoothed
            and should_merge_reader_cards(smoothed[-1], candidate, max_words_per_card)
        ):
            smoothed[-1] = merge_reader_cards(smoothed[-1], candidate)
            continue
        smoothed.append(candidate)

    result: list[Card] = []
    for index, card in enumerate(smoothed, start=1):
        result.append(
            Card(
                id=f"card-{index}",
                kind=card.kind,
                page=card.page,
                section=card.section if card.kind != "paragraph" else normalize_section(card.section),
                text=card.text,
                image_id=card.image_id,
                source_image_id=card.source_image_id,
                bbox=card.bbox,
                items=card.items,
            )
        )
    return result


def sanitize_cross_column_card_bboxes(
    cards: list[Card],
    page_widths: dict[int, float],
) -> list[Card]:
    sanitized: list[Card] = []
    for card in cards:
        page_width = page_widths.get(card.page)
        bbox = card.bbox
        if card.items and page_width and text_block_items_span_columns(card.items, page_width):
            bbox = None
        sanitized.append(
            Card(
                id=card.id,
                kind=card.kind,
                page=card.page,
                section=card.section,
                text=card.text,
                image_id=card.image_id,
                source_image_id=card.source_image_id,
                bbox=bbox,
                items=card.items,
            )
        )
    return sanitized


def should_merge_reader_cards(first: Card, second: Card, max_words_per_card: int) -> bool:
    if first.kind != "paragraph" or second.kind != "paragraph":
        return False
    if first.image_id or second.image_id:
        return False
    if first.page != second.page or first.section != second.section:
        return False
    total_words = len(first.text.split()) + len(second.text.split())
    limit = max(130, max_words_per_card + 45)
    if total_words > limit:
        return False
    if starts_new_caption(second.text) or looks_like_heading(second.text):
        return False
    if is_list_or_bullet_start(second.text) and len(first.text.split()) >= 20:
        return False
    if first.bbox is None or second.bbox is None:
        return False
    if first.bbox and second.bbox:
        if first.bbox[0] > second.bbox[2] and second.bbox[1] >= first.bbox[1]:
            return False
        if second.bbox[0] > first.bbox[2] and second.bbox[1] > first.bbox[1] - 160:
            return False

    if first.section == "Document" and first.page == 1:
        return True
    if len(first.text.split()) <= 14 or len(second.text.split()) <= 14:
        return True
    if starts_with_continuation_word(second.text):
        return True
    if not re.search(r"[.!?)]$", first.text):
        return True
    if first.bbox and second.bbox:
        gap = vertical_gap(first.bbox, second.bbox)
        if gap <= 18 and horizontal_overlap_ratio(first.bbox, second.bbox) >= 0.20:
            return True
    return False


def merge_reader_cards(first: Card, second: Card) -> Card:
    return Card(
        id=first.id,
        kind="paragraph",
        page=first.page,
        section=first.section,
        text=join_reader_text(first.text, second.text),
        source_image_id=first.source_image_id or second.source_image_id,
        bbox=union_optional_bboxes(first.bbox, second.bbox),
        items=[*first.items, *second.items],
    )


def join_reader_text(first: str, second: str) -> str:
    first = normalize_text(first)
    second = normalize_text(second)
    return normalize_text(join_wrapped_text(first, second))


def join_wrapped_text(first: str, second: str) -> str:
    if first.endswith("-") and second and second[0].islower():
        if should_dehyphenate_line_wrap(first, second):
            return first[:-1] + second
        return first + second
    return f"{first} {second}"


def should_dehyphenate_line_wrap(first: str, second: str) -> bool:
    previous = re.search(r"([A-Za-z]+)-$", first)
    if previous is None or not re.match(r"^[a-z]", second):
        return False
    fragment = previous.group(1)
    if len(fragment) <= 3:
        return False
    return True


def union_optional_bboxes(first: BBox | None, second: BBox | None) -> BBox | None:
    boxes = [bbox for bbox in (first, second) if bbox is not None]
    if not boxes:
        return None
    return union_bboxes(boxes)


def normalize_section(section: str) -> str:
    cleaned = normalize_text(section)
    if not cleaned or looks_like_reader_noise(cleaned) or not looks_like_heading(cleaned):
        return "Document"
    return cleaned


def looks_like_reader_noise(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return True
    if CID_GLYPH_RE.search(cleaned):
        return True
    if looks_like_visual_label_noise(cleaned):
        return True
    if looks_like_encoded_gibberish(cleaned):
        return True
    if re.fullmatch(r"[\W_]+", cleaned):
        return True
    if looks_like_standalone_math_scrap(cleaned):
        return True
    return False


def looks_like_standalone_math_scrap(text: str) -> bool:
    cleaned = normalize_text(text)
    if re.fullmatch(r"\(?\s*\d{1,3}\s*\)", cleaned):
        return True
    if len(cleaned) > 20:
        return False
    words = re.findall(r"\b[A-Za-z]\b", cleaned)
    if words and len(words) == len(re.findall(r"\b[A-Za-z]+\b", cleaned)):
        return True
    return bool(
        re.fullmatch(r"[A-Za-z0-9\s_+\-−=∼<>≤≥().,]+", cleaned)
        and (has_math_unicode(cleaned) or true_formula_operator_count(cleaned) > 0)
        and len(re.findall(r"\b[A-Za-z]{3,}\b", cleaned)) == 0
    )


def looks_like_formula_adjacent_fragment(card: Card, formula_cards: list[Card]) -> bool:
    if card.bbox is None or not looks_like_math_fragment_text(card.text):
        return False
    for formula in formula_cards:
        if formula.page != card.page or formula.bbox is None:
            continue
        if bboxes_are_near(card.bbox, formula.bbox, proximity=10.0):
            return True
        if vertical_gap(card.bbox, formula.bbox) <= 4.0 and horizontal_overlap_ratio(
            card.bbox,
            formula.bbox,
        ) >= 0.08:
            return True
    return False


def looks_like_math_fragment_text(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned or len(cleaned) > 48:
        return False
    if re.fullmatch(r"\(?\s*\d{1,3}\s*\)", cleaned):
        return True
    words = [word.lower() for word in re.findall(r"\b[A-Za-z]{1,12}\b", cleaned)]
    allowed_words = {
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
        "g",
        "h",
        "i",
        "j",
        "k",
        "l",
        "m",
        "n",
        "o",
        "p",
        "q",
        "r",
        "s",
        "t",
        "u",
        "v",
        "w",
        "x",
        "y",
        "z",
        "kl",
        "ref",
        "exp",
        "log",
        "min",
        "max",
        "arg",
        "std",
        "mean",
        "norm",
    }
    if words and any(word not in allowed_words for word in words):
        return False
    return has_math_unicode(cleaned) or true_formula_operator_count(cleaned) > 0


def looks_like_encoded_gibberish(text: str) -> bool:
    cleaned = normalize_text(text)
    if len(cleaned) < 24:
        return False
    alpha = [char for char in cleaned if char.isalpha()]
    if len(alpha) < 12:
        return False
    lowercase_ratio = sum(char.islower() for char in alpha) / max(1, len(alpha))
    symbol_ratio = len(re.findall(r"[][&<>/\\^_`|~]", cleaned)) / max(1, len(cleaned))
    long_upperish = bool(re.search(r"\b[A-Z0-9&\]\[<>/]{8,}\b", cleaned))
    return lowercase_ratio < 0.18 and symbol_ratio > 0.06 and long_upperish


def is_list_or_bullet_start(text: str) -> bool:
    return bool(re.match(r"^(?:[•*-]|\(?\d+[\.)])\s+", normalize_text(text)))


def merge_text_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    merged: list[TextBlock] = []
    current: TextBlock | None = None
    mergeable_kinds = {"text", "footnote"}

    for block in blocks:
        if block.kind not in mergeable_kinds:
            if current is not None:
                merged.append(current)
                current = None
            merged.append(block)
            continue
        if current is None:
            current = block
            continue
        if current.kind != block.kind:
            merged.append(current)
            current = block
            continue
        if should_merge_text_blocks(current, block):
            current = TextBlock(
                page=current.page,
                bbox=union_bboxes([current.bbox, block.bbox]),
                text=normalize_text(join_wrapped_text(current.text, block.text)),
                kind=current.kind,
                items=[*text_block_line_items(current), *text_block_line_items(block)],
            )
            continue
        merged.append(current)
        current = block

    if current is not None:
        merged.append(current)
    return merged


def should_merge_text_blocks(first: TextBlock, second: TextBlock) -> bool:
    if first.kind != second.kind or first.kind not in {"text", "footnote"}:
        return False
    if first.page != second.page:
        return False
    if first.kind == "footnote":
        gap = vertical_gap(first.bbox, second.bbox)
        x0_delta = abs(first.bbox[0] - second.bbox[0])
        overlap = horizontal_overlap_ratio(first.bbox, second.bbox)
        return gap <= 18 and (x0_delta <= 72 or overlap >= 0.25)
    if looks_like_heading(first.text) or looks_like_heading(second.text):
        return False
    first_words = len(first.text.split())
    second_words = len(second.text.split())
    first_is_incomplete = not re.search(r"[.!?:;)]$", first.text)
    first_is_short_incomplete = first_words < 25 and first_is_incomplete
    second_starts_continuation = starts_with_continuation_word(second.text)
    if first_is_incomplete and second_starts_continuation:
        if plausible_column_continuation(first.bbox, second.bbox):
            return True
    if first_words >= 85 or second_words >= 85:
        if not first_is_short_incomplete:
            return False
    gap = vertical_gap(first.bbox, second.bbox)
    if gap > 32:
        return False
    x0_delta = abs(first.bbox[0] - second.bbox[0])
    overlap = horizontal_overlap_ratio(first.bbox, second.bbox)
    if x0_delta > 44 and overlap < 0.55:
        return False
    if re.search(r"[.!?]$", first.text) and first_words >= 35:
        return False
    return True


def starts_with_continuation_word(text: str) -> bool:
    stripped = text.lstrip("\"'([{")
    return bool(stripped) and stripped[0].islower()


def plausible_column_continuation(first: BBox, second: BBox) -> bool:
    x0_delta = abs(first[0] - second[0])
    overlap = horizontal_overlap_ratio(first, second)
    if x0_delta <= 56 or overlap >= 0.50:
        return vertical_gap(first, second) <= 72
    second_is_to_the_right = second[0] > first[2] and second[1] <= first[1] - 160
    return second_is_to_the_right


def looks_like_heading(text: str) -> bool:
    text = normalize_text(text)
    if len(text) > 120:
        return False
    if starts_new_caption(text) or looks_like_visual_label_noise(text):
        return False
    section_text = re.sub(r"^[^A-Za-z0-9]+", "", text).strip()
    canonical_heading = (
        r"Abstract|Introduction|Background|Related Work|Preliminaries|Method|Methods|Approach|"
        r"Experiment|Experiments|Evaluation|Results|Discussion|Conclusion|References|Appendix|"
        r"Limitations|Dataset|Datasets|Analysis|Ablation|Implementation|Training|Inference"
    )
    if re.fullmatch(canonical_heading, text, re.IGNORECASE):
        return True
    if re.match(rf"^\d+(?:\.\d+)*\.?\s+(?:{canonical_heading})\b", text, re.IGNORECASE):
        return True
    if looks_like_numbered_section_heading(text) or looks_like_numbered_section_heading(section_text):
        return True
    if re.match(r"^[A-Z]\s+(?:[A-Z][A-Za-z]+(?:\s+|$)){1,6}$", text):
        return True
    return False


def looks_like_numbered_section_heading(text: str) -> bool:
    cleaned = normalize_text(text)
    return bool(
        re.fullmatch(
            r"\d+(?:\.\d+)+\.?\s+"
            r"[A-Z][A-Za-z0-9/&-]*(?:\s+[A-Z][A-Za-z0-9/&-]*){0,5}",
            cleaned,
        )
    )


def looks_like_visual_label_noise(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return True
    if looks_like_orphan_formula_fragment_noise(cleaned):
        return True
    if re.fullmatch(r"[.\-–—•·]+", cleaned):
        return True
    tokens = cleaned.split()
    if len(tokens) == 1 and len(cleaned) == 1 and cleaned.isalpha():
        return True
    single_char_tokens = sum(1 for token in tokens if len(token.strip(".,;:()[]{}")) == 1)
    if len(tokens) >= 3 and single_char_tokens / len(tokens) >= 0.58:
        return True
    alpha_words = re.findall(r"[A-Za-z]{2,}", cleaned)
    numeric_tokens = re.findall(r"\b\d+(?:\.\d+)?%?\b", cleaned)
    if len(numeric_tokens) >= 2 and len(alpha_words) <= 1 and len(cleaned) <= 90:
        return True
    if re.search(r"(?:^|\s)[arxiv]{1}(?:\s+[arxiv]{1}){2,}(?:\s|$)", cleaned, re.IGNORECASE):
        return True
    return False


def looks_like_orphan_formula_fragment_noise(text: str) -> bool:
    cleaned = normalize_text(text)
    if cleaned in {"ref", "old", "new"}:
        return True
    if len(cleaned.split()) > 5:
        return False
    if re.fullmatch(r"\)?\s*[A-Za-z]\([^)]{1,50}\)\s*[,.;]?", cleaned):
        return True
    return bool(
        re.fullmatch(
            r"[()[\]{}.,;:|∑∏√≠↦+\-*/<>=\s]*(?:[A-Za-z]\([^)]{1,50}\)\s*){1,3}[()[\]{}.,;:|∑∏√≠↦+\-*/<>=\s]*",
            cleaned,
        )
    )


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "pdf"


def extract_words(plumber_page: pdfplumber.page.Page) -> list[dict[str, Any]]:
    try:
        return plumber_page.extract_words(
            x_tolerance=2,
            y_tolerance=3,
            keep_blank_chars=False,
            use_text_flow=True,
        )
    except Exception:
        return []


def find_caption_lines(words: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    lines = group_words_into_lines(words)
    caption_lines: list[dict[str, Any]] = []
    for line in lines:
        caption = slice_caption_from_segment(
            line,
            prefix,
            allow_embedded=prefix.lower() in {"figure", "table"},
        )
        if caption is not None:
            caption_lines.append(caption)
    return caption_lines


def find_caption_lines_for_page(
    plumber_page: pdfplumber.page.Page,
    prefix: str,
) -> list[dict[str, Any]]:
    segments = split_chars_into_reading_order_segments(
        plumber_page.chars,
        float(plumber_page.width),
        float(plumber_page.height),
    )
    caption_lines = find_caption_lines_from_segments(segments, prefix)
    if caption_lines:
        return caption_lines
    return find_caption_lines(extract_words(plumber_page), prefix)


def find_caption_lines_from_segments(
    segments: list[dict[str, Any]],
    prefix: str,
) -> list[dict[str, Any]]:
    caption_lines: list[dict[str, Any]] = []
    for segment in segments:
        caption = slice_caption_from_segment(
            segment,
            prefix,
            allow_embedded=prefix.lower() in {"figure", "table"},
        )
        if caption is not None:
            caption_lines.append(caption)
    return caption_lines


def slice_caption_from_segment(
    segment: dict[str, Any],
    prefix: str,
    *,
    allow_embedded: bool = False,
) -> dict[str, Any] | None:
    text = repair_caption_prefix_spacing(str(segment.get("text", "")), prefix)
    anchor = r"\b" if allow_embedded else r"^"
    pattern = re.compile(
        rf"{anchor}(?i:{re.escape(prefix)})\s*{caption_number_pattern(prefix)}"
        rf"(?:[\.:]|\s*\||(?=\s+[A-Z][A-Za-z]))"
    )
    match = pattern.search(text)
    if match is None:
        return None
    if match.start() > 0 and looks_like_inline_visual_reference_prefix(text[: match.start()]):
        return None
    caption = dict(segment)
    caption["text"] = normalize_text(text[match.start() :])
    caption["bbox"] = approximate_text_slice_bbox(segment["bbox"], text, match.start(), len(text))
    caption["embedded"] = match.start() > 0
    caption["line_bbox"] = segment["bbox"]
    if match.start() > 0:
        caption["embedded_prefix"] = normalize_text(text[: match.start()])
    return caption


def caption_number_pattern(prefix: str) -> str:
    if prefix.lower() == "table":
        return r"(?:[A-Z]\s*)?\d+[A-Za-z]?"
    if prefix.lower() == "figure":
        return r"(?:[A-Z]\s*)?\d+[A-Za-z]?"
    return r"\d+"


def embedded_table_caption_has_row_prefix(caption: dict[str, Any]) -> bool:
    if not caption.get("embedded"):
        return False
    prefix = normalize_text(str(caption.get("embedded_prefix", "")))
    if not prefix:
        return False
    return line_is_tableish(prefix) or bool(re.search(r"\b\d+(?:\.\d+)?%?\b\s*$", prefix))


def looks_like_inline_visual_reference_prefix(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    return bool(
        re.search(
            r"\b(?:see|in|as|of|from|satisfies?|shown|using|via|with|and)\s*$",
            cleaned,
            re.IGNORECASE,
        )
    )


def approximate_text_slice_bbox(
    bbox: BBox,
    text: str,
    start: int,
    end: int,
) -> BBox:
    if end <= start or not text:
        return bbox
    width = bbox[2] - bbox[0]
    char_count = max(1, len(text))
    x0 = bbox[0] + width * max(0.0, min(1.0, start / char_count))
    x1 = bbox[0] + width * max(0.0, min(1.0, end / char_count))
    return (x0, bbox[1], max(x0 + 1.0, x1), bbox[3])


def clip_segment_from_x(segment: dict[str, Any], x0: float) -> dict[str, Any] | None:
    bbox = tuple(float(value) for value in segment["bbox"])
    if x0 <= bbox[0] + 1.0:
        return dict(segment)
    if x0 >= bbox[2] - 1.0:
        return None
    text = normalize_text(str(segment.get("text", "")))
    if not text:
        return None
    ratio = max(0.0, min(1.0, (x0 - bbox[0]) / max(1.0, bbox[2] - bbox[0])))
    start = min(len(text), max(0, round(len(text) * ratio)))
    clipped_text = normalize_text(text[start:])
    clipped_text = re.sub(r"^[A-Za-z]-\s+(?=[a-z]{2,}\.)", "", clipped_text)
    if not clipped_text:
        return None
    clipped = dict(segment)
    clipped["text"] = clipped_text
    clipped["bbox"] = approximate_text_slice_bbox(bbox, text, start, len(text))
    return clipped


def repair_caption_prefix_spacing(text: str, prefix: str) -> str:
    return normalize_text(
        re.sub(
            rf"^({re.escape(prefix)})((?:[A-Z]\s*)?\d+[A-Za-z]?)",
            r"\1 \2",
            text,
            flags=re.I,
        )
    )


def group_words_into_lines(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_words = sorted(words, key=lambda word: (round(float(word.get("top", 0)) / 3), word["x0"]))
    lines: list[list[dict[str, Any]]] = []
    for word in sorted_words:
        top = float(word.get("top", 0))
        if lines and abs(top - float(lines[-1][0].get("top", 0))) <= 4:
            lines[-1].append(word)
        else:
            lines.append([word])

    grouped: list[dict[str, Any]] = []
    for line_words in lines:
        text = normalize_text(" ".join(str(word.get("text", "")) for word in line_words))
        if not text:
            continue
        grouped.append(
            {
                "text": text,
                "bbox": (
                    min(float(word["x0"]) for word in line_words),
                    min(float(word["top"]) for word in line_words),
                    max(float(word["x1"]) for word in line_words),
                    max(float(word["bottom"]) for word in line_words),
                ),
            }
        )
    return grouped


def caption_near_bbox(words: list[dict[str, Any]], bbox: BBox, prefix: str) -> str:
    captions = find_caption_lines(words, prefix)
    if not captions:
        return ""
    candidates: list[tuple[float, str]] = []
    for caption in captions:
        cb = caption["bbox"]
        horizontal_overlap = max(0.0, min(bbox[2], cb[2]) - max(bbox[0], cb[0]))
        overlap_width = horizontal_overlap / max(1.0, bbox[2] - bbox[0])
        distance = min(abs(cb[3] - bbox[1]), abs(cb[1] - bbox[3]))
        if distance <= 130 and overlap_width >= 0.15:
            candidates.append((distance, caption["text"]))
    if not candidates:
        return ""
    return sorted(candidates, key=lambda item: item[0])[0][1]


def nearby_table_indexes(
    caption_index: int,
    caption_bboxes: list[BBox],
    tables: list[Any],
) -> list[int]:
    return nearby_bbox_indexes(caption_index, caption_bboxes, [table.bbox for table in tables])


def nearby_bbox_indexes(
    caption_index: int,
    caption_bboxes: list[BBox],
    bboxes: list[BBox],
) -> list[int]:
    indexes: list[int] = []
    for bbox_index, bbox in enumerate(bboxes):
        scores = [
            caption_bbox_match_score(caption_bbox, bbox)
            for caption_bbox in caption_bboxes
        ]
        compatible_scores = [
            (index, score)
            for index, score in enumerate(scores)
            if score is not None
        ]
        if not compatible_scores:
            continue
        nearest_index, nearest_score = min(compatible_scores, key=lambda item: item[1])
        if nearest_index == caption_index and nearest_score <= 260:
            indexes.append(bbox_index)
    return indexes


def caption_bbox_match_score(caption_bbox: BBox, bbox: BBox) -> float | None:
    gap = vertical_gap(caption_bbox, bbox)
    if gap > 180:
        return None
    if not caption_horizontally_matches_bbox(caption_bbox, bbox):
        return None
    caption_center = bbox_center(caption_bbox)[0]
    bbox_center_x = bbox_center(bbox)[0]
    center_distance = abs(caption_center - bbox_center_x)
    caption_is_above_table = caption_bbox[3] <= bbox[1]
    direction_penalty = 22.0 if caption_is_above_table else 0.0
    return gap * 1.6 + center_distance * 0.55 + direction_penalty


def caption_horizontally_matches_bbox(caption_bbox: BBox, bbox: BBox) -> bool:
    caption_width = caption_bbox[2] - caption_bbox[0]
    bbox_width = bbox[2] - bbox[0]
    overlap = max(0.0, min(caption_bbox[2], bbox[2]) - max(caption_bbox[0], bbox[0]))
    if overlap / max(1.0, min(caption_width, bbox_width)) >= 0.18:
        return True
    caption_center = bbox_center(caption_bbox)[0]
    bbox_center_x = bbox_center(bbox)[0]
    return abs(caption_center - bbox_center_x) <= max(60.0, min(caption_width, bbox_width) * 0.55)


def vertical_gap(first: BBox, second: BBox) -> float:
    if first[3] < second[1]:
        return second[1] - first[3]
    if second[3] < first[1]:
        return first[1] - second[3]
    return 0.0


def horizontal_overlap_ratio(first: BBox, second: BBox) -> float:
    overlap = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    return overlap / max(1.0, min(first[2] - first[0], second[2] - second[0]))


def union_bboxes(boxes: list[BBox]) -> BBox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def trim_bbox_around_blockers(bbox: BBox, blockers: list[BBox], anchor_bbox: BBox) -> BBox:
    x0, top, x1, bottom = bbox
    anchor_top, anchor_bottom = anchor_bbox[1], anchor_bbox[3]
    for blocker in blockers:
        if horizontal_overlap_ratio(bbox, blocker) < 0.20:
            continue
        if blocker[3] <= anchor_top and blocker[3] > top:
            top = max(top, blocker[3] + 8)
        elif blocker[1] >= anchor_bottom and blocker[1] < bottom:
            bottom = min(bottom, blocker[1] - 8)
    if bottom - top < 72:
        return bbox
    return (x0, top, x1, bottom)


def trim_bbox_away_from_caption(bbox: BBox, caption_bbox: BBox, minimum_gap: float) -> BBox:
    if horizontal_overlap_ratio(bbox, caption_bbox) < 0.10:
        return bbox
    x0, top, x1, bottom = bbox
    if caption_bbox[1] >= top and caption_bbox[1] <= bottom + minimum_gap:
        candidate_bottom = min(bottom, caption_bbox[1] - minimum_gap)
        if candidate_bottom - top >= 28:
            return (x0, top, x1, candidate_bottom)
    if caption_bbox[3] >= top - minimum_gap and caption_bbox[3] <= bottom:
        candidate_top = max(top, caption_bbox[3] + minimum_gap)
        if bottom - candidate_top >= 28:
            return (x0, candidate_top, x1, bottom)
    return bbox


def plumber_table_candidate(table: Any) -> TableCandidate:
    cell_count = 0
    non_empty_cells = 0
    try:
        rows = table.extract() or []
    except Exception:
        rows = []
    for row in rows:
        for cell in row:
            cell_count += 1
            if normalize_text(str(cell or "")):
                non_empty_cells += 1
    return TableCandidate(
        tuple(float(value) for value in table.bbox),
        source="pdfplumber",
        cell_count=cell_count,
        non_empty_cells=non_empty_cells,
    )


def substantial_table_bbox(bbox: BBox, page: pdfplumber.page.Page) -> bool:
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    page_area = float(page.width * page.height)
    area_ratio = (width * height) / max(1.0, page_area)
    return width >= page.width * 0.38 and height >= 70 and area_ratio >= 0.035


def useful_uncaptioned_table_candidate(
    table: TableCandidate,
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]],
    page_number: int,
) -> bool:
    if table.source == "pdfplumber" and table.cell_count:
        non_empty = table.non_empty_cells or 0
        if non_empty == 0:
            return False
        if non_empty / max(1, table.cell_count) < 0.04:
            return False
    if table.source == "gmft" and page_number == 1 and text_dense_prose_region(table.bbox, words):
        return False
    return True


def detect_uncaptioned_prompt_blocks(
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rules = long_horizontal_rules(page)
    if len(rules) < 2:
        return []

    lines = group_words_into_lines(words)
    candidates: list[dict[str, Any]] = []
    for rule_index, (upper_rule, lower_rule) in enumerate(zip(rules, rules[1:])):
        top = float(upper_rule["top"])
        bottom = float(lower_rule["top"])
        if bottom - top < 48:
            continue
        region_lines = lines_between_rules(lines, top, bottom)
        if not prompt_block_lines_are_table_like(region_lines):
            continue
        title_line = prompt_title_line_above(lines, top)
        preamble_lines: list[dict[str, Any]] = []
        preamble_title_line: dict[str, Any] | None = None
        if rule_index > 0:
            previous_top = float(rules[rule_index - 1]["top"])
            candidate_preamble_lines = lines_between_rules(lines, previous_top, top)
            if prompt_preamble_lines_are_table_like(candidate_preamble_lines):
                preamble_lines = candidate_preamble_lines
                preamble_title_line = prompt_title_line_above(lines, previous_top)
        footer_line = prompt_footer_line_below(lines, bottom)
        text_boxes = [line["bbox"] for line in [*preamble_lines, *region_lines]]
        if preamble_title_line is not None:
            text_boxes.append(preamble_title_line["bbox"])
        if title_line is not None:
            text_boxes.append(title_line["bbox"])
        if footer_line is not None:
            text_boxes.append(footer_line["bbox"])
        x0 = min(float(upper_rule["x0"]), float(lower_rule["x0"]), *(box[0] for box in text_boxes))
        x1 = max(float(upper_rule["x1"]), float(lower_rule["x1"]), *(box[2] for box in text_boxes))
        block_top = min(top, *(box[1] for box in text_boxes))
        block_bottom = max(bottom, *(box[3] for box in text_boxes))
        title_source = title_line or preamble_title_line
        title = normalize_text(str(title_source["text"])) if title_source is not None else ""
        candidates.append(
            {
                "bbox": (
                    max(0.0, x0 - 4.0),
                    max(0.0, block_top - 4.0),
                    min(float(page.width), x1 + 4.0),
                    min(float(page.height), block_bottom + 4.0),
                ),
                "caption": title or "Prompt block",
            }
        )

    return merge_prompt_block_candidates(candidates)


def long_horizontal_rules(page: pdfplumber.page.Page) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for line in getattr(page, "lines", []):
        width = float(line.get("width", 0.0))
        height = abs(float(line.get("height", 0.0)))
        if width < float(page.width) * 0.50 or height > 1.5:
            continue
        top = float(line.get("top", 0.0))
        if top < float(page.height) * 0.06:
            continue
        rules.append(line)
    return sorted(rules, key=lambda line: (float(line.get("top", 0.0)), float(line.get("x0", 0.0))))


def lines_between_rules(
    lines: list[dict[str, Any]],
    top: float,
    bottom: float,
) -> list[dict[str, Any]]:
    return [
        line
        for line in lines
        if float(line["bbox"][1]) >= top - 1.0 and float(line["bbox"][3]) <= bottom + 1.0
    ]


def prompt_block_lines_are_table_like(lines: list[dict[str, Any]]) -> bool:
    if len(lines) < 5:
        return False
    marker_count = sum(1 for line in lines if looks_like_prompt_block_marker(line["text"]))
    if marker_count < 4:
        return False
    if marker_count >= 4 and marker_count / max(1, len(lines)) >= 0.60:
        return True
    marker_ratio = marker_count / max(1, len(lines))
    compact_widths = [
        line["bbox"][2] - line["bbox"][0]
        for line in lines
        if len(normalize_text(str(line.get("text", ""))).split()) <= 4
    ]
    has_label_column = len(compact_widths) >= 3
    return marker_ratio >= 0.18 or has_label_column


def prompt_preamble_lines_are_table_like(lines: list[dict[str, Any]]) -> bool:
    if len(lines) < 2 or len(lines) > 14:
        return False
    marker_count = sum(1 for line in lines if looks_like_prompt_block_marker(line["text"]))
    if marker_count < 2:
        return False
    return marker_count / max(1, len(lines)) >= 0.20


def looks_like_prompt_block_marker(text: str) -> bool:
    cleaned = normalize_text(text)
    compact = normalized_key(cleaned)
    if "prompts" in compact:
        return True
    return bool(
        re.match(
            r"^(?:Original|Act|ReAct|Question|Answer|Thought\s*\d*|Action\s*\d+|Observation\s*\d+|"
            r"Claim|Evidence|Instruction)\b",
            cleaned,
            re.IGNORECASE,
        )
    )


def prompt_title_line_above(lines: list[dict[str, Any]], rule_top: float) -> dict[str, Any] | None:
    candidates = [
        line
        for line in lines
        if 0 <= rule_top - float(line["bbox"][3]) <= 18
        and "prompts" in normalized_key(str(line.get("text", "")))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda line: float(line["bbox"][1]))


def prompt_footer_line_below(lines: list[dict[str, Any]], rule_bottom: float) -> dict[str, Any] | None:
    candidates = [
        line
        for line in lines
        if 0 <= float(line["bbox"][1]) - rule_bottom <= 18
        and re.search(r"\bcontinued\s+on\s+next\s+page\b", normalize_text(str(line.get("text", ""))), re.I)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda line: float(line["bbox"][1]))


def merge_prompt_block_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return []
    merged: list[dict[str, Any]] = []
    current = dict(candidates[0])
    for candidate in candidates[1:]:
        current_bbox = tuple(float(value) for value in current["bbox"])
        candidate_bbox = tuple(float(value) for value in candidate["bbox"])
        same_column = horizontal_overlap_ratio(current_bbox, candidate_bbox) >= 0.75
        if same_column and vertical_gap(current_bbox, candidate_bbox) <= 12:
            current["bbox"] = union_bboxes([current_bbox, candidate_bbox])
            if not current.get("caption"):
                current["caption"] = candidate.get("caption", "")
            continue
        merged.append(current)
        current = dict(candidate)
    merged.append(current)
    return merged


def text_dense_prose_region(bbox: BBox, words: list[dict[str, Any]]) -> bool:
    inside = [
        normalize_text(str(word.get("text", "")))
        for word in words
        if word_inside_bbox(word, bbox)
    ]
    tokens = [token for token in inside if token]
    if len(tokens) < 70:
        return False
    alpha = sum(1 for token in tokens if re.search(r"[A-Za-z]{3,}", token))
    numeric = sum(1 for token in tokens if re.fullmatch(r"\d+(?:\.\d+)?%?", token))
    return alpha / max(1, len(tokens)) >= 0.55 and numeric / max(1, len(tokens)) <= 0.30


def word_inside_bbox(word: dict[str, Any], bbox: BBox) -> bool:
    return (
        safe_float(word.get("x0")) >= bbox[0]
        and safe_float(word.get("x1")) <= bbox[2]
        and safe_float(word.get("top")) >= bbox[1]
        and safe_float(word.get("bottom")) <= bbox[3]
    )


def heuristic_table_bbox(
    caption_bbox: BBox,
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]] | None = None,
    *,
    caption_text: str = "",
) -> BBox | None:
    caption_top = caption_bbox[1]
    caption_bottom = caption_bbox[3]
    above_content_bbox = infer_table_content_bbox_above_caption(caption_bbox, page, words)
    content_bbox = infer_table_content_bbox(caption_bbox, page, words, caption_text=caption_text)
    if should_prefer_below_caption_table_bbox(content_bbox, above_content_bbox, caption_bbox, page):
        return content_bbox
    if above_content_bbox is not None:
        return above_content_bbox
    if content_bbox is not None:
        return content_bbox

    x0, _, x1, _ = infer_caption_column_bbox(caption_bbox, page)
    # Most papers place table captions above the table. If the caption is too low,
    # crop above it instead of off the page.
    if caption_bottom < page.height * 0.72:
        top = min(float(page.height), caption_bottom + 8)
        bottom = infer_content_bottom_after_caption(caption_bbox, page, words)
    else:
        top = max(0.0, caption_top - min(260.0, page.height * 0.34))
        bottom = max(0.0, caption_top - 8)
    if bottom - top < 36:
        return None
    return (x0, top, x1, bottom)


def merge_plumber_and_heuristic_table_bboxes(
    plumber_bbox: BBox,
    heuristic_bbox: BBox,
    page: pdfplumber.page.Page,
) -> BBox:
    if well_ruled_column_table_would_expand_across_page(plumber_bbox, heuristic_bbox, page):
        return plumber_bbox
    return union_bboxes([plumber_bbox, heuristic_bbox])


def should_prefer_below_caption_table_bbox(
    below_bbox: BBox | None,
    above_bbox: BBox | None,
    caption_bbox: BBox,
    page: pdfplumber.page.Page,
) -> bool:
    if below_bbox is None:
        return False
    if above_bbox is None:
        return True
    gap = below_bbox[1] - caption_bbox[3]
    if not (0.0 <= gap <= 60.0):
        return False
    below_rules = horizontal_rule_count_for_bbox(page, below_bbox)
    if below_rules < 2:
        return False
    above_rules = horizontal_rule_count_for_bbox(page, above_bbox)
    return above_rules < 2


def horizontal_rule_count_for_bbox(
    page: pdfplumber.page.Page,
    bbox: BBox,
) -> int:
    count = 0
    for line in getattr(page, "lines", []):
        rule_width = float(line.get("width", 0.0))
        rule_height = abs(float(line.get("height", 0.0)))
        if rule_width < 40 or rule_height > 1.8:
            continue
        rule_bbox = (
            float(line.get("x0", 0.0)),
            float(line.get("top", 0.0)),
            float(line.get("x1", 0.0)),
            float(line.get("bottom", line.get("top", 0.0))),
        )
        rule_y = (rule_bbox[1] + rule_bbox[3]) / 2
        if bbox[1] - 6.0 <= rule_y <= bbox[3] + 6.0 and horizontal_overlap_ratio(rule_bbox, bbox) >= 0.45:
            count += 1
    return count


def infer_table_content_bbox_above_caption(
    caption_bbox: BBox,
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]] | None,
) -> BBox | None:
    if not words:
        return None

    column_bbox = infer_caption_column_bbox(caption_bbox, page)
    bbox = infer_table_content_bbox_above_caption_in_column(
        caption_bbox,
        page,
        words,
        column_bbox,
        allow_refine=True,
    )
    if bbox is not None:
        margin_x = float(page.width) * 0.05
        full_column_bbox = (margin_x, 0.0, float(page.width) - margin_x, float(page.height))
        if column_bbox != full_column_bbox and bbox[2] - bbox[0] < float(page.width) * 0.55:
            full_bbox = infer_table_content_bbox_above_caption_in_column(
                caption_bbox,
                page,
                words,
                full_column_bbox,
                allow_refine=False,
            )
            if (
                full_bbox is not None
                and full_bbox[2] - full_bbox[0] > (bbox[2] - bbox[0]) * 1.35
                and full_bbox[1] <= bbox[1] + 6.0
                and full_bbox[3] >= bbox[3] - 6.0
                and not well_ruled_column_table_would_expand_across_page(bbox, full_bbox, page)
            ):
                return full_bbox
        return bbox
    margin_x = float(page.width) * 0.05
    full_column_bbox = (margin_x, 0.0, float(page.width) - margin_x, float(page.height))
    if column_bbox == full_column_bbox:
        return None
    return infer_table_content_bbox_above_caption_in_column(
        caption_bbox,
        page,
        words,
        full_column_bbox,
        allow_refine=False,
    )


def well_ruled_column_table_would_expand_across_page(
    column_bbox: BBox,
    full_bbox: BBox,
    page: pdfplumber.page.Page,
) -> bool:
    if horizontal_rule_count_for_bbox(page, column_bbox) < 2:
        return False
    if column_bbox[2] - column_bbox[0] < float(page.width) * 0.28:
        return False
    if full_bbox[2] - full_bbox[0] <= (column_bbox[2] - column_bbox[0]) * 1.65:
        return False
    left_expansion = column_bbox[0] - full_bbox[0]
    right_expansion = full_bbox[2] - column_bbox[2]
    return max(left_expansion, right_expansion) > float(page.width) * 0.12


def infer_table_content_bbox_above_caption_in_column(
    caption_bbox: BBox,
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]],
    column_bbox: BBox,
    *,
    allow_refine: bool,
) -> BBox | None:
    caption_top = caption_bbox[1]
    scan_depth = min(520.0, float(page.height) * 0.70)
    candidate_words = [
        word
        for word in words
        if float(word.get("bottom", 0)) < caption_top - 4
        and float(word.get("top", 0)) > max(0.0, caption_top - scan_depth)
        and point_in_bbox(
            (
                (float(word["x0"]) + float(word["x1"])) / 2,
                (float(word["top"]) + float(word["bottom"])) / 2,
            ),
            column_bbox,
        )
    ]
    if allow_refine:
        content_column_bbox = refine_table_content_column_bbox(
            caption_bbox,
            page,
            candidate_words,
            column_bbox,
        )
    else:
        content_column_bbox = column_bbox
    if allow_refine and content_column_bbox != column_bbox:
        candidate_words = [
            word
            for word in candidate_words
            if point_in_bbox(
                (
                    (float(word["x0"]) + float(word["x1"])) / 2,
                    (float(word["top"]) + float(word["bottom"])) / 2,
                ),
                content_column_bbox,
            )
        ]
        column_bbox = content_column_bbox
    lines = group_words_into_lines(candidate_words)
    content_boxes: list[BBox] = []
    previous_top: float | None = None

    for line_index in range(len(lines) - 1, -1, -1):
        line = lines[line_index]
        text = line["text"]
        line_top = float(line["bbox"][1])
        line_bottom = float(line["bbox"][3])
        if content_boxes and starts_new_caption(text):
            break
        if content_boxes and line_continues_previous_caption(lines, line_index):
            break
        is_table_group_label = line_is_table_group_label_between_rows(text, lines, line_index)
        if content_boxes and line_is_body_boundary(text) and not is_table_group_label:
            break
        if not content_boxes:
            if not line_is_tableish(text):
                continue
            if caption_top - line_bottom > 64:
                continue
        elif previous_top is not None and previous_top - line_bottom > 24:
            header_gap = previous_top - line_bottom
            if len(content_boxes) >= 3 and header_gap <= 42 and line_is_tableish(text):
                content_boxes.append(line["bbox"])
                previous_top = line_top
                continue
            break

        if (
            line_is_tableish(text)
            or is_table_group_label
            or line_is_table_fragment_between_rows(text, lines, line_index)
        ):
            content_boxes.append(line["bbox"])
            previous_top = line_top
            continue
        break

    if len(content_boxes) < 3:
        return None
    ordered_boxes = list(reversed(content_boxes))
    content = expand_table_bbox_to_nearby_rules(union_bboxes(ordered_boxes), page, column_bbox)
    x0 = max(column_bbox[0], content[0] - 8)
    top = max(0.0, content[1] - 8)
    x1 = min(column_bbox[2], content[2] + 8)
    bottom = min(float(page.height), caption_top - 4.0, content[3] + 8)
    if x1 - x0 < 80 or bottom - top < 36:
        return None
    return (x0, top, x1, bottom)


def line_continues_previous_caption(
    lines: list[dict[str, Any]],
    line_index: int,
) -> bool:
    if line_index <= 0:
        return False
    current_top = float(lines[line_index]["bbox"][1])
    for previous_index in range(line_index - 1, max(-1, line_index - 4), -1):
        previous = lines[previous_index]
        previous_bbox = previous["bbox"]
        gap = current_top - float(previous_bbox[3])
        if gap < 0 or gap > 18.0:
            return False
        if starts_new_caption(previous["text"]):
            return True
        if not looks_like_caption_continuation_text(previous["text"]):
            return False
        current_top = float(previous_bbox[1])
    return False


def line_is_table_fragment_between_rows(
    text: str,
    lines: list[dict[str, Any]],
    line_index: int,
) -> bool:
    cleaned = normalize_text(text)
    if not cleaned or len(cleaned) > 120:
        return False
    words = re.findall(r"\b[A-Za-z][A-Za-z0-9]*\b", cleaned)
    single_letter_header = len(words) >= 3 and all(len(word) == 1 and word.isupper() for word in words)
    symbol_only = bool(re.fullmatch(r"""[\s"'#().,±†‡*|×✓✗∼+\-]+""", cleaned))
    if not (
        re.search(r"[±†‡*|×✓✗∼#\"()]", cleaned)
        or single_letter_header
        or symbol_only
    ):
        return False
    if re.search(r"\b(?:the|and|with|from|that|this|section|figure|table)\b", cleaned, re.IGNORECASE):
        return False
    nearby_tableish = False
    current_bbox = lines[line_index]["bbox"]
    for neighbor_index in (line_index - 1, line_index + 1):
        if neighbor_index < 0 or neighbor_index >= len(lines):
            continue
        neighbor = lines[neighbor_index]
        if abs(float(neighbor["bbox"][1]) - float(current_bbox[1])) > 24.0:
            continue
        if line_is_tableish(neighbor["text"]) or line_is_table_group_label_between_rows(
            neighbor["text"],
            lines,
            neighbor_index,
        ):
            nearby_tableish = True
            break
    if not nearby_tableish:
        return False
    long_words = [word for word in words if len(word) > 10]
    return not long_words


def expand_table_bbox_to_nearby_rules(
    content_bbox: BBox,
    page: pdfplumber.page.Page,
    column_bbox: BBox,
) -> BBox:
    x0, top, x1, bottom = content_bbox
    for line in getattr(page, "lines", []):
        rule_width = float(line.get("width", 0.0))
        rule_height = abs(float(line.get("height", 0.0)))
        if rule_width < 40 or rule_height > 1.8:
            continue
        rule_bbox = (
            float(line.get("x0", 0.0)),
            float(line.get("top", 0.0)),
            float(line.get("x1", 0.0)),
            float(line.get("bottom", line.get("top", 0.0))),
        )
        if horizontal_overlap_ratio(rule_bbox, column_bbox) < 0.35:
            continue
        if horizontal_overlap_ratio(rule_bbox, content_bbox) < 0.25:
            continue
        rule_y = (rule_bbox[1] + rule_bbox[3]) / 2
        if 0 <= top - rule_y <= 28:
            top = min(top, rule_bbox[1])
            x0 = min(x0, rule_bbox[0])
            x1 = max(x1, rule_bbox[2])
        if 0 <= rule_y - bottom <= 32:
            bottom = max(bottom, rule_bbox[3])
            x0 = min(x0, rule_bbox[0])
            x1 = max(x1, rule_bbox[2])
    return (x0, top, x1, bottom)


def infer_table_content_bbox(
    caption_bbox: BBox,
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]] | None,
    *,
    caption_text: str = "",
) -> BBox | None:
    if not words:
        return None

    column_bbox = infer_caption_column_bbox(caption_bbox, page)
    caption_bottom = caption_bbox[3]
    prose_table_mode = looks_like_prompt_table_caption(caption_text)
    max_scan_depth = min(560.0, page.height * 0.72)
    default_bottom = min(float(page.height), caption_bottom + max_scan_depth)
    candidate_words = [
        word
        for word in words
        if caption_bottom + 4 < float(word.get("top", 0)) < default_bottom
        and point_in_bbox(
            (
                (float(word["x0"]) + float(word["x1"])) / 2,
                (float(word["top"]) + float(word["bottom"])) / 2,
            ),
            column_bbox,
        )
    ]
    lines = group_words_into_lines(candidate_words)
    content_boxes: list[BBox] = []
    last_bottom = 0.0

    for line in lines:
        line_top = float(line["bbox"][1])
        line_bottom = float(line["bbox"][3])
        if looks_like_page_number_line(line["text"], line["bbox"], page):
            break
        if starts_new_caption(line["text"]) and line_top > caption_bottom + 22:
            break
        if (
            not content_boxes
            and line_top - caption_bottom <= 42.0
            and looks_like_caption_continuation_text(line["text"])
        ):
            continue
        allowed_gap = 24.0 if prose_table_mode else 30.0
        if content_boxes and line_top - last_bottom > allowed_gap:
            break
        if content_boxes and line_is_body_boundary(line["text"]) and not prose_table_mode:
            break
        if line_is_tableish(line["text"]):
            if prose_table_mode and looks_like_prompt_table_row(line["text"]):
                prose_table_mode = True
            content_boxes.append(line["bbox"])
            last_bottom = line_bottom
            continue
        if prose_table_mode and looks_like_prompt_table_row(line["text"]):
            content_boxes.append(line["bbox"])
            last_bottom = line_bottom
            continue
        if table_cell_continuation_line(line["text"], line["bbox"], content_boxes, last_bottom):
            content_boxes.append(line["bbox"])
            last_bottom = line_bottom
            continue
        if content_boxes:
            if prose_table_mode:
                content_boxes.append(line["bbox"])
                last_bottom = line_bottom
                continue
            break

    if not content_boxes:
        return None

    content = expand_table_bbox_to_nearby_rules(union_bboxes(content_boxes), page, column_bbox)
    x0 = max(column_bbox[0], content[0] - 8)
    top = max(0.0, content[1] - 8)
    x1 = min(column_bbox[2], content[2] + 8)
    bottom = min(float(page.height), content[3] + 8)
    if x1 - x0 < 80 or bottom - top < 30:
        return None
    return (x0, top, x1, bottom)


def table_cell_continuation_line(
    text: str,
    bbox: BBox,
    content_boxes: list[BBox],
    last_bottom: float,
) -> bool:
    if not content_boxes:
        return False
    if starts_new_caption(text) or line_is_body_boundary(text):
        return False
    if float(bbox[1]) - last_bottom > 8.0:
        return False
    cleaned = normalize_text(text)
    if not cleaned or len(cleaned.split()) > 18:
        return False
    current_content_bbox = union_bboxes(content_boxes)
    if horizontal_overlap_ratio(current_content_bbox, bbox) >= 0.12:
        return True
    return abs(bbox[0] - current_content_bbox[0]) <= 36 or abs(bbox[2] - current_content_bbox[2]) <= 36


def infer_caption_column_bbox(caption_bbox: BBox, page: pdfplumber.page.Page) -> BBox:
    margin_x = page.width * 0.05
    caption_width = caption_bbox[2] - caption_bbox[0]
    caption_center = (caption_bbox[0] + caption_bbox[2]) / 2
    if caption_width < page.width * 0.45:
        if caption_center < page.width / 2:
            return (margin_x, 0.0, page.width * 0.49, float(page.height))
        return (page.width * 0.51, 0.0, page.width - margin_x, float(page.height))
    return (margin_x, 0.0, page.width - margin_x, float(page.height))


def refine_table_content_column_bbox(
    caption_bbox: BBox,
    page: pdfplumber.page.Page,
    candidate_words: list[dict[str, Any]],
    column_bbox: BBox,
) -> BBox:
    caption_width = caption_bbox[2] - caption_bbox[0]
    if caption_width < float(page.width) * 0.55 or len(candidate_words) < 8:
        return column_bbox

    gap = largest_horizontal_word_gap(candidate_words, page)
    if gap is None:
        return column_bbox
    left_edge, right_edge = gap
    gap_width = right_edge - left_edge
    if gap_width < max(14.0, float(page.width) * 0.024):
        return column_bbox

    gap_center = (left_edge + right_edge) / 2
    caption_center = bbox_center(caption_bbox)[0]
    if abs(caption_center - gap_center) < float(page.width) * 0.085:
        return column_bbox
    if caption_center < gap_center:
        return (column_bbox[0], column_bbox[1], min(column_bbox[2], gap_center + 6.0), column_bbox[3])
    return (max(column_bbox[0], gap_center - 6.0), column_bbox[1], column_bbox[2], column_bbox[3])


def largest_horizontal_word_gap(
    words: list[dict[str, Any]],
    page: pdfplumber.page.Page,
) -> tuple[float, float] | None:
    intervals = sorted(
        (float(word["x0"]), float(word["x1"]))
        for word in words
        if float(word["x1"]) > float(word["x0"])
    )
    if len(intervals) < 2:
        return None

    merged: list[list[float]] = []
    for x0, x1 in intervals:
        if not merged or x0 > merged[-1][1] + 1.0:
            merged.append([x0, x1])
        else:
            merged[-1][1] = max(merged[-1][1], x1)

    page_width = float(page.width)
    best_gap: tuple[float, float] | None = None
    best_width = 0.0
    for left, right in zip(merged, merged[1:]):
        gap_left = left[1]
        gap_right = right[0]
        gap_center = (gap_left + gap_right) / 2
        if not (page_width * 0.34 <= gap_center <= page_width * 0.72):
            continue
        gap_width = gap_right - gap_left
        if gap_width > best_width:
            best_width = gap_width
            best_gap = (gap_left, gap_right)
    return best_gap


def infer_content_bottom_after_caption(
    caption_bbox: BBox,
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]] | None,
) -> float:
    caption_bottom = caption_bbox[3]
    default_bottom = min(float(page.height), caption_bottom + min(230.0, page.height * 0.30))
    if not words:
        return default_bottom

    lines = [
        line
        for line in group_words_into_lines(words)
        if line["bbox"][1] > caption_bottom + 6
    ]
    seen_content = False
    last_content_bottom = 0.0

    for line in lines:
        line_top = float(line["bbox"][1])
        line_bottom = float(line["bbox"][3])
        if line_top > default_bottom:
            break
        text = line["text"]
        if starts_new_caption(text) and line_top > caption_bottom + 22:
            return max(caption_bottom + 36, line_top - 8)
        if line_is_tableish(text):
            seen_content = True
            last_content_bottom = line_bottom
            continue
        if seen_content and line_is_body_boundary(text):
            return max(caption_bottom + 36, line_top - 8)
        if seen_content:
            last_content_bottom = line_bottom

    if last_content_bottom:
        return min(default_bottom, last_content_bottom + 10)
    return default_bottom


def starts_new_caption(text: str) -> bool:
    return bool(
        re.match(
            r"^(?:(?i:Figure)\s*(?:[A-Z]\s*)?\d+[A-Za-z]?|"
            r"(?i:Table)\s*(?:[A-Z]\s*)?\d+[A-Za-z]?)"
            r"(?:[\.:]|\s*\||(?=\s+[A-Z][A-Za-z]))",
            normalize_text(text),
        )
    )


def line_is_tableish(text: str) -> bool:
    cleaned = normalize_text(text)
    if looks_like_prompt_table_row(cleaned):
        return True
    numeric_tokens = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", cleaned))
    token_count = len(cleaned.split())
    has_table_terms = bool(
        re.search(
            r"\b(Model|Acc|F1|Cost|Latency|Version|Server|Tool|Method|Dataset|Benchmark|Score|"
            r"Task|Example|Component|Memory|Time|Gradient|Filter|Loss|Approx|Setting|Alpha|"
            r"Temp|Baseline|Optimizer|Epochs?|Architecture|Params?|Parameters?|BLEU|MET|TER|"
            r"METEOR|ROUGE|Schedule|Warmup|Beam|Penalty|Adaptation|Hyperparameters?|Trainable|"
            r"LR)\b",
            cleaned,
            re.IGNORECASE,
        )
    )
    has_url = "http://" in cleaned or "https://" in cleaned or "github.com" in cleaned
    compact_table_label = token_count <= 6 and bool(
        re.search(r"\b(?:CCE|LoRA|GPT|T5|LAMDA|MNLI|Qwen|Gemma|Mistral|Phi)\b", cleaned)
    )
    return numeric_tokens >= 1 or has_table_terms or has_url or compact_table_label


def line_is_table_group_label_between_rows(
    text: str,
    lines: list[dict[str, Any]],
    line_index: int,
) -> bool:
    if not line_is_compact_table_group_label(text, allow_heading_label=True):
        return False
    return (
        nearby_line_is_tableish(lines, line_index, -1)
        and nearby_line_is_tableish(lines, line_index, 1)
    )


def line_is_compact_table_group_label(
    text: str,
    *,
    allow_heading_label: bool = False,
) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    if starts_new_caption(cleaned) or looks_like_numbered_section_heading(cleaned):
        return False
    if looks_like_heading(cleaned) and not allow_heading_label:
        return False
    if re.search(r"[.!?:;,]$", cleaned):
        return False
    tokens = cleaned.split()
    if not (1 <= len(tokens) <= 3):
        return False
    if any(len(token) > 18 for token in tokens):
        return False
    if not all(re.fullmatch(r"[A-Za-z][A-Za-z&/-]*", token) for token in tokens):
        return False
    return True


def nearby_line_is_tableish(
    lines: list[dict[str, Any]],
    line_index: int,
    direction: int,
) -> bool:
    if direction == 0:
        return False
    current_bbox = lines[line_index]["bbox"]
    current_top = float(current_bbox[1])
    current_bottom = float(current_bbox[3])
    next_index = line_index + direction
    while 0 <= next_index < len(lines):
        line = lines[next_index]
        line_top = float(line["bbox"][1])
        line_bottom = float(line["bbox"][3])
        gap = (
            current_top - line_bottom
            if direction < 0
            else line_top - current_bottom
        )
        if gap > 26:
            return False
        text = line["text"]
        if line_is_body_boundary(text):
            return False
        if line_is_tableish(text):
            return True
        if not line_is_compact_table_group_label(text):
            return False
        current_top = line_top
        current_bottom = line_bottom
        next_index += direction
    return False


def looks_like_caption_continuation_text(text: str) -> bool:
    cleaned = normalize_text(text)
    if len(re.findall(r"\b[A-Za-z]{3,}\b", cleaned)) < 3:
        return False
    if re.search(
        r"\b(?:respectively\d*|denotes?|reports?|results?|averaged|continued)\b",
        cleaned,
        re.IGNORECASE,
    ):
        return True
    return bool(cleaned.endswith(".") and cleaned[:1].islower())


def looks_like_prompt_table_caption(text: str) -> bool:
    cleaned = normalize_text(text)
    return bool(
        re.search(
            r"\b(?:Example\s+)?(?:trajector(?:y|ies)|prompt(?:ing|s)?|demonstrations?|"
            r"reasoning\s+trace|action\s+trace|webshop|alfworld)\b",
            cleaned,
            re.IGNORECASE,
        )
    )


def looks_like_prompt_table_row(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    if re.search(
        r"\b(?:Instruction|Action|Observation|Thought|Score|Price|Rating|Description|Features|"
        r"Reviews|Buy\s*Now)\s*:",
        cleaned,
        re.IGNORECASE,
    ):
        return True
    if re.search(r"\b(?:click|search|think|finish)\s*(?:\[|\()", cleaned, re.IGNORECASE):
        return True
    if cleaned.count("[") + cleaned.count("]") >= 2:
        return True
    if re.search(r"\(cid:\d+\)", cleaned):
        return True
    compact = re.sub(r"\s+", "", cleaned)
    if len(compact) >= 24 and re.search(r"[a-z][A-Z]|[a-z][0-9]|[0-9][A-Za-z]", compact):
        return True
    return False


def looks_like_page_number_line(
    text: str,
    bbox: BBox,
    page: pdfplumber.page.Page,
) -> bool:
    cleaned = normalize_text(text)
    if not re.fullmatch(r"\d{1,4}", cleaned):
        return False
    return bbox[1] >= float(page.height) * 0.88


def line_is_body_boundary(text: str) -> bool:
    cleaned = normalize_text(text)
    token_count = len(cleaned.split())
    if looks_like_standalone_heading_boundary(cleaned):
        return True
    if line_is_tableish(cleaned):
        return False
    if looks_like_compact_math_table_row(cleaned):
        return False
    starts_like_prose = bool(
        re.match(
            r"^(A|An|The|This|These|We|In|For|As|Our|To|It|However|Overall|Results?)\b",
            cleaned,
            re.IGNORECASE,
        )
    )
    sentence_like = bool(re.search(r"[.!?]$", cleaned))
    return token_count >= 8 and (starts_like_prose or sentence_like or "," in cleaned)


def looks_like_standalone_heading_boundary(text: str) -> bool:
    cleaned = normalize_text(text)
    if looks_like_heading(cleaned):
        return True
    return bool(
        re.fullmatch(
            r"\d+\.?\s+[A-Z][A-Za-z0-9/&-]*(?:\s+[A-Z][A-Za-z0-9/&-]*){0,5}",
            cleaned,
        )
    )


def looks_like_compact_math_table_row(text: str) -> bool:
    cleaned = normalize_text(text)
    token_count = len(cleaned.split())
    if token_count == 0 or token_count > 22:
        return False
    if re.search(r"[=≤≥≈∼∑∏√∈∉|_{}]", cleaned):
        return True
    return bool(re.search(r"\b[A-Za-z]\s*,\s*(?:\.\.\.|…)\s*,\s*[A-Za-z]\b", cleaned))


def heuristic_figure_bbox(
    caption_bbox: BBox,
    page: pdfplumber.page.Page,
    pdf_page: PdfiumPage | None = None,
    words: list[dict[str, Any]] | None = None,
) -> BBox | None:
    if pdf_page is not None:
        visual_bbox = infer_graphic_content_bbox(caption_bbox, page, pdf_page, words)
        if visual_bbox is not None:
            return visual_bbox

    return broad_figure_bbox_without_caption(caption_bbox, page, pdf_page)


def infer_graphic_content_bbox(
    caption_bbox: BBox,
    plumber_page: pdfplumber.page.Page,
    pdf_page: PdfiumPage,
    words: list[dict[str, Any]] | None,
) -> BBox | None:
    caption_region = scale_plumber_bbox_to_page(caption_bbox, plumber_page, pdf_page)
    search_band = figure_search_band(caption_region, pdf_page.rect)
    if search_band[3] - search_band[1] < 36:
        return None

    visual_boxes = collect_visual_primitive_bboxes(pdf_page, search_band)
    clusters = [
        cluster
        for cluster in cluster_bboxes(visual_boxes, proximity=18.0)
        if substantial_visual_cluster(union_bboxes(cluster), pdf_page.rect)
    ]
    if not clusters:
        return None

    cluster = max(
        clusters,
        key=lambda boxes: visual_cluster_score(union_bboxes(boxes), caption_region),
    )
    visual_bbox = union_bboxes(cluster)
    text_boxes = nearby_graphic_text_bboxes(
        words or extract_words(plumber_page),
        visual_bbox,
        search_band,
        caption_region=caption_region,
    )
    if text_boxes:
        visual_bbox = union_bboxes([visual_bbox, *text_boxes])
    return pad_bbox(visual_bbox, pdf_page.rect, x_padding=4.0, y_padding=4.0)


def broad_figure_bbox_without_caption(
    caption_bbox: BBox,
    page: pdfplumber.page.Page,
    pdf_page: PdfiumPage | None,
) -> BBox | None:
    if pdf_page is not None:
        page_width = float(pdf_page.rect.width)
        page_height = float(pdf_page.rect.height)
        caption_region = scale_plumber_bbox_to_page(caption_bbox, page, pdf_page)
    else:
        page_width = float(page.width)
        page_height = float(page.height)
        caption_region = caption_bbox

    x0 = max(0.0, page_width * 0.05)
    x1 = min(page_width, page_width * 0.95)
    caption_top = caption_region[1]
    caption_bottom = caption_region[3]
    if caption_top > page_height * 0.24:
        lookback = 210.0 if caption_top < page_height * 0.55 else 370.0
        top = max(0.0, caption_top - min(lookback, page_height * 0.48))
        bottom = max(0.0, caption_top - 8)
    else:
        top = min(page_height, caption_bottom + 8)
        bottom = min(page_height, caption_bottom + min(330.0, page_height * 0.42))
    if bottom - top < 72:
        return None
    return (x0, top, x1, bottom)


def scale_plumber_bbox_to_page(
    bbox: BBox,
    plumber_page: pdfplumber.page.Page,
    pdf_page: PdfiumPage,
) -> BBox:
    x_scale = pdf_page.rect.width / float(plumber_page.width)
    y_scale = pdf_page.rect.height / float(plumber_page.height)
    return (
        max(0.0, bbox[0] * x_scale),
        max(0.0, bbox[1] * y_scale),
        min(float(pdf_page.rect.width), bbox[2] * x_scale),
        min(float(pdf_page.rect.height), bbox[3] * y_scale),
    )


def scale_page_bbox_to_plumber(
    bbox: BBox,
    plumber_page: pdfplumber.page.Page,
    pdf_page: PdfiumPage,
) -> BBox:
    x_scale = float(plumber_page.width) / pdf_page.rect.width
    y_scale = float(plumber_page.height) / pdf_page.rect.height
    return (
        max(0.0, bbox[0] * x_scale),
        max(0.0, bbox[1] * y_scale),
        min(float(plumber_page.width), bbox[2] * x_scale),
        min(float(plumber_page.height), bbox[3] * y_scale),
    )


def local_caption_for_visual(
    words: list[dict[str, Any]],
    prefix: str,
    caption_bbox: BBox,
    fallback_text: str,
    visual_bbox: BBox,
    plumber_page: pdfplumber.page.Page,
    pdf_page: PdfiumPage,
) -> tuple[str, BBox] | None:
    visual_plumber_bbox = scale_page_bbox_to_plumber(visual_bbox, plumber_page, pdf_page)
    below_visual = caption_bbox[1] >= visual_plumber_bbox[3] - 8
    if below_visual:
        top = max(0.0, min(caption_bbox[1] - 2.0, visual_plumber_bbox[3] - 8.0))
        bottom = min(float(plumber_page.height), visual_plumber_bbox[3] + 120.0)
    else:
        top = max(0.0, visual_plumber_bbox[1] - 120.0)
        bottom = min(float(plumber_page.height), visual_plumber_bbox[1] + 2.0)

    lines = [
        line
        for line in split_chars_into_horizontal_segments(plumber_page.chars)
        if top <= float(line["bbox"][1]) <= bottom
    ]
    if not lines:
        candidate_words = [
            word
            for word in words
            if top <= float(word.get("top", 0)) <= bottom
        ]
        lines = split_words_into_horizontal_segments(candidate_words)
    caption_pattern = re.compile(
        rf"^(?i:{re.escape(prefix)})\s*{caption_number_pattern(prefix)}"
        rf"(?:[\.:]|\s*\||(?=\s+[A-Z][A-Za-z]))"
    )
    starts = [
        (index, caption)
        for index, line in enumerate(lines)
        if (caption := slice_caption_from_segment(line, prefix, allow_embedded=True)) is not None
        and caption_pattern.match(caption["text"])
    ]
    start_index = min(
        starts,
        key=lambda item: caption_segment_score(item[1]["bbox"], visual_plumber_bbox),
        default=None,
    )
    if start_index is None:
        return None
    start_index = start_index[0]

    selected: list[dict[str, Any]] = []
    previous_bottom = 0.0
    previous_bbox: BBox | None = None
    for line in lines[start_index:]:
        candidate = (
            slice_caption_from_segment(line, prefix, allow_embedded=True)
            if not selected
            else line
        )
        if candidate is None and not selected:
            continue
        if selected and previous_bbox is not None:
            if caption_tiny_math_fragment(line, previous_bbox):
                continue
            candidate = clip_segment_from_x(line, max(0.0, previous_bbox[0] - 8.0))
            if candidate is None:
                break
        if candidate is None:
            continue
        if selected and caption_separator_fragment(candidate["text"]):
            continue
        if selected and float(line["bbox"][1]) - previous_bottom > 18:
            break
        if selected and starts_new_caption(candidate["text"]):
            break
        if selected and caption_continuation_looks_like_body(selected[0], candidate):
            break
        if previous_bbox is not None and not caption_segment_continues(previous_bbox, candidate["bbox"]):
            if vertical_gap(previous_bbox, candidate["bbox"]) <= 4:
                continue
            break
        selected.append(candidate)
        previous_bottom = float(candidate["bbox"][3])
        previous_bbox = candidate["bbox"]
        if selected[0].get("embedded") and len(selected) >= 2:
            break
        if len(selected) >= 10:
            break

    if not selected:
        return None
    text = normalize_block_lines(
        [repair_caption_prefix_spacing(line["text"], prefix) for line in selected]
    )
    if not text or normalized_key(prefix) not in normalized_key(text):
        text = fallback_text
    return text, union_bboxes([line["bbox"] for line in selected])


def caption_tiny_math_fragment(segment: dict[str, Any], previous_bbox: BBox) -> bool:
    text = normalize_text(str(segment.get("text", "")))
    if not re.fullmatch(r"[A-Za-z0-9_]{1,2}", text):
        return False
    bbox = tuple(float(value) for value in segment["bbox"])
    if bbox[2] - bbox[0] > 12 or bbox[3] - bbox[1] > 8:
        return False
    return vertical_gap(previous_bbox, bbox) <= 4


def caption_continuation_looks_like_body(first_line: dict[str, Any], candidate: dict[str, Any]) -> bool:
    first_text = normalize_text(str(first_line.get("text", "")))
    candidate_text = normalize_text(str(candidate.get("text", "")))
    if not first_text or not candidate_text:
        return False
    try:
        first_font = float(first_line.get("font_size") or 0)
        candidate_font = float(candidate.get("font_size") or 0)
    except Exception:
        first_font = 0.0
        candidate_font = 0.0
    if first_font and candidate_font and candidate_font <= first_font + 0.45:
        return False
    if not re.search(r"[.!?]$", first_text):
        return False
    return bool(
        re.match(
            r"^(?:A|An|The|This|These|We|In|For|As|Our|To|It|However|Overall|Results?)\b",
            candidate_text,
            re.IGNORECASE,
        )
    )


def caption_separator_fragment(text: str) -> bool:
    return normalize_text(text) in {"|", "¦"}


def split_chars_into_reading_order_segments(
    chars: list[dict[str, Any]],
    page_width: float,
    page_height: float,
) -> list[dict[str, Any]]:
    segments = split_chars_into_horizontal_segments(chars, page_width=page_width)
    body_font_size = dominant_body_font_size(segments, page_height)
    for segment in segments:
        segment["kind"] = (
            "footnote"
            if segment_is_footnote(segment, page_height, body_font_size)
            else "text"
        )
    if not looks_like_two_column_segments(segments, page_width):
        return segments

    ordered: list[dict[str, Any]] = []
    current_run: list[dict[str, Any]] = []
    footnotes: list[dict[str, Any]] = []

    def flush_run() -> None:
        if current_run:
            ordered.extend(order_column_run(current_run, page_width))
            current_run.clear()

    for segment in segments:
        if segment["kind"] == "footnote":
            footnotes.append(segment)
        elif segment_column_side(segment["bbox"], page_width) == "full":
            flush_run()
            ordered.append(segment)
        else:
            current_run.append(segment)
    flush_run()
    ordered.extend(footnotes)
    return ordered


def split_chars_into_horizontal_segments(
    chars: list[dict[str, Any]],
    page_width: float | None = None,
) -> list[dict[str, Any]]:
    rows = group_chars_by_baseline(chars)
    segments: list[dict[str, Any]] = []
    for row in rows:
        sorted_row = sorted(row, key=lambda char: safe_float(char.get("x0")))
        gap_limit = horizontal_char_segment_gap(sorted_row)
        space_threshold = char_space_threshold(sorted_row)
        current: list[dict[str, Any]] = []
        previous_char: dict[str, Any] | None = None
        for char in sorted_row:
            if previous_char is not None:
                gap = safe_float(char.get("x0")) - safe_float(previous_char.get("x1"))
                if should_break_char_segment(
                    previous_char,
                    char,
                    gap=gap,
                    gap_limit=gap_limit,
                    space_threshold=space_threshold,
                    page_width=page_width,
                ):
                    append_char_segment(segments, current)
                    current = []
            current.append(char)
            previous_char = char
        append_char_segment(segments, current)
    return segments


def group_chars_by_baseline(chars: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    usable_chars = [char for char in chars if valid_text_char(char)]
    sorted_chars = sorted(
        usable_chars,
        key=lambda char: (safe_float(char.get("top")), safe_float(char.get("x0"))),
    )
    rows: list[list[dict[str, Any]]] = []
    row_tops: list[float] = []
    row_sizes: list[float] = []
    for char in sorted_chars:
        top = safe_float(char.get("top"))
        size = char_font_size(char)
        if rows:
            tolerance = max(2.2, min(row_sizes[-1], size) * 0.34)
            if abs(top - row_tops[-1]) <= tolerance:
                rows[-1].append(char)
                row_tops[-1] = median([safe_float(item.get("top")) for item in rows[-1]])
                row_sizes[-1] = median([char_font_size(item) for item in rows[-1]])
                continue
        rows.append([char])
        row_tops.append(top)
        row_sizes.append(size)
    return rows


def valid_text_char(char: dict[str, Any]) -> bool:
    if char.get("upright", True) is False:
        return False
    text = str(char.get("text", ""))
    if not text:
        return False
    try:
        safe_float(char.get("x0"))
        safe_float(char.get("x1"))
        safe_float(char.get("top"))
        safe_float(char.get("bottom"))
    except Exception:
        return False
    return True


def append_char_segment(segments: list[dict[str, Any]], chars: list[dict[str, Any]]) -> None:
    if not chars:
        return
    raw_text = reconstruct_raw_char_line(chars)
    text = normalize_text(raw_text)
    if not text:
        return
    segments.append(
        {
            "text": text,
            "bbox": (
                min(safe_float(char["x0"]) for char in chars),
                min(safe_float(char["top"]) for char in chars),
                max(safe_float(char["x1"]) for char in chars),
                max(safe_float(char["bottom"]) for char in chars),
            ),
            "font_size": median([char_font_size(char) for char in chars]),
            "repaired_ligatures": has_misdecoded_pdf_ligatures(raw_text),
        }
    )


def reconstruct_char_line(chars: list[dict[str, Any]]) -> str:
    return normalize_text(reconstruct_raw_char_line(chars))


def reconstruct_raw_char_line(chars: list[dict[str, Any]]) -> str:
    sorted_chars = sorted(chars, key=lambda char: safe_float(char.get("x0")))
    threshold = char_space_threshold(sorted_chars)
    parts: list[str] = []
    previous_text_char: dict[str, Any] | None = None
    for char in sorted_chars:
        text = str(char.get("text", ""))
        if not text:
            continue
        if text.isspace():
            if parts and parts[-1] != " ":
                parts.append(" ")
            continue
        if (
            previous_text_char is not None
            and parts
            and parts[-1] != " "
            and should_insert_char_space(previous_text_char, char, threshold)
        ):
            parts.append(" ")
        parts.append(text)
        previous_text_char = char
    return repair_leading_marker_spacing("".join(parts))


def repair_leading_marker_spacing(text: str) -> str:
    return re.sub(r"^(\d{1,3})([A-Z])(?=\s|[a-z])", r"\1 \2", text)


def should_insert_char_space(
    previous_char: dict[str, Any],
    current_char: dict[str, Any],
    threshold: float,
) -> bool:
    gap = safe_float(current_char.get("x0")) - safe_float(previous_char.get("x1"))
    if gap < threshold:
        return False
    previous_text = str(previous_char.get("text", ""))
    current_text = str(current_char.get("text", ""))
    if not previous_text or not current_text:
        return False
    if previous_text in "([{“‘":
        return False
    if current_text in ".,;:!?)]}”’%" and gap < threshold * 1.9:
        return False
    return True


def should_break_char_segment(
    previous_char: dict[str, Any],
    current_char: dict[str, Any],
    *,
    gap: float,
    gap_limit: float,
    space_threshold: float,
    page_width: float | None,
) -> bool:
    if gap > gap_limit:
        return True
    if page_width and crosses_column_gutter(previous_char, current_char, page_width):
        return gap > max(6.0, space_threshold * 3.5)
    return False


def crosses_column_gutter(
    previous_char: dict[str, Any],
    current_char: dict[str, Any],
    page_width: float,
) -> bool:
    if page_width <= 0:
        return False
    gutter = page_width / 2
    previous_x1 = safe_float(previous_char.get("x1"))
    current_x0 = safe_float(current_char.get("x0"))
    return (
        previous_x1 <= gutter
        and current_x0 >= gutter
        and previous_x1 >= gutter - page_width * 0.08
        and current_x0 <= gutter + page_width * 0.08
    )


def char_space_threshold(chars: list[dict[str, Any]]) -> float:
    sizes = [char_font_size(char) for char in chars if char_font_size(char) > 0]
    widths = [
        max(0.0, safe_float(char.get("x1")) - safe_float(char.get("x0")))
        for char in chars
        if max(0.0, safe_float(char.get("x1")) - safe_float(char.get("x0"))) > 0
    ]
    size = median(sizes) if sizes else 10.0
    width = median(widths) if widths else size * 0.45
    return max(0.85, size * 0.14, width * 0.22)


def horizontal_char_segment_gap(chars: list[dict[str, Any]]) -> float:
    sizes = [char_font_size(char) for char in chars if char_font_size(char) > 0]
    size = median(sizes) if sizes else 10.0
    return max(12.0, size * 1.6)


def char_font_size(char: dict[str, Any]) -> float:
    size = safe_float(char.get("size"), default=0.0)
    if size > 0:
        return size
    height = safe_float(char.get("bottom")) - safe_float(char.get("top"))
    return height if height > 0 else 10.0


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def dominant_body_font_size(segments: list[dict[str, Any]], page_height: float) -> float:
    candidates = [
        float(segment.get("font_size", 0) or 0)
        for segment in segments
        if segment.get("font_size")
        and segment["bbox"][1] < page_height * 0.88
        and len(str(segment.get("text", "")).strip()) >= 20
    ]
    if not candidates:
        candidates = [
            float(segment.get("font_size", 0) or 0)
            for segment in segments
            if segment.get("font_size")
        ]
    return median(candidates) if candidates else 10.0


def segment_is_footnote(
    segment: dict[str, Any],
    page_height: float,
    body_font_size: float,
) -> bool:
    text = normalize_text(str(segment.get("text", "")))
    if not text or re.fullmatch(r"\d{1,4}", text):
        return False
    top = float(segment["bbox"][1])
    font_size = float(segment.get("font_size", body_font_size) or body_font_size)
    if page_height <= 0 or top < page_height * 0.72:
        return False
    if font_size > body_font_size * 0.91:
        return False
    if (
        count_mathish_chars(text) >= 2
        and true_formula_operator_count(text) >= 1
        and (has_math_unicode(text) or not looks_like_formula_boundary_prose(text))
    ):
        return False
    return len(text) >= 4


def split_words_into_horizontal_segments(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = group_words_by_baseline(words)
    segments: list[dict[str, Any]] = []
    for row in rows:
        current: list[dict[str, Any]] = []
        previous_word: dict[str, Any] | None = None
        for word in row:
            if previous_word is not None:
                gap = float(word["x0"]) - float(previous_word["x1"])
                if gap > horizontal_segment_gap(row):
                    append_word_segment(segments, current)
                    current = []
            current.append(word)
            previous_word = word
        append_word_segment(segments, current)
    return segments


def split_words_into_reading_order_segments(
    words: list[dict[str, Any]],
    page_width: float,
) -> list[dict[str, Any]]:
    segments = split_words_into_horizontal_segments(words)
    if not looks_like_two_column_segments(segments, page_width):
        return segments

    ordered: list[dict[str, Any]] = []
    current_run: list[dict[str, Any]] = []

    def flush_run() -> None:
        if current_run:
            ordered.extend(order_column_run(current_run, page_width))
            current_run.clear()

    for segment in segments:
        if segment_column_side(segment["bbox"], page_width) == "full":
            flush_run()
            ordered.append(segment)
        else:
            current_run.append(segment)
    flush_run()
    return ordered


def looks_like_two_column_segments(segments: list[dict[str, Any]], page_width: float) -> bool:
    if len(segments) < 10 or page_width <= 0:
        return False
    left = 0
    right = 0
    for segment in segments:
        side = segment_column_side(segment["bbox"], page_width)
        if side == "left":
            left += 1
        elif side == "right":
            right += 1
    return left >= 5 and right >= 5 and (left + right) >= len(segments) * 0.48


def looks_like_two_column_text_flow_segments(
    segments: list[dict[str, Any]],
    page_rect: PageRect,
) -> bool:
    flow_segments: list[dict[str, Any]] = []
    for segment in segments:
        text = normalize_text(str(segment.get("text", "")))
        if len(re.findall(r"\b[A-Za-z]{3,}\b", text)) < 4:
            continue
        if formula_display_segment(segment, page_rect):
            continue
        bbox = tuple(float(value) for value in segment["bbox"])
        if bbox[2] - bbox[0] < float(page_rect.width) * 0.18:
            continue
        if count_mathish_chars(text) >= 5 and len(text.split()) < 10:
            continue
        flow_segments.append(segment)
    return looks_like_two_column_segments(flow_segments, float(page_rect.width))


def order_column_run(run: list[dict[str, Any]], page_width: float) -> list[dict[str, Any]]:
    left: list[dict[str, Any]] = []
    right: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for segment in run:
        side = segment_column_side(segment["bbox"], page_width)
        if side == "left":
            left.append(segment)
        elif side == "right":
            right.append(segment)
        else:
            other.append(segment)
    if not left or not right:
        return sorted(run, key=lambda segment: (segment["bbox"][1], segment["bbox"][0]))
    sort_key = lambda segment: (segment["bbox"][1], segment["bbox"][0])
    return [*sorted(left, key=sort_key), *sorted(right, key=sort_key), *sorted(other, key=sort_key)]


def segment_column_side(bbox: BBox, page_width: float) -> str:
    x0, _, x1, _ = bbox
    width = x1 - x0
    center = (x0 + x1) / 2
    gutter = page_width / 2
    spans_gutter = x0 < gutter - page_width * 0.06 and x1 > gutter + page_width * 0.06
    if width >= page_width * 0.62 or spans_gutter:
        return "full"
    if center < gutter:
        return "left"
    if center > gutter:
        return "right"
    if x1 <= gutter:
        return "left"
    if x0 >= gutter:
        return "right"
    return "full"


def group_words_by_baseline(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    sorted_words = sorted(words, key=lambda word: (round(float(word.get("top", 0)) / 3), word["x0"]))
    rows: list[list[dict[str, Any]]] = []
    for word in sorted_words:
        top = float(word.get("top", 0))
        if rows and abs(top - float(rows[-1][0].get("top", 0))) <= 4:
            rows[-1].append(word)
        else:
            rows.append([word])
    return rows


def horizontal_segment_gap(row: list[dict[str, Any]]) -> float:
    gaps = [
        float(next_word["x0"]) - float(word["x1"])
        for word, next_word in zip(row, row[1:])
        if float(next_word["x0"]) > float(word["x1"])
    ]
    ordinary_gaps = [gap for gap in gaps if gap <= 8]
    baseline = max(3.0, sum(ordinary_gaps) / max(1, len(ordinary_gaps)))
    return max(14.0, baseline * 4.0)


def append_word_segment(segments: list[dict[str, Any]], words: list[dict[str, Any]]) -> None:
    if not words:
        return
    raw_text = " ".join(str(word.get("text", "")) for word in words)
    text = normalize_text(raw_text)
    if not text:
        return
    segments.append(
        {
            "text": text,
            "bbox": (
                min(float(word["x0"]) for word in words),
                min(float(word["top"]) for word in words),
                max(float(word["x1"]) for word in words),
                max(float(word["bottom"]) for word in words),
            ),
            "repaired_ligatures": has_misdecoded_pdf_ligatures(raw_text),
        }
    )


def normalize_gmft_bbox(raw_bbox: Any) -> BBox | None:
    if raw_bbox is None:
        return None
    if hasattr(raw_bbox, "to_tuple"):
        raw_bbox = raw_bbox.to_tuple()
    elif hasattr(raw_bbox, "bbox"):
        raw_bbox = raw_bbox.bbox
    try:
        values = tuple(float(value) for value in raw_bbox)
    except Exception:
        return None
    if len(values) != 4:
        return None
    x0, top, x1, bottom = values
    if x1 < x0:
        x0, x1 = x1, x0
    if bottom < top:
        top, bottom = bottom, top
    if x1 - x0 < 12 or bottom - top < 12:
        return None
    return (x0, top, x1, bottom)


def caption_segment_score(segment_bbox: BBox, visual_bbox: BBox) -> float:
    return vertical_gap(segment_bbox, visual_bbox) * 5 + abs(
        bbox_center(segment_bbox)[0] - bbox_center(visual_bbox)[0]
    )


def caption_segment_continues(previous_bbox: BBox, next_bbox: BBox) -> bool:
    if horizontal_overlap_ratio(previous_bbox, next_bbox) >= 0.18:
        return True
    previous_center = bbox_center(previous_bbox)[0]
    next_center = bbox_center(next_bbox)[0]
    return abs(previous_center - next_center) <= max(
        72.0,
        (previous_bbox[2] - previous_bbox[0]) * 0.42,
    )


def figure_search_band(caption_region: BBox, page_rect: PageRect) -> BBox:
    page_width = float(page_rect.width)
    page_height = float(page_rect.height)
    caption_top = caption_region[1]
    caption_bottom = caption_region[3]
    if caption_top > page_height * 0.24:
        if caption_top > page_height * 0.70:
            lookback = min(560.0, page_height * 0.70)
        else:
            lookback = min(
                230.0 if caption_top < page_height * 0.55 else 390.0,
                page_height * 0.50,
            )
        return (
            0.0,
            max(0.0, caption_top - lookback),
            page_width,
            max(0.0, caption_top - 4.0),
        )
    return (
        0.0,
        min(page_height, caption_bottom + 4.0),
        page_width,
        min(page_height, caption_bottom + min(390.0, page_height * 0.50)),
    )


def collect_visual_primitive_bboxes(pdf_page: PdfiumPage, search_band: BBox) -> list[BBox]:
    boxes: list[BBox] = []
    for bbox in pdf_page.visual_bboxes():
        append_visual_bbox(boxes, bbox, pdf_page.rect, search_band)
    return boxes


def append_visual_bbox(
    boxes: list[BBox],
    bbox: BBox,
    page_rect: PageRect,
    search_band: BBox,
) -> None:
    normalized = normalize_visual_bbox(bbox, page_rect)
    if normalized is None:
        return
    if not bbox_intersects(normalized, search_band):
        return
    if visual_bbox_is_page_decoration(normalized, page_rect):
        return
    boxes.append(normalized)


def rect_to_bbox(rect: Any) -> BBox | None:
    try:
        return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
    except AttributeError:
        try:
            values = tuple(float(value) for value in rect)
        except TypeError:
            return None
        if len(values) != 4:
            return None
        return values  # type: ignore[return-value]


def normalize_visual_bbox(bbox: BBox, page_rect: PageRect) -> BBox | None:
    x0, top, x1, bottom = bbox
    if x1 < x0:
        x0, x1 = x1, x0
    if bottom < top:
        top, bottom = bottom, top
    width = x1 - x0
    height = bottom - top
    if width <= 0.5:
        x0 -= 0.75
        x1 += 0.75
        width = x1 - x0
    if height <= 0.5:
        top -= 0.75
        bottom += 0.75
        height = bottom - top
    if width < 1.5 or height < 1.5:
        return None
    return (
        max(float(page_rect.x0), x0),
        max(float(page_rect.y0), top),
        min(float(page_rect.x1), x1),
        min(float(page_rect.y1), bottom),
    )


def normalize_detected_visual_bbox(bbox: BBox, page_rect: PageRect) -> BBox | None:
    normalized = normalize_visual_bbox(bbox, page_rect)
    if normalized is None:
        return None
    raw_width = abs(bbox[2] - bbox[0])
    raw_height = abs(bbox[3] - bbox[1])
    raw_area = max(1.0, raw_width * raw_height)
    normalized_area = max(0.0, (normalized[2] - normalized[0]) * (normalized[3] - normalized[1]))
    if normalized_area / raw_area < 0.42:
        return None
    if visual_bbox_is_page_decoration(normalized, page_rect):
        return None
    return normalized


def visual_bbox_is_page_decoration(bbox: BBox, page_rect: PageRect) -> bool:
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    area = width * height
    page_area = max(1.0, float(page_rect.width * page_rect.height))
    if area / page_area > 0.55:
        return True
    if height < 3.0 and width > float(page_rect.width) * 0.55:
        return True
    if width < 3.0 and height > float(page_rect.height) * 0.55:
        return True
    return False


def cluster_bboxes(boxes: list[BBox], proximity: float) -> list[list[BBox]]:
    remaining = list(boxes)
    clusters: list[list[BBox]] = []
    while remaining:
        cluster = [remaining.pop(0)]
        changed = True
        while changed:
            changed = False
            cluster_bbox = union_bboxes(cluster)
            for bbox in list(remaining):
                if bboxes_are_near(cluster_bbox, bbox, proximity):
                    cluster.append(bbox)
                    remaining.remove(bbox)
                    changed = True
        clusters.append(cluster)
    return clusters


def bboxes_are_near(first: BBox, second: BBox, proximity: float) -> bool:
    horizontal_gap = max(second[0] - first[2], first[0] - second[2], 0.0)
    vertical_gap_value = max(second[1] - first[3], first[1] - second[3], 0.0)
    return horizontal_gap <= proximity and vertical_gap_value <= proximity


def substantial_visual_cluster(bbox: BBox, page_rect: PageRect) -> bool:
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    area = width * height
    page_area = max(1.0, float(page_rect.width * page_rect.height))
    return width >= 42 and height >= 28 and area / page_area >= 0.003


def visual_cluster_score(bbox: BBox, caption_region: BBox) -> float:
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    area = width * height
    distance_penalty = vertical_gap(bbox, caption_region) * 60
    center_penalty = abs(bbox_center(bbox)[0] - bbox_center(caption_region)[0]) * 8
    return area - distance_penalty - center_penalty


def nearby_graphic_text_bboxes(
    words: list[dict[str, Any]],
    visual_bbox: BBox,
    search_band: BBox,
    *,
    caption_region: BBox | None = None,
) -> list[BBox]:
    expanded = expand_bbox(visual_bbox, x_padding=24.0, y_padding=128.0)
    text_boxes: list[BBox] = []
    for line in split_words_into_horizontal_segments(words):
        text = str(line.get("text", ""))
        if starts_new_caption(text):
            continue
        bbox = tuple(float(value) for value in line["bbox"])
        if caption_region is not None and graphic_text_is_on_caption_body_side(
            bbox,
            visual_bbox,
            caption_region,
        ):
            continue
        if not graphic_label_text_candidate(text) and not graphic_embedded_text_candidate(
            text,
            bbox,
            visual_bbox,
        ):
            continue
        if not bbox_intersects(bbox, search_band):
            continue
        if not graphic_text_bbox_candidate(bbox, visual_bbox):
            continue
        if point_in_bbox(bbox_center(bbox), expanded):
            text_boxes.append(bbox)
            continue
        if horizontal_overlap_ratio(bbox, expanded) >= 0.18 and vertical_gap(bbox, expanded) <= 18:
            text_boxes.append(bbox)
    return text_boxes


def graphic_text_is_on_caption_body_side(
    text_bbox: BBox,
    visual_bbox: BBox,
    caption_region: BBox,
) -> bool:
    caption_below_visual = caption_region[1] >= visual_bbox[3] - 8.0
    if caption_below_visual and text_bbox[1] >= caption_region[1] - 2.0:
        return True
    caption_above_visual = caption_region[3] <= visual_bbox[1] + 8.0
    if caption_above_visual and text_bbox[3] <= caption_region[3] + 2.0:
        return True
    return False


def graphic_text_bbox_candidate(text_bbox: BBox, visual_bbox: BBox) -> bool:
    text_width = text_bbox[2] - text_bbox[0]
    visual_width = visual_bbox[2] - visual_bbox[0]
    if text_width > max(visual_width * 1.25, visual_width + 48):
        extends_left = text_bbox[0] < visual_bbox[0] - 16
        extends_right = text_bbox[2] > visual_bbox[2] + 16
        if extends_left or extends_right:
            return False
    return True


def graphic_label_text_candidate(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    token_count = len(cleaned.split())
    if token_count <= 4:
        return True
    if re.search(r"[=∈≤≥→←↦√∑∏⊤×]", cleaned):
        return True
    return False


def graphic_embedded_text_candidate(text: str, text_bbox: BBox, visual_bbox: BBox) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return False
    token_count = len(cleaned.split())
    if token_count > 22:
        return False
    if re.search(r"[.!?:]$", cleaned):
        return False
    text_width = text_bbox[2] - text_bbox[0]
    visual_width = visual_bbox[2] - visual_bbox[0]
    if text_width > max(visual_width * 0.82, 280.0):
        return False
    citation_like = bool(re.search(r"\bet\s+al\.\s*\(\d{4}[a-z]?\)", cleaned))
    title_case_label = bool(re.search(r"\b[A-Z][A-Za-z-]+(?:\s+[A-Z][A-Za-z-]+){1,5}\b", cleaned))
    compact_symbol_label = bool(re.search(r"[≤≥=→←↔/&]", cleaned))
    return citation_like or title_case_label or compact_symbol_label


def embedded_caption_visual_candidate(
    bbox: BBox,
    caption_region: BBox,
    page_rect: PageRect,
) -> bool:
    width = bbox[2] - bbox[0]
    if width > float(page_rect.width) * 0.36:
        return False
    caption_center = bbox_center(caption_region)[0]
    box_center = bbox_center(bbox)[0]
    if abs(box_center - caption_center) > max(90.0, (caption_region[2] - caption_region[0]) * 1.2):
        return False
    return bbox[0] >= caption_region[0] - 95.0 and bbox[2] <= caption_region[2] + 125.0


def bbox_intersects(first: BBox, second: BBox) -> bool:
    return min(first[2], second[2]) > max(first[0], second[0]) and min(first[3], second[3]) > max(
        first[1], second[1]
    )


def bboxes_substantially_overlap(
    first: BBox,
    second: BBox,
    *,
    threshold: float,
) -> bool:
    return overlap_ratio(first, second) > threshold or overlap_ratio(second, first) > threshold


def pad_bbox(
    bbox: BBox,
    page_rect: PageRect,
    x_padding: float,
    y_padding: float,
) -> BBox:
    return (
        max(float(page_rect.x0), bbox[0] - x_padding),
        max(float(page_rect.y0), bbox[1] - y_padding),
        min(float(page_rect.x1), bbox[2] + x_padding),
        min(float(page_rect.y1), bbox[3] + y_padding),
    )


def clamp_bbox_to_page(bbox: BBox, page_rect: PageRect) -> BBox | None:
    x0 = max(float(page_rect.x0), min(float(page_rect.x1), bbox[0]))
    top = max(float(page_rect.y0), min(float(page_rect.y1), bbox[1]))
    x1 = max(float(page_rect.x0), min(float(page_rect.x1), bbox[2]))
    bottom = max(float(page_rect.y0), min(float(page_rect.y1), bbox[3]))
    if x1 - x0 < 2.0 or bottom - top < 2.0:
        return None
    return (x0, top, x1, bottom)


def expand_bbox(bbox: BBox, x_padding: float, y_padding: float) -> BBox:
    return (
        bbox[0] - x_padding,
        bbox[1] - y_padding,
        bbox[2] + x_padding,
        bbox[3] + y_padding,
    )


def valid_bbox(bbox: BBox, page_rect: PageRect) -> bool:
    return (
        bbox[2] > bbox[0]
        and bbox[3] > bbox[1]
        and bbox[0] < page_rect.width
        and bbox[1] < page_rect.height
        and bbox[2] > 0
        and bbox[3] > 0
    )


def bbox_center(bbox: BBox) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def point_in_bbox(point: tuple[float, float], bbox: BBox) -> bool:
    return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]


def region_contains_text_block(text_bbox: BBox, region_bbox: BBox) -> bool:
    if horizontal_overlap_ratio(text_bbox, region_bbox) < 0.45:
        return False
    text_center = bbox_center(text_bbox)
    if point_in_bbox(text_center, region_bbox):
        return True
    text_width = text_bbox[2] - text_bbox[0]
    region_width = region_bbox[2] - region_bbox[0]
    if region_width < text_width * 0.56:
        return False
    return overlap_ratio(text_bbox, region_bbox) > 0.22


def clip_line_left_of_suppressed_region(
    line: dict[str, Any],
    region_bbox: BBox,
) -> dict[str, Any] | None:
    bbox = tuple(float(value) for value in line["bbox"])
    vertical_overlap = max(0.0, min(bbox[3], region_bbox[3]) - max(bbox[1], region_bbox[1]))
    if vertical_overlap <= 0:
        return line
    text_width = bbox[2] - bbox[0]
    region_width = region_bbox[2] - region_bbox[0]
    if region_width <= 0 or text_width <= 0:
        return line
    if region_width > text_width * 0.62:
        return line
    if not (bbox[0] < region_bbox[0] < bbox[2]):
        return line
    if bbox[2] - region_bbox[0] < max(8.0, text_width * 0.05):
        return line
    if region_bbox[2] < bbox[2] - text_width * 0.18:
        return line
    text = normalize_text(str(line.get("text", "")))
    if not text:
        return None
    end = round(len(text) * ((region_bbox[0] - bbox[0]) / text_width)) + 3
    caption_match = re.search(
        r"\b(?i:Figure|Table)\s*\d+(?:[\.:]|\s*\||(?=\s+[A-Z][A-Za-z]))",
        text,
    )
    if caption_match is not None and caption_match.start() <= end + 8:
        end = caption_match.start()
    end = max(0, min(len(text), end))
    clipped_text = normalize_text(text[:end])
    if len(clipped_text) < 2:
        return None
    clipped = dict(line)
    clipped["text"] = clipped_text
    clipped["bbox"] = approximate_text_slice_bbox(bbox, text, 0, end)
    return clipped


def overlap_ratio(first: BBox, second: BBox) -> float:
    x_overlap = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    y_overlap = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    overlap = x_overlap * y_overlap
    first_area = max(1.0, (first[2] - first[0]) * (first[3] - first[1]))
    return overlap / first_area
