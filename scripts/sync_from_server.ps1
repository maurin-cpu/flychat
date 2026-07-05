# sync_from_server.ps1
# --------------------
# NUR auf dem LOKALEN WINDOWS-DEV-PC ausfuehren (PowerShell).
#
# Holt in EINEM Befehl den kompletten Server-Stand, damit man lokal exakt die
# gleiche Ansicht hat wie der Server - OHNE lokal die Analyse-/Wetter-Pipeline
# laufen zu lassen:
#   1. git pull            -> Code + getrackte Analysen (region_analyses_en.json ...)
#   2. scp vom Server      -> die gitignorten Runtime-Daten (wetterdaten.json ~200 MB,
#                             spot_analyses.json, region_analyses.json, data/history/)
#
# Voraussetzung: Windows-OpenSSH (ssh/scp). Test:  ssh deploy@178.105.39.152 "echo ok"
#
# Server-Adresse festlegen (eine der drei Varianten):
#   a) Datei .dev_server im Repo-Root:            deploy@178.105.39.152
#   b) Argument:   .\scripts\sync_from_server.ps1 deploy@178.105.39.152
#   c) Default unten (SERVER_DEFAULT).
#
param(
  [string]$Server = ""
)
$ErrorActionPreference = "Stop"

$SERVER_DEFAULT = "deploy@178.105.39.152"
$REMOTE_DIR     = "/home/deploy/flychat"

# Repo-Root ermitteln und dorthin wechseln
$root = (git rev-parse --show-toplevel).Trim()
Set-Location $root

# Server-Adresse: Argument > .dev_server > Default
if (-not $Server) {
  if (Test-Path ".dev_server") { $Server = (Get-Content ".dev_server" -First 1).Trim() }
}
if (-not $Server) { $Server = $SERVER_DEFAULT }

$RUNTIME_FILES = @(
  "data/region_analyses.json",
  "data/spot_analyses.json",
  "data/wetterdaten.json"      # gross (~200 MB) -> zuletzt
)

Write-Host "== 1) git pull (Code + getrackte Analysen) =="
git pull --no-rebase

Write-Host "== 2) Runtime-Daten vom Server holen ($Server) =="
foreach ($f in $RUNTIME_FILES) {
  Write-Host "   scp $f ..."
  scp "${Server}:$REMOTE_DIR/$f" $f
}
Write-Host "   scp data/history/ ..."
New-Item -ItemType Directory -Force -Path "data" | Out-Null
scp -r "${Server}:$REMOTE_DIR/data/history" "data/"

Write-Host ""
Write-Host "FERTIG. Lokal ist jetzt der Server-Stand da (Code + Analysen + Wetterdaten)."
