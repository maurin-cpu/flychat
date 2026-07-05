#!/usr/bin/env bash
#
# sync_from_server.sh
# -------------------
# NUR auf dem LOKALEN DEV-PC ausfuehren.
#
# Holt in EINEM Befehl den kompletten Server-Stand, damit man lokal exakt die
# gleiche Ansicht hat wie der Server - OHNE lokal die Analyse-/Wetter-Pipeline
# laufen zu lassen:
#   1. git pull            -> Code + getrackte Analysen (region_analyses_en.json ...)
#   2. rsync vom Server    -> die gitignorten Runtime-Daten, die NIE in git sind:
#                             wetterdaten.json (~200 MB), spot_analyses.json,
#                             region_analyses.json, data/history/
#
# Server-Adresse einmalig festlegen (eine der drei Varianten):
#   a) Datei .dev_server im Repo-Root anlegen mit z.B.:  deploy@1.2.3.4
#   b) Umgebungsvariable:   export GLEITCAST_SERVER=deploy@1.2.3.4
#   c) als Argument:        bash scripts/sync_from_server.sh deploy@1.2.3.4
#
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# --- Server-Adresse ermitteln ---
SERVER="${1:-${GLEITCAST_SERVER:-}}"
if [ -z "$SERVER" ] && [ -f .dev_server ]; then
  SERVER="$(head -n1 .dev_server | tr -d '[:space:]')"
fi
if [ -z "$SERVER" ]; then
  echo "FEHLER: Keine Server-Adresse. Einmalig festlegen, z.B.:"
  echo "  echo 'deploy@DEIN_SERVER' > .dev_server"
  echo "oder:  bash scripts/sync_from_server.sh deploy@DEIN_SERVER"
  exit 1
fi

REMOTE_DIR="/home/deploy/flychat"

# Gitignorte Runtime-Daten, die die App zur Laufzeit liest:
RUNTIME_FILES=(
  data/wetterdaten.json
  data/spot_analyses.json
  data/region_analyses.json
)
RUNTIME_DIRS=(
  data/history
)

echo "== 1) git pull (Code + getrackte Analysen) =="
git pull --no-rebase || {
  echo "   git pull abgebrochen. Falls 'would be overwritten': einmal 'git sync' laufen lassen."
}

echo "== 2) Runtime-Daten vom Server holen ($SERVER) =="
for f in "${RUNTIME_FILES[@]}"; do
  echo "   rsync $f ..."
  rsync -az --info=progress2 "$SERVER:$REMOTE_DIR/$f" "$f"
done
for d in "${RUNTIME_DIRS[@]}"; do
  echo "   rsync $d/ ..."
  mkdir -p "$d"
  rsync -az --info=progress2 "$SERVER:$REMOTE_DIR/$d/" "$d/"
done

echo ""
echo "FERTIG. Lokal ist jetzt der Server-Stand da (Code + Analysen + Wetterdaten)."
