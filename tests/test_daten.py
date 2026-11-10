"""Prüft die echten Daten in data/ (Wartungsplan und Historie der eigenen Maschine).

Schlägt fehl, wenn ein Eintrag beim Start übersprungen würde: unbekannte Position,
sinkender km-Stand, Tippfehler im Datum, Position ohne Intervall usw.
"""
from datetime import date
from pathlib import Path

import yaml

from moto_service.db import Datenbank, importiere_seed

DATA = Path(__file__).resolve().parent.parent / "data"


def _lade(name):
    return yaml.safe_load((DATA / name).read_text(encoding="utf-8")) or {}


def test_echte_daten_ohne_fehler(tmp_path):
    db = Datenbank(tmp_path / "t.db")
    z = importiere_seed(db, DATA)
    assert z["fehler"] == 0, "Ein Eintrag in data/*.yaml wird übersprungen – siehe Log"
    assert z["positionen"] == len(_lade("wartungsplan.yaml")["positionen"])
    assert z["services_neu"] == len(_lade("historie.yaml").get("services") or [])
    # zweiter Start: nichts doppelt
    z2 = importiere_seed(db, DATA)
    assert (z2["services_neu"], z2["km_neu"], z2["fehler"]) == (0, 0, 0)


def test_positionsnamen_eindeutig():
    namen = [str(p["position"]).strip().casefold() for p in _lade("wartungsplan.yaml")["positionen"]]
    assert len(namen) == len(set(namen))


def test_historie_nicht_in_der_zukunft():
    hist = _lade("historie.yaml")
    for e in (hist.get("km_stand") or []) + (hist.get("services") or []):
        d = e["datum"]
        assert not isinstance(d, date) or d <= date.today(), e
