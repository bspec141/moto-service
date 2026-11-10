# moto-service – Einrichtung auf Windows 10/11
# Installiert Python (falls nötig), die Abhängigkeiten, fragt Token und Chat-ID ab
# und richtet den Autostart ein: Der Bot läuft ab Systemstart, auch ohne Anmeldung,
# und startet sich nach Abstürzen selbst neu.

$ErrorActionPreference = 'Stop'
$TaskName = 'moto-service'
$Platzhalter = '123456789:ABCdefGhIJKlmNoPQRstuVWxyz'

# --- Als Administrator neu starten -------------------------------------------
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Schritt($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fertig($text)  { Write-Host "    $text" -ForegroundColor Green }
function Abbruch($text) {
    Write-Host "`nFEHLER: $text" -ForegroundColor Red
    Read-Host "`nEnter zum Schliessen"
    exit 1
}

function Bot-Stoppen {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like '*moto_service*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Finde-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in '3.12', '3.13') {
            try {
                # PS 5.1 macht aus umgeleitetem stderr einen Fehler → abfangen
                $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $exe) { return "$exe".Trim() }
            } catch {}
        }
    }
    foreach ($p in "$env:ProgramFiles\Python312\python.exe", "$env:ProgramFiles\Python313\python.exe",
                   "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                   "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe") {
        if (Test-Path $p) { return $p }
    }
    return $null
}

Write-Host "moto-service einrichten in $root" -ForegroundColor White

# --- 1. Python ---------------------------------------------------------------
Schritt "Python suchen"
$python = Finde-Python
if (-not $python) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Start-Process 'https://www.python.org/downloads/release/python-3129/'
        Abbruch "Python 3.12 fehlt. Bitte von python.org installieren (Haken bei 'Add python.exe to PATH') und dieses Programm nochmals starten."
    }
    Write-Host "    Python 3.12 wird installiert (dauert 1-2 Minuten) ..."
    & winget install --id Python.Python.3.12 -e --scope machine --silent --accept-package-agreements --accept-source-agreements
    $python = Finde-Python
    if (-not $python) { Abbruch "Python-Installation hat nicht geklappt. Bitte Python 3.12 von python.org installieren." }
}
Fertig "Python: $python"

# --- 2. Virtuelle Umgebung und Pakete ----------------------------------------
Schritt "Pakete installieren"
Bot-Stoppen
$venvPy = Join-Path $root '.venv\Scripts\python.exe'
if ((Test-Path (Join-Path $root '.venv')) -and -not (Test-Path $venvPy)) {
    Remove-Item -Recurse -Force (Join-Path $root '.venv')   # kaputte Umgebung
}
if (-not (Test-Path $venvPy)) {
    & $python -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) { Abbruch "Virtuelle Umgebung konnte nicht angelegt werden." }
}
& $venvPy -m pip install --disable-pip-version-check -q -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Abbruch "Pakete konnten nicht installiert werden (Internet?)." }
Fertig "Pakete installiert"

# --- 3. Token und Chat-ID (.env) ---------------------------------------------
Schritt "Telegram einrichten"
$envDatei = Join-Path $root '.env'
if (-not (Test-Path $envDatei)) { Copy-Item (Join-Path $root '.env.example') $envDatei }
$zeilen = @(Get-Content $envDatei -Encoding UTF8)

function Wert($name) {
    $z = $zeilen | Where-Object { $_ -match "^\s*$name\s*=" } | Select-Object -First 1
    if ($z) { return ($z -split '=', 2)[1].Trim() } else { return '' }
}
function Setze($name, $wert) {
    $neu = @(); $gefunden = $false
    foreach ($z in $script:zeilen) {
        if ($z -match "^\s*$name\s*=") { $neu += "$name=$wert"; $gefunden = $true } else { $neu += $z }
    }
    if (-not $gefunden) { $neu += "$name=$wert" }
    $script:zeilen = $neu
}

$token = Wert 'BOT_TOKEN'
$bot = $null
while ($true) {
    if ($token -and $token -ne $Platzhalter) {
        try {
            $bot = (Invoke-RestMethod "https://api.telegram.org/bot$token/getMe").result
            break
        } catch { Write-Host "    Token wird von Telegram nicht akzeptiert." -ForegroundColor Yellow }
    }
    $token = (Read-Host "    Bot-Token von @BotFather einfügen (Rechtsklick = einfügen)").Trim()
}
Setze 'BOT_TOKEN' $token
Fertig "Bot: @$($bot.username)"

$chat = Wert 'ALLOWED_CHAT_ID'
if (-not ($chat -match '^-?\d+$') -or $chat -eq '123456789' -or $chat -eq '1') {
    Write-Host "    Öffne jetzt Telegram und schreib deinem Bot @$($bot.username) eine Nachricht (z.B. hallo)."
    Write-Host "    Warte auf die Nachricht ..."
    $chat = $null
    for ($i = 0; $i -lt 100 -and -not $chat; $i++) {
        try {
            $u = Invoke-RestMethod "https://api.telegram.org/bot$token/getUpdates"
            $ids = @($u.result | ForEach-Object { $_.message.chat.id } | Where-Object { $_ })
            if ($ids.Count -gt 0) { $chat = $ids[-1] }
        } catch {}
        if (-not $chat) { Start-Sleep -Seconds 3 }
    }
    if (-not $chat) { Abbruch "Keine Nachricht erhalten. Dem Bot schreiben und dieses Programm nochmals starten." }
}
Setze 'ALLOWED_CHAT_ID' $chat
# UTF-8 ohne BOM, sonst liest python-dotenv die erste Zeile falsch
[IO.File]::WriteAllLines($envDatei, [string[]]$zeilen, (New-Object Text.UTF8Encoding $false))
Fertig "Chat-ID: $chat (in .env gespeichert)"

# --- 4. Automatische Updates aus GitHub --------------------------------------
Schritt "Automatische Updates aus GitHub"
$RepoUrl = 'https://github.com/bspec141/moto-service.git'
$tokenDatei = Join-Path $root '.github-token'
function Finde-Git {
    $g = (Get-Command git -ErrorAction SilentlyContinue).Source
    if (-not $g -and (Test-Path "$env:ProgramFiles\Git\cmd\git.exe")) { $g = "$env:ProgramFiles\Git\cmd\git.exe" }
    return $g
}
function Git-Mit($tok) {
    $env:GIT_TERMINAL_PROMPT = '0'
    $ErrorActionPreference = 'Continue'   # PS 5.1: git-Meldungen auf stderr sonst = Abbruch
    $opt = @('-C', $root, '-c', 'safe.directory=*', '-c', 'credential.helper=')
    if ($tok) {
        $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$tok"))
        $opt += @('-c', "http.https://github.com/.extraheader=AUTHORIZATION: basic $b64")
    }
    & $script:git @opt @args 2>$null
}
$git = Finde-Git
if (-not $git -and (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "    Git wird installiert ..."
    & winget install --id Git.Git -e --scope machine --silent --accept-package-agreements --accept-source-agreements
    $git = Finde-Git
}
if (-not $git) {
    Write-Host "    Git fehlt – ohne Git keine automatischen Updates (Bot läuft trotzdem)." -ForegroundColor Yellow
} else {
    $tok = if (Test-Path $tokenDatei) { (Get-Content $tokenDatei -Raw).Trim() } else { '' }
    $oeffentlich = $false
    Git-Mit '' ls-remote -q $RepoUrl main | Out-Null
    if ($LASTEXITCODE -eq 0) {   # Repo öffentlich: kein Token nötig
        $oeffentlich = $true
        $tok = ''
        if (Test-Path $tokenDatei) { Remove-Item -Force $tokenDatei }
    }
    while (-not $oeffentlich) {
        if ($tok) {
            try { Git-Mit $tok ls-remote -q $RepoUrl main | Out-Null } catch {}
            if ($LASTEXITCODE -eq 0) { break }
            Write-Host "    GitHub akzeptiert den Token nicht (abgelaufen oder falsche Rechte)." -ForegroundColor Yellow
        }
        Write-Host "    Das Repo ist privat. Für Updates braucht der Laptop einen GitHub-Token mit Leserecht"
        Write-Host "    (Anleitung im README, Abschnitt 'Automatische Updates'). Leer lassen = ohne Updates."
        $tok = (Read-Host "    GitHub-Token einfügen").Trim()
        if (-not $tok) { break }
    }
    if ($oeffentlich -or $tok) {
        if ($tok) {
            [IO.File]::WriteAllText($tokenDatei, $tok, (New-Object Text.UTF8Encoding $false))
            # nur SYSTEM und Administratoren dürfen den Token lesen
            & icacls $tokenDatei /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
        }
        if (-not (Test-Path (Join-Path $root '.git'))) {
            # Projekt kam als ZIP: Git-Verwaltung nachrüsten, lokale Dateien (.env, moto.db) bleiben
            Git-Mit $tok init -q -b main | Out-Null
            Git-Mit $tok remote add origin $RepoUrl | Out-Null
        }
        Git-Mit $tok fetch -q origin main
        $hatCommits = $true
        try { Git-Mit $tok rev-parse -q --verify HEAD | Out-Null; $hatCommits = ($LASTEXITCODE -eq 0) } catch { $hatCommits = $false }
        if ($hatCommits) { Git-Mit $tok merge -q --ff-only FETCH_HEAD | Out-Null }
        else { Git-Mit $tok checkout -q -f -B main FETCH_HEAD | Out-Null }
        if ($LASTEXITCODE -eq 0) { Fertig "Updates aktiv: Der Laptop holt Änderungen alle 10 Minuten selbst" }
        else { Write-Host "    Stand konnte nicht abgeglichen werden (lokal geänderte Dateien?). Siehe logs\start.log." -ForegroundColor Yellow }
    } else {
        Write-Host "    Ohne Token: keine automatischen Updates." -ForegroundColor Yellow
    }
}

# --- 5. Autostart (Aufgabenplanung) ------------------------------------------
Schritt "Autostart einrichten"
$lauf = Join-Path $PSScriptRoot 'lauf.ps1'
$aktion = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $root `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$lauf`""
$ausloeser = @(New-ScheduledTaskTrigger -AtStartup)
try {
    # Zusätzlich alle 5 Minuten prüfen: läuft der Bot nicht (mehr), wird er gestartet
    $ausloeser += New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
} catch {}
$einst = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$wer = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $aktion -Trigger $ausloeser -Settings $einst -Principal $wer `
    -Description 'Telegram-Wartungsbot (moto-service)' -Force | Out-Null
Fertig "Aufgabe '$TaskName' angelegt: startet mit Windows, auch ohne Anmeldung"

# --- 6. Energieoptionen (nur am Netzteil) ------------------------------------
Schritt "Energieoptionen am Netzteil: kein Ruhezustand, Zuklappen = nichts tun"
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change hibernate-timeout-ac 0 | Out-Null
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0 | Out-Null
powercfg /setactive SCHEME_CURRENT | Out-Null
Fertig "Gesetzt (im Akkubetrieb bleibt alles wie vorher)"

# --- 7. Starten und prüfen ---------------------------------------------------
Schritt "Bot starten"
$log = Join-Path $root 'logs\moto-service.log'
$vorher = if (Test-Path $log) { (Get-Item $log).Length } else { 0 }
Start-ScheduledTask -TaskName $TaskName
$ok = $false
for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
    Start-Sleep -Seconds 2
    if ((Test-Path $log) -and (Get-Item $log).Length -gt $vorher) {
        $ok = [bool](Select-String -Path $log -Pattern 'Long Polling' -SimpleMatch -Quiet)
    }
}
if ($ok) {
    Fertig "Bot läuft. Schick ihm in Telegram /status"
} else {
    Write-Host "    Bot hat sich noch nicht gemeldet. Details:" -ForegroundColor Yellow
    foreach ($f in 'logs\fehler.log', 'logs\moto-service.log') {
        $p = Join-Path $root $f
        if (Test-Path $p) { Write-Host "    --- $f"; Get-Content $p -Tail 15 }
    }
}
Read-Host "`nEnter zum Schliessen"
