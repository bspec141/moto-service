"""Telegram-Handler: Befehle, km-Meldungen, Inline-Buttons, Dialog /neu."""
from __future__ import annotations

import csv
import io
import logging
from datetime import date
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from . import texte
from .config import Config
from .dienst import Dienst
from .eingabe import ErledigtArgs, finde_position, parse_erledigt, parse_km
from .logik import Position

log = logging.getLogger(__name__)


def _dienst(ctx: ContextTypes.DEFAULT_TYPE) -> Dienst:
    return ctx.bot_data["dienst"]


async def _senden(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    await update.effective_chat.send_message(text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                             disable_web_page_preview=True)


def _ja_nein() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Ja, speichern", callback_data="conf:ja"),
                                  InlineKeyboardButton("Nein", callback_data="conf:nein")]])


# --- Zugriffsschutz -----------------------------------------------------------

async def waechter(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Läuft vor allen anderen Handlern. Fremde Chats werden still ignoriert."""
    cfg: Config = _dienst(ctx).cfg
    chat = update.effective_chat
    if chat is None or chat.id != cfg.allowed_chat_id:
        if chat is not None:
            log.info("Ignoriert: Nachricht aus fremdem Chat %s", chat.id)
        raise ApplicationHandlerStop


# --- Übersicht / km -----------------------------------------------------------

async def _uebersicht_senden(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lage = _dienst(ctx).lage()
    await _senden(update, texte.uebersicht(lage.faelligkeiten, lage.aktueller_km, lage.heute, lage.km_tag))


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _senden(update, texte.HILFE)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _uebersicht_senden(update, ctx)


async def text_nachricht(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    km = parse_km(update.effective_message.text or "")
    if km is None:
        await _senden(update, "Nicht verstanden. Schick den km-Stand als Zahl oder /hilfe.")
        return
    d = _dienst(ctx)
    pruefung = d.pruefe_km(km)
    if not pruefung.ok:
        await _senden(update, f"❌ {pruefung.grund}")
        return
    if pruefung.rueckfrage:
        ctx.chat_data["pending"] = {"art": "km", "km": km}
        await _senden(update, f"⚠️ {texte.km(km)} km? {pruefung.grund}\nStimmt das?", _ja_nein())
        return
    await _km_speichern(update, ctx, km)


async def _km_speichern(update: Update, ctx: ContextTypes.DEFAULT_TYPE, km: int) -> None:
    _dienst(ctx).km_melden(km)
    log.info("km gespeichert: %s", km)
    await _uebersicht_senden(update, ctx)


# --- /erledigt ----------------------------------------------------------------

def _args_normalisieren(args: list[str]) -> list[str]:
    # iOS macht aus "--" gern einen Gedankenstrich
    return ["--" if a in ("—", "–") else a for a in args]


def _positions_buttons(positionen: list[Position]) -> InlineKeyboardMarkup:
    reihen, reihe = [], []
    for p in positionen:
        reihe.append(InlineKeyboardButton(p.name, callback_data=f"erl:{p.id}"))
        if len(reihe) == 2:
            reihen.append(reihe)
            reihe = []
    if reihe:
        reihen.append(reihe)
    reihen.append([InlineKeyboardButton("Abbrechen", callback_data="erl:x")])
    return InlineKeyboardMarkup(reihen)


async def cmd_erledigt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    d = _dienst(ctx)
    a = parse_erledigt(_args_normalisieren(ctx.args or []), d.heute())
    positionen = d.db.positionen()
    if not positionen:
        await _senden(update, "Wartungsplan ist leer. /neu fügt eine Position hinzu.")
        return
    ctx.chat_data["erledigt"] = a
    namen = finde_position(a.position, [p.name for p in positionen]) if a.position else []
    if len(namen) == 1:
        pos = next(p for p in positionen if p.name == namen[0])
        await _erledigt_ausfuehren(update, ctx, pos, a)
        return
    auswahl = [p for p in positionen if p.name in namen] or positionen
    frage = "Welche Position?" if a.position else "Was wurde erledigt?"
    if a.position and not namen:
        frage = f"„{escape(a.position)}“ nicht gefunden. Welche Position?"
    await _senden(update, frage, _positions_buttons(auswahl))


def _km_am(km_log: list[tuple[date, int]], datum: date) -> int | None:
    werte = [km for d, km in km_log if d <= datum]
    return max(werte) if werte else None


async def _erledigt_ausfuehren(update: Update, ctx: ContextTypes.DEFAULT_TYPE, pos: Position, a: ErledigtArgs,
                               bestaetigt: bool = False) -> None:
    d = _dienst(ctx)
    heute = d.heute()
    datum = a.datum or heute
    if datum > heute:
        await _senden(update, "❌ Datum liegt in der Zukunft.")
        return
    km = a.km
    if km is not None and not bestaetigt:
        pruefung = d.pruefe_km(km, datum)
        if not pruefung.ok:
            await _senden(update, f"❌ {pruefung.grund}")
            return
        if pruefung.rueckfrage:
            ctx.chat_data["pending"] = {"art": "erledigt", "pos_id": pos.id, "args": a}
            await _senden(update, f"⚠️ {texte.km(km)} km? {pruefung.grund}\nStimmt das?", _ja_nein())
            return
    if km is None:
        km = _km_am(d.db.km_log(), datum)  # ohne km = letzter Stand (am Datum)

    neu = d.db.service_speichern(pos.id, datum, km, a.wer, a.kosten_chf, a.notiz)
    if a.km is not None and datum == heute:
        d.km_melden(a.km, datum)  # zählt auch als Antwort auf die Km-Frage
    if not neu:
        await _senden(update, f"ℹ️ {escape(pos.name)} am {texte.dat(datum)} ist schon eingetragen.")
        return
    log.info("Service gespeichert: %s %s %s km", pos.name, datum, km)
    f = next((x for x in d.lage().faelligkeiten if x.position.id == pos.id), None)
    text = f"✅ <b>{escape(pos.name)}</b> erledigt: {texte.dat(datum)} · {texte.km(km)} km"
    if f is not None:
        naechst = []
        if f.faellig_km is not None:
            naechst.append(f"{texte.km(f.faellig_km)} km")
        if f.faellig_datum is not None:
            naechst.append(texte.dat(f.faellig_datum))
        if naechst:
            text += f"\nNächstes Mal: {' oder '.join(naechst)} (was zuerst kommt)"
    await _senden(update, text)


# --- Inline-Buttons -----------------------------------------------------------

async def callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    daten = q.data or ""
    d = _dienst(ctx)

    if daten.startswith("erl:"):
        a: ErledigtArgs | None = ctx.chat_data.pop("erledigt", None)
        if daten == "erl:x" or a is None:
            await q.edit_message_text("Abgebrochen." if a else "Abgelaufen, bitte /erledigt neu senden.")
            return
        pos = d.db.position_nach_id(int(daten[4:]))
        if pos is None:
            await q.edit_message_text("Position nicht mehr vorhanden.")
            return
        await q.edit_message_text(f"→ {pos.name}")
        await _erledigt_ausfuehren(update, ctx, pos, a)
        return

    if daten.startswith("conf:"):
        pending = ctx.chat_data.pop("pending", None)
        if pending is None:
            await q.edit_message_text("Abgelaufen, bitte neu senden.")
            return
        if daten == "conf:nein":
            await q.edit_message_text("Nicht gespeichert.")
            return
        await q.edit_message_text("Bestätigt.")
        if pending["art"] == "km":
            await _km_speichern(update, ctx, pending["km"])
        else:
            pos = d.db.position_nach_id(pending["pos_id"])
            if pos:
                await _erledigt_ausfuehren(update, ctx, pos, pending["args"], bestaetigt=True)


# --- /historie /plan /export --------------------------------------------------

async def cmd_historie(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    d = _dienst(ctx)
    suche = " ".join(ctx.args or []).strip()
    if not suche:
        await _senden(update, texte.historie(d.db.historie(limit=10), "🗂 <b>Letzte Services</b>"))
        return
    positionen = d.db.positionen()
    namen = finde_position(suche, [p.name for p in positionen])
    if not namen:
        await _senden(update, f"„{escape(suche)}“ nicht gefunden. /plan zeigt alle Positionen.")
        return
    teile = []
    for name in namen:
        pos = next(p for p in positionen if p.name == name)
        teile.append(texte.historie(d.db.historie(pos.id, limit=10), f"🗂 <b>{escape(pos.name)}</b>"))
    await _senden(update, "\n\n".join(teile))


async def cmd_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _senden(update, texte.plan(_dienst(ctx).db.positionen()))


def _csv(kopf: list[str], zeilen: list[list]) -> io.BytesIO:
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=";")  # Semikolon + BOM: öffnet direkt in Excel (CH)
    w.writerow(kopf)
    w.writerows(zeilen)
    return io.BytesIO(puffer.getvalue().encode("utf-8-sig"))


async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    d = _dienst(ctx)
    heute = d.heute().isoformat()
    services = d.db.historie(limit=0)
    s = _csv(["datum", "position", "km", "wer", "kosten_chf", "notiz"],
             [[e.datum.isoformat(), e.position, e.km if e.km is not None else "", e.wer or "",
               f"{e.kosten_chf:.2f}" if e.kosten_chf is not None else "", e.notiz or ""]
              for e in reversed(services)])
    k = _csv(["datum", "km"], [[dt.isoformat(), km] for dt, km in d.db.km_log()])
    await update.effective_chat.send_document(s, filename=f"service_log_{heute}.csv")
    await update.effective_chat.send_document(k, filename=f"km_log_{heute}.csv")


# --- /neu (geführter Dialog) --------------------------------------------------

NAME, INT_KM, INT_MONATE, NOTIZ = range(4)


def _optional_zahl(text: str) -> tuple[bool, int | None]:
    """(gültig, Wert). '-', 'nein', 'keins' = kein Wert."""
    t = text.strip().lower()
    if t in ("-", "nein", "keins", "kein", "0"):
        return True, None
    z = parse_km(t)
    return (z is not None and z > 0), z


async def neu_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.chat_data["neu"] = {}
    await _senden(update, "➕ Neue Position. Wie heisst sie? (/abbrechen zum Abbrechen)")
    return NAME


async def neu_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.effective_message.text or "").strip()
    vorhanden = {p.name.casefold() for p in _dienst(ctx).db.positionen()}
    if not name or len(name) > 60:
        await _senden(update, "Bitte einen Namen mit 1–60 Zeichen.")
        return NAME
    if name.casefold() in vorhanden:
        await _senden(update, "Diese Position gibt es schon. Anderer Name?")
        return NAME
    ctx.chat_data["neu"]["name"] = name
    await _senden(update, "Intervall in <b>km</b>? (Zahl, oder <code>-</code> für keins)")
    return INT_KM


async def neu_km(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ok, wert = _optional_zahl(update.effective_message.text or "")
    if not ok:
        await _senden(update, "Bitte eine Zahl oder <code>-</code>.")
        return INT_KM
    ctx.chat_data["neu"]["km"] = wert
    await _senden(update, "Intervall in <b>Monaten</b>? (Zahl, oder <code>-</code> für keins)")
    return INT_MONATE


async def neu_monate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ok, wert = _optional_zahl(update.effective_message.text or "")
    if not ok or (wert is not None and wert > 240):
        await _senden(update, "Bitte eine Zahl (1–240) oder <code>-</code>.")
        return INT_MONATE
    if wert is None and ctx.chat_data["neu"].get("km") is None:
        await _senden(update, "Mindestens ein Intervall ist nötig. Intervall in <b>km</b>?")
        return INT_KM
    ctx.chat_data["neu"]["monate"] = wert
    await _senden(update, "Notiz? (oder <code>-</code>)")
    return NOTIZ


async def neu_notiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    t = (update.effective_message.text or "").strip()
    n = ctx.chat_data.pop("neu")
    notiz = None if t in ("-", "") else t
    p = Position(0, n["name"], n["km"], n["monate"], notiz)
    _dienst(ctx).db.position_speichern(p.name, p.intervall_km, p.intervall_monate, notiz)
    log.info("Neue Position: %s", p)
    await _senden(update, f"✅ <b>{escape(p.name)}</b> hinzugefügt: {texte.intervall(p)}\n"
                          f"Schon gemacht? <code>/erledigt {escape(p.name)} [km] [datum]</code>")
    return ConversationHandler.END


async def neu_abbrechen(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.chat_data.pop("neu", None)
    await _senden(update, "Abgebrochen.")
    return ConversationHandler.END


async def cmd_abbrechen(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ctx.chat_data.pop("pending", None)
    ctx.chat_data.pop("erledigt", None)
    await _senden(update, "Nichts offen.")


async def fehler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Fehler im Handler", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await update.effective_chat.send_message("⚠️ Interner Fehler, Details im Log.")
        except Exception:
            pass


# --- Aufbau -------------------------------------------------------------------

def handler_registrieren(app: Application) -> None:
    app.add_handler(TypeHandler(Update, waechter), group=-1)
    text = filters.TEXT & ~filters.COMMAND
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("neu", neu_start)],
        states={
            NAME: [MessageHandler(text, neu_name)],
            INT_KM: [MessageHandler(text, neu_km)],
            INT_MONATE: [MessageHandler(text, neu_monate)],
            NOTIZ: [MessageHandler(text, neu_notiz)],
        },
        fallbacks=[CommandHandler("abbrechen", neu_abbrechen)],
        conversation_timeout=600,
    ))
    app.add_handler(CommandHandler(["start", "hilfe", "help"], cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("erledigt", cmd_erledigt))
    app.add_handler(CommandHandler("historie", cmd_historie))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("abbrechen", cmd_abbrechen))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(text, text_nachricht))
    app.add_error_handler(fehler)
