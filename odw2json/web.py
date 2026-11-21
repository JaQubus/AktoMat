"""GUI: wczytanie PDF-ów (pojedynczo, folder sprawy albo ZIP), automatyczna klasyfikacja,
podgląd dokumentu obok wyodrębnionych danych, poprawki ręczne i eksport ZIP w układzie output/<sprawa>/.

  python -m odw2json web   ->  http://127.0.0.1:8000
"""
from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
import os
import re
import shutil
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import yaml
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from .config import CONFIG_DIR, ROOT
from .wordfile import DOCX_MIME, build_docx
from .anonymize import Anonymizer, load_export_config
from .checks import load_rules, run_checks
from .locate import locate, page_words
from .pipeline import Engine

STATIC = Path(__file__).parent / "static"
# Dane pracy referenta (sesje i wczytane PDF-y) poza repozytorium kodu w git: katalog sesje/ jest w .gitignore.
DATA = Path(os.environ.get("AKTOMAT_DANE") or ROOT / "sesje")
UPLOADS = DATA / "pliki"
SESSIONS = DATA / "zapis"
UPLOADS.mkdir(parents=True, exist_ok=True)
SESSIONS.mkdir(parents=True, exist_ok=True)
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


@app.delete("/api/pliki/{fid}")
def usun_plik(fid: str):
    """Usuwa wczytany PDF (np. po usunięciu sprawy z sesji)."""
    if not fid.isalnum():
        raise HTTPException(404)
    shutil.rmtree(UPLOADS / fid, ignore_errors=True)
    return {"ok": True}


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


@app.get("/api/eksport")
def eksport_konfig():
    """Ustawienia eksportu z config/eksport.yaml (ukrywanie danych osobowych, kolumny rejestru spraw)."""
    return load_export_config()


@app.post("/api/zip")
def eksport_zip(pliki: list[dict] = Body(..., embed=True), inne: list[dict] | None = Body(None, embed=True),
                ukryj: bool = Body(False, embed=True)):
    """ZIP z wynikami: [{"sciezka": "sprawa/plik.json", "json": {...}}] -> output/<sprawa>/<plik>.json.
    `inne`: dodatkowe pliki tekstowe w katalogu głównym ZIP-a, np. [{"sciezka": "dziennik_zmian.csv", "tekst": "..."}].
    `ukryj`: ukrywa dane osobowe (config/eksport.yaml) w JSON-ach i w plikach `inne`."""
    anon = None
    if ukryj:
        anon = Anonymizer()
        for item in pliki:
            anon.collect(item.get("json"))
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
            if anon and not isinstance(data, str):
                data = anon.json(data)
            body = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
            zf.writestr("output/" + rel, body)
        for item in inne or []:
            name = str(_safe_rel(str(item.get("sciezka", "plik.txt"))))
            if name.lower().endswith((".csv", ".txt", ".md")):
                txt = str(item.get("tekst", ""))
                if anon:
                    txt = anon.text(txt)
                zf.writestr(name, "\ufeff" + txt if name.endswith(".csv") else txt)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="wyniki_aktomat.zip"'})


@app.get("/api/pisma")
def pisma():
    """Szablony pism z config/pisma.yaml (projekt wezwania do uzupełnienia braków)."""
    p = CONFIG_DIR / "pisma.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {"pisma": []}


@app.post("/api/docx")
def docx(tekst: str = Body(..., embed=True), nazwa: str = Body("pismo", embed=True)):
    """Tekst pisma -> .docx. "# " tytuł, "> " do prawej, **pogrubienie**, pusta linia = nowy akapit."""
    name = re.sub(r"[^\w\- ]+", "", nazwa).strip() or "pismo"
    return Response(build_docx(tekst), media_type=DOCX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="{name}.docx"'})


# ---------- sesje: zapis pracy referenta na serwerze ----------

def _sid(sid: str) -> str:
    if not re.fullmatch(r"[a-z0-9]{8,40}", sid or ""):
        raise HTTPException(404)
    return sid


def _session_meta(p: Path) -> dict | None:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    items = (d.get("stan") or {}).get("items") or []
    cases = sorted({i.get("sprawa") for i in items if i.get("sprawa")})
    return {"id": p.stem, "nazwa": d.get("nazwa") or p.stem, "referent": d.get("referent") or "",
            "zmieniono": d.get("zmieniono"), "sprawy": cases, "dokumenty": len(items)}


@app.get("/api/sesje")
def sesje():
    """Zapisane sesje, od ostatnio zmienionej."""
    out = [m for m in (_session_meta(p) for p in SESSIONS.glob("*.json")) if m]
    return sorted(out, key=lambda m: m.get("zmieniono") or "", reverse=True)


@app.get("/api/sesje/{sid}")
def sesja(sid: str):
    p = SESSIONS / f"{_sid(sid)}.json"
    if not p.exists():
        raise HTTPException(404)
    return json.loads(p.read_text(encoding="utf-8"))


@app.put("/api/sesje/{sid}")
def zapisz_sesje(sid: str, nazwa: str = Body("", embed=True), referent: str = Body("", embed=True),
                 stan: dict = Body(..., embed=True)):
    """Zapis stanu pracy (dokumenty, poprawki, zatwierdzenia, pominięcia, dziennik). Zapis atomowy."""
    p = SESSIONS / f"{_sid(sid)}.json"
    body = {"nazwa": nazwa[:200], "referent": referent[:200],
            "zmieniono": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "stan": stan}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return {"ok": True, "zmieniono": body["zmieniono"]}


@app.delete("/api/sesje/{sid}")
def usun_sesje(sid: str):
    """Usuwa sesję i jej wczytane PDF-y."""
    p = SESSIONS / f"{_sid(sid)}.json"
    if not p.exists():
        raise HTTPException(404)
    try:
        items = (json.loads(p.read_text(encoding="utf-8")).get("stan") or {}).get("items") or []
    except ValueError:
        items = []
    for it in items:
        fid = str(it.get("id") or "")
        if fid.isalnum() and (UPLOADS / fid).is_dir():
            shutil.rmtree(UPLOADS / fid, ignore_errors=True)
    p.unlink()
    return {"ok": True}


# ---------- rejestr spraw ze wszystkich zapisanych sesji ----------

def _norm_key(v) -> str:
    return re.sub(r"[\W_]+", "", str(v or "")).upper()


def _first(docs, klasa, path):
    from .checks import values
    for d in docs:
        if d.get("klasa") == klasa and isinstance(d.get("json"), dict):
            v = values(d["json"], path)
            if v:
                return v[0]
    return None


@app.get("/api/rejestr")
def rejestr():
    """Wszystkie sprawy ze wszystkich zapisanych sesji: strony, numery, braki (z pominięciami referenta)
    i powiązania: ta sama sprawa (nr postępowania, ogłoszenie BZP albo TED) w innych sprawach."""
    rules = load_rules()
    rows = []
    for p in SESSIONS.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        st = d.get("stan") or {}
        by_case: dict[str, list] = {}
        for it in st.get("items") or []:
            by_case.setdefault(it.get("sprawa") or "bez sprawy", []).append(it)
        for case, items in by_case.items():
            docs = [{"plik": i.get("plik"), "klasa": i.get("klasa"), "json": i.get("json")} for i in items if not i.get("blad")]
            res = run_checks(docs, rules, (st.get("termDays") or {}))
            skip = (st.get("skip") or {}).get(case) or {}
            braki = [x["opis"] for kind in ("wymagane", "pola", "zgodnosc") for x in res[kind]
                     if x["wynik"] in ("brak", "niezgodne") and f"{kind}:{x['id']}" not in skip]
            term = (res.get("terminy") or [{}])[0]
            rows.append({
                "sesja": p.stem, "sesja_nazwa": d.get("nazwa") or p.stem, "referent": d.get("referent") or "",
                "zmieniono": d.get("zmieniono"), "sprawa": case, "dokumenty": len(items),
                "klasy": sorted({i.get("klasa") for i in items if i.get("klasa")}),
                "odwolujacy": _first(docs, "odwolanie", "Odwolujacy[*].nazwa"),
                "nip": _first(docs, "odwolanie", "Odwolujacy[*].nip"),
                "zamawiajacy": _first(docs, "odwolanie", "Zamawiajacy[*].nazwa"),
                "nip_zamawiajacego": _first(docs, "odwolanie", "Zamawiajacy[*].nip"),
                "numer_postepowania": _first(docs, "odwolanie", "ZamowieniePubliczne.numer_postepowania"),
                "numer_bzp": _first(docs, "odwolanie", "ZamowieniePubliczne.numer_bzp"),
                "numer_ted": _first(docs, "odwolanie", "ZamowieniePubliczne.numer_ted"),
                "czynnosc_dzien": _first(docs, "odwolanie", "OdwolanieKIO.czynnosc_dzien"),
                "termin": term.get("do"), "braki": braki, "pominiete": len(skip),
            })
    keys = ("numer_postepowania", "numer_bzp", "numer_ted")
    index: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        for k in keys:
            if r.get(k):
                index.setdefault((k, _norm_key(r[k])), []).append(i)
    for i, r in enumerate(rows):
        rel = {}
        for k in keys:
            for j in index.get((k, _norm_key(r.get(k))), []) if r.get(k) else []:
                if j != i:
                    rel.setdefault(j, set()).add(k)
        r["powiazane"] = [{"sesja": rows[j]["sesja"], "sprawa": rows[j]["sprawa"], "odwolujacy": rows[j]["odwolujacy"],
                           "przez": sorted(v)} for j, v in rel.items()]
    return sorted(rows, key=lambda r: r.get("zmieniono") or "", reverse=True)
