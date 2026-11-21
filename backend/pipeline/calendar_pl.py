"""Kalendarz polski: święta (stałe i ruchome liczone algorytmicznie) i terminy w dniach kalendarzowych."""
from __future__ import annotations

from datetime import date, timedelta


def easter(year: int) -> date:
    """Wielkanoc (algorytm Meeusa/Jonesa/Butchera, kalendarz gregoriański)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def holidays(year: int, wigilia_od: int | None = 2025) -> dict[date, str]:
    e = easter(year)
    h = {
        date(year, 1, 1): "Nowy Rok", date(year, 1, 6): "Trzech Króli", e: "Wielkanoc",
        e + timedelta(days=1): "Poniedziałek Wielkanocny", date(year, 5, 1): "Święto Pracy",
        date(year, 5, 3): "Święto Konstytucji 3 Maja", e + timedelta(days=49): "Zielone Świątki",
        e + timedelta(days=60): "Boże Ciało", date(year, 8, 15): "Wniebowzięcie NMP",
        date(year, 11, 1): "Wszystkich Świętych", date(year, 11, 11): "Święto Niepodległości",
        date(year, 12, 25): "Boże Narodzenie", date(year, 12, 26): "Drugi dzień Bożego Narodzenia",
    }
    if wigilia_od is not None and year >= wigilia_od:
        h[date(year, 12, 24)] = "Wigilia"
    return h


def day_off_reason(d: date, wigilia_od: int | None = 2025) -> str | None:
    """Powód, dla którego dzień nie jest roboczy (sobota/niedziela/święto) albo None."""
    if d in holidays(d.year, wigilia_od):
        return holidays(d.year, wigilia_od)[d]
    if d.weekday() == 5:
        return "sobota"
    if d.weekday() == 6:
        return "niedziela"
    return None


def compute_deadline(start: date, days: int, shift: bool, wigilia_od: int | None = 2025) -> tuple[date, str | None]:
    """start + days (dni kalendarzowe, dzień czynności nie jest liczony). Przy `shift` przesuwa z dnia wolnego na roboczy.

    Zwraca (termin, notatka) — notatka opisuje przesunięcie albo None.
    """
    raw = start + timedelta(days=days)
    if not shift:
        return raw, None
    d, first_reason = raw, day_off_reason(raw, wigilia_od)
    while day_off_reason(d, wigilia_od):
        d += timedelta(days=1)
    if d == raw:
        return raw, None
    return d, f"koniec terminu {raw.isoformat()} przypada w dniu wolnym ({first_reason}) → przesunięty na {d.isoformat()}"
