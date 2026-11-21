"""Spójność danych syntetycznych: wzorce (Zał. D) muszą wskazywać pola istniejące w modelu Karty; identyfikatory — poprawne sumy."""
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.models.karta import KartaOdwolania

SYNTH = Path(__file__).resolve().parents[2] / "data" / "synthetic"
GT = sorted((SYNTH / "ground_truth").glob("case_*[!s].yaml")) if SYNTH.exists() else []
GT = [p for p in GT if not p.name.endswith(".rules.yaml")]
pytestmark = pytest.mark.skipif(not GT, reason="uruchom: make synth")


def nip_ok(n: str) -> bool:
    w = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    return len(n) == 10 and n.isdigit() and sum(int(a) * b for a, b in zip(n, w)) % 11 == int(n[9])


def regon_ok(n: str) -> bool:
    w = (8, 9, 2, 3, 4, 5, 6, 7)
    return len(n) == 9 and n.isdigit() and sum(int(a) * b for a, b in zip(n, w)) % 11 % 10 == int(n[8])


def resolve(d: dict, path: str):
    for k in path.split("."):
        assert isinstance(d, dict) and k in d, f"brak ścieżki {path} w modelu Karty"
        d = d[k]


@pytest.mark.parametrize("gt", GT, ids=lambda p: p.stem)
def test_ground_truth_paths_exist_in_model(gt):
    data = yaml.safe_load(gt.read_text(encoding="utf-8"))
    assert data["version"] == 2 and data["min_similarity"] == 0.55
    empty = KartaOdwolania.model_validate({"metadata": {"generated_at": "x", "case_id": "c"}}).to_json_dict()
    for path in data["assert"]:
        resolve(empty, path)


@pytest.mark.parametrize("gt", GT, ids=lambda p: p.stem)
def test_identifiers_valid(gt):
    a = yaml.safe_load(gt.read_text(encoding="utf-8"))["assert"]
    assert nip_ok(a["odwolujacy.nip"]) and nip_ok(a["zamawiajacy.nip"]) and regon_ok(a["odwolujacy.regon"])
    assert len(a["odwolujacy.krs"]) == 10 and a["odwolujacy.krs"].startswith("0009")  # poza zakresem istniejących KRS


def test_mock_krs_endpoint():
    c = TestClient(app)
    krs = sorted((SYNTH / "krs_mock").glob("*.json"))[0].stem
    r = c.get(f"/mock/krs/api/krs/OdpisAktualny/{krs}", params={"rejestr": "P", "format": "json"})
    assert r.status_code == 200 and r.json()["odpis"]["naglowekA"]["numerKRS"] == krs
    assert c.get("/mock/krs/api/krs/OdpisAktualny/0000000001", params={"rejestr": "P"}).status_code == 404
