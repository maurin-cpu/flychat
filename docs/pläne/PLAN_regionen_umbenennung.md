# PLAN — Regionen umbenennen

**Stand:** 2026-07-26 · **Status:** zur Freigabe — **6 Entscheide offen (§2)**,
Umsetzung bewusst auf einen späteren Tag verschoben
**Betrifft:** `data/regionen.csv` · `data/fluggebiete_*.csv` · beide GeoJSONs ·
60 Archivtage · `xcontest_validation/observations.csv` · `skills/**` ·
`cost_testing/**`

**Anlass:** Die Regionsnamen beschreiben ihren Inhalt nicht. „Freiburger
Voralpen" umfasst 70 Spots bis zum Niesen (50 davon Kanton Bern: Adelboden,
Kandersteg, Gstaad), „Berner Oberland" nur 4 Spots im Entlebuch. In der
49-Tage-Validierung erzeugt das einen **Benennungs-Effekt**: das Paar
*Berner Oberland 87 % / Freiburger Voralpen 26 %* vergleicht nicht die Gebiete,
die die Namen suggerieren (`2026-07-26_ANALYSE_49_TAGE.md`, Befund 3).

---

## 1. Die Vorgabe

Vom User am 2026-07-26 vorgegeben — nicht mein Vorschlag:

| # | alt | neu | Spots |
|---|---|---|---|
| 1 | Schwarzsee / Gantrisch | **Freiburger Voralpen** | 7 |
| 2 | Freiburger Voralpen | **Berner Oberland** | 70 |
| 3 | Berner Oberland | **Emmental** | 4 |
| 4 | Berner Voralpen | **Berner Alpen** | 33 |
| 5 | Mittelland West | **Plateau** | 0 |
| 6 | Mattertal / Saastal | **Walliser Hochalpen** | 13 |
| 7 | Zentralschweizer Voralpen | **Urner Alpen** | 87 |
| 8 | Waadtländer Alpen | **Bas-Valais** | 26 |

Entschieden am 2026-07-26: **technische `id`s werden mitmigriert**;
**`Bas-Valais`** bleibt wie vorgegeben (nicht „Chablais").

Damit auch die ids:

| alt | neu |
|---|---|
| `schwarzsee_gantrisch` | `freiburger_voralpen` |
| `freiburger_voralpen` | `berner_oberland` |
| `berner_oberland` | `emmental` |
| `berner_voralpen` | `berner_alpen` |
| `mittelland_west` | `plateau` |
| `mattertal_saastal` | `walliser_hochalpen` |
| `zentralschweizer_voralpen` | `urner_alpen` |
| `waadtlaender_alpen` | `bas_valais` |

**Zeile 1–3 sind eine Kette** (Schwarzsee → Freiburger Voralpen → Berner
Oberland → Emmental), bei Namen *und* ids. Naives Suchen-und-Ersetzen wirft drei
Regionen in einen Topf. Siehe §5.

---

## 2. Offene Entscheide — vor dem Start zu klären

> **Beim Wiederaufnehmen hier anfangen.** Sechs Punkte, alle unbeantwortet.
> Ohne sie kann die Migration nicht starten.
>
> | # | Frage | Empfehlung |
> |---|---|---|
> | 1 | „Emmental" kollidiert mit `Seeland / Emmental` | `Seeland / Emmental` → **`Seeland`** (§2.1) |
> | 2 | „Plateu" = Tippfehler? | **`Plateau`** (§2.2) |
> | 3 | `data/history/*` (echte Chatverläufe, 54 Treffer) mitziehen? | **nein** (§2.3) |
> | 4 | `*.bak*`-Dateien (1 365 Treffer) mitziehen? | **nein** (§2.3) |
> | 5 | `fluggebiete_test.csv` / `foehntest.csv` mitziehen? | **ja** (§2.3) |
> | 6 | `data/preview/*` mitziehen? | egal, wird neu erzeugt (§2.3) |



### 2.1 „Emmental" — Kollision, aber harmloser als gedacht

Es gibt bereits `Seeland / Emmental` (`id=seeland_emmental`). Zwei Regionen mit
„Emmental" im Namen sind verwirrend, und jede spätere Textsuche nach „Emmental"
trifft beide.

**Neuer Befund: `Seeland / Emmental` hat 0 Spots.** Sie wird über den
Refpoint-Pfad geprognostiziert, nicht über Spot-Mediane
(`fetch_weather.py:38-42`, `SPOT_MEDIAN_MIN_SPOTS = 3`).

**Empfehlung:** `Seeland / Emmental` → **`Seeland`** (`id=seeland`). Kostet
nichts, die Region hat keine Spot-Zuordnungen, und der Name stimmt danach
besser — das Emmental sitzt geografisch in der Nachbarregion. Die Kette wird
vierstufig, was am Verfahren nichts ändert.

*Alternative, falls nicht gewollt:* die 4 Entlebuch-Spots statt „Emmental"
**„Entlebuch"** nennen. Dann bleibt `Seeland / Emmental` unangetastet.

### 2.2 „Plateu" → „Plateau"

Die Vorgabe schreibt „Plateu". Ich nehme das als Tippfehler und setze
**`Plateau`** (`id=plateau`). Falls anders gemeint: sagen.

### 2.3 Vier Randbereiche — mitziehen oder stehen lassen?

Gefunden beim Erstellen der Umzugsliste (§3.1), noch nicht entschieden:

| Bereich | Dateien | Treffer | Empfehlung | Begründung |
|---|---|---|---|---|
| `data/history/user_1.json`, `sess_*.json` | 2 | 54 | **nicht** umziehen | echte Chatverläufe — Protokoll dessen, was gesagt wurde. Umschreiben fälscht Verlauf. |
| `*.bak*` (`region_analyses.bak_*`, `spot_analyses.bak_*` ×2, `fluggebiete_dhv.backup_pre_pge.csv`, `labeled_examples.jsonl.pre-backfill.bak`) | 5 | 1 365 | **nicht** umziehen | Backups sind Momentaufnahmen eines Stands; ein migriertes Backup ist kein Backup mehr |
| `data/fluggebiete_test.csv`, `data/fluggebiete_foehntest.csv` | 2 | 17 | **doch** umziehen | sonst laufen Tests gegen Regionsnamen, die es nicht mehr gibt |
| `data/preview/briefing_preview.*` | 2 | 6 | egal | Generat, wird beim nächsten Lauf überschrieben |

Wird Punkt 1 oder 2 auf „nicht umziehen" entschieden, muss die Restsuche in
Schritt 3 diese Pfade **ausnehmen** — sonst meldet sie Altnamen und die
Verifikation schlägt fälschlich an.

---

## 3. Was der Rename anfasst — gemessen, nicht geschätzt

688 Textdateien gescannt (ohne `.git`, Binaries). Treffer der 8 Altnamen
inkl. Schreibvarianten plus der 8 ids:

| Bereich | Dateien | Charakter |
|---|---|---|
| `data/weather_archive/*.json` | 60 | Historie, Join-Schlüssel jeder Validierung |
| `cost_testing/**` | 44 | Golden-Fixtures + Reports |
| `xcontest_validation/**` | 42 | `observations.csv` (Daten) + datierte Analysen (Protokoll) |
| `data/` CSV + GeoJSON | 16 | **live — Quelle der Wahrheit** |
| `docs/` + `meteo_research/` | 14 | Doku |
| `scripts/` + `debug_scripts/` | 12 | Werkzeuge |
| `skills/**` | 9 | **LLM-sichtbar** (de + en) |
| `data/analysen/` + `region_analyses*.json` | 7 | LLM-Ergebnisse, Historie |
| Python (Produktiv) | 3 | nur Kommentare/Beispiele |
| `tests/**` | 1 | nur Kommentar |
| **Summe** | **208** | **19 283 Treffer** (18 374 Namen + 909 ids) |

**Schreibvarianten, die mitmüssen** (sonst bleiben Reste stehen):
`Schwarzsee/Gantrisch` (45×), `Mattertal/Saastal` (51×),
`Waadtlaender Alpen` (79×, ASCII-Variante).

### 3.1 Die Umzugsliste, Datei für Datei

**Stufe A — Quelle der Wahrheit (6 Dateien, 506 Treffer).** Ohne die stimmt
nichts; Namen *und* ids, in CSV-Spalten wie in GeoJSON-`properties`:

```
data/regionen.csv                             16   + description neu schreiben (§4)
data/fluggebiete_pge.csv                     240   aktive Spot-Quelle (USE_SPOT_CSV=pge)
data/fluggebiete_dhv.csv                     202   Alternativquelle, muss schaltbar bleiben
data/regionen_polygone_mapped.geojson         16
data/regionen_referenzpunkte.geojson          16
data/regionen_referenzpunkte_precip.geojson   16
```

**Stufe B — Historie und Daten (75 Dateien, 17 206 Treffer):**

```
data/weather_archive/*.json          60 Dateien  14 353   Join-Schluessel jeder Validierung
data/region_analyses*.json
  + data/spot_analyses*.json          7 Dateien   1 683   LLM-Ergebnisse (davon 4 Backups → §2.3)
xcontest_validation/observations.csv  1 Datei       481   Validierungs-Korpus
data/labeled_examples.jsonl                        419   live (Admin-UI + API, web.py:1903 ff.)
data/wetterdaten.json                               24
data/history/*, data/preview/*                      60   → §2.3, offen
```

**Stufe C — Text, Prompts, Fixtures (76 Dateien, 408 Treffer):**

```
cost_testing/**            44 Dateien  208   Golden-Fixtures
debug_scripts/**           11 Dateien   50   Ad-hoc-Werkzeuge
skills/** (de + en)         9 Dateien   35   LLM-sichtbar
docs/**                     6 Dateien   65   v.a. REFPOINT_LISTE.md (51)
Produktivcode (3)                        5   nur Kommentare/Beispieltext, s.o.
tests/test_synoptic_context.py           1   nur Kommentar
scripts/preview_briefing_email.py        3
```

**Bewusst NICHT umziehen (49 Dateien, 985 Treffer):** `xcontest_validation/*.md`
und `meteo_research/**` — datierte Protokolle. Dazu **dieses Plan-Dokument
selbst**, es enthält die Zuordnung alt→neu und muss sie behalten. Alle drei
Pfade gehören in die Ausnahmeliste der Restsuche (Schritt 3).

### Der Befund, der den Plan billig macht

**Kein Produktivcode hängt funktional am Regionsnamen oder an einer id.**
Alle Treffer im Produktivcode sind Kommentare oder LLM-Beispieltext:

| Datei | Zeile | Art |
|---|---|---|
| `fetch_weather.py` | 40–41 | Kommentar (Aufzählung kleiner Regionen) |
| `thermik_calculator.py` | 125 | Docstring der Elevation-Fallback-Schwellen |
| `engine/chat_orchestrator.py` | 236, 244 | LLM-Tool-Beschreibung „z.B. 'Berner Oberland'" |
| `tests/test_synoptic_context.py` | 308 | Kommentar; die Assertion nutzt lat/lon |

Nirgends ein `dict`, das auf Namen oder ids schlüsselt. Der Name fliesst aus
`regionen.csv` / `fluggebiete_pge.csv` durch die Pipeline.
**Das ist eine Datenmigration, kein Code-Refactoring.**

---

## 4. Was ein reiner Rename NICHT erledigt — und deshalb mit muss

`regionen.csv` trägt pro Region `description`, `terrain_type` und
`elevation_ref`. Nach der Umbenennung beschreiben die den **alten** Zuschnitt.
`source_area.py` gibt `description` ans Frontend (Karte) — das ist also sichtbar,
nicht intern:

| neuer Name | `description` heute | passt? |
|---|---|---|
| Berner Oberland *(ex Freiburger Voralpen, 70 Spots)* | „Moléson - freistehende Gipfel" | **nein** — Moléson ist nur einer von 70 |
| Emmental *(ex Berner Oberland, 4 Spots)* | „Eiger/Mönch/Jungfrau-Region mit Hochalpencharakter" | **nein** — das sind 4 Entlebuch-Spots |
| Berner Alpen *(ex Berner Voralpen, 33 Spots)* | „Niederhorn / Stockhorn - exponierte Grate" | **nein** — enthält Jungfrauregion, Schilthorn, Grindelwald |
| Urner Alpen *(ex Zentralschweizer Voralpen, 87)* | „Engelberg / Pilatus / Stoos" | teilweise |
| Bas-Valais *(ex Waadtländer Alpen, 26)* | „Alpenrand Waadt: Leysin/Diablerets" | teilweise — 16 der 26 sind Wallis |
| Freiburger Voralpen *(ex Schwarzsee/Gantrisch, 7)* | „Voralpine Ketten Freiburg/Bern" | ja |
| Walliser Hochalpen *(ex Mattertal/Saastal, 13)* | „Tiefe Hochtäler mit Gletscherwind" | ja |

→ **`description` wird im selben Schritt neu geschrieben.** Ohne das steht auf
der Karte bei „Emmental" die Jungfrau.

**`terrain_type` / `elevation_ref` bleiben in diesem Plan unangetastet.** Sie
sind fachlich fragwürdig — 298 von 494 Spots bekommen über
`thermik_calculator.py:135-139` eine Terrain-Zone, die ihrer eigenen Höhe
widerspricht, weil die Region den Spot überstimmt. Das ist ein **Physik-Eingriff**
(er verändert `climb_factor_terrain` und damit jede Steigraten-Prognose) und
gehört nicht in eine Umbenennung. Eigener Plan, nach dem Rename.

**Zwei Nebenbefunde, nur zur Kenntnis, hier nicht angefasst:**
- `Bas-Valais` liegt in der Synoptik-Zone `alpennordhang`, nicht `wallis`. Der
  Name legt anderes nahe; die Zone ist inhaltlich vertretbar (Chablais-Nordseite).
- `Mittelland West` (→ `Plateau`) und `Seeland / Emmental` haben **0 Spots** und
  laufen über den Refpoint-Pfad.

---

## 5. Vorgehen

### Schritt 0 — sauberer Ausgangspunkt *(noch offen, Stand 2026-07-26)*

Der Working Tree hat 3 geänderte + 8 unversionierte Dateien (die
XContest-Validierung: Analyse, 3 Skripte, Rohdaten, `PATTERNS.md`, `README.md`,
`observations.csv`). **Erst committen.** Sonst liegt eine 208-Dateien-Migration
im selben Diff wie inhaltliche Arbeit — nicht reviewbar, nicht einzeln
zurückrollbar.

### Schritt 1 — Mapping als einzige Quelle

`data/region_renames_2026-07.csv` mit `alt;neu;typ;kommentar`
(`typ` ∈ `name` | `id` | `variante`). Kein Skript enthält Namenspaare hartkodiert;
Migration *und* Verifikation lesen dieselbe Tabelle. Enthält alle drei
Schreibvarianten aus §3.

### Schritt 2 — Migrationsskript

`scripts/migrate_region_names.py`, **Default Dry-Run**, Schreiben nur mit
`--apply`, Backup je Datei vor dem ersten Schreiben.

Gegen das Ketten-Problem **keine Reihenfolge, sondern Zwei-Pass über
Platzhalter**: erst jeder Altname/jede id → `\x00<n>\x00`, dann Platzhalter →
Neuname. Damit sind Ketten und selbst Ringtausche kollisionsfrei, unabhängig von
der Sortierung — robuster als „von hinten nach vorn", weil es nicht davon
abhängt, dass ich richtig sortiere.

Ersetzt wird **wortgrenzen-bewusst**, damit `berner_oberland` nicht in
`berner_oberland_alt` trifft und `Emmental` nicht in `Seeland / Emmental`.

Umfang in drei einzeln schaltbaren Stufen:

- **A, zwingend** — `regionen.csv` (inkl. neuer `description`),
  `fluggebiete_pge.csv` + die übrigen Spot-CSVs, beide GeoJSONs
  (`properties.region`, `properties.id`)
- **B, empfohlen** — 60 Archivtage, `region_analyses*.json`, `data/analysen/`,
  `observations.csv`
- **C, empfohlen** — `skills/**` (de **und** en), `cost_testing`-Goldens,
  die 4 Code-Kommentare aus §3

**Nicht anfassen:** die datierten Analysen in `xcontest_validation/*.md` und
`meteo_research/**`. Das sind Protokolle eines Stands — sie bekommen oben einen
Hinweis auf die Umbenennung, werden aber nicht umgeschrieben. Sonst fälscht man
rückwirkend Befunde.

### Schritt 3 — Verifikation, mechanisch statt „sieht gut aus"

| Prüfung | Sollwert | beweist |
|---|---|---|
| Regionen-Zahl | 29 → 29, kein Name doppelt | nichts verloren/verschmolzen |
| Spots je Region | identisch (mapping-übersetzt) | keine Zuordnung abgerissen |
| Punkt-in-Polygon | wieder 476/494 im eigenen Polygon, 0 Widersprüche | CSV und GeoJSON konsistent migriert |
| Restsuche Altnamen | 0 Treffer in Stufe A/B/C | keine Schreibvariante vergessen |
| `pytest` | wie vor der Migration | (Referenz: zuletzt 280 passed, 15 skipped, 3 vorbestehende Playwright-Errors) |
| `cost_testing` gegen Goldens | grün | LLM-Pfad unverändert |
| `scripts/validate_climb_onesided.py` | **identische Perzentile je Region** | die Migration hat keine Daten getrennt |

Die letzte Zeile ist die schärfste: weicht ein Perzentil ab, hat der Rename einen
Join zerschnitten.

### Schritt 4 — keine Alias-Schicht

Die Alternative wäre, die Archive unangetastet zu lassen und im Lesepfad zu
übersetzen. Davon rate ich ab: die Alias-Anwendung müsste in jedem Leser stehen
(Validierungsskripte, Replay, `region_analyses`-Loader) und bricht still, sobald
einer sie vergisst. Einmal migrieren mit Backup ist sauberer als eine dauerhafte
Übersetzungsschicht.

### Schritt 5 — nachziehen

`SYSTEM_CHANGES.md`, Notiz in `xcontest_validation/PATTERNS.md` (sonst ist die
Befund-2-Tabelle der 49-Tage-Analyse nicht mehr lesbar — sie nennt alte Namen),
Memory aktualisieren.

### Rollback

Ein Commit je Stufe (A / B / C). `git revert` der jeweiligen Stufe stellt den
Stand her; zusätzlich die Datei-Backups aus Schritt 2.

---

## 6. Was der Rename bringt — und was nicht

**Bringt:** Der Benennungs-Effekt verschwindet. Die 70-Spot-Region mit Niesen,
Adelboden und Gstaad heisst dann „Berner Oberland", die 4 Entlebuch-Spots heissen
nicht mehr so. Regionale Auswertungen vergleichen wieder die Gebiete, die die
Namen suggerieren. Piloten und LLM sehen im Chat den richtigen Namen.

**Bringt nicht:**
- Die **echte Schieflage** aus I-016. „Jura Zentral 100 %" ist unberührt — die
  Region wird nicht umbenannt und ist kompakt.
- Den **Zuschnitt**. „Urner Alpen" bleibt ein Topf mit 87 Spots von Pilatus bis
  Gemsstock; ein Median darüber bleibt schwach.
- Die **Engadin-/Ostschweiz-Definitionsfehler**: `id=engadin_unter` enthält
  Mittelbünden (Somtgant, Scalottas, Alp Stätz), das echte Scuol/Motta Naluns
  liegt im Polygon `Engadin Ober`. Zwei Regionen tragen „Ostschweiz" im Namen und
  meinen Verschiedenes. Das sind **Zuschnitte**, keine Namen — eigener Schritt.
- Die **Terrain-Zonen-Schieflage** aus §4.

Diese vier bleiben nach dem Rename offen und sind bewusst nicht mitgemischt.
