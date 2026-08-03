#!/bin/bash
# Taegliches Backup der server-lokalen Daten auf die Hetzner Storage Box.
#
# WARUM: Diese Daten existieren sonst nur einmal, auf der Server-Platte —
# und zwei Vorfaelle in einer Woche haben gezeigt, wie schnell sie weg sind
# (rollendes Prognosefenster 31.07., Deploy-Stash frass 8 Snapshot-Tage,
# geborgen am 03.08., der 23.07. blieb verloren). Git ist als Lager bewusst
# raus: ~11 MB/Tag wachsen dort unbegrenzt und sind nie wieder loeschbar.
#
# Einrichtung (einmalig): docs/BACKUP.md
# Aufruf: taeglich per Cron, siehe ebenda. Additiv — dieses Skript LOESCHT
# NIE etwas auf der Box (kein --delete): ein lokaler Datenverlust darf sich
# nicht ins Backup fortpflanzen.
set -euo pipefail

# Adresse steht in ~/.storagebox (eine Zeile, z. B. u123456@u123456.your-storagebox.de)
BOX="${STORAGEBOX:-$(cat "$HOME/.storagebox" 2>/dev/null || true)}"
if [ -z "$BOX" ]; then
    echo "FEHLER: Storage-Box-Adresse fehlt — 'echo u...@u....your-storagebox.de > ~/.storagebox'"
    exit 1
fi

cd "$HOME/flychat"
R() {
    rsync -az --mkpath --timeout=300 -e "ssh -p 23 -o BatchMode=yes" "$@"
}

echo "[$(date '+%F %T')] Backup -> $BOX:flychat-backup/"
R data/weather_archive/      "$BOX:flychat-backup/weather_archive/"
R validation/                "$BOX:flychat-backup/validation/"
R data/dwd_fronten_archiv/   "$BOX:flychat-backup/dwd_fronten_archiv/"
R data/wetterdaten.json      "$BOX:flychat-backup/wetterdaten/wetterdaten.json"
R data/spot_analyses_en.json "$BOX:flychat-backup/wetterdaten/spot_analyses_en.json"
R data/region_analyses_en.json "$BOX:flychat-backup/wetterdaten/region_analyses_en.json"
echo "[$(date '+%F %T')] Backup OK"
