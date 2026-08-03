#!/bin/bash
set -e
cd ~/flychat
# NUR getrackte Aenderungen stashen. --include-untracked frass die taeglichen
# Server-Daten: jeder Deploy packte die untrackten Snapshots
# (data/weather_archive/) in einen Stash, den nie jemand poppte — die Tage
# 26.07.-02.08.2026 waren so "verschwunden" (am 03.08. aus stash@{0}/@{1}
# geborgen, der 23.07. ist endgueltig verloren). Untrackte Dateien blockieren
# einen Pull nicht; kollidiert doch einmal eine neue getrackte Datei mit einer
# untrackten gleichen Namens, bricht der Pull sichtbar ab — genau richtig.
git stash 2>/dev/null || true
git pull
source .venv/bin/activate
pip install -q -r requirements.txt
sudo systemctl restart wingcast
echo "=== Deploy fertig ==="
sudo systemctl status wingcast --no-pager | head -5