"""CLI.

  python -m odw2json                      # input/ -> output/ (ślad w trace/)
  python -m odw2json run -i input -o output [--no-llm]
  python -m odw2json eval --gt <dane> [--no-llm]    # F1 na zbiorze treningowym UZP
  python -m odw2json web                  # GUI na http://127.0.0.1:8000
  python -m odw2json classes              # lista skonfigurowanych klas dokumentów
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import ROOT


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="odw2json", description="Odwołania KIO: PDF -> JSON")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="przetwórz katalog input/ do output/")
    r.add_argument("-i", "--input", default=str(ROOT / "input"))
    r.add_argument("-o", "--output", default=str(ROOT / "output"))
    r.add_argument("-t", "--trace", default=str(ROOT / "trace"), help="katalog śladu ekstrakcji ('' = brak)")
    r.add_argument("--no-llm", action="store_true", help="tylko reguły, bez LLM")
    r.add_argument("-w", "--workers", type=int)
    e = sub.add_parser("eval", help="policz F1 względem wzorcowych JSON-ów")
    e.add_argument("--gt", required=True, help="katalog z przyklad_XX/{*.pdf,*.json}")
    e.add_argument("--pred", help="gotowe predykcje (pomija uruchamianie pipeline'u)")
    e.add_argument("--no-llm", action="store_true")
    e.add_argument("--report", default=str(ROOT / "eval_report"))
    e.add_argument("-w", "--workers", type=int)
    w = sub.add_parser("web", help="GUI w przeglądarce")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8000)
    sub.add_parser("classes", help="lista klas dokumentów")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cmd = args.cmd or "run"
    if cmd == "run":
        from .pipeline import run

        if args.cmd is None:
            args = r.parse_args([])
        res = run(Path(args.input), Path(args.output), Path(args.trace) if args.trace else None,
                  use_llm=False if args.no_llm else None, workers=args.workers)
        ok = sum(1 for x in res if x.data is not None)
        print(f"Gotowe: {ok}/{len(res)} plików zapisanych do {args.output}")
    elif cmd == "eval":
        from .evaluate import run_eval

        run_eval(Path(args.gt), Path(args.pred) if args.pred else None, Path(args.report),
                 use_llm=False if args.no_llm else None, workers=args.workers)
    elif cmd == "web":
        import uvicorn

        uvicorn.run("odw2json.web:app", host=args.host, port=args.port)
    elif cmd == "classes":
        from .config import load_classes

        for c in load_classes():
            print(f"{c.name:16} {len(c.fields):3} pól  {c.source.name}  — {c.description}")


if __name__ == "__main__":
    main()
