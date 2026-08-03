#!/bin/bash
# Taegliches Backup der server-lokalen Daten.
#
# WARUM: Diese Daten existieren sonst nur einmal, auf der Server-Platte —
# und zwei Vorfaelle in einer Woche haben gezeigt, wie schnell sie weg sind
# (rollendes Prognosefenster 31.07., Deploy-Stash frass 8 Snapshot-Tage,
# geborgen am 03.08., der 23.07. blieb verloren). Git ist als Lager bewusst
# raus: ~11 MB/Tag wachsen dort unbegrenzt und sind nie wieder loeschbar.
#
# ZIEL (automatisch gewaehlt):
#   1. Hetzner Storage Box, wenn ~/.storagebox existiert
#      (eine Zeile: u123456@u123456.your-storagebox.de — siehe docs/BACKUP.md)
#   2. sonst Uebergangsloesung (Entscheid 03.08.): lokaler Ordner
#      ~/flychat-backup/ NEBEN dem Projekt. Schuetzt vor Deploy-/Skript-
#      Unfaellen, NICHT vor Plattentod — der Wechsel auf die Box ist spaeter
#      nur das Anlegen von ~/.storagebox, sonst aendert sich nichts.
#
# Additiv — dieses Skript LOESCHT NIE etwas im Backup (kein --delete):
# ein lokaler Datenverlust darf sich nicht ins Backup fortpflanzen.
set -euo pipefail

BOX="${STORAGEBOX:-$(cat "$HOME/.storagebox" 2>/dev/null || true)}"
if [ -n "$BOX" ]; then
    ZIEL="$BOX:flychat-backup"
    RSH=(-e "ssh -p 23 -o BatchMode=yes")
else
    ZIEL="$HOME/flychat-backup"
    RSH=()
    mkdir -p "$ZIEL"
fi

cd "$HOME/flychat"
R() {
    rsync -az --mkpath --timeout=300 ${RSH[@]+"${RSH[@]}"} "$@"
}

echo "[$(date '+%F %T')] Backup -> $ZIEL/"
R data/weather_archive/        "$ZIEL/weather_archive/"
R validation/                  "$ZIEL/validation/"
R data/dwd_fronten_archiv/     "$ZIEL/dwd_fronten_archiv/"
R data/wetterdaten.json        "$ZIEL/wetterdaten/wetterdaten.json"
R data/spot_analyses_en.json   "$ZIEL/wetterdaten/spot_analyses_en.json"
R data/region_analyses_en.json "$ZIEL/wetterdaten/region_analyses_en.json"
echo "[$(date '+%F %T')] Backup OK"
