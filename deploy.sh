#!/bin/bash
set -e
cd ~/flychat
git stash --include-untracked 2>/dev/null || true
git pull
source .venv/bin/activate
pip install -q -r requirements.txt
sudo systemctl restart wingcast
echo "=== Deploy fertig ==="
sudo systemctl status wingcast --no-pager | head -5