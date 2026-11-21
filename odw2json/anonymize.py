"""Ukrywanie danych osobowych w eksporcie sprawy. Reguły: config/eksport.yaml (sekcja dane_osobowe)."""
from __future__ import annotations

import re
from functools import lru_cache

import yaml

from .config import CONFIG_DIR


def load_export_config(path=None) -> dict:
    p = path or (CONFIG_DIR / "eksport.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


@lru_cache(maxsize=32)
def _compile(patterns: tuple) -> list:
    return [re.compile(p) for p in patterns]


class Anonymizer:
    """Zbiera wartości pól osobowych z całej sprawy i ukrywa je w JSON-ach oraz w tekstach."""

    def __init__(self, cfg: dict | None = None):
        cfg = (cfg if cfg is not None else load_export_config()).get("dane_osobowe", {}) or {}
        self.mask = str(cfg.get("zastapienie", "[UKRYTE]"))
        self.fields = set(cfg.get("pola", []) or [])
        self.patterns = _compile(tuple(cfg.get("wzorce", []) or []))
        self.known: set[str] = set()

    def collect(self, obj, key: str | None = None):
        if isinstance(obj, dict):
            for k, v in obj.items():
                self.collect(v, k)
        elif isinstance(obj, list):
            for v in obj:
                self.collect(v, key)
        elif isinstance(obj, str) and key in self.fields and len(obj.strip()) >= 3:
            self.known.add(obj.strip())
        return self

    def text(self, s: str) -> str:
        for v in sorted(self.known, key=len, reverse=True):
            s = re.sub(re.escape(v), self.mask, s, flags=re.I)
        for rx in self.patterns:
            if "v" in rx.groupindex:
                s = rx.sub(lambda m: m.group(0).replace(m.group("v"), self.mask), s)
            else:
                s = rx.sub(self.mask, s)
        return s

    def json(self, obj, key: str | None = None):
        if isinstance(obj, dict):
            return {k: self.json(v, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.json(v, key) for v in obj]
        if key in self.fields and obj not in (None, ""):
            return self.mask
        if isinstance(obj, str):
            return self.text(obj)
        return obj
