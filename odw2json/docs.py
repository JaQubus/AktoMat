"""Dokumentacja AktoMat jako strona WWW.

  python -m odw2json docs        # osobny serwer: http://127.0.0.1:8001 (otwiera przeglądarkę)
  python -m odw2json web         # GUI; dokumentacja także pod /dokumentacja

Treść jest w docs/index.html. Część „Konfiguracja na żywo” strona pobiera z /dokumentacja/konfiguracja.json,
które jest czytane wprost z config/*.yaml przy każdym wejściu, więc nowa klasa dokumentu, pole albo reguła
kontroli pojawia się w dokumentacji bez zmian w kodzie i bez ręcznego dopisywania.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from .config import CONFIG_DIR, ROOT, load_classes, load_settings

DOCS = ROOT / "docs"
IMG = DOCS / "img"
PREFIX = "/dokumentacja"

router = APIRouter()


def _yaml(name: str) -> dict:
    p = CONFIG_DIR / name
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _rule_kinds() -> list[dict]:
    """Rodzaje reguł z docstringu odw2json/rules.py (jedno źródło prawdy)."""
    from . import rules

    out = []
    for line in (rules.__doc__ or "").splitlines():
        m = re.match(r"\s{2}(\w+)\s+-\s+(.+)", line)
        if m:
            out.append({"nazwa": m.group(1), "opis": m.group(2).strip()})
    return out


def konfiguracja() -> dict:
    """Bieżąca konfiguracja z YAML, bez kluczy API (te są tylko w .env)."""
    s = load_settings()
    llm = s.get("llm", {}) or {}
    ocr = s.get("ocr", {}) or {}
    klasy = []
    for c in load_classes():
        klasy.append({
            "nazwa": c.name, "opis": c.description, "plik": c.source.name,
            "prog": c.classify.get("min_score", 3),
            "slowa_kluczowe": len(c.classify.get("keywords", []) or []),
            "wykluczenia": len(c.classify.get("negative", []) or []),
            "sekcje": sorted((c.sections or {}).keys()),
            "listy": sorted((c.lists or {}).keys()),
            "ocr_layout": c.ocr_layout,
            "pola": [{
                "sciezka": f.path, "typ": f.type, "opis": f.description,
                "reguly": [r.get("kind", "regex") if isinstance(r, dict) else "regex" for r in f.rules],
                "zrodlo": "wyliczane" if f.derive else (f.prefer or "llm, potem reguły"),
                "weryfikacja": bool(f.require_grounding and not f.derive),
                "slownik": bool(f.vocabulary),
            } for f in c.fields],
        })
    k = _yaml("kontrola.yaml")
    p = _yaml("pisma.yaml")
    e = _yaml("eksport.yaml")
    return {
        "llm": {
            "wlaczony": bool(llm.get("enabled", True)), "model": llm.get("model"), "adres": llm.get("base_url"),
            "temperatura": llm.get("temperature"), "limit_s": llm.get("timeout"),
            "znaki_dokumentu": llm.get("max_doc_chars"),
            "profile": [{"nazwa": n, "model": (v or {}).get("model"), "adres": (v or {}).get("base_url")}
                        for n, v in ((_yaml("settings.yaml").get("llm") or {}).get("profiles") or {}).items()],
        },
        "ocr": {"wlaczony": bool(ocr.get("enabled", True)), "silnik": ocr.get("engine", "auto"),
                "jezyk": ocr.get("lang"), "dpi": ocr.get("dpi"), "max_stron": ocr.get("max_pages")},
        "rownoleglosc": s.get("workers"), "budzet_s": s.get("time_budget_s"),
        "pusty_json": s.get("unknown_output"),
        "klasy": klasy,
        "reguly": _rule_kinds(),
        "kontrola": {
            "wymagane": [{"opis": w.get("opis"), "klasa": w.get("klasa"), "poziom": w.get("poziom", "brak")}
                         for w in k.get("wymagane", []) or []],
            "pola": [{"opis": w.get("opis"), "pole": w.get("pole"), "poziom": w.get("poziom", "brak")}
                     for w in k.get("pola", []) or []],
            "zgodnosc": [{"opis": z.get("opis"), "tryb": z.get("tryb")} for z in k.get("zgodnosc", []) or []],
            "terminy": [{"opis": t.get("opis"), "dni": t.get("dni"), "warianty": t.get("warianty")}
                        for t in k.get("terminy", []) or []],
            "walidacja": k.get("walidacja", {}) or {},
        },
        "pisma": [x.get("nazwa") for x in p.get("pisma", []) or []],
        "eksport": {"ukrywane_pola": ((e.get("dane_osobowe") or {}).get("pola") or []),
                    "kolumny_rejestru": [c.get("naglowek") for c in (e.get("rejestr") or {}).get("kolumny", []) or []]},
    }


@router.get(PREFIX, response_class=HTMLResponse)
def strona():
    return (DOCS / "index.html").read_text(encoding="utf-8")


@router.get(PREFIX + "/konfiguracja.json")
def konfiguracja_json():
    return konfiguracja()


@router.get(PREFIX + "/img/{nazwa}")
def obraz(nazwa: str):
    if not re.fullmatch(r"[\w-]+\.(?:jpg|png|svg)", nazwa):
        raise HTTPException(404)
    p = IMG / nazwa
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


# Osobny serwer samej dokumentacji (python -m odw2json docs).
app = FastAPI(title="AktoMat: dokumentacja", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)


@app.get("/", include_in_schema=False)
def _root():
    return RedirectResponse(PREFIX)
