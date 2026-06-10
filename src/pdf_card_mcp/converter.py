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
from .pdf_backend import PageRect, PdfiumDocument, PdfiumPage


@dataclass(slots=True)
class ConversionOptions:
    pdf_path: Path
    output_path: Path | None = None
    title: str | None = None
    standalone: bool = True
    ocr: bool = False
    max_pages: int | None = None
    theme: str = "soft"
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
        }


@dataclass(slots=True)
class TextBlock:
    page: int
    bbox: BBox
    text: str
    kind: str = "text"


@dataclass(slots=True)
class TableCandidate:
    bbox: BBox
    source: str = "pdfplumber"
    confidence: float = 1.0


def convert_pdf_to_card_html(
    pdf_path: str | Path,
    output_path: str | Path | None = None,
    title: str | None = None,
    standalone: bool = True,
    ocr: bool = False,
    max_pages: int | None = None,
    theme: str = "soft",
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

        output_path = self._default_output_path(pdf_path)
        manifest_path = output_path.with_suffix(".manifest.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with PdfiumDocument(pdf_path) as document, pdfplumber.open(pdf_path) as plumber_pdf:
            page_count = len(document)
            processed_pages = min(page_count, self.options.max_pages or page_count)
            title = self._title(plumber_pdf)
            gmft_tables = self._detect_gmft_tables(processed_pages)
            for index in range(processed_pages):
                page_number = index + 1
                pdf_page = document[index]
                plumber_page = plumber_pdf.pages[index]
                source_asset = self._render_source_page(pdf_page, page_number)
                self.assets.append(source_asset)

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

            self.cards = smooth_reader_cards(self.cards, self.options.max_words_per_card)

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

            manifest = ConversionManifest(
                title=title,
                source_pdf=pdf_path,
                page_count=page_count,
                processed_pages=processed_pages,
                cards=self.cards,
                assets=self.assets,
                warnings=self.warnings,
                theme=self.options.theme,
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
        )

    def _default_output_path(self, pdf_path: Path) -> Path:
        if self.options.output_path:
            return self.options.output_path
        return pdf_path.with_name(f"{slugify(pdf_path.stem)}_card_reader.html")

    def _title(self, plumber_pdf: pdfplumber.PDF) -> str:
        if self.options.title:
            return self.options.title.strip()
        metadata_title = (plumber_pdf.metadata or {}).get("Title") or ""
        if metadata_title.strip():
            return normalize_text(metadata_title)
        if plumber_pdf.pages:
            text = plumber_pdf.pages[0].extract_text() or ""
            for line in text.splitlines():
                cleaned = normalize_text(line)
                if cleaned and len(cleaned) > 5:
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
        tables = [
            TableCandidate(tuple(float(value) for value in table.bbox), source="pdfplumber")
            for table in plumber_tables
            if not caption_near_bbox(words, table.bbox, "Figure")
        ]
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
            plumber_bbox = (
                union_bboxes([tables[index].bbox for index in near_indexes])
                if near_indexes
                else None
            )
            heuristic_bbox = heuristic_table_bbox(caption["bbox"], plumber_page, words)
            if plumber_bbox is not None and heuristic_bbox is not None:
                plumber_bbox = union_bboxes([plumber_bbox, heuristic_bbox])
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

            bbox = self._scale_plumber_bbox(plumber_bbox, plumber_page, pdf_page)
            caption_region = self._scale_plumber_bbox(caption["bbox"], plumber_page, pdf_page)
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
                caption=caption["text"],
                fallback_label=f"Table {caption_index} on page {page_number}",
            )

        for table_index, table in enumerate(tables):
            if table_index in consumed_table_indexes:
                continue
            if caption_near_bbox(words, table.bbox, "Figure"):
                continue
            if not substantial_table_bbox(table.bbox, plumber_page):
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
        image_bboxes = [
            bbox
            for bbox in pdf_page.visual_bboxes()
            if self._useful_image_bbox(bbox, pdf_page.rect, table_regions)
        ]
        caption_bboxes = [caption["bbox"] for caption in figure_captions]
        consumed_image_indexes: set[int] = set()

        for caption_index, caption in enumerate(figure_captions, start=1):
            near_indexes = nearby_bbox_indexes(caption_index - 1, caption_bboxes, image_bboxes)
            consumed_image_indexes.update(near_indexes)
            caption_region = self._scale_plumber_bbox(caption["bbox"], plumber_page, pdf_page)
            candidate_boxes = [image_bboxes[index] for index in near_indexes]
            if len(near_indexes) == 0:
                heuristic_bbox = heuristic_figure_bbox(caption["bbox"], plumber_page, pdf_page, words)
                if heuristic_bbox is None:
                    self.warnings.append(
                        f"Page {page_number}: found figure caption but could not infer crop: "
                        f"{caption['text'][:80]}"
                    )
                    continue
                candidate_boxes.append(heuristic_bbox)

            bbox = union_bboxes(candidate_boxes)
            search_band = figure_search_band(caption_region, pdf_page.rect)
            label_boxes = nearby_graphic_text_bboxes(words, bbox, search_band)
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
            if any(overlap_ratio(bbox, region) > 0.65 for region in figure_regions):
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
            if any(overlap_ratio(bbox, region) > 0.35 for region in figure_regions):
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

    def _extract_text_blocks(
        self,
        pdf_page: PdfiumPage,
        plumber_page: pdfplumber.page.Page,
        page_number: int,
        suppressed_regions: list[BBox],
        document_title: str,
    ) -> list[TextBlock]:
        text_blocks: list[TextBlock] = []
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

        for line in lines:
            bbox = tuple(float(value) for value in line["bbox"])
            if any(region_contains_text_block(bbox, region) for region in suppressed_regions):
                continue
            text = normalize_text(str(line["text"]))
            kind = str(line.get("kind", "text"))
            if text and is_formula_text_line(bbox, pdf_page.rect, text):
                text_blocks.append(TextBlock(page=page_number, bbox=bbox, text=text, kind="formula"))
                continue
            if (
                text
                and not is_metadata_or_noise(text, page_number, document_title)
                and not looks_like_visual_label_noise(text)
            ):
                text_blocks.append(TextBlock(page=page_number, bbox=bbox, text=text, kind=kind))
        return merge_text_blocks(text_blocks)

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
        if block.kind == "formula":
            self._append_cropped_asset_card(
                pdf_page=pdf_page,
                page_number=block.page,
                kind="formula",
                bbox=block.bbox,
                caption=block.text,
                fallback_label=f"Formula on page {block.page}",
            )
            return

        if block.kind == "footnote":
            kind = "footnote"
        else:
            kind = "heading" if looks_like_heading(block.text) else "paragraph"
        if kind == "heading":
            text_parts = [block.text]
            section = block.text
        elif kind == "footnote":
            text_parts = split_text(block.text, self.options.max_words_per_card)
            section = "Footnotes"
        else:
            text_parts = split_text(block.text, self.options.max_words_per_card)
            section = self._current_section()
        for text in text_parts:
            self.cards.append(
                Card(
                    id=self._next_card_id(),
                    kind=kind,
                    page=block.page,
                    section=section,
                    text=text,
                    source_image_id=source_image_id,
                    bbox=block.bbox,
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
    ) -> None:
        try:
            data, width, height = pdf_page.render_clip_png(bbox, self.options.crop_scale)
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
            if re.search(r"\bTable\s+\d+", text, re.IGNORECASE):
                return True
        return False


def png_data_uri(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


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
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalized_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(text).lower())


def is_metadata_or_noise(text: str, page_number: int, document_title: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
        return True
    if re.fullmatch(r"\d{1,4}", cleaned):
        return True
    if normalized_key(cleaned) == normalized_key(document_title):
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


def is_formula_text_line(bbox: BBox, page_rect: PageRect, text: str) -> bool:
    cleaned = normalize_text(text)
    if not looks_like_display_formula_text(cleaned):
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
    if re.match(r"^(?:[•*-]|\d+[\.)])\s+", text):
        return False
    if len(text.split()) > 18:
        return False
    if re.fullmatch(r"\d{1,4}", text):
        return False
    has_operator = bool(
        re.search(r"(?:->|=>|←|→|↔|=|≤|≥|≠|∈|∉|∑|∏|∫|√|±|≈|∂|∀|∃|\barg\s*max\b|\barg\s*min\b)", text)
    )
    has_math_structure = bool(re.search(r"[A-Za-z]\s*[_^][A-Za-z0-9{(]|[(),:;]", text))
    return has_operator and has_math_structure


def strong_formula_syntax(text: str) -> bool:
    math_marks = len(re.findall(r"[_^=→←↔≤≥≠∈∉∑∏∫√±≈∂(),:]", text))
    alpha_tokens = len(re.findall(r"[A-Za-z]+", text))
    return math_marks >= 4 and alpha_tokens <= 10


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


def smooth_reader_cards(cards: list[Card], max_words_per_card: int) -> list[Card]:
    """Apply a conservative reader-oriented cleanup pass to paragraph cards."""
    smoothed: list[Card] = []
    for card in cards:
        text = normalize_text(card.text)
        if card.kind == "paragraph" and looks_like_reader_noise(text):
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
            )
        )
    return result


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
    if looks_like_visual_label_noise(cleaned):
        return True
    if re.fullmatch(r"[\W_]+", cleaned):
        return True
    return False


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
    second_is_to_the_right = second[0] > first[2] and second[1] <= first[1] + 36
    second_is_to_the_left = first[0] > second[2] and first[1] >= second[1] - 36
    return second_is_to_the_right or second_is_to_the_left


def looks_like_heading(text: str) -> bool:
    text = normalize_text(text)
    if len(text) > 120:
        return False
    if starts_new_caption(text) or looks_like_visual_label_noise(text):
        return False
    canonical_heading = (
        r"Abstract|Introduction|Background|Related Work|Preliminaries|Method|Methods|Approach|"
        r"Experiment|Experiments|Evaluation|Results|Discussion|Conclusion|References|Appendix|"
        r"Limitations|Dataset|Datasets|Analysis|Ablation|Implementation|Training|Inference"
    )
    if re.fullmatch(canonical_heading, text, re.IGNORECASE):
        return True
    if re.match(rf"^\d+(?:\.\d+)*\.?\s+(?:{canonical_heading})\b", text, re.IGNORECASE):
        return True
    if re.match(r"^[A-Z]\s+(?:[A-Z][A-Za-z]+(?:\s+|$)){1,6}$", text):
        return True
    return False


def looks_like_visual_label_noise(text: str) -> bool:
    cleaned = normalize_text(text)
    if not cleaned:
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
    pattern = re.compile(rf"^{re.escape(prefix)}\s*\d+[\.:]", re.IGNORECASE)
    return [line for line in lines if pattern.match(line["text"])]


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
    pattern = re.compile(rf"^{re.escape(prefix)}\s*\d+[\.:]", re.IGNORECASE)
    caption_lines: list[dict[str, Any]] = []
    for segment in segments:
        text = repair_caption_prefix_spacing(str(segment.get("text", "")), prefix)
        if not pattern.match(text):
            continue
        caption = dict(segment)
        caption["text"] = text
        caption_lines.append(caption)
    return caption_lines


def repair_caption_prefix_spacing(text: str, prefix: str) -> str:
    return normalize_text(re.sub(rf"^({re.escape(prefix)})(\d+)", r"\1 \2", text, flags=re.I))


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
        distances = [vertical_gap(caption_bbox, bbox) for caption_bbox in caption_bboxes]
        if not distances:
            continue
        nearest_index = min(range(len(distances)), key=lambda index: distances[index])
        if nearest_index == caption_index and distances[nearest_index] <= 180:
            indexes.append(bbox_index)
    return indexes


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


def substantial_table_bbox(bbox: BBox, page: pdfplumber.page.Page) -> bool:
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    page_area = float(page.width * page.height)
    area_ratio = (width * height) / max(1.0, page_area)
    return width >= page.width * 0.38 and height >= 70 and area_ratio >= 0.035


def heuristic_table_bbox(
    caption_bbox: BBox,
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]] | None = None,
) -> BBox | None:
    caption_top = caption_bbox[1]
    caption_bottom = caption_bbox[3]
    content_bbox = infer_table_content_bbox(caption_bbox, page, words)
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


def infer_table_content_bbox(
    caption_bbox: BBox,
    page: pdfplumber.page.Page,
    words: list[dict[str, Any]] | None,
) -> BBox | None:
    if not words:
        return None

    column_bbox = infer_caption_column_bbox(caption_bbox, page)
    caption_bottom = caption_bbox[3]
    default_bottom = min(float(page.height), caption_bottom + min(230.0, page.height * 0.30))
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
    prose_table_mode = False

    for line in lines:
        line_top = float(line["bbox"][1])
        line_bottom = float(line["bbox"][3])
        if starts_new_caption(line["text"]) and line_top > caption_bottom + 22:
            break
        if content_boxes and line_top - last_bottom > 18:
            break
        if line_is_tableish(line["text"]):
            if re.search(r"\b(Example|Task)\b", line["text"], re.IGNORECASE):
                prose_table_mode = True
            content_boxes.append(line["bbox"])
            last_bottom = line_bottom
            continue
        if content_boxes and line_is_body_boundary(line["text"]) and not prose_table_mode:
            break
        if content_boxes:
            content_boxes.append(line["bbox"])
            last_bottom = line_bottom

    if not content_boxes:
        return None

    content = union_bboxes(content_boxes)
    x0 = max(column_bbox[0], content[0] - 8)
    top = max(0.0, content[1] - 8)
    x1 = min(column_bbox[2], content[2] + 8)
    bottom = min(float(page.height), content[3] + 8)
    if x1 - x0 < 80 or bottom - top < 30:
        return None
    return (x0, top, x1, bottom)


def infer_caption_column_bbox(caption_bbox: BBox, page: pdfplumber.page.Page) -> BBox:
    margin_x = page.width * 0.05
    caption_width = caption_bbox[2] - caption_bbox[0]
    caption_center = (caption_bbox[0] + caption_bbox[2]) / 2
    if caption_width < page.width * 0.45:
        if caption_center < page.width / 2:
            return (margin_x, 0.0, page.width * 0.49, float(page.height))
        return (page.width * 0.51, 0.0, page.width - margin_x, float(page.height))
    return (margin_x, 0.0, page.width - margin_x, float(page.height))


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
    return bool(re.match(r"^(Figure|Table)\s*\d+[\.:]", normalize_text(text), re.IGNORECASE))


def line_is_tableish(text: str) -> bool:
    cleaned = normalize_text(text)
    numeric_tokens = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", cleaned))
    token_count = len(cleaned.split())
    has_table_terms = bool(
        re.search(
            r"\b(Model|Acc|F1|Cost|Latency|Version|Server|Tool|Method|Dataset|Benchmark|Score|Task|Example)\b",
            cleaned,
            re.IGNORECASE,
        )
    )
    has_url = "http://" in cleaned or "https://" in cleaned or "github.com" in cleaned
    return numeric_tokens >= 2 or has_table_terms or has_url or token_count <= 6


def line_is_body_boundary(text: str) -> bool:
    cleaned = normalize_text(text)
    token_count = len(cleaned.split())
    if looks_like_heading(cleaned):
        return True
    if line_is_tableish(cleaned):
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
    text_boxes = nearby_graphic_text_bboxes(words or extract_words(plumber_page), visual_bbox, search_band)
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
        top = max(0.0, visual_plumber_bbox[3] - 2.0)
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
    caption_pattern = re.compile(rf"^{re.escape(prefix)}\s*\d+[\.:]", re.IGNORECASE)
    starts = [
        (index, line)
        for index, line in enumerate(lines)
        if caption_pattern.match(repair_caption_prefix_spacing(line["text"], prefix))
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
        if selected and float(line["bbox"][1]) - previous_bottom > 18:
            break
        if selected and starts_new_caption(line["text"]):
            break
        if previous_bbox is not None and not caption_segment_continues(previous_bbox, line["bbox"]):
            if vertical_gap(previous_bbox, line["bbox"]) <= 4:
                continue
            break
        selected.append(line)
        previous_bottom = float(line["bbox"][3])
        previous_bbox = line["bbox"]
        if len(selected) >= 6:
            break

    if not selected:
        return None
    text = normalize_block_lines(
        [repair_caption_prefix_spacing(line["text"], prefix) for line in selected]
    )
    if not text or normalized_key(prefix) not in normalized_key(text):
        text = fallback_text
    return text, union_bboxes([line["bbox"] for line in selected])


def split_chars_into_reading_order_segments(
    chars: list[dict[str, Any]],
    page_width: float,
    page_height: float,
) -> list[dict[str, Any]]:
    segments = split_chars_into_horizontal_segments(chars)
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

    def flush_run() -> None:
        if current_run:
            ordered.extend(order_column_run(current_run, page_width))
            current_run.clear()

    for segment in segments:
        if segment["kind"] == "footnote":
            flush_run()
            ordered.append(segment)
        elif segment_column_side(segment["bbox"], page_width) == "full":
            flush_run()
            ordered.append(segment)
        else:
            current_run.append(segment)
    flush_run()
    return ordered


def split_chars_into_horizontal_segments(chars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = group_chars_by_baseline(chars)
    segments: list[dict[str, Any]] = []
    for row in rows:
        sorted_row = sorted(row, key=lambda char: safe_float(char.get("x0")))
        gap_limit = horizontal_char_segment_gap(sorted_row)
        current: list[dict[str, Any]] = []
        previous_char: dict[str, Any] | None = None
        for char in sorted_row:
            if previous_char is not None:
                gap = safe_float(char.get("x0")) - safe_float(previous_char.get("x1"))
                if gap > gap_limit:
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
    text = reconstruct_char_line(chars)
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
        }
    )


def reconstruct_char_line(chars: list[dict[str, Any]]) -> str:
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
    return normalize_text(repair_leading_marker_spacing("".join(parts)))


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
    if abs(center - gutter) <= page_width * 0.07 and width <= page_width * 0.45:
        return "full"
    if x1 <= gutter + page_width * 0.08 or center < gutter:
        return "left"
    if x0 >= gutter - page_width * 0.08 or center > gutter:
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
    text = normalize_text(" ".join(str(word.get("text", "")) for word in words))
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
        lookback = 230.0 if caption_top < page_height * 0.55 else 390.0
        return (
            0.0,
            max(0.0, caption_top - min(lookback, page_height * 0.50)),
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
) -> list[BBox]:
    expanded = expand_bbox(visual_bbox, x_padding=18.0, y_padding=34.0)
    text_boxes: list[BBox] = []
    for line in split_words_into_horizontal_segments(words):
        bbox = tuple(float(value) for value in line["bbox"])
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


def graphic_text_bbox_candidate(text_bbox: BBox, visual_bbox: BBox) -> bool:
    text_width = text_bbox[2] - text_bbox[0]
    visual_width = visual_bbox[2] - visual_bbox[0]
    if text_width > max(visual_width * 1.25, visual_width + 48):
        extends_left = text_bbox[0] < visual_bbox[0] - 16
        extends_right = text_bbox[2] > visual_bbox[2] + 16
        if extends_left or extends_right:
            return False
    return True


def bbox_intersects(first: BBox, second: BBox) -> bool:
    return min(first[2], second[2]) > max(first[0], second[0]) and min(first[3], second[3]) > max(
        first[1], second[1]
    )


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
    if point_in_bbox(bbox_center(text_bbox), region_bbox):
        return True
    return overlap_ratio(text_bbox, region_bbox) > 0.22


def overlap_ratio(first: BBox, second: BBox) -> float:
    x_overlap = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    y_overlap = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    overlap = x_overlap * y_overlap
    first_area = max(1.0, (first[2] - first[0]) * (first[3] - first[1]))
    return overlap / first_area
