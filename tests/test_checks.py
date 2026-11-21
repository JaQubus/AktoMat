"""Kontrola formalna teczki: kompletność, zgodność, terminy, sumy kontrolne."""
import datetime as dt

import pytest

from odw2json.checks import check_value, deadline, load_rules, run_checks

ODW = {"plik": "odwolanie.pdf", "klasa": "odwolanie", "json": {
    "OdwolanieKIO": {"data": None, "czynnosc_dzien": "2026-03-20"},
    "ZamowieniePubliczne": {"numer_postepowania": "ZS.791.2026"},
    "Odwolujacy": [{"nazwa": "Belmoria Rozwiązania S.A.", "nip": "5260250995", "przez-pelnomocnika": 1,
                    "pelnomocnik": {"imie_nazwisko": "Aleksandra Marciniak"}}],
    "Zamawiajacy": [{"nazwa": "Aurelink Automatyka S.A."}],
}}
PEL = {"plik": "pelnomocnictwo.pdf", "klasa": "pelnomocnictwo", "json": {
    "mocodawca": [{"data": {"nazwa": "Belmoria Rozwiazania SA", "nip": "526-025-09-95"}}],
    "pelnomocnicy": [{"imie_nazwisko": "Aleksandra Marciniak"}, {"imie_nazwisko": "Jan Zajkowski"}],
}}
PRZ = {"plik": "przelew.pdf", "klasa": "przelew", "json": {
    "przelew_bankowy": {"tytul": "Opłata skarbowa od pełnomocnictwa ZS.791.2026"}}}


@pytest.fixture(scope="module")
def rules():
    return load_rules()


def _by_id(items):
    return {x["id"]: x for x in items}


def test_teczka_bez_wpisu(rules):
    r = run_checks([ODW, PEL, PRZ], rules)
    req = _by_id(r["wymagane"])
    assert req["odwolanie"]["wynik"] == "ok"
    assert req["pelnomocnictwo"]["wynik"] == "ok"
    assert req["wpis"]["wynik"] == "brak" and "skarbowa" in req["wpis"]["szczegoly"]
    assert req["oplata_skarbowa"]["wynik"] == "ok"
    cross = _by_id(r["zgodnosc"])
    assert all(cross[k]["wynik"] == "ok" for k in ("pelnomocnik", "mocodawca", "nip_mocodawcy",
                                                       "postepowanie_w_przelewie"))
    assert _by_id(r["pola"])["OdwolanieKIO.data"]["wynik"] == "ostrzezenie"
    assert r["podsumowanie"]["braki"] == 1


def test_brak_pelnomocnictwa_i_niezgodny_pelnomocnik(rules):
    odw = {**ODW, "json": {**ODW["json"], "Odwolujacy": [
        {**ODW["json"]["Odwolujacy"][0], "pelnomocnik": {"imie_nazwisko": "Piotr Nowak"}}]}}
    r = run_checks([odw, PEL], rules)
    assert _by_id(r["zgodnosc"])["pelnomocnik"]["wynik"] == "niezgodne"
    r = run_checks([odw], rules)
    assert _by_id(r["wymagane"])["pelnomocnictwo"]["wynik"] == "brak"
    assert _by_id(r["wymagane"])["oplata_skarbowa"]["wynik"] == "nie_dotyczy"


def test_termin_przesuniety_z_weekendu_i_swieta(rules):
    assert deadline(dt.date(2026, 3, 20), 10, rules) == (dt.date(2026, 3, 30), False)
    assert deadline(dt.date(2026, 3, 18), 10, rules) == (dt.date(2026, 3, 30), True)   # sobota -> pon.
    assert deadline(dt.date(2026, 3, 26), 10, rules) == (dt.date(2026, 4, 7), True)    # Wielkanoc 5-6.04
    t = run_checks([ODW], rules, {"odwolanie": 5})["terminy"][0]
    assert (t["od"], t["do"], t["dni"]) == ("2026-03-20", "2026-03-25", 5)


@pytest.mark.parametrize("kind,v,ok", [
    ("nip", "526-025-09-95", True), ("nip", "5260250996", False),
    ("regon", "012100784", True), ("regon", "012100785", False),
    ("pesel", "44051401359", True), ("pesel", "44051401358", False),
    ("nrb", "PL61 1090 1014 0000 0712 1981 2874", True), ("nrb", "61109010140000071219812875", False),
])
def test_sumy_kontrolne(kind, v, ok):
    assert check_value(kind, v) is ok


def test_walidacja_w_wyniku(rules):
    v = run_checks([ODW, PEL], rules)["walidacja"]
    assert v["odwolanie.pdf"]["Odwolujacy[0].nip"] == {"typ": "nip", "ok": True}
    assert v["pelnomocnictwo.pdf"]["mocodawca[0].data.nip"]["ok"] is True
