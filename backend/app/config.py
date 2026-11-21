"""Ustawienia z .env. Ścieżka danych i model LLM są konfigurowalne; zero założeń o nazwach plików."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    data_dir: Path = REPO_ROOT / "data"          # DATA_DIR: katalog z paczkami ZIP (uzp/, synthetic/, public/)
    cases_dir: Path = REPO_ROOT / "var" / "cases"  # katalogi spraw (wynik ingest)
    cache_dir: Path = REPO_ROOT / "var" / "cache"  # cache odpowiedzi rejestrów (*_api.json)
    rules_config: Path = REPO_ROOT / "config" / "rules.yaml"
    offline: bool = False                         # OFFLINE=1: tylko cache, zero sieci
    llm_model: str = "anthropic/claude-sonnet-5-5"  # LLM_MODEL: przełączalny np. na "ollama/llama3"
    llm_api_base: str | None = None               # LLM_API_BASE: model lokalny
    krs_base_url: str = "https://api-krs.ms.gov.pl"
    ezam_base_url: str = "https://ezamowienia.gov.pl"
    mock_registries: bool = False                 # MOCK_REGISTRIES=1: mock KRS dla danych syntetycznych


settings = Settings()
