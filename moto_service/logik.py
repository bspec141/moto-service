"""Fälligkeitslogik – reine Funktionen ohne Datenbank oder Telegram (gut testbar)."""
from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta
from enum import IntEnum


class Status(IntEnum):
    # Reihenfolge = Sortierung in der Übersicht
    UEBERFAELLIG = 0
    BALD = 1
    OK = 2


STATUS_TEXT = {Status.UEBERFAELLIG: "ÜBERFÄLLIG", Status.BALD: "BALD", Status.OK: "OK"}


@dataclass(frozen=True)
class Position:
    id: int
    name: str
    intervall_km: int | None
    intervall_monate: int | None
    notiz: str | None = None


@dataclass(frozen=True)
class Ausfuehrung:
    datum: date
    km: int | None


@dataclass(frozen=True)
class Faelligkeit:
    position: Position
    letzte: Ausfuehrung | None
    faellig_km: int | None
    faellig_datum: date | None
    rest_km: int | None        # negativ = so viele km überfällig
    rest_tage: int | None      # negativ = so viele Tage überfällig
    prognose_tage: int | None  # Tage bis zur km-Fälligkeit laut Ø km/Tag
    status: Status

    @property
    def nie_erfasst(self) -> bool:
        return self.letzte is None

    @property
    def tage_bis(self) -> int | None:
        """Frühester erwarteter Fälligkeitstag (Datum oder km-Prognose), in Tagen."""
        werte = [w for w in (self.rest_tage, self.prognose_tage) if w is not None]
        return min(werte) if werte else None


def plus_monate(d: date, monate: int) -> date:
    """Datum + n Monate; Monatsende wird gekappt (31.01. + 1 Monat = 28./29.02.)."""
    m = d.month - 1 + monate
    jahr, monat = d.year + m // 12, m % 12 + 1
    tag = min(d.day, calendar.monthrange(jahr, monat)[1])
    return date(jahr, monat, tag)


def km_pro_tag(km_log: list[tuple[date, int]], heute: date, fenster_tage: int = 60) -> float | None:
    """Ø km/Tag aus den km-Meldungen der letzten `fenster_tage` Tage.

    Erste und letzte Meldung im Fenster ergeben die Steigung. Weniger als zwei
    Meldungen an verschiedenen Tagen → keine Prognose (None).
    """
    start = heute - timedelta(days=fenster_tage)
    punkte = sorted((d, km) for d, km in km_log if start <= d <= heute)
    if len(punkte) < 2:
        return None
    (d0, km0), (d1, km1) = punkte[0], punkte[-1]
    tage = (d1 - d0).days
    if tage <= 0:
        return None
    return max(km1 - km0, 0) / tage


def berechne(
    position: Position,
    letzte: Ausfuehrung | None,
    aktueller_km: int | None,
    heute: date,
    km_tag: float | None,
    bald_km: int = 500,
    bald_tage: int = 30,
) -> Faelligkeit:
    """Fälligkeit einer Position. Fällig ist, was zuerst erreicht wird (km oder Zeit).

    - Fälligkeitspunkt erreicht (rest_km <= 0 oder rest_tage <= 0) → ÜBERFÄLLIG
    - innerhalb der Schwelle (rest_km <= bald_km oder rest_tage <= bald_tage) → BALD
    - nie ausgeführt → ÜBERFÄLLIG (Intervall unbekannt, ab wann es läuft)
    """
    if letzte is None:
        return Faelligkeit(position, None, None, None, None, None, None, Status.UEBERFAELLIG)

    faellig_km = rest_km = prognose = None
    if position.intervall_km and letzte.km is not None:
        faellig_km = letzte.km + position.intervall_km
        if aktueller_km is not None:
            rest_km = faellig_km - max(aktueller_km, letzte.km)
            if rest_km > 0 and km_tag:
                prognose = math.ceil(rest_km / km_tag)

    faellig_datum = rest_tage = None
    if position.intervall_monate:
        faellig_datum = plus_monate(letzte.datum, position.intervall_monate)
        rest_tage = (faellig_datum - heute).days

    if (rest_km is not None and rest_km <= 0) or (rest_tage is not None and rest_tage <= 0):
        status = Status.UEBERFAELLIG
    elif (rest_km is not None and rest_km <= bald_km) or (rest_tage is not None and rest_tage <= bald_tage):
        status = Status.BALD
    elif rest_km is None and rest_tage is None:
        # Nur km-Intervall, aber kein km bekannt (weder beim Service noch aktuell)
        status = Status.UEBERFAELLIG if letzte.km is None else Status.OK
    else:
        status = Status.OK
    return Faelligkeit(position, letzte, faellig_km, faellig_datum, rest_km, rest_tage, prognose, status)


def sortiere(liste: list[Faelligkeit]) -> list[Faelligkeit]:
    """ÜBERFÄLLIG zuerst (am längsten überfällig oben), dann BALD (nächste zuerst), dann OK."""
    def schluessel(f: Faelligkeit):
        tage = f.tage_bis if f.tage_bis is not None else math.inf
        km_rest = f.rest_km if f.rest_km is not None else math.inf
        nie = 0 if f.nie_erfasst else 1
        return (f.status, nie, tage, km_rest, f.position.name.casefold())
    return sorted(liste, key=schluessel)


# --- Zeitbasierte Erinnerungen -------------------------------------------------

def zeit_erinnerungen(liste: list[Faelligkeit], schon_gesendet: set[str],
                      vorwarn_tage: int = 30) -> list[tuple[str, Faelligkeit]]:
    """Welche Datums-Erinnerungen sind jetzt zu schicken?

    Pro Position und Fälligkeitsdatum je einmal: `vorwarn_tage` vorher und am
    Fälligkeitstag. War der Laptop aus, wird die Meldung beim nächsten Check
    nachgeholt (ist das Datum schon vorbei, kommt nur noch „fällig“).
    Rückgabe: Liste (Schlüssel, Fälligkeit); den Schlüssel als gesendet merken.
    """
    neu = []
    for f in liste:
        if f.faellig_datum is None or f.rest_tage is None:
            continue
        basis = f"{f.position.id}:{f.faellig_datum.isoformat()}"
        if f.rest_tage <= 0:
            schluessel = f"{basis}:faellig"
        elif f.rest_tage <= vorwarn_tage:
            schluessel = f"{basis}:vorher"
        else:
            continue
        if schluessel not in schon_gesendet:
            neu.append((schluessel, f))
    return neu


# --- Plausibilität km-Stand ---------------------------------------------------

@dataclass(frozen=True)
class KmPruefung:
    ok: bool
    rueckfrage: bool = False
    grund: str = ""
    letzter_km: int | None = None


def pruefe_km(neu: int, datum: date, km_log: list[tuple[date, int]], sprung_km: int = 2000) -> KmPruefung:
    """km-Stand darf nicht sinken; Sprung > sprung_km seit der letzten Meldung → Rückfrage."""
    if neu < 0:
        return KmPruefung(False, grund="km-Stand kann nicht negativ sein.")
    vorher = [km for d, km in km_log if d <= datum]
    nachher = [km for d, km in km_log if d > datum]
    letzter = max(vorher) if vorher else None
    if letzter is not None and neu < letzter:
        return KmPruefung(False, grund=f"km-Stand darf nicht sinken (zuletzt {letzter} km).", letzter_km=letzter)
    if nachher and neu > min(nachher):
        return KmPruefung(False, grund=f"Später ist schon {min(nachher)} km erfasst.", letzter_km=letzter)
    if letzter is not None and neu - letzter > sprung_km:
        return KmPruefung(True, rueckfrage=True, grund=f"+{neu - letzter} km seit der letzten Meldung.",
                          letzter_km=letzter)
    return KmPruefung(True, letzter_km=letzter)
