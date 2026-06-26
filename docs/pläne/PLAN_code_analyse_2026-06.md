# Plan: Verbesserungen aus der Code-Analyse (Juni 2026)

**Stand:** 2026-06-10 (Abend) · **Status:** Befunde verifiziert, Umsetzung startet mit Paket 3 · **Zielgruppe dieses Dokuments:** Management / Nicht-Techniker

> **Update 2026-06-10 Abend:** Die vier Server-/Kosten-Punkte (Paket 3) wurden im Code
> und an den Live-Daten nachgeprüft. Drei bestätigt, **einer war falsch**: Der Vorfilter
> funktioniert in Wahrheit einwandfrei (er spart bereits ~1.200 KI-Aufrufe pro Tag) —
> nur sein Statistik-Zähler zeigt fälschlich null an. Die geschätzte Ersparnis von
> ~120 $/Monat entfällt damit; sie ist schon realisiert. Details unten im Abschnitt
> „Stand der Umsetzung". Noch wurde **nichts am Code geändert**.

---

## Worum geht es?

Im Juni 2026 wurde der gesamte Wingcast-Code (~33.000 Zeilen) systematisch untersucht —
auf Rechenfehler, Geschwindigkeit/Kosten und Wartbarkeit. Das Ergebnis in einem Satz:

> **Das Fundament ist solide, aber es gibt eine Handvoll konkreter Fehler, die unsere
> Prognosen verfälschen, einen Speicherfresser, der den Server an seine Grenze bringt,
> und eine Test-Absicherung, die derzeit gar nicht greift.**

Dieser Plan beschreibt, was wir beheben sollten, warum, und in welcher Reihenfolge.

---

## Die wichtigsten Erkenntnisse — ohne Technik-Jargon

### 1. Drei Rechenfehler machen Prognosen falsch

| Problem | Was es für den Nutzer bedeutet |
|---|---|
| **Thermik-Bremse wirkt nie.** Ein Wetterwert (CIN, „Deckel über der Thermik") wird mit falschem Vorzeichen geprüft. Die eingebaute Abwertung für gedeckelte Tage greift dadurch **nie**. | Thermik-Bewertungen fallen systematisch **zu optimistisch** aus — genau das Problem, das uns Nutzer bereits gemeldet haben. |
| **Regionen sehen den Bodenwind nicht.** Die Regions-Analyse fragt Wind-Warnwerte ab, die an dieser Stelle nie gespeichert werden. Sie liest immer „null Warnstunden". | Eine Region kann selbst an einem **Sturmtag** ohne Bodenwind-Warnung erscheinen. |
| **Eine Sicherheitsregel hebelt sich selbst aus.** Bei Starkwind in der Höhe soll gelten: „viele Gefahrenstunden ODER gefährliches Muster → nicht sicher". Im Code überschreibt das Muster aber die Stundenzählung. | Ein Tag mit 5 verstreuten Gefahrenstunden kann als „bedingt fliegbar" durchrutschen statt als „nicht sicher". **Sicherheitsrelevant.** |

Dazu kommen kleinere Fehler derselben Art: fehlende Wetterdaten werden stillschweigend
als „gutes Wetter" gewertet, Nordföhn ist auf dem Dashboard unsichtbar, und zwei Teile
des Systems bewerten dieselbe Regen-Stunde unterschiedlich streng.

**Gemeinsame Ursache:** Wenn irgendwo ein Wert fehlt, nimmt das System still einen
Ersatzwert an (oft „0" oder „alles ok"), statt zu warnen. Das ist exakt die Fehlerklasse,
die uns schon die aufwendigen Einzelfall-Untersuchungen (Scheidegg, Föhn) beschert hat.

### 2. Der Server ächzt unnötig

- Die Wetterdaten-Datei (209 MB) wird beim Start komplett in den Speicher geladen und
  bläht sich dort auf ~700 MB auf. Beim täglichen Update liegen zeitweise **drei Kopien**
  gleichzeitig im Speicher. **Das ist der Grund, warum der Server Auslagerungsspeicher
  (Swap) braucht** und zeitweise langsam wird.
- Die Startseite lädt bei jedem Aufruf **9 MB** unkomprimierte Daten — für Handynutzer
  spürbar langsam. Eine Komprimierung (eine Zeile Konfiguration) reduziert das um ~90 %.
- Die KI-Analysen kosten aktuell **~8,50 $ pro Tag** (~250 $/Monat).
  ~~Der Vorfilter überspringt null Analysen → ~120 $/Monat Ersparnis~~ — **Korrektur
  nach Prüfung (10.06.):** Der Vorfilter arbeitet korrekt und spart bereits ~1.200
  KI-Aufrufe pro Tag. Kaputt ist nur sein **Statistik-Zähler** (er wird in dem
  Programmpfad, den der tägliche Lauf nutzt, nie hochgezählt) — die Kostenstatistik
  lügt also, nicht der Filter. Fix: Zähler reparieren, damit wir den Kosten echten
  Zahlen trauen können.
- **Sieben** kostenintensive bzw. zustandsändernde Funktionen (Wetter-Neuladen,
  Spot-/Region-Analyse-Läufe in je zwei Varianten, Wetterlage-Refresh, Spot-Reload)
  sind **ohne Anmeldung** von außen aufrufbar — jemand könnte uns damit pro Aufruf
  bis zu ~8 $ Kosten verursachen. Der restliche Admin-Bereich ist sauber geschützt
  (alle 40+ Admin-Routen geprüft).

### 3. Unser Sicherheitsnetz hängt durch

- Es existieren **209 automatische Tests** — aber sie laufen derzeit wegen eines
  Startfehlers **gar nicht** und werden beim Deployment nicht ausgeführt. Reparatur:
  ca. 1 Stunde.
- Software-Bibliotheken sind nicht auf feste Versionen festgelegt: Jedes Deployment
  kann unbemerkt eine neue, inkompatible Version installieren.
- Der Text, den die KI als Eingabe bekommt, wird nach jeder Analyse **weggeworfen**.
  Jede Nachfrage „Warum sagt die App hier nicht sicher?" wird dadurch zur stundenlangen
  Detektivarbeit (siehe Scheidegg). Würden wir ihn aufheben, wäre es eine 5-Minuten-Frage.

---

## Der Plan: 4 Pakete

### Paket 1 — Prognose-Fehler beheben (höchste Priorität)
**Aufwand: ~1–2 Tage · Nutzen: korrektere und sicherere Prognosen**

1. Thermik-Bremse (CIN-Vorzeichen) korrigieren.
2. Bodenwind-Daten auch für Regionen speichern.
3. Sicherheitsregel „Stunden ODER Muster" so umsetzen, wie sie dokumentiert ist.
4. Fehlende Wetterdaten als „unbekannt" behandeln statt als „gut".
5. Regen-Schwelle vereinheitlichen, Nordföhn auf dem Dashboard sichtbar machen.

### Paket 2 — Sicherheitsnetz spannen
**Aufwand: ~0,5–1 Tag · Nutzen: künftige Fehler fallen sofort auf statt beim Nutzer**

1. Testsuite reparieren (209 Tests wieder lauffähig, 3 veraltete Tests aktualisieren).
2. Tests automatisch vor jedem Deployment laufen lassen — schlägt einer fehl, wird
   nicht deployt.
3. Bibliotheks-Versionen festschreiben.
4. KI-Eingabetexte pro Analyse einige Tage aufbewahren (Debugging in Minuten statt Stunden).

### Paket 3 — Server entlasten & Kosten senken
**Aufwand: ~2–3 Tage · Nutzen: schnellere App, kein Swap, ~120 $/Monat weniger KI-Kosten**

1. Die sieben offenen Admin-Funktionen hinter die Anmeldung legen.
2. Komprimierung im Webserver aktivieren (Sofortmaßnahme, eine Zeile).
3. Doppeltes Laden der Wetterdaten abstellen; Reserve-Kopie nur bei Bedarf laden
   (Speicherspitze sinkt von 3 auf 2 Datenkopien, ~700 MB weniger).
4. Vorfilter-Statistik-Zähler reparieren (Filter selbst funktioniert — siehe
   Korrektur oben). *Optionale spätere Idee:* Regions-Ergebnis für Spots in
   „roten" Regionen wiederverwenden — das wäre aber eine inhaltliche
   Design-Entscheidung, kein Bugfix, und wird separat entschieden.
5. Alte Archivdateien automatisch aufräumen (wachsen derzeit unbegrenzt).

### Paket 4 — Aufräumen für die Zukunft (kein Zeitdruck)
**Aufwand: verteilt, je ~0,5–1 Tag pro Punkt · Nutzen: weniger Folgefehler, schnellere Entwicklung**

1. Einheitliches Datenformat für Analyse-Ergebnisse (verhindert die „Phantomfeld"-Fehlerklasse).
2. Vierfach kopierten KI-Aufruf-Code zu einer Funktion zusammenführen.
3. Stilles „Fehler schlucken" (~50 Stellen) durch Protokollierung ersetzen.
4. Produktions-Webserver statt Entwicklungs-Server einsetzen.
5. Die zwei größten Code-Dateien in handliche, einzeln testbare Teile zerlegen.
6. Veraltete Einmal-Skripte und Forschungsordner ins Archiv verschieben.

---

## Empfohlene Reihenfolge & Gesamtaufwand

| Schritt | Inhalt | Aufwand | Warum zuerst |
|---|---|---|---|
| 1 | Paket 2.1–2.2 (Tests reparieren + Deployment-Gate) | ~1 h | Sichert alle weiteren Änderungen ab |
| 2 | Paket 1 (Prognose-Fehler) | 1–2 Tage | Direkter Qualitäts- und Sicherheitsgewinn |
| 3 | Paket 3.1–3.2 (Komprimierung + Speicher) | ~1 Tag | Spürbar schnellere App, Swap-Spitzen weg |
| 4 | Paket 2.3–2.4, Paket 3.3–3.5 | 1–2 Tage | Kosten runter, Debugging-Zeit runter |
| 5 | Paket 4 | laufend | Nach und nach, jeweils abgesichert durch Schritt 1 |

**Gesamt für Schritt 1–4: rund eine Arbeitswoche.** Danach: korrektere Prognosen,
eine schnellere App, ~120 $/Monat geringere Kosten und ein Sicherheitsnetz, das
Folgefehler abfängt, bevor Nutzer sie sehen.

---

## Stand der Umsetzung

**2026-06-10 Abend — Paket 3 vollständig verifiziert, noch nichts geändert.**
Beschlossene Reihenfolge für die Umsetzung (morgen weiter):

1. **Auth:** Alle 7 offenen Endpoints mit `@_require_admin` versehen (Liste im Anhang).
   Risiko geprüft: Einzige lebende Aufrufer sind die Admin-Config-Seite und ein
   **toter** Handler in `chat.js:716` (`refreshWeatherBtn` existiert in keinem
   Template mehr). Keine Cronjobs / n8n-Workflows / Hermes-Aufrufer — geprüft.
   **Update 10.06. spät:** `_require_admin` wurde inzwischen auf Session-E-Mail-Check
   umgestellt (Magic-Link als `ADMIN_EMAIL`, Commit `376d1ab`, kein Basic-Auth mehr) —
   same-origin-Fetches der Admin-Seite schicken das Session-Cookie automatisch mit,
   der Decorator ist also gefahrlos ergänzbar. Nach Deploy: Buttons auf
   `/admin/config` einmal durchklicken.
2. **Caddy:** `encode zstd gzip` in Repo-`caddyfile` **und** `/etc/caddy/Caddyfile`
   (beide aktuell identisch, Caddy v2.11.2), dann `systemctl reload caddy`.
3. **Speicher:** (a) `fetch_weather.py:946` Fallback-Cache lazy laden,
   (b) `web.py` (`api_briefing_generate`) + `scheduler.py:116` auf
   `engine.weather_data` umstellen (verifiziert: Synoptik liest nur Spot-Dicts,
   überspringt `_`-Keys — das gepoppte `_regions` stört nicht).
4. **Telemetrie:** `prefilter_skipped`-Zähler im Parallel-Pfad inkrementieren.
5. Danach: Tests laufen lassen, deployen (`deploy.sh` stasht Uncommitted —
   Few-Shot-Arbeit bleibt erhalten).

**Verifikation Vorfilter (Beleg für die Korrektur):** Live-Daten vom 10.06.:
2.440 Spot-Tage, 1.618 not_safe, davon **1.226 mit deterministischen
Pre-Filter-Begründungen** (u. a. 556× `wind_direction_mismatch`). Der Zähler wird
nur im Batch-Pfad gesetzt (`engine/analyzers.py:2603`); der tägliche Lauf nutzt
aber den Parallel-Pfad (`run_all_analyses_stream` via `scheduler.py:283`), der
ihn nie inkrementiert. Telemetrie aller letzten 6 Tage: `mode=parallel,
prefilter_skipped=0` bei 1.810–2.283 Calls/Tag.

---

## Anhang für die Umsetzung (technisch)

Kurzreferenzen zu den Fundstellen — Details stehen in der Analyse vom 2026-06-10.

**Paket 1 (Logik):**
- CIN-Vorzeichen: `thermik_calculator.py:1424` (`< -100`/`< -50` → positive Beträge; Open-Meteo liefert 0…412)
- Region-Gust-Cache-Keys fehlen: Writer `engine/weather_context.py:3479` vs. Reader `engine/decision_engine.py:961`; zusätzlich `decide_wind_strong_majority` auf Engine-Zählwerte statt LLM-Echo umstellen (`decision_engine.py:483`)
- Aloft-Trigger: `engine/decision_engine.py:186` (`triggers = False` im else-Zweig widerspricht Docstring „ODER")
- Fehlende Daten: `chat_engine.py:560` (Wind→OK-Fallback), `foehn_indicators.py:146` (dir=0°→Nord), `thermik_calculator.py:1584` (RH=50)
- Regen-Drift: `weather_context.py:637` (>0.05) vs. `1705/2989` (>0); „Regen nach Fenster" unerreichbar: `weather_context.py:1592/2862` + `decision_engine.py:893`
- Nordföhn-Dashboard: `foehn_indicators.py:403` (default `kritischer_foehn="Süd"`); Crest-Danger 180 km/h: `foehn_indicators.py:49`
- Terrain-Zone in Thermal-Tags: `weather_context.py:1892` (`spot.get("region_id")` ist immer None → `spot_region_id` durchreichen)
- Hartcodierte Segment-Schwellen: `weather_context.py:2104` (40/30 statt config 30/20)
- Querschnitts-Guard: Schema-Assert beim Schreiben des `_ctx_gust_cache` (Spot- vs. Region-Keyset)

**Paket 2 (Sicherheitsnetz):**
- `tests/test_e2e_meteogram.py:40`: `sys.exit(2)` → `pytest.skip(allow_module_level=True)`
- 3 stale Tests: `test_spots_data.py:12`, `test_model_config.py:18`, `test_decision_engine.py:1018` (warn→reducer)
- deploy.sh: `pytest -q tests/ || exit 1` vor Restart
- `pip freeze > requirements.lock`, Installation aus Lock
- Analysis-Audit: `{ctx, raw_llm_json, decisions_applied}` gzipped nach `data/analysis_audit/<date>/` (Aufbau analog `data/synoptic_audit/`); Einstieg `engine/analyzers.py:98`

**Paket 3 (Performance/Kosten)** — verifiziert 2026-06-10:
- Caddyfile: `encode zstd gzip` — Repo-`caddyfile` UND `/etc/caddy/Caddyfile` (identisch, v2.11.2), `systemctl reload caddy`
- `fetch_weather.py:946`: Fallback-Cache lazy laden — Nutzstellen sind nur die Fehlerpfade Zeilen 1133/1137 (`_mark_stale_cache`) und 1201/1206 (per-Spot-Fallback); memoisierter Helper, Verhalten identisch
- `web.py` `api_briefing_generate` (~Z. 2474) + `scheduler.py:116`: `engine.weather_data` durchreichen statt `load_cached_weather()`-Re-Parse (2,4 s + ~700 MB transient); Disk-Fallback behalten, falls `engine.weather_data` leer. Verifiziert: alle Synoptik-Funktionen (`synoptic_context.py`) iterieren nur Spot-Dicts und skippen `_`-Keys
- Vorfilter-Zähler: Parallel-Pfad (`run_all_analyses_stream`, `analyzers.py:2997` ff. / `_build_and_analyze_spot` Z. 107-110) inkrementiert `cost_tracker.prefilter_skipped` nie — nur Batch-Pfad tut es (Z. 2603). **Filter selbst funktioniert** (1.226/1.618 not_safe am 10.06. deterministisch). Region-Verdict-Reuse = separate Design-Entscheidung, nicht Teil dieses Pakets
- Auth → `@_require_admin` für 7 Routen: `web.py:2462` (`/api/briefing/generate`), `:2576` (`/api/run-analyses`, kein lebender Aufrufer), `:2801` (`/api/run-region-analyses`, kein lebender Aufrufer), `:3108` (`/api/run-analyses-stream`, Aufrufer: admin/config), `:3114` (`/api/run-region-analyses-stream`, Aufrufer: admin/config), `:3147` (`/api/refresh-spots`), `:3157` (`/api/refresh-weather`, Aufrufer: admin/config + toter Code `chat.js:716`)
- Retention: `scheduler.py:251` (weather_archive ~60 Tage), `data/*.bak*`, alte `foehn_cache_*.json`
- Optional: `wetterdaten.json` ohne `indent=2` schreiben (`config.py:1185`); langfristig Stunden-Arrays statt Dict-of-Dicts

**Paket 4 (Qualität):**
- `SpotDayResult`-TypedDict, Normalisierung in `_merge_safety_flyability` (`analyzers.py:667`)
- LLM-Call-Dedup: `analyzers.py:322/382/484/545` → eine `_llm_analysis_call(...)`
- `except Exception: pass` (~50×, u. a. `weather_context.py:748/756/1299/1707`) → mindestens `logger.debug(..., exc_info=True)`
- gunicorn (`--workers 1 --threads 16 --worker-class gthread`; 1 Worker wegen In-Process-State/Scheduler); `FLASK_DEBUG`-Default in `main.py` auf false
- `_build_single_spot_context` (870 Zeilen, `weather_context.py:1447`) in Sektions-Builder splitten
- Archiv: `debug_scripts/`, `debug_weissenstein_wind.py`, `xcontest_validation/`, `marktresearch/`, `meteo_research/`, `import_dhv/` → `archive/`; **`cost_testing/` ist live** (web.py:1502), nicht verschieben
