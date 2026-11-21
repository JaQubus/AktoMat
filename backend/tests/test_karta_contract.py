"""Kontrakt: fixture z Zał. C musi przejść walidację i zserializować się 1:1 (bez dodanych/utraconych kluczy)."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.karta import KartaOdwolania, Kryterium, Pole, Status, StatusReguly

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "karta_example.json"


def load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_roundtrip_1_to_1():
    raw = load()
    karta = KartaOdwolania.model_validate(raw)
    assert karta.to_json_dict() == raw


def test_top_level_keys_match_annex_c():
    keys = list(KartaOdwolania.model_validate(load()).to_json_dict())
    assert keys == ["metadata", "naglowek", "informacje_ogolne", "odwolujacy", "reprezentacja",
                    "zamawiajacy", "weryfikacja", "stopka", "audit_trail"]


def test_unknown_key_rejected():
    raw = load()
    raw["odwolujacy"]["nip"]["nieznany"] = 1
    with pytest.raises(ValidationError):
        KartaOdwolania.model_validate(raw)


def test_bad_status_rejected():
    raw = load()
    raw["odwolujacy"]["nip"]["status"] = "ok"
    with pytest.raises(ValidationError):
        KartaOdwolania.model_validate(raw)


def test_default_card_is_all_missing_never_guessed():
    k = KartaOdwolania.model_validate({"metadata": {"generated_at": "x", "case_id": "c"}})
    d = k.to_json_dict()
    assert d["odwolujacy"]["nip"] == {"value": None, "status": "missing", "source": "BRAK DANYCH"}
    assert d["reprezentacja"]["pelnomocnictwo_zalaczone"] == {"value": None, "status": "not_applicable"}


def test_extensions_serialized_only_when_present():
    p = Pole[str](value="x", status=Status.verified, source="a.pdf > strona: 1", dowod="cytat")
    assert p.model_dump()["dowod"] == "cytat"
    assert "dowod" not in Pole[str](value="x", status=Status.verified).model_dump()
    k = KartaOdwolania.model_validate(load())
    k.weryfikacja.kryteria = [Kryterium(id="F1", nazwa="Termin", status=StatusReguly.spelnione, uzasadnienie="ok")]
    assert k.to_json_dict()["weryfikacja"]["kryteria"][0]["status"] == "spełnione"
