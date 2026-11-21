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
