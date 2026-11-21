from odw2json.normalize import grounded, n_person, normalize


def test_dates():
    assert normalize("Lublin, dnia 9 listopada 2026 roku", "date") == "2026-11-09"
    assert normalize("28.08.2026", "date") == "2026-08-28"
    assert normalize("09-07-2026", "date") == "2026-07-09"
    assert normalize("2026-07-21", "date") == "2026-07-21"
    assert normalize("31.02.2026", "date") is None


def test_amounts():
    assert normalize("15 000,00 zł", "amount") == 15000.0
    assert normalize("200.00 PLN", "amount") == 200.0
    assert normalize("1.234,56", "amount") == 1234.56
    assert normalize(17, "amount") == 17.0


def test_identifiers():
    assert normalize("PL92 4762 1523 6332 5238 9437 1099", "account") == "92476215236332523894371099"
    assert normalize("999-755-33-19", "nip") == "9997553319"
    assert normalize("12345", "nip") is None
    assert normalize("2026/BZP 00999143", "bzp") == "2026/BZP00999143"
    assert normalize("2026/S 067-999583", "ted") == "999583-2026"
    assert normalize("999475-2026", "ted") == "999475-2026"


def test_person_titles():
    assert n_person("r. pr. Aleksandra Marciniak") == "Aleksandra Marciniak"
    assert n_person("adw. Zbigniew Górnicki") == "Zbigniew Górnicki"
    assert n_person("radca prawny Jan Kowalski") == "Jan Kowalski"


def test_grounding_rejects_hallucination():
    text = "KRS: 9999511966, NIP: 999-755-33-19, reprezentowana przez r. pr. Krystynę Mazowiecką"
    assert grounded("9997553319", "nip", text)
    assert not grounded("1234567890", "krs", text)
    assert grounded("Krystyna Mazowiecka", "person", text)  # odmiana nazwiska
    assert not grounded("Jan Nowak", "person", text)
