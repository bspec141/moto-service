# Startet den Bot, startet ihn nach Absturz/Netzwerkausfall neu und holt alle 10 Minuten
# Änderungen aus dem GitHub-Repo (z.B. neue Einträge in data/*.yaml). Gibt es welche,
# wird der Bot mit dem neuen Stand neu gestartet.
# Läuft über die Aufgabe "moto-service" (Aufgabenplanung) ab Systemstart.
$ErrorActionPreference = 'Continue'
$root  = Split-Path -Parent $PSScriptRoot
$py    = Join-Path $root '.venv\Scripts\python.exe'
$logs  = Join-Path $root 'logs'
$token = Join-Path $root '.github-token'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$env:GIT_TERMINAL_PROMPT = '0'
$UpdateAlle = [TimeSpan]::FromMinutes(10)

function Log($text) { Add-Content -Path (Join-Path $logs 'start.log') -Value "$(Get-Date -Format s)  $text" }

function Starte {
    Start-Process -FilePath $py -ArgumentList '-m', 'moto_service' -WorkingDirectory $root `
        -NoNewWindow -PassThru -RedirectStandardError (Join-Path $logs 'fehler.log')
}

function Stoppe {
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like '*moto_service*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

$gitExe = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $gitExe -and (Test-Path "$env:ProgramFiles\Git\cmd\git.exe")) { $gitExe = "$env:ProgramFiles\Git\cmd\git.exe" }

function Git {
    $opt = @('-C', $root, '-c', 'safe.directory=*', '-c', 'credential.helper=')
    if (Test-Path $token) {   # nur nötig, falls das Repo privat ist
        $t = (Get-Content $token -Raw).Trim()
        $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$t"))
        $opt += @('-c', "http.https://github.com/.extraheader=AUTHORIZATION: basic $b64")
    }
    & $gitExe @opt @args 2>$null
}

# Rückgabe: 'nichts', 'neustart' (Bot neu starten) oder 'skript' (lauf.ps1 selbst geändert)
function Update {
    if (-not $gitExe -or -not (Test-Path (Join-Path $root '.git'))) { return 'nichts' }
    try {
        $alt = "$(Git rev-parse HEAD)".Trim()
        Git fetch -q origin main
        if ($LASTEXITCODE -ne 0) { Log "Update: fetch fehlgeschlagen (Internet?)"; return 'nichts' }
        $neu = "$(Git rev-parse FETCH_HEAD)".Trim()
        if (-not $neu -or $neu -eq $alt) { return 'nichts' }
        $dateien = @(Git diff --name-only $alt $neu)
        Git merge -q --ff-only FETCH_HEAD
        if ($LASTEXITCODE -ne 0) { Log "Update: merge fehlgeschlagen (lokal geänderte Dateien?)"; return 'nichts' }
        Log "Update: $($alt.Substring(0,7)) -> $($neu.Substring(0,7)) ($($dateien -join ', '))"
        if ($dateien -contains 'requirements.txt') {
            & $py -m pip install --disable-pip-version-check -q -r (Join-Path $root 'requirements.txt') 2>$null
        }
        if ($dateien -contains 'windows/lauf.ps1') { return 'skript' }
        return 'neustart'
    } catch { Log "Update: Fehler $_"; return 'nichts' }
}

$bot = $null
$naechstesUpdate = Get-Date
while ($true) {
    if ((Get-Date) -ge $naechstesUpdate) {
        $naechstesUpdate = (Get-Date) + $UpdateAlle
        switch (Update) {
            'neustart' { Stoppe; $bot = $null }
            'skript'   { Stoppe; Log "lauf.ps1 geändert, Aufgabe startet in ein paar Minuten neu"; exit 0 }
        }
    }
    if (-not $bot -or $bot.HasExited) {
        if ($bot) { Log "Bot beendet (Code $($bot.ExitCode)), Neustart in 30 s"; Start-Sleep -Seconds 30 }
        $bot = Starte
    }
    Start-Sleep -Seconds 15
}
