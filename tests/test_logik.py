from datetime import date

import pytest

from moto_service.logik import (
    Ausfuehrung, Position, Status, berechne, km_pro_tag, plus_monate, pruefe_km, sortiere, zeit_erinnerungen,
)

HEUTE = date(2026, 11, 9)
OEL = Position(1, "Öl", 6000, 12)
KETTE = Position(2, "Kette schmieren", 600, None)
MFK = Position(3, "MFK", None, 36)


def f(pos, letzte_datum, letzte_km, aktuell, km_tag=None, heute=HEUTE):
    letzte = Ausfuehrung(letzte_datum, letzte_km) if letzte_datum else None
    return berechne(pos, letzte, aktuell, heute, km_tag, bald_km=500, bald_tage=30)


# --- plus_monate --------------------------------------------------------------

@pytest.mark.parametrize("start,monate,erwartet", [
    (date(2026, 1, 31), 1, date(2026, 2, 28)),
    (date(2024, 1, 31), 1, date(2024, 2, 29)),   # Schaltjahr
    (date(2026, 11, 15), 3, date(2027, 2, 15)),  # Jahreswechsel
    (date(2024, 2, 29), 12, date(2025, 2, 28)),
    (date(2026, 5, 10), 36, date(2029, 5, 10)),
])
def test_plus_monate(start, monate, erwartet):
    assert plus_monate(start, monate) == erwartet


# --- nur km -------------------------------------------------------------------

def test_km_ok():
    r = f(KETTE, date(2026, 11, 1), 14000, 14050)
    assert (r.faellig_km, r.rest_km, r.status) == (14600, 550, Status.OK)
    assert r.faellig_datum is None


def test_km_bald_genau_auf_schwelle():
    assert f(KETTE, date(2026, 11, 1), 14000, 14100).status == Status.BALD  # rest 500


def test_km_genau_erreicht_ist_ueberfaellig():
    r = f(KETTE, date(2026, 11, 1), 14000, 14600)
    assert r.rest_km == 0 and r.status == Status.UEBERFAELLIG


def test_km_ueberschritten():
    r = f(KETTE, date(2026, 11, 1), 14000, 14700)
    assert r.rest_km == -100 and r.status == Status.UEBERFAELLIG


def test_km_ohne_aktuellen_stand_unbekannt_aber_ok():
    r = f(KETTE, date(2026, 11, 1), 14000, None)
    assert r.rest_km is None and r.faellig_km == 14600 and r.status == Status.OK


def test_nur_km_intervall_aber_service_ohne_km():
    assert f(KETTE, date(2026, 11, 1), None, 14000).status == Status.UEBERFAELLIG


# --- nur Zeit -----------------------------------------------------------------

def test_zeit_ok():
    r = f(MFK, date(2024, 5, 14), None, 15000)
    assert r.faellig_datum == date(2027, 5, 14) and r.status == Status.OK


def test_zeit_bald_30_tage_vorher():
    r = f(MFK, date(2023, 12, 9), None, None)  # fällig 09.12.2026 = in 30 Tagen
    assert r.rest_tage == 30 and r.status == Status.BALD


def test_zeit_31_tage_ist_ok():
    assert f(MFK, date(2023, 12, 10), None, None).status == Status.OK


def test_zeit_am_faelligkeitstag_ueberfaellig():
    r = f(MFK, date(2023, 11, 9), None, None)
    assert r.rest_tage == 0 and r.status == Status.UEBERFAELLIG


def test_zeit_vorbei():
    r = f(MFK, date(2023, 10, 1), None, None)
    assert r.rest_tage < 0 and r.status == Status.UEBERFAELLIG


# --- beides: was zuerst kommt -------------------------------------------------

def test_beides_km_zuerst():
    r = f(OEL, date(2026, 6, 1), 10000, 15800)  # km rest 200, Zeit noch 7 Monate
    assert r.status == Status.BALD and r.rest_km == 200 and r.rest_tage > 30


def test_beides_zeit_zuerst():
    r = f(OEL, date(2025, 11, 1), 10000, 11000)  # km rest 5000, Datum 01.11.2026 vorbei
    assert r.status == Status.UEBERFAELLIG and r.rest_km == 5000 and r.rest_tage == -8


def test_beides_ok():
    assert f(OEL, date(2026, 6, 1), 10000, 11000).status == Status.OK


def test_beides_beide_ueberschritten():
    assert f(OEL, date(2025, 1, 1), 5000, 12000).status == Status.UEBERFAELLIG


def test_nie_erfasst_ist_ueberfaellig():
    r = f(OEL, None, None, 14000)
    assert r.nie_erfasst and r.status == Status.UEBERFAELLIG and r.faellig_km is None


def test_km_stand_unter_service_km_wird_nicht_negativ_gerechnet():
    # Service mit km nach dem letzten km_log-Eintrag: rest_km ab Service-km
    r = f(KETTE, date(2026, 11, 1), 14000, 13900)
    assert r.rest_km == 600


# --- Prognose -----------------------------------------------------------------

def test_km_pro_tag_aus_60_tagen():
    log = [(date(2026, 8, 1), 10000),   # ausserhalb des Fensters
           (date(2026, 9, 10), 13000), (date(2026, 11, 9), 14200)]
    assert km_pro_tag(log, HEUTE) == pytest.approx(1200 / 60)


def test_km_pro_tag_zu_wenig_daten():
    assert km_pro_tag([], HEUTE) is None
    assert km_pro_tag([(date(2026, 11, 1), 14000)], HEUTE) is None
    assert km_pro_tag([(date(2026, 11, 1), 14000), (date(2026, 11, 1), 14100)], HEUTE) is None
    assert km_pro_tag([(date(2026, 8, 1), 1), (date(2026, 8, 20), 2)], HEUTE) is None  # alles alt


def test_km_pro_tag_fenstergrenze_inklusiv():
    log = [(date(2026, 9, 10), 13000), (date(2026, 11, 9), 13600)]  # genau 60 Tage
    assert km_pro_tag(log, HEUTE) == pytest.approx(10.0)


def test_km_pro_tag_stillstand():
    log = [(date(2026, 10, 1), 14000), (date(2026, 11, 1), 14000)]
    assert km_pro_tag(log, HEUTE) == 0


def test_prognose_tage_aufgerundet():
    r = f(KETTE, date(2026, 11, 1), 14000, 14100, km_tag=30)  # rest 500 / 30 = 16.7
    assert r.prognose_tage == 17


def test_keine_prognose_bei_stillstand_oder_ueberfaellig():
    assert f(KETTE, date(2026, 11, 1), 14000, 14100, km_tag=0).prognose_tage is None
    assert f(KETTE, date(2026, 11, 1), 14000, 14700, km_tag=30).prognose_tage is None


def test_tage_bis_nimmt_frueheres():
    r = f(OEL, date(2026, 6, 1), 10000, 15000, km_tag=100)  # km in 10 Tagen, Datum in 204 Tagen
    assert r.prognose_tage == 10 and r.tage_bis == 10


# --- Sortierung ---------------------------------------------------------------

def test_sortierung():
    ok = f(MFK, date(2025, 1, 1), None, None)
    bald_spaet = f(KETTE, date(2026, 11, 1), 14000, 14150, km_tag=10)   # 45 Tage
    bald_frueh = f(OEL, date(2026, 6, 1), 10000, 15900, km_tag=10)      # 10 Tage
    ueber = f(Position(4, "Luftfilter", 1000, None), date(2026, 1, 1), 1000, 14000)
    nie = f(Position(5, "Ventilspiel", 24000, None), None, None, 14000)
    reihenfolge = [x.position.name for x in sortiere([ok, bald_spaet, ueber, bald_frueh, nie])]
    assert reihenfolge == ["Ventilspiel", "Luftfilter", "Öl", "Kette schmieren", "MFK"]


# --- Termin-Erinnerungen ------------------------------------------------------

def test_erinnerung_30_tage_vorher_und_am_tag():
    vorher = f(MFK, date(2023, 12, 9), None, None)           # in 30 Tagen
    zu_frueh = f(MFK, date(2023, 12, 10), None, None)        # in 31 Tagen
    heute = f(Position(9, "Bremsflüssigkeit", None, 24), date(2024, 11, 9), None, None)
    neu = zeit_erinnerungen([vorher, zu_frueh, heute], set())
    assert [s for s, _ in neu] == ["3:2026-12-09:vorher", "9:2026-11-09:faellig"]


def test_erinnerung_nur_einmal():
    x = f(MFK, date(2023, 12, 9), None, None)
    assert zeit_erinnerungen([x], {"3:2026-12-09:vorher"}) == []


def test_erinnerung_neuer_zyklus_nach_service():
    alt = {"3:2026-12-09:vorher", "3:2026-12-09:faellig"}
    neu = f(MFK, date(2026, 11, 9), None, None)  # neu fällig 2029
    assert zeit_erinnerungen([neu], alt) == []
    spaeter = f(MFK, date(2026, 11, 9), None, None, heute=date(2029, 10, 20))
    assert [s for s, _ in zeit_erinnerungen([spaeter], alt)] == ["3:2029-11-09:vorher"]


def test_erinnerung_nicht_fuer_nur_km_oder_nie_erfasst():
    assert zeit_erinnerungen([f(KETTE, date(2020, 1, 1), 1, 99999), f(MFK, None, None, None)], set()) == []


# --- Plausibilität ------------------------------------------------------------

LOG = [(date(2026, 10, 1), 13000), (date(2026, 11, 1), 14000)]


def test_km_normal():
    p = pruefe_km(14250, HEUTE, LOG)
    assert p.ok and not p.rueckfrage and p.letzter_km == 14000


def test_km_gleich_bleibt_ok():
    assert pruefe_km(14000, HEUTE, LOG).ok


def test_km_sinkt_abgelehnt():
    p = pruefe_km(13999, HEUTE, LOG)
    assert not p.ok and "sinken" in p.grund


def test_km_sprung_genau_2000_ohne_rueckfrage():
    assert not pruefe_km(16000, HEUTE, LOG).rueckfrage


def test_km_sprung_ueber_2000_rueckfrage():
    p = pruefe_km(16001, HEUTE, LOG)
    assert p.ok and p.rueckfrage


def test_km_nachtraeglich_muss_dazwischen_passen():
    assert pruefe_km(13500, date(2026, 10, 15), LOG).ok
    assert not pruefe_km(14100, date(2026, 10, 15), LOG).ok


def test_km_erster_eintrag():
    assert pruefe_km(14000, HEUTE, []).ok
    assert not pruefe_km(-1, HEUTE, []).ok
