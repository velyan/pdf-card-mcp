"""PDF Card MCP public package."""

from .annotations import Annotation, AnnotationBundle
from .converter import ConversionOptions, ConversionResult, convert_pdf_to_card_html
from .publish import PublishResult, publish_reader_bundle, validate_reader_annotations

__all__ = [
    "Annotation",
    "AnnotationBundle",
    "ConversionOptions",
    "ConversionResult",
    "PublishResult",
    "convert_pdf_to_card_html",
    "publish_reader_bundle",
    "validate_reader_annotations",
]

__version__ = "0.1.0"
