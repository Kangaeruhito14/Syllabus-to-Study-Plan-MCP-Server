from __future__ import annotations

from dataclasses import dataclass

import pytesseract
from pdf2image import convert_from_bytes


@dataclass(frozen=True)
class OcrPage:
    page_number: int
    text: str


def pdf_bytes_to_text_pages(
    pdf_bytes: bytes, *, dpi: int = 250, lang: str = "eng"
) -> list[OcrPage]:
    """
    OCR a PDF (including scanned PDFs) into per-page text.

    Notes:
    - This requires Poppler (for pdf2image) and Tesseract installed on the system.
    - We keep per-page boundaries to support citations and confidence.
    """
    images = convert_from_bytes(pdf_bytes, dpi=dpi)
    pages: list[OcrPage] = []
    for i, img in enumerate(images, start=1):
        text = pytesseract.image_to_string(img, lang=lang)
        pages.append(OcrPage(page_number=i, text=text))
    return pages

