"""SQLite-Zugriff: Schema, Abfragen und Abgleich mit den YAML-Seed-Dateien."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

import yaml

from .logik import Ausfuehrung, Position, pruefe_km

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS wartungsplan (
    id               INTEGER PRIMARY KEY,
    position         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    intervall_km     INTEGER CHECK (intervall_km > 0),
    intervall_monate INTEGER CHECK (intervall_monate > 0),
    notiz            TEXT,
    CHECK (intervall_km IS NOT NULL OR intervall_monate IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS service_log (
    id          INTEGER PRIMARY KEY,
    position_id INTEGER NOT NULL REFERENCES wartungsplan(id),
    datum       TEXT NOT NULL,               -- ISO yyyy-mm-dd
    km          INTEGER,
    wer         TEXT,                        -- z.B. "selbst" oder Werkstattname
    kosten_chf  REAL,
    notiz       TEXT
);
-- Duplikat = gleiche Position + Datum + km
CREATE UNIQUE INDEX IF NOT EXISTS ux_service ON service_log(position_id, datum, IFNULL(km, -1));
CREATE TABLE IF NOT EXISTS km_log (
    id    INTEGER PRIMARY KEY,
    datum TEXT NOT NULL,
    km    INTEGER NOT NULL CHECK (km >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_km ON km_log(datum, km);
CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


@dataclass(frozen=True)
class ServiceEintrag:
    id: int
    position: str
    datum: date
    km: int | None
    wer: str | None
    kosten_chf: float | None
    notiz: str | None


class Datenbank:
    def __init__(self, pfad: Path | str):
        self.pfad = str(pfad)
        with self._con() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def _con(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.pfad)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            with con:  # Transaktion: commit oder rollback
                yield con
        finally:
            con.close()

    # --- Wartungsplan -------------------------------------------------------

    def positionen(self) -> list[Position]:
        with self._con() as con:
            rows = con.execute("SELECT * FROM wartungsplan ORDER BY position COLLATE NOCASE").fetchall()
        return [Position(r["id"], r["position"], r["intervall_km"], r["intervall_monate"], r["notiz"]) for r in rows]

    def position_nach_id(self, pid: int) -> Position | None:
        return next((p for p in self.positionen() if p.id == pid), None)

    def position_speichern(self, name: str, intervall_km: int | None, intervall_monate: int | None,
                           notiz: str | None) -> int:
        """Legt eine Position an oder aktualisiert sie (Schlüssel: Name, ohne Gross/klein)."""
        name = name.strip()
        with self._con() as con:
            # SQLite-NOCASE kennt nur ASCII ("Öl" ≠ "öl"), darum Vergleich in Python
            rows = con.execute("SELECT id, position FROM wartungsplan").fetchall()
            pid = next((r["id"] for r in rows if r["position"].casefold() == name.casefold()), None)
            if pid is None:
                cur = con.execute(
                    "INSERT INTO wartungsplan (position, intervall_km, intervall_monate, notiz) VALUES (?, ?, ?, ?)",
                    (name, intervall_km, intervall_monate, notiz))
                return cur.lastrowid
            con.execute(
                "UPDATE wartungsplan SET position = ?, intervall_km = ?, intervall_monate = ?, notiz = ? WHERE id = ?",
                (name, intervall_km, intervall_monate, notiz, pid))
            return pid

    # --- km_log -------------------------------------------------------------

    def km_log(self) -> list[tuple[date, int]]:
        with self._con() as con:
            rows = con.execute("SELECT datum, km FROM km_log ORDER BY datum, km").fetchall()
        return [(date.fromisoformat(r["datum"]), r["km"]) for r in rows]

    def aktueller_km(self) -> int | None:
        with self._con() as con:
            r = con.execute("SELECT MAX(km) FROM km_log").fetchone()
        return r[0]

    def letzte_km_meldung(self) -> tuple[date, int] | None:
        with self._con() as con:
            r = con.execute("SELECT datum, km FROM km_log ORDER BY datum DESC, km DESC LIMIT 1").fetchone()
        return (date.fromisoformat(r["datum"]), r["km"]) if r else None

    def km_speichern(self, datum: date, km: int) -> bool:
        """True, wenn neu gespeichert (False = gleicher Eintrag existiert schon)."""
        with self._con() as con:
            cur = con.execute("INSERT OR IGNORE INTO km_log (datum, km) VALUES (?, ?)", (datum.isoformat(), km))
            return cur.rowcount == 1

    # --- service_log --------------------------------------------------------

    def service_speichern(self, position_id: int, datum: date, km: int | None, wer: str | None = None,
                          kosten_chf: float | None = None, notiz: str | None = None) -> bool:
        """Speichert einen Service und – falls km angegeben – auch einen Punkt im km_log.

        Rückgabe: True = neu, False = Duplikat (gleiche Position + Datum + km).
        Der km-Punkt wird nur übernommen, wenn er zum bisherigen km_log passt.
        """
        with self._con() as con:
            cur = con.execute(
                """INSERT OR IGNORE INTO service_log (position_id, datum, km, wer, kosten_chf, notiz)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (position_id, datum.isoformat(), km, wer, kosten_chf, notiz),
            )
            neu = cur.rowcount == 1
        if km is not None:
            if pruefe_km(km, datum, self.km_log(), sprung_km=10**9).ok:
                self.km_speichern(datum, km)
            else:
                log.warning("km %s am %s passt nicht zum km_log, nicht übernommen", km, datum)
        return neu

    def letzte_ausfuehrungen(self) -> dict[int, Ausfuehrung]:
        """Pro Position die jüngste Ausführung (nach Datum, dann km)."""
        with self._con() as con:
            rows = con.execute(
                """SELECT position_id, datum, km FROM service_log s
                   WHERE id = (SELECT id FROM service_log t WHERE t.position_id = s.position_id
                               ORDER BY datum DESC, IFNULL(km, -1) DESC LIMIT 1)"""
            ).fetchall()
        return {r["position_id"]: Ausfuehrung(date.fromisoformat(r["datum"]), r["km"]) for r in rows}

    def historie(self, position_id: int | None = None, limit: int = 10) -> list[ServiceEintrag]:
        sql = """SELECT s.id, w.position, s.datum, s.km, s.wer, s.kosten_chf, s.notiz
                 FROM service_log s JOIN wartungsplan w ON w.id = s.position_id"""
        args: tuple = ()
        if position_id is not None:
            sql += " WHERE s.position_id = ?"
            args = (position_id,)
        sql += " ORDER BY s.datum DESC, IFNULL(s.km, -1) DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._con() as con:
            rows = con.execute(sql, args).fetchall()
        return [ServiceEintrag(r["id"], r["position"], date.fromisoformat(r["datum"]), r["km"], r["wer"],
                               r["kosten_chf"], r["notiz"]) for r in rows]

    # --- Bot-Zustand (Merker) -----------------------------------------------

    def state_get(self, key: str) -> str | None:
        with self._con() as con:
            r = con.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
        return r[0] if r else None

    def state_set(self, key: str, value: str | None) -> None:
        with self._con() as con:
            if value is None:
                con.execute("DELETE FROM bot_state WHERE key = ?", (key,))
            else:
                con.execute("INSERT INTO bot_state (key, value) VALUES (?, ?) "
                            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def state_keys(self, prefix: str) -> set[str]:
        with self._con() as con:
            rows = con.execute("SELECT key FROM bot_state WHERE key LIKE ? || '%'", (prefix,)).fetchall()
        return {r[0][len(prefix):] for r in rows}

    # --- Backup -------------------------------------------------------------

    def backup_nach(self, ziel: Path) -> None:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        quelle = sqlite3.connect(self.pfad)
        dest = sqlite3.connect(str(ziel))
        try:
            quelle.backup(dest)
        finally:
            dest.close()
            quelle.close()


# --- Seed-Import ---------------------------------------------------------------

def _datum(wert) -> date:
    if isinstance(wert, date):
        return wert
    s = str(wert).strip()
    if "." in s:  # dd.mm.yyyy
        t, m, j = s.split(".")
        return date(int(j), int(m), int(t))
    return date.fromisoformat(s)


def _opt_int(wert) -> int | None:
    if wert is None or str(wert).strip() in ("", "-"):
        return None
    return int(str(wert).replace("'", "").replace("_", "").strip())


def _opt_float(wert) -> float | None:
    if wert is None or str(wert).strip() == "":
        return None
    return float(str(wert).replace(",", "."))


def _opt_str(wert) -> str | None:
    return str(wert).strip() if wert not in (None, "") else None


def importiere_seed(db: Datenbank, data_dir: Path) -> dict[str, int]:
    """Gleicht data/wartungsplan.yaml und data/historie.yaml mit der DB ab.

    - Positionen: neu anlegen oder aktualisieren (Schlüssel = Name). Positionen, die
      nur in der DB stehen (z.B. aus /neu), bleiben erhalten.
    - Services und km-Stände: nur Neues einfügen, Duplikate werden übersprungen.
    """
    zaehler = {"positionen": 0, "services_neu": 0, "km_neu": 0, "fehler": 0}

    plan_datei = data_dir / "wartungsplan.yaml"
    if plan_datei.exists():
        plan = yaml.safe_load(plan_datei.read_text(encoding="utf-8")) or {}
        for p in plan.get("positionen") or []:
            try:
                km, monate = _opt_int(p.get("intervall_km")), _opt_int(p.get("intervall_monate"))
                if not km and not monate:
                    raise ValueError("weder intervall_km noch intervall_monate")
                db.position_speichern(str(p["position"]), km, monate, _opt_str(p.get("notiz")))
                zaehler["positionen"] += 1
            except Exception as e:  # einzelne fehlerhafte Einträge nicht den Start verhindern lassen
                zaehler["fehler"] += 1
                log.error("wartungsplan.yaml: Eintrag %r übersprungen: %s", p, e)

    hist_datei = data_dir / "historie.yaml"
    if hist_datei.exists():
        hist = yaml.safe_load(hist_datei.read_text(encoding="utf-8")) or {}
        namen = {p.name.casefold(): p.id for p in db.positionen()}
        for k in hist.get("km_stand") or []:
            try:
                d, km = _datum(k["datum"]), _opt_int(k["km"])
                if not pruefe_km(km, d, db.km_log(), sprung_km=10**9).ok:
                    raise ValueError("passt nicht zu den übrigen km-Ständen (km sinkt)")
                zaehler["km_neu"] += db.km_speichern(d, km)
            except Exception as e:
                zaehler["fehler"] += 1
                log.error("historie.yaml km_stand %r übersprungen: %s", k, e)
        for s in hist.get("services") or []:
            try:
                pid = namen.get(str(s["position"]).strip().casefold())
                if pid is None:
                    raise ValueError(f"Position {s['position']!r} steht nicht im Wartungsplan")
                zaehler["services_neu"] += db.service_speichern(
                    pid, _datum(s["datum"]), _opt_int(s.get("km")), _opt_str(s.get("wer")),
                    _opt_float(s.get("kosten_chf")), _opt_str(s.get("notiz")),
                )
            except Exception as e:
                zaehler["fehler"] += 1
                log.error("historie.yaml service %r übersprungen: %s", s, e)

    log.info("Seed-Abgleich: %s", zaehler)
    return zaehler
