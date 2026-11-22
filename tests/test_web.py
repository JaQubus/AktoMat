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
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "_engine", Engine(use_llm=False))
    monkeypatch.setattr(web, "_sem", None)
    monkeypatch.setattr(web, "UPLOADS", tmp_path / "pliki")
    monkeypatch.setattr(web, "SESSIONS", tmp_path / "zapis")
    (tmp_path / "pliki").mkdir()
    (tmp_path / "zapis").mkdir()
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


def test_pisma_i_docx(client):
    pydocx = pytest.importorskip("docx")  # python-docx (opcjonalnie) tylko do odczytu w teście

    pisma = client.get("/api/pisma").json()
    tpl = pisma["pisma"][0]
    assert tpl["id"] == "wezwanie_braki" and "{braki}" in tpl["tekst"]
    r = client.post("/api/docx", json={"tekst": "> Warszawa, dnia 1.01.2026\n\n# WEZWANIE\n\n**Firma** & Syn\n1) wpisu.",
                                       "nazwa": "wezwanie/../x"})
    assert r.status_code == 200 and 'filename="wezwaniex.docx"' in r.headers["content-disposition"]
    d = pydocx.Document(io.BytesIO(r.content))
    assert [p.text for p in d.paragraphs] == ["Warszawa, dnia 1.01.2026", "WEZWANIE", "Firma & Syn\n1) wpisu."]
    assert d.paragraphs[2].runs[0].bold and not d.paragraphs[2].runs[1].bold


def test_sesje_zapis_lista_usuniecie(client):
    up = client.post("/api/extract", files=[("files", ("przelew.pdf", _pdf(PRZELEW), "application/pdf"))]).json()
    fid = up[0]["id"]
    assert (web.UPLOADS / fid).is_dir()
    stan = {"items": [{**up[0], "sprawa": "s1", "edits": {}, "ok": {}}], "skip": {}, "log": [{"akcja": "x"}]}
    assert client.put("/api/sesje/abcdef12", json={"nazwa": "Test", "referent": "Anna", "stan": stan}).json()["ok"]
    lista = client.get("/api/sesje").json()
    assert lista[0]["id"] == "abcdef12" and lista[0]["sprawy"] == ["s1"] and lista[0]["referent"] == "Anna"
    assert client.get("/api/sesje/abcdef12").json()["stan"]["log"] == [{"akcja": "x"}]
    assert client.get("/api/sesje/..%2Fx").status_code == 404
    assert client.put("/api/sesje/ZLE", json={"stan": {}}).status_code == 404
    assert client.delete("/api/sesje/abcdef12").json()["ok"]
    assert client.get("/api/sesje").json() == [] and not (web.UPLOADS / fid).exists()


def test_zip_bez_danych_osobowych(client):
    odw = {"Odwolujacy": [{"nazwa": "Belmoria S.A.", "nip": "5260250995",
                           "pelnomocnik": {"imie_nazwisko": "Aleksandra Marciniak", "mail": "a.m@kancelaria.pl"}}]}
    prz = {"przelew_bankowy": {"tytul": "Opłata skarbowa, pełnomocnik Aleksandra Marciniak", "kwota": 17.0}}
    r = client.post("/api/zip", json={"ukryj": True, "pliki": [{"sciezka": "s/odw.json", "json": odw}, {"sciezka": "s/prz.json", "json": prz}],
                                      "inne": [{"sciezka": "dziennik.csv", "tekst": "zmiana;ALEKSANDRA MARCINIAK;tel. 600 100 200;PESEL 44051401359"}]})
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    o = json.loads(zf.read("output/s/odw.json"))
    assert o["Odwolujacy"][0]["pelnomocnik"] == {"imie_nazwisko": "[UKRYTE]", "mail": "[UKRYTE]"}
    assert o["Odwolujacy"][0]["nazwa"] == "Belmoria S.A." and o["Odwolujacy"][0]["nip"] == "5260250995"
    p = json.loads(zf.read("output/s/prz.json"))
    assert p["przelew_bankowy"] == {"tytul": "Opłata skarbowa, pełnomocnik [UKRYTE]", "kwota": 17.0}
    assert zf.read("dziennik.csv").decode("utf-8-sig") == "zmiana;[UKRYTE];tel. [UKRYTE];PESEL [UKRYTE]"


def test_rejestr_spraw_i_powiazania(client):
    from test_checks import ODW, PEL, PRZ

    odw2 = {**ODW, "json": {**ODW["json"], "Odwolujacy": [{"nazwa": "Inny Wykonawca sp. z o.o.", "nip": "1234563218"}],
                            "ZamowieniePubliczne": {"numer_postepowania": "zs 791 2026", "numer_bzp": "2026/BZP1"}}}
    s1 = {"items": [{**d, "sprawa": "A"} for d in (ODW, PEL, PRZ)], "skip": {"A": {"wymagane:wpis": {"powod": "ok"}}}}
    s2 = {"items": [{**odw2, "sprawa": "B"}], "skip": {}}
    client.put("/api/sesje/sesja0001", json={"nazwa": "S1", "referent": "Anna", "stan": s1})
    client.put("/api/sesje/sesja0002", json={"nazwa": "S2", "stan": s2})
    rows = {r["sprawa"]: r for r in client.get("/api/rejestr").json()}
    a, b = rows["A"], rows["B"]
    assert a["nip"] == "5260250995" and a["numer_postepowania"] == "ZS.791.2026" and a["termin"] == "2026-03-30"
    assert a["braki"] == [] and a["pominiete"] == 1          # wpis pominięty przez referenta
    assert b["braki"] == ["Dowód uiszczenia wpisu od odwołania"]   # bez pełnomocnika, bez przelewu
    assert a["powiazane"] == [{"sesja": "sesja0002", "sprawa": "B", "odwolujacy": "Inny Wykonawca sp. z o.o.",
                               "przez": ["numer_postepowania"]}]
    assert b["powiazane"][0]["sprawa"] == "A"


def test_usuniecie_pliku(client):
    from odw2json import web
    d = web.UPLOADS / "abc123"
    d.mkdir(parents=True)
    (d / "x.pdf").write_bytes(b"%PDF")
    assert client.delete("/api/pliki/abc123").json() == {"ok": True}
    assert not d.exists()
    assert client.delete("/api/pliki/..%2F..").status_code == 404


def test_przelacznik_ai_wylacza_llm_bez_restartu(client, monkeypatch):
    """Przełącznik „Asystent AI” w GUI: ai=0 przetwarza pliki silnikiem bez LLM (same reguły)."""
    llm_engine = Engine(use_llm=False)
    llm_engine.llm.enabled = True  # udajemy skonfigurowany model; wywołania LLM nie mogą nastąpić przy ai=0
    llm_engine.llm.extract = lambda *a, **k: pytest.fail("LLM wywołany mimo wyłączonego asystenta")
    monkeypatch.setattr(web, "_engine", llm_engine)
    monkeypatch.setattr(web, "_engine_rules", None)
    assert web.engine(True) is llm_engine
    rules = web.engine(False)
    assert rules is not llm_engine and not rules.llm.enabled and web.engine(False) is rules
    res = client.post("/api/extract", files={"files": ("dowod.pdf", _pdf(PRZELEW), "application/pdf")},
                      data={"ai": "0"}).json()
    assert res[0]["klasa"] == "przelew" and not res[0]["slad"].get("llm_uzyty")


def test_dokumentacja_w_gui_i_osobno(client):
    """Dokumentacja: strona, obrazy i konfiguracja na żywo z YAML (bez kluczy API)."""
    from odw2json import docs
    from odw2json.config import load_classes

    r = client.get("/dokumentacja")
    assert r.status_code == 200 and "Instrukcja dla referenta" in r.text
    assert client.get("/dokumentacja/img/sprawa.jpg").status_code == 200
    assert client.get("/dokumentacja/img/..%2Fconfig.py").status_code == 404
    k = client.get("/dokumentacja/konfiguracja.json").json()
    assert [c["nazwa"] for c in k["klasy"]] == [c.name for c in load_classes()]
    assert {"regex", "sentence_map"} <= {r["nazwa"] for r in k["reguly"]}
    assert k["kontrola"]["wymagane"] and k["llm"]["profile"]
    assert "api_key" not in str(k).lower()

    solo = TestClient(docs.app)
    assert solo.get("/", follow_redirects=False).headers["location"] == "/dokumentacja"
    assert solo.get("/dokumentacja/konfiguracja.json").status_code == 200
