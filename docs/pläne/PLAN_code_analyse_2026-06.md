# Plan: Verbesserungen aus der Code-Analyse (Juni 2026)

**Stand:** 2026-06-10 · **Status:** Nicht begonnen · **Zielgruppe dieses Dokuments:** Management / Nicht-Techniker

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
- Die KI-Analysen kosten aktuell **~8,50 $ pro Tag** (~250 $/Monat). Der eingebaute
  Vorfilter, der aussichtslose Tage überspringen soll, überspringt derzeit **null**
  Analysen. Mit funktionierendem Filter sparen wir geschätzt **~120 $/Monat**.
- Zwei kostenintensive Funktionen (Wetter-Neuladen, kompletter Analyse-Lauf) sind
  **ohne Anmeldung** von außen aufrufbar — jemand könnte uns damit Kosten verursachen.

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

1. Komprimierung im Webserver aktivieren (Sofortmaßnahme, eine Zeile).
2. Doppeltes Laden der Wetterdaten abstellen; Reserve-Kopie nur bei Bedarf laden.
3. Vorfilter scharf stellen: aussichtslose Tage ohne KI-Analyse abhandeln,
   Regions-Ergebnis für Spots in „roten" Regionen wiederverwenden.
4. Die zwei offenen Admin-Funktionen hinter die Anmeldung legen.
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

**Paket 3 (Performance/Kosten):**
- Caddyfile: `encode zstd gzip`
- `fetch_weather.py:946`: Fallback-Cache lazy; `web.py:2474` + `scheduler.py:116`: `engine.weather_data` nutzen statt Re-Parse
- Vorfilter: `prefilter_skipped` in `data/cost_telemetry.jsonl` beobachten; Region-Verdict-Reuse via `analyzers.py:1552`
- Auth: `web.py:3157` (`/api/refresh-weather`), `web.py:2576` (`/api/run-analyses`) → `@_require_admin`
- Retention: `scheduler.py:251` (weather_archive ~60 Tage), `data/*.bak*`, alte `foehn_cache_*.json`
- Optional: `wetterdaten.json` ohne `indent=2` schreiben (`config.py:1185`); langfristig Stunden-Arrays statt Dict-of-Dicts

**Paket 4 (Qualität):**
- `SpotDayResult`-TypedDict, Normalisierung in `_merge_safety_flyability` (`analyzers.py:667`)
- LLM-Call-Dedup: `analyzers.py:322/382/484/545` → eine `_llm_analysis_call(...)`
- `except Exception: pass` (~50×, u. a. `weather_context.py:748/756/1299/1707`) → mindestens `logger.debug(..., exc_info=True)`
- gunicorn (`--workers 1 --threads 16 --worker-class gthread`; 1 Worker wegen In-Process-State/Scheduler); `FLASK_DEBUG`-Default in `main.py` auf false
- `_build_single_spot_context` (870 Zeilen, `weather_context.py:1447`) in Sektions-Builder splitten
- Archiv: `debug_scripts/`, `debug_weissenstein_wind.py`, `xcontest_validation/`, `marktresearch/`, `meteo_research/`, `import_dhv/` → `archive/`; **`cost_testing/` ist live** (web.py:1502), nicht verschieben
