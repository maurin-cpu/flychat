# PLAN — Wetterlage-Block von flychat auf wingcast.ch

**Stand:** 2026-07-25
**Status:** beschlossen — Umsetzung freigegeben
**Betrifft:** `flychat` (Hetzner, Flask) · `gleitcast_webpage` (Vercel, Next.js 15) ·
`wingcast_marketing` (Content/Doku)

**Ziel:** Der täglich generierte Synoptik-Block (`llm_overview`) erscheint öffentlich
auf `wingcast.ch/flugwetter-schweiz` — automatisch, ohne manuellen Schritt.

**Marketing-Kontext:** Zielt auf den unbesetzten Kern-Slot `flugwetter schweiz`
(`wingcast_marketing/seo/keywords.md`, P1) und zieht `windprognose schweiz` +
Gratis-Cluster mit. Freshness, Eigendaten und Modelltransparenz zahlen auf
E-E-A-T und GEO ein.

### Getroffene Entscheide

| Frage | Entscheid |
|---|---|
| Wird gebaut? | **Ja** — trotz kleinem Volumen (~90/Monat): in einem Markt von ~15 k SHV-Piloten proportional relevant, Besucher ohne Streuverlust |
| Öffentliche Tage | **3** (App: anonym 1, eingeloggt 5) — die vollen 5 bleiben Anmelde-Anreiz |
| Sprachen | **Nur Deutsch.** Der Qualitäts-Validator (`_validate`) kennt nur DE/EN-Muster; ungeprüfte Wind-/Föhnaussagen auf FR/IT sind ein Sicherheitsrisiko |
| URL | **Eigene Seite** `/flugwetter-schweiz`, nicht unter `/funktionen` — Suchintention „Wetter sehen" ≠ Produktseite |

### Nicht Teil dieses Plans

- **Archiv-URLs** (`/flugwetter/2026-07-25`): bewusst **nicht** gebaut. 365 nahezu
  identische Seiten pro Jahr wären Thin Content, und die Helpful-Content-Bewertung
  wirkt domainweit — das Risiko steht in keinem Verhältnis zum Nutzen.
- **Synoptik-Karte** (`synoptic_grid.py`, `/synoptik`): anderes Feature, vor dem
  Launch bewusst aus der UI genommen (Commit `f80ec5e`). Hier geht es
  ausschliesslich um den **Textblock**, der produktiv in Cast und Mail läuft.
- **Föhn-Pillar** `/wetterkunde/foehn`: eigener Content-Strang, läuft parallel
  (Prio 1 der freigegebenen Content-Struktur, Score 9.1 — Video-CTA läuft
  aktuell ins Leere). Blockiert diesen Plan nicht, macht ihn aber stärker.

---

## 1. Architektur-Entscheid

**Pull (ISR) + Push (On-Demand-Revalidate).**

```
Hetzner (flychat)                          Vercel (gleitcast_webpage)
─────────────────                          ──────────────────────────
scheduler.py  06:00
  refresh_synoptic_overview()
        │
        ├──> data/synoptic_context.json
        │
        │   ①  GET /api/public/wetterlage   <────── fetch (ISR, Tag "wetterlage")
        │                                            └─ Server Component
        └──> ②  POST /api/revalidate  ──────────────> revalidateTag("wetterlage")
                (Secret im Header)                     → Seite baut sofort neu
```

- **① Pull** ist die Datenquelle. Ohne Push erneuert sich die Seite trotzdem
  (Zeit-Revalidate 1 h) — der Push macht sie nur schneller aktuell.
- **② Push** ist Komfort, kein Single Point of Failure. Fällt er aus, greift ①.
- **Kein** Git-Commit-in-Repo, **kein** Vercel-KV: die Datei auf Hetzner bleibt
  einzige Wahrheitsquelle.

### Warum nicht anders

| Verworfen | Grund |
|---|---|
| Hetzner committet JSON ins Webseiten-Repo | Täglicher Commit-Churn, voller Rebuild (1–2 min), Repo-Historie zugemüllt |
| Daten nach Vercel KV/Edge Config spiegeln | Zweite Wahrheitsquelle, zusätzlicher Dienst, zusätzliche Kosten |
| Client-seitiger Fetch im Browser | SEO-Killer — Google sieht im Zweifel eine leere Seite |
| Bestehenden `/api/synoptic/grid` mitbenutzen | Liefert das komplette Druckraster mit (schwer), interne Route ohne Stabilitätszusage |

---

## 2. Repo A — `flychat`

### 2.1 `config.py` — drei neue Werte

Nach dem Block `BASE_URL` / `MARKETING_URL` (~Zeile 999) einfügen:

```python
# Wetterlage-Block auf der Marketing-Webseite (wingcast.ch).
# REVALIDATE_URL leer => Push deaktiviert (Webseite erneuert dann nur zeitbasiert).
WEBSITE_REVALIDATE_URL    = os.environ.get("WINGCAST_REVALIDATE_URL", "").strip()
WEBSITE_REVALIDATE_SECRET = os.environ.get("WINGCAST_REVALIDATE_SECRET", "").strip()
# Wie viele Forecast-Tage die oeffentliche Webseite zeigt. Bewusst kleiner als
# FORECAST_DAYS (5, eingeloggt) — die vollen Tage bleiben ein Login-Anreiz.
PUBLIC_WETTERLAGE_DAYS    = int(os.environ.get("PUBLIC_WETTERLAGE_DAYS", "3"))
```

### 2.2 `web.py` — neuer Endpunkt

Neuer Abschnitt bei der Synoptik-Sektion (~Zeile 2560, vor `/synoptik`):

```python
@app.route("/api/public/wetterlage", methods=["GET"])
def api_public_wetterlage():
    """Oeffentlicher, schlanker Wetterlage-Block fuer wingcast.ch.

    Read-only, kein Login, keine Rohdaten. Liefert 503 wenn kein valider
    Block existiert — die Webseite behaelt dann ihren letzten Stand
    (ISR-stale), statt eine leere Box zu rendern.
    """
```

**Verhalten:**

| Fall | Antwort |
|---|---|
| Valider Block im Cache | `200` + JSON (Vertrag unten) |
| Kein Cache / `llm_overview` ist `null` / keine Tage | `503` + `{"available": false, "reason": …}` |

- Tage auf `config.PUBLIC_WETTERLAGE_DAYS` kürzen (Positions-Vertrag: `days[i]` ↔ `forecast_dates[i]`).
- Header `Cache-Control: public, max-age=300, s-maxage=300`.
- **Kein** `ch_snapshots`, **kein** `europe_grid`, **kein** `unresolved`/`attempts` — Interna bleiben intern.
- Kein CORS-Header: der Abruf ist Server-zu-Server.

**Response-Vertrag (v1)** — das ist die Schnittstelle, gegen die die Webseite validiert:

```json
{
  "version": 1,
  "available": true,
  "lang": "de",
  "generated_at": "2026-07-25T06:26:44",
  "age_hours": 2.4,
  "lage_label": "Nordföhnlage",
  "lead": "Wechselhafter Start, dann Hochdruckaufbau …",
  "days": [
    {
      "date": "2026-07-25",
      "weekday": "Samstag",
      "text": "Samstag: …",
      "flight_hint": "…"
    }
  ],
  "source": {
    "provider": "Wingcast",
    "models": "ICON-CH1, ICON-D2, ICON-EU, GFS (Open-Meteo)"
  }
}
```

`lang` ist bewusst dabei: `config.LANG` ist global (`i18n.get_current_lang()`),
der Cache enthält **genau eine** Sprachversion. Läuft der Server versehentlich
auf `en`, muss die deutsche Seite den Block ausblenden statt englischen Text
zu zeigen → siehe §3.1.

### 2.3 `scheduler.py` — Push-Ping

Im bestehenden Wetterlage-Block (~Zeile 111–127), **nach** erfolgreichem
`refresh_synoptic_overview()` und nur wenn `sctx.get("llm_overview")` gesetzt ist:

```python
_ping_website_revalidate()   # eigenes try/except, Fehler nur geloggt
```

Helper am Modulende: `requests.post(config.WEBSITE_REVALIDATE_URL, …)`,
Secret im Header `X-Revalidate-Secret`, `timeout=10`.

**Harte Regel:** Der Ping darf den Mailversand nie blockieren — eigener
`try/except`, kein `raise`, Timeout gesetzt. Gleiche Disziplin wie beim
bestehenden Grid-Refresh-Block.

### 2.4 `tests/test_public_wetterlage.py` — neu

| Test | Prüft |
|---|---|
| `test_liefert_vertrag` | Alle Pflichtfelder da, `version == 1`, `days` ≤ `PUBLIC_WETTERLAGE_DAYS` |
| `test_keine_rohdaten` | `ch_snapshots`, `europe_grid`, `unresolved`, `attempts` fehlen in der Antwort |
| `test_kein_cache_gibt_503` | Fehlender Cache → 503, `available: false` |
| `test_leeres_llm_overview_gibt_503` | `llm_overview: null` → 503 |
| `test_ping_bricht_scheduler_nicht` | Revalidate-Ping wirft → Scheduler läuft weiter |

`deploy.sh` fährt `pytest -q tests/` vor dem Restart — die Tests sind damit
automatisch Deploy-Gate.

---

## 3. Repo B — `gleitcast_webpage`

### 3.1 `lib/wetterlage.ts` — neu

Serverseitiger Abruf. `zod` ist bereits Dependency.

```ts
export type Wetterlage = { … };

export async function getWetterlage(locale: string): Promise<Wetterlage | null>
```

**Gibt `null` zurück** (Seite zeigt dann nur den statischen Teil) bei:

1. Server nicht erreichbar / 503 / Timeout
2. Antwort besteht die Zod-Prüfung nicht
3. `age_hours > 18` → **veraltete Prognose ist schlimmer als keine**
4. `lang !== locale` → kein englischer Text auf der deutschen Seite

Fetch-Optionen: `next: { revalidate: 3600, tags: ["wetterlage"] }`.
Damit ist der Inhalt serverseitig im HTML (SEO-tauglich) und übersteht
einen Hetzner-Ausfall mit dem letzten guten Stand.

### 3.2 `app/api/revalidate/route.ts` — neu

`POST`, vergleicht `X-Revalidate-Secret` gegen `process.env.REVALIDATE_SECRET`
(timing-safe), ruft `revalidateTag("wetterlage")`. Falsches/fehlendes Secret → `401`.
Liegt unter `/api` und ist damit von `middleware.ts` schon vom Locale-Routing
ausgenommen (`matcher` schliesst `api` aus) — keine Änderung nötig.

### 3.3 `components/sections/Wetterlage.tsx` — neu

Der Block als **eigenständige, wiederverwendbare Komponente**, damit er später
ohne Umbau auch auf anderen Seiten stehen kann.

Enthält: Lage-Label · Lead · die 3 Tage mit Flug-Hinweis · sichtbares
„Stand: Samstag, 06:26 Uhr" · Decision-Support-Disclaimer.
Rendert `null` wenn keine Daten — **nie eine leere Box**.

### 3.4 `app/[locale]/flugwetter-schweiz/page.tsx` — neu

Aufbau der Seite:

1. `<h1>` mit Ziel-Keyword
2. **TL;DR** — der Lead-Satz zuoberst (AI-SEO: Citability, `strategien/approved/ai-seo.md`)
3. Wetterlage-Block (Komponente aus §3.3)
4. **Statischer Erklär-Sockel** — was Nordföhn / Bise / Vb-Lage / Hochdruck für
   Piloten bedeuten. Trägt die Seite an ruhigen Wettertagen und ist der Teil,
   den AI-Suchen zitieren können.
5. FAQ-Block (`FAQPage`-Schema)
6. CTA auf `app.wingcast.ch` mit `utm_source=flugwetter`

**Deutsch-only umsetzen:** `generateStaticParams` gibt nur `{ locale: "de" }`
zurück, andere Locales → `notFound()`. Damit existiert `/fr/flugwetter-schweiz`
gar nicht erst und es entsteht keine hreflang-Leiche.

**Interne Links:** Der Erklär-Sockel *soll* auf `/wetterkunde/foehn` und
`/wetterkunde/talwind` zeigen. Beide existieren noch nicht → Links erst setzen,
wenn die Seiten live sind. Bis dahin Sockel ohne interne Links ausliefern
(kein Link auf 404).

### 3.5 `app/sitemap.ts` · `lib/schema.ts`

- Sitemap: Eintrag `/flugwetter-schweiz`, `changeFrequency: "daily"`,
  **nur `de`**, ohne fr/it-Alternates (die Route existiert dort nicht).
  Die bestehende `languages()`-Hilfsfunktion darf hier nicht greifen.
- Schema: `WebPage`/`Article` mit `dateModified` aus `generated_at`
  (nicht aus `PAGE_LAST_UPDATED` — das ist der manuelle Landing-Wert)
  plus `FAQPage` für den FAQ-Block.

---

## 4. Repo C — `wingcast_marketing` (Doku nachziehen)

`webseite/00-README.md` verlangt: kein Content ohne Eintrag in der Struktur.
Diese Nachträge gehören dazu, sonst läuft die Doku aus dem Ruder:

| Datei | Nachtrag |
|---|---|
| `seo/keywords.md` | `flugwetter schweiz` von `/` bzw. `/funktionen` auf `/flugwetter-schweiz` umhängen, mit Begründung Suchintention |
| `seo/seo-architektur.md` | Seite in den URL-Baum (§2) aufnehmen |
| `strategien/approved/content-struktur-wingcast-ch.md` | Ergänzung im Ziel-URL-Baum + Notiz, dass Pillar 3 damit eine tagesaktuelle Einstiegsseite bekommt |
| `webseite/seiten/flugwetter-schweiz.md` | **Der Seitentext** (H1, TL;DR, Erklär-Sockel, FAQ, Disclaimer) — nach den dortigen Regeln: Ziel-Keyword, Decision-Support-Framing, keine Konkurrenz-Namen, kein Sicherheitsversprechen |
| `seo/redaktionsplan.md` | Seite als Eintrag aufnehmen |

Reihenfolge: **Text zuerst in `webseite/seiten/` schreiben und freigeben lassen**,
dann in die Webpage übertragen. Nicht direkt in TSX texten.

---

## 5. Umgebungsvariablen (manuell zu setzen)

Secret einmalig erzeugen, z. B. `openssl rand -hex 32`, und **auf beiden Seiten
identisch** eintragen.

**Hetzner** — `/home/deploy/flychat/.env`:

```
WINGCAST_REVALIDATE_URL=https://wingcast.ch/api/revalidate
WINGCAST_REVALIDATE_SECRET=<secret>
PUBLIC_WETTERLAGE_DAYS=3
```
danach `sudo systemctl restart wingcast`.

**Vercel** — Project Settings → Environment Variables (Production + Preview):

```
WINGCAST_API_URL=https://app.wingcast.ch
REVALIDATE_SECRET=<derselbe secret>
```

Lokal für Entwicklung: `.env.local` in `gleitcast_webpage` (vor dem Anlegen
prüfen, dass es gitignored ist).

---

## 6. Reihenfolge — Commit, Push, Deploy

**flychat zuerst.** Die Webseite braucht den Endpunkt; umgekehrt ist die
Abhängigkeit tolerant (Webseite ohne Endpunkt = Block einfach unsichtbar).

| # | Schritt | Repo |
|---|---|---|
| 1 | Branch `feat/public-wetterlage-api` | flychat |
| 2 | `config.py`, `web.py`, `scheduler.py`, Tests | flychat |
| 3 | `pytest -q tests/` lokal grün | flychat |
| 4 | Commit + Push, Merge nach `main` | flychat |
| 5 | Auf dem Server: `.env` ergänzen, dann `./deploy.sh` (Tests + Restart) | Hetzner |
| 6 | **Abnahme A** (§7) — Endpunkt liefert Daten | — |
| 7 | Seitentext schreiben + freigeben | marketing |
| 8 | Branch `feat/wetterlage-anbindung` | webpage |
| 9 | `lib/wetterlage.ts`, Revalidate-Route, Komponente, Seite, Sitemap, Schema | webpage |
| 10 | `npm run build` lokal grün | webpage |
| 11 | Commit + Push → Vercel Preview-Deploy | webpage |
| 12 | Env-Variablen in Vercel setzen | Vercel |
| 13 | **Abnahme B–D** (§7) | — |
| 14 | Merge nach `main` → Production | webpage |
| 15 | Doku-Nachträge (§4) committen | marketing |
| 16 | Search Console: Seite zur Indexierung einreichen | — |

Beide Code-Repos waren zu Planungsbeginn sauber, Basis jeweils `main`.
Feature-Branches statt direkt auf `main`, weil flychat produktiv läuft.

---

## 7. Abnahme

**A — Endpunkt (nach Schritt 5)**

```bash
curl -s https://app.wingcast.ch/api/public/wetterlage | python -m json.tool
```
Erwartet: `200`, `version: 1`, `lang: "de"`, `days` mit 3 Einträgen,
`age_hours` klein. Nirgends `ch_snapshots` / `europe_grid`.

**B — Anzeige (nach Schritt 11)**
Preview-URL öffnen, **Seitenquelltext** (nicht DevTools-DOM) prüfen: der Lagetext
muss im ausgelieferten HTML stehen. Steht er nur im DOM, wird clientseitig
geladen — dann ist das SEO-Ziel verfehlt.

**C — Push-Kette (nach Schritt 12)**

```bash
curl -X POST https://wingcast.ch/api/revalidate \
     -H "X-Revalidate-Secret: <secret>"
```
Erwartet `200`. Ohne Header: `401`.
Echter Test am nächsten Morgen: Scheduler-Log zeigt den Ping, Seite trägt
denselben Tag.

**D — Ausfallverhalten** (bewusst provozieren)
`wingcast`-Dienst kurz stoppen → Webseite zeigt weiterhin den letzten Stand,
keine Fehlerseite. Cache-Alter künstlich >18 h → Block verschwindet, statischer
Sockel bleibt. `lang` auf `en` → Block verschwindet.

---

## 8. Rollback

| Problem | Rückweg |
|---|---|
| Endpunkt macht Last/Fehler | Route auskommentieren, `./deploy.sh` — nichts anderes hängt daran |
| Ping stört den Scheduler | `WINGCAST_REVALIDATE_URL` leeren + Restart → Push aus, Pull läuft weiter |
| Seite zeigt Unsinn | Vercel: vorheriges Deployment promoten (sofort wirksam) |
| Grundsätzlich zurück | Beide Merges sind je ein Commit → `git revert` |

Kein Schritt fasst bestehende Cast-, Mail- oder Analyse-Logik an. Der
Wetterlage-Refresh selbst bleibt unverändert — es kommen nur ein Leser und
ein Ping dazu.

---

## 9. Betriebsrisiko — bewusst akzeptiert

Ein öffentlicher, automatisch befüllter Wetter-Output ist eine dauerhafte
Qualitätsfläche: steht einen Tag lang Unsinn drauf, sieht das genau die
Zielgruppe, die auf Datenqualität achtet.

Dagegen gebaut:

- Sichtbares „Stand: …" auf der Seite — nichts wirkt aktueller als es ist
- 18-Stunden-Cutoff: lieber kein Block als ein alter
- Sprach-Check: kein englischer Text auf der deutschen Seite
- Validator + Korrekturschleife + Admin-Alarm laufen bereits im Bestand
  (`engine/synoptic_llm.py`) — der Block ist kein roher LLM-Output
- Ausfall wird in Abnahme D aktiv provoziert, nicht gehofft

Rest-Risiko: eine inhaltlich plausible, aber falsche Lage-Einschätzung fällt
niemandem auf, bis ein Pilot sie meldet. Das ist derselbe Fall wie im Cast —
kein neues Risiko, aber ein öffentlich sichtbares.

---

## 10. Offene Punkte

| # | Punkt | Wer |
|---|---|---|
| 1 | Secret erzeugen und in beide Systeme eintragen (§5) | Maurin |
| 2 | `./deploy.sh` auf dem Hetzner-Server ausführen | Maurin |
| 3 | Seitentext freigeben, bevor er in die Webpage geht (§4) | Maurin |
| 4 | FR/IT: erst wenn der Validator dort greift — eigener Plan | offen |
| 5 | Föhn-Pillar `/wetterkunde/foehn`: paralleler Content-Strang, danach interne Links in §3.4 nachziehen | offen |
