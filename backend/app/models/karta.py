"""Model Karty Odwołania = kontrakt danych. Klucze 1:1 z Załącznikiem C starszego OPZ.

Rozszerzenia (nie ma ich w Zał. C) są opcjonalne i pomijane w JSON, gdy puste:
  - Pole.dowod            krótki cytat dowodu z dokumentu,
  - Weryfikacja.kryteria  wynik reguł F1–F13 (status + uzasadnienie + źródło),
  - Metadata.rozszerzenia_kontraktu  lista nazw rozszerzeń użytych w danej Karcie.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_serializer

T = TypeVar("T")

BRAK_DANYCH = "BRAK DANYCH"


class Status(str, Enum):
    verified = "verified"
    warning = "warning"
    missing = "missing"
    not_applicable = "not_applicable"


class StatusReguly(str, Enum):
    spelnione = "spełnione"
    niespelnione = "niespełnione"
    do_weryfikacji = "do_weryfikacji_ręcznej"
    nie_dotyczy = "nie_dotyczy"


class Kontrakt(BaseModel):
    """Baza: pola z `_OMIT_IF_NONE` nie trafiają do JSON, gdy są None (pozostałe null zostają jako null)."""

    model_config = ConfigDict(extra="forbid")
    OMIT_IF_NONE: ClassVar[tuple[str, ...]] = ()

    @model_serializer(mode="wrap")
    def _ser(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        for k in self.OMIT_IF_NONE:
            if k in data and data[k] is None:
                del data[k]
        return data


class Pole(Kontrakt, Generic[T]):
    """{value, status, source} z Zał. C pkt 4.1 (+ opcjonalny `dowod`)."""

    OMIT_IF_NONE: ClassVar[tuple[str, ...]] = ("source", "dowod")
    value: T | None = None
    status: Status = Status.missing
    source: str | None = None
    dowod: str | None = None


def brak() -> Pole[Any]:
    return Pole(value=None, status=Status.missing, source=BRAK_DANYCH)


def nd() -> Pole[Any]:
    return Pole(value=None, status=Status.not_applicable)


class PoleWart(Kontrakt):
    """Element adresu: {value, status} (źródło jest na poziomie adresu)."""

    value: str | None = None
    status: Status = Status.missing


class Adres(Kontrakt):
    ulica: PoleWart = Field(default_factory=PoleWart)
    kod_pocztowy: PoleWart = Field(default_factory=PoleWart)
    miasto: PoleWart = Field(default_factory=PoleWart)
    source: str | None = BRAK_DANYCH


class Metadata(Kontrakt):
    OMIT_IF_NONE: ClassVar[tuple[str, ...]] = ("rozszerzenia_kontraktu",)
    version: str = "1.0"
    generated_at: str
    case_id: str
    generator: str = "odwolania2json"
    workflow_version: str = "0.1.0"
    rozszerzenia_kontraktu: list[str] | None = None


class Naglowek(Kontrakt):
    sygnatura: str | None = None
    numer_dzk: str | None = None
    sekretariat: str | None = None
    data: str | None = None
    braki_formalne: bool = False
    braki_formalne_opis: str = "BRAK BRAKÓW FORMALNYCH"


class Wpis(Kontrakt):
    OMIT_IF_NONE: ClassVar[tuple[str, ...]] = ("source", "dowod")
    wymagane: float | None = None
    wniesione: float | None = None
    data_wplaty: str | None = None
    waluta: str = "PLN"
    prawidlowy: bool | None = None
    status: Status = Status.missing
    source: str | None = None
    dowod: str | None = None


class WniesioneWTerminie(Kontrakt):
    """informacje_ogolne.wniesione_w_terminie ma dodatkowo `opis` (Zał. C)."""

    OMIT_IF_NONE: ClassVar[tuple[str, ...]] = ("source", "dowod")
    value: bool | None = None
    opis: str | None = None
    status: Status = Status.missing
    source: str | None = None
    dowod: str | None = None


class InformacjeOgolne(Kontrakt):
    zamowienie: Pole[str] = Field(default_factory=brak)
    tryb_postepowania: Pole[str] = Field(default_factory=brak)
    publikator: Pole[str] = Field(default_factory=brak)
    czynnosc: Pole[str] = Field(default_factory=brak)
    termin_na_wniesienie: Pole[str] = Field(default_factory=brak)
    wniesione_w_terminie: WniesioneWTerminie = Field(default_factory=WniesioneWTerminie)
    wpis: Wpis = Field(default_factory=Wpis)


class Odwolujacy(Kontrakt):
    konsorcjum: Pole[bool] = Field(default_factory=brak)
    nazwa: Pole[str] = Field(default_factory=brak)
    forma_prawna: Pole[str] = Field(default_factory=brak)
    adres: Adres = Field(default_factory=Adres)
    email: Pole[str] = Field(default_factory=brak)
    telefon: Pole[str] = Field(default_factory=brak)
    nip: Pole[str] = Field(default_factory=brak)
    regon: Pole[str] = Field(default_factory=brak)
    krs: Pole[str] = Field(default_factory=brak)
    bae: Pole[str] = Field(default_factory=brak)
    epuap: Pole[str] = Field(default_factory=brak)


class CzlonekOrganu(Kontrakt):
    OMIT_IF_NONE: ClassVar[tuple[str, ...]] = ("source",)
    imie: str | None = None
    nazwisko: str | None = None
    funkcja: str | None = None
    status: Status = Status.verified
    source: str | None = None


class Podpisujacy(Kontrakt):
    imie_nazwisko: Pole[str] = Field(default_factory=brak)
    typ_podpisu: Pole[str] = Field(default_factory=brak)
    data_podpisu: Pole[str] = Field(default_factory=brak)
    podpis_wazny: Pole[bool] = Field(default_factory=brak)


class Reprezentacja(Kontrakt):
    zasady: Pole[str] = Field(default_factory=brak)
    organ: Pole[str] = Field(default_factory=brak)
    czlonkowie: list[CzlonekOrganu] = Field(default_factory=list)
    podpisujacy: Podpisujacy = Field(default_factory=Podpisujacy)
    pelnomocnictwo_wymagane: Pole[bool] = Field(default_factory=brak)
    pelnomocnictwo_zalaczone: Pole[bool] = Field(default_factory=nd)
    oplata_skarbowa: Pole[bool] = Field(default_factory=nd)


class Zamawiajacy(Kontrakt):
    nazwa: Pole[str] = Field(default_factory=brak)
    adres: Adres = Field(default_factory=Adres)
    nip: Pole[str] = Field(default_factory=brak)
    regon: Pole[str] = Field(default_factory=brak)
    pelnomocnik: Pole[str] = Field(default_factory=nd)


class BrakiFormalne(Kontrakt):
    value: bool | None = None
    lista_brakow: list[str] = Field(default_factory=list)
    status: Status = Status.missing


class Kryterium(Kontrakt):
    """Rozszerzenie: wynik jednej reguły F1–F13."""

    OMIT_IF_NONE: ClassVar[tuple[str, ...]] = ("source",)
    id: str
    nazwa: str
    status: StatusReguly
    uzasadnienie: str
    source: str | None = None


class Weryfikacja(Kontrakt):
    OMIT_IF_NONE: ClassVar[tuple[str, ...]] = ("kryteria",)
    numer_ogloszenia: Pole[str] = Field(default_factory=brak)
    data_czynnosci: Pole[str] = Field(default_factory=brak)
    termin_ustawowy: Pole[str] = Field(default_factory=brak)
    termin_wyliczony: Pole[str] = Field(default_factory=brak)
    termin_faktyczny: Pole[str] = Field(default_factory=brak)
    wniesione_w_terminie: Pole[bool] = Field(default_factory=brak)
    wpis_prawidlowy: Pole[bool] = Field(default_factory=brak)
    dowod_przekazania_kopii: Pole[bool] = Field(default_factory=brak)
    dokument_umocowania: Pole[str] = Field(default_factory=brak)
    braki_formalne: BrakiFormalne = Field(default_factory=BrakiFormalne)
    kryteria: list[Kryterium] | None = None


class Stopka(Kontrakt):
    sklad_orzekajacy: str | None = None
    data_podpisu_prezesa: str | None = None
    uwaga: str = "Do wypełnienia ręcznie przez pracownika KIO"


class AuditTrail(Kontrakt):
    processing_start: str | None = None
    processing_end: str | None = None
    sources_used: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class KartaOdwolania(Kontrakt):
    metadata: Metadata
    naglowek: Naglowek = Field(default_factory=Naglowek)
    informacje_ogolne: InformacjeOgolne = Field(default_factory=InformacjeOgolne)
    odwolujacy: Odwolujacy = Field(default_factory=Odwolujacy)
    reprezentacja: Reprezentacja = Field(default_factory=Reprezentacja)
    zamawiajacy: Zamawiajacy = Field(default_factory=Zamawiajacy)
    weryfikacja: Weryfikacja = Field(default_factory=Weryfikacja)
    stopka: Stopka = Field(default_factory=Stopka)
    audit_trail: AuditTrail = Field(default_factory=AuditTrail)

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
