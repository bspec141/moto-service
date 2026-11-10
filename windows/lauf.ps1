# Startet den Bot und startet ihn nach einem Absturz oder Netzwerkausfall automatisch neu.
# Wird von der Aufgabe "moto-service" in der Windows-Aufgabenplanung beim Systemstart ausgeführt.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$py   = Join-Path $root '.venv\Scripts\python.exe'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'

while ($true) {
    $p = Start-Process -FilePath $py -ArgumentList '-m', 'moto_service' -WorkingDirectory $root `
        -NoNewWindow -Wait -PassThru -RedirectStandardError (Join-Path $logs 'fehler.log')
    Add-Content -Path (Join-Path $logs 'start.log') -Value "$(Get-Date -Format s)  Bot beendet (Code $($p.ExitCode)), Neustart in 30 s"
    Start-Sleep -Seconds 30
}
