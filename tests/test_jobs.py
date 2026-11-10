from datetime import datetime
from zoneinfo import ZoneInfo

from moto_service.jobs import letzter_frage_termin

TZ = ZoneInfo("Europe/Zurich")


def test_letzter_termin_mitten_in_der_woche():
    t = letzter_frage_termin(datetime(2026, 11, 11, 10, 0, tzinfo=TZ))  # Mittwoch
    assert t == datetime(2026, 11, 8, 18, 0, tzinfo=TZ)


def test_sonntag_vor_18_uhr_zaehlt_vorwoche():
    assert letzter_frage_termin(datetime(2026, 11, 8, 17, 59, tzinfo=TZ)).day == 1


def test_sonntag_genau_18_uhr():
    assert letzter_frage_termin(datetime(2026, 11, 8, 18, 0, tzinfo=TZ)) == datetime(2026, 11, 8, 18, 0, tzinfo=TZ)
