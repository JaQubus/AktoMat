"""Ekstrakcja przez LLM (dowolne API zgodne z OpenAI: Scaleway, OVHcloud, vLLM, Ollama, ...).

Prompt jest budowany w całości z konfiguracji klasy (opisy pól, słowniki, szablon JSON),
więc nowa klasa dokumentu nie wymaga zmian w tym pliku.
"""
from __future__ import annotations

import json
import logging
import re
import time

from .config import DocClass

log = logging.getLogger(__name__)

DEFAULT_SYSTEM = (
    "Jesteś precyzyjnym systemem ekstrakcji danych z polskich dokumentów dotyczących zamówień "
    "publicznych i postępowań przed Krajową Izbą Odwoławczą. Zwracasz wyłącznie poprawny JSON. "
    "Nigdy nie zgadujesz: jeśli informacji nie ma w dokumencie, wpisujesz null. Wartości przepisujesz "
    "dokładnie tak, jak w dokumencie (bez poprawiania pisowni), chyba że instrukcja pola mówi inaczej."
)


class LLMError(RuntimeError):
    pass


def build_prompt(cls: DocClass, doc_text: str) -> str:
    lines = [f"Typ dokumentu: {cls.name} — {cls.description}", ""]
    if cls.llm_instructions:
        lines += ["Instrukcje:", cls.llm_instructions.strip(), ""]
    lines.append("Opis pól (ścieżka: typ — znaczenie):")
    for f in cls.fields:
        if f.derive:
            continue
        lines.append(f"- {f.path}: {f.type} — {f.description.strip()}")
    for name, enum in cls.enums.items():
        lines.append(f"\nSłownik {name}:")
        lines += [f"  {k}: {v}" for k, v in enum.items()]
    lines += [
        "",
        "Formaty: daty jako RRRR-MM-DD; kwoty jako liczba (kropka dziesiętna); NIP, KRS, REGON, PESEL i "
        "numery rachunków jako ciągi samych cyfr (bez spacji, bez 'PL'); brak informacji = null.",
        "Tekst może pochodzić z OCR (literówki, brak polskich znaków, rozjechane kolumny): przywróć polskie "
        "znaki w nazwach i nazwiskach tylko wtedy, gdy są oczywiste; cyfr nie poprawiaj.",
        "Listy obiektów: jeden element na każdy podmiot/osobę; pusta informacja = lista z jednym elementem "
        "wypełnionym null tylko jeśli szablon tego wymaga.",
        "",
        "Zwróć JSON o dokładnie takiej strukturze (klucze jak w szablonie):",
        json.dumps(cls.output_template, ensure_ascii=False, indent=1),
        "",
        "DOKUMENT:",
        doc_text,
    ]
    return "\n".join(lines)


def _parse_json(s: str) -> dict:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if not m:
            raise
        return json.loads(m.group())


class LLMClient:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.enabled = bool(cfg.get("enabled", True) and cfg.get("api_key") and cfg.get("base_url"))
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(base_url=self.cfg["base_url"], api_key=self.cfg["api_key"],
                                  timeout=float(self.cfg.get("timeout", 120)))
        return self._client

    def extract(self, cls: DocClass, doc_text: str) -> tuple[dict, dict]:
        """Zwraca (json, meta). meta zawiera model, czas i zużycie tokenów do śladu."""
        prompt = build_prompt(cls, doc_text)
        msgs = [{"role": "system", "content": self.cfg.get("system_prompt") or DEFAULT_SYSTEM},
                {"role": "user", "content": prompt}]
        kwargs = dict(model=self.cfg["model"], messages=msgs,
                      temperature=float(self.cfg.get("temperature", 0)),
                      max_tokens=int(self.cfg.get("max_tokens", 4096)))
        if self.cfg.get("json_mode", True):
            kwargs["response_format"] = {"type": "json_object"}
        if self.cfg.get("extra_body"):
            kwargs["extra_body"] = self.cfg["extra_body"]
        last = None
        for attempt in range(int(self.cfg.get("retries", 3))):
            t0 = time.time()
            try:
                r = self.client.chat.completions.create(**kwargs)
                content = r.choices[0].message.content or ""
                data = _parse_json(content)
                usage = getattr(r, "usage", None)
                return data, {"model": self.cfg["model"], "seconds": round(time.time() - t0, 2),
                              "tokens": getattr(usage, "total_tokens", None), "attempt": attempt + 1}
            except Exception as e:  # noqa: BLE001
                last = e
                msg = str(e)
                # zgodność z różnymi dostawcami: przy kolejnych próbach upraszczamy zapytanie
                if "reasoning" in msg or attempt == 0:
                    kwargs.pop("extra_body", None)
                if "response_format" in msg or "json_object" in msg or attempt >= 1:
                    kwargs.pop("response_format", None)
                log.warning("LLM próba %s nieudana: %s", attempt + 1, msg[:200])
                time.sleep(min(2 ** attempt * 2, 20))
        raise LLMError(f"LLM niedostępny: {last}")
