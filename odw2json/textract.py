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
    ocr_engine: str | None = None

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


import re
import threading

WIN_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

_OCR_FIXES = [
    (re.compile(r"\n[ \t]*\n+"), "\n"),                                   # Tesseract rozdziela akapity pustą linią
    (re.compile(r"\bsp\.\s*[zZ]\s*[0oO]\.\s*[0oO]\.?"), "sp. z o.o."),     # "sp. Z 0.0." -> "sp. z o.o."
    (re.compile(r"(?<![\w@])([A-Za-z0-9._%+-]+)(?:QO|Q|©|\(at\))([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)\b"), r"\1@\2"),
    (re.compile(r"\bBZP\s*[O0](?=\d{8}\b)"), "BZP"),                          # "BZPO00999392"
    (re.compile(r"\bREG[0O]N\b"), "REGON"),
]


def clean_ocr(text: str) -> str:
    """Typowe błędy OCR, które psują reguły (wyłączenie: ocr.cleanup: false)."""
    for rx, rep in _OCR_FIXES:
        text = rx.sub(rep, text)
    return text


class OCR:
    """Wybór silnika OCR: Tesseract (najlepszy dla polskiego) albo RapidOCR (sam pip, bez instalacji systemowej).

    ocr.engine: auto | tesseract | rapidocr. W trybie auto: Tesseract, jeśli jest; inaczej RapidOCR.
    """
    _lock = threading.Lock()
    _rapid = None

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.engine, self.lang, self.note = self._pick()

    def _tesseract(self):
        try:
            import pytesseract
        except ImportError:
            return None
        cmd = self.cfg.get("tesseract_cmd")
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        elif not shutil.which("tesseract") and WIN_TESSERACT.exists():
            pytesseract.pytesseract.tesseract_cmd = str(WIN_TESSERACT)
        try:
            return set(pytesseract.get_languages(config=""))
        except Exception:  # noqa: BLE001 - brak binarki
            return None

    def _pick(self):
        want = self.cfg.get("engine", "auto")
        lang = self.cfg.get("lang", "pol")
        if want in ("auto", "tesseract"):
            langs = self._tesseract()
            if langs:
                if lang in langs:
                    return "tesseract", lang, None
                return "tesseract", "eng", f"Tesseract bez języka '{lang}' - używam 'eng' (gorsze polskie znaki)"
            if want == "tesseract":
                return None, None, "Tesseract nie jest zainstalowany - OCR pominięty"
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return "rapidocr", None, ("Brak Tesseract - używam RapidOCR (bez polskich znaków)"
                                      if want == "auto" else None)
        except ImportError:
            return None, None, "Brak silnika OCR (Tesseract / rapidocr_onnxruntime) - skany pominięte"

    def page(self, page) -> str:
        dpi = int(self.cfg.get("dpi", 300))
        if self.engine == "tesseract":
            import pytesseract
            from PIL import Image

            img = Image.open(io.BytesIO(page.get_pixmap(dpi=dpi).tobytes("png")))
            return pytesseract.image_to_string(img, lang=self.lang, config="--psm 3")
        if self.engine == "rapidocr":
            import numpy as np
            from rapidocr_onnxruntime import RapidOCR

            with OCR._lock:
                if OCR._rapid is None:
                    OCR._rapid = RapidOCR()
            pix = page.get_pixmap(dpi=min(dpi, 200))
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            res, _ = OCR._rapid(img)
            return "\n".join(r[1] for r in (res or []))
        return ""


_OCR_CACHE: dict = {}


def get_ocr(cfg: dict) -> OCR:
    key = (cfg.get("engine", "auto"), cfg.get("lang", "pol"), cfg.get("tesseract_cmd"))
    if key not in _OCR_CACHE:
        _OCR_CACHE[key] = OCR(cfg)
    return _OCR_CACHE[key]


def load_pdf(path: Path, settings: dict) -> Document:
    ocr_cfg = settings.get("ocr", {})
    min_chars = int(ocr_cfg.get("min_chars_per_page", 40))
    max_pages = int(settings.get("max_pages", 0)) or None
    ocr_limit = int(ocr_cfg.get("max_pages", 0)) or None
    doc = pymupdf.open(path)
    pages, ocr_pages, warnings = [], [], []
    ocr = None
    for i, page in enumerate(doc):
        if max_pages and i >= max_pages:
            break
        txt = page.get_text("text", sort=False) or ""
        if len(txt.strip()) < min_chars and ocr_cfg.get("enabled", True) and not (ocr_limit and i >= ocr_limit):
            if ocr is None:
                ocr = get_ocr(ocr_cfg)
                if ocr.note:
                    warnings.append(ocr.note)
            if ocr.engine:
                try:
                    txt = ocr.page(page)
                    if ocr_cfg.get("cleanup", True):
                        txt = clean_ocr(txt)
                    ocr_pages.append(i + 1)
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"OCR strony {i + 1} nie powiódł się: {e}")
        pages.append(txt)
    return Document(path=Path(path), pages=pages, ocr_pages=ocr_pages, warnings=warnings,
                    ocr_engine=ocr.engine if ocr else None)
