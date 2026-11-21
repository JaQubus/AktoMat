"""GUI/API: wczytanie ZIP-a sprawy, klasyfikacja, odrzucenie podróbki, wyszukanie cytatu, eksport ZIP."""
import io
import json
import zipfile

import pymupdf
import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from odw2json import web  # noqa: E402
from odw2json.pipeline import Engine  # noqa: E402

from test_pipeline import PRZELEW  # noqa: E402


def _pdf(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 60), text, fontsize=10)
    return doc.tobytes()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web, "_engine", Engine(use_llm=False))
    monkeypatch.setattr(web, "_sem", None)
    return TestClient(web.app)


def test_zip_sprawy_klasyfikacja_i_eksport(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("input/sprawa_7/dowod.pdf", _pdf(PRZELEW))
        zf.writestr("input/sprawa_7/inny.pdf", _pdf("Lista obecnosci na szkoleniu BHP"))
        zf.writestr("../zly.txt", "x")
    res = client.post("/api/extract", files={"files": ("akta.zip", buf.getvalue(), "application/zip")}).json()
    by = {r["plik"]: r for r in res}
    assert set(by) == {"dowod.pdf", "inny.pdf"}
    assert all(r["sprawa"] == "sprawa_7" for r in res)
    assert by["dowod.pdf"]["klasa"] == "przelew" and by["dowod.pdf"]["json"]["przelew_bankowy"]
    assert by["inny.pdf"]["klasa"] is None and by["inny.pdf"]["json"] is None

    hit = client.get(f"/api/szukaj/{by['dowod.pdf']['id']}", params={"q": ["CEN2607213383444"], "strona": 1}).json()
    assert hit["strona"] == 1 and hit["prostokaty"]
    assert client.get(f"/api/strona/{by['dowod.pdf']['id']}/1").headers["content-type"] == "image/png"

    z = client.post("/api/zip", json={"pliki": [
        {"sciezka": "sprawa_7/dowod.json", "json": by["dowod.pdf"]["json"]},
        {"sciezka": "sprawa_7/inny.json", "json": "{}"},
        {"sciezka": "../../etc/x.json", "json": {}}]})
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert names == ["output/sprawa_7/dowod.json", "output/sprawa_7/inny.json", "output/etc/x.json"]
    assert zipfile.ZipFile(io.BytesIO(z.content)).read("output/sprawa_7/inny.json") == b"{}"


def test_folder_sprawy_i_klasy(client):
    res = client.post("/api/extract", files={"files": ("dowod.pdf", _pdf(PRZELEW), "application/pdf")},
                      data={"sciezki": "akta/sprawa_9/dowod.pdf"}).json()
    assert res[0]["sprawa"] == "sprawa_9" and res[0]["klasa"] == "przelew"
    klasy = {k["nazwa"]: k for k in client.get("/api/klasy").json()}
    assert {"odwolanie", "pelnomocnictwo", "przelew"} <= set(klasy)
    assert json.dumps(klasy["przelew"]["szablon"]) and klasy["przelew"]["pola"]
    assert client.get("/api/pdf/..%2F..").status_code == 404


def test_zaznaczanie_wartosci_rozmyte():
    from odw2json.locate import match

    words = [(0.1, 0.1, 0.15, 0.12, "NIP:"), (0.16, 0.1, 0.3, 0.12, "999-928-40-65,"),
             (0.31, 0.1, 0.4, 0.12, "REGON:"), (0.1, 0.2, 0.2, 0.22, "Belmoria"), (0.21, 0.2, 0.4, 0.22, "Rozwiqzania")]
    score, rects = match(words, "9999284065")
    assert score >= 99 and rects == [[0.16, 0.1, 0.3, 0.12]]
    score, rects = match(words, "Belmoria Rozwiązania")  # błąd OCR "q" zamiast "ą"
    assert score >= 85 and rects == [[0.1, 0.2, 0.4, 0.22]]
    assert match(words, "Zupełnie inna firma")[1] == []


def test_szukaj_na_drugiej_stronie(client, tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 60), "Strona pierwsza", fontsize=10)
    doc.new_page().insert_text((50, 700), "Numer ogloszenia: 2026/BZP 00123456", fontsize=10)
    res = client.post("/api/extract", files={"files": ("x.pdf", doc.tobytes(), "application/pdf")}).json()[0]
    hit = client.get(f"/api/szukaj/{res['id']}", params={"q": ["2026/BZP00123456"], "strona": 1}).json()
    assert hit["strona"] == 2 and hit["prostokaty"] and hit["prostokaty"][0][1] > 0.7


def test_api_kontrola_i_zip_z_dziennikiem(client):
    from test_checks import ODW, PRZ

    r = client.post("/api/kontrola", json={"dokumenty": [ODW, PRZ], "dni": {"odwolanie": 5}})
    assert r.status_code == 200
    body = r.json()
    assert {x["id"]: x["wynik"] for x in body["wymagane"]}["wpis"] == "brak"
    assert body["terminy"][0]["do"] == "2026-03-25"
    assert "wymagane" in client.get("/api/kontrola/reguly").json()
    z = client.post("/api/zip", json={"pliki": [{"sciezka": "s1/a.json", "json": {}}],
                                      "inne": [{"sciezka": "dziennik_zmian.csv", "tekst": "a;b"},
                                               {"sciezka": "../x.exe", "tekst": "no"}]})
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert names == ["output/s1/a.json", "dziennik_zmian.csv"]
