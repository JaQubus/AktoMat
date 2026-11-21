"""Reguły oceny formalnej F1–F13 — deterministyczne, parametry z config/rules.yaml.

Zasady: niepewne dane → do_weryfikacji_ręcznej, NIGDY niespełnione. `braki_formalne` = są reguły niespełnione.
Przy brakujących danych wejściowych reguła sprawdza wszystkie możliwe interpretacje: jeśli wszystkie dają ten sam wynik,
wynik jest pewny, inaczej → do weryfikacji ręcznej.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from rapidfuzz import fuzz

from app.models.karta import Kryterium, StatusReguly
from pipeline.calendar_pl import compute_deadline

S, N, D, W = (StatusReguly.spelnione, StatusReguly.niespelnione, StatusReguly.nie_dotyczy, StatusReguly.do_weryfikacji)
WARSAW = ZoneInfo("Europe/Warsaw")
NAZWY = {
    "F1": "Termin wniesienia odwołania", "F2": "Kwota wpisu", "F3": "Wpis wniesiony w terminie",
    "F4": "Podpis kwalifikowany lub zaufany", "F5": "Podpis osoby uprawnionej", "F6": "Pełnomocnictwo",
    "F7": "Opłata skarbowa od pełnomocnictwa", "F8": "Dowód przekazania kopii zamawiającemu",
    "F9": "Wskazanie czynności/zaniechania", "F10": "Wskazanie żądania", "F11": "Okoliczności faktyczne i prawne",
    "F12": "Dane odwołującego potwierdzone w rejestrze", "F13": "Adres e-mail i adres do doręczeń elektronicznych",
}


# ───────────────────────── konfiguracja ─────────────────────────


def load_config(path: Path | str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# ───────────────────────── dopasowanie nazwisk ─────────────────────────


def normalize_name(s: str) -> str:
    s = s.replace("ł", "l").replace("Ł", "L")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def _tok_compat(a: str, b: str, prog: float) -> bool:
    if a == b:
        return True
    if (len(a) == 1 or len(b) == 1) and a[0] == b[0]:  # inicjał
        return True
    return fuzz.ratio(a, b) >= prog


def name_score(a: str, b: str, prog: float = 85) -> float:
    """token_set_ratio (0–100). Gdy któryś token krótszego zapisu nie ma pary (np. Jan ≠ Janusz), wynik < progu;
    gdy wszystkie mają parę (równe, inicjał, ≥ próg), wynik ≥ progu (np. „J. Kowalski” = „Jan Kowalski”)."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    ta, tb = na.split(), nb.split()
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    ts = fuzz.token_set_ratio(na, nb)
    if all(any(_tok_compat(x, y, prog) for y in long_) for x in short):
        return max(ts, prog)
    return min(ts, prog - 1)


def best_match(name: str, candidates: list[str], prog: float = 85) -> tuple[float, str | None]:
    best = (0.0, None)
    for c in candidates:
        sc = name_score(name, c, prog)
        if sc > best[0]:
            best = (sc, c)
    return best


# ───────────────────────── wejście ─────────────────────────


@dataclass
class Facts:
    """Fakty z ekstrakcji/rejestrów/podpisów. None = nieustalone (→ weryfikacja ręczna)."""
    # termin
    czynnosc_date: date | None = None
    zaniechanie: bool = False
    powyzej_progu_ue: bool | None = None
    elektroniczna: bool | None = None
    signature_time: datetime | None = None  # najwcześniejszy podpis
    # podpis
    signature_valid: bool | None = None
    signature_level: str | None = None  # qualified | trusted | unqualified | unknown
    signer_name: str | None = None
    # wpis
    typ_zamowienia: str | None = None  # dostawy | uslugi | roboty
    wpis_wniesione: float | None = None
    wpis_data: date | None = None
    # reprezentacja
    organ_members: list[str] | None = None
    pelnomocnictwo_zalaczone: bool | None = None
    pelnomocnicy: list[str] | None = None  # osoby wymienione w pełnomocnictwie; None = nie ustalono
    oplata_skarbowa_found: bool | None = None  # przelew opłaty skarbowej (17 zł) wśród dokumentów
    dowod_kopii: bool | None = None
    # treść odwołania
    czynnosc_opis: str | None = None
    zadanie: str | None = None
    okolicznosci: str | None = None
    text_quality_ok: bool = True  # False: skan słabej jakości → braki treści nie są pewne
    # odwołujący
    odw_nazwa: str | None = None
    odw_adres: str | None = None
    odw_nip: str | None = None
    odw_krs: str | None = None
    rejestr_potwierdzony: bool | None = None
    # F13
    postepowanie_start: date | None = None
    emails: list[str] | None = None
    ade: list[str] | None = None
    src: dict[str, str] = field(default_factory=dict)  # nazwa faktu → źródło (do Kryterium.source)


@dataclass
class RulesResult:
    kryteria: list[Kryterium]
    braki_formalne: bool
    lista_brakow: list[str]
    termin: date | None = None  # termin graniczny, gdy jednoznaczny
    termin_ustawowy: str | None = None
    wpis_wymagany: float | None = None


def _verdict(passes: list[bool]) -> bool | None:
    return True if all(passes) else False if not any(passes) else None


def _src(f: Facts, *keys: str) -> str | None:
    s = [f.src[k] for k in keys if k in f.src]
    return "; ".join(dict.fromkeys(s)) or None


def _sign_date(f: Facts) -> date | None:
    t = f.signature_time
    return None if t is None else (t.astimezone(WARSAW) if t.tzinfo else t).date()


# ───────────────────────── reguły ─────────────────────────


def _term_candidates(f: Facts, cfg: dict) -> list[tuple[int, str, str]]:
    ups = [f.powyzej_progu_ue] if f.powyzej_progu_ue is not None else [True, False]
    els = ["zaniechanie"] if f.zaniechanie else (
        ["elektroniczna"] if f.elektroniczna is True else ["inna"] if f.elektroniczna is False else ["elektroniczna", "inna"])
    out = []
    for up in ups:
        for e in els:
            t = cfg["terminy"]["powyzej_progu_ue" if up else "ponizej_progu_ue"][e]
            out.append((t["dni"], t["podstawa"], f"{'powyżej' if up else 'poniżej'} progów UE, {e}"))
    return out


def _deadlines(f: Facts, cfg: dict) -> list[tuple[date, str, int, str, str | None]]:
    res = []
    for dni, podst, opis in _term_candidates(f, cfg):
        d, note = compute_deadline(f.czynnosc_date, dni, cfg["shift_weekend_holiday"], cfg.get("wigilia_wolna_od_roku", 2025))
        res.append((d, podst, dni, opis, note))
    return res


def f1(f: Facts, cfg: dict) -> tuple[Kryterium, list]:
    sd = _sign_date(f)
    if f.czynnosc_date is None or sd is None:
        brak = "daty czynności" if f.czynnosc_date is None else "daty podpisu"
        return _k("F1", W, f"Brak {brak} — nie można obliczyć terminu.", f, "czynnosc_date", "signature_time"), []
    dls = _deadlines(f, cfg)
    v = _verdict([sd <= d[0] for d in dls])
    if len(dls) == 1:
        d, podst, dni, opis, note = dls[0]
        txt = f"Czynność {f.czynnosc_date}, termin {dni} dni ({podst}; {opis}) → {d}" + (f" ({note})" if note else "") + \
              f"; najwcześniejszy podpis {sd} — " + ("w terminie." if v else "po terminie.")
    else:
        txt = "Nieustalony tryb/próg (kilka interpretacji: " + "; ".join(f"{x[0]} [{x[3]}]" for x in dls) + f"); podpis {sd} — " + \
              ("w terminie przy każdej." if v else "po terminie przy każdej." if v is False else "wynik zależy od interpretacji.")
    return _k("F1", S if v else N if v is False else W, txt, f, "czynnosc_date", "signature_time"), dls


def f2(f: Facts, cfg: dict) -> tuple[Kryterium, float | None]:
    if f.wpis_wniesione is None or f.typ_zamowienia is None:
        return _k("F2", W, "Brak kwoty wpisu lub rodzaju zamówienia.", f, "wpis_wniesione", "typ_zamowienia"), None
    grp = cfg["wpis"]["roboty_budowlane" if f.typ_zamowienia == "roboty" else "dostawy_uslugi"]
    ups = [f.powyzej_progu_ue] if f.powyzej_progu_ue is not None else [True, False]
    req = [grp["powyzej_progu_ue" if u else "ponizej_progu_ue"] for u in ups]
    tol = cfg["wpis"]["tolerancja"]
    v = _verdict([abs(f.wpis_wniesione - r) <= tol for r in req])
    txt = f"Wymagany wpis {' / '.join(f'{r:,.2f}'.replace(',', ' ') for r in req)} zł ({f.typ_zamowienia}), wniesiono {f.wpis_wniesione:,.2f} zł".replace(",", " ")
    return _k("F2", S if v else N if v is False else W, txt + ".", f, "wpis_wniesione"), (req[0] if len(req) == 1 else None)


def f3(f: Facts, dls: list) -> Kryterium:
    if f.wpis_data is None or not dls:
        return _k("F3", W, "Brak daty przelewu wpisu lub terminu z F1.", f, "wpis_data")
    v = _verdict([f.wpis_data <= d[0] for d in dls])
    txt = f"Data przelewu {f.wpis_data}, termin graniczny {' / '.join(str(d[0]) for d in dls)}."
    return _k("F3", S if v else N if v is False else W, txt, f, "wpis_data")


def f4(f: Facts) -> Kryterium:
    if f.signature_valid is None:
        return _k("F4", W, "Nie zweryfikowano podpisu (brak podpisu lub format XAdES/CAdES — weryfikacja ręczna).", f, "signature_valid")
    if not f.signature_valid:
        return _k("F4", N, "Podpis nieważny (weryfikacja kryptograficzna negatywna).", f, "signature_valid")
    if f.signature_level in ("qualified", "trusted"):
        return _k("F4", S, f"Podpis ważny, poziom: {f.signature_level}.", f, "signature_valid")
    return _k("F4", W, "Podpis kryptograficznie ważny, ale nie ustalono, że jest kwalifikowany/zaufany "
                       "(brak weryfikacji zaufania certyfikatu) — do weryfikacji ręcznej.", f, "signature_valid")


def _in_organ(f: Facts, cfg: dict) -> tuple[bool | None, str]:
    """True/False/None (niepewne) + opis."""
    if not f.signer_name or not f.organ_members:
        return None, "brak imienia podpisującego lub składu organu"
    p, pn = cfg["dopasowanie_nazwisk"]["prog"], cfg["dopasowanie_nazwisk"]["prog_niepewny"]
    sc, who = best_match(f.signer_name, f.organ_members, p)
    if sc >= p:
        return True, f"{f.signer_name} ≈ {who} ({sc:.0f})"
    if sc >= pn:
        return None, f"{f.signer_name} podobny do {who} ({sc:.0f}) — niepewne dopasowanie"
    return False, f"{f.signer_name} nie występuje w składzie organu (najlepsze dopasowanie {sc:.0f})"


def f5(f: Facts, cfg: dict) -> tuple[Kryterium, bool | None]:
    inn, why = _in_organ(f, cfg)
    if inn is True:
        return _k("F5", S, f"Podpisujący w składzie organu: {why}.", f, "signer_name", "organ_members"), True
    if inn is None:
        return _k("F5", W, f"Nie można pewnie ustalić: {why}.", f, "signer_name", "organ_members"), None
    # nie w organie → pełnomocnictwo
    if f.pelnomocnictwo_zalaczone is False:
        return _k("F5", N, f"{why}; brak pełnomocnictwa.", f, "signer_name", "organ_members"), False
    if f.pelnomocnictwo_zalaczone and f.pelnomocnicy:
        p = cfg["dopasowanie_nazwisk"]["prog"]
        sc, who = best_match(f.signer_name, f.pelnomocnicy, p)
        if sc >= p:
            return _k("F5", S, f"{why}; wymieniony w pełnomocnictwie ({who}, {sc:.0f}).", f, "signer_name"), False
        if sc >= cfg["dopasowanie_nazwisk"]["prog_niepewny"]:
            return _k("F5", W, f"{why}; w pełnomocnictwie podobna osoba {who} ({sc:.0f}) — niepewne.", f, "signer_name"), False
        return _k("F5", N, f"{why}; w pełnomocnictwie brak podpisującego.", f, "signer_name"), False
    return _k("F5", W, f"{why}; pełnomocnictwo nieustalone lub bez odczytanych osób.", f, "signer_name"), False


def f6(f: Facts, cfg: dict, in_organ: bool | None) -> Kryterium:
    if in_organ is True:
        return _k("F6", D, "Podpisujący w składzie organu — pełnomocnictwo niewymagane.", f, "signer_name")
    if in_organ is None:
        return _k("F6", W, "Nie ustalono, czy podpisujący jest w składzie organu.", f, "signer_name")
    if f.pelnomocnictwo_zalaczone is True:
        return _k("F6", S, "Podpisujący spoza organu; pełnomocnictwo załączone.", f, "pelnomocnictwo_zalaczone")
    if f.pelnomocnictwo_zalaczone is False:
        return _k("F6", N, "Podpisujący spoza organu; brak pełnomocnictwa wśród dokumentów.", f, "pelnomocnictwo_zalaczone")
    return _k("F6", W, "Nie ustalono, czy pełnomocnictwo jest załączone.", f, "pelnomocnictwo_zalaczone")


def f7(f: Facts, cfg: dict, in_organ: bool | None) -> Kryterium:
    kwota = cfg["oplata_skarbowa_pelnomocnictwa"]
    if in_organ is True:
        return _k("F7", D, "Brak pełnomocnika — opłata skarbowa niewymagana.", f)
    if in_organ is None or f.pelnomocnictwo_zalaczone is not True:
        return _k("F7", W, f"Pełnomocnictwo nieustalone/niezałączone — opłata skarbowa {kwota} zł do weryfikacji ręcznej.", f)
    if f.oplata_skarbowa_found:
        return _k("F7", S, f"Znaleziono potwierdzenie opłaty skarbowej {kwota} zł.", f, "oplata_skarbowa_found")
    # brak dowodu ≠ pewny brak (możliwe zwolnienia) → ręcznie
    return _k("F7", W, f"Nie znaleziono przelewu opłaty skarbowej {kwota} zł (możliwe zwolnienie) — do weryfikacji ręcznej.", f, "oplata_skarbowa_found")


def f8(f: Facts) -> Kryterium:
    if f.dowod_kopii is None:
        return _k("F8", W, "Nie ustalono, czy załączono dowód przekazania kopii.", f, "dowod_kopii")
    return _k("F8", S if f.dowod_kopii else N, "Załączono dowód przekazania kopii odwołania zamawiającemu." if f.dowod_kopii
              else "Brak dowodu przekazania kopii odwołania zamawiającemu.", f, "dowod_kopii")


def _nonempty(fid: str, f: Facts, val: str | None, co: str, key: str) -> Kryterium:
    if val and val.strip():
        return _k(fid, S, f"{co}: wskazano.", f, key)
    if not f.text_quality_ok:
        return _k(fid, W, f"{co}: nie znaleziono, ale jakość tekstu (skan/OCR) jest niska — do weryfikacji ręcznej.", f, key)
    return _k(fid, N, f"{co}: brak w treści odwołania.", f, key)


def f12(f: Facts) -> Kryterium:
    brak = [n for n, v in (("nazwa", f.odw_nazwa), ("adres", f.odw_adres), ("NIP lub KRS", f.odw_nip or f.odw_krs)) if not v]
    if brak and f.text_quality_ok:
        return _k("F12", N, f"Brak danych odwołującego: {', '.join(brak)}.", f, "odw_nazwa")
    if brak:
        return _k("F12", W, f"Nie znaleziono: {', '.join(brak)} (niska jakość tekstu).", f, "odw_nazwa")
    if f.rejestr_potwierdzony is True:
        return _k("F12", S, "Nazwa, adres i NIP/KRS potwierdzone w rejestrze.", f, "rejestr_potwierdzony")
    return _k("F12", W, "Dane kompletne, ale niepotwierdzone w rejestrze (offline/brak odpowiedzi/rozbieżność).", f, "rejestr_potwierdzony")


def f13(f: Facts, cfg: dict) -> Kryterium:
    if f.postepowanie_start is None:
        return _k("F13", W, "Nie ustalono daty wszczęcia postępowania (F13 zależy od 13.03.2026).", f)
    zmiana = date.fromisoformat(str(cfg["data_zmiany_rezimu"]))
    if f.postepowanie_start < zmiana:
        return _k("F13", D, f"Postępowanie wszczęte {f.postepowanie_start} (przed {zmiana}).", f)
    if f.emails is None or f.ade is None:
        return _k("F13", W, "Nie ustalono adresów e-mail / do doręczeń elektronicznych.", f, "emails", "ade")
    ok = len(set(f.emails)) == 1 and len(set(f.ade)) == 1
    return _k("F13", S if ok else N, f"Adresów e-mail: {len(set(f.emails))}, adresów do doręczeń elektronicznych: {len(set(f.ade))} (wymagany dokładnie 1 i 1).",
              f, "emails", "ade")


def _k(fid: str, st: StatusReguly, why: str, f: Facts, *keys: str) -> Kryterium:
    return Kryterium(id=fid, nazwa=NAZWY[fid], status=st, uzasadnienie=why, source=_src(f, *keys))


# ───────────────────────── całość ─────────────────────────


def evaluate(f: Facts, cfg: dict) -> RulesResult:
    k1, dls = f1(f, cfg)
    k2, wpis_req = f2(f, cfg)
    k3 = f3(f, dls)
    k5, in_organ = f5(f, cfg)
    ks = [k1, k2, k3, f4(f), k5, f6(f, cfg, in_organ), f7(f, cfg, in_organ), f8(f),
          _nonempty("F9", f, f.czynnosc_opis, "Czynność/zaniechanie", "czynnosc_opis"),
          _nonempty("F10", f, f.zadanie, "Żądanie", "zadanie"),
          _nonempty("F11", f, f.okolicznosci, "Okoliczności faktyczne i prawne", "okolicznosci"),
          f12(f), f13(f, cfg)]
    braki = [f"{k.id}: {k.nazwa} — {k.uzasadnienie}" for k in ks if k.status == N]
    uniq = {d[0] for d in dls}
    podst = {d[1] for d in dls}
    return RulesResult(ks, bool(braki), braki, termin=uniq.pop() if len(uniq) == 1 else None,
                       termin_ustawowy=(f"{dls[0][2]} dni ({dls[0][1]})" if len(podst) == 1 and dls else None), wpis_wymagany=wpis_req)
