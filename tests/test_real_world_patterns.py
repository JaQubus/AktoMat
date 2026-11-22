"""Wzorce z prawdziwych, publicznych odwołań do KIO (tekst syntetyczny, bez danych osobowych)."""
from pathlib import Path

from odw2json.classify import classify
from odw2json.config import load_classes
from odw2json.extract import extract
from odw2json.textract import Document

APPEAL = """Warszawa, data 12.03.2024 r.

Krajowa Izba Odwoławcza
ul. Postępu 17a, 02-676 Warszawa

Wykonawca:
Przykładowa Firma Budowlana Sp. z o. o.
Ul. Graniczna 5
00-001 Gdańsk
NIP: 123-45-67-819

Zamawiający:
Szpital Wojewódzki im. Testowego
ul. Szpitalna 1, 00-002 Kraków

Dotyczy: postępowania na roboty budowlane o nazwie: „Przebudowa oddziału wewnętrznego” ogłoszonego pod numerem: 444695-2024, numer wydania: Dz.U. S: 143/2024

ODWOŁANIE

Działając w imieniu Odwołującego wnoszę odwołanie od niezgodnych z ustawą czynności i zaniechań Zamawiającego polegających na: 1) odrzuceniu oferty Odwołującego; 2) unieważnieniu postępowania.
Zawiadomienie o wynikach postępowania zostało przekazane Odwołującemu w dniu 07.03.2024 r.
"""

KIO_ORDER = """POSTANOWIENIE PREZESA KRAJOWEJ IZBY ODWOŁAWCZEJ
Prezes Krajowej Izby Odwoławczej po rozpoznaniu odwołania wniesionego przez wykonawcę w postępowaniu
prowadzonym przez zamawiającego, zwraca odwołanie i nakazuje zwrot kwoty wpisu z rachunku Urzędu Zamówień
Publicznych na rachunek odwołującego. Zamawiający. Odwołujący. Przelew kwota tytułem zwrotu wpisu.
"""


def _classes():
    return {c.name: c for c in load_classes()}


def test_real_world_appeal_phrasing():
    cls = _classes()
    assert classify(APPEAL, "x.pdf", list(cls.values())).name == "odwolanie"
    r = extract(Document(Path("x.pdf"), [APPEAL]), cls["odwolanie"], None)
    r = r[0] if isinstance(r, tuple) else r
    k = r["OdwolanieKIO"]
    assert (k["data"], k["miejscowosc"]) == ("2024-03-12", "Warszawa")
    assert (k["czynnosc_powod_id"], k["czynnosc_dzien"]) == (1, "2024-03-07")
    o = r["Odwolujacy"][0]
    assert o["nazwa"] == "Przykładowa Firma Budowlana Sp. z o. o."
    assert o["nip"] == "1234567819"
    z = r["ZamowieniePubliczne"]
    assert z["numer_ted"] == "444695-2024"
    assert z["tytul"] == "Przebudowa oddziału wewnętrznego"


def test_kio_order_is_not_a_document_class():
    assert classify(KIO_ORDER, "x.pdf", list(_classes().values())).name is None
