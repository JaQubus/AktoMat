"""GUI: wczytanie PDF-ów (pojedynczo, folder sprawy albo ZIP), automatyczna klasyfikacja,
podgląd dokumentu obok wyodrębnionych danych, poprawki ręczne i eksport ZIP w układzie output/<sprawa>/.

  python -m odw2json web   ->  http://127.0.0.1:8000
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from .config import ROOT
from .checks import load_rules, run_checks
from .locate import locate, page_words
from .pipeline import Engine

STATIC = Path(__file__).parent / "static"
UPLOADS = Path(tempfile.gettempdir()) / "odw2json_uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / "eval_report" / "raport.md"
MAX_ZIP_FILES = 500

app = FastAPI(title="AktoMat", version="1.2")
_engine: Engine | None = None
_sem: asyncio.Semaphore | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine


def _limit() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(max(1, int(engine().settings.get("workers", 4))))
    return _sem


def _safe_rel(name: str) -> PurePosixPath:
    """Ścieżka względna bez '..', liter dysków i ukośników na początku (ochrona przed zip-slip)."""
    parts = [p for p in re.split(r"[\\/]+", name or "") if p not in ("", ".", "..") and ":" not in p]
    return PurePosixPath(*parts) if parts else PurePosixPath("dokument.pdf")


def _case_of(rel: PurePosixPath, default: str) -> str:
    return rel.parts[-2] if len(rel.parts) > 1 else default


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def status():
    e = engine()
    ocr = e.settings.get("ocr", {})
    return {"llm": e.llm.enabled, "model": e.settings.get("llm", {}).get("model"),
            "ocr": bool(ocr.get("enabled", True)), "ocr_silnik": ocr.get("engine", "auto"),
            "pusty_json": e.settings.get("unknown_output", "{}"),
            "raport": REPORT.exists(),
            "klasy": [{"nazwa": c.name, "opis": c.description, "pola": len(c.fields),
                       "prog": float(c.classify.get("min_score", 3))} for c in e.classes]}


@app.get("/api/klasy")
def klasy():
    """Klasy dokumentów prosto z config/classes/*.yaml — pokazuje, że nowa klasa = nowy plik YAML."""
    out = []
    for c in engine().classes:
        out.append({
            "nazwa": c.name, "opis": c.description, "plik": c.source.name,
            "prog": float(c.classify.get("min_score", 3)),
            "slowa_kluczowe": len(c.classify.get("keywords", [])),
            "wykluczenia": len(c.classify.get("negative", [])),
            "szablon": c.output_template,
            "pola": [{"sciezka": f.path, "typ": f.type, "opis": f.description,
                      "zrodlo": "wyliczane" if f.derive else (f.prefer or "domyślne"),
                      "reguly": len(f.rules), "weryfikacja": f.require_grounding} for f in c.fields],
        })
    return out


@app.get("/api/raport")
def raport():
    if not REPORT.exists():
        return {"jest": False, "tekst": ""}
    return {"jest": True, "tekst": REPORT.read_text(encoding="utf-8")}


async def _process(p: Path, fid: str, case: str, rel: str) -> dict:
    async with _limit():
        try:
            r = await run_in_threadpool(engine().process, p)
        except Exception as e:  # noqa: BLE001 - jeden zły plik nie zatrzymuje partii
            return {"id": fid, "plik": p.name, "sprawa": case, "sciezka": rel, "blad": str(e)}
    if r.trace.get("ocr_strony"):
        _prefetch_words(p, r.trace["ocr_strony"])
    return {"id": fid, "plik": p.name, "sprawa": case, "sciezka": rel,
            "klasa": r.doc_class, "json": r.data, "slad": r.trace}


def _store(name: str, data) -> tuple[str, Path]:
    fid = uuid.uuid4().hex
    d = UPLOADS / fid
    d.mkdir()
    p = d / _safe_rel(name).name
    with p.open("wb") as fh:
        if isinstance(data, bytes):
            fh.write(data)
        else:
            shutil.copyfileobj(data, fh)
    return fid, p


@app.post("/api/extract")
async def extract(files: list[UploadFile] = File(...), sciezki: list[str] | None = Form(None)):
    """Przyjmuje PDF-y i/lub archiwa ZIP. `sciezki` (opcjonalnie, w tej samej kolejności co pliki)
    to ścieżki względne z wybranego folderu: katalog nadrzędny pliku = nazwa sprawy."""
    jobs, out = [], []
    for i, f in enumerate(files):
        given = sciezki[i] if sciezki and i < len(sciezki) and sciezki[i] else f.filename
        rel = _safe_rel(given)
        low = rel.name.lower()
        if low.endswith(".zip"):
            try:
                zf = zipfile.ZipFile(io.BytesIO(await f.read()))
            except zipfile.BadZipFile:
                out.append({"plik": rel.name, "sprawa": rel.stem, "blad": "Uszkodzone archiwum ZIP"})
                continue
            members = [m for m in zf.infolist() if not m.is_dir() and m.filename.lower().endswith(".pdf")
                       and not PurePosixPath(m.filename).name.startswith(("._", "~$"))]
            if not members:
                out.append({"plik": rel.name, "sprawa": rel.stem, "blad": "Archiwum nie zawiera plików PDF"})
            for m in members[:MAX_ZIP_FILES]:
                mrel = _safe_rel(m.filename)
                fid, p = _store(mrel.name, zf.read(m))
                jobs.append((p, fid, _case_of(mrel, rel.stem), str(mrel)))
        elif low.endswith(".pdf"):
            fid, p = _store(rel.name, f.file)
            jobs.append((p, fid, _case_of(rel, "bez sprawy"), str(rel)))
        else:
            out.append({"plik": rel.name, "sprawa": _case_of(rel, "bez sprawy"),
                        "blad": "Nieobsługiwany format: wczytaj PDF albo ZIP"})
    out += await asyncio.gather(*(_process(*j) for j in jobs))
    return out


def _pdf_path(fid: str) -> Path:
    if not fid.isalnum():
        raise HTTPException(404)
    d = UPLOADS / fid
    files = list(d.glob("*.pdf")) if d.exists() else []
    if not files:
        raise HTTPException(404)
    return files[0]


@app.get("/api/pdf/{fid}")
def pdf(fid: str):
    return FileResponse(_pdf_path(fid), media_type="application/pdf",
                        headers={"Content-Disposition": "inline"})


@app.get("/api/strona/{fid}/{n}")
def strona(fid: str, n: int, skala: float = 1.6):
    """Strona PDF jako PNG (podgląd działa w każdej przeglądarce i pozwala zaznaczać cytaty)."""
    import pymupdf as fitz

    with fitz.open(_pdf_path(fid)) as doc:
        if not 1 <= n <= doc.page_count:
            raise HTTPException(404)
        s = min(max(skala, 0.5), 3.0)
        png = doc[n - 1].get_pixmap(matrix=fitz.Matrix(s, s), alpha=False).tobytes("png")
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/info/{fid}")
def info(fid: str):
    import pymupdf as fitz

    with fitz.open(_pdf_path(fid)) as doc:
        return {"strony": [{"w": p.rect.width, "h": p.rect.height} for p in doc]}


@app.get("/api/szukaj/{fid}")
def szukaj(fid: str, q: list[str] = Query(default=[]), strona: int = 0):
    """Położenie fragmentu tekstu na stronie: prostokąty w ułamkach szerokości/wysokości strony.
    Działa na warstwie tekstowej i na skanach (ramki słów z OCR). Kolejne `q` to warianty od najlepszego
    (surowy zapis z dokumentu, wartość, fragment cytatu); najpierw szuka na stronie `strona`."""
    import pymupdf

    p = _pdf_path(fid)
    with pymupdf.open(p) as doc:
        n = doc.page_count
    return locate(p, q, strona, engine().settings, n)


def _prefetch_words(p: Path, pages: list[int]):
    """W tle: OCR z ramkami dla stron-skanów, żeby pierwsze kliknięcie pola nie czekało na OCR."""
    def run():
        for n in pages:
            try:
                page_words(p, n - 1, engine().settings)
            except Exception:  # noqa: BLE001
                pass
    threading.Thread(target=run, daemon=True).start()


@app.post("/api/kontrola")
def kontrola(dokumenty: list[dict] = Body(..., embed=True), dni: dict | None = Body(None, embed=True)):
    """Kontrola formalna teczki: [{"plik", "klasa", "json"}] -> kompletność, zgodność, terminy, walidacja.
    Reguły: config/kontrola.yaml. `dni` nadpisuje liczbę dni terminu, np. {"odwolanie": 5}."""
    return run_checks(dokumenty, load_rules(), dni)


@app.get("/api/kontrola/reguly")
def kontrola_reguly():
    return load_rules()


@app.post("/api/zip")
def eksport_zip(pliki: list[dict] = Body(..., embed=True), inne: list[dict] | None = Body(None, embed=True)):
    """ZIP z wynikami: [{"sciezka": "sprawa/plik.json", "json": {...}}] -> output/<sprawa>/<plik>.json.
    `inne`: dodatkowe pliki tekstowe w katalogu głównym ZIP-a, np. [{"sciezka": "dziennik_zmian.csv", "tekst": "..."}]."""
    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in pliki:
            rel = str(_safe_rel(str(item.get("sciezka", "wynik.json"))))
            if not rel.lower().endswith(".json"):
                rel += ".json"
            base, k = rel, 2
            while rel in used:
                rel = base[:-5] + f" ({k}).json"
                k += 1
            used.add(rel)
            data = item.get("json")
            body = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
            zf.writestr("output/" + rel, body)
        for item in inne or []:
            name = str(_safe_rel(str(item.get("sciezka", "plik.txt"))))
            if name.lower().endswith((".csv", ".txt", ".md")):
                zf.writestr(name, "\ufeff" + str(item.get("tekst", "")) if name.endswith(".csv") else str(item.get("tekst", "")))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="wyniki_aktomat.zip"'})
