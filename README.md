# moto-service

Telegram-Bot für den Wartungsstand der **Suzuki Inazuma 250 (2014)**. Er erinnert an fällige Services nach Kilometern **und** nach Zeit. Fällig ist, was zuerst erreicht wird.

- Läuft auf Windows 10 als Dienst (NSSM), Python 3.12, kein Docker
- Telegram per Long Polling: kein Port-Forwarding, kein Webhook
- SQLite (`moto.db`), Konfiguration in `.env`, Zeitzone Europe/Zurich

## Inhalt
1. [Bedienung](#bedienung)
2. [Setup](#setup)
3. [Bot bei @BotFather erstellen](#bot-bei-botfather-erstellen)
4. [Chat-ID herausfinden](#chat-id-herausfinden)
5. [YAML-Format (Seed-Daten)](#yaml-format-seed-daten)
6. [Als Windows-Dienst einrichten (NSSM)](#als-windows-dienst-einrichten-nssm)
7. [Logs, Backup, Tests](#logs-backup-tests)
8. [Projektstruktur und Logik](#projektstruktur-und-logik)

---

## Bedienung

| Eingabe | Wirkung |
| --- | --- |
| `14250` (nur eine Zahl) | km-Stand speichern, danach Übersicht: Überfälliges und Baldiges zuerst, OK nur kurz |
| `/status` | aktuelle Übersicht |
| `/erledigt <position> [km] [datum]` | Service eintragen. Ohne km gilt der letzte Stand, ohne Datum heute |
| `/historie [position]` | letzte 10 Einträge (alle oder eine Position) |
| `/plan` | Wartungsplan |
| `/neu` | neue Position hinzufügen (geführter Dialog, `/abbrechen` bricht ab) |
| `/export` | `service_log.csv` und `km_log.csv` (Semikolon, öffnet direkt in Excel) |

**`/erledigt` im Detail.** Die Reihenfolge der Angaben ist egal:

```
/erledigt kette
/erledigt öl 14300 3.11.
/erledigt bremsflüssigkeit 12.10.2026 werkstatt 65chf -- Garage Muster
```

- Position wird unscharf gesucht: `kette` → „Kette schmieren“, `oel` → „Öl“. Ist sie unklar (`filter`), kommen Buttons zur Auswahl.
- Datum: `heute`, `gestern`, `3.11.`, `3.11.26`, `3.11.2026`, `2026-11-03`
- km: `14300` oder `14'300`
- `selbst` / `werkstatt` → Feld *wer*. `45chf`, `chf45` oder `45.-` → Kosten
- alles nach `--` → Notiz

**Automatisch:**
- Jeden **Sonntag 18:00** fragt der Bot „Km-Stand?“. Ohne Antwort fragt er nach 2 Tagen einmal nach. War der Laptop um 18:00 aus, holt er die Frage nach.
- **Täglich 09:00** (und beim Start) prüft er alle Positionen mit Zeit-Intervall (MFK, Bremsflüssigkeit …). Er meldet sich 30 Tage vorher und am Fälligkeitstag, je einmal pro Termin.
- **Status:** 🔴 ÜBERFÄLLIG (Fälligkeit erreicht) · 🟡 BALD (≤ 500 km oder ≤ 30 Tage, einstellbar) · 🟢 OK
- **Prognose:** Ø km/Tag aus den km-Meldungen der letzten 60 Tage → „voraussichtlich in ca. N Tagen“
- **Plausibilität:** Der km-Stand darf nicht sinken. Bei mehr als 2000 km seit der letzten Meldung fragt der Bot nach (Ja/Nein).
- Positionen ohne einen einzigen Eintrag gelten als **ÜBERFÄLLIG („noch nie erfasst“)**, bis du sie mit `/erledigt` oder über `historie.yaml` einträgst.
- Nachrichten aus anderen Chats als `ALLOWED_CHAT_ID` werden ignoriert (nur im Log vermerkt).

---

## Setup

### Einfach: Doppelklick

1. Projekt nach `C:\moto-service` holen (`git clone` oder ZIP entpacken).
2. **`installieren.cmd` doppelklicken** und die Admin-Rückfrage mit Ja bestätigen.

Das Programm installiert bei Bedarf Python 3.12 (über winget), legt `.venv` an, installiert die Pakete, fragt den Bot-Token ab, holt die Chat-ID selbst (du schreibst dem Bot einfach eine Nachricht) und richtet den **Autostart** ein: eine Aufgabe `moto-service` in der Windows-Aufgabenplanung. Sie startet den Bot mit Windows, auch ohne Anmeldung, und startet ihn nach Absturz oder Netzwerkausfall neu. Am Netzteil werden Ruhezustand und Zuklappen-Aktion ausgeschaltet.

- Nochmals ausführen ist gefahrlos (z.B. nach `git pull`, um Pakete zu aktualisieren und den Bot neu zu starten).
- `deinstallieren.cmd` entfernt den Autostart. Daten bleiben erhalten.
- Logs: `logs\moto-service.log`, Startprobleme in `logs\fehler.log` und `logs\start.log`.

Die Abschnitte unten (manuelles Setup, NSSM) brauchst du dann nicht.

### Automatische Updates

Der Laptop holt alle 10 Minuten den Stand von `main` aus GitHub. Gibt es Änderungen (z.B. neue Einträge in `data/historie.yaml` oder ein angepasster Wartungsplan), übernimmt er sie und startet den Bot neu. Du musst also nicht mehr auf den Laptop zugreifen: Änderung ins Repo pushen, fertig.

Weil das Repo privat ist, braucht der Laptop einen Token, der nur lesen darf:

1. GitHub → Profilbild → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
2. Name z.B. `moto-laptop`, Ablauf möglichst lang (oder „No expiration“, falls angeboten)
3. **Repository access:** *Only select repositories* → `moto-service`
4. **Permissions → Repository permissions → Contents:** *Read-only* (sonst nichts)
5. Token kopieren und bei `installieren.cmd` einfügen, wenn danach gefragt wird.

Der Token liegt in `.github-token` (nicht im Repo, nur für SYSTEM und Administratoren lesbar). Läuft er ab: neuen erstellen und `installieren.cmd` nochmals ausführen. Updates und Fehler stehen in `logs\start.log`.

Gut zu wissen:
- Einträge in den YAML-Dateien werden nur **hinzugefügt**. Einen Eintrag ändern (z.B. andere km) ergibt einen zusätzlichen Eintrag; löschen geht über die YAML nicht.
- Auf dem Laptop selbst keine Dateien im Projekt ändern, sonst kann das Update nicht übernommen werden (`.env`, `moto.db`, `logs` sind davon nicht betroffen).

### Manuell

Voraussetzung: **Python 3.12** von python.org. Beim Installer „Add python.exe to PATH“ anhaken.

In PowerShell (Beispielpfad `C:\moto-service`):

```powershell
cd C:\
git clone <dein-repo-url> moto-service
cd C:\moto-service
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
notepad .env
```

In `.env` `BOT_TOKEN` und `ALLOWED_CHAT_ID` eintragen (siehe die nächsten zwei Abschnitte). Dann testen:

```powershell
.\.venv\Scripts\python -m moto_service
```

Im Telegram-Chat mit dem Bot `/status` senden. Beenden mit `Ctrl+C`. Danach als Dienst einrichten.

Optionale Werte in `.env`:

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `BALD_KM` | 500 | Schwelle für BALD in km |
| `BALD_TAGE` | 30 | Schwelle für BALD in Tagen |
| `SPRUNG_KM` | 2000 | ab diesem Sprung fragt der Bot nach |
| `BACKUP_BEHALTEN` | 30 | Anzahl Backups |
| `ZEITZONE` | Europe/Zurich | |

---

## Bot bei @BotFather erstellen

1. In Telegram **@BotFather** öffnen (blauer Haken) und `/newbot` senden.
2. Anzeigename eingeben, z.B. `Moto Service`.
3. Benutzername eingeben. Er muss auf `bot` enden, z.B. `hamed_moto_bot`.
4. BotFather schickt den **Token** (`123456789:AA…`). Ihn in `.env` als `BOT_TOKEN` eintragen.
   Den Token niemandem zeigen. Falls er doch rausgeht: bei BotFather `/revoke`.
5. Optional: `/setprivacy` → Enable, `/setjoingroups` → Disable (der Bot ist nur für dich).

Die Befehlsliste (Menü „/“) setzt der Bot beim Start selbst.

## Chat-ID herausfinden

**Variante A (ohne Hilfsmittel):**
1. Dem neuen Bot in Telegram irgendeine Nachricht schicken, z.B. `hallo`.
2. Im Browser öffnen (Token einsetzen): `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. In der Antwort steht `"chat":{"id":123456789,…}`. Diese Zahl ist deine Chat-ID → `ALLOWED_CHAT_ID`.
   Die Liste ist leer? Bot kurz stoppen, Nachricht nochmals senden, Seite neu laden.

**Variante B:** `ALLOWED_CHAT_ID=1` setzen, Bot starten und ihm schreiben. Im Log (`logs\moto-service.log`) steht `Ignoriert: Nachricht aus fremdem Chat 123456789`. Diese Zahl eintragen und den Bot neu starten.

---

## YAML-Format (Seed-Daten)

Beim Start gleicht der Bot `data/wartungsplan.yaml` und `data/historie.yaml` mit der Datenbank ab. Du kannst die Dateien jederzeit ergänzen und den Dienst neu starten (`nssm restart moto-service`).

**Regeln beim Abgleich**
- **Positionen:** Schlüssel ist der Name (Gross/klein egal). Neue werden angelegt, bestehende aktualisiert (Intervalle, Notiz). Positionen aus `/neu` bleiben erhalten. Löschen geht über die YAML nicht, das schützt die Historie.
- **Services und km-Stände:** Nur neue Einträge werden übernommen. Duplikat = gleiche Position + Datum + km (bzw. gleiches Datum + km).
- Fehlerhafte Einträge (unbekannte Position, km sinkt, kein Intervall) werden übersprungen und im Log gemeldet. Der Bot startet trotzdem.

### `data/wartungsplan.yaml`

```yaml
positionen:
  - position: Öl              # Pflicht, eindeutig
    intervall_km: 6000        # optional
    intervall_monate: 12      # optional (mindestens eines der beiden)
    notiz: "10W-40"           # optional
  - position: MFK
    intervall_monate: 36
```

> Die mitgelieferten Intervalle sind **Beispielwerte**. Gleiche sie mit der Bedienungsanleitung oder deiner Werkstatt ab.

### `data/historie.yaml`

```yaml
km_stand:                     # abgelesene km-Stände
  - datum: 2026-10-04         # yyyy-mm-dd (oder "04.10.2026" in Anführungszeichen)
    km: 13980

services:                     # ausgeführte Wartungen
  - position: Öl              # Name wie im Wartungsplan
    datum: 2026-03-21
    km: 11800                 # optional, empfohlen; wird auch als km-Stand übernommen
    wer: selbst               # optional: selbst / Werkstattname
    kosten_chf: 38.50         # optional
    notiz: Motul 10W-40       # optional
```

Für den Start reicht: pro Position die **letzte** Ausführung plus der **aktuelle km-Stand**.

> Die Beispiel-Einträge vor dem ersten echten Start durch deine Daten ersetzen. Sonst sind sie in der Datenbank. Sie über die YAML wieder zu entfernen geht nicht. In dem Fall `moto.db` löschen (nur solange noch nichts Echtes drin ist) und neu starten.

---

## Als Windows-Dienst einrichten (NSSM)

NSSM startet den Bot beim Booten, auch ohne Anmeldung, und startet ihn nach einem Absturz neu.

1. **NSSM herunterladen:** <https://nssm.cc/download> → `nssm-2.24.zip` entpacken. `win64\nssm.exe` nach `C:\nssm\nssm.exe` kopieren.
2. **PowerShell als Administrator** öffnen.
3. Dienst anlegen (Pfade anpassen):

```powershell
C:\nssm\nssm.exe install moto-service "C:\moto-service\.venv\Scripts\python.exe" "-m moto_service"
C:\nssm\nssm.exe set moto-service AppDirectory "C:\moto-service"
C:\nssm\nssm.exe set moto-service DisplayName "moto-service (Telegram-Wartungsbot)"
C:\nssm\nssm.exe set moto-service Start SERVICE_AUTO_START
C:\nssm\nssm.exe set moto-service AppExit Default Restart
C:\nssm\nssm.exe set moto-service AppRestartDelay 10000
C:\nssm\nssm.exe set moto-service AppThrottle 30000
C:\nssm\nssm.exe set moto-service AppEnvironmentExtra PYTHONUTF8=1 PYTHONUNBUFFERED=1
C:\nssm\nssm.exe set moto-service AppStdout "C:\moto-service\logs\nssm.log"
C:\nssm\nssm.exe set moto-service AppStderr "C:\moto-service\logs\nssm.log"
C:\nssm\nssm.exe set moto-service AppRotateFiles 1
C:\nssm\nssm.exe set moto-service AppRotateBytes 1000000
```

4. Starten und prüfen:

```powershell
mkdir C:\moto-service\logs -Force
C:\nssm\nssm.exe start moto-service
C:\nssm\nssm.exe status moto-service
Get-Content C:\moto-service\logs\moto-service.log -Tail 20
```

`SERVICE_RUNNING` = läuft. Im Log steht `Long Polling läuft`.

**Weitere Befehle**

| Zweck | Befehl |
| --- | --- |
| Neustart (z.B. nach YAML-Änderung oder Update) | `C:\nssm\nssm.exe restart moto-service` |
| Stoppen | `C:\nssm\nssm.exe stop moto-service` |
| Einstellungen im Fenster ändern | `C:\nssm\nssm.exe edit moto-service` |
| Entfernen | `C:\nssm\nssm.exe remove moto-service confirm` |

**Update:** `git pull`, `.\.venv\Scripts\pip install -r requirements.txt`, Dienst neu starten.

**Laptop als Server: Energieoptionen**

Sonst schläft der Laptop ein und der Bot ist weg:
- Einstellungen → System → Netzbetrieb und Energiesparen → *Energiesparmodus (Netzbetrieb)*: **Nie**
- Systemsteuerung → Energieoptionen → *Auswählen, was beim Zuklappen des Computers geschehen soll* → Netzbetrieb: **Nichts unternehmen**
- Windows Update → Erweiterte Optionen → Nutzungszeit setzen, damit Neustarts nachts passieren. Der Dienst startet danach von selbst.

Fällt das WLAN aus, versucht der Bot es von selbst weiter. Verpasste Sonntagsfragen und Termin-Erinnerungen holt er nach.

---

## Logs, Backup, Tests

- **Log:** `logs\moto-service.log`, rotiert bei 1 MB, 5 alte Dateien. Der Bot-Token wird nicht geloggt.
- **Backup:** täglich 03:00 und beim Start, falls heute noch keins existiert. Ziel ist `backup\moto-JJJJ-MM-TT.db`, die letzten 30 bleiben. Wiederherstellen: Dienst stoppen, Backup als `moto.db` kopieren, Dienst starten.
- **Tests:**

```powershell
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest
```

Getestet werden die Fälligkeitslogik (km, Zeit, beides, Grenzfälle, Prognose, Sortierung), die Plausibilität, Termin-Erinnerungen, Eingaben (km, Datum, unscharfe Namen), der YAML-Abgleich, das Backup und die Bot-Handler gegen einen simulierten Telegram-Server.

Die Tests nutzen feste Beispieldaten in `tests/fixtures/data/`. Deine echten Daten in `data/` kannst du also frei ändern, ohne dass Tests brechen. `tests/test_daten.py` prüft zusätzlich, dass `data/wartungsplan.yaml` und `data/historie.yaml` fehlerfrei importiert werden (keine unbekannte Position, kein sinkender km-Stand). Nach jeder Änderung an den YAML-Dateien also kurz `pytest` laufen lassen.

---

## Projektstruktur und Logik

```
moto_service/
  config.py    .env laden
  db.py        SQLite-Schema, Abfragen, YAML-Abgleich
  logik.py     Fälligkeit, Status, Prognose, Plausibilität, Termin-Erinnerungen (reine Funktionen)
  eingabe.py   km/Datum parsen, /erledigt-Argumente, unscharfes Matching
  dienst.py    verbindet DB und Logik
  texte.py     Antworttexte
  bot.py       Telegram-Handler, Buttons, Dialog /neu, Zugriffsschutz
  jobs.py      Sonntagsfrage, Nachfrage, Tagescheck, Backup
  backup.py    SQLite-Backup mit Aufräumen
  __main__.py  Start, Logging
data/          wartungsplan.yaml, historie.yaml (deine echten Daten)
windows/       installieren.ps1, lauf.ps1 (Autostart), deinstallieren.ps1
tests/         fixtures/data/ = feste Testdaten
```

**Datenbank**

| Tabelle | Felder |
| --- | --- |
| `wartungsplan` | id, position, intervall_km, intervall_monate, notiz |
| `service_log` | id, position_id, datum, km, wer, kosten_chf, notiz |
| `km_log` | id, datum, km |
| `bot_state` | key, value (Merker: Km-Frage offen, Erinnerung gesendet …) |

Ein Service mit km erzeugt auch einen Eintrag im `km_log`. Das verbessert die Prognose.

**Berechnung pro Position**
- Fällig bei km = km der letzten Ausführung + `intervall_km`
- Fällig am = Datum der letzten Ausführung + `intervall_monate` (31.01. + 1 Monat = 28./29.02.)
- ÜBERFÄLLIG, sobald einer der beiden Punkte erreicht ist (genau erreicht zählt schon). BALD, wenn einer innerhalb der Schwelle liegt.
- Prognose: (letzter − erster km-Stand im 60-Tage-Fenster) / Tage dazwischen. Mindestens 2 Meldungen an verschiedenen Tagen nötig.
