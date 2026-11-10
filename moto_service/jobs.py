"""Geplante Aufgaben: Sonntagsfrage, Nachfrage, täglicher Fälligkeits-Check, Backup.

Alle Jobs sind idempotent und merken sich ihren Stand in bot_state. Dadurch
überleben sie Neustarts und holen Verpasstes nach (Laptop war aus).
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from html import escape

from telegram.ext import Application, ContextTypes

from . import texte
from .backup import backup_erstellen, backup_heute_vorhanden
from .dienst import Dienst
from .logik import zeit_erinnerungen

log = logging.getLogger(__name__)

FRAGE_WOCHENTAG = 6          # Python: Montag=0 … Sonntag=6
FRAGE_ZEIT = time(18, 0)
NACHFRAGE_NACH = timedelta(days=2)
TAGESCHECK_ZEIT = time(9, 0)
BACKUP_ZEIT = time(3, 0)
VORWARN_TAGE = 30


def letzter_frage_termin(jetzt: datetime) -> datetime:
    """Letzter Sonntag 18:00 (Ortszeit) vor oder gleich `jetzt`."""
    tage_zurueck = (jetzt.weekday() - FRAGE_WOCHENTAG) % 7
    termin = datetime.combine(jetzt.date() - timedelta(days=tage_zurueck), FRAGE_ZEIT, tzinfo=jetzt.tzinfo)
    if termin > jetzt:
        termin -= timedelta(days=7)
    return termin


async def km_frage_pruefen(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    dienst: Dienst = ctx.bot_data["dienst"]
    db, cfg = dienst.db, dienst.cfg
    jetzt = datetime.now(cfg.tz)

    # 1) Sonntagsfrage (auch nachgeholt, falls der Laptop um 18:00 aus war)
    termin = letzter_frage_termin(jetzt)
    gestellt = db.state_get("km_frage_termin")
    if gestellt is None or datetime.fromisoformat(gestellt) < termin:
        await ctx.bot.send_message(cfg.allowed_chat_id, "🏍 Km-Stand?")
        db.state_set("km_frage_termin", termin.isoformat())
        db.state_set("km_frage_seit", jetzt.isoformat())
        db.state_set("km_frage_nachgefragt", None)
        log.info("Km-Frage gesendet")
        return

    # 2) Einmal nachfragen, wenn 2 Tage keine Antwort kam
    seit = db.state_get("km_frage_seit")
    if seit and not db.state_get("km_frage_nachgefragt"):
        if jetzt - datetime.fromisoformat(seit) >= NACHFRAGE_NACH:
            await ctx.bot.send_message(cfg.allowed_chat_id, "🏍 Km-Stand? (Erinnerung, Sonntag kam keine Antwort)")
            db.state_set("km_frage_nachgefragt", "1")
            log.info("Km-Nachfrage gesendet")


async def tagescheck(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    dienst: Dienst = ctx.bot_data["dienst"]
    db, cfg = dienst.db, dienst.cfg
    lage = dienst.lage()
    neu = zeit_erinnerungen(lage.faelligkeiten, db.state_keys("erinnert:"), VORWARN_TAGE)
    if not neu:
        return
    zeilen = ["⏰ <b>Termin-Erinnerung</b>"]
    for _, f in neu:
        if f.rest_tage <= 0:
            zeilen.append(f"🔴 {escape(f.position.name)}: fällig {'heute' if f.rest_tage == 0 else 'seit ' + texte.dat(f.faellig_datum)}")
        else:
            zeilen.append(f"🟡 {escape(f.position.name)}: fällig am {texte.dat(f.faellig_datum)} (in {texte.tage(f.rest_tage)})")
    zeilen.append("\nErledigt? /erledigt &lt;position&gt;")
    await ctx.bot.send_message(cfg.allowed_chat_id, "\n".join(zeilen), parse_mode="HTML")
    for schluessel, _ in neu:
        db.state_set("erinnert:" + schluessel, lage.heute.isoformat())
    log.info("Termin-Erinnerungen gesendet: %s", [s for s, _ in neu])


async def backup_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    dienst: Dienst = ctx.bot_data["dienst"]
    cfg = dienst.cfg
    heute = dienst.heute()
    if ctx.job and ctx.job.name == "backup_start" and backup_heute_vorhanden(cfg.backup_dir, heute):
        return
    try:
        backup_erstellen(dienst.db, cfg.backup_dir, heute, cfg.backup_behalten)
    except Exception:
        log.exception("Backup fehlgeschlagen")


def jobs_einrichten(app: Application, dienst: Dienst) -> None:
    tz = dienst.cfg.tz
    jq = app.job_queue
    # PTB: days 0=Sonntag … 6=Samstag
    jq.run_daily(km_frage_pruefen, FRAGE_ZEIT.replace(tzinfo=tz), days=(0,), name="km_frage")
    jq.run_repeating(km_frage_pruefen, interval=3600, first=60, name="km_frage_stuendlich")
    jq.run_daily(tagescheck, TAGESCHECK_ZEIT.replace(tzinfo=tz), name="tagescheck")
    jq.run_once(tagescheck, 30, name="tagescheck_start")
    jq.run_daily(backup_job, BACKUP_ZEIT.replace(tzinfo=tz), name="backup")
    jq.run_once(backup_job, 10, name="backup_start")
