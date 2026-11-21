"""Pipeline: PDF -> tekst (OCR) -> klasyfikacja -> reguły + LLM -> walidacja -> JSON + ślad."""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .classify import classify
from .config import DocClass, load_classes, load_settings
from .extract import extract
from .llm import LLMClient, LLMError
from .textract import load_pdf

log = logging.getLogger("odw2json")


@dataclass
class Result:
    input: Path
    doc_class: str | None
    data: dict | None
    trace: dict = field(default_factory=dict)

    def to_trace(self) -> dict:
        return {"plik": str(self.input.name), "klasa": self.doc_class, **self.trace}


class Engine:
    def __init__(self, settings: dict | None = None, classes: list[DocClass] | None = None,
                 use_llm: bool | None = None):
        self.settings = settings or load_settings()
        self.classes = classes or load_classes()
        llm_cfg = dict(self.settings.get("llm", {}))
        if use_llm is not None:
            llm_cfg["enabled"] = use_llm
        self.llm = LLMClient(llm_cfg)
        self.by_name = {c.name: c for c in self.classes}

    def process(self, pdf: Path) -> Result:
        t0 = time.time()
        doc = load_pdf(pdf, self.settings)
        cl = classify(doc.text, pdf.name, self.classes,
                      int(self.settings.get("classify_head_chars", 6000)))
        tr = {"klasyfikacja": {"wynik": cl.name, "punkty": cl.scores, "trafienia": cl.hits.get(cl.name, [])},
              "strony": len(doc.pages), "ocr_strony": doc.ocr_pages, "ostrzezenia": doc.warnings}
        if cl.name is None:
            tr["czas_s"] = round(time.time() - t0, 2)
            return Result(pdf, None, None, tr)
        cls = self.by_name[cl.name]
        llm_json, llm_err, llm_meta = None, None, None
        if self.llm.enabled:
            try:
                max_chars = int(self.settings.get("llm", {}).get("max_doc_chars", 24000))
                llm_json, llm_meta = self.llm.extract(cls, doc.numbered_text(max_chars))
            except LLMError as e:
                llm_err = str(e)[:300]
                log.warning("%s: LLM niedostępny, używam samych reguł", pdf.name)
        data, fields, meta = extract(doc, cls, llm_json, llm_err)
        tr.update(meta)
        if llm_meta:
            tr["llm"] = llm_meta
        tr["pola"] = fields
        tr["czas_s"] = round(time.time() - t0, 2)
        return Result(pdf, cl.name, data, tr)


def iter_cases(input_dir: Path):
    """Zwraca pary (nazwa_sprawy, [pdf...]). PDF-y bezpośrednio w input/ trafiają do sprawy '.'."""
    input_dir = Path(input_dir)
    loose = sorted(p for p in input_dir.glob("*") if p.suffix.lower() == ".pdf")
    if loose:
        yield ".", loose
    for d in sorted(p for p in input_dir.iterdir() if p.is_dir()):
        pdfs = sorted(p for p in d.rglob("*") if p.suffix.lower() == ".pdf")
        if pdfs:
            yield d.name, pdfs


def run(input_dir: Path, output_dir: Path, trace_dir: Path | None = None, use_llm: bool | None = None,
        workers: int | None = None) -> list[Result]:
    eng = Engine(use_llm=use_llm)
    output_dir, input_dir = Path(output_dir), Path(input_dir)
    jobs = [(case, pdf) for case, pdfs in iter_cases(input_dir) for pdf in pdfs]
    workers = workers or int(eng.settings.get("workers", 4))
    log.info("Plików PDF: %d, LLM: %s", len(jobs), "tak" if eng.llm.enabled else "NIE (tylko reguły)")

    def one(job):
        case, pdf = job
        try:
            return case, eng.process(pdf)
        except Exception as e:  # noqa: BLE001 - jeden zły plik nie zatrzymuje całej partii
            log.exception("Błąd przetwarzania %s", pdf)
            return case, Result(pdf, None, None, {"blad": str(e)})

    results = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for case, res in ex.map(one, jobs):
            rel = res.input.relative_to(input_dir).with_suffix(".json")
            if res.data is not None:
                out = output_dir / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(res.data, ensure_ascii=False, indent=2), encoding="utf-8")
                log.info("%-45s -> %-15s %s", str(rel.with_suffix(".pdf")), res.doc_class, out)
            else:
                log.info("%-45s -> pominięty (nierozpoznany typ dokumentu)", str(rel.with_suffix(".pdf")))
            if trace_dir:
                t = Path(trace_dir) / rel.with_suffix(".trace.json")
                t.parent.mkdir(parents=True, exist_ok=True)
                t.write_text(json.dumps(res.to_trace(), ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(res)
    return results
