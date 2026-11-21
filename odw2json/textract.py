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
    alt_pages: dict = field(default_factory=dict)  # inne odczyty układu stron OCR, np. {"columns": [...]}

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
    (re.compile(r"(?<![\w@])([A-Za-z0-9._%+-]+) ?(?:QO|Q©|Q|©|\(at\)) ?([a-z0-9-]+(?:\.[A-Za-z0-9-]+)+)\b"), r"\1@\2"),
    (re.compile(r"\b(20\d{2}) ?/ ?[S5] ?(\d{3}) ?- ?(\d{6})\b"), r"\1/S \2-\3"),           # TED "2026/5189-999923"
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
            data = pytesseract.image_to_data(img, lang=self.lang, config="--psm 3",
                                             output_type=pytesseract.Output.DICT)
            lines = _tess_lines(data)
            rows = "\n".join(" ".join(w[2] for w in ln) for ln in lines)
            # drugi odczyt: kolumny jedna po drugiej (np. dwa bloki podpisów obok siebie);
            # klasa wybiera go w YAML (ocr_layout: columns), domyślnie zostaje odczyt wierszami
            return {"rows": rows, "columns": columns_to_text(lines, img.width)}
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


def _tess_lines(d: dict) -> list[list[tuple[int, int, str]]]:
    """Słowa z image_to_data pogrupowane w linie: [(x0, x1, słowo), ...] w kolejności czytania."""
    lines: dict = {}
    for i, w in enumerate(d["text"]):
        if not str(w).strip():
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        lines.setdefault(key, {"top": d["top"][i], "words": []})
        lines[key]["words"].append((d["left"][i], d["left"][i] + d["width"][i], str(w)))
    out = sorted(lines.values(), key=lambda ln: ln["top"])
    return [sorted(ln["words"]) for ln in out]


def columns_to_text(lines: list[list[tuple[int, int, str]]], page_w: int, gap_frac: float = 0.06) -> str:
    """Odtwarza kolejność kolumn, którą OCR skleja w jedną linię ("Za A   Za B" / "Jan X   Anna Y").

    Linia dzieli się na segmenty w miejscach dużej przerwy poziomej. Kolejne linie z segmentami
    w tych samych kolumnach tworzą blok; blok wypisujemy kolumnami (najpierw cała lewa, potem prawa),
    tak jak warstwa tekstowa PDF-a z dwoma blokami podpisów albo nagłówkiem "Mocodawca | Pełnomocnik".
    """
    gap, tol = page_w * gap_frac, page_w * 0.05
    segs_per_line = []
    for words in lines:
        segs, cur = [], [words[0]]
        for w in words[1:]:
            if w[0] - cur[-1][1] > gap:
                segs.append(cur)
                cur = [w]
            else:
                cur.append(w)
        segs.append(cur)
        segs_per_line.append([(sg[0][0], sg[-1][1], " ".join(x[2] for x in sg)) for sg in segs])

    out, run_cols, run = [], None, []

    def flush():
        nonlocal run, run_cols
        if run_cols:
            for c in range(len(run_cols)):
                out.extend(t for line in run for (ci, t) in line if ci == c)
        run, run_cols = [], None

    for segs in segs_per_line:
        if len(segs) >= 2 and run_cols is None:
            run_cols = [x0 for x0, _, _ in segs]
        if run_cols is None:
            out.append(segs[0][2])
            continue
        placed = []
        bounds = [(a + b) / 2 for a, b in zip(run_cols, run_cols[1:])]   # granice między kolumnami
        for x0, x1, t in segs:
            if len(segs) == 1:
                # pojedynczy fragment: musi zaczynać się przy którejś kolumnie (np. "KRS ..." pod nazwą)
                ci = min(range(len(run_cols)), key=lambda c: abs(run_cols[c] - x0))
                ok = abs(run_cols[ci] - x0) <= tol
            else:
                # kilka fragmentów (np. wyśrodkowane podpisy): kolumna wg środka fragmentu
                ci = sum(1 for b in bounds if (x0 + x1) / 2 > b)
                ok = True
            if not ok or any(x0 < b < x1 for b in bounds):
                placed = None   # fragment poza kolumnami albo przez całą szerokość: koniec bloku
                break
            placed.append((ci, t))
        if placed is None:
            flush()
            if len(segs) >= 2:
                run_cols = [x0 for x0, _, _ in segs]
                run.append([(i, t) for i, (_, _, t) in enumerate(segs)])
            else:
                out.append(" ".join(t for _, _, t in segs))
            continue
        run.append(placed)
    flush()
    return "\n".join(out)


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
    alt: dict = {}
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
                    res = ocr.page(page)
                    layouts = res if isinstance(res, dict) else {"rows": res}
                    if ocr_cfg.get("cleanup", True):
                        layouts = {k: clean_ocr(v) for k, v in layouts.items()}
                    txt = layouts.pop("rows")
                    for k, v in layouts.items():
                        alt.setdefault(k, list(pages)).append(v)
                    ocr_pages.append(i + 1)
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"OCR strony {i + 1} nie powiódł się: {e}")
        pages.append(txt)
        for k, v in alt.items():
            if len(v) < len(pages):
                v.append(txt)
    return Document(path=Path(path), pages=pages, ocr_pages=ocr_pages, warnings=warnings,
                    ocr_engine=ocr.engine if ocr else None, alt_pages=alt)
