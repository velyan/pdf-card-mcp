from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from .models import BBox


@dataclass(frozen=True, slots=True)
class PageRect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


class PdfiumDocument:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._document = pdfium.PdfDocument(str(path))

    def __len__(self) -> int:
        return len(self._document)

    def __getitem__(self, index: int) -> "PdfiumPage":
        return PdfiumPage(self._document[index])

    def close(self) -> None:
        self._document.close()

    def __enter__(self) -> "PdfiumDocument":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class PdfiumPage:
    def __init__(self, page: Any) -> None:
        self._page = page
        self.rect = PageRect(0.0, 0.0, float(page.get_width()), float(page.get_height()))

    def render_page_png(self, scale: float) -> tuple[bytes, int, int]:
        return self._render_png(scale=scale, crop=(0.0, 0.0, 0.0, 0.0))

    def render_clip_png(self, bbox: BBox, scale: float, padding: float = 5.0) -> tuple[bytes, int, int]:
        clipped = clip_bbox(pad_bbox(bbox, self.rect, padding), self.rect)
        crop = (
            clipped[0],
            self.rect.height - clipped[3],
            self.rect.width - clipped[2],
            clipped[1],
        )
        return self._render_png(scale=scale, crop=crop)

    def visual_bboxes(self) -> list[BBox]:
        bboxes: list[BBox] = []
        try:
            objects = self._page.get_objects()
        except Exception:
            return bboxes

        for obj in objects:
            if obj.__class__.__name__ == "PdfTextObj":
                continue
            try:
                bounds = obj.get_bounds()
            except Exception:
                continue
            bbox = pdfium_bounds_to_top_left_bbox(bounds, self.rect.height)
            if bbox is not None:
                bboxes.append(bbox)
        return bboxes

    def _render_png(self, scale: float, crop: tuple[float, float, float, float]) -> tuple[bytes, int, int]:
        bitmap = self._page.render(scale=scale, crop=crop, may_draw_forms=True)
        try:
            image = bitmap.to_pil()
            if image.mode != "RGB":
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue(), image.width, image.height
        finally:
            bitmap.close()


def pdfium_bounds_to_top_left_bbox(bounds: Any, page_height: float) -> BBox | None:
    try:
        x0, y0, x1, y1 = (float(value) for value in bounds)
    except Exception:
        return None
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return (x0, page_height - y1, x1, page_height - y0)


def pad_bbox(bbox: BBox, page_rect: PageRect, padding: float) -> BBox:
    return (
        bbox[0] - padding,
        bbox[1] - padding,
        bbox[2] + padding,
        bbox[3] + padding,
    )


def clip_bbox(bbox: BBox, page_rect: PageRect) -> BBox:
    return (
        max(page_rect.x0, bbox[0]),
        max(page_rect.y0, bbox[1]),
        min(page_rect.x1, bbox[2]),
        min(page_rect.y1, bbox[3]),
    )
