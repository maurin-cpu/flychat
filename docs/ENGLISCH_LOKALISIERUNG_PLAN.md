# Plan: Englische Version für Forum-Demo (wirkt fertig)

> **Erstellt:** 2026-06-04 · **Aktualisiert:** 2026-06-04
> **Zweck:** Die App englischsprachigen Forum-Testern geben. Produktion bleibt vorerst deutsch — das Englische dient dem Einholen von Feedback.
> **Leitsatz: „Es muss auf dem Tester-Pfad aussehen, als wäre es fertig."** Kein deutscher Rest dort, wo ein Tester hinschaut. Natürliche englische Prosa. Englische Datums-/Zeitformate.
> **Entscheidung:** Harter Wechsel (kein Sprach-Selektor). **Tester-sichtbarer Pfad: voll & poliert. Admin-UI: bleibt deutsch (kein Tester sieht sie → Plan 4 entfällt).**
> **API-/Token-Kosten:** ~0 $ — der LLM-Output kostet auf Englisch gleich viel wie auf Deutsch.
> **Gesamtaufwand:** ~5.5–7.5 Entwicklertage (Admin gestrichen, dafür Prosa-Qualität + Locale + Leak-Hunt voll drin).

---

## Scope-Filter: „Sieht der Tester das?"

Maßstab ist **nicht** Vollständigkeit über die ganze App, sondern Vollständigkeit über den **Tester-Pfad** — und dort kompromisslos fertig:

**IN (muss perfekt englisch sein):** Landing-Page → Region-/Spot-Briefing → **Analyse-Output** → **Chat** → ggf. Registrierung/Login → Account-Basics. Plus alles Sichtbare drumherum: Nav, Footer, Fehlermeldungen, Chart-Labels, Datums-/Zeitformate.

**OUT (bleibt deutsch):** Admin-UI (`templates/admin/*`, `static/js/admin-*.js`, Config-Schema-Labels), interne Tools, Accuracy-Mail (falls Tester sie nie auslösen), Dev-Kommentare/Logs.

**Härter als beim Quick-Test:** weil es „fertig" wirken soll, sind **Locale (Plan 5)**, **Prosa-Qualität (Plan 6)** und ein **systematischer Leak-Hunt** jetzt Pflicht, nicht optional.

---

## Leitprinzip (gilt über alle Teilpläne)

Jeder deutsche String fällt in **genau eine** von drei Klassen:

| Klasse | Beispiel | Aktion |
|---|---|---|
| **A — User-facing** | Button „Anmelden", E-Mail-Betreff, Fehlermeldung im Browser, Chart-Achsenlabel | **Übersetzen** |
| **B — LLM-intern** | Kontext-Block den das LLM liest (`_build_weather_context`), Skill-Prompts, Tag-Erklärungen | **Bleibt deutsch** — der LLM-Toggle (Plan 1) erzeugt englischen Output daraus |
| **C — Dev-intern** | Code-Kommentare, Docstrings, Log-Messages, Variablennamen | **Bleibt deutsch** — sieht kein User |

**Konsequenz:** Die scheinbar riesigen Python-Zahlen (`weather_context.py` 226, `analyzers.py` 186) sind fast komplett Klasse B + C. Der echte Python-Übersetzungs-Umfang ist klein und liegt v. a. in `web.py`, `email_service.py` und den Status-/Tag-Generatoren.

**Definition of Done (gesamt):** Ein frisch geladener User sieht nirgends mehr Deutsch — Web-UI, Chat, Analysen, E-Mails, Admin. `<html lang="en">`. Datums-/Zeit-/Zahlenformate englisch.

---

## Plan 0 — Grundlagen & Inventar (½ Tag)

**Ziel:** Fundament legen, bevor Strings angefasst werden.

1. `templates/base.html`: `<html lang="de">` → `lang="en"`.
2. **Vollständiges String-Inventar** erstellen: pro Datei alle Klasse-A-Strings auflisten (Grep + manuelle Sichtung), in `docs/LOC_INVENTORY.md` festhalten. Macht die Tagesschätzung exakt.
3. **Locale-Audit:** alle Stellen finden, die Datum/Zeit/Zahl deutsch formatieren — Wochentage, Monatsnamen, „Uhr", „13h", Dezimal-Komma. Kandidaten: `static/js/briefing.js`, `static/js/meteogram.js`, `email_service.py`, `web.py`. Liste in dasselbe Inventar.

**Done:** `lang="en"` gesetzt, Inventar-Datei existiert mit Datei→String-Mapping.

---

## Plan 1 — LLM-Kern: Analysen + Chat (½ Tag, ~0 $) — ✅ ERLEDIGT 2026-06-04

> **Status:** Alle Output-Sprach-Anker auf Englisch geflippt (Skill-Bodies bleiben deutsch). Verifiziert: alle 6 zusammengebauten Prompts tragen den EN-Befehl, kein „Sprache: Deutsch"-Rest. Few-Shot-Block prüft = nur numerisch, kein deutscher Prosa-Leak. **Offen: echter LLM-Smoke-Test** (kostet ~$0.50, braucht Keys+Wetterdaten) zur Sichtprüfung des realen englischen Outputs.
>
> Geänderte Dateien: `01_core_principles.md` (Punkt 0 + Anti-Beispiele + Begriffs-Regel), `system_chat.md` (Punkt 7 + Z.163), `synoptic_overview.md`, `email_week_lead.md`, `templates/base.html` (`lang="en"` + og:title/description).


**Ziel:** Der eigentliche Produkt-Output (Spot-/Region-Analysen + Chat) erscheint englisch. **Skills bleiben deutsch.**

1. `skills/shared/01_global/01_core_principles.md`, **Punkt 0** umschreiben:
   „Sprache: **Englisch**. Alle Prosa-Felder auf Englisch. JSON-Keys und Enum-Werte (`safe`, `conditional`, `FOEHN`, …) bleiben unverändert."
   (Kein Config-Toggle nötig — harter Wechsel.)
2. `skills/system_chat.md`: Sprach-Anweisung auf Englisch umstellen.
3. `skills/email_week_lead.md` + alle Skills, die user-facing Prosa erzeugen, auf englische Output-Sprache prüfen.
4. **Smoke-Test:** `python cost_testing/analyze_once.py` für ein paar Spots → Output-JSON sichten: ist die Prosa englisch, sind Enums unverändert?

**Risiko:** niedrig. **Done:** Analyse-JSON + Chat-Antworten kommen englisch, Enums/Keys unverändert, kein Sprachmix.

---

## Plan 2 — E-Mails (½–1 Tag)

**Ziel:** Alle versendeten Mails englisch.

**Dateien:** `templates/email/{confirm,login,welcome,briefing,accuracy}.{html,txt}` (10 Dateien) + Betreffzeilen/Strings in `email_service.py`.

1. Die 10 Template-Dateien übersetzen (Klasse A).
2. `email_service.py`: Betreffzeilen, ggf. `_build_week_lead_input` / `_build_region_matrix`-Labels übersetzen.
3. Datums-/Wochentag-Formatierung in den Mails auf Englisch (siehe Plan 5).
4. **Verifikation:** `python scripts/preview_briefing_email.py` → Rendering prüfen.

**Done:** Preview aller 5 Mail-Typen zeigt sauberes Englisch inkl. Datumsformat.

---

## Plan 3 — Public Web-UI: Templates + JS (~2.5–4 Tage)

**Ziel:** Die öffentliche Oberfläche komplett englisch. Größter Brocken.

### 3a — Public-Templates (~1–1.5 Tage)
**Reihenfolge nach String-Dichte:**
`regionen.html` (40) · `index.html` (39) · `account.html` (38) · `base.html` (33, Nav/Footer) · `subscribe.html` (11) · `briefing.html` (10) · `login_confirm.html` (5) · `subscribe_status.html` · `login.html`.

### 3b — Public-JS (~1.5–2.5 Tage)
**Reihenfolge nach Dichte:**
`briefing.js` (~176) · `region-map.js` (~102) · `meteogram.js` (~77) · `analysis-view.js` (~57) · `chat.js` (~49) · `chat-charts.js` (~42) · `map.js` (~35) · `rating-info.js` (~24) · `foehn_diagram.js` (~13) · `subscribe.js` · `feedback.js` · `shared-glyph.js` · `precip-refpoints-layer.js`.

**Achtung in JS:** Chart-Achsen, Tooltips, Wochentags-/Stunden-Labels, Status-Texte. Locale-Formatierung NICHT vergessen (Plan 5).

**Done:** Klick-Durchlauf Startseite → Region → Spot-Briefing → Chat → Account zeigt nirgends Deutsch.

---

## Plan 4 — Admin-UI ~~(~1–1.5 Tage)~~ — **GESTRICHEN für Forum-Demo**

Tester sehen die Admin-UI nicht → bleibt deutsch. Bei späterem Produktiv-Rollout nachholen:
`templates/admin/*.html`, `static/js/admin-*.js`, `config_overrides.py` (Config-Schema-Labels).

---

## Plan 5 — Python User-facing Strings + Locale/Datum (~1–2 Tage)

**Ziel:** Die server-generierten Klasse-A-Strings + alle Datums-/Zeit-/Zahlformate.

1. **`web.py` (180 Treffer, aber nur Teil A):** Flash-/Fehlermeldungen, HTTP-Antwort-Texte, OG-Tags (`_build_briefing_og`). Klasse B/C (Kommentare, Logs) **überspringen**.
2. **Status-/Tag-Generatoren:** prüfen, ob `engine/decision_engine.py::build_topic_tags` / `build_region_topic_tags` deutsche Strings erzeugen, die **ohne** LLM in die UI gelangen → dann übersetzen. (Falls sie nur ins LLM-Kontext gehen = Klasse B, bleibt.)
3. **Locale-Layer:** einen zentralen Datums-/Zeit-Formatter einführen (Wochentage, Monate, „Uhr"→„:00"/AM-PM, Dezimal-Punkt). Verteilte deutsche Formatierungen darauf umstellen — in JS und Python. **Eine Quelle statt verstreuter Strings.**
   - **Konkret gefunden (2026-06-04):** `engine/_common.py:343` — Funktion gibt **deutsche Wochentagsnamen** zurück (Montag…) → englische Namen. Erreicht Briefing/Mail-Output.
   - **`routing.py:77/101`** — Geocoding `accept-language`-Header → auf `en` für englische Ortsnamen.
4. `chat_engine.py` / `engine/chat_orchestrator.py`: user-facing Fehlertexte/Fallbacks (z. B. „Ich konnte keine Daten finden") übersetzen — NICHT die LLM-Kontext-Bauer.

**Risiko:** mittel — die A/B-Abgrenzung pro String muss sauber getroffen werden, sonst übersetzt man LLM-Kontext kaputt. **Done:** keine deutschen Texte in HTTP-Antworten/Mails; Datumsformate durchgängig englisch.

---

## Plan 6 — LLM-Prosa-Qualität + Gesamt-Abnahme (~½–1 Tag)

**Ziel:** Englischer Output klingt nach echter Fliegersprache, nicht nach Übersetzungs-Maschine; Gesamt-QA.

1. **Prosa-Anker spiegeln:** in `skills/shared/04_flyability/03_prose_style.md` die deutschen Beispiel-Wordings („starker Tag", „XC-Tag", Rating↔Wort-Konsistenz) englische Pendants ergänzen, damit Ton/Konsistenz stimmen. Analog `_flight_subratings_*.md`.
2. **Regressions-Lauf:** `python cost_testing/analyze_once.py` + Stichproben-Review der englischen Prosa über mehrere Rating-Stufen.
3. **End-to-End-Abnahme:** kompletter User-Flow auf einem frischen Browser-Profil — Registrierung-Mail → Login → Web-UI → Chat → Briefing-Mail. Checkliste: irgendwo noch Deutsch?

**Done:** Abnahme-Checkliste komplett grün.

---

## Reihenfolge & Quick Wins

```
Plan 0  ─► Plan 1 (sofort sichtbarer Kern, ~0 Aufwand)
            │
            ├─► Plan 2  (Onboarding-Mails — nur falls Tester sich registrieren)
            ├─► Plan 3  (Public-UI)   ← größter Brocken
            └─► Plan 5  (Python user-facing + Locale)
                  │
                  └─► Plan 6 (Prosa-Qualität + LEAK-HUNT auf Tester-Pfad)

Plan 4 (Admin)  ─►  gestrichen für Forum-Demo
```

**Empfohlener Start:** Plan 1 zuerst — flippt mit minimalem Aufwand den Produkt-Kern (Analysen + Chat) auf Englisch und macht das Ergebnis sofort beurteilbar, bevor die zeitintensive UI-Übersetzung beginnt.

**Offen:** Müssen Tester sich registrieren? → entscheidet, ob Plan 2 (Onboarding-Mails) im Scope ist. Eine deutsche Signup-Mail würde „fertig" sofort widerlegen.

## Risiken / Fallen

- **A/B-Verwechslung (größtes Risiko):** LLM-Kontext-Strings (Klasse B) versehentlich übersetzen → bricht die Analyse-Qualität. Im Zweifel: erzeugt der String *Input fürs LLM* oder *Output für den User*?
- **Locale-Streuung:** Datum/Zeit/Zahl sind über viele Dateien verteilt → zentral lösen (Plan 5.3), sonst bleiben überall „Uhr"/Komma-Reste.
- **Kein Selektor = Rückweg teuer:** harter Wechsel heißt, Deutsch ist weg. Falls später doch DE/EN nötig → echtes i18n nachrüsten (separater, größerer Plan).
- **Prosa-Qualität:** ohne Plan 6 klingt englischer Output mechanisch — die kalibrierten Anker sind deutsch.
```
