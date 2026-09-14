# Server → lokaler PC synchronisieren

Ziel: lokal exakt die **aktuelle Server-Ansicht** haben, ohne lokal die Pipeline
laufen zu lassen. Lokale Daten werden **nie** auf den Server gepusht.

## Normalfall – ein Befehl

```powershell
.\scripts\sync_from_server.ps1        # Windows / PowerShell (dieser PC)
```
(Linux/macOS: `./scripts/sync_from_server.sh`)

Das Skript macht in einem Rutsch:
1. `git pull` → holt den **Code** (Daten sind seit 14.09.2026 nicht mehr in
   Git — `docs/DATENKONZEPT.md`)
2. `scp` → die View-Dateien **frisch vom Server-Datenträger**:
   `config_overrides.json`, `spot_analyses_en.json`, `region_analyses_en.json`,
   `synoptic_context.json`, `synoptic_grid.json`, `labeled_examples.jsonl`,
   `wetterdaten.json` (~200 MB)
3. `scp` → **DWD-Frontenarchiv + Validierung** (siehe unten)
4. OGN-Flugdaten verdichtet nach `data/ogn_local/`
5. Wetter-Archiv **additiv** nach `data/weather_archive/` — nur fehlende Tage,
   nie überschreiben (zweite Kopie der Belege, freiwillig)

Warum scp und nicht git? Weil nichts davon in Git liegt: Der Server erzeugt
diese Dateien, Git ist für Code (`docs/DATENKONZEPT.md`). `git pull` allein
bringt keinen Wetter-/Fliegbarkeits-Stand.

Danach: **App neu starten** → Ansicht stimmt.

## DWD-Frontenarchiv

Der Server sammelt die DWD-Frontenkarten **4× täglich** selbst
(`scheduler.py`, `FRONTEN_STUNDEN` = 02/08/14/20 Uhr) und wertet sie aus. Diese
Daten liegen **server-lokal und gitignored**, exakt wie `wetterdaten.json` —
es gibt keinen Weg über Git, weder hin noch zurück.

Geholt werden `data/dwd_fronten_archiv/` und aus `validation/fronten/` die
Maschinendateien (`observations.csv`, `AUTO_REPORT.md`, `aussagen/`).

Die **Roh-PNGs bleiben per Default draussen** — rund 45 MB pro Tag, lokal nur
zum Nach-Extrahieren nötig:

```powershell
.\scripts\sync_from_server.ps1 -MitKarten     # dann kommen sie mit
```

Von Hand gepflegt und deshalb **im Git**, nicht im Sync: `README.md`,
`SCHEMA.md`, `PATTERNS.md`, die Fallstudien und `handurteile.csv`. Letztere
legt der Validator bei jedem Lauf über die Maschinenzeilen — ein Urteil gehört
also dorthin und nie in `observations.csv`, die wird überschrieben.

## Wenn der Sync abbricht: Merge-Konflikt im `git pull`

Symptom: `You have unmerged paths` / `both modified`. Fast immer betroffen:
`static/js/briefing.js`, seltener `data/labeled_examples.jsonl`.

> **Seit dem 14.09.2026 liegt nichts mehr in Git, was der Server erzeugt**
> (`docs/DATENKONZEPT.md`): `data/synoptic_audit/` (13.09.),
> `data/weather_archive/`, `data/spot_analyses_en.json`,
> `data/region_analyses_en.json`, `data/synoptic_context.json` (14.09.). Sie
> tauchen in keinem Sync- und Konflikt-Schritt mehr auf.

Auflösen:

```powershell
# Server-beschriftete Daten -> immer Server-Version (theirs)
git checkout --theirs data/labeled_examples.jsonl
git add data/labeled_examples.jsonl

# CODE (z.B. briefing.js) -> NICHT blind theirs! Von Hand mergen,
# damit lokale Features (z.B. Maplink /synoptik) nicht verloren gehen.
#   Datei öffnen, <<<<<<< / ======= / >>>>>>> auflösen, beide Seiten sinnvoll behalten
git add static/js/briefing.js

git commit --no-edit
.\scripts\sync_from_server.ps1        # danach Sync erneut starten
```

Konfliktmarker finden: `git diff --check`

## „git status zeigt Server-Daten als modified"

Seit dem 14.09.2026 sollte das nur noch `data/labeled_examples.jsonl` treffen —
die einzige Datei, die der Server beschriftet und die trotzdem getrackt ist.
Das ist gewollt: neue Labels werden vom Entwicklungsrechner aus committet.

Zeigt `git status` eine **andere** vom Server erzeugte Datei, fehlt sie in
`.gitignore` — Zeile ergänzen, nicht `skip-worktree` setzen. Der Behelf ist
abgeschafft (`docs/DATENKONZEPT.md`).
