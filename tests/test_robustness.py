"""Odporność na podróbki (dokumenty podobne do klas, które mają dać `{}`) i na tekst ze skanu (OCR bez polskich znaków)."""
import json

import pymupdf
import pytest

from odw2json.classify import classify
from odw2json.config import load_classes
from odw2json.extract import extract
from odw2json.normalize import normalize
from odw2json.pipeline import run
from odw2json.textract import Document

CLASSES = load_classes()
BY_NAME = {c.name: c for c in CLASSES}

ODWOLANIE = """Warszawa, dnia 16 czerwca 2025 r.
Prezes Krajowej Izby Odwoławczej
Odwołujący:
Alfa Budowa sp. z o.o., ul. Prosta 1, 00-001 Warszawa, KRS 0000123456
Zamawiający:
Gmina Testowo, ul. Rynek 1, 00-002 Testowo
ODWOŁANIE
Działając na podstawie art. 513 pkt 1 ustawy Pzp wnoszę odwołanie od czynności Zamawiającego.
Zarzucam Zamawiającemu naruszenie art. 16 Pzp.
"""

FAKES = {
    "odpowiedz": """Warszawa, 20 czerwca 2025 r.
Krajowa Izba Odwoławcza
ODPOWIEDŹ NA ODWOŁANIE
Zamawiający: Gmina Testowo. Odwołujący: Alfa Budowa sp. z o.o.
Zamawiający wnosi o oddalenie odwołania w całości, zarzuty Odwołującego są chybione (art. 513, art. 505 Pzp).""",
    "przystapienie": """Prezes Krajowej Izby Odwoławczej
Zgłaszam przystąpienie do postępowania odwoławczego po stronie Zamawiającego.
Odwołujący: Alfa Budowa sp. z o.o. Zamawiający: Gmina Testowo. Wnoszę o oddalenie odwołania, zarzut chybiony.""",
    "skarga": """Sąd Okręgowy w Warszawie XXIII Wydział Gospodarczy Odwoławczy i Zamówień Publicznych
SKARGA na wyrok Krajowej Izby Odwoławczej
Skarżący (Odwołujący): Alfa Budowa sp. z o.o. Zamawiający: Gmina Testowo. Wnoszę o zmianę wyroku, zarzucam naruszenie art. 513.""",
    "wzor": """WZÓR ODWOŁANIA
[miejscowość], dnia [data]
Prezes Krajowej Izby Odwoławczej
Odwołujący: [nazwa wykonawcy]
Zamawiający: [nazwa zamawiającego]
Wnoszę odwołanie od czynności Zamawiającego, zarzucam naruszenie art. 513 Pzp.""",
}


@pytest.mark.parametrize("name", sorted(FAKES))
def test_fakes_are_not_classified(name):
    assert classify(FAKES[name], f"{name}.pdf", CLASSES).name is None


def test_filename_does_not_decide_class():
    # prawdziwe odwołanie nazwane jak przelew - liczy się treść
    assert classify(ODWOLANIE, "przelew_nr_1.pdf", CLASSES).name == "odwolanie"
    # podróbka nazwana jak odwołanie nadal odrzucona
    assert classify(FAKES["odpowiedz"], "odwolanie.pdf", CLASSES).name is None


def test_name_type_rejects_sentence_fragments():
    assert normalize("art. Ustawy 16, przygotował dokumenty naruszeniem przepisów", "name") is None
    assert normalize('BIOARCUS" Spółka z o.o.', "name") == "BIOARCUS Spółka z o.o."
    assert normalize("PHU „Alfa” s.c.", "name") == "PHU „Alfa” s.c."


# Układ ze skanu (RapidOCR, bez polskich znaków): nazwy nad etykietami, etykieta "Zamawiajacy" powtórzona
# w uzasadnieniu, cudzysłów otwierający odczytany jako przecinek.
SCAN = """KANCELARIA PRAWNA
Warszawa, dnia 16 czerwca 2025 r.
Prezes Krajowej Izby Odwolawczej
Odwolujacy
reprezentowany przez radce prawnego
Kancelaria Prawna
adres e - mail:
Miejskie Przedsiebiorstwo Oczyszczania Spolka z ograniczona
odpowiedzialnoscia
Zamawiajacy
Warszawa
Dotyczy: postepowania prowadzonego w trybie podstawowym pn.:
,Dostawa preparatow do instalacji przetwarzania odpadow" (postepowanie nr RZP.27.29.2025.KD)
ODWOLANIE
Dzialajac na podstawie art. 513 pkt 1 ustawy Pzp - w imieniu wykonawcy
,,BIOARCUS" Spolka z ograniczona odpowiedzialnoscia, wnosze odwolanie.
Wskazanie naruszen, ktorych dopuscil sie Zamawiajacy:
Zamawiajacy
Pzp tj.: art.
Ustawy
16, przygotowat dokumenty
"""


def _doc(text):
    return Document(path=None, pages=[text], ocr_pages=[1], ocr_engine="rapidocr")


def test_scan_layout_rules_only():
    data, trace, _ = extract(_doc(SCAN), BY_NAME["odwolanie"], None)
    assert data["Zamawiajacy"][0]["nazwa"] == "Miejskie Przedsiebiorstwo Oczyszczania Spolka z ograniczona odpowiedzialnoscia"
    assert data["Odwolujacy"][0]["nazwa"] == "BIOARCUS Spolka z ograniczona odpowiedzialnoscia"
    assert data["ZamowieniePubliczne"]["tytul"] == "Dostawa preparatow do instalacji przetwarzania odpadow"
    # kancelaria bez nazwiska pełnomocnika też oznacza działanie przez pełnomocnika
    assert data["Odwolujacy"][0]["pelnomocnik"]["nazwa"] == "Kancelaria Prawna"
    assert data["Odwolujacy"][0]["przez-pelnomocnika"] == 1


def test_llm_restores_polish_letters_lost_by_ocr():
    llm = {"Zamawiajacy": [{"nazwa": "Miejskie Przedsiębiorstwo Oczyszczania Spółka z ograniczoną odpowiedzialnością"}]}
    data, trace, _ = extract(_doc(SCAN), BY_NAME["odwolanie"], llm)
    assert data["Zamawiajacy"][0]["nazwa"] == "Miejskie Przedsiębiorstwo Oczyszczania Spółka z ograniczoną odpowiedzialnością"
    assert trace["Zamawiajacy[0].nazwa"]["zrodlo"] == "reguły (znaki z LLM)"


def test_fake_gets_empty_json(tmp_path):
    d = tmp_path / "input" / "case1"
    d.mkdir(parents=True)
    doc = pymupdf.open()
    ascii_text = FAKES["odpowiedz"].translate(str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ"))
    doc.new_page().insert_text((50, 60), ascii_text, fontsize=10)
    doc.save(d / "odwolanie.pdf")
    run(tmp_path / "input", tmp_path / "output", tmp_path / "trace", use_llm=False, workers=1)
    assert json.loads((tmp_path / "output" / "case1" / "odwolanie.json").read_text(encoding="utf-8")) == {}


def test_vocabulary_restores_city_name():
    text = SCAN.replace("Warszawa, dnia 16 czerwca 2025 r.", "Krakow, dnia 16 czerwca 2025 r.")
    data, trace, _ = extract(_doc(text), BY_NAME["odwolanie"], None)
    assert data["OdwolanieKIO"]["miejscowosc"] == "Kraków"
