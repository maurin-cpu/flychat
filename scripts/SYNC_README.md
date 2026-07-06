# Server → lokaler PC synchronisieren

Ziel: lokal exakt die **aktuelle Server-Ansicht** haben, ohne lokal die Pipeline
laufen zu lassen. Lokale Daten werden **nie** auf den Server gepusht.

## Normalfall – ein Befehl

```powershell
.\scripts\sync_from_server.ps1        # Windows / PowerShell (dieser PC)
```
(Linux/macOS: `./scripts/sync_from_server.sh`)

Das Skript macht in einem Rutsch:
1. lokale Daten-Änderungen freigeben (für sauberen `git pull`)
2. `git pull` → holt den **Code**
3. `skip-worktree` setzen → Server-Daten werden nie gepusht
4. `scp` → die 4 View-Dateien **frisch vom Server-Datenträger**:
   `config_overrides.json`, `spot_analyses_en.json`, `region_analyses_en.json`,
   `wetterdaten.json` (~200 MB)

Warum scp und nicht nur git? `wetterdaten.json` ist gitignored und die Analysen
liegen auf dem Server-Datenträger **neuer** als der letzte Commit. `git pull`
allein bringt also keinen aktuellen Wetter-/Fliegbarkeits-Stand.

Danach: **App neu starten** → Ansicht stimmt.

## Wenn der Sync abbricht: Merge-Konflikt im `git pull`

Symptom: `You have unmerged paths` / `both modified`. Fast immer betroffen:
`data/synoptic_context.json`, `data/synoptic_audit/<datum>.json`,
`static/js/briefing.js`.

Auflösen:

```powershell
# Laufzeit-Daten -> immer Server-Version (theirs)
git checkout --theirs data/synoptic_context.json data/synoptic_audit/*.json
git add data/synoptic_context.json data/synoptic_audit/*.json

# CODE (z.B. briefing.js) -> NICHT blind theirs! Von Hand mergen,
# damit lokale Features (z.B. Maplink /synoptik) nicht verloren gehen.
#   Datei öffnen, <<<<<<< / ======= / >>>>>>> auflösen, beide Seiten sinnvoll behalten
git add static/js/briefing.js

git commit --no-edit
.\scripts\sync_from_server.ps1        # danach Sync erneut starten
```

Konfliktmarker finden: `git diff --check`

## „git status zeigt Server-Daten als modified"

Dann ist `skip-worktree` nicht (mehr) gesetzt. Neu setzen:

```powershell
git update-index --skip-worktree `
  data/spot_analyses_en.json data/region_analyses_en.json `
  data/spot_analyses.json data/region_analyses.json `
  data/synoptic_context.json data/labeled_examples.jsonl
git update-index --skip-worktree (git ls-files data/synoptic_audit data/weather_archive)
```

Prüfen (S = geschützt): `git ls-files -v | Select-String '^S'`
