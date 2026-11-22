# AktoMat

**Od dokumentów do danych.** Aplikacja zamienia dokumenty sprawy odwoławczej przed KIO (odwołanie, pełnomocnictwo, potwierdzenie przelewu) w pliki JSON zgodne ze schematami UZP z [hacknation-2026](https://github.com/Urzad-Zamowien-Publicznych/hacknation-2026).

- rozpoznaje rodzaj dokumentu po treści (nazwa pliku nie ma wpływu), a dokumenty spoza klas i podróbki (odpowiedź na odwołanie, przystąpienie, skarga, wyrok KIO, pusty wzór, ogłoszenie) dostają pusty JSON `{}`,
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
| `TESSDATA_PREFIX` | instalacja Tesseracta albo `./tessdata` | folder z `pol.traineddata`; `start.bat` sam go pobiera do `./tessdata`, gdy Tesseract nie ma polskiego |

Domyślny dostawca to **Scaleway Generative APIs (Paryż, UE)**, zgodnie z wymogiem FAQ: usługodawca i serwer w UE, model z możliwością instalacji lokalnej. Ten sam kod działa z lokalnym serwerem (vLLM, Ollama) po zmianie `LLM_BASE_URL` i `LLM_MODEL`. Gdy LLM jest niedostępny, aplikacja nie przerywa pracy: zwraca wynik z reguł i zapisuje błąd w śladzie.

**Profile dostawców.** Zamiast przepisywać `LLM_*`, w `.env` można dopisać `LLM_PROFILE=<nazwa>` i klucz `<NAZWA>_API_KEY`. Profile są w `config/settings.yaml` (`llm.profiles`): `ovh` (OVHcloud AI Endpoints, UE, `gpt-oss-20b`), `sherlock` (CloudFerro, UE, Bielik 11B / PLLuM 12B / Llama 3.1 8B), `groq` (tylko testy). Model profilu można nadpisać przez `<NAZWA>_MODEL`.

**Klucz API dla jury.** `.env` nie trafia do repozytorium. Do zgłoszenia klucz przekazujemy osobno; wystarczy wpisać go do `.env` (np. `LLM_PROFILE=ovh` i `OVH_API_KEY=...`) i uruchomić `start.bat`. Bez klucza aplikacja działa na samych regułach.

**Limit czasu UZP (150 PDF w 45 min).** `time_budget_s` w `config/settings.yaml` (domyślnie 2400 s = 40 min): gdy partia przekroczy budżet, LLM jest pomijany i pozostałe dokumenty są liczone samymi regułami, więc wynik zawsze powstaje w limicie. Pojedyncze zapytanie do LLM ma limit 90 s. Bez LLM 30 skanów (72 strony, OCR Tesseract) liczy się w ok. 100 s na 4 rdzeniach.

Do darmowych testów i ewaluacji można użyć **Groq** (ten sam model open-weight gpt-oss-120b): w `.env` dopisz `LLM_PROFILE=groq` i `GROQ_API_KEY=gsk_...`, a linie Scaleway (`LLM_*`) zostaw. Usunięcie `LLM_PROFILE` wraca do Scaleway. Groq jest firmą z USA, więc w zgłoszeniu do UZP zostaje dostawca z UE.

## Wykorzystany model językowy

- **Model:** `gpt-oss-120b` (OpenAI, open-weight, licencja Apache 2.0, ~117 mld parametrów w architekturze MoE, ~5 mld aktywnych na token). Można go uruchomić lokalnie (vLLM, Ollama, llama.cpp).
- **Dostawca API:** Scaleway Generative APIs, Paryż (firma i serwery w UE). API zgodne z OpenAI.
- **Zmiana modelu:** `LLM_MODEL` w `.env`, np. mniejszy `gpt-oss-20b` albo `mistral-small-3.2-24b-instruct-2506`. Kod się nie zmienia.
- **Rola modelu:** wypełnia pola wg opisów z YAML; każda jego wartość jest sprawdzana w tekście dokumentu i walidowana formatem. Reguły deterministyczne działają jako weryfikacja i zapas, więc aplikacja zwraca wynik także bez LLM (`LLM_ENABLED=0`).
- **Parametry:** temperatura 0, tryb JSON, do 24 000 znaków tekstu dokumentu na zapytanie (kluczowe dane są na pierwszych stronach).

## Jak to działa

```
PDF ──► tekst stron (PyMuPDF; strona bez tekstu ► OCR: Tesseract pol, zapasowo RapidOCR)
    ──► klasyfikacja (ważone wzorce z YAML, wzorce negatywne dla podróbek, próg; brak klasy ► pusty JSON `{}`)
    ──► reguły deterministyczne (regex, sekcje, bloki podmiotów)  ┐
    ──► LLM: prompt zbudowany z opisów pól w YAML ► JSON          ├► wybór wartości pole po polu
    ──► normalizacja (daty ISO, kwoty, NIP/KRS/rachunki = cyfry)  ┘   + weryfikacja w tekście
    ──► pola wyliczane (np. opis czynności ze słownika) ► JSON + ślad
```

**Wybór wartości.** Dla każdego pola brana jest wartość z LLM, o ile ma poprawny format i **występuje w tekście dokumentu** (dla nazwisk z tolerancją na odmianę). W przeciwnym razie wartość z reguł, a jeśli i jej nie ma: `null`. Uzasadnienie: w ocenie UZP wpisanie wartości tam, gdzie wzorzec ma `null`, to FP, a `null` przy pustym wzorcu to TN. Zgadywanie się nie opłaca. Rozbieżności LLM vs reguły trafiają do śladu jako uwagi.

**Skany.** Tekst z OCR bywa bez polskich znaków (RapidOCR) i z innym układem (nazwa podmiotu nad etykietą „Zamawiający”, cudzysłów odczytany jako przecinek). Wzorce w YAML dopasowują litery z ogonkiem i bez, blok stron jest szukany tylko w nagłówku pisma (opcja sekcji `before`), a pole typu `name` odrzuca fragmenty zdań (np. „art. 16 ustawy…”). Gdy reguła i LLM dają tę samą wartość, a LLM odtworzył polskie znaki, bierzemy wersję z LLM.

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

Pole bez `rules` jest wypełniane przez LLM (i weryfikowane), pole z `rules` ma dodatkowo deterministyczny zapas. Dostępne typy pól: `string, text, name, person, int, enum, flag, date, amount, nip, krs, regon, pesel, account, email, bzp, ted, refno`. Rodzaje reguł: `regex, sentence_map, titled_persons, signatories, entity_name, first_line, const` (opis w `odw2json/rules.py`). Opcje pola: `prefer: llm|rules`, `require_grounding`, `derive` (pola wyliczane, `from` może być listą pól), `cast`, `vocabulary` (słownik poprawnych zapisów, np. `config/slowniki/miejscowosci.txt`: „Krakow” ze skanu → „Kraków”). Sekcje dokumentu (`sections`, z opcjami `end`, `max_chars`, `before`) i podział na wiele podmiotów (`lists`) też są w YAML. Podróbki odcina się wzorcami `classify.negative`. Klucz `ocr_layout: columns` każe czytać skan kolumnami (bloki podpisów obok siebie), a `cut` w regule `sentence_map` kończy fragment, np. na punkcie „2.” listy zaskarżonych czynności. Zobacz `config/classes/odwolanie.yaml` jako pełny przykład.

## Jakość

Ewaluacja liczy F1 dokładnie według definicji UZP: TP = wartość zgodna (długie napisy: podobieństwo ≥ 80%), TN = `null` w obu, FP = wartość błędna lub zbędna, FN = brak wartości obecnej we wzorcu. Raport (`eval_report/raport.md`) pokazuje F1 per klasa i per pole, a `bledy.csv` każdą pomyłkę.

| zbiór | tryb | F1 |
|---|---|---|
| 60 spraw treningowych UZP (PDF z tekstem) | same reguły, bez LLM | 1.000 |
| 12 z tych spraw zamienionych na skany 150 dpi, OCR Tesseract | same reguły, bez LLM | 0.963 |
| j.w., zapasowy OCR RapidOCR (bez Tesseract) | same reguły, bez LLM | 0.915 |
| 8 spraw jako skany 150 dpi w skali szarości, RapidOCR | same reguły, bez LLM | 0.933 (przed poprawkami skanów: 0.911) |
| 60 spraw jako skany 150 dpi, Tesseract `pol` | same reguły, bez LLM | 0.984 (przed odczytem kolumn: 0.953) |
| skany UZP `dane/skany` (10 odwołań, 10 pełnomocnictw, 10 przelewów, inne szablony) | same reguły, bez LLM | 0.875, klasyfikacja 30/30 (na starcie: 0.750) |
| klasyfikacja 60 spraw + 16 dokumentów negatywnych UZP | | 196/196 |
| podróbki (odpowiedź na odwołanie, przystąpienie, skarga, wzór) i dokument z mylącą nazwą pliku | testy `tests/test_robustness.py` | wszystkie `{}` / właściwa klasa |
| 60 spraw treningowych | reguły + mistral-small-3.2-24b | 0.9988 |
| j.w. | reguły + LLM (gpt-oss-120b) | 0.9995 |
| skany UZP `dane/skany` (30) | reguły + gpt-oss-120b (117B) | 0.937 |
| j.w. | reguły + **gpt-oss-20b (21B)** | **0.949** |
| j.w. | reguły + Qwen 3.8 27B | 0.942 |
| j.w. | reguły + ALLaM 7B | 0.801 (gorzej niż same reguły) |

Na skanach mniejszy model daje tyle samo co duży, bo LLM tylko uzupełnia pola, których nie złapały reguły, a każda jego wartość jest weryfikowana w tekście. Raport pokazuje też **ścisłą dokładność** (wartość identyczna co do znaku): na 60 sprawach treningowych 180/180 plików JSON jest identycznych ze wzorcem.

Wynik na danych treningowych jest optymistyczny, bo reguły były strojone na tych samych szablonach. Prawdziwe odwołania są pisane swobodnie i tam główną robotę wykonuje LLM, a reguły działają jako weryfikacja i zapas.

## Wdrożenie na serwer oceny UZP (VM.md)

Organizator ocenia rozwiązanie na swojej maszynie (Ubuntu 24.04, 2 vCPU, bez GPU) komendą z `/opt/solution/RUN.md`. Instalacja (jednorazowo, po zalogowaniu przez SSH):

```bash
cd /opt/solution
git clone https://github.com/JaQubus/AktoMat.git repo
bash repo/deploy/vm_setup.sh          # Tesseract z polskim, Python 3.13, venv, RUN.md, test
nano /opt/solution/.env               # opcjonalnie klucz API (LLM_PROFILE=... i <PROFIL>_API_KEY=...)
```

Test dokładnie tak jak u oceniających: wrzuć PDF-y do `/opt/solution/input`, wyczyść `/opt/solution/output` i uruchom `sudo bash repo/deploy/run.sh` (z katalogu `/opt/solution`). Aplikacja czyta też `.env` z bieżącego katalogu albo ze ścieżki `ODW2JSON_ENV`.

## Zgodność z wymaganiami UZP

| wymaganie (README UZP) | jak spełnione |
|---|---|
| PDF → rozpoznanie typu → JSON wg `oczekiwane-json` | klasy w `config/classes/*.yaml`, `output_template` 1:1 ze wzorcami |
| klasyfikacja po treści, nie po nazwie pliku | `filename_weight: 0`, test `test_filename_does_not_decide_class` |
| dokument spoza klas → pusty `.json` | plik z `{}` (`unknown_output`), 16/16 negatywów UZP |
| foldery `input/` i `output/` w katalogu głównym, JSON o tej samej nazwie co PDF, drzewo spraw | `python -m odw2json` / `start.bat` czyta `input/<sprawa>/*.pdf`, pisze `output/<sprawa>/<plik>.json` |
| CLI / wrapper script, GUI dodatkowo | `start.bat`, `start.sh`, `python -m odw2json web` |
| Python 3.13+, `requirements.txt` | tak (CLI ostrzega przy starszym Pythonie) |
| tylko open source, bez GPU, LLM po API z UE, klucz dostarczony | modele open-weight, profile `ovh` / `sherlock` / Scaleway; klucz w `.env` |
| skany | OCR lokalny (Tesseract `pol`, zapasowo RapidOCR), więc OCR nie liczy się jako model z API |
| 150 PDF w 45 min | budżet czasu `time_budget_s`, potem same reguły |
| nowe klasy bez zmian w kodzie | tylko YAML (sekcja niżej) |
| transparentność | ślad `trace/` per pole + GUI z podświetleniem źródła |

## Struktura projektu

```
odw2json/            kod (pipeline, OCR, klasyfikacja, reguły, LLM, ewaluacja, GUI)
config/settings.yaml ustawienia ogólne (model, OCR, równoległość)
config/classes/      definicje klas dokumentów (YAML)
input/ output/       foldery wejścia i wyjścia wymagane przez UZP
tests/               testy (pytest)
```

Testy: `python -m pytest -q`.
