"""GUI: wgranie PDF-ów, uruchomienie analizy, podgląd dokumentu obok wyodrębnionego JSON-a.

  python -m odw2json web   ->  http://127.0.0.1:8000
"""
from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse

from .pipeline import Engine

STATIC = Path(__file__).parent / "static"
UPLOADS = Path(tempfile.gettempdir()) / "odw2json_uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Odwołania2JSON", version="1.0")
_engine: Engine | None = None


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def status():
    e = engine()
    return {"llm": e.llm.enabled, "model": e.settings.get("llm", {}).get("model"),
            "klasy": [{"nazwa": c.name, "opis": c.description, "pola": len(c.fields)} for c in e.classes]}


@app.post("/api/extract")
async def extract(files: list[UploadFile] = File(...)):
    out = []
    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            out.append({"plik": f.filename, "blad": "To nie jest plik PDF"})
            continue
        fid = uuid.uuid4().hex
        d = UPLOADS / fid
        d.mkdir()
        p = d / Path(f.filename).name
        with p.open("wb") as fh:
            shutil.copyfileobj(f.file, fh)
        try:
            r = await run_in_threadpool(engine().process, p)
            out.append({"id": fid, "plik": p.name, "klasa": r.doc_class, "json": r.data, "slad": r.trace})
        except Exception as e:  # noqa: BLE001
            out.append({"id": fid, "plik": p.name, "blad": str(e)})
    return out


@app.get("/api/pdf/{fid}")
def pdf(fid: str):
    if not fid.isalnum():
        raise HTTPException(404)
    d = UPLOADS / fid
    files = list(d.glob("*.pdf")) if d.exists() else []
    if not files:
        raise HTTPException(404)
    return FileResponse(files[0], media_type="application/pdf",
                        headers={"Content-Disposition": "inline"})

