#!/usr/bin/env bash
#
# local_dev_no_push_data.sh
# -------------------------
# NUR auf dem LOKALEN DEV-PC ausfuehren (NICHT auf dem Server).
#
# Idee: Der Server macht die (teuren) Analysen + haelt die Wetterdaten und
# committet/pusht sie. Der lokale PC soll diese Staende nur ZIEHEN, damit man
# lokal mit echten Daten am Code arbeiten kann - ohne die Pipeline lokal laufen
# zu lassen. Lokale Aenderungen an diesen Daten sollen NIE zurueckgepusht werden.
#
# Dieses Skript:
#   1. markiert die server-eigenen Datendateien mit --skip-worktree
#      -> lokale Aenderungen daran werden von git ignoriert (kein commit/push).
#   2. traegt die "churn"-Ordner in .git/info/exclude ein (lokal-only, nicht
#      committet) -> NEU entstehende Dateien darin werden lokal ignoriert,
#      waehrend der Server dort weiter neue Dateien committen kann.
#   3. legt den Alias `git sync` an -> holt sauber die Server-Version
#      ("Server gewinnt immer" fuer die Daten), Code bleibt unberuehrt.
#
# Danach:
#   git sync                          # Server-Daten ziehen (statt git pull)
#   git add -A && git commit && git push   # nur Code geht raus, Daten nie
#
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Einzelne, namentlich bekannte Server-Daten-Dateien:
FILES=(
  data/region_analyses_en.json
  data/spot_analyses_en.json
  data/synoptic_context.json
  data/labeled_examples.jsonl
)

# Ganze Ordner mit taeglich neuen Dateien (Server committet dort neu):
DIRS=(
  data/synoptic_audit
  data/weather_archive
)

echo "== 1) skip-worktree fuer getrackte Server-Daten setzen =="
# Nur wirklich getrackte Pfade an update-index geben:
tracked=$(git ls-files "${FILES[@]}" "${DIRS[@]}")
if [ -n "$tracked" ]; then
  echo "$tracked" | xargs git update-index --skip-worktree
  echo "$tracked" | sed 's/^/   skip: /'
else
  echo "   (keine getrackten Dateien gefunden)"
fi

echo "== 2) churn-Ordner lokal ignorieren (.git/info/exclude) =="
exclude=".git/info/exclude"
touch "$exclude"
for d in "${DIRS[@]}"; do
  if ! grep -qxF "$d/" "$exclude"; then
    echo "$d/" >> "$exclude"
    echo "   + $d/"
  else
    echo "   = $d/ (schon drin)"
  fi
done

echo "== 3) git-Alias 'sync' anlegen =="
git config alias.sync '!f() { \
  root=$(git rev-parse --show-toplevel); cd "$root"; \
  files=$(git ls-files data/region_analyses_en.json data/spot_analyses_en.json data/synoptic_context.json data/labeled_examples.jsonl data/synoptic_audit data/weather_archive); \
  [ -n "$files" ] && echo "$files" | xargs git update-index --no-skip-worktree; \
  [ -n "$files" ] && echo "$files" | xargs git checkout --; \
  git pull --no-rebase; \
  [ -n "$files" ] && echo "$files" | xargs git update-index --skip-worktree; \
}; f'
echo "   'git sync' angelegt."

echo ""
echo "FERTIG. Ab jetzt:"
echo "  git sync                              # Server-Daten ziehen"
echo "  git add -A && git commit && git push  # nur Code, keine Daten"
