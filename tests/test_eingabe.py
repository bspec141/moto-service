from datetime import date

import pytest

from moto_service.eingabe import finde_position, parse_datum, parse_erledigt, parse_km

HEUTE = date(2026, 11, 9)
NAMEN = ["Öl", "Ölfilter", "Kette schmieren", "Bremsflüssigkeit", "Zündkerzen", "Luftfilter", "Ventilspiel", "MFK"]


@pytest.mark.parametrize("text,km", [
    ("14250", 14250), ("14'250", 14250), ("14 250", 14250), ("14250 km", 14250), (" 14250km ", 14250),
    ("abc", None), ("14.250", None), ("-5", None), ("", None), ("14'25", None),
])
def test_parse_km(text, km):
    assert parse_km(text) == km


@pytest.mark.parametrize("text,d", [
    ("heute", HEUTE), ("gestern", date(2026, 11, 8)), ("3.11.2026", date(2026, 11, 3)),
    ("3.11.26", date(2026, 11, 3)), ("3.11.", date(2026, 11, 3)), ("2026-04-12", date(2026, 4, 12)),
    ("31.2.2026", None), ("14250", None), ("kette", None),
])
def test_parse_datum(text, d):
    assert parse_datum(text, HEUTE) == d


def test_parse_erledigt_alles():
    a = parse_erledigt("kette 14'300 3.11. selbst 12chf -- Motul Spray".split(), HEUTE)
    assert (a.position, a.km, a.datum, a.wer, a.kosten_chf, a.notiz) == (
        "kette", 14300, date(2026, 11, 3), "selbst", 12.0, "Motul Spray")


def test_parse_erledigt_minimal():
    a = parse_erledigt(["kette"], HEUTE)
    assert (a.position, a.km, a.datum) == ("kette", None, None)


def test_parse_erledigt_mehrwortig_und_kosten_formate():
    a = parse_erledigt(["kette", "schmieren", "chf7.50"], HEUTE)
    assert a.position == "kette schmieren" and a.kosten_chf == 7.5
    assert parse_erledigt(["öl", "45.-"], HEUTE).kosten_chf == 45.0


@pytest.mark.parametrize("eingabe,erwartet", [
    ("kette", ["Kette schmieren"]),
    ("Kette Schmieren", ["Kette schmieren"]),
    ("öl", ["Öl"]),                          # exakt schlägt "Ölfilter"
    ("oel", ["Öl"]),                         # Umlaut-Ersatz
    ("oelfilter", ["Ölfilter"]),
    ("brems", ["Bremsflüssigkeit"]),
    ("mfk", ["MFK"]),
    ("filter", ["Ölfilter", "Luftfilter"]),  # mehrdeutig → Auswahl
    ("ventil", ["Ventilspiel"]),
    ("zuendkerze", ["Zündkerzen"]),
    ("ketet", ["Kette schmieren"]),          # Tippfehler
    ("xyz", []),
    ("", []),
])
def test_finde_position(eingabe, erwartet):
    assert sorted(finde_position(eingabe, NAMEN)) == sorted(erwartet)


def test_mehrdeutig_bei_aehnlichen_positionen():
    assert sorted(finde_position("kette", ["Kette schmieren", "Kette spannen"])) == [
        "Kette schmieren", "Kette spannen"]
