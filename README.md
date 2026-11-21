# ODWOŁANIA2JSON (HackNation 2026, wyzwanie UZP)

Paczka dokumentów odwołania do KIO (ZIP) → ustrukturyzowana **Karta Odwołania (JSON)** z oceną formalną F1–F13 i źródłem każdej informacji.

> ⚠️ **Dane w `data/synthetic/` są FIKCYJNE** (wymyślone firmy, osoby i numery). Nie są to prawdziwe sprawy.
> Prawdziwe dane UZP wrzuć do `data/uzp/` — pipeline nie zakłada nazw plików, wystarczy je przepuścić.

## Uruchomienie
```
cp .env.example .env     # ustaw ANTHROPIC_API_KEY (lub LLM_MODEL na model lokalny)
docker compose up --build
```
UI: http://localhost:5173 · API: http://localhost:8000/docs

## Komendy deweloperskie
- testy: `make test` (`cd backend && uv run --python 3.11 --extra dev python -m pytest -q`)
- dane syntetyczne: `make synth` · ewaluacja: `make eval`

Kontrakt danych: `backend/app/models/karta.py` (klucze 1:1 z Zał. C OPZ), przykład: `fixtures/karta_example.json`.
