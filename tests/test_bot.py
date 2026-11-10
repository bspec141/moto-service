"""End-to-End-Test der Handler mit simuliertem Telegram-Server (kein Netzwerk)."""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from telegram import Update
from telegram.ext import Application
from telegram.request import BaseRequest

from moto_service.bot import handler_registrieren
from moto_service.config import Config
from moto_service.db import Datenbank, importiere_seed
from moto_service.dienst import Dienst

CHAT = 4242
DATA = Path(__file__).resolve().parent.parent / "data"


class FakeRequest(BaseRequest):
    def __init__(self):
        self.gesendet: list[tuple[str, dict]] = []

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, read_timeout=None, write_timeout=None,
                         connect_timeout=None, pool_timeout=None):
        endpunkt = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        self.gesendet.append((endpunkt, params))
        if endpunkt == "getMe":
            res = {"id": 1, "is_bot": True, "first_name": "moto", "username": "moto_bot"}
        elif endpunkt in ("sendMessage", "editMessageText", "sendDocument"):
            res = {"message_id": len(self.gesendet), "date": 0, "chat": {"id": CHAT, "type": "private"},
                   "text": params.get("text", "")}
        else:
            res = True
        return 200, json.dumps({"ok": True, "result": res}).encode()


class Bot:
    def __init__(self, tmp_path):
        cfg = Config("1:x", CHAT, ZoneInfo("Europe/Zurich"), tmp_path / "t.db", DATA, tmp_path, tmp_path)
        db = Datenbank(cfg.db_path)
        importiere_seed(db, DATA)
        self.dienst = Dienst(db, cfg)
        self.req = FakeRequest()
        self.app = Application.builder().token("1:x").request(self.req).get_updates_request(FakeRequest()).build()
        self.app.bot_data["dienst"] = self.dienst
        handler_registrieren(self.app)
        self.uid = 0

    async def __aenter__(self):
        await self.app.initialize()
        return self

    async def __aexit__(self, *a):
        await self.app.shutdown()

    def _naechste(self):
        self.uid += 1
        return self.uid

    async def schreibe(self, text, chat=CHAT) -> list[str]:
        self.req.gesendet.clear()
        entities = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}] if text.startswith("/") else []
        u = {"update_id": self._naechste(), "message": {
            "message_id": self.uid, "date": int(datetime.now().timestamp()), "text": text, "entities": entities,
            "chat": {"id": chat, "type": "private"}, "from": {"id": chat, "is_bot": False, "first_name": "H"}}}
        await self.app.process_update(Update.de_json(u, self.app.bot))
        return self.texte()

    async def tippe(self, data) -> list[str]:
        self.req.gesendet.clear()
        u = {"update_id": self._naechste(), "callback_query": {
            "id": str(self.uid), "chat_instance": "c", "data": data,
            "from": {"id": CHAT, "is_bot": False, "first_name": "H"},
            "message": {"message_id": 1, "date": 0, "text": "x", "chat": {"id": CHAT, "type": "private"}}}}
        await self.app.process_update(Update.de_json(u, self.app.bot))
        return self.texte()

    def texte(self):
        return [p.get("text", "") for e, p in self.req.gesendet if e in ("sendMessage", "editMessageText")]

    def buttons(self):
        for e, p in reversed(self.req.gesendet):
            if "reply_markup" in p:
                m = p["reply_markup"]
                m = json.loads(m) if isinstance(m, str) else m
                return [b["callback_data"] for reihe in m["inline_keyboard"] for b in reihe]
        return []


def lauf(coro):
    return asyncio.run(coro)


def test_fremder_chat_wird_ignoriert(tmp_path):
    async def t():
        async with Bot(tmp_path) as b:
            assert await b.schreibe("/status", chat=999) == []
    lauf(t())


def test_km_meldung_und_uebersicht(tmp_path):
    async def t():
        async with Bot(tmp_path) as b:
            out = await b.schreibe("14250")
            assert len(out) == 1 and "14'250 km" in out[0]
            assert out[0].index("ÜBERFÄLLIG") < out[0].index("OK (")
            assert b.dienst.db.aktueller_km() == 14250
            assert "nicht sinken" in (await b.schreibe("14000"))[0]
    lauf(t())


def test_km_sprung_rueckfrage(tmp_path):
    async def t():
        async with Bot(tmp_path) as b:
            out = await b.schreibe("17000")
            assert "Stimmt das?" in out[0] and b.dienst.db.aktueller_km() == 13980
            await b.tippe("conf:ja")
            assert b.dienst.db.aktueller_km() == 17000
            await b.schreibe("20000")
            await b.tippe("conf:nein")
            assert b.dienst.db.aktueller_km() == 17000
    lauf(t())


def test_erledigt_eindeutig(tmp_path):
    async def t():
        async with Bot(tmp_path) as b:
            out = await b.schreibe("/erledigt kette selbst")
            assert "Kette schmieren" in out[0] and "13'980 km" in out[0] and "14'580 km" in out[0]
            e = b.dienst.db.historie(limit=1)[0]
            assert e.position == "Kette schmieren" and e.wer == "selbst"
    lauf(t())


def test_erledigt_mehrdeutig_buttons(tmp_path):
    async def t():
        async with Bot(tmp_path) as b:
            out = await b.schreibe("/erledigt filter 14000")
            assert "Welche Position?" in out[0]
            knoepfe = b.buttons()
            assert len(knoepfe) == 3  # Ölfilter, Luftfilter, Abbrechen
            luft = next(p.id for p in b.dienst.db.positionen() if p.name == "Luftfilter")
            out = await b.tippe(f"erl:{luft}")
            assert any("Luftfilter" in x and "erledigt" in x for x in out)
            assert b.dienst.db.aktueller_km() == 14000
    lauf(t())


def test_neu_dialog(tmp_path):
    async def t():
        async with Bot(tmp_path) as b:
            await b.schreibe("/neu")
            assert "schon" in (await b.schreibe("öl"))[0]
            await b.schreibe("Reifen")
            await b.schreibe("-")
            assert "Mindestens" in (await b.schreibe("-"))[0]
            await b.schreibe("15000")
            await b.schreibe("60")
            out = await b.schreibe("Pirelli")
            assert "Reifen" in out[0] and "15'000 km / 60 Mt." in out[0]
            assert any(p.name == "Reifen" for p in b.dienst.db.positionen())
    lauf(t())


def test_plan_historie_export(tmp_path):
    async def t():
        async with Bot(tmp_path) as b:
            assert "Wartungsplan" in (await b.schreibe("/plan"))[0]
            assert "Motul" in (await b.schreibe("/historie öl"))[0]
            await b.schreibe("/export")
            assert [e for e, _ in b.req.gesendet].count("sendDocument") == 2
    lauf(t())


def test_jobs_frage_nachfrage_erinnerung(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from moto_service import jobs

    async def t():
        async with Bot(tmp_path) as b:
            ctx = SimpleNamespace(bot=b.app.bot, bot_data=b.app.bot_data, job=None)
            tz = ZoneInfo("Europe/Zurich")
            uhr = {"jetzt": datetime(2026, 11, 8, 18, 0, tzinfo=tz)}

            class FakeDT(datetime):
                @classmethod
                def now(cls, tz=None):
                    return uhr["jetzt"]
            monkeypatch.setattr(jobs, "datetime", FakeDT)

            b.req.gesendet.clear()
            await jobs.km_frage_pruefen(ctx)
            assert b.texte() == ["🏍 Km-Stand?"]
            b.req.gesendet.clear()
            await jobs.km_frage_pruefen(ctx)                    # kein zweites Mal
            uhr["jetzt"] = datetime(2026, 11, 10, 17, 0, tzinfo=tz)
            await jobs.km_frage_pruefen(ctx)                    # noch keine 2 Tage
            assert b.texte() == []
            uhr["jetzt"] = datetime(2026, 11, 10, 18, 5, tzinfo=tz)
            await jobs.km_frage_pruefen(ctx)
            assert "Erinnerung" in b.texte()[0]
            b.req.gesendet.clear()
            uhr["jetzt"] = datetime(2026, 11, 12, 18, 5, tzinfo=tz)
            await jobs.km_frage_pruefen(ctx)                    # nur einmal nachfragen
            assert b.texte() == []

            # Antwort stoppt die Nachfrage
            uhr["jetzt"] = datetime(2026, 11, 15, 18, 0, tzinfo=tz)
            await jobs.km_frage_pruefen(ctx)
            await b.schreibe("14100")
            b.req.gesendet.clear()
            uhr["jetzt"] = datetime(2026, 11, 18, 18, 0, tzinfo=tz)
            await jobs.km_frage_pruefen(ctx)
            assert b.texte() == []

            # Termin-Erinnerung: Bremsflüssigkeit (02.12.2024 + 24 Mt.) ist in < 30 Tagen fällig
            b.req.gesendet.clear()
            await jobs.tagescheck(ctx)
            assert "Bremsflüssigkeit" in b.texte()[0]
            b.req.gesendet.clear()
            await jobs.tagescheck(ctx)
            assert b.texte() == []
    lauf(t())
