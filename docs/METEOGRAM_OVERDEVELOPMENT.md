# Überentwicklungsgefahr (CAPE) im Meteogramm

**Status:** ✅ **Umgesetzt & live** — der Code aus Phase 1 ist vollständig in
`static/js/meteogram.js` (`hasOverdev`/`capeStrong`, Schwellen 800/1500, hohler vs.
gefüllter Blitz in Mobile- und Desktop-Zweig). Phase 3 (redundantes Warnband) ist
erledigt — Band entfernt, Symbol ist einzige CAPE-Quelle. Offen ist nur noch der
**nutzer-seitige** Punkt ohne Code-Arbeit: visuelle Abnahme im Browser (Phase 2).
Weil das Feature umgesetzt ist, liegt dieses Dokument in `docs/` (Doku) und nicht in `docs/pläne/`.
**Erstellt:** 2026-05-29
**Betroffene Datei:** `static/js/meteogram.js`

---

## Ziel in einem Satz

Der Pilot soll im Meteogramm **stundengenau** sehen, *wann* Überentwicklungsgefahr besteht — und zwar klar unterscheidbar von einem bereits prognostizierten echten Gewitter.

## Hintergrund / Motivation

User-Beobachtung 2026-05-29: Der Analysetext sagt teilweise „Überentwicklungsgefahr", aber im Meteogramm ist **kein** Symbol zu erkennen.

**Befund nach Code-Check:** Es gab zwei getrennte, unterschiedlich behandelte Signale:

| Signal | Quelle | Bedeutung | Darstellung (vorher) |
|---|---|---|---|
| **Gewitter** | `weather_code` 95/96/99 | Modell prognostiziert konkretes Gewitter | gefüllter Blitz in der Wetterzeile über dem Meteogramm |
| **Überentwicklung (CAPE)** | `cape > 800 J/kg` | Energie/Potenzial vorhanden, noch kein Gewitter | **nur** ein wegklappbares Warnband unten — **kein Zeilen-Symbol** |

**Zwei Ursachen, warum der User nichts sah:**
1. Die Wetterzeile (`precipRowY`) rendert eine Stunde nur, wenn `hasPrecip || hasStorm` — CAPE wurde dort gar nicht berücksichtigt (früher Early-Return).
2. Das CAPE-Warnband steht als **letzter** Eintrag in `WARN_TYPES` (`meteogram.js:612`) und fällt damit bei `MAX_WARN_ROWS = 4` als Erstes in die „+N weitere"-Overflow-Pille — an windigen Labilitätstagen also fast immer unsichtbar.

→ „Überentwicklung" war im Text präsent, aber im wichtigsten visuellen Element praktisch unsichtbar.

## Schwellen (identisch zur Engine, `config.py`)

- `CAPE_WARN_JKG = 800` → Überentwicklung **möglich**
- `CAPE_DANGER_JKG = 1500` → Überentwicklung **hoch**

Konsistenz-Prinzip: Frontend nutzt **dieselben** Schwellen wie `engine/weather_context.py` (CAPE-WARN/CAPE-DANGER) — eine Wahrheit, kein Auseinanderlaufen von Text und Grafik.

## Entscheidungen (vom User bestätigt)

1. **Darstellung „wie im Meteogramm"** — eigenes Symbol pro Stunde in der Wetterzeile, nicht nur das Band.
2. **Klar unterscheidbar vom echten Gewitter** — gewählt: **hohler Blitz** (nur Umriss) vs. **gefüllter Blitz** (echtes Gewitter). Intuitiv: „baut sich auf" vs. „ist da".
3. **Zwei Intensitätsstufen** — `> 800` (hohl, heller Hintergrund) und `> 1500` (leicht gefüllt, kräftigerer Hintergrund).
4. **Echtes Gewitter hat Vorrang** — bei `hasStorm` wird der gefüllte Blitz gezeigt, kein Doppelsymbol.
5. **Kein „CAPE"-Wort gegenüber dem Piloten** — Tooltip spricht von „Überentwicklungsgefahr (möglich/hoch)", der Zahlenwert steht nur als Detail dahinter.

---

## Phasen

### Phase 1 — Implementierung (ERLEDIGT)

- [x] In der Wetterzeilen-Schleife `cape` aus `wx.thermik.cape` lesen
- [x] `hasOverdev = !hasStorm && cape > 800`, `capeStrong = cape > 1500`
- [x] Early-Return erweitert: `if (!hasPrecip && !hasStorm && !hasOverdev) return;`
- [x] Hintergrund-Tint für Überentwicklung (hell bei möglich, kräftiger bei hoch)
- [x] Tooltip: „Überentwicklungsgefahr (möglich|hoch) · CAPE N J/kg" (+ mm falls auch Regen)
- [x] **Mobile-Zweig:** hohler Blitz zwischen `hasStorm` und `hasPrecip`
- [x] **Desktop-Zweig:** hohler Blitz + Cluster-Breiten-/Textfarben-Anpassung
- [x] `node --check` grün (Syntax valide)
- [x] **Commit:** noch offen — siehe Phase 3

**Render-Vorrang pro Stunde:** echtes Gewitter (gefüllter Blitz) → Überentwicklung (hohler Blitz) → Regen (Tropfen).

### Phase 2 — Visuelle Abnahme (User-Action, OFFEN)

JS ist gecached → **Hard-Reload** (Strg+Shift+R) nötig.

- [ ] Tag mit hohem CAPE (> 1500) öffnen → leicht gefüllter hohler Blitz, kräftiger Hintergrund
- [ ] Tag mit moderatem CAPE (800–1500) ohne Regen/Gewitter → hohler Blitz sichtbar
- [ ] Tag mit echtem Gewitter (95/96/99) → weiterhin **gefüllter** Blitz, **kein** hohler daneben
- [ ] CAPE **und** Regen gleichzeitig → hohler Blitz + mm-Text (Desktop)
- [ ] Mobile-Ansicht gegenchecken (Icon zentriert, lesbar bei kleiner `PRECIP_ROW_H`)
- [ ] Tooltip-Text prüfen (Hover Desktop / Touch Mobile)
- [ ] Gegencheck: Stunde, in der der Analysetext „Überentwicklung" sagt → jetzt auch Symbol vorhanden

### Phase 3 — Folge-Entscheidung: redundantes Warnband (ERLEDIGT)

**Entscheidung A umgesetzt (2026-05-31):** Das redundante Band „Überentwicklung
(CAPE)" wurde aus `WARN_TYPES` entfernt. Das stündliche Symbol (hohler Blitz) ist
jetzt die einzige, klare CAPE-Quelle — kein Doppelsignal, nichts versteckt sich
mehr in der „+N weitere"-Overflow-Pille. Das verwaiste `f.cape = true`-Flag wurde
mitentfernt. Tooltip-Detail-Panel (CAPE-Zahl) bleibt unberührt.

---

## Risiken und Gegenmaßnahmen

| Risiko | Mitigation |
|---|---|
| Viele hohle Blitze an stark labilen Tagen (visuelles Rauschen) | Spiegelt bewusst die tatsächliche Lage — verhält sich wie Regen/Gewitter, die ebenfalls jede betroffene Stunde markieren |
| Hohler vs. gefüllter Blitz auf kleinem Mobile-Icon schwer unterscheidbar | Stroke-Width bewusst dicker (`1.6/scale`); in Phase 2 auf echtem Gerät prüfen, ggf. Farbton stärker trennen |
| `wx.thermik.cape` fehlt in manchen Datensätzen | Null-Guard `cape != null ? ... : 0` → kein Symbol statt Fehler |
| Frontend-Schwelle läuft Engine-Schwelle davon | Beide aus `config.py`-Logik (800/1500) abgeleitet; bei Änderung **beide** Stellen anpassen — als Risiko dokumentiert |
| Redundanz Symbol + Band verwirrt | Phase-3-Entscheidung adressiert genau das |

## Abnahme-Kriterien

1. Stunde mit `cape > 800` (ohne Gewitter/Regen) zeigt hohlen Blitz in Wetterzeile — Desktop **und** Mobile
2. Echtes Gewitter bleibt gefüllter Blitz, kein Doppelsymbol
3. Tooltip nennt „Überentwicklungsgefahr" in Pilotensprache
4. Symbol erscheint genau in den Stunden, in denen der Analysetext Überentwicklung erwähnt
5. Phase-3-Entscheidung (Band entfernen/behalten) getroffen und committet

## Was bleibt unverändert

- Engine / Safety-Logik (rein Frontend-Darstellung; CAPE-Tags werden weiterhin in der Engine erzeugt)
- Skills / LLM-Prompts
- Gewitter-Darstellung (gefüllter Blitz) und Regen-Tropfen
- Schwellenwerte (800 / 1500) — nur sichtbar gemacht, nicht geändert

## Nicht im Scope

- Änderung der CAPE-Schwellen
- CAPE im Tooltip-Detail-Panel (existiert bereits, `meteogram.js:~1900`)
- Engine-seitige Anpassung der CAPE-WARN/DANGER-Erzeugung

## Wiederaufnahme-Hinweise

1. **Diese Datei lesen** — `docs/PLAN_meteogram_overdevelopment.md`
2. **`git status` / `git diff static/js/meteogram.js`** — Code aus Phase 1 sollte sichtbar sein
3. **`node --check static/js/meteogram.js`** — Syntax-Gegencheck
4. **Phase 2** ist die nächste offene Aufgabe (visuelle Abnahme im Browser)
5. **Phase 3** Entscheidung über das redundante Band trifft der User
