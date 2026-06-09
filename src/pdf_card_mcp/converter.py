from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
import pdfplumber
from PIL import Image

from .html_renderer import render_html
from .models import BBox, Card, ConversionManifest, ImageAsset


@dataclass(slots=True)
class ConversionOptions:
    pdf_path: Path
    output_path: Path | None = None
    title: str | None = None
    standalone: bool = True
    ocr: bool = False
    max_pages: int | None = None
    theme: str = "soft"
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
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "html_path": str(self.html_path),
            "manifest_path": str(self.manifest_path),
            "page_count": self.page_count,
            "card_count": self.card_count,
            "table_count": self.table_count,
            "figure_count": self.figure_count,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class TextBlock:
    page: int
    bbox: BBox
    text: str


def convert_pdf_to_card_html(
    pdf_path: str | Path,
    output_path: str | Path | None = None,
    title: str | None = None,
    standalone: bool = True,
    ocr: bool = False,
    max_pages: int | None = None,
    theme: str = "soft",
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

        output_path = self._default_output_path(pdf_path)
        manifest_path = output_path.with_suffix(".manifest.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with fitz.open(pdf_path) as document, pdfplumber.open(pdf_path) as plumber_pdf:
            page_count = len(document)
            processed_pages = min(page_count, self.options.max_pages or page_count)
            title = self._title(document, plumber_pdf)
            for index in range(processed_pages):
                page_number = index + 1
                fitz_page = document[index]
                plumber_page = plumber_pdf.pages[index]
                source_asset = self._render_source_page(fitz_page, page_number)
                self.assets.append(source_asset)

                table_regions = self._extract_tables(fitz_page, plumber_page, page_number)
                figure_regions = self._extract_figures(
                    fitz_page,
                    plumber_page,
                    page_number,
                    table_regions,
                )
                suppressed_regions = [*table_regions, *figure_regions]

                text_blocks = self._extract_text_blocks(
                    fitz_page,
                    page_number,
                    suppressed_regions,
                    title,
                )
                if not text_blocks and self.options.ocr:
                    text_blocks = self._ocr_page(source_asset, page_number)
                for block in text_blocks:
                    self._append_text_cards(block, source_asset.id)

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
            warnings=manifest.warnings,
        )

    def _default_output_path(self, pdf_path: Path) -> Path:
        if self.options.output_path:
            return self.options.output_path
        return pdf_path.with_name(f"{slugify(pdf_path.stem)}_card_reader.html")

    def _title(self, document: fitz.Document, plumber_pdf: pdfplumber.PDF) -> str:
        if self.options.title:
            return self.options.title.strip()
        metadata_title = (document.metadata or {}).get("title") or ""
        if metadata_title.strip():
            return normalize_text(metadata_title)
        if plumber_pdf.pages:
            text = plumber_pdf.pages[0].extract_text() or ""
            for line in text.splitlines():
                cleaned = normalize_text(line)
                if cleaned and len(cleaned) > 5:
                    return cleaned[:180]
        return self.options.pdf_path.stem.replace("_", " ").replace("-", " ").title()

    def _render_source_page(self, page: fitz.Page, page_number: int) -> ImageAsset:
        data, width, height = render_page_png(page, self.options.page_scale)
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

    def _extract_tables(
        self,
        fitz_page: fitz.Page,
        plumber_page: pdfplumber.page.Page,
        page_number: int,
    ) -> list[BBox]:
        table_regions: list[BBox] = []
        try:
            tables = plumber_page.find_tables()
        except Exception as error:
            self.warnings.append(f"Page {page_number}: table detection failed: {error}")
            tables = []

        words = extract_words(plumber_page)
        tables = [table for table in tables if not caption_near_bbox(words, table.bbox, "Figure")]
        caption_lines = find_caption_lines(words, "Table")
        consumed_table_indexes: set[int] = set()

        caption_bboxes = [caption["bbox"] for caption in caption_lines]
        for caption_index, caption in enumerate(caption_lines, start=1):
            near_indexes = nearby_table_indexes(caption_index - 1, caption_bboxes, tables)
            consumed_table_indexes.update(near_indexes)
            plumber_bbox = union_bboxes(
                [caption["bbox"], *[tables[index].bbox for index in near_indexes]]
            )
            if len(near_indexes) == 0:
                heuristic_bbox = heuristic_table_bbox(caption["bbox"], plumber_page, words)
                if heuristic_bbox is None:
                    self.warnings.append(
                        f"Page {page_number}: found table caption but could not infer crop: "
                        f"{caption['text'][:80]}"
                    )
                    continue
                plumber_bbox = union_bboxes([caption["bbox"], heuristic_bbox])
                self.warnings.append(
                    f"Page {page_number}: used heuristic crop for table caption "
                    f"'{caption['text'][:80]}'."
                )

            bbox = self._scale_plumber_bbox(plumber_bbox, plumber_page, fitz_page)
            if any(overlap_ratio(bbox, region) > 0.65 for region in table_regions):
                continue
            if not valid_bbox(bbox, fitz_page.rect):
                self.warnings.append(f"Page {page_number}: skipped invalid table bbox {plumber_bbox}.")
                continue
            table_regions.append(bbox)
            self._append_cropped_asset_card(
                fitz_page=fitz_page,
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
            bbox = self._scale_plumber_bbox(table.bbox, plumber_page, fitz_page)
            if any(overlap_ratio(bbox, region) > 0.35 for region in table_regions):
                continue
            if not valid_bbox(bbox, fitz_page.rect):
                continue
            table_regions.append(bbox)
            self._append_cropped_asset_card(
                fitz_page=fitz_page,
                page_number=page_number,
                kind="table",
                bbox=bbox,
                caption=f"Table on page {page_number}",
                fallback_label=f"Table {table_index + 1} on page {page_number}",
            )

        return table_regions

    def _extract_figures(
        self,
        fitz_page: fitz.Page,
        plumber_page: pdfplumber.page.Page,
        page_number: int,
        table_regions: list[BBox],
    ) -> list[BBox]:
        figure_regions: list[BBox] = []
        words = extract_words(plumber_page)
        figure_captions = find_caption_lines(words, "Figure")
        try:
            image_infos = fitz_page.get_image_info(xrefs=True)
        except Exception:
            image_infos = []
        image_bboxes = [
            bbox
            for info in image_infos
            if info.get("bbox")
            for bbox in [tuple(float(value) for value in info["bbox"])]
            if self._useful_image_bbox(bbox, fitz_page.rect, table_regions)
        ]
        caption_bboxes = [caption["bbox"] for caption in figure_captions]
        consumed_image_indexes: set[int] = set()

        for caption_index, caption in enumerate(figure_captions, start=1):
            near_indexes = nearby_bbox_indexes(caption_index - 1, caption_bboxes, image_bboxes)
            consumed_image_indexes.update(near_indexes)
            candidate_boxes = [caption["bbox"], *[image_bboxes[index] for index in near_indexes]]
            if len(near_indexes) == 0:
                heuristic_bbox = heuristic_figure_bbox(caption["bbox"], plumber_page)
                if heuristic_bbox is None:
                    self.warnings.append(
                        f"Page {page_number}: found figure caption but could not infer crop: "
                        f"{caption['text'][:80]}"
                    )
                    continue
                candidate_boxes.append(heuristic_bbox)

            plumber_bbox = union_bboxes(candidate_boxes)
            bbox = self._scale_plumber_bbox(plumber_bbox, plumber_page, fitz_page)
            bbox = trim_bbox_around_blockers(bbox, table_regions, caption["bbox"])
            if not valid_bbox(bbox, fitz_page.rect):
                self.warnings.append(f"Page {page_number}: skipped invalid figure bbox {plumber_bbox}.")
                continue
            figure_regions.append(bbox)
            self._append_cropped_asset_card(
                fitz_page=fitz_page,
                page_number=page_number,
                kind="figure",
                bbox=bbox,
                caption=caption["text"],
                fallback_label=f"Figure {caption_index} on page {page_number}",
            )

        for image_index, bbox in enumerate(image_bboxes, start=1):
            if image_index - 1 in consumed_image_indexes:
                continue
            if not self._useful_image_bbox(bbox, fitz_page.rect, table_regions):
                continue
            caption = caption_near_bbox(words, bbox, "Figure") or f"Figure on page {page_number}"
            figure_regions.append(bbox)
            self._append_cropped_asset_card(
                fitz_page=fitz_page,
                page_number=page_number,
                kind="figure",
                bbox=bbox,
                caption=caption,
                fallback_label=f"Figure {image_index} on page {page_number}",
            )
        return figure_regions

    def _extract_text_blocks(
        self,
        fitz_page: fitz.Page,
        page_number: int,
        suppressed_regions: list[BBox],
        document_title: str,
    ) -> list[TextBlock]:
        text_blocks: list[TextBlock] = []
        raw = fitz_page.get_text("dict")
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            bbox = tuple(float(value) for value in block.get("bbox", (0, 0, 0, 0)))
            if any(region_contains_text_block(bbox, region) for region in suppressed_regions):
                continue
            lines: list[str] = []
            for line in block.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                if line_text.strip():
                    lines.append(line_text.rstrip())
            text = normalize_block_lines(lines)
            if text and not is_metadata_or_noise(text, page_number, document_title):
                text_blocks.append(TextBlock(page=page_number, bbox=bbox, text=text))
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

    def _append_text_cards(self, block: TextBlock, source_image_id: str) -> None:
        kind = "heading" if looks_like_heading(block.text) else "paragraph"
        if kind == "heading":
            text_parts = [block.text]
            section = block.text
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
        fitz_page: fitz.Page,
        page_number: int,
        kind: str,
        bbox: BBox,
        caption: str,
        fallback_label: str,
    ) -> None:
        try:
            data, width, height = render_clip_png(fitz_page, bbox, self.options.crop_scale)
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
        fitz_page: fitz.Page,
    ) -> BBox:
        x_scale = fitz_page.rect.width / float(plumber_page.width)
        y_scale = fitz_page.rect.height / float(plumber_page.height)
        x0, top, x1, bottom = bbox
        return (
            max(0.0, x0 * x_scale),
            max(0.0, top * y_scale),
            min(float(fitz_page.rect.width), x1 * x_scale),
            min(float(fitz_page.rect.height), bottom * y_scale),
        )

    def _useful_image_bbox(
        self,
        bbox: BBox,
        page_rect: fitz.Rect,
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


def render_page_png(page: fitz.Page, scale: float) -> tuple[bytes, int, int]:
    dpi = round(72 * scale)
    pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False, annots=True)
    return pixmap.tobytes("png"), pixmap.width, pixmap.height


def render_clip_png(page: fitz.Page, bbox: BBox, scale: float) -> tuple[bytes, int, int]:
    rect = padded_rect(bbox, page.rect, padding=5)
    dpi = round(72 * scale)
    pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, clip=rect, alpha=False, annots=True)
    return pixmap.tobytes("png"), pixmap.width, pixmap.height


def padded_rect(bbox: BBox, page_rect: fitz.Rect, padding: float) -> fitz.Rect:
    return fitz.Rect(
        max(page_rect.x0, bbox[0] - padding),
        max(page_rect.y0, bbox[1] - padding),
        min(page_rect.x1, bbox[2] + padding),
        min(page_rect.y1, bbox[3] + padding),
    )


def png_data_uri(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def normalize_text(text: str) -> str:
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
        if result.endswith("-") and re.match(r"^[a-z]", line):
            result = result[:-1] + line
        else:
            result += " " + line
    return normalize_text(result)


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


def merge_text_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    merged: list[TextBlock] = []
    current: TextBlock | None = None

    for block in blocks:
        if current is None:
            current = block
            continue
        if should_merge_text_blocks(current, block):
            current = TextBlock(
                page=current.page,
                bbox=union_bboxes([current.bbox, block.bbox]),
                text=normalize_text(f"{current.text} {block.text}"),
            )
            continue
        merged.append(current)
        current = block

    if current is not None:
        merged.append(current)
    return merged


def should_merge_text_blocks(first: TextBlock, second: TextBlock) -> bool:
    if first.page != second.page:
        return False
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
    if len(text) > 140:
        return False
    if re.match(r"^(\d+(?:\.\d+)*\.?|[A-Z])\s+[A-Z][A-Za-z0-9 ,:/&()'-]{2,}$", text):
        return True
    if re.match(r"^(Abstract|Introduction|Conclusion|References|Methods?|Results?|Discussion)$", text):
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
    pattern = re.compile(rf"^{re.escape(prefix)}\s+\d+[\.:]", re.IGNORECASE)
    return [line for line in lines if pattern.match(line["text"])]


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
    x0 = max(0.0, page.width * 0.05)
    x1 = min(float(page.width), page.width * 0.95)
    caption_top = caption_bbox[1]
    caption_bottom = caption_bbox[3]
    # Most papers place table captions above the table. If the caption is too low,
    # crop above it instead of off the page.
    if caption_bottom < page.height * 0.72:
        top = max(0.0, caption_top - 8)
        bottom = infer_content_bottom_after_caption(caption_bbox, page, words)
    else:
        top = max(0.0, caption_top - min(260.0, page.height * 0.34))
        bottom = min(float(page.height), caption_bottom + 8)
    if bottom - top < 36:
        return None
    return (x0, top, x1, bottom)


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
    return bool(re.match(r"^(Figure|Table)\s+\d+[\.:]", normalize_text(text), re.IGNORECASE))


def line_is_tableish(text: str) -> bool:
    cleaned = normalize_text(text)
    numeric_tokens = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", cleaned))
    token_count = len(cleaned.split())
    has_table_terms = bool(
        re.search(
            r"\b(Model|Acc|F1|Cost|Latency|Version|Server|Tool|Method|Dataset|Benchmark|Score)\b",
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
    starts_like_prose = bool(re.match(r"^(The|This|These|We|In|For|As|Our|To|It)\b", cleaned))
    sentence_like = bool(re.search(r"[.!?]$", cleaned))
    return token_count >= 8 and (starts_like_prose or sentence_like)


def heuristic_figure_bbox(caption_bbox: BBox, page: pdfplumber.page.Page) -> BBox | None:
    x0 = max(0.0, page.width * 0.05)
    x1 = min(float(page.width), page.width * 0.95)
    caption_top = caption_bbox[1]
    caption_bottom = caption_bbox[3]
    if caption_top > page.height * 0.24:
        lookback = 210.0 if caption_top < page.height * 0.55 else 370.0
        caption_extra = 32.0 if caption_top < page.height * 0.55 else 80.0
        top = max(0.0, caption_top - min(lookback, page.height * 0.48))
        bottom = min(float(page.height), caption_bottom + min(caption_extra, page.height * 0.10))
    else:
        top = max(0.0, caption_top - 8)
        bottom = min(float(page.height), caption_bottom + min(330.0, page.height * 0.42))
    if bottom - top < 72:
        return None
    return (x0, top, x1, bottom)


def valid_bbox(bbox: BBox, page_rect: fitz.Rect) -> bool:
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
