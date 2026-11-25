"""Tesseract OCR wrapper (languages default to eng+urd)."""

from __future__ import annotations

import shutil
from functools import lru_cache
from typing import Protocol

from PIL import Image


class OCREngine(Protocol):
    def available(self) -> bool: ...
    def image_to_text(self, image: Image.Image) -> str: ...


class TesseractOCR:
    def __init__(self, languages: str = "eng+urd") -> None:
        self.languages = languages

    def available(self) -> bool:
        return _tesseract_binary() is not None

    def installed_languages(self) -> set[str]:
        import pytesseract

        return set(pytesseract.get_languages(config=""))

    def image_to_text(self, image: Image.Image) -> str:
        import pytesseract

        langs = [lang for lang in self.languages.split("+") if lang in self.installed_languages()]
        if not langs:
            raise RuntimeError(f"None of the OCR languages {self.languages!r} are installed for Tesseract")
        # --psm 3: automatic page segmentation. Grayscale helps on coloured scans.
        return pytesseract.image_to_string(image.convert("L"), lang="+".join(langs), config="--psm 3")


@lru_cache
def _tesseract_binary() -> str | None:
    import pytesseract

    configured = pytesseract.pytesseract.tesseract_cmd
    found = shutil.which(configured) or shutil.which("tesseract")
    if found is None:
        # Default Windows install location (local development only).
        win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if shutil.which(win):
            found = win
    if found:
        pytesseract.pytesseract.tesseract_cmd = found
    return found
