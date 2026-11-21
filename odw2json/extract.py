"""Łączenie reguł i LLM w jeden wynik zgodny z szablonem klasy, ze śladem pochodzenia każdego pola.

Polityka wyboru wartości dla pola (konfigurowalna `prefer` w YAML: przy polu albo na poziomie klasy):
  prefer: llm   (domyślnie) - wartość LLM, jeśli ma poprawny format i występuje w tekście;
                              w przeciwnym razie wartość z reguł; w przeciwnym razie null.
  prefer: rules              - wartość z reguł, a gdy jej brak: zweryfikowana wartość LLM.
Wartość, której nie da się ugruntować w tekście, jest odrzucana: w ocenie F1 błędna wartość (FP)
kosztuje tyle samo co brak, a null przy pustym wzorcu daje TN.
"""
from __future__ import annotations

import copy
import re

from . import paths
from .config import DocClass, FieldSpec, load_vocabulary
from .normalize import digits, fold, grounded, locate, normalize
from .rules import Hit, apply_rules, split_blocks


def blank(tpl):
    if isinstance(tpl, dict):
        return {k: blank(v) for k, v in tpl.items()}
    if isinstance(tpl, list):
        return [blank(tpl[0])] if tpl else []
    return None


def conform(tpl, data):
    """Dopasuj odpowiedź (np. LLM) do struktury szablonu: brakujące klucze = null, nadmiarowe usuwamy."""
    if isinstance(tpl, dict):
        data = data if isinstance(data, dict) else {}
        return {k: conform(v, data.get(k)) for k, v in tpl.items()}
    if isinstance(tpl, list):
        if not tpl:
            return data if isinstance(data, list) else []
        if isinstance(data, dict):
            data = [data]
        items = [conform(tpl[0], d) for d in data] if isinstance(data, list) and data else []
        items = [i for i in items if any(v is not None for _, v in paths.leaves(i))] or [blank(tpl[0])]
        return items
    if isinstance(data, (dict, list)):
        return None
    return data


def concrete_paths(obj, generic: str) -> list[str]:
    """Rozwiń 'a[*].b[*].c' na istniejące ścieżki w obiekcie."""
    toks = paths.tokens(generic)
    out = []

    def walk(cur, i, acc):
        if i == len(toks):
            out.append(acc)
            return
        t = toks[i]
        if t == "*":
            if isinstance(cur, list):
                for j in range(len(cur)):
                    walk(cur[j], i + 1, f"{acc}[{j}]")
            return
        if isinstance(t, int):
            if isinstance(cur, list) and t < len(cur):
                walk(cur[t], i + 1, f"{acc}[{t}]")
            return
        if isinstance(cur, dict) and t in cur:
            walk(cur[t], i + 1, f"{acc}.{t}" if acc else t)

    walk(obj, 0, "")
    return out


def _indices(path: str) -> list[int]:
    return [int(x) for x in re.findall(r"\[(\d+)\]", path)]


def _bind(generic: str, idx: list[int]) -> str:
    it = iter(idx)
    return re.sub(r"\[\*\]", lambda m: f"[{next(it, 0)}]", generic)


def _cast(v, cast):
    if v is None or not cast:
        return v
    try:
        return {"int": int, "float": float, "str": str}[cast](v)
    except (ValueError, TypeError):
        return v


def _grow(result, cls: DocClass, list_path: str, n: int):
    lst = paths.get(result, list_path)
    item_tpl = cls.list_templates.get(paths.generic(list_path))
    if isinstance(lst, list) and item_tpl is not None:
        while len(lst) < n:
            lst.append(blank(item_tpl))


def _rule_value_at(hit_value, idx: list[int], per_block: bool = False):
    if per_block:
        if not idx or idx[0] >= len(hit_value):
            return None
        v = hit_value[idx[0]]
        if isinstance(v, list):
            j = idx[1] if len(idx) > 1 else 0
            return v[j] if j < len(v) else None
        return v if len(idx) < 2 or idx[1] == 0 else None
    if isinstance(hit_value, list):
        i = idx[-1] if idx else 0
        return hit_value[i] if i < len(hit_value) else None
    return hit_value if not idx or all(i == 0 for i in idx) else None


def _ensure_list_len(result, cls: DocClass, generic: str, n: int):
    """Wydłuż listę (np. pelnomocnicy) do n elementów, gdy reguły znalazły więcej osób niż jest w wyniku."""
    m = re.match(r"^(.*)\[\*\]", generic)  # najgłębsza lista w ścieżce
    if not m:
        return
    list_path = m.group(1)
    if "[*]" in list_path:
        list_path = _bind(list_path, [0] * list_path.count("[*]"))
    lst = paths.get(result, list_path)
    tpl_key = paths.generic(list_path)
    item_tpl = cls.list_templates.get(tpl_key)
    if isinstance(lst, list) and item_tpl is not None:
        while len(lst) < n:
            lst.append(blank(item_tpl))


def _page_of(snippet: str, pages: list[str]) -> int | None:
    key = fold(snippet)[:60]
    for i, p in enumerate(pages, 1):
        if key and key in fold(p):
            return i
    return None


_VOCABS: dict = {}


def _vocab(spec) -> dict:
    key = spec if isinstance(spec, str) else tuple(spec)
    if key not in _VOCABS:
        _VOCABS[key] = load_vocabulary(spec)
    return _VOCABS[key]


def _n_diacritics(s: str) -> int:
    return sum(1 for c in s if c in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def _derive(spec: FieldSpec, result, path: str, cls: DocClass):
    d = spec.derive
    idx = _indices(path)
    srcs = d.get("from") or []
    srcs = [srcs] if isinstance(srcs, str) else srcs
    vals = [paths.get(result, _bind(s, idx)) for s in srcs]
    src = next((v for v in vals if v not in (None, "", [])), None)   # pierwsza niepusta z listy źródeł
    kind = d.get("kind")
    if kind == "enum_label":
        return cls.enums.get(d["enum"], {}).get(normalize(src, "int")) if src is not None else None
    if kind == "notnull_flag":
        return 1 if src not in (None, "", []) else 0
    if kind == "case":
        for c in d.get("when", []):
            v = paths.get(result, _bind(c["notnull"], idx)) if "notnull" in c else None
            if "notnull" in c and v not in (None, ""):
                return c["value"]
            if "isnull" in c and paths.get(result, _bind(c["isnull"], idx)) in (None, ""):
                return c["value"]
        return d.get("else")
    raise ValueError(f"Nieznany rodzaj pola wyliczanego: {kind}")


def extract(doc, cls: DocClass, llm_json: dict | None, llm_error: str | None = None):
    text = doc.text
    folded, dig = fold(text), digits(text)

    # 1) reguły dla każdego pola (niezależnie od LLM, do weryfikacji i jako zapas)
    blocks = {}
    for lp, cfg in cls.lists.items():
        b = split_blocks(text, cls.sections, cfg)
        parent = lp.rsplit("[*]", 1)[0] if "[*]" in lp else None
        if len(b) >= 2 and (parent is None or parent in blocks):
            blocks[lp] = b
    rule_hits = {}
    for f in cls.fields:
        if not f.rules:
            continue
        hit = None
        lp = max((lp for lp in blocks if f.path.startswith(lp + "[*]")), key=len, default=None)
        if lp:
            per = [apply_rules(f.rules, b, cls.sections, in_block=True) for b in blocks[lp]]
            if any(per):
                hit = Hit([h.value if h else None for h in per], " | ".join(h.evidence or "" for h in per if h),
                          f"bloki:{lp}", per_block=True)
        rule_hits[f.path] = hit or apply_rules(f.rules, text, cls.sections)

    # 2) szkielet wyniku: odpowiedź LLM dopasowana do szablonu albo pusty szablon
    if llm_json is not None:
        result = conform(cls.output_template, llm_json)
    else:
        result = blank(cls.output_template)
        for lp, b in blocks.items():
            if "[*]" not in lp:
                _grow(result, cls, lp, len(b))
        for f in cls.fields:
            h = rule_hits.get(f.path)
            if not h or not isinstance(h.value, list) or "[*]" not in f.path:
                continue
            if h.per_block:
                inner = f.path.rsplit("[*]", 1)[0]
                if inner.count("[*]") == 1:  # lista zagnieżdżona w bloku, np. podpisujący danego mocodawcy
                    for i, v in enumerate(h.value):
                        if isinstance(v, list):
                            _grow(result, cls, inner.replace("[*]", f"[{i}]"), len(v))
            else:
                _ensure_list_len(result, cls, f.path, len(h.value))

    llm_snapshot = copy.deepcopy(result) if llm_json is not None else None
    trace = {}

    # 3) wybór wartości pole po polu
    for f in cls.fields:
        if f.derive:
            continue
        for path in concrete_paths(result, f.path):
            idx = _indices(path)
            raw_llm = paths.get(llm_snapshot, path) if llm_snapshot is not None else None
            v_llm = normalize(raw_llm, f.type)
            ok_llm = v_llm is not None and (not f.require_grounding or grounded(v_llm, f.type, text, folded, dig))
            hit = rule_hits.get(f.path)
            raw_rule = _rule_value_at(hit.value, idx, hit.per_block) if hit else None
            v_rule = normalize(raw_rule, f.type)
            notes = []
            if v_llm is not None and not ok_llm:
                notes.append("wartość LLM odrzucona: brak w tekście dokumentu")
            if raw_llm not in (None, "") and v_llm is None:
                notes.append(f"wartość LLM w złym formacie: {raw_llm!r}")
            if f.prefer == "rules":
                order = [("reguły", v_rule), ("LLM", v_llm if ok_llm else None)]
            else:
                order = [("LLM", v_llm if ok_llm else None), ("reguły", v_rule)]
            source, value = next(((s, v) for s, v in order if v is not None), ("brak", f.default))
            if (source == "reguły" and ok_llm and isinstance(value, str) and isinstance(v_llm, str)
                    and fold(v_llm) == fold(value) and _n_diacritics(v_llm) > _n_diacritics(value)):
                # ta sama wartość, ale LLM odtworzył polskie znaki zgubione przez OCR
                source, value = "reguły (znaki z LLM)", v_llm
            if (v_llm is not None and v_rule is not None and ok_llm
                    and fold(str(v_llm)) != fold(str(v_rule))):
                notes.append(f"rozbieżność LLM={v_llm!r} vs reguły={v_rule!r}")
            if isinstance(value, str) and f.vocabulary:
                canon = _vocab(f.vocabulary).get(fold(value))
                if canon and canon != value:
                    notes.append(f"zapis ze słownika: {value!r} -> {canon!r}")
                    value = canon
            value = _cast(value, f.cast)
            paths.set_(result, path, value)
            if source == "reguły" and hit and hit.evidence:
                snippet, page = hit.evidence, _page_of(hit.evidence, doc.pages)
            elif f.type in ("int", "enum", "flag"):
                page, snippet = None, None  # liczba nie ma sensownego miejsca w tekście
            else:
                page, snippet = locate(value, f.type, doc.pages)
            trace[path] = {
                "wartosc": value, "zrodlo": source, "strona": page, "cytat": snippet,
                "regula": hit.rule if hit else None, "llm": raw_llm, "reguly": raw_rule,
                **({"uwagi": notes} if notes else {}),
            }

    # 4) pola wyliczane (np. opis czynności ze słownika, flaga "przez pełnomocnika")
    for f in cls.fields:
        if not f.derive:
            continue
        for path in concrete_paths(result, f.path):
            value = _cast(_derive(f, result, path, cls), f.cast)
            paths.set_(result, path, value)
            trace[path] = {"wartosc": value, "zrodlo": "wyliczone", "regula": f.derive.get("kind"),
                           "z_pola": f.derive.get("from")}

    meta = {"llm_uzyty": llm_json is not None, **({"llm_blad": llm_error} if llm_error else {})}
    return result, trace, meta
