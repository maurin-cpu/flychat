#!/usr/bin/env bash
#
# sync_from_server.sh
# -------------------
# NUR auf dem LOKALEN DEV-PC ausfuehren (Linux/Mac). Windows: sync_from_server.ps1
#
# Holt in EINEM Befehl den AKTUELLEN Server-Stand, damit man lokal exakt die
# gleiche Ansicht hat wie der Server - OHNE lokal die Pipeline laufen zu lassen.
#
# WICHTIG: Die App liest zur Laufzeit Dateien, die auf dem Server-DATENTRAEGER
# oft NEUER sind als der letzte git-Commit (Analyse-Job schreibt taeglich,
# committet aber nur ~1x/Tag mit Versatz). Deshalb holen wir die view-relevanten
# Dateien direkt per rsync vom Datentraeger - NICHT ueber git:
#   - config_overrides.json  (LANG=en etc.)
#   - spot_analyses_en.json / region_analyses_en.json  (aktuelle Fliegbarkeit)
#   - wetterdaten.json  (~200 MB, Rohwetter fuer Meteogramme)
#
# Server-Adresse: .dev_server-Datei | $GLEITCAST_SERVER | Argument.
#
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

SERVER="${1:-${GLEITCAST_SERVER:-}}"
if [ -z "$SERVER" ] && [ -f .dev_server ]; then
  SERVER="$(head -n1 .dev_server | tr -d '[:space:]')"
fi
if [ -z "$SERVER" ]; then
  echo "FEHLER: Keine Server-Adresse. Z.B.:  echo 'deploy@178.105.39.152' > .dev_server"
  exit 1
fi
REMOTE_DIR="/home/deploy/flychat"

# view-relevante Dateien vom Server-DATENTRAEGER (git hinkt hinterher):
FROM_DISK=(
  data/config_overrides.json
  data/spot_analyses_en.json
  data/region_analyses_en.json
  data/wetterdaten.json          # gross (~200 MB) -> zuletzt
)
# getrackte Analyse-Dateien: vor git pull lokale Aenderungen verwerfen, damit
# pull nicht mit "clean your working tree" abbricht (auch DE, falls frueher mal
# per scp ueberschrieben):
TRACKED_DISK=(
  data/spot_analyses_en.json data/region_analyses_en.json
  data/spot_analyses.json data/region_analyses.json
)

# getrackte Server-Daten, die lokal NIE gepusht werden duerfen:
NO_PUSH=(
  data/spot_analyses_en.json data/region_analyses_en.json
  data/spot_analyses.json data/region_analyses.json
  data/synoptic_context.json data/labeled_examples.jsonl
)
extra="$(git ls-files data/synoptic_audit data/weather_archive)"
[ -n "$extra" ] && while IFS= read -r line; do NO_PUSH+=("$line"); done <<< "$extra"

echo "== 0) getrackte Analysen fuer sauberen git pull freigeben =="
git update-index --no-skip-worktree "${TRACKED_DISK[@]}" 2>/dev/null || true
git checkout -- "${TRACKED_DISK[@]}" 2>/dev/null || true

echo "== 1) git pull (nur Code relevant; Daten kommen unten frisch per rsync) =="
git pull --no-rebase || echo "   git pull-Hinweis beachten."

echo "== 2) skip-worktree setzen -> lokale Daten werden nie gepusht =="
printf '%s\n' "${NO_PUSH[@]}" | xargs git update-index --skip-worktree 2>/dev/null || true

echo "== 3) aktuelle view-Daten vom Server-Datentraeger holen ($SERVER) =="
for f in "${FROM_DISK[@]}"; do
  echo "   rsync $f ..."
  rsync -az --info=progress2 "$SERVER:$REMOTE_DIR/$f" "$f"
done

echo "== 4) DWD-Frontenarchiv + Validierung (server-lokal, gitignored) =="
# Der Server sammelt 4x taeglich (scheduler.py, FRONTEN_STUNDEN). Nichts davon
# liegt im Git - genau wie wetterdaten.json. Die Roh-PNGs bleiben per Default
# draussen: ~5 MB je Karte, rund 45 MB pro Tag, und lokal braucht man sie nur
# zum Nach-Extrahieren. Mit --mit-karten kommen sie mit.
FRONTEN_EXCLUDE=(--exclude '*.png')
if [ "${MIT_KARTEN:-0}" = "1" ] || [ "${2:-}" = "--mit-karten" ]; then
  FRONTEN_EXCLUDE=()
else
  echo "   (ohne Roh-PNGs - fuer die: --mit-karten)"
fi
mkdir -p data/dwd_fronten_archiv fronten_validation/aussagen
rsync -az --info=progress2 "${FRONTEN_EXCLUDE[@]}" \
  "$SERVER:$REMOTE_DIR/data/dwd_fronten_archiv/" data/dwd_fronten_archiv/

# In fronten_validation/ NUR die Maschinendateien holen. README, SCHEMA,
# PATTERNS und handurteile.csv sind von Hand gepflegt und liegen im Git — ein
# rsync des ganzen Ordners wuerde lokale, noch nicht gepushte Aenderungen
# daran mit der Serverkopie ueberschreiben.
rsync -az --info=progress2 \
  "$SERVER:$REMOTE_DIR/fronten_validation/observations.csv" \
  "$SERVER:$REMOTE_DIR/fronten_validation/AUTO_REPORT.md" \
  fronten_validation/
rsync -az --info=progress2 \
  "$SERVER:$REMOTE_DIR/fronten_validation/aussagen/" \
  fronten_validation/aussagen/

echo ""
echo "FERTIG. Lokal = aktueller Server-Stand (Analysen inkl. Tag 3 + Wetterdaten). App neu starten."
