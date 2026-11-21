"""Test end-to-end na wygenerowanym PDF (bez LLM) i z udawanym LLM, który halucynuje."""
import json

import pymupdf
import pytest

from odw2json.llm import LLMClient
from odw2json.pipeline import Engine, run

PRZELEW = """POTWIERDZENIE WYKONANIA PRZELEWU
Rachunek zleceniodawcy
PL07 1044 6255 1544 8206 2521 6547
Rachunek odbiorcy
PL28 1369 0218 8320 8799 8443 6720
Kwota
100,00 PLN
Data operacji
21.07.2026
Tytul przelewu
oplata skarbowa od pelnomocnictwa ZP.271.93.2026
Numer referencyjny
CEN2607213383444
"""


@pytest.fixture
def pdf(tmp_path):
    d = tmp_path / "input" / "case1"
    d.mkdir(parents=True)
    p = d / "dowod.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), PRZELEW, fontsize=10)
    doc.save(p)
    return p


def test_run_writes_json_with_same_name(pdf, tmp_path):
    run(tmp_path / "input", tmp_path / "output", tmp_path / "trace", use_llm=False, workers=1)
    out = json.loads((tmp_path / "output" / "case1" / "dowod.json").read_text(encoding="utf-8"))
    assert out == {"przelew_bankowy": {
        "data_operacji": "2026-07-21", "kwota": 100.0, "na_rachunek": "28136902188320879984436720",
        "numer_transakcji": "CEN2607213383444", "tytul": "oplata skarbowa od pelnomocnictwa ZP.271.93.2026",
        "z_rachunku": "07104462551544820625216547"}}
    trace = json.loads((tmp_path / "trace" / "case1" / "dowod.trace.json").read_text(encoding="utf-8"))
    assert trace["klasa"] == "przelew" and trace["pola"]["przelew_bankowy.kwota"]["zrodlo"] == "reguły"


def test_llm_hallucination_is_rejected(pdf, monkeypatch):
    def fake(self, cls, text):
        return {"przelew_bankowy": {"kwota": "100,00", "z_rachunku": "11112222333344445555666677",
                                    "tytul": "oplata skarbowa od pelnomocnictwa ZP.271.93.2026"}}, {}
    monkeypatch.setattr(LLMClient, "extract", fake)
    eng = Engine(use_llm=True)
    eng.llm.enabled = True
    r = eng.process(pdf)
    assert r.data["przelew_bankowy"]["kwota"] == 100.0
    assert r.data["przelew_bankowy"]["z_rachunku"] == "07104462551544820625216547"  # z reguł
    assert "odrzucona" in r.trace["pola"]["przelew_bankowy.z_rachunku"]["uwagi"][0]
