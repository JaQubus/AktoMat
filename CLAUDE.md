# Odwołania2JSON (HackNation 2026, wyzwanie UZP)

PDF (odwołanie / pełnomocnictwo / potwierdzenie przelewu) → JSON zgodny ze schematami z https://github.com/Urzad-Zamowien-Publicznych/hacknation-2026 (`oczekiwane-json/`). Ocena: F1 per pole na ukrytym zbiorze realnych spraw (także skany).

## Zasady
- Struktura JSON 1:1 z `output_template` w `config/classes/*.yaml`; klasa = nazwa wzorcowego pliku UZP.
- Nowe klasy/pola tylko przez YAML (to 50% oceny finałowej). Kod w `odw2json/` ma być ogólny.
- Nie zgadywać: wartość spoza tekstu dokumentu → `null` (FP kosztuje). Weryfikacja w `normalize.grounded`.
- LLM tylko open-weight przez API w UE (domyślnie Scaleway, `gpt-oss-120b`), klucz w `.env`, nigdy w repo.
- Python 3.13+, zależności w `requirements.txt`, uruchamianie: `start.bat` / `python -m odw2json`.

## Komendy
- testy: `python -m pytest -q`
- F1 na danych treningowych: `python -m odw2json eval --gt <hacknation-2026>/dane [--no-llm]` → `eval_report/raport.md`, `bledy.csv`
- GUI: `python -m odw2json web`
