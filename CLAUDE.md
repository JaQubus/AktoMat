# ODWOŁANIA2JSON — HackNation 2026 (wyzwanie UZP)

Aplikacja: paczka dokumentów odwołania do KIO (ZIP) → ustrukturyzowana „Karta Odwołania” (JSON) z oceną formalną F1–F13 i źródłem każdej informacji. ~24 h. **Priorytet: działający end-to-end na PRAWDZIWYCH danych z ./data, nie liczba funkcji.**

## Źródła prawdy
- `docs/OPZ_starsza_pelne_zalaczniki.pdf` — Zał. C (JSON Karty, klucze 1:1!), D (ground_truth.yaml), E (raport accuracy), G (kryteria F1–F12). Tekst: wyciągany PyMuPDF.
- `docs/OPZ_nowsza.pdf` — dodaje e-Doręczenia (ADE/BAE), dopuszcza rozwiązanie równoważne zamiast n8n.
- Reszta docs: UZP_postepowanie_odwolawcze_od_2026-03-13, projekt_nowelizacji_Pzp_wpis, protokol_WKR, przykład orzeczenia KIO 4463/25, prezentacja UZP.

## Kontrakt danych
- Model Pydantic v2 Karty = kontrakt; klucze 1:1 z Zał. C: `metadata, naglowek, informacje_ogolne, odwolujacy, reprezentacja, zamawiajacy, weryfikacja, stopka, audit_trail`.
- Pole: `{value, status: verified|warning|missing|not_applicable, source: "Plik.pdf > strona: N" | "KRS API" | "BRAK DANYCH"}` + (nasze rozszerzenie) krótki cytat dowodu. Brak dowodu → `null` + `missing`. Nigdy nie zgadywać.
- Statusy reguł: spełnione / niespełnione / do_weryfikacji_ręcznej / nie_dotyczy. Niepewne dane → do_weryfikacji_ręcznej, NIGDY niespełnione. `braki_formalne = true` gdy cokolwiek niespełnione.
- Priorytet źródeł przy konflikcie: rejestry > podpis > dokument oryginalny > dokument wtórny.
- Żadnych kwot/terminów na sztywno w kodzie → `config/rules.yaml`. Nie wymyślać przepisów ani kwot spoza promptu i OPZ.
- PESEL i dane osobowe z certyfikatów maskować w UI i logach.

## Stack
Python 3.11, FastAPI, Pydantic v2, pytest, uv. PyMuPDF (PDF z tekstem), OCR tylko dla skanów (docling/Tesseract `pol`). LLM przez LiteLLM w `llm.py` (model/klucz z .env, domyślnie Claude, przełączalny na lokalny jedną zmienną). pyHanko (PAdES); XAdES/CAdES = do weryfikacji ręcznej. Rejestry: KRS, eZamówienia (timeout+retry+backoff+cache na dysku `*_api.json`+tryb offline), CEIDG/REGON mock. Frontend: React+Vite+TS+Tailwind+pdf.js. `docker compose up`.

## Pipeline (backend/pipeline/)
ingest → text → classify (8 kategorii) → extract → validate → signatures → registries → rules (F1–F13) → output (JSON, Karta DOCX, wezwanie DOCX art. 518 ust. 1 Pzp, 3 dni).

## Kamienie milowe (commit po każdym, testy zielone)
M1 szkielet+model+fixtures · M2 ingest/text/classify · M3 extract · M4 validate+registries · M5 rules+testy · M6 output+API · M7 eval+accuracy · M8 frontend · M9 `make demo` offline.

## Komendy (uzupełniać w miarę powstawania)
Środowisko: brak systemowego Pythona; używać `uv` (`uv run ...`). Docker 29, Node 24 dostępne.
- run: `docker compose up --build` (UI :5173, API :8000) · test: `make test` = `cd backend && uv run --python 3.11 --extra dev python -m pytest -q` · synth: `make synth` · eval: `make eval` (M7)

## Decyzje
- (Krok 0) Tekst dokumentów OPZ wyciągnięty do scratchpada przez `uv run --with pymupdf`.

## Stan danych / ryzyka
- `./data/uzp` — dane UZP jeszcze nie dostarczone (dojdą później); pracujemy na syntetycznych.

## Pytania do mentora UZP
- Art. 8 ust. 4 Pzp (przesunięcie terminu z soboty/niedzieli/święta) — źródła UZP sprzeczne; domyślnie flaga `shift_weekend_holiday` w config.
- Czy są wzorcowe Karty DOC/DOCX do wygenerowania ground_truth? Ile spraw, czy są skany?
- F13 / e-Doręczenia: skąd brać adres ADE (BAE) w danych testowych?
- (M1) Układ: `backend/{app,pipeline,tests}`, `fixtures/`, `config/`, `scripts/`, `frontend/`. Model Karty: `backend/app/models/karta.py`; rozszerzenia (`dowod`, `weryfikacja.kryteria`, `metadata.rozszerzenia_kontraktu`) pomijane w JSON gdy puste, więc round-trip fixture = 1:1.
- (M1) Windows Application Control blokuje `.exe` launchery i natywne moduły node (pytest.exe, rollup): używać `python -m pytest`; `vite build` działa tylko w Dockerze. Lokalnie: `node node_modules/typescript/bin/tsc --noEmit`.
- (Plan) Dane UZP dojdą później. Najpierw dane syntetyczne (`data/synthetic/`, FIKCYJNE, z ground_truth.yaml) + 1 publiczne odwołanie (`data/public/`, ustawa z 2020 r., tylko do testów ekstrakcji, nie reguł F1–F12). Ścieżka danych z `.env` (DATA_DIR), zero założeń o nazwach plików. Po pojawieniu się `data/uzp/`: raport Kroku 0 + porównanie struktury z syntetycznymi + poprawka generatora.
