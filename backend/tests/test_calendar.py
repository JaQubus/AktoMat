from datetime import date

from pipeline.calendar_pl import compute_deadline, day_off_reason, easter, holidays


def test_easter_known_dates():
    assert easter(2025) == date(2025, 4, 20)
    assert easter(2026) == date(2026, 4, 5)
    assert easter(2024) == date(2024, 3, 31)


def test_movable_holidays_2026():
    h = holidays(2026)
    assert date(2026, 4, 6) in h  # Poniedziałek Wielkanocny
    assert h[date(2026, 6, 4)] == "Boże Ciało"
    assert date(2026, 5, 24) in h  # Zielone Świątki


def test_wigilia_only_from_2025():
    assert date(2025, 12, 24) in holidays(2025)
    assert date(2024, 12, 24) not in holidays(2024)


def test_deadline_plain():
    assert compute_deadline(date(2025, 12, 30), 10, True) == (date(2026, 1, 9), None)


def test_deadline_saturday_shifts_to_monday():
    d, note = compute_deadline(date(2026, 1, 14), 10, True)
    assert d == date(2026, 1, 26) and "sobota" in note


def test_deadline_saturday_without_shift_flag():
    assert compute_deadline(date(2026, 1, 14), 10, False) == (date(2026, 1, 24), None)


def test_deadline_on_corpus_christi_shifts_to_friday():
    d, note = compute_deadline(date(2026, 5, 25), 10, True)  # 4.06.2026 = Boże Ciało
    assert d == date(2026, 6, 5) and "Boże Ciało" in note


def test_deadline_easter_weekend_chain():
    # 3 dni od 2.04.2026 = niedziela wielkanocna 5.04 → poniedziałek 6.04 też wolny → wtorek 7.04
    assert compute_deadline(date(2026, 4, 2), 3, True)[0] == date(2026, 4, 7)


def test_wigilia_2025_is_day_off_but_not_2024():
    assert day_off_reason(date(2025, 12, 24)) == "Wigilia"
    assert day_off_reason(date(2024, 12, 24), 2025) is None
