"""Antworttexte (Telegram HTML)."""
from __future__ import annotations

from datetime import date
from html import escape

from .db import ServiceEintrag
from .logik import Faelligkeit, Position, Status


def km(n: int | None) -> str:
    return "?" if n is None else f"{n:,}".replace(",", "'")


def dat(d: date | None) -> str:
    return "?" if d is None else d.strftime("%d.%m.%Y")


def tage(n: int) -> str:
    return "1 Tag" if n == 1 else f"{n} Tagen"


def intervall(p: Position) -> str:
    teile = []
    if p.intervall_km:
        teile.append(f"{km(p.intervall_km)} km")
    if p.intervall_monate:
        teile.append(f"{p.intervall_monate} Mt.")
    return " / ".join(teile)


def detail(f: Faelligkeit) -> str:
    """Kurze Beschreibung, wann eine Position fällig ist/war."""
    if f.nie_erfasst:
        return "noch nie erfasst"
    teile = []
    if f.rest_km is not None:
        if f.rest_km < 0:
            teile.append(f"seit {km(-f.rest_km)} km")
        elif f.rest_km == 0:
            teile.append("jetzt (km)")
        else:
            teile.append(f"in {km(f.rest_km)} km")
    elif f.faellig_km is not None:
        teile.append(f"bei {km(f.faellig_km)} km")
    elif f.position.intervall_km and f.letzte and f.letzte.km is None:
        teile.append("km der letzten Ausführung fehlt")
    if f.rest_tage is not None:
        if f.rest_tage < 0:
            teile.append(f"seit {tage(-f.rest_tage)} ({dat(f.faellig_datum)})")
        elif f.rest_tage == 0:
            teile.append("heute")
        else:
            teile.append(f"am {dat(f.faellig_datum)}")
    text = " · ".join(teile)
    if f.status != Status.UEBERFAELLIG and f.prognose_tage is not None and (
        f.rest_tage is None or f.prognose_tage < f.rest_tage
    ):
        text += f" (voraussichtlich in ca. {tage(f.prognose_tage)})"
    return text


def uebersicht(liste: list[Faelligkeit], aktueller_km: int | None, heute: date, km_tag: float | None) -> str:
    kopf = f"🏍 <b>{km(aktueller_km)} km</b> · {dat(heute)}"
    if km_tag is not None:
        kopf += f"\nØ {km_tag:.0f} km/Tag (60 Tage)"
    zeilen = [kopf]

    ueber = [f for f in liste if f.status == Status.UEBERFAELLIG]
    bald = [f for f in liste if f.status == Status.BALD]
    ok = [f for f in liste if f.status == Status.OK]
    if ueber:
        zeilen.append("\n🔴 <b>ÜBERFÄLLIG</b>")
        zeilen += [f"• {escape(f.position.name)}: {detail(f)}" for f in ueber]
    if bald:
        zeilen.append("\n🟡 <b>BALD</b>")
        zeilen += [f"• {escape(f.position.name)}: {detail(f)}" for f in bald]
    if ok:
        zeilen.append(f"\n🟢 <b>OK ({len(ok)})</b>: " + ", ".join(escape(f.position.name) for f in ok))
    if not liste:
        zeilen.append("\nWartungsplan ist leer.")
    return "\n".join(zeilen)


def plan(positionen: list[Position]) -> str:
    if not positionen:
        return "Wartungsplan ist leer. /neu fügt eine Position hinzu."
    zeilen = ["📋 <b>Wartungsplan</b>"]
    for p in positionen:
        z = f"• <b>{escape(p.name)}</b>: {intervall(p)}"
        if p.notiz:
            z += f"\n  <i>{escape(p.notiz)}</i>"
        zeilen.append(z)
    zeilen.append("\nFällig ist, was zuerst erreicht wird.")
    return "\n".join(zeilen)


def historie(eintraege: list[ServiceEintrag], titel: str) -> str:
    if not eintraege:
        return f"{titel}\nKeine Einträge."
    zeilen = [titel]
    for e in eintraege:
        z = f"• {dat(e.datum)} · {km(e.km)} km · {escape(e.position)}"
        extra = [x for x in (e.wer, f"CHF {e.kosten_chf:.2f}" if e.kosten_chf is not None else None, e.notiz) if x]
        if extra:
            z += f"\n  <i>{escape(' · '.join(extra))}</i>"
        zeilen.append(z)
    return "\n".join(zeilen)


HILFE = """🏍 <b>moto-service</b>
Schick einfach den km-Stand als Zahl (z.B. <code>14250</code>).

/status – Übersicht
/erledigt &lt;position&gt; [km] [datum] – Service eintragen
   z.B. <code>/erledigt kette</code> oder <code>/erledigt öl 14300 3.11.</code>
/historie [position] – letzte Einträge
/plan – Wartungsplan
/neu – Position hinzufügen
/export – CSV-Dateien
/abbrechen – laufenden Dialog abbrechen"""
