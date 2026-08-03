# PLAN — Regionen umbenennen

**Stand:** 2026-08-02 · **Status:** zur Freigabe — **4 Entscheide offen (§2)**,
Umsetzung bewusst auf einen späteren Tag verschoben
**Betrifft:** `data/regionen.csv` · `data/fluggebiete_*.csv` · alle drei GeoJSONs ·
61 Archivtage · `validation/xcontest/observations.csv` · `skills/**` ·
`cost_testing/**` · **`subscriber.py` + Abo-DB** (§3.3)

**Anlass:** Die Regionsnamen beschreiben ihren Inhalt nicht. „Freiburger
Voralpen" umfasst 70 Spots bis zum Niesen (50 davon Kanton Bern: Adelboden,
Kandersteg, Gstaad), „Berner Oberland" nur 4 Spots im Entlebuch. In der
49-Tage-Validierung erzeugt das einen **Benennungs-Effekt**: das Paar
*Berner Oberland 87 % / Freiburger Voralpen 26 %* vergleicht nicht die Gebiete,
die die Namen suggerieren (`2026-07-26_ANALYSE_49_TAGE.md`, Befund 3).

**Änderung 2026-08-02 — von 8 auf 19 Umbenennungen.** Auslöser war eine externe
Zuordnungsliste (xctherm), die der User zum Abgleich brachte. Jede Zeile wurde
gegen die **tatsächlichen Spot-Zuordnungen** geprüft (`fluggebiete_*.csv`,
Spalte `analyse_region`), nicht gegen Namensgleichheit. Zwei der ursprünglichen
8 fielen dabei durch, elf neue Namensfehler kamen dazu.

> **Methodischer Punkt, der die Prüfung trägt:** Namensgleichheit beweist nichts.
> xctherm ordnet unser „Berner Oberland" seinem „Berner Oberland" zu — unsere
> Region enthält aber nur Falkenflue und Marbachegg, also Entlebuch. Bestätigen
> oder widerlegen kann nur der Blick auf die Spots.

---

## 1. Die Liste

**19 Umbenennungen, 10 Regionen bleiben.** Spot-Zahlen aus der aktiven Quelle
`fluggebiete_pge.csv` (494 Spots gesamt).

### 1.1 Bestätigt aus der User-Vorgabe vom 2026-07-26

| # | alt | neu | Spots | Beleg |
|---|---|---|---|---|
| 1 | Schwarzsee / Gantrisch | **Freiburger Voralpen** | 7 | Gurli, Schwyberg, Vounetse, La Vudalla — Kanton FR |
| 2 | Freiburger Voralpen | **Berner Oberland** | 70 | Adelboden, Kandersteg, Lenk, Gstaad, Interlaken |
| 3 | Berner Oberland | **Emmental** | 4 | nur Falkenflue + Marbachegg = Entlebuch |
| 4 | Seeland / Emmental | **Seeland** | 0 | macht „Emmental" für Zeile 3 frei (§2.1) |
| 5 | Berner Voralpen | **Berner Alpen** | 33 | First, Niederhorn, Brienzer Rothorn, Jungfraujoch |
| 6 | Mittelland West | **Plateau** | 0 | Vorgabe „Plateu" = Tippfehler (§2.2) |
| 7 | Mattertal / Saastal | **Walliser Hochalpen** | 13 | enthält Evolène + Sorebois, die gar nicht im Mattertal liegen |

### 1.2 Korrigiert gegenüber der Vorgabe (2026-08-02)

| # | alt | Vorgabe 26.07. | **neu** | Spots | warum die Vorgabe nicht trägt |
|---|---|---|---|---|---|
| 8 | Zentralschweizer Voralpen | ~~Urner Alpen~~ | **Zentralschweizer Alpen** | 87 | Inhalt ist Engelberg, Melchsee-Frutt, Stoos — Hochgebirge, nicht Voralpen; Uri stellt die Minderheit, Schwyz/Obwalden die Mehrheit |
| – | Waadtländer Alpen | ~~Bas-Valais~~ | **bleibt** | 26 | Leysin, Diablerets, Chamossaire, Les Pléiades sind Kanton Waadt; „Bas-Valais" gehört auf die andere Rhone-Seite (dort liegt `unterwallis`) |

### 1.3 Neu dazugekommen (2026-08-02)

| # | alt | neu | Spots | Beleg |
|---|---|---|---|---|
| 9 | Mittelland Zentral | **Zentrale Voralpen** | 22 | Pilatus, Rigi, Zugerberg, Chli Aubrig, Seebodenalp — kein Mittelland |
| 10 | Zentralwallis | **Lötschental** | 4 | die Spots sind Lauchernalp + Hockenhorngrat |
| 11 | Engadin Unter | **Mittelbünden** | 28 | Lenzerheide, Savognin, Parpaner Rothorn, Scalottas — kein Unterengadin-Spot |
| 12 | Engadin Ober | **Oberengadin** | 12 | Corvatsch, Diavolezza, Muottas Muragl — nur sprachlich geglättet |
| 13 | Ostschweiz | **Rheintal** | 12 | Chur, Calanda, Feldis, Pizol, Hoher Kasten; die id heisst bereits `rheintal` |
| 14 | Alpstein / Ostschweiz | **Alpstein / Toggenburg** | 6 | Ebenalp, Kronberg, Chäserugg; beseitigt das doppelte „Ostschweiz" |
| 15 | Glarnerland / Walensee | **Glarner Alpen** | 17 | Braunwald, Elm, Fronalp |
| 16 | Jura Ost | **Tafeljura** | 1 | Belchen, Wasserfallen, Hohwacht |
| 17 | Jura West | **Neuenburger Jura** | 9 | Chasseral, Chaumont, Tête de Ran, Mauborget |
| 18 | Tessin Nord | **Leventina / Blenio** | 4 | Bassa di Nara, Cari, Malvaglia |
| 19 | Tessin Zentral | **Locarnese / Bellinzonese** | 30 | Cimetta, Monte Tamaro, Mornera |

### 1.4 Bewusst unverändert (10)

Waadtländer Alpen (26) · Unterwallis (33) · Oberwallis / Goms (7) ·
Jura Zentral (21) · Mittelland Ost (2) · Zentrales Mittelland (1) ·
Genferseeregion (8) · Bodenseeraum (1) · Prättigau - Davos (23) · Surselva (13)

Zwei davon sind **Zuschnitt-Probleme, keine Namensprobleme** — und gehören
deshalb nicht in diese Migration:
- **Unterwallis** hält Crans-Montana, Anniviers und Nendaz, also das eigentliche
  Valais Central. Erst den Zuschnitt richten, dann benennen.
- **Jura Zentral** ist zur Hälfte solothurnisch (Weissenstein, Grenchenberg,
  Passwang), zur Hälfte bernisch (Montoz, Corgémont). „Berner Jura" wäre nur
  halb richtig.

### 1.5 Die ids

Entschieden am 2026-07-26: **technische `id`s werden mitmigriert.**

| alt | neu |
|---|---|
| `schwarzsee_gantrisch` | `freiburger_voralpen` |
| `freiburger_voralpen` | `berner_oberland` |
| `berner_oberland` | `emmental` |
| `seeland_emmental` | `seeland` |
| `berner_voralpen` | `berner_alpen` |
| `mittelland_west` | `plateau` |
| `mattertal_saastal` | `walliser_hochalpen` |
| `zentralschweizer_voralpen` | `zentralschweizer_alpen` |
| `mittelland_zentral` | `zentrale_voralpen` |
| `zentralwallis` | `loetschental` |
| `engadin_unter` | `mittelbuenden` |
| `engadin_ober` | `oberengadin` |
| `glarnerland_walensee` | `glarner_alpen` |
| `jura_ost` | `tafeljura` |
| `jura_west` | `neuenburger_jura` |
| `tessin_nord` | `leventina_blenio` |
| `tessin_zentral` | `locarnese_bellinzonese` |
| `rheintal` | *(unverändert — nur der Name ändert)* |
| `alpstein` | *(unverändert — nur der Name ändert)* |

**Zwei Zeilen sind reine Namensänderungen** (13, 14). Die Migration darf ihre
ids nicht anfassen, sonst laufen die Joins ins Leere.

### 1.6 Die drei Fallen beim Ersetzen

1. **Kette über drei Stufen:** Schwarzsee → Freiburger Voralpen → Berner
   Oberland → Emmental, bei Namen *und* ids. Naives Ersetzen wirft drei Regionen
   in einen Topf.
2. **Teilstrings:** „Ostschweiz" (Zeile 13) steckt auch in „Alpstein /
   Ostschweiz" (Zeile 14); „Emmental" (neu, Zeile 3) steckt in „Seeland /
   Emmental" (alt, Zeile 4). Ersetzt werden muss **längster Name zuerst**.
3. **Gleicher Name, andere Bedeutung:** beide Spot-CSVs führen neben
   `analyse_region` eine grobe `region`-Spalte aus der DHV-Herkunft, die
   ebenfalls „Ostschweiz" enthält (28 Zeilen in `pge`, 55 in `dhv`) — und
   ausserdem Zentralschweiz, Wallis, Waadt, Jura. Das ist **nicht** unsere
   Region. Ein flaches Suchen-und-Ersetzen beschädigt die Quelldaten.
   → Migration muss in diesen Dateien **spaltenscharf** laufen (§5).

Verfahren gegen alle drei: §5.

---

## 2. Offene Entscheide — vor dem Start zu klären

> **Beim Wiederaufnehmen hier anfangen.** Vier Punkte offen, alle im Randbereich
> — die inhaltlichen Entscheide sind gefallen.
>
> | # | Frage | Empfehlung |
> |---|---|---|
> | 1 | `data/history/*` (echte Chatverläufe, 115 Treffer) mitziehen? | **nein** (§2.3) |
> | 2 | `*.bak*`-Dateien mitziehen? | **nein** (§2.3) |
> | 3 | `fluggebiete_test.csv` / `foehntest.csv` mitziehen? | **ja** (§2.3) |
> | 4 | `data/preview/*` mitziehen? | egal, wird neu erzeugt (§2.3) |
>
> **Entschieden 2026-07-26:** ids werden mitmigriert · „Plateu" = `Plateau` (§2.2)
> · `Seeland / Emmental` → `Seeland` (§2.1).
> **Entschieden 2026-08-02:** die Liste umfasst 19 statt 8 Umbenennungen; statt
> „Urner Alpen" → `Zentralschweizer Alpen`; `Waadtländer Alpen` bleibt (§1.2).



### 2.1 „Emmental" — Kollision, aber harmloser als gedacht *(entschieden)*

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

### 2.2 „Plateu" → „Plateau" *(entschieden)*

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

**Neu gemessen am 2026-08-02** für alle 19 Altnamen inkl. Schreibvarianten plus
der 17 zu ändernden ids. Repo ohne `.git`, ohne Binaries:

| Bereich | Dateien | Treffer | Charakter |
|---|---|---|---|
| `data/weather_archive/*.json` | 61 | 22 737 | Historie, Join-Schlüssel jeder Validierung |
| `data/` CSV + GeoJSON + JSON | 20 | 5 801 | **live — Quelle der Wahrheit** |
| `validation/xcontest/**` | 46 | 2 847 | `observations.csv` (Daten) + datierte Analysen (Protokoll) |
| `cost_testing/**` | 61 | 310 | Golden-Fixtures + Reports |
| `docs/**` | 11 | 181 | Doku |
| `data/history/*` | 2 | 115 | echte Chatverläufe → §2.3 |
| `debug_scripts/**` | 15 | 93 | Ad-hoc-Werkzeuge |
| `skills/**` | 10 | 69 | **LLM-sichtbar** (de + en) |
| `meteo_research/**` | 9 | 40 | datierte Protokolle — nicht anfassen |
| Wurzel + übrige | 10 | 33 | Produktivcode: nur Kommentare/Beispiele |
| `data/preview/*` | 2 | 8 | Generat |
| `scripts/**` | 2 | 6 | Werkzeuge |
| `tests/**` | 3 | 4 | nur Kommentare |
| **Summe** | **252** | **32 244** | |

Gezählt **ohne dieses Plan-Dokument** (89 Treffer) — es enthält die Zuordnung
alt→neu und muss sie behalten.

Zum Vergleich: mit den ursprünglichen 8 Namen waren es 208 Dateien / 19 283
Treffer. Der Zuwachs kommt fast vollständig aus dem Archiv — die neu
dazugekommenen Regionen sind grosse: `Zentralschweizer Voralpen` allein rund
6 480 Treffer, `Tessin Zentral` 2 280, `Engadin Unter` 2 030,
`Mittelland Zentral` 2 005, `Ostschweiz` 1 980.

**Schreibvarianten, die mitmüssen** (sonst bleiben Reste stehen):
`Schwarzsee/Gantrisch`, `Mattertal/Saastal`, `Seeland/Emmental`,
`Alpstein/Ostschweiz`, `Glarnerland/Walensee` — jeweils ohne Leerzeichen um den
Schrägstrich. `Waadtlaender Alpen` (ASCII) entfällt, weil die Region bleibt.

### 3.1 Die Umzugsliste, Datei für Datei

**Stufe A — Quelle der Wahrheit (6 Dateien, 939 Treffer).** Ohne die stimmt
nichts; Namen *und* ids, in CSV-Spalten wie in GeoJSON-`properties`:

```
data/regionen.csv                             40   + description neu schreiben (§4)
data/fluggebiete_pge.csv                     393   aktive Spot-Quelle (USE_SPOT_CSV=pge)  ← nur Spalte analyse_region!
data/fluggebiete_dhv.csv                     389   Alternativquelle, muss schaltbar bleiben ← dito
data/regionen_polygone_mapped.geojson         39
data/regionen_referenzpunkte.geojson          39
data/regionen_referenzpunkte_precip.geojson   39
```

⚠️ Bei den beiden `fluggebiete_*.csv` darf **nur `analyse_region`** ersetzt
werden. Die Spalte `region` daneben trägt die grobe DHV-Herkunft (Ostschweiz,
Zentralschweiz, Wallis, Waadt, Jura …) und bedeutet etwas anderes — siehe §1.6
Falle 3.

**Stufe B — Historie und Daten (ca. 75 Dateien, 30 148 Treffer):**

```
data/weather_archive/*.json          61 Dateien  22 737   Join-Schluessel jeder Validierung
data/spot_analyses*.json              4 Dateien   2 065   LLM-Ergebnisse (davon 3 Backups → §2.3)
data/region_analyses*.json            3 Dateien     812   dito (davon 2 Backups)
validation/xcontest/observations.csv  1 Datei       840   Validierungs-Korpus
data/labeled_examples.jsonl                        795   live (Admin-UI + API, web.py:1903 ff.)
data/wetterdaten.json                               58
data/history/*, data/preview/*                     123   → §2.3, offen
```

**Stufe C — Text, Prompts, Fixtures (ca. 110 Dateien, 720 Treffer):**

```
cost_testing/**            61 Dateien  310   Golden-Fixtures
docs/**                    11 Dateien  181   v.a. REFPOINT_LISTE.md
debug_scripts/**           15 Dateien   93   Ad-hoc-Werkzeuge
skills/** (de + en)        10 Dateien   69   LLM-sichtbar
Produktivcode + Wurzel     10 Dateien   33   nur Kommentare/Beispieltext, s.u.
data/fluggebiete_test.csv                 24   → §2.3
scripts/**                  2 Dateien    6
tests/**                    3 Dateien    4   nur Kommentare
data/fluggebiete_foehntest.csv             3   → §2.3
```

**Bewusst NICHT umziehen (49 Dateien, 985 Treffer):** `validation/xcontest/*.md`
und `meteo_research/**` — datierte Protokolle. Dazu **dieses Plan-Dokument
selbst**, es enthält die Zuordnung alt→neu und muss sie behalten. Alle drei
Pfade gehören in die Ausnahmeliste der Restsuche (Schritt 3).

### 3.2 Der Befund, der den Plan billig macht — mit zwei Einschränkungen

**Im Kern hängt kein Produktivcode funktional am Regionsnamen.** Neu geprüft am
2026-08-02 über alle 19 Namen und 17 ids (`.py`, `.js`, `.html`). Der Grossteil
der Treffer sind Kommentare, Docstrings und LLM-Beispieltext:

| Datei | Zeile | Art |
|---|---|---|
| `config.py` | 132, 198, 901–906 | Kommentare (Fallbeispiele, Tuning-Notizen) |
| `fetch_weather.py` | 41, 315 | Kommentar + Docstring |
| `thermik_calculator.py` | 123–130 | Docstring der Elevation-Fallback-Schwellen |
| `engine/chat_orchestrator.py` | 236, 244 | LLM-Tool-Beschreibung „z.B. 'Berner Oberland'" |
| `engine/weather_context.py` | 2919, 3651 | Kommentare (Gewitter-Fallbeispiele) |
| `web.py` | 4382 | Kommentar |
| `static/js/region-map.js` | 499, 589 | Kommentare zur bbox-Heuristik |
| `tests/**` | 4 Stellen | Kommentare; die Assertions nutzen lat/lon |

Nirgends ein `dict`, das im Rechenweg auf Namen schlüsselt. Der Name fliesst aus
`regionen.csv` / `fluggebiete_pge.csv` durch die Pipeline.

**Einschränkung 1 — zwei Stellen mit hartkodierten ids, die sich ändern:**

| Datei | Zeile | was |
|---|---|---|
| `scripts/preview_briefing_email.py` | 10, 29–37 | Default-Regionsliste: `jura_ost`, `berner_voralpen`, `schwarzsee_gantrisch`, `glarnerland_walensee` — alle vier werden umbenannt |
| `data/preview/briefing_preview.html` | 313 | Generat mit id-Liste im Link → wird neu erzeugt |

**Einschränkung 2 — `import_dhv/**` darf NICHT migriert werden.**
`build_complete_csv.py:20-25` und `import_dhv_to_csv.py:29-34` mappen Kantone auf
die grobe DHV-Herkunft (`"St. Gallen": "Ostschweiz"`). Das ist die Spalte
`region`, nicht `analyse_region` — dieselbe Bedeutungskollision wie in §1.6
Falle 3, hier als Code. Beide Dateien gehören in die Ausnahmeliste.

**Das bleibt eine Datenmigration** — aber nicht mehr ausschliesslich eine über
Textdateien, siehe §3.3.

### 3.3 Wo ids ausserhalb der Dateien leben: die Abo-Datenbank

`subscriber.py:94-115` hält die Regions-Abos als JSON-Array in der Spalte
`subscribers.regions` — **ids, nicht Namen**. Ohne Mitziehen verlieren alle
bestehenden Abonnenten still ihre Regionsauswahl.

Gut: das Verfahren existiert bereits (`_REGION_ID_RENAMES` +
`_migrate_rename_region_ids`, idempotent über `WHERE regions LIKE`). Die 17
id-Renames werden dort angehängt.

**Aber — die vorhandene Implementierung hat genau das Ketten-Problem.** Sie
läuft `REPLACE` sequenziell je Paar. Mit unserer Kette würde aus einem Abo auf
`schwarzsee_gantrisch` nacheinander `freiburger_voralpen`, dann
`berner_oberland`, dann `emmental` — drei Regionen fielen zu einer zusammen.
→ **Die Schleife braucht denselben Zwei-Pass über Platzhalter wie das
Migrationsskript** (§5), sonst ist der Bug in der Datenbank statt in den Dateien.

*Nebenbei, historisch:* die Liste enthält bereits
`("urner_alpen", "bodenseeraum")` — die id `urner_alpen` war schon einmal
vergeben und wurde 2026-04 wegmigriert. Sie erneut zu benutzen (so die Vorgabe
vom 26.07.) hätte die alte Migration wieder scharf gestellt. Ein weiteres
Argument für `zentralschweizer_alpen` aus §1.2.

---

## 4. Was ein reiner Rename NICHT erledigt — und deshalb mit muss

`regionen.csv` trägt pro Region `description`, `terrain_type` und
`elevation_ref`. Nach der Umbenennung beschreiben die den **alten** Zuschnitt.
`source_area.py` gibt `description` ans Frontend (Karte) — das ist also sichtbar,
nicht intern:

| neuer Name | `description` heute | passt? |
|---|---|---|
| Berner Oberland *(ex Freiburger Voralpen, 70)* | „Moléson - freistehende Gipfel" | **nein** — Moléson ist nur einer von 70 |
| Emmental *(ex Berner Oberland, 4)* | „Eiger/Mönch/Jungfrau-Region mit Hochalpencharakter" | **nein** — das sind 4 Entlebuch-Spots |
| Berner Alpen *(ex Berner Voralpen, 33)* | „Niederhorn / Stockhorn - exponierte Grate" | **nein** — enthält Jungfrauregion, Schilthorn, Grindelwald |
| Zentrale Voralpen *(ex Mittelland Zentral, 22)* | „Napf-Gebiet - hügelig bis bergig" | **nein** — enthält Pilatus, Rigi, Zugerberg; der Napf liegt woanders |
| Mittelbünden *(ex Engadin Unter, 28)* | „Hochtal mit starken Talwindsystemen" | **nein** — Lenzerheide/Savognin sind kein Hochtal |
| Glarner Alpen *(ex Glarnerland / Walensee, 17)* | „Glarner **Voralpen** … voralpiner Flugcharakter" | **nein** — widerspricht dem neuen Namen |
| Alpstein / Toggenburg *(ex Alpstein / Ostschweiz, 6)* | „Markante Kalkfelsen Appenzell" | **nein** — Toggenburg (Chäserugg) fehlt |
| Lötschental *(ex Zentralwallis, 4)* | „Hochalpines Rhonetal Leukerbad/Lötschental" | teilweise — Leukerbad muss raus |
| Zentralschweizer Alpen *(ex Zentralschweizer Voralpen, 87)* | „Engelberg / Pilatus / Stoos" | teilweise — Pilatus liegt in Zeile 4 oben |
| Tafeljura *(ex Jura Ost, 1)* | „Jura-Ketten: Wasserflue / Geissflue" | teilweise — die Spots sind Belchen/Wasserfallen |
| Freiburger Voralpen *(ex Schwarzsee/Gantrisch, 7)* | „Voralpine Ketten Freiburg/Bern" | ja |
| Walliser Hochalpen *(ex Mattertal/Saastal, 13)* | „Tiefe Hochtäler mit Gletscherwind" | ja |
| Seeland *(ex Seeland / Emmental, 0)* | „Flaches Mittelland mit Hügelzone" | ja |
| Rheintal *(ex Ostschweiz, 12)* | „Rheintal mit Alpstein- und Sarganser Talflanken" | ja — passt sogar besser als vorher |
| Oberengadin, Neuenburger Jura, Leventina/Blenio, Locarnese/Bellinzonese | – | ja, unverändert brauchbar |

→ **`description` wird im selben Schritt neu geschrieben** (10 der 19 Zeilen).
Ohne das steht auf der Karte bei „Emmental" die Jungfrau und bei den
„Glarner Alpen" das Wort Voralpen.

**`terrain_type` / `elevation_ref` bleiben in diesem Plan unangetastet.** Sie
sind fachlich fragwürdig — 298 von 494 Spots bekommen über
`thermik_calculator.py:135-139` eine Terrain-Zone, die ihrer eigenen Höhe
widerspricht, weil die Region den Spot überstimmt. Das ist ein **Physik-Eingriff**
(er verändert `climb_factor_terrain` und damit jede Steigraten-Prognose) und
gehört nicht in eine Umbenennung. Eigener Plan, nach dem Rename.

**Nebenbefunde, nur zur Kenntnis, hier nicht angefasst:**
- `Mittelland West` (→ `Plateau`) und `Seeland / Emmental` (→ `Seeland`) haben
  **0 Spots** und laufen über den Refpoint-Pfad.
- `Mittelland Zentral` (→ `Zentrale Voralpen`) trägt `zone=alpennordhang` und
  `terrain_type=mittelland`. Nach der Umbenennung steht dort „Voralpen" bei
  Terrain „Mittelland" — für Pilatus und Rigi ohnehin falsch. Der `terrain_type`
  bleibt trotzdem draussen: das ist der Physik-Eingriff von oben, nicht
  Kosmetik. Nur im Blick behalten, dass die Umbenennung ihn **sichtbarer** macht.
- `zentralwallis` (→ `Lötschental`) hat nur 4 Spots und fällt damit unter
  `SPOT_MEDIAN_MIN_SPOTS = 3` knapp *nicht* — bleibt also Spot-Median-Region.

---

## 5. Vorgehen

### Schritt 0 — sauberer Ausgangspunkt *(Stand 2026-08-02: fast erledigt)*

Die XContest-Validierung von Ende Juli ist committet. Offen sind nur noch drei
unversionierte Datenstände (`data/lpi_archive/`, `data/synoptic_audit/`, ein
Archivtag) plus dieses Plan-Dokument. **Erst committen.** Sonst liegt eine
252-Dateien-Migration im selben Diff wie inhaltliche Arbeit — nicht reviewbar,
nicht einzeln zurückrollbar.

### Schritt 1 — Mapping als einzige Quelle

`data/region_renames_2026-08.csv` mit `alt;neu;typ;kommentar`
(`typ` ∈ `name` | `id` | `variante`). Kein Skript enthält Namenspaare hartkodiert;
Migration *und* Verifikation lesen dieselbe Tabelle. Enthält die 19 Namen, die
17 zu ändernden ids und die fünf Schreibvarianten aus §3 — und **nur** die: die
zwei reinen Namensänderungen (`rheintal`, `alpstein`) stehen ohne id-Zeile drin.

### Schritt 2 — Migrationsskript

`scripts/migrate_region_names.py`, **Default Dry-Run**, Schreiben nur mit
`--apply`, Backup je Datei vor dem ersten Schreiben.

Gegen das Ketten-Problem (§1.6 Falle 1) **keine Reihenfolge, sondern Zwei-Pass
über Platzhalter**: erst jeder Altname/jede id → `\x00<n>\x00`, dann Platzhalter
→ Neuname. Damit sind Ketten und selbst Ringtausche kollisionsfrei, unabhängig
von der Sortierung — robuster als „von hinten nach vorn", weil es nicht davon
abhängt, dass ich richtig sortiere.

Gegen die Teilstrings (§1.6 Falle 2) wird im ersten Pass **längster Name zuerst**
gesucht: `Alpstein / Ostschweiz` vor `Ostschweiz`, `Seeland / Emmental` vor
`Emmental`. Zusätzlich **wortgrenzen-bewusst**, damit `berner_oberland` nicht in
`berner_oberland_alt` trifft.

Gegen die Bedeutungskollision (§1.6 Falle 3) läuft die Migration bei
`fluggebiete_pge.csv` und `fluggebiete_dhv.csv` **nicht über den Dateitext,
sondern über die CSV-Spalten**: ersetzt wird ausschliesslich `analyse_region`.
Die Spalte `region` (grobe DHV-Herkunft, enthält ebenfalls „Ostschweiz") bleibt
unangetastet. Dasselbe gilt sinngemäss für die GeoJSONs: nur `properties.region`
und `properties.id`.

Umfang in drei einzeln schaltbaren Stufen:

- **A, zwingend** — `regionen.csv` (inkl. neuer `description`),
  `fluggebiete_pge.csv` + die übrigen Spot-CSVs **spaltenscharf**, beide GeoJSONs
  (`properties.region`, `properties.id`)
- **B, empfohlen** — 61 Archivtage, `region_analyses*.json`,
  `spot_analyses*.json`, `labeled_examples.jsonl`, `observations.csv`
- **C, empfohlen** — `skills/**` (de **und** en), `cost_testing`-Goldens,
  `docs/**`, die Code-Kommentare aus §3.2 und `scripts/preview_briefing_email.py`
- **D, zwingend, aber ausserhalb der Dateien** — die 17 id-Renames in
  `subscriber.py:_REGION_ID_RENAMES` anhängen **und die Schleife auf Zwei-Pass
  umstellen** (§3.3). Ohne D verlieren bestehende Abonnenten ihre Regionen.

**Nicht anfassen:** die datierten Analysen in `validation/xcontest/*.md` und
`meteo_research/**`. Das sind Protokolle eines Stands — sie bekommen oben einen
Hinweis auf die Umbenennung, werden aber nicht umgeschrieben. Sonst fälscht man
rückwirkend Befunde. Dazu **`import_dhv/**`** (§3.2, Einschränkung 2) und die
Spalte `region` in beiden Spot-CSVs — dort bedeutet „Ostschweiz" etwas anderes.

### Schritt 3 — Verifikation, mechanisch statt „sieht gut aus"

| Prüfung | Sollwert | beweist |
|---|---|---|
| Regionen-Zahl | 29 → 29, kein Name doppelt | nichts verloren/verschmolzen |
| Spots je Region | identisch (mapping-übersetzt) | keine Zuordnung abgerissen |
| Punkt-in-Polygon | wieder 476/494 im eigenen Polygon, 0 Widersprüche | CSV und GeoJSON konsistent migriert |
| Restsuche Altnamen | 0 Treffer in Stufe A/B/C | keine Schreibvariante vergessen |
| `region`-Spalte beider Spot-CSVs | **unverändert** (28 bzw. 55× „Ostschweiz" bleiben) | die Bedeutungskollision hat nicht zugeschlagen |
| `pytest` | wie vor der Migration | (Referenz: zuletzt 280 passed, 15 skipped, 3 vorbestehende Playwright-Errors) |
| `cost_testing` gegen Goldens | grün | LLM-Pfad unverändert |
| `scripts/validate_climb_onesided.py` | **identische Perzentile je Region** | die Migration hat keine Daten getrennt |
| Abo-DB: `SELECT regions FROM subscribers` | Zahl der Regionen je Abo **unverändert**, keine Zeile mit `emmental` die vorher `schwarzsee_gantrisch` war | die Kette ist in der DB nicht kollabiert (§3.3) |

Die letzte Zeile ist die schärfste: weicht ein Perzentil ab, hat der Rename einen
Join zerschnitten.

### Schritt 4 — keine Alias-Schicht

Die Alternative wäre, die Archive unangetastet zu lassen und im Lesepfad zu
übersetzen. Davon rate ich ab: die Alias-Anwendung müsste in jedem Leser stehen
(Validierungsskripte, Replay, `region_analyses`-Loader) und bricht still, sobald
einer sie vergisst. Einmal migrieren mit Backup ist sauberer als eine dauerhafte
Übersetzungsschicht.

### Schritt 5 — nachziehen

`SYSTEM_CHANGES.md`, Notiz in `validation/xcontest/PATTERNS.md` (sonst ist die
Befund-2-Tabelle der 49-Tage-Analyse nicht mehr lesbar — sie nennt alte Namen),
Memory aktualisieren. Dazu die **Regionsauswahl im Frontend** einmal ansehen:
19 von 29 Regionen heissen anders, bestehende Abonnenten sehen beim nächsten
Login neue Namen — ein kurzer Hinweistext im Abo-Bereich ist vermutlich
angebracht.

### Rollback

Ein Commit je Stufe (A / B / C / D). `git revert` der jeweiligen Stufe stellt den
Stand her; zusätzlich die Datei-Backups aus Schritt 2.

**Ausnahme D:** Die Abo-DB ist nicht versioniert. Vor Stufe D eine Kopie der
SQLite-Datei ziehen — ein `git revert` erreicht sie nicht.

---

## 6. Was der Rename bringt — und was nicht

**Bringt:** Der Benennungs-Effekt verschwindet. Die 70-Spot-Region mit Niesen,
Adelboden und Gstaad heisst dann „Berner Oberland", die 4 Entlebuch-Spots heissen
nicht mehr so. Regionale Auswertungen vergleichen wieder die Gebiete, die die
Namen suggerieren. Piloten und LLM sehen im Chat den richtigen Namen.

Mit der erweiterten Liste kommen drei Dinge dazu, die vorher offen blieben:
- **Das doppelte „Ostschweiz" verschwindet.** Bisher trugen zwei Regionen den
  Namen und meinten Verschiedenes (Chur/Rheintal vs. Alpstein/Toggenburg).
- **„Engadin Unter" heisst nicht mehr Engadin,** obwohl 28 Spots in Mittelbünden
  liegen. Der Zuschnitt bleibt zwar wie er ist — aber der Name lügt nicht mehr.
- **„Mittelland Zentral" heisst nicht mehr Mittelland,** obwohl Pilatus und Rigi
  drin sind.

**Bringt nicht:**
- Die **echte Schieflage** aus I-016. „Jura Zentral 100 %" ist unberührt — die
  Region wird nicht umbenannt und ist kompakt.
- Den **Zuschnitt**. „Zentralschweizer Alpen" bleibt ein Topf mit 87 Spots von
  Stoos bis Gemsstock; ein Median darüber bleibt schwach. Ebenso bleibt
  `unterwallis` mit Crans-Montana und Anniviers zu gross und falsch geschnitten
  — genau deshalb wird es **nicht** in „Bas-Valais" umbenannt (§1.2).
- Die **Polygon-Fehlzuordnung** hinter „Engadin": Scuol/Motta Naluns liegt im
  Polygon `Engadin Ober` (→ `Oberengadin`). Der Rename macht den Namen ehrlich,
  nicht die Geometrie. Eigener Schritt.
- Die **Terrain-Zonen-Schieflage** aus §4 — die Umbenennung macht sie sogar
  sichtbarer (`Zentrale Voralpen` mit `terrain_type=mittelland`).

Diese vier bleiben nach dem Rename offen und sind bewusst nicht mitgemischt.
