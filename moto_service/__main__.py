"""Start: python -m moto_service"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from telegram import BotCommand, Update
from telegram.ext import Application

from . import __version__
from .bot import handler_registrieren
from .config import Config, lade_config
from .db import Datenbank, importiere_seed
from .dienst import Dienst
from .jobs import jobs_einrichten

BEFEHLE = [
    BotCommand("status", "Aktuelle Übersicht"),
    BotCommand("erledigt", "Service eintragen: <position> [km] [datum]"),
    BotCommand("historie", "Letzte Einträge [position]"),
    BotCommand("plan", "Wartungsplan anzeigen"),
    BotCommand("neu", "Position hinzufügen"),
    BotCommand("export", "CSV senden"),
    BotCommand("hilfe", "Hilfe"),
]


def logging_einrichten(cfg: Config) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    datei = RotatingFileHandler(cfg.log_dir / "moto-service.log", maxBytes=1_000_000, backupCount=5,
                                encoding="utf-8")
    datei.setFormatter(fmt)
    konsole = logging.StreamHandler(sys.stdout)
    konsole.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers[:] = [datei, konsole]
    # httpx loggt jede Anfrage inkl. URL mit Bot-Token → nur Warnungen
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def main() -> None:
    cfg = lade_config()
    logging_einrichten(cfg)
    log = logging.getLogger("moto_service")
    log.info("moto-service %s startet", __version__)

    db = Datenbank(cfg.db_path)
    importiere_seed(db, cfg.data_dir)
    dienst = Dienst(db, cfg)

    async def nach_start(app: Application) -> None:
        await app.bot.set_my_commands(BEFEHLE)

    app = Application.builder().token(cfg.bot_token).post_init(nach_start).build()
    app.bot_data["dienst"] = dienst
    handler_registrieren(app)
    jobs_einrichten(app, dienst)
    log.info("Long Polling läuft")
    # Netzwerkfehler (WLAN weg, Laptop aufgewacht) behandelt PTB selbst mit Wiederholung
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
