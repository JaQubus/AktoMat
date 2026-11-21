"""Kontrola formalna teczki sprawy: kompletność, zgodność między dokumentami, terminy i walidacja wartości.

Reguły są w config/kontrola.yaml; ten moduł tylko je wykonuje. Wejście to lista dokumentów sprawy
w postaci {"plik", "klasa", "json"} (wynik ekstrakcji, ewentualnie poprawiony przez referenta).
"""
from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache

import yaml

from .config import CONFIG_DIR
from .normalize import fold


def load_rules(path=None) -> dict:
    p = path or (CONFIG_DIR / "kontrola.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


# ---------- dostęp do pól ----------

def values(obj, path: str) -> list:
    """Wartości pod ścieżką "A[*].b.c" (gwiazdka i indeksy list). Pomija None i puste napisy."""
    cur = [obj]
    for part in re.findall(r"[^.\[\]]+|\[\*\]|\[\d+\]", path):
        nxt = []
        for o in cur:
            if part == "[*]":
                nxt.extend(o if isinstance(o, list) else [])
            elif part.startswith("["):
                i = int(part[1:-1])
                if isinstance(o, list) and i < len(o):
                    nxt.append(o[i])
            elif isinstance(o, dict) and part in o:
                nxt.append(o[part])
        cur = nxt
    return [v for v in cur if v is not None and v != "" and not isinstance(v, (dict, list))]


def _docs(docs: list[dict], klasa: str) -> list[dict]:
    return [d for d in docs if d.get("klasa") == klasa and isinstance(d.get("json"), dict)]


def _norm(s) -> str:
    return re.sub(r"\s+", " ", fold(str(s)).lower()).strip()


def _compact(s) -> str:
    return re.sub(r"[\W_]+", "", fold(str(s)).lower())


def _similar(a, b, threshold: float) -> bool:
    from rapidfuzz import fuzz

    a, b = _norm(a), _norm(b)
    if threshold >= 100:
        return _compact(a) == _compact(b)
    return fuzz.token_sort_ratio(a, b) >= threshold


# ---------- wymagane dokumenty ----------

def _condition(docs, gdy) -> bool:
    if not gdy:
        return True
    if "jest" in gdy:
        return bool(_docs(docs, gdy["jest"]))
    for d in _docs(docs, gdy.get("klasa")):
        vals = values(d["json"], gdy["pole"])
        if "rowne" in gdy and any(str(v) == str(gdy["rowne"]) for v in vals):
            return True
    return False


def _required(docs, rule) -> dict:
    out = {"id": rule.get("id"), "opis": rule.get("opis"), "dokumenty": []}
    if not _condition(docs, rule.get("gdy")):
        return {**out, "wynik": "nie_dotyczy", "szczegoly": "Wymóg nie dotyczy tej sprawy."}
    cands = _docs(docs, rule["klasa"])
    if rule.get("pole"):
        inc = re.compile(rule["wzorzec"], re.I) if rule.get("wzorzec") else None
        exc = re.compile(rule["wyklucz"], re.I) if rule.get("wyklucz") else None
        ok, seen = [], []
        for d in cands:
            raw = " ".join(str(v) for v in values(d["json"], rule["pole"]))
            txt = _norm(raw)
            seen.append((d, raw))
            if (inc is None or inc.search(txt)) and not (exc and exc.search(txt)):
                ok.append(d)
        if ok:
            return {**out, "wynik": "ok", "dokumenty": [d.get("plik") for d in ok]}
        level = rule.get("poziom", "brak")
        if seen:
            titles = "; ".join(f"„{t[:90]}”" for _, t in seen if t) or "bez tytułu"
            return {**out, "wynik": level, "dokumenty": [d.get("plik") for d, _ in seen],
                    "szczegoly": f"Żaden dokument nie pasuje. Znalezione: {titles}"}
        return {**out, "wynik": level, "szczegoly": "Brak dokumentu w teczce."}
    if cands:
        return {**out, "wynik": "ok", "dokumenty": [d.get("plik") for d in cands]}
    return {**out, "wynik": rule.get("poziom", "brak"), "szczegoly": "Brak dokumentu w teczce."}


# ---------- zgodność między dokumentami ----------

def _side(docs, spec):
    vals, files = [], []
    for d in _docs(docs, spec["klasa"]):
        v = values(d["json"], spec["pole"])
        if v:
            vals.extend(v)
            files.append(d.get("plik"))
    return vals, files


def _cross(docs, rule) -> dict:
    a, fa = _side(docs, rule["a"])
    b, fb = _side(docs, rule["b"])
    out = {"id": rule.get("id"), "opis": rule.get("opis"), "a": a, "b": b, "dokumenty": fa + fb}
    if not a or not b:
        missing = rule["a"]["klasa"] if not a else rule["b"]["klasa"]
        return {**out, "wynik": "brak_danych", "szczegoly": f"Brak wartości do porównania ({missing})."}
    thr = float(rule.get("podobienstwo", 85))
    mode = rule.get("tryb", "rowne")
    if mode == "w_tekscie":
        hit = [x for x in a if any(_compact(x) and _compact(x) in _compact(y) for y in b)]
        bad = [x for x in a if x not in hit]
    elif mode == "zawiera_sie":
        bad = [x for x in a if not any(_similar(x, y, thr) for y in b)]
    else:
        bad = [] if any(_similar(x, y, thr) for x in a for y in b) else list(a)
    if bad:
        return {**out, "wynik": "niezgodne", "szczegoly": "Brak odpowiednika: " + ", ".join(map(str, bad))}
    return {**out, "wynik": "ok"}


# ---------- terminy ----------

def _easter(y: int) -> dt.date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return dt.date(y, month, day)


@lru_cache(maxsize=64)
def _holidays(year: int, fixed: tuple, movable: tuple) -> frozenset:
    out = {dt.date(year, int(md[:2]), int(md[3:])) for md in fixed}
    e = _easter(year)
    off = {"wielkanoc": 0, "poniedzialek_wielkanocny": 1, "zeslanie_ducha": 49, "boze_cialo": 60}
    out |= {e + dt.timedelta(days=off[m]) for m in movable if m in off}
    return frozenset(out)


def deadline(start: dt.date, days: int, rules: dict) -> tuple[dt.date, bool]:
    """Ostatni dzień terminu; przesunięty z dnia wolnego na najbliższy dzień roboczy. Zwraca (data, czy_przesunięto)."""
    sw = rules.get("swieta", {}) or {}
    fixed, mov = tuple(sw.get("stale", [])), tuple(sw.get("ruchome", []))
    end = start + dt.timedelta(days=days)
    moved = False
    while end.weekday() >= 5 or end in _holidays(end.year, fixed, mov):
        end += dt.timedelta(days=1)
        moved = True
    return end, moved


def _parse_date(v):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


DNI = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]


def _terms(docs, rule, rules, days_override=None) -> dict:
    out = {"id": rule.get("id"), "opis": rule.get("opis"), "dni": days_override or rule.get("dni"),
           "warianty": rule.get("warianty") or [rule.get("dni")]}
    for d in _docs(docs, rule["klasa"]):
        for v in values(d["json"], rule["pole"]):
            start = _parse_date(v)
            if start:
                end, moved = deadline(start, int(out["dni"]), rules)
                return {**out, "wynik": "ok", "od": start.isoformat(), "do": end.isoformat(),
                        "dzien_tygodnia": DNI[end.weekday()], "przesuniety": moved, "dokumenty": [d.get("plik")]}
    return {**out, "wynik": "brak_danych", "szczegoly": "Brak daty początkowej w dokumentach."}


# ---------- walidacja wartości ----------

def _digits(s) -> str:
    return re.sub(r"\D", "", str(s))


def check_value(kind: str, v) -> bool | None:
    """True/False dla znanego typu, None gdy wartość nie ma sensu dla walidacji (np. inna długość)."""
    s = _digits(v)
    if kind == "nip":
        if len(s) != 10:
            return False
        c = sum(int(a) * w for a, w in zip(s, [6, 5, 7, 2, 3, 4, 5, 6, 7])) % 11
        return c != 10 and c == int(s[9])
    if kind == "regon":
        if len(s) == 9:
            c = sum(int(a) * w for a, w in zip(s, [8, 9, 2, 3, 4, 5, 6, 7])) % 11 % 10
            return c == int(s[8])
        if len(s) == 14:
            c = sum(int(a) * w for a, w in zip(s, [2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8])) % 11 % 10
            return c == int(s[13])
        return False
    if kind == "krs":
        return len(s) == 10
    if kind == "pesel":
        if len(s) != 11:
            return False
        c = (10 - sum(int(a) * w for a, w in zip(s, [1, 3, 7, 9, 1, 3, 7, 9, 1, 3])) % 10) % 10
        return c == int(s[10])
    if kind == "nrb":
        if len(s) != 26:
            return False
        n = int(s[2:] + "2521" + s[:2])   # PL = 25 21
        return n % 97 == 1
    return None


def validate_fields(doc_json: dict, rules: dict, prefix: str = "") -> dict:
    """{ścieżka: {"typ", "ok"}} dla pól, których nazwa ma regułę w `walidacja`."""
    spec = rules.get("walidacja", {}) or {}
    out: dict = {}

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
        elif o not in (None, ""):
            name = path.rsplit(".", 1)[-1]
            if name in spec:
                out[path] = {"typ": spec[name], "ok": check_value(spec[name], o)}

    walk(doc_json or {}, prefix)
    return out


# ---------- całość ----------

def run_checks(docs: list[dict], rules: dict | None = None, term_days: dict | None = None) -> dict:
    rules = rules if rules is not None else load_rules()
    req = [_required(docs, r) for r in rules.get("wymagane", [])]
    fields = []
    for r in rules.get("pola", []):
        ds = _docs(docs, r["klasa"])
        if not ds:
            continue
        ok = any(values(d["json"], r["pole"]) for d in ds)
        fields.append({"id": r["pole"], "opis": r.get("opis"), "wynik": "ok" if ok else r.get("poziom", "ostrzezenie"),
                       "dokumenty": [d.get("plik") for d in ds], "szczegoly": None if ok else "Brak w dokumencie."})
    cross = [_cross(docs, r) for r in rules.get("zgodnosc", [])]
    terms = [_terms(docs, r, rules, (term_days or {}).get(r.get("id"))) for r in rules.get("terminy", [])]
    valid = {d.get("plik"): validate_fields(d.get("json"), rules) for d in docs if isinstance(d.get("json"), dict)}
    all_items = req + fields + cross
    summary = {
        "braki": sum(1 for x in all_items if x["wynik"] in ("brak", "niezgodne")),
        "ostrzezenia": sum(1 for x in all_items if x["wynik"] == "ostrzezenie"),
        "bledne_sumy": sum(1 for v in valid.values() for r in v.values() if r["ok"] is False),
    }
    return {"wymagane": req, "pola": fields, "zgodnosc": cross, "terminy": terms, "walidacja": valid,
            "podsumowanie": summary}
