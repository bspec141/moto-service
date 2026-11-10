"""Eingaben verstehen: km-Zahlen, Datumsangaben, unscharfe Positionsnamen."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date, timedelta

_KM = re.compile(r"^\d{1,3}(?:['’ ]\d{3})+$|^\d+$")


def parse_km(text: str) -> int | None:
    """'14250', "14'250", '14 250', '14250 km' → 14250. Sonst None."""
    s = text.strip().lower()
    if s.endswith("km"):
        s = s[:-2].strip()
    if not _KM.match(s):
        return None
    return int(re.sub(r"\D", "", s))


def parse_datum(text: str, heute: date) -> date | None:
    """'heute', 'gestern', '12.4.2026', '12.4.26', '12.4.' (laufendes Jahr), '2026-04-12'."""
    s = text.strip().lower()
    if s == "heute":
        return heute
    if s == "gestern":
        return heute - timedelta(days=1)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return date.fromisoformat(s)
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})?", s)
        if m:
            jahr = m.group(3)
            j = heute.year if not jahr else (2000 + int(jahr) if len(jahr) == 2 else int(jahr))
            return date(j, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    return None


_CHF = re.compile(r"^(?:chf)?(\d+(?:[.,]\d{1,2})?)(?:chf|fr\.?|\.-)$|^chf(\d+(?:[.,]\d{1,2})?)$", re.I)
WER_WORTE = {"selbst": "selbst", "werkstatt": "Werkstatt"}


@dataclass
class ErledigtArgs:
    position: str
    km: int | None
    datum: date | None
    wer: str | None = None
    kosten_chf: float | None = None
    notiz: str | None = None


def parse_erledigt(args: list[str], heute: date) -> ErledigtArgs:
    """'/erledigt kette 14300 3.11. selbst 12chf -- Motul' → alle Felder.

    Reihenfolge egal. `selbst`/`werkstatt` = wer, `45chf`/`chf45`/`45.-` = Kosten,
    alles nach `--` = Notiz. Die übrigen Wörter sind die Position.
    """
    notiz = None
    if "--" in args:
        i = args.index("--")
        notiz = " ".join(args[i + 1:]).strip() or None
        args = args[:i]
    worte: list[str] = []
    km = datum = wer = kosten = None
    for a in args:
        if a.casefold() in WER_WORTE and wer is None:
            wer = WER_WORTE[a.casefold()]
            continue
        m = _CHF.match(a)
        if m and kosten is None:
            kosten = float((m.group(1) or m.group(2)).replace(",", "."))
            continue
        d = parse_datum(a, heute)
        if d is not None and datum is None:
            datum = d
            continue
        k = parse_km(a)
        if k is not None and km is None:
            km = k
            continue
        worte.append(a)
    return ErledigtArgs(" ".join(worte).strip(), km, datum, wer, kosten, notiz)


def _norm(s: str) -> str:
    s = s.casefold().strip()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)


def finde_position(eingabe: str, namen: list[str]) -> list[str]:
    """Unscharfes Matching. Liefert die Kandidaten (1 = eindeutig, 0 = nichts gefunden).

    Reihenfolge: exakter Name → Name beginnt mit Eingabe / Wort beginnt mit Eingabe
    → Eingabe ist Teil des Namens → Ähnlichkeit (Tippfehler).
    """
    e = _norm(eingabe)
    if not e:
        return []
    norm = {n: _norm(n) for n in namen}

    exakt = [n for n, v in norm.items() if v == e]
    if exakt:
        return exakt
    wortanfang = [n for n, v in norm.items() if v.startswith(e) or any(w.startswith(e) for w in v.split())]
    if wortanfang:
        return wortanfang
    teil = [n for n, v in norm.items() if e in v]
    if teil:
        return teil

    # Tippfehler: ganze Namen und einzelne Wörter vergleichen
    treffer: dict[str, float] = {}
    for n, v in norm.items():
        for kandidat in [v, *v.split()]:
            r = difflib.SequenceMatcher(None, e, kandidat).ratio()
            if r >= 0.7:
                treffer[n] = max(treffer.get(n, 0), r)
    if not treffer:
        return []
    beste = max(treffer.values())
    # klar bester Treffer → eindeutig, sonst alle ähnlichen zur Auswahl
    nahe = [n for n, r in sorted(treffer.items(), key=lambda x: -x[1]) if beste - r < 0.1]
    return nahe
