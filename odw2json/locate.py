"""Położenie wartości na stronie PDF (dla GUI): słowa z ramkami z warstwy tekstowej albo z OCR skanu
i dopasowanie rozmyte szukanego tekstu do ciągu kolejnych słów.

Dopasowanie porównuje formy "zwarte" (małe litery, bez ogonków, spacji i interpunkcji), więc znajduje
NIP "999-928-40-65" dla wartości "9999284065", a na skanach toleruje typowe błędy OCR.
"""
from __future__ import annotations

import io
import logging
import re
import threading
from functools import lru_cache

import pymupdf

from .normalize import fold

log = logging.getLogger(__name__)
_lock = threading.Lock()
_cache: dict = {}          # (ścieżka, strona) -> lista słów [(x0, y0, x1, y1, tekst)] w ułamkach strony
_CACHE_MAX = 400
_inflight: dict = {}  # (ścieżka, strona) -> Event, gdy OCR strony trwa


def compact(s: str) -> str:
    return re.sub(r"[\W_]+", "", fold(str(s)).lower())


def _layer_words(page) -> list[tuple]:
    W, H = page.rect.width, page.rect.height
    return [(w[0] / W, w[1] / H, w[2] / W, w[3] / H, w[4]) for w in page.get_text("words", sort=True)]


def _ocr_words(page, ocr_cfg: dict) -> list[tuple]:
    """OCR strony z ramkami słów. Tesseract daje słowa; RapidOCR linie (dzielone na słowa proporcjonalnie)."""
    from .textract import get_ocr

    ocr = get_ocr(ocr_cfg)
    dpi = min(int(ocr_cfg.get("dpi", 300)), 300)
    if ocr.engine == "tesseract":
        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(page.get_pixmap(dpi=dpi).tobytes("png")))
        d = pytesseract.image_to_data(img, lang=ocr.lang, config="--psm 3", output_type=pytesseract.Output.DICT)
        out = []
        for i, t in enumerate(d["text"]):
            if str(t).strip():
                x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
                out.append((x / img.width, y / img.height, (x + w) / img.width, (y + h) / img.height, str(t)))
        return out
    if ocr.engine == "rapidocr":
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR

        from .textract import OCR

        with OCR._lock:
            if OCR._rapid is None:
                OCR._rapid = RapidOCR()
        pix = page.get_pixmap(dpi=min(dpi, 200))
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        res, _ = OCR._rapid(img)
        out = []
        for box, text, _score in res or []:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            n = max(1, len(text))
            for m in re.finditer(r"\S+", text):
                a, b = m.start() / n, m.end() / n
                out.append((x0 + (x1 - x0) * a, y0, x0 + (x1 - x0) * b, y1, m.group()))
        return [(a / pix.w, b / pix.h, c / pix.w, d / pix.h, t) for a, b, c, d, t in out]
    return []


def page_words(pdf_path, index: int, settings: dict, allow_ocr: bool = True) -> list[tuple]:
    """Słowa strony; `allow_ocr=False` pomija (niezbuforowany) OCR skanu, żeby nie czekać na każdą stronę."""
    key = (str(pdf_path), index)
    with _lock:
        if key in _cache:
            return _cache[key]
        busy = _inflight.get(key)
    if busy is not None and allow_ocr:
        busy.wait(120)          # ta sama strona jest właśnie OCR-owana w tle - czekamy zamiast liczyć drugi raz
        with _lock:
            if key in _cache:
                return _cache[key]
    with _lock:
        mine = key not in _inflight
        if mine:
            _inflight[key] = threading.Event()
    try:
        return _compute(pdf_path, index, settings, allow_ocr, key)
    finally:
        if mine:
            with _lock:
                _inflight.pop(key).set()


def _compute(pdf_path, index: int, settings: dict, allow_ocr: bool, key) -> list[tuple]:
    ocr_cfg = settings.get("ocr", {})
    with pymupdf.open(pdf_path) as doc:
        page = doc[index]
        words = _layer_words(page)
        if len("".join(w[4] for w in words)) < int(ocr_cfg.get("min_chars_per_page", 40)) and ocr_cfg.get("enabled", True):
            if not allow_ocr:
                return words
            try:
                words = _ocr_words(page, ocr_cfg)
            except Exception as e:  # noqa: BLE001 - brak OCR nie może psuć podglądu
                log.warning("OCR do zaznaczania nie powiódł się (str. %d): %s", index + 1, e)
    with _lock:
        if len(_cache) > _CACHE_MAX:
            _cache.clear()
        _cache[key] = words
    return words


@lru_cache(maxsize=4096)
def _ratio(a: str, b: str) -> float:
    from rapidfuzz import fuzz

    return fuzz.ratio(a, b)


def match(words: list[tuple], query: str, min_score: float = 85) -> tuple[float, list[tuple]]:
    """Najlepszy ciąg kolejnych słów odpowiadający `query`. Zwraca (wynik 0-100, ramki słów)."""
    q = compact(query)
    if len(q) < 2:
        return 0.0, []
    comp = [compact(w[4]) for w in words]
    best, span = 0.0, None
    for i in range(len(words)):
        if not comp[i]:
            continue
        acc = ""
        for j in range(i, min(len(words), i + 40)):
            acc += comp[j]
            if q in acc and (len(q) >= 4 or acc == q):
                # wartość zawarta w ciągu słów (np. NIP sklejony z etykietą "NIP:9999...") — bierzemy najkrótszy ciąg
                score = 100.0 - (len(acc) - len(q)) * 0.1
            else:
                score = _ratio(acc, q) if len(acc) >= len(q) * 0.6 else 0.0
            if score > best:
                best, span = score, (i, j)
            if len(acc) > len(q) * 1.4:
                break
    if not span or best < min_score:
        return best, []
    i, j = span
    return best, _merge_lines(words[i:j + 1])


def _merge_lines(ws: list[tuple]) -> list[list[float]]:
    """Ramki słów scalone w jedną ramkę na linię (czytelniejsze zaznaczenie)."""
    rects: list[list[float]] = []
    for x0, y0, x1, y1, _ in ws:
        if rects and abs(rects[-1][1] - y0) < (y1 - y0) * 0.6 and x0 >= rects[-1][0] - 0.01:
            r = rects[-1]
            r[0], r[1], r[2], r[3] = min(r[0], x0), min(r[1], y0), max(r[2], x1), max(r[3], y1)
        else:
            rects.append([x0, y0, x1, y1])
    return rects


def locate(pdf_path, queries: list[str], page_hint: int, settings: dict, page_count: int,
           min_score: float = 85) -> dict:
    """Szuka kolejnych wariantów tekstu (np. surowy zapis, wartość, fragment cytatu), najpierw na stronie
    ze śladu ekstrakcji, potem na pozostałych. Pierwszy wariant z dopasowaniem wygrywa."""
    order = ([page_hint - 1] if 1 <= page_hint <= page_count else []) + \
            [i for i in range(page_count) if i != page_hint - 1]
    for q in queries:
        q = " ".join(str(q).split())[:160]
        if len(compact(q)) < 2:
            continue
        for i in order:
            score, rects = match(page_words(pdf_path, i, settings, allow_ocr=(i == order[0])), q, min_score)
            if rects:
                return {"strona": i + 1, "prostokaty": rects, "dopasowanie": round(score), "tekst": q}
    return {"strona": page_hint or None, "prostokaty": [], "dopasowanie": 0, "tekst": None}
