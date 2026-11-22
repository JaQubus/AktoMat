# AktoMat (Odwołania2JSON): uruchomienie

Z katalogu `/opt/solution`:

```bash
sudo bash repo/deploy/run.sh
```

- Przetwarza wszystkie pliki PDF z `/opt/solution/input` (także w podkatalogach spraw) i zapisuje JSON-y o tych samych nazwach do `/opt/solution/output`. Dokument spoza obsługiwanych klas dostaje plik z `{}`.
- Nie wymaga interakcji i kończy się sam. Dla 150 PDF działa w limicie 45 minut (po 40 minutach LLM jest pomijany, reszta liczona samymi regułami).
- OCR skanów lokalnie: Tesseract z językiem polskim (zainstalowany na serwerze).
- Ślad ekstrakcji (skąd wzięła się każda wartość): `/opt/solution/trace/`.

## Usługi zewnętrzne

Model językowy open-weight przez API zgodne z OpenAI, klucz w `/opt/solution/.env` (`LLM_PROFILE` + `<PROFIL>_API_KEY` albo `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`). Bez klucza aplikacja działa na samych regułach.
