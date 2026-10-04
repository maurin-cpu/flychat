# PLAN: Öffentliches Schweiz-Briefing auf wingcast.ch

**Stand:** 2026-10-04 · **Status:** umgesetzt (flychat + Webseite), **Deploy offen**

## 0. Stand der Umsetzung (04.10.)

Entscheid Maurin 04.10.: Deutsch und Englisch, nicht nur Englisch. Gebaut:

- `i18n.lang_override()` / `get_server_lang()`: Sprache thread-lokal übersteuern. Nötig, weil der Scheduler im Webprozess läuft und `config.LANG` global ist.
- `engine/synoptic_llm.refresh_synoptic_overview_lang()`: zweiter LLM-Lauf nur für den Text-Teil, Strukturfeld bleibt (sprachneutral), Cache `data/synoptic_context.<lang>.json`.
- `engine/public_briefing.py`: Whitelist über `build_chain_all_days()`, je Sprache `data/public_briefing/briefing.<lang>.json` (~16 KB statt 12 MB).
- `scheduler.py`: nach dem Hauptlauf je weitere Sprache aus `PUBLIC_BRIEFING_LANGS` den Lauf, nach `build_briefing_data()` die JSON. Eigenes try/except, blockiert nie den Mailversand.
- `web.py`: `GET /api/public/briefing?lang=de|en` (200 / 503 fehlend oder älter 18 h / 404 Sprache), `Cache-Control: public, max-age=300`. **`/api/briefing/generate` jetzt `@_require_admin`.**
- `config.py`: `PUBLIC_BRIEFING_LANGS` (env `WINGCAST_PUBLIC_BRIEFING_LANGS`, Default `de,en`), `PUBLIC_BRIEFING_DAYS` (3), `PUBLIC_BRIEFING_MAX_AGE_H` (18), `PUBLIC_BRIEFING_DIR`.
- Tests: `tests/test_public_briefing.py` (10), dazu Synoptik- und Warnungs-Tests grün (300).
- Webseite (`gleitcast_webpage`): `/flugwetter-schweiz` (de) + `/en/flugwetter-schweiz`, Block auf `/` und `/en`, hreflang, Sitemap täglich, FR/IT 404.

**Nicht gebaut (bewusst):** Revalidate-Ping (Seite ist spätestens 07:00 aktuell, ISR 1 h), Regionszeilen, FR/IT.

**Deploy (Maurin):** `./deploy.sh` auf Hetzner. Keine neue Env nötig, Defaults reichen. Danach prüfen: `curl https://app.wingcast.ch/api/public/briefing?lang=de` liefert erst nach dem nächsten 06:00-Lauf 200 (vorher 503 „missing"); die Webseite zeigt bis dahin den festen Teil. Kosten: ein zusätzlicher LLM-Call pro Tag für Deutsch.
**Ersetzt:** `PLAN_wetterlage_webseite.md` (25.07.). Dessen Architektur bleibt (Pull per ISR + Revalidate-Ping), der Inhalt nicht: der `llm_overview`-Block, auf dem er aufbaute, ist seit 19.09. aus der App entfernt (`docs/BRIEFING.md` §8).

## 1. Warum

Search Console 03.10.: `thermikprognose` 44 Impressionen in zwei Wochen, 0 Klicks, Position 9,4. `flugwetter schweiz` Position 17. Die Startseite beschreibt das Produkt, zeigt aber keine Prognose. Wer „Thermikprognose" sucht, will eine sehen.

Eine Seite mit dem Briefing von heute bringt:
1. **Google:** Inhalt passt zur Suchabsicht, Besucher bleiben, täglich frischer Text. Erwartung: Platz 9 → 5–6 über Wochen. Platz 1–3 braucht weiterhin Backlinks.
2. **Teilen:** ein Link, der jeden Tag neu geteilt werden kann (Club-Chats). Der stärkste bisherige Kanal war ein geteilter Link.
3. **KI-Chats:** ChatGPT/Perplexity zitieren aktuelle, konkrete Seiten. Die Produktseite zitieren sie nicht.

## 2. Was es schon gibt (nicht neu bauen)

| Baustein | Ort |
|---|---|
| Analyse-Kette + Warnungen Schweiz für **jeden Tag**, ohne Abo-Regionen, Tageskachel über alle 29 Regionen | `scripts/briefing_v3_context.py:3458` `build_chain_all_days()` |
| Warnungen Schweiz (Schalter vom Code, ein KI-Satz je Gefahr, Code-Satz mit Zahl) | `scripts/briefing_v3_context.py:3350` `_ch_warnings()` |
| Tageslauf 06:00, Synoptik-Refresh, `build_briefing_data()` | `scheduler.py:210` `_send_briefings_once`, L251–285 |
| Validator, Korrekturschleife, Admin-Alarm | `engine/synoptic_llm.py:443` `_validate`, L799 `_notify_admin` |
| App rendert dieselbe Kette clientseitig | `static/js/briefing.js` `renderChain` |

Der öffentliche Inhalt ist also **1:1 das, was die App heute ohne Login zeigt**, nur serverseitig gerendert.

## 3. Entscheide (Vorschlag)

- **Inhalt:** Lage, Fronten, Föhn/Bise, Höhenwind, Thermik, Warnungen Schweiz, Tageskachel je Tag. **Keine Regionszeilen** in Stufe 1 (gibt es nur pro Abonnent, `_region_cards` L1634). Stufe 2 prüfen.
- **3 Tage** öffentlich (wie alter Plan). Kein Tages-Archiv (dünne Seiten).
- **Nur Deutsch** in Stufe 1. Der Server erzeugt genau eine Sprache (`config.LANG`), der Validator kennt DE/EN. FR ist Stufe 2, eigener Plan (ein Drittel der Besucher spricht Französisch).
- **Zwei Orte, eine Quelle:**
  - `wingcast.ch/flugwetter-schweiz`: ganzes Briefing, Ziel `flugwetter schweiz`.
  - Startseite DE: kurzer Block „Thermik heute" (Kachel + Warnungen + Lage-Satz von heute), Link auf die Seite. Stärkt die Seite, die für `thermikprognose` schon rankt.
- **Zwei Wochen intern** (Seite live, aber `noindex` und nicht verlinkt), Texte täglich gegenlesen. Dann öffentlich.

## 4. Umsetzung

### Schritt 1: flychat, öffentlicher Endpunkt

- `web.py`, neben `/api/briefing` (L2704): `GET /api/public/briefing`.
  - Ruft `build_chain_all_days(wetterlage, dates[:PUBLIC_BRIEFING_DAYS], days)`, wie `/api/briefing` L2765–2773.
  - Gibt nur eine **schmale Whitelist** aus: je Tag `tile` (status, rating, pressure_hpa, wind_*), `warnings`, und aus `chain` die Textfelder (`lage.label`, `situation`, `day_hint`, `foehn.fazit`, `wind.regional`, `thermik.fazit`, Front-`lines`). Keine Rohdaten, keine `attempts`/`unresolved`, kein Druckraster.
  - Kopf: `version`, `lang`, `generated_at`, `age_hours`, `source`.
  - `503 {"available": false}` wenn Cache fehlt oder älter als 18 h.
  - `Cache-Control: public, max-age=300, s-maxage=300`.
- `config.py`: `PUBLIC_BRIEFING_DAYS` (3), `WINGCAST_REVALIDATE_URL`, `WINGCAST_REVALIDATE_SECRET`.
- `scheduler.py` nach dem Refresh (L269): `_ping_website_revalidate()`, eigenes try/except, `timeout=10`, blockiert nie den Mailversand.
- Tests: `tests/test_public_briefing.py` (Whitelist, 503-Fälle, keine internen Felder im JSON).

**Nebenbefunde, im selben Zug beheben:**
- `/api/briefing/generate` (L2776) hat **kein** `@_require_admin`, löst aber einen LLM-Call aus. Jeder kann Kosten erzeugen. Admin-Schutz wie beim Grid-Refresh (L2941).
- `/api/briefing` gibt den ganzen `synoptic_context.json` mit Interna aus. Prüfen, ob die App alles braucht.

### Schritt 2: Webseite

- `lib/briefing.ts`: Fetch mit `next: { revalidate: 3600, tags: ["briefing"] }`, zod-Validierung, `null` bei Fehler, 503, `age_hours > 18` oder falscher Sprache.
- `app/api/revalidate/route.ts`: Secret per timing-sicherem Vergleich, `revalidateTag("briefing")`. `/api` ist schon aus Middleware und robots ausgenommen.
- `components/sections/BriefingToday.tsx` (Startseite, zwischen `Hero` und `Problem`, `id="briefing"`). Bei `null` wird der Block nicht gezeigt, die Seite bleibt wie heute.
- `app/[locale]/flugwetter-schweiz/page.tsx`: Gerüst wie `wetterkunde/[slug]/page.tsx` (L126–161, `prose-wingcast`). H1 „Flugwetter Schweiz heute", sichtbarer Stand mit Uhrzeit, Briefing je Tag, kurzer fester Erklärteil, FAQ, CTA zur App. Nur `de` in `generateStaticParams`. Bei `null`: fester Erklärteil + Hinweis, keine leere Seite.
- `generateMetadata`: Title „Flugwetter Schweiz heute: Thermik und Wind für Gleitschirm", `dateModified` aus `generated_at`.
- `app/sitemap.ts`: Eintrag `changeFrequency: "daily"`, lastmod aus `generated_at` (Typ L39 erweitern). `public/llms.txt`: Zeile unter „Hauptseiten". Footer `productLinks`, Navbar erst nach der Testphase.
- `.env.example`: `WINGCAST_API_URL`, `REVALIDATE_SECRET`.

### Schritt 3: Marketing-Repo

`1-planung/seo/keywords.md`, `seo-architektur.md`, `redaktionsplan.md` nachführen. Text der festen Teile zuerst als Draft unter `2-ausfuehrung/webseite/drafts/` (Regel: Webseiten-Content gegen Keywords abgleichen, keine Gedankenstriche, Spotzahl nicht als Argument).

## 5. Was nur Maurin kann

1. Secret erzeugen (`openssl rand -hex 32`), eintragen in Hetzner `/home/deploy/flychat/.env` und Vercel (`REVALIDATE_SECRET`, `WINGCAST_API_URL=https://app.wingcast.ch`).
2. `./deploy.sh` auf Hetzner. Achtung: `deploy.sh` führt **keine Tests** aus (anders als im alten Plan angenommen). Tests vorher lokal.
3. Nach zwei Wochen: Freigabe für `index` und Verlinkung.

## 6. Prüfen

- flychat lokal: `pytest tests/test_public_briefing.py`; `curl localhost:…/api/public/briefing` zeigt 3 Tage, keine internen Felder.
- Webseite lokal mit `WINGCAST_API_URL` auf Produktion: `npm run build`, Seite und Startseiten-Block rendern serverseitig (Text steht im HTML, nicht erst nach JS).
- Ausfall erzwingen: falsche API-URL → Startseite unverändert, Briefing-Seite zeigt den festen Teil.
- Revalidate: `curl -X POST` mit falschem Secret → 401, mit richtigem → neue Fassung innerhalb einer Minute.
- Nach Livegang: Rich-Results-Test, URL-Prüfung in der GSC, nach 4–6 Wochen `thermikprognose` und `flugwetter schweiz` messen.

## 7. Risiko

Ein plausibler, aber falscher KI-Satz steht öffentlich, zum Beispiel „sicher" an einem Gewittertag. Gegenmittel: Validator und Admin-Alarm bestehen, sichtbarer Stand, 18-h-Grenze, „Entscheidungshilfe, du entscheidest" auf der Seite, zwei Wochen interner Lauf vor dem Index.
