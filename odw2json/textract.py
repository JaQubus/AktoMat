"""PDF -> tekst stron. Warstwa tekstowa przez PyMuPDF, OCR (Tesseract, pol) tylko dla stron bez tekstu."""
from __future__ import annotations

import io
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

log = logging.getLogger(__name__)
# Tesseract domyślnie używa wielu wątków OpenMP; przy równoległych dokumentach to drastycznie spowalnia OCR.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")


@dataclass
class Document:
    path: Path
    pages: list[str]
    ocr_pages: list[int] = field(default_factory=list)  # numery stron (od 1) przepuszczonych przez OCR
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.pages)

    def numbered_text(self, max_chars: int | None = None) -> str:
        out, total = [], 0
        for i, p in enumerate(self.pages, 1):
            chunk = f"=== Strona {i} ===\n{p.strip()}\n"
            if max_chars and total + len(chunk) > max_chars:
                out.append(chunk[: max(0, max_chars - total)])
                break
            out.append(chunk)
            total += len(chunk)
        return "".join(out)


def _tesseract_available(cmd: str | None) -> bool:
    import pytesseract

    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
        return Path(cmd).exists() or shutil.which(cmd) is not None
    return shutil.which("tesseract") is not None or Path(
        r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists()


import re

_OCR_FIXES = [
    (re.compile(r"\n[ \t]*\n+"), "\n"),                                   # Tesseract rozdziela akapity pustą linią
    (re.compile(r"\bsp\.\s*[zZ]\s*[0oO]\.\s*[0oO]\.?"), "sp. z o.o."),     # "sp. Z 0.0." -> "sp. z o.o."
    (re.compile(r"(?<![\w@])([A-Za-z0-9._%+-]+)(?:QO|Q|©|\(at\))([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)\b"), r"\1@\2"),
    (re.compile(r"\bBZP\s*[O0](?=\d{8}\b)"), "BZP"),                          # "BZPO00999392"
]


def clean_ocr(text: str) -> str:
    """Typowe błędy OCR, które psują reguły (konfigurowalne wyłączenie: ocr.cleanup: false)."""
    for rx, rep in _OCR_FIXES:
        text = rx.sub(rep, text)
    return text


def _ocr_page(page, dpi: int, lang: str) -> str:
    import pytesseract
    from PIL import Image

    if not shutil.which(pytesseract.pytesseract.tesseract_cmd):
        win = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if win.exists():
            pytesseract.pytesseract.tesseract_cmd = str(win)
    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img, lang=lang, config="--psm 3")


def load_pdf(path: Path, settings: dict) -> Document:
    ocr_cfg = settings.get("ocr", {})
    min_chars = int(ocr_cfg.get("min_chars_per_page", 40))
    max_pages = int(settings.get("max_pages", 0)) or None
    doc = pymupdf.open(path)
    pages, ocr_pages, warnings = [], [], []
    tess_ok = None
    for i, page in enumerate(doc):
        if max_pages and i >= max_pages:
            break
        txt = page.get_text("text", sort=False) or ""
        ocr_limit = int(ocr_cfg.get("max_pages", 0)) or None
        if len(txt.strip()) < min_chars and ocr_cfg.get("enabled", True) and not (ocr_limit and i >= ocr_limit):
            if tess_ok is None:
                tess_ok = _tesseract_available(ocr_cfg.get("tesseract_cmd"))
                if not tess_ok:
                    warnings.append("Strona bez tekstu, a Tesseract nie jest zainstalowany - OCR pominięty")
            if tess_ok:
                try:
                    txt = _ocr_page(page, int(ocr_cfg.get("dpi", 300)), ocr_cfg.get("lang", "pol"))
                    if ocr_cfg.get("cleanup", True):
                        txt = clean_ocr(txt)
                    ocr_pages.append(i + 1)
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"OCR strony {i + 1} nie powiódł się: {e}")
        pages.append(txt)
    return Document(path=Path(path), pages=pages, ocr_pages=ocr_pages, warnings=warnings)
