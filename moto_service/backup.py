"""Tägliches Backup der SQLite-DB, die letzten N behalten."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from .db import Datenbank

log = logging.getLogger(__name__)
PREFIX = "moto-"


def backup_erstellen(db: Datenbank, ordner: Path, heute: date, behalten: int = 30) -> Path:
    ziel = ordner / f"{PREFIX}{heute.isoformat()}.db"
    db.backup_nach(ziel)  # SQLite-Online-Backup: sicher, auch während der Bot läuft
    alte = sorted(ordner.glob(f"{PREFIX}*.db"))
    for datei in alte[:-behalten] if behalten > 0 else []:
        datei.unlink(missing_ok=True)
        log.info("Altes Backup gelöscht: %s", datei.name)
    log.info("Backup erstellt: %s", ziel)
    return ziel


def backup_heute_vorhanden(ordner: Path, heute: date) -> bool:
    return (ordner / f"{PREFIX}{heute.isoformat()}.db").exists()
