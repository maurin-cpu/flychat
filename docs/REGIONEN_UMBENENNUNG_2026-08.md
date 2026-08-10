# Regionen-Umbenennung 2026-08-10

**19 der 29 Regionen heissen seit dem 10.08.2026 anders.** Namen *und*
technische ids. Maschinenlesbare Zuordnung: **`data/region_renames_2026-08.csv`**
(Spalten `alt;neu;typ;kommentar`, `typ` ∈ `name` | `variante` | `id`).

Diese Datei bleibt dauerhaft im Repo. Sie ist die einzige Quelle — sowohl das
Migrationsskript als auch dessen Kontrolle lesen daraus, und jede spätere
Auswertung, die alte Namen antrifft, kann darüber übersetzen.

## Warum

Die Namen beschrieben ihren Inhalt nicht. „Freiburger Voralpen" umfasste 70
Spots bis zum Niesen, davon 50 im Kanton Bern (Adelboden, Kandersteg, Gstaad);
„Berner Oberland" nur 4 Spots im Entlebuch. In der 49-Tage-Validierung erzeugte
das einen **Benennungs-Effekt**: das Paar *Berner Oberland 87 % / Freiburger
Voralpen 26 %* verglich nicht die Gebiete, die die Namen suggerierten.

## Die Liste

| alt | neu | Spots |
|---|---|---|
| Schwarzsee / Gantrisch | **Freiburger Voralpen** | 7 |
| Freiburger Voralpen | **Berner Oberland** | 70 |
| Berner Oberland | **Emmental** | 4 |
| Seeland / Emmental | **Seeland** | 0 |
| Berner Voralpen | **Berner Alpen** | 33 |
| Mittelland West | **Plateau** | 0 |
| Mattertal / Saastal | **Walliser Hochalpen** | 13 |
| Zentralschweizer Voralpen | **Zentralschweizer Alpen** | 87 |
| Mittelland Zentral | **Zentrale Voralpen** | 22 |
| Zentralwallis | **Lötschental** | 4 |
| Engadin Unter | **Mittelbünden** | 28 |
| Engadin Ober | **Oberengadin** | 12 |
| Ostschweiz | **Rheintal** | 12 |
| Alpstein / Ostschweiz | **Alpstein / Toggenburg** | 6 |
| Glarnerland / Walensee | **Glarner Alpen** | 17 |
| Jura Ost | **Tafeljura** | 1 |
| Jura West | **Neuenburger Jura** | 9 |
| Tessin Nord | **Leventina / Blenio** | 4 |
| Tessin Zentral | **Locarnese / Bellinzonese** | 30 |

**Unverändert (10):** Waadtländer Alpen · Unterwallis · Oberwallis / Goms ·
Jura Zentral · Mittelland Ost · Zentrales Mittelland · Genferseeregion ·
Bodenseeraum · Prättigau - Davos · Surselva.

Zwei davon sind **Zuschnitt-Probleme, keine Namensprobleme**: `unterwallis`
hält Crans-Montana, Anniviers und Nendaz, also das eigentliche Valais Central.
`jura_zentral` ist halb solothurnisch, halb bernisch. Erst den Zuschnitt
richten, dann benennen.

Bei **Rheintal** und **Alpstein** änderte sich nur der Name, nicht die id.

## Wo noch alte Namen stehen — und zwar zu Recht

Wer hier alte Namen findet, hat keinen Migrationsrest gefunden:

| Ort | warum unangetastet |
|---|---|
| `data/history/*` | echte Chatverläufe. Umschreiben fälscht das Protokoll |
| `*.bak*`, `*.pre_rename` | Momentaufnahmen eines Stands; ein migriertes Backup ist keins mehr |
| `validation/xcontest/*.md` | datierte Analysen. Sie tragen oben einen Hinweis auf diese Datei |
| `meteo_research/**` | dito |
| Spalte `region` in `fluggebiete_*.csv` | **andere Bedeutung**: grobe DHV-Herkunft (Ostschweiz, Zentralschweiz, Wallis, Waadt, Jura). Unsere Region steht in `analyse_region` |
| `import_dhv/**` | mappt Kantone auf ebendiese DHV-Herkunft |

Der Fall `Ostschweiz` ist der heikelste: er bedeutet je nach Ort die alte
Region (→ Rheintal), den Landesteil oder die DHV-Herkunft. Freie Notizen wie
„Vermutlich Ostschweiz / Toggenburg" in `validation/xcontest/observations.csv`
sind Auswerter-Prosa und bleiben stehen.

## Zwei Namen sind zugleich alt und neu

`Freiburger Voralpen` und `Berner Oberland` (samt ihrer ids) stehen nach der
Migration völlig zu Recht im Bestand — sie meinen dann nur etwas anderes als
vorher. Zwei Konsequenzen:

1. Eine Restsuche darf sie **nicht** als Fehler melden.
2. **Die Migration darf nur ein einziges Mal laufen.** Ein zweiter Durchlauf
   schöbe sie eine Stufe weiter und liesse Regionen verschmelzen.
   `scripts/migrate_region_names.py` sperrt sich selbst, sobald es eine
   `.pre_rename`-Sicherung findet; die Abo-DB hat dafür einen Marker in
   `schema_migrations`.

## Werkzeug

```
python scripts/migrate_region_names.py                    # Dry-Run, alle Stufen
python scripts/migrate_region_names.py --stage A --apply  # schreiben, mit Backup
python scripts/migrate_region_names.py --verify           # Restsuche
python scripts/migrate_region_names.py --show-ambiguous   # die Ostschweiz-Fälle
```

Drei Fallen, die das Skript abfängt:

1. **Ketten** — Schwarzsee → Freiburger Voralpen → Berner Oberland → Emmental,
   vierstufig, bei Namen wie ids. Zwei-Pass über Platzhalter, deshalb
   reihenfolgeunabhängig und auch gegen Ringtausch dicht.
2. **Teilstrings** — „Ostschweiz" steckt in „Alpstein / Ostschweiz". Pass 1
   sucht längster Name zuerst, zusätzlich wortgrenzen-bewusst.
3. **Bedeutungskollision** — strukturierte Dateien laufen spaltenscharf, nicht
   über den Dateitext. In den Spot-CSVs wird ausschliesslich `analyse_region`
   angefasst, in den GeoJSONs nur `properties.id` und `properties.region`.

## Was der Rename nicht erledigt

- **Zuschnitte.** „Zentralschweizer Alpen" bleibt ein Topf mit 87 Spots von
  Stoos bis Gemsstock; ein Median darüber bleibt schwach.
- **Polygon-Fehlzuordnungen.** Scuol/Motta Naluns liegt im Polygon
  `oberengadin`. Falkenflue liegt im Polygon `zentrale_voralpen`, obwohl der
  Spot der Region `emmental` zugeordnet ist. Der Name ist jetzt ehrlich, die
  Geometrie unverändert.
- **Terrain-Zonen und Referenzhöhen.** Nachgemessen am 10.08.2026 gegen die
  Median-Höhe der Spots je Region: **12 von 27 Regionen mit Spots tragen eine
  `terrain_type`, die nicht zu ihrem Inhalt passt, 5 davon um zwei Stufen.**
  Die zwei krassesten sind genau das Paar, um das es beim Rename ging:

  | Region | Spots | Median-Höhe | gesetzt | passend | `elevation_ref` |
  |---|---|---|---|---|---|
  | Emmental *(4 Entlebuch-Spots)* | 4 | 1327 m | `hochalpin` | `voralpen` | 1800 |
  | Berner Oberland *(70 Spots)* | 70 | 1983 m | `voralpen` | `hochalpin` | 1500 |

  Das ist derselbe Befund wie beim Namen, eine Ebene tiefer: **auch
  `terrain_type` und `elevation_ref` wurden zum alten Namen gepflegt, nicht
  zum tatsächlichen Inhalt.** Wirkung: `terrain_type` geht über
  `climb_factor_terrain` (0.95–1.15) und die Mindest-Thermikhöhe direkt in die
  Steigwert-Prognose ein; `elevation_ref` in den Refpoint-Pfad. Für die grösste
  Region des Systems bedeutet die falsche Stufe rund 9 % zu tiefe Steigwerte.

  Bewusst **nicht** in dieser Migration geändert: das ist ein Physik-Eingriff
  und gehört in einen eigenen Plan mit eigener Validierung.

  *Korrektur zum ursprünglichen Plan:* dieser behauptete, `zentrale_voralpen`
  trage `terrain_type=mittelland`. Das stimmt nicht — dort steht `voralpen`,
  was zur Median-Höhe von 1220 m passt. Der Befund liegt woanders, siehe oben.
- **Die Landmarken-Spalte `name` in den GeoJSONs.** Sie ist teils
  offensichtlich verrutscht (`rheintal` → „Santa Maria in Calanca",
  `bodenseeraum` → „Eggberge Altdorf", `zentrales_mittelland` → „Hasliberg
  Planplatten"). Bestand schon vorher, hier nicht angefasst.
- **`skills/chat_capabilities_guide.md`** ist unabhängig davon veraltet: „28+
  Startplaetze" (es sind 494), Verweis auf ein nicht mehr existierendes
  `data/fluggebiete.csv`, und eine Regionsliste aus einer früheren Ära
  (`Suedbuerden`, `Urner Alpen`, `Chur/Mittelbuenden`). Eigener Schritt.

## Umfang der Migration

| Stufe | Inhalt | Dateien | Ersetzungen |
|---|---|---|---|
| A | Stammdaten: `regionen.csv`, beide Spot-CSVs, drei GeoJSONs, 10 neue `description` | 6 | 830 |
| B | 71 Archivtage, XContest-Korpus, Gewitter-Validierung | 103 | 29 054 |
| C | Prompts, Doku, cost_testing-Goldens, Code-Kommentare | 97 | 590 |
| D | Abo-Datenbank (`subscriber.py`) | – | element-weise über das JSON-Array |

## Ausrollen — was git nicht mitbringt

Ausgerollt am 10.08.2026. **`git push` allein bewirkt auf dem Server nichts**,
und selbst ein erfolgreicher `pull` migriert nur die Hälfte. Für die nächste
Datenmigration ist das hier die Checkliste:

1. **Der Server nimmt den Pull nicht an, solange sein Arbeitsverzeichnis
   schmutzig ist.** Er schreibt selbst in getrackte Dateien
   (`labeled_examples.jsonl`, `region_analyses_en.json`,
   `spot_analyses_en.json`, `synoptic_context.json`) und hatte **kein
   `skip-worktree` gesetzt**. Diese Stände sind neuer als die in git → vor dem
   Pull sichern, danach zurückspielen, dann migrieren. `skip-worktree` ist
   inzwischen gesetzt.
2. **Archivtage, die nur auf dem Server liegen**, sind noch nicht committet und
   tragen alte Namen. Die, die der Pull selbst mitbringt, vorher aus dem Weg
   räumen — sonst bricht er ab.
3. **Die Abo-Datenbank erreicht kein `git revert`.** Vorher kopieren.
4. **Die Abo-Migration läuft NICHT beim Dienststart.** `SubscriberManager` wird
   in `web.py` pro Request erzeugt (`get_manager_from_env`) — `_init_db` zündet
   also irgendwann unbeaufsichtigt. Bewusst auslösen und prüfen, bevor Betrieb
   darauf läuft.
5. **`data/wetterdaten.json` muss mit.** Sie ist zwar rollend, hält aber unter
   `_regions` die Regions-Wetterdaten auf der Regions-ID. Ohne sie liefen 15 von
   29 Regionen in „Keine Wetterdaten". Der Fehler war live sichtbar.
6. **Nur auf dem Server vorhanden und deshalb leicht zu übersehen:**
   `validation/gewitter/**`, `validation/fronten/**`, die deutschen
   `*_analyses.json`, `data/synoptic_audit/**`, `data/test_runs/**`,
   `data/mocks/**`, `data/foehn_cache_*.json`.
   → **Immer `--verify` auf dem Server laufen lassen**, nicht nur lokal.
7. Der Marker `data/.region_rename_2026-08.done` kommt über git mit und sperrt
   dort einen unbegrenzten `--apply`-Lauf. Für die server-eigenen Daten
   `--paths` benutzen.

**Neu gegenüber dem ursprünglichen Plan:** `validation/gewitter/**` gehört dazu.
Der Gewitter-Richter zieht seine Regionsnamen über
`scripts/validation_common.py:30` direkt aus
`data/regionen_polygone_mapped.geojson`; seine Messwerte und Urteile tragen
dieselben Namen. Diese Daten sind gitignored und liegen auf dem Server — sie
müssen dort migriert werden, nicht hier.
