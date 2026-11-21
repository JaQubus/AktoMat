"""FastAPI. M1: tylko /health i mock Karty z fixtures (frontend może od razu pracować). Pełne API w M6."""
import json
from pathlib import Path

from fastapi import FastAPI

from app.config import REPO_ROOT, settings
from app.models.karta import KartaOdwolania

app = FastAPI(title="ODWOŁANIA2JSON", version="0.1.0")
FIXTURE = REPO_ROOT / "fixtures" / "karta_example.json"


@app.get("/health")
def health():
    return {"status": "ok", "offline": settings.offline, "data_dir": str(settings.data_dir)}


@app.get("/mock/karta", response_model=None)
def mock_karta():
    raw = json.loads(Path(FIXTURE).read_text(encoding="utf-8"))
    return KartaOdwolania.model_validate(raw).to_json_dict()


@app.get("/mock/krs/api/krs/OdpisAktualny/{krs}")
def mock_krs(krs: str, rejestr: str = "P", format: str = "json"):
    """Mock KRS API dla FIKCYJNYCH numerów (data/synthetic/krs_mock). Prawdziwy rejestr: patrz M4."""
    from fastapi import HTTPException

    if rejestr != "P" or not krs.isdigit():
        raise HTTPException(status_code=404, detail="Nie znaleziono podmiotu")  # jak prawdziwe API: S → retry po stronie klienta
    p = settings.data_dir / "synthetic" / "krs_mock" / f"{krs}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Nie znaleziono podmiotu")
    return json.loads(p.read_text(encoding="utf-8"))
