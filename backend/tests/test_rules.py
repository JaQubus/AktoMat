import json
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from app.models.karta import StatusReguly as SR
from pipeline.rules import Facts, evaluate, load_config, name_score

ROOT = Path(__file__).resolve().parents[2]
CFG = load_config(ROOT / "config" / "rules.yaml")
S, N, D, W = SR.spelnione, SR.niespelnione, SR.nie_dotyczy, SR.do_weryfikacji


def utc(y, m, d, h=9, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def good(**kw) -> Facts:
    base = dict(
        czynnosc_date=date(2025, 12, 30), powyzej_progu_ue=True, elektroniczna=True,
        signature_time=utc(2026, 1, 8), signature_valid=True, signature_level="qualified",
        signer_name="Jan Kowalski", typ_zamowienia="uslugi", wpis_wniesione=15000.0, wpis_data=date(2026, 1, 8),
        organ_members=["Jan Kowalski"], pelnomocnictwo_zalaczone=False, dowod_kopii=True,
        czynnosc_opis="odrzucenie oferty", zadanie="unieważnienie", okolicznosci="uzasadnienie",
        odw_nazwa="X sp. z o.o.", odw_adres="ul. A 1", odw_nip="5252001234", rejestr_potwierdzony=True,
        postepowanie_start=date(2025, 12, 1))
    base.update(kw)
    return Facts(**base)


def st(f: Facts, fid: str, cfg=CFG):
    return {k.id: k.status for k in evaluate(f, cfg).kryteria}[fid]


def test_all_good_no_braki():
    r = evaluate(good(), CFG)
    assert not r.braki_formalne and r.lista_brakow == []
    assert {k.id: k.status for k in r.kryteria} == {
        "F1": S, "F2": S, "F3": S, "F4": S, "F5": S, "F6": D, "F7": D, "F8": S, "F9": S, "F10": S, "F11": S, "F12": S, "F13": D}
    assert r.termin == date(2026, 1, 9) and r.termin_ustawowy.startswith("10 dni") and r.wpis_wymagany == 15000.0


# F1
def test_f1_last_day_ok_and_day_after_late():
    assert st(good(signature_time=utc(2026, 1, 9, 12)), "F1") == S
    assert st(good(signature_time=utc(2026, 1, 12, 12)), "F1") == N  # 10.01 sobota nie dotyczy: termin 9.01 (piątek)


def test_f1_saturday_deadline_monday_submission():
    f = good(czynnosc_date=date(2026, 1, 14), signature_time=utc(2026, 1, 26, 8))
    assert st(f, "F1") == S
    cfg = deepcopy(CFG)
    cfg["shift_weekend_holiday"] = False
    assert st(f, "F1", cfg) == N


def test_f1_movable_holiday_corpus_christi():
    f = good(czynnosc_date=date(2026, 5, 25), signature_time=utc(2026, 6, 5, 10))
    assert st(f, "F1") == S  # 4.06 Boże Ciało → 5.06
    assert st(good(czynnosc_date=date(2026, 5, 25), signature_time=utc(2026, 6, 8, 10)), "F1") == N


def test_f1_uses_warsaw_date_for_signature_time():
    # 23:30 UTC 9.01 = 0:30 czasu polskiego 10.01 → po terminie (piątek 9.01)
    assert st(good(signature_time=utc(2026, 1, 9, 23, 30)), "F1") == N


def test_f1_other_notification_gives_15_days():
    assert st(good(elektroniczna=False, signature_time=utc(2026, 1, 13)), "F1") == S
    assert st(good(signature_time=utc(2026, 1, 13)), "F1") == N


def test_f1_below_threshold_5_days():
    assert st(good(powyzej_progu_ue=False, signature_time=utc(2026, 1, 6)), "F1") == N
    assert st(good(powyzej_progu_ue=False, signature_time=utc(2026, 1, 5)), "F1") == S


def test_f1_zaniechanie():
    assert st(good(zaniechanie=True, signature_time=utc(2026, 1, 9)), "F1") == S


def test_f1_unknown_mode_ambiguous_is_manual_not_failed():
    assert st(good(elektroniczna=None, signature_time=utc(2026, 1, 12)), "F1") == W  # po 10 dniach, przed 15
    assert st(good(elektroniczna=None, signature_time=utc(2026, 2, 20)), "F1") == N  # po obu
    assert st(good(elektroniczna=None), "F1") == S  # w obu


def test_f1_missing_data_manual():
    assert st(good(czynnosc_date=None), "F1") == W
    assert st(good(signature_time=None), "F1") == W


# F2
@pytest.mark.parametrize("typ,up,kwota,exp", [
    ("uslugi", True, 15000, S), ("uslugi", True, 7500, N), ("dostawy", False, 7500, S), ("dostawy", False, 15000, N),
    ("roboty", True, 20000, S), ("roboty", True, 15000, N), ("roboty", False, 10000, S), ("roboty", False, 20000, N)])
def test_f2_amounts(typ, up, kwota, exp):
    assert st(good(typ_zamowienia=typ, powyzej_progu_ue=up, wpis_wniesione=float(kwota)), "F2") == exp


def test_f2_wrong_amount_sets_braki():
    r = evaluate(good(wpis_wniesione=7500.0), CFG)
    assert r.braki_formalne and r.lista_brakow[0].startswith("F2")


def test_f2_unknown_threshold_with_7500_is_manual():
    assert st(good(powyzej_progu_ue=None, wpis_wniesione=7500.0), "F2") == W
    assert st(good(wpis_wniesione=None), "F2") == W


# F3
def test_f3_deadline_day_ok_and_late_fails():
    assert st(good(wpis_data=date(2026, 1, 9)), "F3") == S
    assert st(good(wpis_data=date(2026, 1, 12)), "F3") == N
    assert st(good(wpis_data=None), "F3") == W


# F4
def test_f4_levels():
    assert st(good(signature_level="trusted"), "F4") == S
    assert st(good(signature_level="unqualified"), "F4") == W  # niepewne ≠ niespełnione
    assert st(good(signature_valid=False), "F4") == N
    assert st(good(signature_valid=None), "F4") == W  # np. XAdES


# F5/F6/F7
def test_f5_initials_in_name():
    assert st(good(signer_name="J. Kowalski"), "F5") == S
    assert st(good(signer_name="Kowalski Jan"), "F5") == S


def test_f5_diacritics_and_double_surname():
    f = good(signer_name="Ewelina Kozlowska Mazur", organ_members=["Ewelina Kozłowska-Mazur"])
    assert st(f, "F5") == S
    assert name_score("Łukasz Żurawski", "Lukasz Zurawski") >= 85


def test_f5_similar_but_different_given_name_is_manual():
    assert st(good(signer_name="Janusz Kowalski"), "F5") == W  # Jan ≠ Janusz — niepewne, nie „niespełnione”


def test_f5_prokurent_not_in_organ_without_power_of_attorney():
    f = good(signer_name="Marek Zieliński", organ_members=["Anna Wiśniewska"])
    r = {k.id: k.status for k in evaluate(f, CFG).kryteria}
    assert r["F5"] == N and r["F6"] == N and r["F7"] == W
    assert evaluate(f, CFG).braki_formalne


def test_f5_f6_f7_with_power_of_attorney():
    f = good(signer_name="Marek Zieliński", organ_members=["Anna Wiśniewska"], pelnomocnictwo_zalaczone=True,
             pelnomocnicy=["Marek Zieliński"], oplata_skarbowa_found=True)
    r = {k.id: k.status for k in evaluate(f, CFG).kryteria}
    assert (r["F5"], r["F6"], r["F7"]) == (S, S, S)
    f.pelnomocnicy = ["Zofia Inna"]
    assert st(f, "F5") == N
    f.pelnomocnicy = None
    assert st(f, "F5") == W
    g = good(signer_name="Marek Zieliński", organ_members=["Anna Wiśniewska"], pelnomocnictwo_zalaczone=True,
             pelnomocnicy=["Marek Zieliński"], oplata_skarbowa_found=False)
    assert st(g, "F7") == W


def test_f5_unknown_organ_is_manual():
    assert st(good(organ_members=None), "F5") == W
    assert st(good(organ_members=None), "F6") == W


# F8–F12
def test_f8():
    assert st(good(dowod_kopii=False), "F8") == N and st(good(dowod_kopii=None), "F8") == W


@pytest.mark.parametrize("fid,field", [("F9", "czynnosc_opis"), ("F10", "zadanie"), ("F11", "okolicznosci")])
def test_f9_f10_f11(fid, field):
    assert st(good(**{field: None}), fid) == N
    assert st(good(**{field: "  "}), fid) == N
    assert st(good(**{field: None, "text_quality_ok": False}), fid) == W  # słaby skan ≠ pewny brak


def test_f12():
    assert st(good(odw_nip=None, odw_krs=None), "F12") == N
    assert st(good(odw_krs="0000123456", odw_nip=None), "F12") == S
    assert st(good(rejestr_potwierdzony=None), "F12") == W  # offline


# F13
def test_f13():
    after = date(2026, 3, 13)
    assert st(good(postepowanie_start=date(2026, 3, 12)), "F13") == D
    assert st(good(postepowanie_start=after, emails=["a@x.pl"], ade=["AE:PL-1"]), "F13") == S
    assert st(good(postepowanie_start=after, emails=["a@x.pl", "b@x.pl"], ade=["AE:PL-1"]), "F13") == N
    assert st(good(postepowanie_start=after, emails=["a@x.pl"], ade=[]), "F13") == N
    assert st(good(postepowanie_start=after, emails=None, ade=None), "F13") == W
    assert st(good(postepowanie_start=None), "F13") == W


def test_no_hardcoded_amounts_config_drives_rules():
    cfg = deepcopy(CFG)
    cfg["wpis"]["dostawy_uslugi"]["powyzej_progu_ue"] = 16000
    assert st(good(), "F2", cfg) == N


# integracja z danymi syntetycznymi
SYNTH = ROOT / "data" / "synthetic"
CASES = sorted(p.name[:-len(".rules.yaml")] for p in (SYNTH / "ground_truth").glob("*.rules.yaml")) if SYNTH.exists() else []


def facts_from_ground_truth(cid: str) -> Facts:
    a = yaml.safe_load((SYNTH / "ground_truth" / f"{cid}.yaml").read_text(encoding="utf-8"))["assert"]
    krs = json.loads((SYNTH / "krs_mock" / f"{a['odwolujacy.krs']}.json").read_text(encoding="utf-8"))
    sklad = krs["odpis"]["dane"]["dzial2"]["reprezentacja"]["sklad"]
    organ = [f"{m['imiona']['imie']} {m['imiona'].get('imieDrugie', '')} {m['nazwisko']['nazwiskoICzlon']}".replace("  ", " ") for m in sklad]
    return Facts(
        czynnosc_date=date.fromisoformat(a["weryfikacja.data_czynnosci"]), powyzej_progu_ue=True, elektroniczna=True,
        signature_time=datetime.fromisoformat(a["reprezentacja.podpisujacy.data_podpisu"].replace("Z", "+00:00")),
        signature_valid=a["reprezentacja.podpisujacy.podpis_wazny"],
        signature_level="qualified" if a["reprezentacja.podpisujacy.typ_podpisu"] == "kwalifikowany" else "unknown",
        signer_name=a["reprezentacja.podpisujacy.imie_nazwisko"],
        typ_zamowienia={"Dostawy": "dostawy", "Usługi": "uslugi", "Roboty budowlane": "roboty"}[a["informacje_ogolne.zamowienie"].split(":")[0]],
        wpis_wniesione=a["informacje_ogolne.wpis.wniesione"], wpis_data=date.fromisoformat(a["informacje_ogolne.wpis.data_wplaty"]),
        organ_members=organ, pelnomocnictwo_zalaczone=False, dowod_kopii=a["weryfikacja.dowod_przekazania_kopii"],
        czynnosc_opis="x", zadanie="x", okolicznosci="x", odw_nazwa=a["odwolujacy.nazwa"], odw_adres=a["odwolujacy.adres.ulica"],
        odw_nip=a["odwolujacy.nip"], odw_krs=a["odwolujacy.krs"], rejestr_potwierdzony=True, postepowanie_start=date(2025, 12, 1))


@pytest.mark.skipif(not CASES, reason="uruchom: make synth")
@pytest.mark.parametrize("cid", CASES)
def test_synthetic_cases_match_expected_rules(cid):
    exp = yaml.safe_load((SYNTH / "ground_truth" / f"{cid}.rules.yaml").read_text(encoding="utf-8"))
    gt = yaml.safe_load((SYNTH / "ground_truth" / f"{cid}.yaml").read_text(encoding="utf-8"))["assert"]
    r = evaluate(facts_from_ground_truth(cid), CFG)
    assert {k.id: k.status.value for k in r.kryteria} == exp["kryteria"]
    assert r.braki_formalne == gt["weryfikacja.braki_formalne"]
    assert r.termin.isoformat() == gt["weryfikacja.termin_wyliczony"]
    assert r.termin_ustawowy == gt["weryfikacja.termin_ustawowy"]
    assert r.wpis_wymagany == gt["informacje_ogolne.wpis.wymagane"]
