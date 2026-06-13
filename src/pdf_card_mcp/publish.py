from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .annotations import (
    AnnotationBundle,
    AnnotationValidationResult,
    empty_annotation_bundle,
    load_annotation_bundle,
    validate_annotation_bundle,
    write_annotation_bundle,
)
from .html_renderer import render_html
from .models import ConversionManifest
from .postprocess import load_standalone_manifest


@dataclass(slots=True)
class PublishResult:
    output_path: Path
    manifest_path: Path | None
    annotations_path: Path | None
    bundle_path: Path | None
    annotation_count: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "annotations_path": str(self.annotations_path) if self.annotations_path else None,
            "bundle_path": str(self.bundle_path) if self.bundle_path else None,
            "annotation_count": self.annotation_count,
            "warnings": self.warnings,
        }


def validate_reader_annotations(
    reader_html_path: str | Path,
    annotations_path: str | Path,
    *,
    include_private: bool = True,
) -> dict[str, Any]:
    manifest = load_standalone_manifest(Path(reader_html_path).expanduser())
    bundle = load_annotation_bundle(Path(annotations_path).expanduser())
    result = validate_annotation_bundle(bundle, manifest, include_private=include_private)
    return {
        "valid": result.rejected_count == 0,
        "accepted_count": result.accepted_count,
        "rejected_count": result.rejected_count,
        "warnings": result.warnings,
        "document_id": result.bundle.document_id,
        "manifest_hash": result.bundle.manifest_hash,
    }


def publish_reader_bundle(
    reader_html_path: str | Path,
    output_path: str | Path,
    *,
    annotations_path: str | Path | None = None,
    include_private: bool = False,
    redact_source_path: bool = True,
    read_only: bool = True,
) -> PublishResult:
    reader_path = Path(reader_html_path).expanduser()
    output = Path(output_path).expanduser()
    manifest = load_standalone_manifest(reader_path)
    bundle = load_annotation_bundle(Path(annotations_path).expanduser()) if annotations_path else None
    validation = prepare_published_annotations(bundle, manifest, include_private=include_private)
    if validation.rejected_count:
        raise ValueError(
            f"Cannot publish reader: {validation.rejected_count} annotation(s) "
            "could not be anchored to the reader."
        )
    published_manifest = redact_manifest_source_path(manifest) if redact_source_path else manifest
    html = render_html(
        published_manifest,
        annotation_bundle=validation.bundle,
        annotation_read_only=read_only,
    )

    warnings = [
        *validation.warnings,
        (
            "Published output may include extracted PDF text, source-page images, "
            "visual crops, notes, and highlights. Share only when you have the rights to do so."
        ),
    ]
    if redact_source_path:
        warnings.append("Redacted source_pdf from the published reader payload.")

    if output.suffix.lower() == ".html":
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html, encoding="utf-8")
        return PublishResult(
            output_path=output,
            manifest_path=None,
            annotations_path=None,
            bundle_path=None,
            annotation_count=validation.accepted_count,
            warnings=warnings,
        )

    output.mkdir(parents=True, exist_ok=True)
    reader_output = output / "index.html"
    manifest_output = output / "reader.manifest.json"
    annotations_output = output / "reader.annotations.json"
    bundle_output = output / "bundle.json"
    reader_output.write_text(html, encoding="utf-8")
    manifest_output.write_text(
        json.dumps(published_manifest.to_dict(include_data=False), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_annotation_bundle(validation.bundle, annotations_output)
    bundle_output.write_text(
        json.dumps(
            {
                "schema_version": "pdf-card-published-bundle/v1",
                "reader": reader_output.name,
                "manifest": manifest_output.name,
                "annotations": annotations_output.name,
                "annotation_count": validation.accepted_count,
                "read_only": read_only,
                "source_pdf_redacted": redact_source_path,
                "warnings": warnings,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return PublishResult(
        output_path=reader_output,
        manifest_path=manifest_output,
        annotations_path=annotations_output,
        bundle_path=bundle_output,
        annotation_count=validation.accepted_count,
        warnings=warnings,
    )


def prepare_published_annotations(
    bundle: AnnotationBundle | None,
    manifest: ConversionManifest,
    *,
    include_private: bool,
) -> AnnotationValidationResult:
    source = bundle if bundle is not None else empty_annotation_bundle(manifest)
    result = validate_annotation_bundle(source, manifest, include_private=include_private)
    public_annotations = [
        annotation.public_copy() if include_private else annotation
        for annotation in result.bundle.annotations
        if include_private or annotation.visibility == "public"
    ]
    published_bundle = result.bundle.model_copy(update={"annotations": public_annotations})
    return AnnotationValidationResult(
        bundle=published_bundle,
        warnings=result.warnings,
        rejected_count=result.rejected_count,
    )


def redact_manifest_source_path(manifest: ConversionManifest) -> ConversionManifest:
    return ConversionManifest(
        title=manifest.title,
        source_pdf=Path("redacted.pdf"),
        page_count=manifest.page_count,
        processed_pages=manifest.processed_pages,
        cards=manifest.cards,
        assets=manifest.assets,
        warnings=manifest.warnings,
        theme=manifest.theme,
        style_engine=manifest.style_engine,
        style_hints=manifest.style_hints,
        style=manifest.style,
    )
