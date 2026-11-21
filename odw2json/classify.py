"""Klasyfikacja dokumentu na podstawie wag wzorców z sekcji `classify` w YAML klasy.

Punktacja jest jawna (lista trafionych wzorców trafia do śladu), więc decyzja jest wyjaśnialna.
Dokument bez klasy powyżej progu = "nieznany" (nie generujemy dla niego JSON-a).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import DocClass
from .normalize import fold


@dataclass
class Classification:
    name: str | None
    score: float
    scores: dict = field(default_factory=dict)
    hits: dict = field(default_factory=dict)


def _score(cls: DocClass, head: str, head_folded: str, filename: str) -> tuple[float, list]:
    cfg = cls.classify
    score, hits = 0.0, []
    for rule in cfg.get("keywords", []):
        pat, w = rule["pattern"], float(rule.get("weight", 1))
        target = head if rule.get("case_sensitive") else head_folded
        flags = 0 if rule.get("case_sensitive") else re.IGNORECASE
        p = pat if rule.get("case_sensitive") else fold(pat) if rule.get("fold", True) else pat
        if re.search(p, target, flags):
            score += w
            hits.append(f"+{w:g} {pat}")
    for rule in cfg.get("negative", []):
        if re.search(fold(rule["pattern"]), head_folded, re.IGNORECASE):
            w = float(rule.get("weight", 1))
            score -= w
            hits.append(f"-{w:g} {rule['pattern']}")
    fn = fold(filename)
    for hint in cfg.get("filename_hints", []):
        if fold(hint) in fn:
            w = float(cfg.get("filename_weight", 1))
            score += w
            hits.append(f"+{w:g} nazwa pliku ~ {hint}")
            break
    return score, hits


def classify(text: str, filename: str, classes: list[DocClass], head_chars: int = 6000) -> Classification:
    head = text[:head_chars]
    head_folded = fold(head)
    scores, hits = {}, {}
    for c in classes:
        scores[c.name], hits[c.name] = _score(c, head, head_folded, filename)
    best = max(classes, key=lambda c: scores[c.name], default=None)
    if best is None or scores[best.name] < float(best.classify.get("min_score", 3)):
        return Classification(None, scores.get(best.name, 0) if best else 0, scores, hits)
    return Classification(best.name, scores[best.name], scores, hits)
