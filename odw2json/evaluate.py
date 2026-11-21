"""Ewaluacja F1 wg zasad ogłoszonych przez UZP (Discord, 2026-11-21):

  TP - wartość jest w JSON i zgadza się z wzorcem (długie napisy: podobieństwo >= 80%)
  TN - wartości nie ma ani w JSON, ani we wzorcu
  FP - wartość jest tylko w JSON, albo jest w obu, ale jest błędna
  FN - wartości nie ma w JSON, a jest we wzorcu
  F1 = 2TP / (2TP + FP + FN)

Porównanie liść po liściu (listy wyrównane po indeksie). Raport per pole, per klasa i lista błędów.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz

from . import paths
from .normalize import ws

LONG_STRING = 15        # od tej długości stosujemy dopasowanie przybliżone
SIMILARITY = 80         # próg zgodności dla długich napisów (%)

# nazwa pliku PDF w zbiorze treningowym -> oczekiwana klasa (tylko do raportu klasyfikacji)
EXPECTED_CLASS = {"odwolanie": "odwolanie", "pelnomocnictwo": "pelnomocnictwo",
                  "potwierdzenie_przelewu": "przelew", "przelew": "przelew"}


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def values_match(pred, gt) -> bool:
    if isinstance(gt, bool) or isinstance(pred, bool):
        return pred == gt
    if isinstance(gt, (int, float)) and not isinstance(gt, bool):
        try:
            return abs(float(str(pred).replace(",", ".")) - float(gt)) < 0.005
        except ValueError:
            return False
    p, g = ws(str(pred)), ws(str(gt))
    if p == g:
        return True
    if re.fullmatch(r"[\d\s-]+", g) and re.sub(r"\D", "", p) == re.sub(r"\D", "", g):
        return True  # te same cyfry (np. PESEL zapisany jako liczba vs napis)
    if len(g) >= LONG_STRING:
        return fuzz.ratio(p.lower(), g.lower()) >= SIMILARITY
    return False


def compare(pred: dict | None, gt: dict) -> list[tuple[str, str, object, object]]:
    """Zwraca listę (ścieżka, wynik TP/FP/FN/TN, pred, gt)."""
    gl = dict(paths.leaves(gt))
    pl = dict(paths.leaves(pred)) if pred else {}
    out = []
    for p in list(gl) + [p for p in pl if p not in gl]:
        g, v = gl.get(p), pl.get(p)
        if _empty(g) and _empty(v):
            r = "TN"
        elif _empty(v):
            r = "FN"
        elif _empty(g):
            r = "FP"
        else:
            r = "TP" if values_match(v, g) else "FP"
        out.append((p, r, v, g))
    return out


def f1(c: dict) -> float:
    d = 2 * c["TP"] + c["FP"] + c["FN"]
    return 2 * c["TP"] / d if d else 1.0


def run_eval(gt_dir: Path, pred_dir: Path | None, report_dir: Path, use_llm=None, workers=None):
    gt_dir = Path(gt_dir)
    tmp = None
    if pred_dir is None:
        from .pipeline import run

        tmp = Path(tempfile.mkdtemp(prefix="odw2json_eval_"))
        results = run(gt_dir, tmp / "out", tmp / "trace", use_llm=use_llm, workers=workers)
        cls_of = {(r.input.parent.name, r.input.stem): r.doc_class for r in results}
        pred_dir = tmp / "out"
    else:
        cls_of = None

    total = defaultdict(int)
    per_class = defaultdict(lambda: defaultdict(int))
    per_field = defaultdict(lambda: defaultdict(int))
    errors, cls_ok, cls_all, cls_errors = [], 0, 0, []
    for case in sorted(p for p in gt_dir.iterdir() if p.is_dir()):
        preds = {}
        for pdf in sorted(case.glob("*.pdf")):
            expected = EXPECTED_CLASS.get(pdf.stem)   # None = dokument negatywny (nie powinien mieć klasy)
            got = cls_of.get((case.name, pdf.stem)) if cls_of is not None else None
            pj = pred_dir / case.name / f"{pdf.stem}.json"
            data = None
            if pj.exists():
                raw = pj.read_text(encoding="utf-8").strip()
                data = json.loads(raw) if raw else {}
            if cls_of is None:
                got = expected if data else None  # gotowe predykcje: klasa z nazwy pliku, pusty JSON = brak klasy
            cls_all += 1
            cls_ok += got == expected
            if got != expected:
                cls_errors.append(f"{case.name}/{pdf.name}: oczekiwano {expected}, jest {got}")
            if expected is None:
                # negatyw z wartościami = każda niepusta wartość to FP
                for path, v in (paths.leaves(data) if data else []):
                    if not _empty(v):
                        total["FP"] += 1
                        per_class["negatywne"]["FP"] += 1
                        errors.append({"sprawa": case.name, "klasa": "negatywne", "pole": f"{pdf.name}:{path}",
                                       "wynik": "FP", "predykcja": v, "wzorzec": None})
                if not data:
                    per_class["negatywne"]["TN"] += 1
                continue
            if got == expected and data:
                preds[got] = data
        for gj in sorted(case.glob("*.json")):
            klass = gj.stem
            gt = json.loads(gj.read_text(encoding="utf-8"))
            for path, r, v, g in compare(preds.get(klass), gt):
                total[r] += 1
                per_class[klass][r] += 1
                per_field[f"{klass}:{paths.generic(path)}"][r] += 1
                if r in ("FP", "FN"):
                    errors.append({"sprawa": case.name, "klasa": klass, "pole": path, "wynik": r,
                                   "predykcja": v, "wzorzec": g})

    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Raport jakości ekstrakcji", "",
             f"**F1 = {f1(total):.4f}**  (TP={total['TP']}, FP={total['FP']}, FN={total['FN']}, TN={total['TN']})",
             f"Klasyfikacja: {cls_ok}/{cls_all} poprawnie", "", "## Per klasa", "",
             "| klasa | F1 | TP | FP | FN | TN |", "|---|---|---|---|---|---|"]
    for k, c in sorted(per_class.items()):
        lines.append(f"| {k} | {f1(c):.3f} | {c['TP']} | {c['FP']} | {c['FN']} | {c['TN']} |")
    lines += ["", "## Per pole (najsłabsze na górze)", "",
              "| pole | F1 | TP | FP | FN | TN |", "|---|---|---|---|---|---|"]
    for k, c in sorted(per_field.items(), key=lambda kv: f1(kv[1])):
        lines.append(f"| {k} | {f1(c):.3f} | {c['TP']} | {c['FP']} | {c['FN']} | {c['TN']} |")
    if cls_errors:
        lines += ["", "## Błędy klasyfikacji", ""] + [f"- {e}" for e in cls_errors]
    (report_dir / "raport.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(report_dir / "bledy.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["sprawa", "klasa", "pole", "wynik", "predykcja", "wzorzec"])
        w.writeheader()
        w.writerows(errors)
    summary = {"f1": round(f1(total), 4), **total,
               "per_klasa": {k: round(f1(c), 4) for k, c in per_class.items()},
               "klasyfikacja": f"{cls_ok}/{cls_all}"}
    (report_dir / "wynik.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(lines[:5 + len(per_class) + 4]))
    print(f"\nPełny raport: {report_dir / 'raport.md'}, błędy: {report_dir / 'bledy.csv'}")
    if tmp:
        shutil.copytree(tmp / "trace", report_dir / "trace", dirs_exist_ok=True)
        shutil.copytree(pred_dir, report_dir / "predykcje", dirs_exist_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
    return summary
