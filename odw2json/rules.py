"""Biblioteka deterministycznych ekstraktorów sterowanych konfiguracją YAML.

Każda reguła w YAML ma pole `kind` (domyślnie `regex`) i parametry. Reguły pola są próbowane
po kolei, pierwsza niepusta wartość wygrywa. Każdy wynik niesie fragment tekstu-dowód.

Dostępne rodzaje reguł:
  regex          - wyrażenie regularne, grupa `v` (lub 1); opcjonalnie section, all, max_chars
  sentence_map   - znajdź zdanie po kotwicy, zmapuj słowa kluczowe na wartość (np. id powodu)
  titled_persons - osoby poprzedzone tytułem zawodowym (adw., r. pr., radca prawny, ...)
  signatories    - osoby z bloku podpisów (między wzorcami start/end)
  entity_name    - nazwa podmiotu stojąca przed adresem / numerami rejestrowymi
  first_line     - pierwsza sensowna linia sekcji
  const          - stała wartość
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import TITLES_RE, ws

FLAGS = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}
UPPER = "A-ZĄĆĘŁŃÓŚŹŻ"
LOWER = "a-ząćęłńóśźż"
NAME_WORD = rf"[{UPPER}][{LOWER}]+(?:-[{UPPER}][{LOWER}]+)?"
PERSON = rf"{NAME_WORD}(?:\s+{NAME_WORD}){{1,2}}"
TITLE = (r"(?:r\.\s*pr\.|radc[aąy]\w*\s+prawn\w*|adw\.|adwokat\w*|mec\.|apl\.\s*adw\.|"
         r"apl\.\s*radc\.|aplikant\w*\s+(?:adwokack|radcowsk)\w*)")
ROLE_WORDS = re.compile(
    r"\b(prezes|wiceprezes|członek|czlonek|zarząd|zarzad|prokurent|wspólnik|wspolnik|dyrektor|"
    r"pełnomocnik|pelnomocnik|komplementariusz|właściciel|wlasciciel|przedsiębiorca|burmistrz|"
    r"wójt|starosta|kierownik|główn|skarbnik|sekretarz|mocodawca|podpis|data|kwalifikowany)\b",
    re.IGNORECASE)
NOT_NAME = re.compile(
    r"\b(ul|al|sp|spółka|spolka|kancelaria|zamawiający|odwołujący|krajowa|izba|prezes|warszawa|"
    r"pełnomocnictwo|strona|zarząd|zarzadu|zarządu|s\.a|technologie|systemy|usługi|serwis|izb\w*|krajow\w*|"
    r"odwoławcz\w*|zamówień|publiczn\w*|prawo|wykonawc\w*|mocodawc\w*|data|dotyczy|zakres|podpis\w*)\b", re.IGNORECASE)


@dataclass
class Hit:
    value: object
    evidence: str | None = None
    rule: str | None = None
    per_block: bool = False        # value = lista wartości, po jednej na blok (podmiot)


def _flags(spec: str | None) -> int:
    f = 0
    for ch in (spec if spec is not None else "i"):
        f |= FLAGS.get(ch, 0)
    return f


def section_text(text: str, sections: dict, name: str | None) -> str:
    if not name:
        return text
    sec = sections.get(name)
    if not sec:
        return text
    flags = _flags(sec.get("flags", "i"))
    starts = list(re.finditer(sec["start"], text, flags))
    if not starts:
        return ""
    occ = int(sec.get("occurrence", 0))
    if occ >= len(starts):
        return ""
    st = starts[occ].end()
    end = len(text)
    if sec.get("end"):
        m = re.compile(sec["end"], flags).search(text, st)
        if m:
            end = m.start()
    if sec.get("max_chars"):
        end = min(end, st + int(sec["max_chars"]))
    return text[st:end]


def _snip(text: str, a: int, b: int, pad: int = 50) -> str:
    return ws(text[max(0, a - pad): b + pad])


def r_regex(rule, text):
    flags = _flags(rule.get("flags"))
    if rule.get("max_chars"):
        text = text[: int(rule["max_chars"])]
    rx = re.compile(rule["pattern"], flags)
    grp = rule.get("group", "v" if "(?P<v>" in rule["pattern"] else 1)
    if rule.get("all"):
        vals, ev = [], []
        for m in rx.finditer(text):
            v = ws(m.group(grp) or "")
            if v and v not in vals:
                vals.append(v)
                ev.append(_snip(text, m.start(), m.end()))
        return Hit(vals, " | ".join(ev[:3])) if vals else None
    m = rx.search(text)
    if not m:
        return None
    v = m.group(grp) if rx.groups else m.group(0)
    if v is None:
        return None
    if "value" in rule:  # dopasowanie wzorca => stała wartość
        return Hit(rule["value"], _snip(text, m.start(), m.end()))
    return Hit(ws(v), _snip(text, m.start(), m.end()))


_SENT_END = re.compile(rf"\.\s+(?=[{UPPER}][{LOWER}]+[\s,])|\n\s*\n|(?=Zarzut\s+nr)")


def r_sentence_map(rule, text):
    flags = _flags(rule.get("flags"))
    skip = re.compile(rule["skip"], flags) if rule.get("skip") else None
    for m in re.finditer(rule["anchor"], text, flags):
        rest = text[m.start(): m.start() + int(rule.get("window", 400))]
        e = _SENT_END.search(rest, len(m.group(0)))
        sent = ws(rest[: e.start()] if e else rest)
        if skip and skip.search(sent):
            continue
        ret = rule.get("return", "value")
        for opt in rule.get("map", []):
            if re.search(opt["pattern"], sent, flags):
                if ret == "value":
                    return Hit(opt["value"], sent)
                if ret == "match":
                    return Hit(ws(m.group("v") if "v" in m.groupdict() else m.group(0)), sent)
        if not rule.get("map"):
            return Hit(ws(m.group("v") if "v" in m.groupdict() else sent), sent)
    return None


def r_titled_persons(rule, text):
    rx = re.compile(rf"{TITLE}\s*(?P<v>{PERSON})", re.IGNORECASE if rule.get("ci") else 0)
    rx = re.compile(rf"(?i:{TITLE})\s*(?P<v>{PERSON})")
    vals, ev = [], []
    for m in rx.finditer(text):
        v = _trim_person(m.group("v"))
        if v and v not in vals:
            vals.append(v)
            ev.append(_snip(text, m.start(), m.end()))
    if not vals:
        return None
    return Hit(vals if rule.get("all", True) else vals[0], " | ".join(ev[:3]))


def _trim_person(v: str) -> str | None:
    words = v.split()
    # odcinamy słowa, które nie są częścią nazwiska (np. "Kowalski Kancelaria")
    out = []
    for w in words:
        if NOT_NAME.search(w):
            break
        out.append(w)
    return " ".join(out) if len(out) >= 2 else None


DOTS = re.compile(r"^\s*(?:[.…_]{5,}|-{8,})\s*$")


def _signatories_dots(rule, text):
    """Osoby podpisane pod linią kropek (bez tytułów zawodowych), aż do wzorca `end`."""
    flags = _flags(rule.get("flags"))
    end = re.compile(rule["end"], flags) if rule.get("end") else None
    lines = text.splitlines()
    vals, ev = [], []
    for i, line in enumerate(lines):
        if end and end.search(line):
            break
        if not DOTS.match(line):
            continue
        for nxt in lines[i + 1: i + 4]:
            n = ws(nxt)
            if not n or re.match(r"(?:Za|W imieniu|Mocodawca|Podpis)\b", n, re.I):
                continue
            if end and end.search(n):
                break
            if re.match(TITLE, n, re.I):
                break
            m = re.fullmatch(rf"({PERSON})(?:\s*[,–-].*)?", n)
            if m and _trim_person(m.group(1)):
                p = _trim_person(m.group(1))
                if p not in vals:
                    vals.append(p)
                    ev.append(n)
            break
    return Hit(vals, " | ".join(ev)) if vals else None


def r_signatories(rule, text):
    flags = _flags(rule.get("flags"))
    if rule.get("mode") == "dots":
        return _signatories_dots(rule, text)
    block = text
    if rule.get("start"):
        ms = list(re.finditer(rule["start"], text, flags))
        if not ms:
            return None
        block = text[ms[-1].end():] if rule.get("last", True) else text[ms[0].end():]
    if rule.get("end"):
        me = re.search(rule["end"], block, flags)
        if me:
            block = block[: me.start()]
    vals = []
    for line in block.splitlines():
        line = ws(line).strip(".… _")
        if not line or ROLE_WORDS.search(line) and not re.fullmatch(PERSON, line):
            # linia z funkcją ("Prezes Zarządu") - pomijamy, ale nazwisko może być przed przecinkiem
            m = re.match(rf"({PERSON})\s*[,–-]", line)
            if m and _trim_person(m.group(1)):
                vals.append(_trim_person(m.group(1)))
            continue
        if re.match(TITLE, line, re.I) and rule.get("exclude_titled", True):
            continue
        m = re.fullmatch(rf"({PERSON})(?:\s*[,–-].*)?", line)
        if m:
            p = _trim_person(m.group(1))
            if p and p not in vals:
                vals.append(p)
    return Hit(vals, ws(block)[:200]) if vals else None


def r_entity_name(rule, text):
    """Nazwa podmiotu: tekst przed ', ul.' / ' z siedzibą' / '(KRS' / nowej linii z adresem."""
    t = text.strip()
    if rule.get("after"):
        m = re.search(rule["after"], t, re.I)
        if not m:
            return None
        t = t[m.end():].lstrip(" :\n")
    if rule.get("skip"):
        lines = t.splitlines()
        while lines and (not lines[0].strip() or re.search(rule["skip"], lines[0], re.I)):
            lines.pop(0)
        t = "\n".join(lines)
    t = t.strip()
    m = re.match(
        r"(?P<v>.+?)(?:,?\s*(?:z\s+siedzib\w+|ul\.|al\.|pl\.|os\.|\(KRS|\(NIP|KRS[:\s]|NIP[:\s]|adres|"
        r"prowadząc\w+|wpisan\w+|\(dalej|\(zwan\w*|zwan\w+\s+dalej|\d{2}-\d{3})|\n\s*(?:ul\.|al\.|pl\.|os\.|KRS|NIP|\d{2}-\d{3}))",
        t, re.S)
    if not m:
        return None
    v = ws(m.group("v")).strip(" ,")
    if len(v) < 3 or len(v) > int(rule.get("max_len", 200)):
        return None
    return Hit(v, ws(t[: m.end() + 30]))


def r_first_line(rule, text):
    skip = re.compile(rule["skip"], re.I) if rule.get("skip") else None
    for line in text.splitlines():
        line = ws(line).strip(" :")
        if len(line) < 3 or (skip and skip.search(line)):
            continue
        return Hit(line, line)
    return None


def r_const(rule, text):
    return Hit(rule.get("value"), None)


KINDS = {
    "regex": r_regex, "sentence_map": r_sentence_map, "titled_persons": r_titled_persons,
    "signatories": r_signatories, "entity_name": r_entity_name, "first_line": r_first_line,
    "const": r_const,
}


def split_blocks(text: str, sections: dict, cfg: dict) -> list[str]:
    """Podziel sekcję na bloki (np. członkowie konsorcjum, kilku zamawiających)."""
    scope = section_text(text, sections, cfg.get("section"))
    parts = re.split(cfg["split"], scope, flags=_flags(cfg.get("flags", "m")))
    if len(parts) < 3:
        return []
    req = re.compile(cfg["require"], re.I) if cfg.get("require") else None
    return [p for p in parts[1:] if p.strip() and (not req or req.search(p))]


def apply_rules(rules: list, text: str, sections: dict, in_block: bool = False) -> Hit | None:
    """in_block=True: tekst to już blok jednego podmiotu, więc sekcje są pomijane."""
    for i, rule in enumerate(rules or []):
        kind = rule.get("kind", "regex")
        fn = KINDS.get(kind)
        if not fn:
            raise ValueError(f"Nieznany rodzaj reguły: {kind}")
        sec = rule.get("section")
        if sec == "@multi":
            if not in_block:
                continue
            scope = text
        else:
            scope = text if in_block else section_text(text, sections, sec)
        if not scope:
            continue
        try:
            hit = fn(rule, scope)
        except re.error as e:
            raise ValueError(f"Błędny regex w regule {rule}: {e}") from e
        if hit and hit.value not in (None, "", []):
            hit.rule = f"{kind}#{i}" + (f"@{rule['section']}" if rule.get("section") else "")
            return hit
    return None
