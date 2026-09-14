# Datenkonzept — was wohin gehört

**Entscheid 14.09.2026:** Jede Datei des Projekts fällt in genau eine von drei
Klassen, und jede Klasse hat genau einen Ort. **Belege** liegen auf dem Server,
die Kopie ausser Haus ist das Hetzner Server-Backup — **nie in Git**. Rohdaten
sind befristet und bleiben server-lokal. Laufzeit-Ausgaben werden nicht
archiviert. Git ist für Code und für die wenigen Dateien, die von Hand
geschrieben werden.

Anlass: Bis zu diesem Tag gab es keine Regel, nur Gewohnheit — und die hatte
sich dreimal in einer Woche als Ursache gezeigt. Audit-Protokolle, die nach 30
Tagen gelöscht *und* für immer versioniert waren (Endlosschleife, zehn Stashes
auf dem Server). Ein Wetter-Archiv, das seit dem 5. August niemand mehr nach
Git eingespielt hatte. 16 660 verdichtete OGN-Flüge, die nur auf einer
einzigen Platte lagen.

## Die Leitfrage

**Kann man es wiederbeschaffen, wenn es weg ist?**

Daraus folgt alles Weitere. Nicht die Grösse entscheidet, nicht die Häufigkeit
der Änderung, sondern ob die Datei aus einer anderen Quelle wieder entstehen
kann.

## Drei Klassen

| Klasse | Kennzeichen | Regel |
|---|---|---|
| **A · Belege** | unwiederbringlich, einmal geschrieben | vollständig auf dem Server; Kopie ausser Haus = Hetzner Server-Backup; **nie in Git** |
| **B · Rohdaten** | nach Verdichtung entbehrlich | server-lokal, befristet, **nie in Git**; gelöscht wird nur, was **alt und nachweislich verdichtet** ist |
| **C · Laufzeit-Ausgaben** | werden laufend neu erzeugt | server-lokal, **nie in Git**; auf den Entwicklungsrechner über `scripts/sync_from_server.ps1` |

Die Doppelbedingung in Klasse B stammt aus `ogn_sessions.prune_beacons`: Fällt
die Verdichtung aus, wachsen die Rohdaten sichtbar weiter, statt still zu
verschwinden. Am 28.08.2026 hat genau das einen ausgefallenen Lauf gerettet.

## Einteilung aller Daten

Grössen: Stand 14.09.2026, Server.

### A · Belege

| Pfad | Grösse | Warum unersetzlich |
|---|---|---|
| `data/weather_archive/YYYY-MM-DD.json` | 1,2 GB, 111 Tage seit 18.05. (10,5 MB/Tag) | die eingefrorene Prognose des Tages — **nachgemessen nicht nachbestellbar**, siehe unten |
| OGN-Flüge, verdichtet (`data/ogn_tracks.db`, Tabellen `flights`/`coverage`/`rollup_log`) | 16 660 Flüge, 32 Tage, ~3 MB | die Rohpunkte werden nach 7 Tagen gelöscht; die Flüge sind alles, was bleibt |
| `data/dwd_fronten_archiv/` | 525 MB | der DWD hält Open Data nur rund zwei Tage vor (`validation/fronten/README.md`) |
| `data/labeled_examples.jsonl` | 16 MB, 349 Beispiele | von Hand bewertet (Admin-UI auf dem Server) |
| `validation/*/PATTERNS.md`, `handurteile.csv`, `validation/xcontest/observations.csv` | < 5 MB | menschliche Urteile und kuratierte Befunde |

### B · Rohdaten

| Pfad | Frist | Wiederbeschaffbar aus |
|---|---|---|
| OGN-Rohpunkte (`beacons` in `data/ogn_tracks.db`) | 7 Tage (`RETENTION_DAYS`) | — entbehrlich, sobald zu Flügen verdichtet |
| `data/synoptic_audit/` | 30 Tage (`SYNOPTIC_AUDIT_KEEP_DAYS`) | — Nachvollzieh-Protokoll, nur für die letzten Wochen gebraucht |
| `data/wetterdaten.json` | rollendes 5-Tage-Fenster | — der Freeze in Klasse A ist die dauerhafte Form |
| `data/station_observations.db`, `data/_meteoschweiz_cache/` | Cache | MeteoSchweiz OGD, amtlich und dauerhaft |
| `validation/gewitter/messwerte/`, `urteile/` | Maschinenausgabe | Freeze (A) + MeteoSchweiz OGD — rekonstruierbar, siehe `.gitignore` |
| `validation/fronten/observations.csv`, `aussagen/` | Maschinenausgabe | Frontenarchiv (A) |

### C · Laufzeit-Ausgaben

`data/spot_analyses_en.json` (8 MB), `data/region_analyses_en.json`,
`data/synoptic_context.json`, `data/synoptic_grid.json`, `AUTO_REPORT.md` je
Domäne. Die App erzeugt sie täglich neu; ein Stand von gestern hat keinen
Wert, der nicht schon im Freeze (A) steckt.

### Die bewusste Ausnahme

Klasse-A-Dateien, die **klein sind und von Hand geschrieben werden**, bleiben
in Git: `PATTERNS.md`, `handurteile.csv`, `validation/xcontest/observations.csv`
und `data/labeled_examples.jsonl`. Grund: Git ist dort das Arbeitswerkzeug
(Diff, Review, Historie eines Urteils), nicht das Archiv. Die Sicherung ausser
Haus übernimmt trotzdem das Server-Backup, nicht GitHub.

Offen bleibt dabei `data/labeled_examples.jsonl`: Es wird **auf dem Server**
beschriftet, ist aber getrackt — die einzige Datei, die noch beides ist. Der
Sync holt sie per scp, committet wird sie vom Entwicklungsrechner aus. Das ist
tragbar, weil sie klein ist, aber es ist die letzte Stelle, an der Server und
Git um dieselbe Datei konkurrieren.

## Warum das Wetter-Archiv unersetzlich ist

Die naheliegende Annahme war: Die Werte kommen von Open-Meteo, also holt man
sie bei Bedarf noch einmal. **Geprüft am 14.09.2026 — sie trägt nicht.**

Gleicher Spot (Fiesch-Kühboden, 46.4048 / 8.09598), gleicher Tag (07.09.),
gleiches Modell (`meteoswiss_icon_ch1`), gleiche Stunde. Archiv gegen
`historical-forecast-api`:

| Zeit | Wert | Archiv | Nachabruf | Differenz |
|---|---|---|---|---|
| 10:00 | Temperatur 2 m | 15,9 °C | 14,6 °C | −1,3 |
| 12:00 | Temperatur 2 m | 17,1 °C | 16,2 °C | −0,9 |
| **12:00** | **Böen 10 m** | **25,6 km/h** | **36,0 km/h** | **+10,4 (+40 %)** |
| 14:00 | Böen 10 m | 29,5 km/h | 31,3 km/h | +1,8 |

Open-Meteo liefert für einen vergangenen Tag *eine* Prognose — aber nicht
*die*, die die App an jenem Morgen um 05:39 benutzt und den Nutzern gezeigt
hat. Es ist ein späterer, besserer Modelllauf. Für die Validierung („stimmte
unsere Vorhersage?") ist das der Unterschied zwischen sinnvoll und wertlos: Man
prüfte eine Vorhersage, die die App nie gemacht hat.

Zwei weitere Gründe, unabhängig davon:

1. **Die Archivwerte sind keine Abrufwerte, sondern Ausgabe unserer
   Verarbeitung.** Modellwahl in vier Stufen (`config.py`,
   `SURFACE_PRIMARY_MODEL` ff.), Böen als `max(icon_d2, ch1, ch2)`
   (`GUST_MERGE_MODELS`), Niederschlag über 16 Referenzpunkte je Region
   (`PRECIP_DENSE_MODEL`), Grenzschicht aus GFS, dazu eigene Thermikwerte je
   Stunde (`climb_rate`, `max_height`, `lcl`, `rating`). Das liesse sich nur
   durch einen kompletten Neulauf der Pipeline auf alten Eingaben
   rekonstruieren — und die alten Eingaben sind, siehe oben, nicht mehr dieselben.
2. **`thunder_ensemble` ist rückwirkend nicht beschaffbar.** Die Member des
   ICON-CH2-EPS sind nach rund drei Tagen identisch (`CLAUDE.md`,
   Modell-Rückblick). Nur der Snapshot hält die Wahrscheinlichkeit von damals.

Das ist auch Regel 1 in `validation/README.md`: *Was dort fehlt, kann
rückwirkend nicht validiert werden.*

## Soll gegen Ist — Stand vor der Bereinigung (14.09.2026)

Zwei Spalten, bewusst getrennt: **vorhanden** heisst, die Datei existiert;
**gesichert** heisst, es gibt eine Kopie ausser Haus.

| Daten | vorhanden | gesichert ausser Haus | Befund |
|---|---|---|---|
| Wetter-Archiv | Server 111 Tage (18.05.–14.09.), Backup-Ordner 116 | Git: 71 Tage, **nur bis 05.08.** | Einspielen nach Git ist am 05.08. eingeschlafen; fünf Wochen ohne auswärtige Kopie |
| OGN-Flüge | Server | **nirgends** | nur eine Platte |
| Frontenarchiv | Server 525 MB | **nirgends** | nur eine Platte |
| Audit-Protokolle | Server, 30 Tage | Git (bis 13.09.) | Widerspruch, am 13.09. behoben |
| Laufzeit-Ausgaben | Server | Git, mit `skip-worktree`-Behelf | der Behelf ist das Symptom |
| Backup-Ordner `~/flychat-backup/` | Server, additiv, täglich 07:30 | **dieselbe Platte** | schützt vor Skript-Unfällen, nicht vor Plattentod |

Der Backup-Ordner hat mehr Tage als der Live-Ordner, weil er nie etwas löscht —
so haben schon einmal fünf Tage überlebt, die ein Deploy-Stash aus dem
Live-Ordner gerissen hatte.

## Die Kopie ausser Haus

**Hetzner Server-Backup** (im Cloud-Konto aktiviert, 14.09.2026): die ganze
Platte als Abbild, täglich, rollend die letzten sieben Tage. Auf dem Server ist
dafür nichts einzurichten. Der additive Ordner `~/flychat-backup/` liegt mit
im Abbild — ein Skript-Unfall im Live-Ordner ist also aus dem Ordner
wiederherstellbar, ein Plattenschaden aus dem Abbild.

**Restlücke, benannt:** Ein Unfall, der Live-Ordner **und** `~/flychat-backup/`
gleichzeitig trifft *und* länger als sieben Tage unbemerkt bleibt, wäre nicht
mehr aufzufangen. Das ist eng, aber nicht null. Wer das schliessen will,
holt den Backup-Ordner zusätzlich additiv auf den Entwicklungsrechner — das
Sync-Skript tut das für `data/weather_archive/` seit dem 14.09. (nur
fehlende Tage, nie überschreiben).

Die Storage-Box-Zielstufe aus `docs/BACKUP.md` ist damit **abgelöst**, nicht
mehr geplant.

## Was daraus folgt — die Bereinigung

1. **Git:** `data/weather_archive/`, `data/spot_analyses_en.json`,
   `data/region_analyses_en.json`, `data/synoptic_context.json` aus dem Index,
   Dateien bleiben auf der Platte, Pfade in `.gitignore`. Die
   `skip-worktree`-Behelfe entfallen. **Keine Umschreibung der Historie** —
   die 691 MB von vor dem 05.08. bleiben in der Vergangenheit liegen
   (`.git` 167 MB), wachsen aber nicht mehr.
2. **Server:** Der nächste `git pull` entfernt die 71 Archivtage aus dem
   Arbeitsverzeichnis, weil sie den Index verlassen. Sie werden unmittelbar
   aus `~/flychat-backup/weather_archive/` zurückgeholt (`rsync
   --ignore-existing`), vorher und nachher gezählt. Die Laufzeit-Ausgaben
   werden vor dem Pull beiseitegelegt und danach zurückgelegt, sonst fehlt
   der Synoptik-Block bis zum nächsten Scheduler-Lauf.
3. **Entwicklungsrechner:** Nichts löschen. Die lokalen Archivtage bleiben,
   die Validierungsskripte lesen sie. Der Sync holt sie künftig additiv nach.

## Ausblick — nicht Teil dieses Entscheids

- **Verlustfreie Komprimierung des Archivs.** Gemessen am 14.09. an
  `2026-09-07.json`: 10,54 MB → 0,89 MB je Tag (kompakt + gzip, **kein Feld
  entfernt**), 116 Tage von 1,2 GB auf 98 MB. Braucht einen gemeinsamen Lader
  in `scripts/validation_common.py` (heute öffnet jedes Skript selbst) und eine
  Gegenprobe aller vier Validierungen. Sinnvoll, aber ein eigenes Vorhaben.
- **Feld-Reduktion** (auf die heute gelesenen Felder: 0,19 MB je Tag) ist
  **nicht** vorgesehen. Sie wäre unwiderruflich, und die OGN-Auswertung
  (Phase 3) existiert noch nicht — niemand weiss, welche Felder sie braucht.
- **Umschreiben der Git-Historie** ist **nicht** vorgesehen.

## Pflege

Neue Datenart? Erst die Leitfrage beantworten, dann die Zeile in die Tabelle
oben, dann `.gitignore`. Nie umgekehrt. Wer eine Datei in Git findet, die der
Server erzeugt, hat einen Fehler gefunden — nicht eine Ausnahme.
