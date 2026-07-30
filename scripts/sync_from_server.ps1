# sync_from_server.ps1
# --------------------
# NUR auf dem LOKALEN WINDOWS-DEV-PC ausfuehren (PowerShell).
#
# Holt in EINEM Befehl den kompletten AKTUELLEN Server-Stand, damit man lokal
# exakt die gleiche Ansicht hat wie der Server - OHNE lokal die Pipeline laufen
# zu lassen.
#
# WICHTIG: Die App liest zur Laufzeit Dateien, die auf dem Server-DATENTRAEGER
# oft NEUER sind als der letzte git-Commit (der Analyse-Job schreibt taeglich,
# committet aber nur ~1x/Tag mit Versatz). Deshalb holen wir die
# view-relevanten Dateien direkt per scp vom Datentraeger - NICHT ueber git:
#   - config_overrides.json  (LANG=en etc. -> sonst laueft lokal Default-Deutsch)
#   - spot_analyses_en.json / region_analyses_en.json  (aktuelle Fliegbarkeit)
#   - wetterdaten.json  (~200 MB, Rohwetter fuer Meteogramme)
# git pull liefert nur den Code (+ die evtl. hinterherhinkenden getrackten Daten).
#
# Voraussetzung: Windows-OpenSSH (ssh/scp). Test:  ssh deploy@178.105.39.152 "echo ok"
# Server-Adresse: Argument > .dev_server-Datei > Default unten.
#
param(
  [string]$Server = "",
  [switch]$MitKarten          # auch die Roh-PNGs des Frontenarchivs holen
)
$ErrorActionPreference = "Continue"

$SERVER_DEFAULT = "deploy@178.105.39.152"
$REMOTE_DIR     = "/home/deploy/flychat"

$root = (git rev-parse --show-toplevel).Trim()
Set-Location $root

if (-not $Server) {
  if (Test-Path ".dev_server") { $Server = (Get-Content ".dev_server" -First 1).Trim() }
}
if (-not $Server) { $Server = $SERVER_DEFAULT }

# view-relevante Dateien, die wir vom Server-DATENTRAEGER holen (git hinkt hinterher):
$FROM_DISK = @(
  "data/config_overrides.json",
  "data/spot_analyses_en.json",
  "data/region_analyses_en.json",
  "data/wetterdaten.json"          # gross (~200 MB) -> zuletzt
)
# getrackte Analyse-Dateien: vor git pull lokale Aenderungen verwerfen, damit
# pull nicht mit "clean your working tree" abbricht (auch DE, falls frueher mal
# per scp ueberschrieben). Werden danach ggf. per scp neu geholt.
$TRACKED_DISK = @(
  "data/spot_analyses_en.json","data/region_analyses_en.json",
  "data/spot_analyses.json","data/region_analyses.json"
)

# getrackte Server-Daten, die lokal NIE gepusht werden duerfen (skip-worktree):
$NO_PUSH = @(
  "data/spot_analyses_en.json","data/region_analyses_en.json",
  "data/spot_analyses.json","data/region_analyses.json",
  "data/synoptic_context.json","data/labeled_examples.jsonl"
)
$extra = (git ls-files data/synoptic_audit data/weather_archive) 2>$null
if ($extra) { $NO_PUSH += ($extra -split "`n" | Where-Object { $_ }) }

Write-Host "== 0) getrackte Analysen fuer sauberen git pull freigeben =="
git update-index --no-skip-worktree $TRACKED_DISK 2>$null
git checkout -- $TRACKED_DISK 2>$null

Write-Host "== 1) git pull (nur Code relevant; Daten kommen unten frisch per scp) =="
git pull --no-rebase

Write-Host "== 2) skip-worktree setzen -> lokale Daten werden nie gepusht =="
git update-index --skip-worktree $NO_PUSH 2>$null

Write-Host "== 3) aktuelle view-Daten vom Server-Datentraeger holen ($Server) =="
foreach ($f in $FROM_DISK) {
  Write-Host "   scp $f ..."
  scp "${Server}:$REMOTE_DIR/$f" $f
}

Write-Host "== 4) DWD-Frontenarchiv + Validierung (server-lokal, gitignored) =="
# Der Server sammelt 4x taeglich (scheduler.py, FRONTEN_STUNDEN). Nichts davon
# liegt im Git - genau wie wetterdaten.json. Die Roh-PNGs bleiben per Default
# draussen: ~5 MB je Karte, rund 45 MB pro Tag, und lokal braucht man sie nur
# zum Nach-Extrahieren. Mit -MitKarten kommen sie mit.
$FRONTEN = @(
  "data/dwd_fronten_archiv/analyse/*.geojson",
  "data/dwd_fronten_archiv/vorhersage/*.geojson",
  "data/dwd_fronten_archiv/text/*",
  "data/dwd_fronten_archiv/aussagen/*.json",
  "data/dwd_fronten_archiv/alarm_zustand.json",
  "fronten_validation/observations.csv",
  "fronten_validation/AUTO_REPORT.md",
  "fronten_validation/aussagen/*.json"
)
if ($MitKarten) {
  $FRONTEN += "data/dwd_fronten_archiv/analyse/*.png"
  $FRONTEN += "data/dwd_fronten_archiv/vorhersage/*.png"
} else {
  Write-Host "   (ohne Roh-PNGs - fuer die: -MitKarten)"
}
foreach ($muster in $FRONTEN) {
  $ziel = Split-Path $muster -Parent
  if (-not (Test-Path $ziel)) { New-Item -ItemType Directory -Force $ziel | Out-Null }
  Write-Host "   scp $muster ..."
  scp "${Server}:$REMOTE_DIR/$muster" "$ziel/"
}

Write-Host ""
Write-Host "FERTIG. Lokal = aktueller Server-Stand (Analysen inkl. Tag 3 + Wetterdaten)."
Write-Host "App neu starten, dann stimmt die Ansicht."
