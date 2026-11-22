"""Ładowanie konfiguracji: config/settings.yaml, config/classes/*.yaml i zmienne z .env.

Nowa klasa dokumentu = nowy plik YAML w config/classes/ (bez zmian w kodzie).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(os.environ.get("ODW2JSON_CONFIG", ROOT / "config"))


def _load_env():
    try:
        from dotenv import load_dotenv

        # kolejność: ODW2JSON_ENV, .env w bieżącym katalogu (np. /opt/solution/.env na VM UZP), .env w repo
        for env in (os.environ.get("ODW2JSON_ENV"), Path.cwd() / ".env", ROOT / ".env"):
            if env and Path(env).is_file():
                load_dotenv(env)
    except ImportError:
        pass


@dataclass
class FieldSpec:
    path: str                      # np. "Odwolujacy[*].nip"
    type: str = "string"
    description: str = ""
    rules: list = field(default_factory=list)
    prefer: str | None = None      # llm | rules; brak = `prefer` klasy (domyślnie llm)
    derive: dict | None = None     # pole wyliczane z innych pól
    require_grounding: bool = True  # wartość musi występować w tekście
    default: object = None
    cast: str | None = None        # wymuszenie typu w JSON: str | int | float
    vocabulary: str | list | None = None  # słownik poprawnych zapisów (lista albo plik w config/), np. miejscowości z ogonkami


def load_vocabulary(spec) -> dict:
    """Słownik zapisów kanonicznych: klucz = forma bez ogonków i wielkości liter."""
    from .normalize import fold
    if not spec:
        return {}
    items = spec if isinstance(spec, list) else [
        ln.strip() for ln in (CONFIG_DIR / spec).read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")]
    return {fold(x): x for x in items}


@dataclass
class DocClass:
    name: str
    description: str
    output_template: dict
    fields: list[FieldSpec]
    classify: dict
    sections: dict
    enums: dict
    llm_instructions: str
    list_templates: dict           # "Odwolujacy" -> szablon elementu listy
    source: Path
    lists: dict = field(default_factory=dict)  # podział sekcji na bloki = elementy listy (wiele podmiotów)
    ocr_layout: str | None = None  # odczyt skanu: None = wierszami, "columns" = kolumny jedna po drugiej

    def field(self, path: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.path == path), None)


def load_settings() -> dict:
    _load_env()
    p = CONFIG_DIR / "settings.yaml"
    s = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    llm = s.setdefault("llm", {})
    llm["base_url"] = os.environ.get("LLM_BASE_URL", llm.get("base_url"))
    llm["model"] = os.environ.get("LLM_MODEL", llm.get("model"))
    llm["api_key"] = os.environ.get("LLM_API_KEY")
    # LLM_PROFILE=groq -> GROQ_BASE_URL / GROQ_MODEL / GROQ_API_KEY (domyślne z settings.yaml llm.profiles.groq);
    # zwykłe LLM_* zostają w .env obok i wracają po usunięciu LLM_PROFILE.
    name = (os.environ.get("LLM_PROFILE") or "").strip()
    if name:
        prof = dict((llm.get("profiles") or {}).get(name.lower(), {}))
        env = lambda k: os.environ.get(f"{name.upper()}_{k}")
        # pozostałe klucze profilu (np. max_tokens, max_doc_chars pod limity darmowego planu) nadpisują llm
        llm.update({k: v for k, v in prof.items() if k not in ("base_url", "model", "api_key")})
        llm["base_url"] = env("BASE_URL") or prof.get("base_url") or llm["base_url"]
        llm["model"] = env("MODEL") or prof.get("model") or llm["model"]
        llm["api_key"] = env("API_KEY") or llm["api_key"]
        llm["profile"] = name.lower()
    llm.pop("profiles", None)
    if os.environ.get("LLM_ENABLED") is not None:
        llm["enabled"] = os.environ["LLM_ENABLED"].strip() not in ("0", "false", "no", "")
    if os.environ.get("OCR_ENGINE"):
        s.setdefault("ocr", {})["engine"] = os.environ["OCR_ENGINE"]
    if os.environ.get("TESSERACT_CMD"):
        s.setdefault("ocr", {})["tesseract_cmd"] = os.environ["TESSERACT_CMD"]
    return s


def _list_templates(tpl, prefix="", out=None):
    out = {} if out is None else out
    if isinstance(tpl, dict):
        for k, v in tpl.items():
            _list_templates(v, f"{prefix}.{k}" if prefix else k, out)
    elif isinstance(tpl, list) and tpl:
        out[prefix] = tpl[0]
        _list_templates(tpl[0], f"{prefix}[*]", out)
    return out


def load_classes(classes_dir: Path | None = None) -> list[DocClass]:
    d = Path(classes_dir or CONFIG_DIR / "classes")
    out = []
    for p in sorted(d.glob("*.y*ml")):
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not raw or raw.get("enabled", True) is False:
            continue
        fields = [FieldSpec(**f) for f in raw.get("fields", [])]
        for f in fields:
            f.prefer = f.prefer or raw.get("prefer", "llm")
        tpl = raw["output_template"]
        out.append(DocClass(
            name=raw["name"],
            description=raw.get("description", ""),
            output_template=tpl,
            fields=fields,
            classify=raw.get("classify", {}),
            sections=raw.get("sections", {}),
            enums={k: {int(i) if str(i).isdigit() else i: v for i, v in e.items()}
                   for k, e in (raw.get("enums") or {}).items()},
            llm_instructions=raw.get("llm_instructions", ""),
            list_templates=_list_templates(tpl),
            source=p,
            lists=raw.get("lists") or {},
            ocr_layout=raw.get("ocr_layout"),
        ))
    return out
