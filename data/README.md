# Dane

| katalog | zawartość | w repo |
|---|---|---|
| `synthetic/` | 5 **FIKCYJNYCH** spraw (ZIP) + `ground_truth/` (Zał. D) + `krs_mock/`; generator: `scripts/make_synthetic_cases.py` | tak |
| `public/` | publiczne odwołanie ABM (2020, stara ustawa Pzp) — tylko do testów ekstrakcji tekstu/pól, nie reguł F1–F12. Pobranie: https://bip.abm.gov.pl/download/2/552/IQVIA220620odwolanieABM.pdf | nie |
| `uzp/` | prawdziwe dane od UZP (gdy dotrą). Pipeline nie zakłada nazw plików; ścieżka bazowa: `DATA_DIR` w `.env` | nie |
