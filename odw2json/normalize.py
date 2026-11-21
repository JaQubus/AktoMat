"""Normalizacja i walidacja wartości wg typu pola (typy deklarowane w config/classes/*.yaml).

Każdy typ ma:
  normalize(raw) -> wartość kanoniczna albo None (gdy nie da się sparsować),
  grounded(value, text) -> czy wartość faktycznie występuje w tekście dokumentu.
Ugruntowanie chroni przed halucynacjami LLM: wartość, której nie ma w dokumencie, to FP w ocenie.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

from rapidfuzz import fuzz

MONTHS = {
    "stycznia": 1, "styczeń": 1, "styczen": 1, "lutego": 2, "luty": 2, "marca": 3, "marzec": 3,
    "kwietnia": 4, "kwiecień": 4, "maja": 5, "maj": 5, "czerwca": 6, "czerwiec": 6,
    "lipca": 7, "lipiec": 7, "sierpnia": 8, "sierpień": 8, "września": 9, "wrzesień": 9,
    "wrzesnia": 9, "października": 10, "październik": 10, "pazdziernika": 10,
    "listopada": 11, "listopad": 11, "grudnia": 12, "grudzień": 12,
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
    "xi": 11, "xii": 12,
}

TITLES_RE = re.compile(
    r"^(?:(?:r\.\s*pr\.?|radc[aąy]\w*\s+prawn\w*|adw\.?|adwokat\w*|mec\.?|mecenas\w*|"
    r"apl\.?\s*(?:adw|radc)\.?\w*|aplikant\w*\s+\w+|pan[iy]?|pan|p\.|dr\.?|hab\.?|prof\.?|inż\.?|mgr\.?)\s+)+",
    re.IGNORECASE,
)


def ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def fold(s: str) -> str:
    """Do porównań: małe litery, bez diakrytyków, pojedyncze spacje."""
    s = (s or "").replace("ł", "l").replace("Ł", "L")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("„", '"').replace("”", '"').replace("“", '"').replace("–", "-").replace("—", "-")
    return ws(s).lower()


def digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


# ---------------------------------------------------------------- normalizatory

def n_string(v):
    if v is None:
        return None
    s = ws(str(v)).strip(" ,;:")
    s = s.strip("„”\"'")
    return s or None


def n_person(v):
    s = n_string(v)
    if not s:
        return None
    s = TITLES_RE.sub("", s)
    s = re.sub(r",?\s*(?:r\.\s*pr\.?|adw\.?|radca prawny|adwokat)$", "", s, flags=re.I)
    s = re.sub(r"\s*\((?:nr|wpis|PESEL)[^)]*\)\s*$", "", s, flags=re.I)
    return ws(s) or None


def n_int(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    d = re.search(r"-?\d+", str(v))
    return int(d.group()) if d else None


def n_date(v):
    if v is None:
        return None
    s = fold(str(v))
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.search(r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})", s)
        if m:
            d, mo, y = map(int, m.groups())
        else:
            m = re.search(r"(\d{1,2})\s+([a-z]+)\.?\s+(\d{4})", s)
            if not m:
                return None
            mon = fold(m.group(2))
            mo = next((n for k, n in MONTHS.items() if fold(k) == mon), None)
            if mo is None:
                return None
            d, y = int(m.group(1)), int(m.group(3))
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def n_amount(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 2)
    s = str(v).replace("\xa0", " ")
    m = re.search(r"-?\d[\d \.]*(?:,\d{1,2})?|-?\d+(?:\.\d{1,2})?", s)
    if not m:
        return None
    t = m.group().replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1 or re.search(r"\.\d{3}$", t):
        t = t.replace(".", "")
    try:
        return round(float(t), 2)
    except ValueError:
        return None


def _fixed_digits(n):
    def f(v):
        d = digits(v)
        return d if len(d) == n else None
    return f


def n_regon(v):
    d = digits(v)
    return d if len(d) in (9, 14) else None


def n_account(v):
    d = digits(v)
    return d if len(d) == 26 else None


def n_pesel(v):
    d = digits(v)
    return d if len(d) == 11 else None


def n_email(v):
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", str(v or ""))
    return m.group().lower() if m else None


def n_bzp(v):
    if v is None:
        return None
    m = re.search(r"(\d{4})\s*/\s*BZP\s*[O0]?\s*(\d{8})(?:\s*/\s*(\d{2}))?", str(v), re.I)
    if not m:
        return None
    return f"{m.group(1)}/BZP{m.group(2)}" + (f"/{m.group(3)}" if m.group(3) else "")


def n_ted(v):
    if v is None:
        return None
    s = str(v)
    m = re.search(r"(\d{4})\s*/\s*S\s*\d{1,3}\s*-\s*(\d{5,7})", s, re.I)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    m = re.search(r"(\d{5,7})\s*-\s*(\d{4})", s)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def n_refno(v):
    s = n_string(v)
    if not s:
        return None
    s = re.sub(r"\s*([./\-])\s*", r"\1", s)
    return s.rstrip(".,;)") or None


NORMALIZERS = {
    "string": n_string, "text": n_string, "name": n_string, "person": n_person,
    "int": n_int, "enum": n_int, "flag": n_int,
    "date": n_date, "amount": n_amount,
    "nip": _fixed_digits(10), "krs": _fixed_digits(10), "regon": n_regon,
    "pesel": n_pesel, "account": n_account, "email": n_email,
    "bzp": n_bzp, "ted": n_ted, "refno": n_refno,
}


def normalize(value, typ: str):
    fn = NORMALIZERS.get(typ or "string", n_string)
    try:
        return fn(value)
    except Exception:  # noqa: BLE001 - normalizacja nigdy nie może wywrócić pipeline'u
        return None


# ---------------------------------------------------------------- ugruntowanie w tekście

DIGIT_TYPES = {"nip", "krs", "regon", "pesel", "account"}


def grounded(value, typ: str, text: str, folded: str | None = None, dig: str | None = None) -> bool:
    """Czy znormalizowana wartość ma pokrycie w tekście dokumentu."""
    if value is None:
        return True
    typ = typ or "string"
    if typ in DIGIT_TYPES:
        dig = dig if dig is not None else digits(text)
        return str(value) in dig
    if typ == "date":
        return locate(value, typ, [text])[0] is not None
    if typ in ("int", "enum", "flag", "amount"):
        return True
    if typ == "bzp":
        return digits(value)[4:] in digits(text)
    if typ == "ted":
        return digits(str(value).split("-")[0]) in digits(text)
    folded = folded if folded is not None else fold(text)
    fv = fold(str(value))
    if not fv:
        return True
    if fv in folded:
        return True
    if typ == "email":
        return False
    if typ == "person":
        # odmiana nazwisk (mianownik vs. dopełniacz): wystarczy, że rdzeń każdego słowa jest w tekście
        toks = [t for t in re.split(r"[\s-]+", fv) if len(t) > 1]
        return bool(toks) and all(re.search(r"\b" + re.escape(t[: max(3, len(t) - 2)]), folded) for t in toks)
    return fuzz.partial_ratio(fv, folded) >= 88


def locate(value, typ: str, pages: list[str]) -> tuple[int | None, str | None]:
    """Znajdź stronę i fragment tekstu, z którego pochodzi wartość (transparentność)."""
    if value is None:
        return None, None
    needles = []
    if typ in DIGIT_TYPES:
        v = str(value)
        for pi, p in enumerate(pages):
            # dopuszczamy separatory między cyframi (spacje, myślniki)
            pat = r"\D?".join(re.escape(c) for c in v[:10])
            m = re.search(pat, p)
            if m:
                return pi + 1, _snip(p, m.start(), m.end())
        return None, None
    if typ == "date":
        y, mo, d = str(value).split("-")
        needles = [f"{int(d)}.{mo}.{y}", f"{d}.{mo}.{y}", f"{d}-{mo}-{y}", f"{int(d)}-{mo}-{y}",
                   f"{d}/{mo}/{y}", f"{d}.{mo}.{y[2:]}", f"{int(d)}.{int(mo)}.{y}", str(value)]
        mon_names = [k for k, n in MONTHS.items() if n == int(mo) and len(k) > 4]
        needles += [f"{int(d)} {k} {y}" for k in mon_names] + [f"{d} {k} {y}" for k in mon_names]
    elif typ == "amount":
        whole = int(float(value))
        needles = [f"{whole:,}".replace(",", " "), f"{whole:,}".replace(",", "."), str(whole)]
    elif typ == "ted":
        needles = [str(value).split("-")[0]]
    elif typ == "bzp":
        needles = [digits(value)[4:]]
    else:
        needles = [str(value)]
    for pi, p in enumerate(pages):
        fp = fold(p)
        for n in needles:
            fn_ = fold(n)
            if not fn_:
                continue
            i = fp.find(fn_)
            if i >= 0:
                return pi + 1, _snip(ws(p), i, i + len(fn_), folded_index=True)
    return None, None


def _snip(p: str, a: int, b: int, folded_index: bool = False, pad: int = 60) -> str:
    src = ws(p) if folded_index else p
    return ws(src[max(0, a - pad): b + pad])
