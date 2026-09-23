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
# git pull liefert nur den Code - seit 14.09.2026 keine Daten mehr (docs/DATENKONZEPT.md).
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
  # Wetterlage-Block und /synoptik-Druckkarte. Beide schreibt der Server
  # taeglich neu; synoptic_grid.json ist gitignored und kam frueher gar nicht
  # mit, synoptic_context.json nur ueber git und damit verspaetet. Fehlen sie
  # oder sind sie aelter als das Vorhersagefenster, verschwindet der ganze
  # Synoptik-Teil lokal wortlos.
  "data/synoptic_context.json",
  "data/synoptic_grid.json",
  "data/labeled_examples.jsonl",   # auf dem Server beschriftet (Admin-UI), getrackt
  "data/wetterdaten.json"          # gross (~200 MB) -> zuletzt
)
# Seit 14.09.2026 (docs/DATENKONZEPT.md) ist nichts mehr getrackt, was der
# Server erzeugt - kein skip-worktree, kein Freigeben vor dem Pull. Einzige
# Ausnahme bleibt data/labeled_examples.jsonl: auf dem Server beschriftet,
# per scp geholt, vom Entwicklungsrechner aus committet.

Write-Host "== 1) git pull (nur Code; Daten kommen unten frisch per scp) =="
git pull --no-rebase

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
  "validation/fronten/observations.csv",
  "validation/fronten/AUTO_REPORT.md",
  "validation/fronten/aussagen/*.json",
  "validation/gewitter/messwerte/*.json",
  "validation/gewitter/urteile/*.json",
  "validation/gewitter/scoreboard.json",
  "validation/gewitter/AUTO_REPORT.md"
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
Write-Host "== 4) OGN-Flugdaten (verdichtet) nach data/ogn_local/ =="
# Der Server haelt data/ogn_tracks.db - 686 MB Rohpunkte plus WAL, dazu ein
# offener Schreiber (ogn-collector.service). Die Datei als Ganzes zu kopieren
# waere gross UND unzuverlaessig: ohne Checkpoint fehlt der WAL-Inhalt.
# Deshalb nur die verdichteten Tabellen als CSV, lesend ueber stdout gestreamt
# (mode=ro + query_only, der Collector wird nicht gestoert). Zusammen ~3 MB.
# data/ogn_local/ ist gitignored - erzeugte Daten, jederzeit neu holbar.
$OGN_TABELLEN = @("flights", "coverage", "rollup_log")
if (-not (Test-Path "data/ogn_local")) {
  New-Item -ItemType Directory -Force "data/ogn_local" | Out-Null
}
foreach ($tab in $OGN_TABELLEN) {
  $py = "import sqlite3,csv,sys;" +
        "con=sqlite3.connect('file:data/ogn_tracks.db?mode=ro',uri=True,timeout=20);" +
        "con.execute('PRAGMA query_only=1');" +
        "cur=con.execute('SELECT * FROM $tab');" +
        "w=csv.writer(sys.stdout,lineterminator=chr(10));" +
        "w.writerow([d[0] for d in cur.description]);w.writerows(cur)"
  Write-Host "   $tab.csv ..."
  # Programm per stdin (python3 -), nicht als -c-Argument: PowerShell reicht
  # die inneren Anfuehrungszeichen nicht an die Remote-Shell durch, bash sah
  # "python3 -c import sqlite3,..." und brach mit Syntaxfehler ab (23.09.2026).
  # Ohne BOM schreiben - Out-File -Encoding utf8 setzt in PS 5.1 eines, und
  # das haengt am ersten Spaltennamen.
  $csv = $py | ssh $Server "cd $REMOTE_DIR && python3 -"
  [IO.File]::WriteAllText((Join-Path $root "data/ogn_local/$tab.csv"),
    (($csv -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding $false))
}

Write-Host ""
Write-Host "== 5) Wetter-Archiv additiv nach data/weather_archive/ (nur fehlende Tage) =="
# Klasse A (docs/DATENKONZEPT.md): Belege liegen auf dem Server, die Kopie
# ausser Haus ist das Hetzner Server-Backup. Diese zweite Kopie hier ist
# freiwillig und additiv - es wird nur geholt, was lokal fehlt, nie
# ueberschrieben, nie geloescht. ~10 MB je Tag.
if (-not (Test-Path "data/weather_archive")) {
  New-Item -ItemType Directory -Force "data/weather_archive" | Out-Null
}
$remote = ssh $Server "ls $REMOTE_DIR/data/weather_archive/" 2>$null |
  Where-Object { $_ -match '^\d{4}-\d{2}-\d{2}\.json$' }
$fehlend = @($remote | Where-Object { -not (Test-Path "data/weather_archive/$_") })
if ($fehlend.Count -gt 0) {
  Write-Host "   $($fehlend.Count) fehlende Tage ..."
  foreach ($tag in $fehlend) {
    scp "${Server}:$REMOTE_DIR/data/weather_archive/$tag" "data/weather_archive/$tag"
  }
} else {
  Write-Host "   nichts fehlt"
}

Write-Host ""
Write-Host "FERTIG. Lokal = aktueller Server-Stand (Analysen inkl. Tag 3 + Wetterdaten)."
Write-Host "App neu starten, dann stimmt die Ansicht."
