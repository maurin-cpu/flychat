# Morgenbriefing — Aufbau, Prinzip, Labels

**Stand:** 2026-09-19 · Gilt für das **versendete Mail** ab 19.09.2026 und (§8) die App-Seite `/briefing`
(`email_service.send_briefing_email` → `templates/email/briefing_v3.html`/`.txt`)
und die Vorschau-Seite (`scripts/preview_briefing_email.py` →
`data/preview/briefing_preview.html`). Beide bauen denselben Kontext
(`scripts/briefing_v3_context.build_v3_context`); die Vorschau ist die
Design-Referenz, das Mail-Template die mail-sichere Fassung (Tabellen,
Inline-CSS, Karte als Inline-Bild `cid:synoptik`). Schalter
`WINGCAST_BRIEFING_VERSION=v2` fällt ohne Deploy auf das alte Layout zurück;
bricht der v3-Aufbau, geht v2 automatisch raus.

## Für den Manager

Das Briefing beantwortet jeden Morgen eine Frage: **Stimmt das, was die
Grosswetterlage erwarten lässt, mit dem überein, was unsere Prognosedaten für
den Tag zeigen — und wo nicht?** Jeder Block der Analyse-Kette stellt zuerst
die Erwartung aus der Synoptik (Druckzentren, Strömung, Luftmasse, Druck-
tendenz), hält dann die Prognosedaten dagegen und spricht ein Urteil. Das
Urteil steht als farbige Pille im Titel, die Begründung als ein kurzer Satz
darunter. Alles ausser dem Lage-Satz und den Regionstexten rechnet der Code —
gleich an jedem Tag, nie erfunden. Nur Prognosedaten, keine Messungen.

## 1. Prinzip

1. **Erwartung** aus der Synoptik: Druckzentren → Strömung → Luftmasse;
   Druck über der Schweiz und seine Tendenz; DWD-Frontenprognose.
2. **Daten** aus der eigenen Prognose (Open-Meteo, ICON-CH1/CH2 als Haupt-
   modelle): je Zone, Region oder Startplatz, stündlich.
3. **Urteil**: passt / teilweise / passt nicht — und was das für den Piloten
   heisst. Die Logik muss stimmen: „beruhigt sich" darf nie neben „Schauer
   nehmen zu" stehen (§6).

Zonen sind die vier Synoptik-Zonen `config.SYNOPTIC_ZONES`: Alpennordhang,
Wallis, Tessin, Graubünden & Engadin. Nur der Tag zählt — kein Ausblick auf
Folgetage in den Blöcken (die haben ihr eigenes Briefing).

## 2. Aufbau der Seite

| Sektion | Inhalt | Quelle |
|---|---|---|
| Kopf | Betreff, Vorschautext, beste Abo-Region mit Note und Fenster | Code |
| Woche als Bild | drei Tageskacheln: Einstufung, Note, Druck, Höhenwind-Pfeil, Regionen-Gruppen, CH-Zählung. **Kein** Tages-Hinweis, keine Auffälligkeits-Zeile — beides las sich als Urteil über die gelisteten Regionen | Code |
| Synoptik-Karte | Screenshot der App-Karte `/synoptik/karte` (Festland Spanien–Slowakei, Isobaren, H/T, DWD-Fronten, Höhenwind-Pfeile) | App + Playwright |
| **Analyse-Kette** | acht Blöcke, §3 | Code (Block 1 künftig KI) |
| Warnungen Schweiz | Gefahren-Schalter je Tag mit Ausmass, Zeitfenster und **synoptischer Ursache** | Code (+ KI-Satz, wenn vorhanden) |
| Deine Regionen | je Abo-Region Note, Fenster, Chips, erster Satz der Regions-Einschätzung | Code + KI (Regionsanalyse) |

Die Seite zeigt nur, was das Mail am Ende zeigt — keine Vorschau-Kopfzeile,
keine Code/KI-Badges.

## 3. Die Analyse-Kette

Reihenfolge wie ein Pilot die Lage liest. Jeder Block: Titel mit Icon und
Status-Pille, Fakten-Chips, ein Satz (erster Teil fett = Aussage).

| # | Block | Erwartung (Synoptik) | Daten (Prognose) | Urteil / Satz |
|---|---|---|---|---|
| 1 | Lage | Druckzentren → Strömung → Luftmasse; Druck und Tendenz | Regen und Wind für die ganze Schweiz (Nord/Süd-Aggregate), Regen-Trend im Tagesverlauf | drei Sätze: Einfluss, Druck mit Bedeutung, „ICON-CH1/ICON-D2 bestätigt das / passt nur teilweise dazu / widerspricht: …“. Urteil: Erwartung (beruhigend / unbeständig / Übergang) gegen Stufe der Daten (0 trocken & ruhig, 1 teils/einseitig, 2 verbreitet/kräftig) |
| 2 | Fronten | DWD-Frontenprognose (`fronten.durchgaenge`), letzte drei Läufe zusammengeführt, ältere Aussagen gegen die Karte des Tages geprüft | **Frontsignatur** je Zone: Druckminimum + Anstieg ≥ 1.2 hPa/3 h, Winddrehung ≥ 40° auf 700 hPa, dazu T850-Sprung ≥ 2 K oder ≥ 1 mm Regen | „zieht durch" nur mit Signatur; DWD ohne Signatur → „schwächt sich ab"; gestern durchgezogen → „Rückseite" |
| 3 | Föhn / Bise | Druckgefälle über die Alpen (Schwelle 4 hPa), Druckgefälle NE–S und 700-hPa-Richtung für Bise | Böen am Lee-**Prognosepunkt** (Zürich / Lugano); starke Winde an einzelnen Startplätzen (≥ 40 km/h, mit Richtung, Höhe, Stunde); Nordostwind im Mittelland | Bise nur erwähnt, wenn Nord-/Ostkomponente, aktiv oder am Boden sichtbar. Kein „Föhntal": wir wissen nicht, welcher Punkt im Tal liegt |
| 4 | Höhenwind | Schweizer Mittel 700 hPa (Vektormittel 12 Uhr) mit Stärkeklasse | Spanne der Regionsspitzen (schwächste bis stärkste Region, Stunde); ⅔-Regel für den Boden | Klasse der Spitze gegen Klasse des Mittels: „regional stärker / wie im Mittel / schwächer". Das ist ein Auflösungs-, kein Quellen-Vergleich |
| 5 | Labilität | Luftmasse (SW feucht → labil im Süden; N/NW kühl → Schauer am Nordhang), Druck deckelt oder begünstigt | CAPE je Zone in Klassen (150/400/1000), Modell-Gewitter mit Beginn, Überentwicklung | Urteil: „Die Prognosedaten bestätigen …" (blockspezifisch: die Labilität dort, wo die Lage sie erwarten lässt / die stabile Schichtung / die gedeckelte bzw. hohe Basis / die Zweiteilung bzw. landesweit) / „nur teilweise — der Deckel hält im Norden nicht" / „zeigen das nicht — stabiler als …" / „widersprechen — labiler als …" |
| 6 | Thermik / Basis | Hoch → Absinken, gedeckelte Basis; Tief → hohe Basis, Überentwicklung; T850 ≥ 14 °C bremst, ≤ 4 °C fördert | je Zone: Basis (LCL 13 Uhr, Median der Regionen), Steigen (Tagesspitze, Median), Sonne/tiefe Wolken 10–16 Uhr — kein Thermikbeginn (bewusst weggelassen) | Urteil am Median der Zonen-Basen (Schwelle 2800 m): „Genau das …" / „zeigen das nicht — Basis höher/tiefer als die Lage erwarten lässt". Zahlen in Chips, Text ohne Meter |
| 7 | Sonne / Bewölkung | Hoch → Sonne, Tief → Wolken; Luftmasse legt Wolken auf eine Seite | Sonnenanteil je Zone (Balken), Wolkenart unter/über 2 km | Nord und Süd gegen Erwartung: passt / teilweise / nicht |
| 8 | Modelle | Verlässlichkeit der Lage | fünf Modelle an vier Punkten (Interlaken, Sion, Locarno, Chur): ICON-CH1/CH2 (MeteoSchweiz), ICON-D2/EU (DWD), GFS (NOAA) — Böen, Niederschlag, Bewölkung | welche Parameter einig, welche nicht, welche Modelle zusammenstehen. GFS zählt bei Wind/Wolken nicht in die Spanne (25 km, systematisch tief) |

## 4. Status-Pillen

Fix definiert in `scripts/briefing_v3_context.py` (`st_*`-Labels DE/EN,
Regeln in `_decorate_chain`). Drei Stufen: **grün** = passt / ruhig,
**blau** = Hinweis, **orange** = Abweichung / Gefahr. Die Farbe trägt nie
allein die Bedeutung — jede Pille hat ihr Wort, der Satz darunter dasselbe
ausführlich.

| Block | grün | blau | orange |
|---|---|---|---|
| Lage | Daten passen zur Lage | Daten passen teilweise | Daten widersprechen der Lage |
| Fronten | keine Front | Front schwächt ab · Rückseite | Front zieht durch |
| Föhn / Bise | kein Föhn | einzelne Böen | Föhn aktiv · Bise |
| Höhenwind | regional wie im Mittel | regional schwächer | regional stärker |
| Labilität | stabil | teils labil | Gewitter |
| Thermik / Basis | gutes Steigen (≥ 2 m/s) | mässiges Steigen (≥ 1) | schwaches Steigen |
| Sonne / Bewölkung | wie erwartet | teils anders | anders als erwartet |
| Modelle | Modelle einig | ein offener Punkt | Modelle uneinig |

Regeln:
- **Lage**: beruhigend (Druck steigt, oder Hoch) erwartet trocken & ruhig,
  unbeständig (fällt, oder Tief) erwartet Regen/Wind; Stufe 1 → teilweise,
  Gegenteil → widersprechen; Übergangslage: nur Stufe 2 → teilweise.
- **Fronten**: Signatur → zieht durch; DWD nennt Front, keine Signatur →
  schwächt ab; Ist-Durchgang der letzten 36 h (DWD-Analyse) → Rückseite.
  Ob die DWD-Prognose für den Tag eine Front nennt, kommt aus **derselben**
  Quelle wie der Satz (`passagen_*.json` über `_front_block`, Feld `dwd`) —
  nicht aus `wetterlage.fronten.durchgaenge`: deren Tageszuordnung wich ab
  und stellte „keine Front“ neben einen Satz mit Front (19.09.2026).
- **Föhn/Bise**: aktiv → orange; sonst Böe ≥ 40 km/h an einem Startplatz →
  einzelne Böen.
- **Höhenwind**: Stärkeklasse der Regionsspitze gegen Klasse des Mittels
  (schwach < 15, mässig < 30, kräftig < 50 km/h).
- **Labilität**: Modell-Gewitter → Gewitter; CAPE-Klasse in einer Zone →
  teils labil.
- **Sonne**: Nord (Alpennordhang) und Süd (Tessin) je gegen Erwartung; eine
  passt nicht → teils; keine → anders.
- **Modelle**: 0 / 1 / ≥ 2 Parameter uneinig (Böen-Spanne ≥ 20 km/h,
  Bewölkung ≥ 30 %, Regen geteilt).

Keine Pille: die Warnungen (eigene Schwere Vorsicht / Stopp). Block 1 trägt
seit 19.09.2026 eine Pille (Daten gegen Erwartung aus dem Druck).

## 5. Wer schreibt was

| Element | Quelle |
|---|---|
| Pillen, Chips, Fazit-Sätze Blöcke 2–8, Warnungen inkl. Ursache | Code |
| Block 1 Tagessatz | heute Code; vorgesehen KI (`day_lines`), Skill verlangt dieselbe Form: Einfluss → Druck → Wetterfolge, max 35 Wörter, Laienworte für Hoch/Tief, Logik-Abgleich |
| KI-Satz über einer Warnung | KI (`hazards`), optional |
| Regionen-Einschätzung | KI (Regionsanalyse, eigener Skill) |

Skill-Regeln zu Fronten: Fronten-Wörter nur, wenn `fronten.durchgaenge`
Einträge hat; Validator lässt sie dann durch (`_FRONT_PATTERNS`). Ohne
Daten kein Frontenwort — auch nicht „keine Front in Sicht".

## 6. Logik-Regeln (Code und Skill identisch)

- **Nie „unsere Prognose", nie anonyme „Prognosedaten".** Die Daten sind nicht
  von Wingcast: **jeder** Abgleich-Satz der Blöcke 1–7 nennt das Modell und
  spricht das Urteil aus („ICON-CH1/ICON-D2 bestätigt das / zeigt das nur
  teilweise / widerspricht: …"; Namen
  aus `config.SURFACE_PRIMARY_MODEL` / `PRESSURE_LEVEL_PRIMARY_MODEL` über
  `_model_words()`), die DWD-Frontenprognose heisst DWD. Die App zeigt unter
  der Kette eine Quellenzeile (`analyse.source`), das Mail nennt die Quellen
  im Footer.

- „beruhigt sich" (Druck steigt) + Schauer nehmen zu, nur im Süden →
  „beruhigt sich im Norden, im Süden Schauer am Nachmittag zunehmend";
  verbreitet → „Hochdruckeinfluss nimmt zu, kommt aber noch nicht an".
- „unbeständig" (Druck fällt) + trocken → „vorerst meist trocken".
- Front: kein „zieht durch" ohne Signatur in den eigenen Daten.
- **Druckzeile** (seit 23.09.2026): „3 Tage: stabil −1,2 hPa/d · tagsüber
  +0,4 hPa · Sprung +1,4 hPa in 3 h, 17–20 Uhr (Alpennordhang)". Drei Zahlen,
  drei Jobs: 3-Tage-Steigung des CH-Mittels; Tagestendenz 06–22 h als Mittel
  über die Zonen, nur wenn sie einig sind — sonst „uneinheitlich" plus das
  Muster in ein paar Wörtern („Norden steigend, Süden fallend" / „nur Tessin
  fallend"); der betragsgrösste 3-h-Sprung als Maximum über die Zonen mit
  Zonenname, hervorgehoben ab `SYNOPTIC_DRUCK_SPRUNG_HPA` (2 hPa). Alles auf
  der um den **mittleren Tagesgang** bereinigten Druckreihe
  (`data/druck_tagesgang.json`, je Zone und Monat, aus einem Jahr ICON-CH1 via
  `python scripts/druck_tagesgang.py`; einmal je Quartal nachziehen). Ohne
  Abzug misst die Tendenz die Tageszeit: über den Alpen schwankt der MSL-Druck
  täglich um 1–2 hPa, die 06→22-h-Differenz war im September um +0,7…+1,0 hPa
  verzerrt — genau die alte Schwelle, daher stand fast täglich „steigender
  Druck" neben einer fallenden 3-Tage-Zahl. Der Frontsatz nennt als Gegenbeleg
  den fehlenden **Sprung** über alle Zonen, nie die Tagesbilanz (eine Front ist
  ein Knick, keine Steigung). Die KI bekommt dasselbe `druck_tag` und darf bei
  uneinigen Zonen das Muster als Halbsatz aufgreifen, keine Zahl.
- Zwei Fronten gleichen Typs an verschiedenen Tagen sind zwei Fronten.
- Aussagen aus dem Vortageslauf gelten nur, wenn die Karte des Tages die
  Front noch innerhalb 600 km zeigt (der neueste DWD-Lauf sieht < 36 h nicht).

## 7. Datenfelder (Strukturfeld `synoptic_context.json`)

Neu seit 09/2026, alle aus `engine/synoptic_context.py`: `fronten`
(Durchgänge + `vergangen`), `frontsignatur`, `aloft_regional` (mit
`min_kmh`), `bise_boden`, `starkwind_punkte`, `thermik_zonen`,
`modell_vergleich`; Föhn-Block trägt `claim` (ΔP, Kammwind) und `lee`.
Server rechnet sie im Morgenlauf; lokal per Preview-Skript nachrechenbar.

## 8. Dieselbe Kette in der App (`/briefing`)

**Seit 19.09.2026.** Die App zeigt unter der Synoptik-Mini-Karte die Analyse-Kette
und die Warnungen Schweiz — **für jeden Prognosetag**, die Tages-Tabs
schalten um (das Mail bleibt ein Heute-Briefing). Gleiche Quelle, gleiches
Ergebnis: `scripts/briefing_v3_context.build_chain_all_days(wetterlage, dates)`
ruft je Tag dieselben Funktionen wie `build_v3_context` (`_chain`,
`_ch_warnings`); Fronten je Tag aus dem DWD-Archiv wie die Karte
(`engine.fronten.select_for_timestep`, 12:00). Für „heute" sind Pillen und
Sätze in Mail und App 1:1 identisch.

| Ebene | Ort |
|---|---|
| Payload | `/api/briefing` → `analyse.by_date[YYYY-MM-DD].{chain, warnings, fronts_kind}` + `analyse.labels` (`web.py _briefing_analyse`, bei Fehler `null`, die Spots kommen trotzdem) |
| Cache | ETag zusätzlich über die Ordner-mtimes des DWD-Fronten-Archivs und der Prognose-Durchgänge sowie den Prozessstart (sonst liefert der Browser nach einem Deploy per 304 die alte Payload-Form bis zum nächsten Datenlauf) |
| Darstellung | `static/js/briefing.js renderChain`: Akkordeon-Liste, eine Zeile je Block 1–8 plus Warnungen — Nummer, Titel, Status-Pille rechts, Chevron; Inhalt klappt unter der Zeile auf (ARIA-Disclosure, Tastatur-Fokus bleibt auf der Zeile). Lage trägt statt Pille Druck · Regime · Tendenz. Offene Blöcke bleiben über den Tageswechsel (`localStorage wingcast.briefing.chainOpen2`, Erstbesuch: **alle** offen) |
| Kopfzeile | „Stand" = Zeitpunkt des Morgenlaufs (`wetterlage.generated_at`, sonst mtime des Analyse-Caches) — **nie** die Abrufzeit |
| Tages-Tabs | tragen die Kachel des Wochenstreifens (`tile`: Einstufung Safe/Caution/Not safe über **alle** bewerteten Regionen per `_day_verdict` — ohne die Note, die ist ohne Regionsliste daneben nicht einzuordnen —, Bodendruck, Höhenwind-Pfeil · Sektor · Stärke) plus die Zahl fliegbarer Spots |
| Nicht übernommen | Kartenbild, „Deine Regionen", Betreff, Hero — die App hat Mini-Karte und Regionsfilter; sie kennt keine Abo-Regionen |
| Entfallen | der ganze frühere Wetterlage-Block (KI-Kurztext der Woche + KI-Zonentexte hinter „Detail"): zwei Aussagen zum selben Tag konnten sich widersprechen, und die Lage des Tages steht als Block 1 in der Kette |

Tag ohne Synoptik-Daten (älterer Cache) → ehrliche Leerzeile, kein geratener
Block. Folgetage sind beim Fronten-Block unschärfer als heute: „Rückseite"
(Ist-Durchgang der letzten 36 h) gibt es nur für heute; für Tag +1/+2 greift
die Regel nicht, das Ergebnis ist korrekt, aber nicht gleich belastbar.

## 9. Vorschau bauen, Grenzen, offene Schritte

```
PORT=5001 python main.py
python scripts/preview_briefing_email.py --lokal-karte http://localhost:5001
```
`--lokal-karte` fotografiert die Karte aus der lokalen App (playwright-core
gegen das installierte Chrome); ohne den Schalter per SSH vom Server.
Vorschau nutzt den Datenstand des Morgenlaufs (05:00 Wetter, 06:43 Synoptik,
DWD-Lauf 00 UTC).

- Nur Prognosedaten. Für „schon durchgezogen" die DWD-Analyse, sonst nichts
  Gemessenes.
- Schwellen (4 hPa, 40 km/h, 1.2 hPa/3 h, 40°, CAPE-Klassen, 600 km) sind
  gesetzt, nicht an Messungen validiert — `validation/fronten/` hat 59
  Ist-Durchgänge für eine spätere Prüfung der Frontsignatur.
- Mail-Versand: Karte per `scripts/synoptik_snapshot.js` gegen
  `WINGCAST_BRIEFING_MAP_URL` (Default `http://127.0.0.1:$PORT`), ein
  Screenshot je Lauf für alle Subscriber; ohne node/Playwright geht das Mail
  ohne Bild raus. Betreff = `v3_subject` („Today and Sat safe").
- Offen: `skills/i18n_sync.json` nach Skill-Änderung auf dem Server
  aktualisieren (nicht auf Windows); Schwellen gegen Messungen validieren.

Verwandt: `docs/WETTERLAGE.md`, `docs/GEWITTER.md`, `docs/RATING_FARBKONZEPT.md`,
`docs/pläne/PLAN_briefing_mail_v3.md`.

## Oeffnungs- und Klick-Messung (seit 22.09.2026)

`mail_tracking.py`. Jedes Briefing-Mail traegt ein 1x1-Pixel (`/t/o/<id>/<sig>.gif`)
und leitet die Links Konto/Dashboard/Spots ueber `/t/c/<id>/<sig>?u=…` (nur eigene
Domains als Ziel). Signatur = HMAC ueber die Subscriber-ID, kein DB-Token.

Gespeichert wird je Abonnent `last_open_at`, `last_open_client`, `last_open_valid`,
`last_valid_open_at`, `last_click_at` plus jedes Ereignis in `email_events`.
**`last_open_valid=0` = Apple Mail** (laedt Bilder ueber den Privacy-Proxy vor dem
Lesen, belegt keine Oeffnung). Outlook blockiert Bilder standardmaessig — kommt kein
Aufruf, fehlt der Wert schlicht. Ein Klick belegt die Oeffnung immer.

PostHog bekommt server-seitig (ohne Browser-Consent, kein Browser-Tracking) die
Events `briefing_sent`, `briefing_opened`, `briefing_clicked` und je Person die
Eigenschaften `briefing_last_opened_at`, `briefing_last_open_valid`,
`briefing_last_open_client`, `briefing_last_valid_open_at`, `briefing_last_clicked_at`,
`subscriber_status`, `regions_count`, … Einmal-Abgleich aller Konten:
`python scripts/posthog_sync_subscribers.py`. Keine IPs, keine User-Agents gespeichert.
