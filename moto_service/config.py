"""Konfiguration aus .env bzw. Umgebungsvariablen."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASIS = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    bot_token: str
    allowed_chat_id: int
    tz: ZoneInfo
    db_path: Path
    data_dir: Path
    log_dir: Path
    backup_dir: Path
    bald_km: int = 500
    bald_tage: int = 30
    sprung_km: int = 2000
    backup_behalten: int = 30


def _int(name: str, default: int) -> int:
    wert = os.getenv(name, "").strip()
    return int(wert) if wert else default


def lade_config(basis: Path = BASIS) -> Config:
    load_dotenv(basis / ".env")
    token = os.getenv("BOT_TOKEN", "").strip()
    chat = os.getenv("ALLOWED_CHAT_ID", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN fehlt in .env")
    if not chat.lstrip("-").isdigit():
        raise SystemExit("ALLOWED_CHAT_ID fehlt oder ist keine Zahl (.env)")
    return Config(
        bot_token=token,
        allowed_chat_id=int(chat),
        tz=ZoneInfo(os.getenv("ZEITZONE", "Europe/Zurich")),
        db_path=basis / "moto.db",
        data_dir=basis / "data",
        log_dir=basis / "logs",
        backup_dir=basis / "backup",
        bald_km=_int("BALD_KM", 500),
        bald_tage=_int("BALD_TAGE", 30),
        sprung_km=_int("SPRUNG_KM", 2000),
        backup_behalten=_int("BACKUP_BEHALTEN", 30),
    )
