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
