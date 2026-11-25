"""Identify uploads by their content (magic bytes), never by the file name alone."""

from __future__ import annotations

import io
import zipfile
from enum import Enum


class FileKind(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    ODT = "odt"
    RTF = "rtf"
    TXT = "txt"


class UnsupportedFileType(ValueError):
    pass


_ODT_MIME = b"application/vnd.oasis.opendocument.text"


def detect_file_type(data: bytes) -> FileKind:
    """Return the kind of document in `data` or raise UnsupportedFileType."""
    if not data:
        raise UnsupportedFileType("The file is empty")
    if data[:1024].lstrip(b"\x00\t\r\n ").startswith(b"%PDF-"):
        return FileKind.PDF
    if data.startswith(b"{\\rtf"):
        return FileKind.RTF
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
                if "word/document.xml" in names:
                    return FileKind.DOCX
                if "mimetype" in names and zf.read("mimetype").strip() == _ODT_MIME:
                    return FileKind.ODT
        except zipfile.BadZipFile as exc:
            raise UnsupportedFileType("The file is a damaged ZIP/Office document") from exc
        raise UnsupportedFileType("Unsupported Office/ZIP document. Upload PDF, DOCX, ODT, RTF or TXT.")
    if _looks_like_text(data):
        return FileKind.TXT
    raise UnsupportedFileType("Unsupported file type. Upload PDF, DOCX, ODT, RTF or TXT.")


def _looks_like_text(data: bytes) -> bool:
    sample = data[:65536]
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):  # UTF-16 BOM
        return True
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:
        # A multi-byte character cut at the end of the sample is fine.
        if exc.start >= len(sample) - 4:
            return True
    # Legacy 8-bit text: allow if almost everything is printable.
    printable = sum(1 for b in sample if b >= 0x20 or b in (9, 10, 13))
    return printable / len(sample) > 0.97
