"""Ścieżki do pól w zagnieżdżonym JSON-ie: "Odwolujacy[0].pelnomocnik.mail", "pelnomocnicy[*].imie_nazwisko"."""
from __future__ import annotations

import copy
import re

_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+|\*)\]")


def tokens(path: str) -> list:
    out = []
    for name, idx in _TOKEN.findall(path):
        if name:
            out.append(name)
        else:
            out.append("*" if idx == "*" else int(idx))
    return out


def get(obj, path: str, default=None):
    cur = obj
    for t in tokens(path):
        if t == "*":
            raise ValueError("get() nie obsługuje [*], użyj get_all()")
        try:
            cur = cur[t]
        except (KeyError, IndexError, TypeError):
            return default
    return cur


def set_(obj, path: str, value, template_item=None):
    """Ustaw wartość, tworząc brakujące elementy list na podstawie szablonu."""
    toks = tokens(path)
    cur = obj
    for i, t in enumerate(toks[:-1]):
        nxt = toks[i + 1]
        if isinstance(t, int):
            while len(cur) <= t:
                cur.append(copy.deepcopy(template_item) if template_item is not None else {})
            if cur[t] is None:
                cur[t] = [] if isinstance(nxt, int) else {}
            cur = cur[t]
        else:
            if cur.get(t) is None:
                cur[t] = [] if isinstance(nxt, int) else {}
            cur = cur[t]
    last = toks[-1]
    if isinstance(last, int):
        while len(cur) <= last:
            cur.append(None)
    cur[last] = value


def leaves(obj, prefix: str = ""):
    """Wszystkie liście (ścieżka, wartość). Listy indeksowane od 0."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaves(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaves(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def generic(path: str) -> str:
    """Odwolujacy[3].nip -> Odwolujacy[*].nip"""
    return re.sub(r"\[\d+\]", "[*]", path)
