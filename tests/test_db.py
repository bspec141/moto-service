from datetime import date
from pathlib import Path

import pytest

from moto_service.backup import backup_erstellen
from moto_service.db import Datenbank, importiere_seed

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def db(tmp_path):
    return Datenbank(tmp_path / "t.db")


def test_seed_ohne_duplikate(db):
    z1 = importiere_seed(db, DATA)
    assert z1["fehler"] == 0 and z1["positionen"] == 8 and z1["services_neu"] == 5
    z2 = importiere_seed(db, DATA)
    assert z2["services_neu"] == 0 and z2["km_neu"] == 0
    assert len(db.positionen()) == 8
    assert len(db.historie(limit=0)) == 5


def test_service_km_landet_im_km_log(db):
    importiere_seed(db, DATA)
    assert (date(2026, 3, 21), 11800) in db.km_log()
    assert db.aktueller_km() == 13980


def test_sync_aktualisiert_und_behaelt_eigene(db, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "wartungsplan.yaml").write_text("positionen:\n  - {position: Öl, intervall_km: 6000}\n", encoding="utf-8")
    importiere_seed(db, d)
    db.position_speichern("Reifen", 10000, None, None)  # wie /neu
    (d / "wartungsplan.yaml").write_text(
        "positionen:\n  - {position: öl, intervall_km: 5000, intervall_monate: 12, notiz: neu}\n", encoding="utf-8")
    importiere_seed(db, d)
    p = {x.name: x for x in db.positionen()}
    assert set(p) == {"öl", "Reifen"}  # gleiche Position (Gross/klein egal), Name aus YAML
    assert (p["öl"].intervall_km, p["öl"].intervall_monate, p["öl"].notiz) == (5000, 12, "neu")


def test_fehlerhafte_eintraege_werden_uebersprungen(db, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "wartungsplan.yaml").write_text(
        "positionen:\n  - {position: Öl, intervall_km: 6000}\n  - {position: Leer}\n", encoding="utf-8")
    (d / "historie.yaml").write_text(
        "km_stand:\n  - {datum: 2026-10-01, km: 5000}\n  - {datum: 2026-11-01, km: 4000}\n"
        "services:\n  - {position: Gibtsnicht, datum: 2026-01-01}\n"
        "  - {position: öl, datum: '01.02.2026', km: 3000, kosten_chf: '45,50'}\n", encoding="utf-8")
    z = importiere_seed(db, d)
    assert z["fehler"] == 3 and z["services_neu"] == 1 and z["km_neu"] == 1
    e = db.historie(limit=0)[0]
    assert e.datum == date(2026, 2, 1) and e.kosten_chf == 45.5


def test_letzte_ausfuehrung(db):
    pid = db.position_speichern("Öl", 6000, None, None)
    db.service_speichern(pid, date(2026, 1, 1), 1000)
    db.service_speichern(pid, date(2026, 6, 1), 4000)
    db.service_speichern(pid, date(2026, 3, 1), 2000)
    a = db.letzte_ausfuehrungen()[pid]
    assert (a.datum, a.km) == (date(2026, 6, 1), 4000)


def test_state(db):
    db.state_set("erinnert:1:x", "a")
    db.state_set("erinnert:2:y", "b")
    db.state_set("anders", "c")
    assert db.state_keys("erinnert:") == {"1:x", "2:y"}
    db.state_set("anders", None)
    assert db.state_get("anders") is None


def test_backup_behaelt_30(db, tmp_path):
    ordner = tmp_path / "backup"
    for i in range(35):
        backup_erstellen(db, ordner, date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + i), 30)
    dateien = sorted(p.name for p in ordner.glob("*.db"))
    assert len(dateien) == 30 and dateien[0] == "moto-2026-01-06.db"
