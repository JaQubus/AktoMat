from odw2json.evaluate import compare, f1, values_match
from odw2json.rules import apply_rules

TEXT = """Lublin, dnia 9 listopada 2026 roku
Odwołujący:
Corvantis Wyposażenie sp. z o.o.
ul. Orzechowa 31, 20-174 Lublin
reprezentowana przez: r. pr. Ignacy Sadowski, adw. Jan Kowal
Zamawiający:
Belmoria S.A.
Zamawiający w dniu 18 września 2026 r. wzywał wykonawcę do wyjaśnień ceny. Zamawiający w dniu 25 października 2026 roku nie odrzucił oferty złożonej przez konkurenta. Uprzednio, w dniu 1 października 2026 r. coś się stało.
"""

MAP = [{"pattern": "zaniecha\\w*\\s+odrzuc|nie\\s+odrzuci", "value": 7}, {"pattern": "odrzuc", "value": 1}]


def test_sentence_map_skips_earlier_summons():
    rule = {"kind": "sentence_map", "anchor": r"Zamawiający\s+w\s+dniu\s+(?P<v>\d{1,2}\s+\w+\s+\d{4})",
            "skip": "wezwał|wzywał", "map": MAP}
    assert apply_rules([rule], TEXT, {}).value == 7
    assert apply_rules([{**rule, "return": "match"}], TEXT, {}).value == "25 października 2026"


def test_sections_and_titled_persons():
    sections = {"odw": {"start": r"(?m)^Odwołujący:", "end": r"(?m)^Zamawiający:", "flags": ""}}
    hit = apply_rules([{"kind": "titled_persons", "section": "odw", "all": True}], TEXT, sections)
    assert hit.value == ["Ignacy Sadowski", "Jan Kowal"]
    hit = apply_rules([{"kind": "entity_name", "section": "odw"}], TEXT, sections)
    assert hit.value == "Corvantis Wyposażenie sp. z o.o."


def test_uzp_f1_definition():
    gt = {"a": "X", "b": None, "c": "Kancelaria Prawna i Partnerzy", "d": "1"}
    pred = {"a": "X", "b": "oops", "c": "Kancelaria Prawna Partnerzy", "d": None}
    res = {p: r for p, r, _, _ in compare(pred, gt)}
    assert res == {"a": "TP", "b": "FP", "c": "TP", "d": "FN"}  # c: >=80% podobieństwa
    assert round(f1({"TP": 2, "FP": 1, "FN": 1}), 4) == round(4 / 6, 4)
    assert values_match("85071204278", "85071204278")
    assert values_match(100, 100.0)
