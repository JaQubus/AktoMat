# Odwołania2JSON

**Od dokumentów do danych.** Aplikacja zamienia dokumenty sprawy odwoławczej przed KIO (odwołanie, pełnomocnictwo, potwierdzenie przelewu) w pliki JSON zgodne ze schematami UZP z [hacknation-2026](https://github.com/Urzad-Zamowien-Publicznych/hacknation-2026).

- rozpoznaje rodzaj dokumentu po treści (nie po nazwie pliku), dokumenty spoza klas pomija,
- czyta PDF-y z warstwą tekstową i skany (OCR Tesseract, język polski),
- łączy reguły deterministyczne z otwartym modelem językowym (GPT-OSS-120B przez API w UE) i odrzuca wartości, których nie ma w dokumencie,
- dla każdego pola zapisuje ślad: skąd pochodzi wartość (LLM, reguła, wyliczenie), strona i cytat,
- nowe typy dokumentów i pola dodaje się **wyłącznie plikiem YAML**, bez zmian w kodzie.

## Szybki start

Wymagania: **Python 3.13+**. Do skanów zalecany [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) z językiem polskim (przy instalacji zaznacz *Polish*). Bez niego aplikacja sama użyje zapasowego OCR (RapidOCR, instalowany z `requirements.txt`, bez polskich znaków, nieco słabszy).

```bat
:: Windows
copy .env.example .env      &:: wpisz LLM_API_KEY
start.bat                   &:: input\ -> output\
start.bat web               &:: GUI: http://127.0.0.1:8000
```

```bash
# Linux / macOS
cp .env.example .env && ./start.sh          # input/ -> output/
./start.sh web
```

`start.bat` / `start.sh` same tworzą środowisko `.venv` i instalują `requirements.txt`. Ręcznie:

```bash
pip install -r requirements.txt
python -m odw2json run -i input -o output        # przetwarzanie
python -m odw2json run --no-llm                  # tylko reguły (bez sieci)
python -m odw2json web                           # GUI
python -m odw2json eval --gt ../hacknation-2026/dane   # F1 na zbiorze treningowym
python -m odw2json classes                       # lista skonfigurowanych klas
```

### Wejście i wyjście

```
input/                         output/                         trace/ (ślad ekstrakcji)
├── case1/                     ├── case1/                      ├── case1/
│   ├── odwolanie_nr_1.pdf     │   ├── odwolanie_nr_1.json     │   ├── odwolanie_nr_1.trace.json
│   ├── pelnomocnictwo.pdf     │   ├── pelnomocnictwo.json     │   └── ...
│   ├── przelew_nr_1.pdf       │   └── przelew_nr_1.json
│   └── ogloszenie_TED.pdf     │   └── ogloszenie_TED.json     (dokument spoza klas: pusty JSON `{}`, powód w trace/)
```

Każdy JSON nazywa się tak samo jak odpowiadający mu PDF. Struktura jest 1:1 ze schematami UZP (`oczekiwane-json/`).

### Model językowy (LLM)

Konfiguracja w `.env` (szablon: `.env.example`), domyślnie:

| zmienna | domyślnie | znaczenie |
|---|---|---|
| `LLM_API_KEY` | — | klucz API (wymagany do użycia LLM) |
| `LLM_BASE_URL` | `https://api.scaleway.ai/v1` | dowolne API zgodne z OpenAI |
| `LLM_MODEL` | `gpt-oss-120b` | model open-weight (Apache 2.0) |
| `LLM_ENABLED` | `1` | `0` = tylko reguły |
| `TESSERACT_CMD` | z PATH | ścieżka do `tesseract.exe` |

Domyślny dostawca to **Scaleway Generative APIs (Paryż, UE)**, zgodnie z wymogiem FAQ: usługodawca i serwer w UE, model z możliwością instalacji lokalnej. Ten sam kod działa z lokalnym serwerem (vLLM, Ollama) po zmianie `LLM_BASE_URL` i `LLM_MODEL`. Gdy LLM jest niedostępny, aplikacja nie przerywa pracy: zwraca wynik z reguł i zapisuje błąd w śladzie.

## Wykorzystany model językowy

- **Model:** `gpt-oss-120b` (OpenAI, open-weight, licencja Apache 2.0, ~117 mld parametrów w architekturze MoE, ~5 mld aktywnych na token). Można go uruchomić lokalnie (vLLM, Ollama, llama.cpp).
- **Dostawca API:** Scaleway Generative APIs, Paryż (firma i serwery w UE). API zgodne z OpenAI.
- **Zmiana modelu:** `LLM_MODEL` w `.env`, np. mniejszy `gpt-oss-20b` albo `mistral-small-3.2-24b-instruct-2506`. Kod się nie zmienia.
- **Rola modelu:** wypełnia pola wg opisów z YAML; każda jego wartość jest sprawdzana w tekście dokumentu i walidowana formatem. Reguły deterministyczne działają jako weryfikacja i zapas, więc aplikacja zwraca wynik także bez LLM (`LLM_ENABLED=0`).
- **Parametry:** temperatura 0, tryb JSON, do 24 000 znaków tekstu dokumentu na zapytanie (kluczowe dane są na pierwszych stronach).

## Jak to działa

```
PDF ──► tekst stron (PyMuPDF; strona bez tekstu ► OCR: Tesseract pol, zapasowo RapidOCR)
    ──► klasyfikacja (ważone wzorce z YAML, próg; brak klasy ► pusty JSON)
    ──► reguły deterministyczne (regex, sekcje, bloki podmiotów)  ┐
    ──► LLM: prompt zbudowany z opisów pól w YAML ► JSON          ├► wybór wartości pole po polu
    ──► normalizacja (daty ISO, kwoty, NIP/KRS/rachunki = cyfry)  ┘   + weryfikacja w tekście
    ──► pola wyliczane (np. opis czynności ze słownika) ► JSON + ślad
```

**Wybór wartości.** Dla każdego pola brana jest wartość z LLM, o ile ma poprawny format i **występuje w tekście dokumentu** (dla nazwisk z tolerancją na odmianę). W przeciwnym razie wartość z reguł, a jeśli i jej nie ma: `null`. Uzasadnienie: w ocenie UZP wpisanie wartości tam, gdzie wzorzec ma `null`, to FP, a `null` przy pustym wzorcu to TN. Zgadywanie się nie opłaca. Rozbieżności LLM vs reguły trafiają do śladu jako uwagi.

**Transparentność.** `trace/<sprawa>/<plik>.trace.json` zawiera punktację klasyfikacji, strony przepuszczone przez OCR, czas i model LLM oraz dla każdego pola: wartość, źródło, regułę, stronę i cytat. GUI pokazuje to obok podglądu PDF; kliknięcie pola przewija PDF do strony źródłowej.

## Dodanie nowej klasy dokumentu (bez kodu)

Wystarczy nowy plik `config/classes/<nazwa>.yaml`:

```yaml
name: wezwanie                       # nazwa klasy = nazwa wzorcowego JSON-a
description: Wezwanie do uzupełnienia braków formalnych odwołania
classify:
  min_score: 5
  keywords:                          # bez wielkości liter i polskich znaków
    - {pattern: 'wezwanie', weight: 3}
    - {pattern: 'braki formalne|uzupelnienia', weight: 3}
output_template:                     # dokładna struktura wynikowego JSON-a
  wezwanie:
    data: null
    sygnatura: null
    termin_dni: null
llm_instructions: |
  - sygnatura ma postać "KIO 1234/26".
fields:
  - path: wezwanie.data
    type: date
    description: Data wezwania.
  - path: wezwanie.sygnatura
    type: string
    description: Sygnatura akt KIO.
    rules:
      - pattern: '(?P<v>KIO\s*\d+/\d{2})'
  - path: wezwanie.termin_dni
    type: int
    description: Termin na uzupełnienie w dniach.
```

Pole bez `rules` jest wypełniane przez LLM (i weryfikowane), pole z `rules` ma dodatkowo deterministyczny zapas. Dostępne typy pól: `string, text, name, person, int, enum, flag, date, amount, nip, krs, regon, pesel, account, email, bzp, ted, refno`. Rodzaje reguł: `regex, sentence_map, titled_persons, signatories, entity_name, first_line, const` (opis w `odw2json/rules.py`). Opcje pola: `prefer: llm|rules`, `require_grounding`, `derive` (pola wyliczane), `cast`. Sekcje dokumentu (`sections`) i podział na wiele podmiotów (`lists`) też są w YAML. Zobacz `config/classes/odwolanie.yaml` jako pełny przykład.

## Jakość

Ewaluacja liczy F1 dokładnie według definicji UZP: TP = wartość zgodna (długie napisy: podobieństwo ≥ 80%), TN = `null` w obu, FP = wartość błędna lub zbędna, FN = brak wartości obecnej we wzorcu. Raport (`eval_report/raport.md`) pokazuje F1 per klasa i per pole, a `bledy.csv` każdą pomyłkę.

| zbiór | tryb | F1 |
|---|---|---|
| 60 spraw treningowych UZP (PDF z tekstem) | same reguły, bez LLM | 1.000 |
| 12 z tych spraw zamienionych na skany 150 dpi, OCR Tesseract | same reguły, bez LLM | 0.963 |
| j.w., zapasowy OCR RapidOCR (bez Tesseract) | same reguły, bez LLM | 0.915 |
| klasyfikacja 60 spraw + 16 dokumentów negatywnych UZP | | 196/196 |
| j.w. | reguły + LLM (gpt-oss-120b) | do zmierzenia: `python -m odw2json eval --gt ...` z kluczem w `.env` |

Wynik na danych treningowych jest optymistyczny, bo reguły były strojone na tych samych szablonach. Prawdziwe odwołania są pisane swobodnie i tam główną robotę wykonuje LLM, a reguły działają jako weryfikacja i zapas.

## Struktura projektu

```
odw2json/            kod (pipeline, OCR, klasyfikacja, reguły, LLM, ewaluacja, GUI)
config/settings.yaml ustawienia ogólne (model, OCR, równoległość)
config/classes/      definicje klas dokumentów (YAML)
input/ output/       foldery wejścia i wyjścia wymagane przez UZP
tests/               testy (pytest)
```

Testy: `python -m pytest -q`.
