"""Text extraction: file type detection, per-format extractors, OCR and normalisation."""

from engine.extract.detect import FileKind, UnsupportedFileType, detect_file_type
from engine.extract.extractor import ExtractionError, ExtractOptions, extract_document
from engine.extract.normalize import count_words, normalize_text, text_sha256
from engine.extract.types import ExtractedDocument, PageText

__all__ = [
    "ExtractOptions",
    "ExtractedDocument",
    "ExtractionError",
    "FileKind",
    "PageText",
    "UnsupportedFileType",
    "count_words",
    "detect_file_type",
    "extract_document",
    "normalize_text",
    "text_sha256",
]
