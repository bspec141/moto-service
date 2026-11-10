"""Verbindet Datenbank und Logik: Übersicht berechnen, km und Services speichern."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .config import Config
from .db import Datenbank
from .logik import Faelligkeit, KmPruefung, berechne, km_pro_tag, pruefe_km, sortiere


@dataclass
class Lage:
    faelligkeiten: list[Faelligkeit]
    aktueller_km: int | None
    km_tag: float | None
    heute: date


class Dienst:
    def __init__(self, db: Datenbank, cfg: Config):
        self.db = db
        self.cfg = cfg

    def heute(self) -> date:
        return datetime.now(self.cfg.tz).date()

    def lage(self, heute: date | None = None) -> Lage:
        heute = heute or self.heute()
        km_log = self.db.km_log()
        aktuell = self.db.aktueller_km()
        km_tag = km_pro_tag(km_log, heute)
        letzte = self.db.letzte_ausfuehrungen()
        liste = [
            berechne(p, letzte.get(p.id), aktuell, heute, km_tag, self.cfg.bald_km, self.cfg.bald_tage)
            for p in self.db.positionen()
        ]
        return Lage(sortiere(liste), aktuell, km_tag, heute)

    def pruefe_km(self, km: int, datum: date | None = None) -> KmPruefung:
        return pruefe_km(km, datum or self.heute(), self.db.km_log(), self.cfg.sprung_km)

    def km_melden(self, km: int, datum: date | None = None) -> None:
        self.db.km_speichern(datum or self.heute(), km)
        # offene Sonntagsfrage gilt als beantwortet
        self.db.state_set("km_frage_seit", None)
        self.db.state_set("km_frage_nachgefragt", None)
