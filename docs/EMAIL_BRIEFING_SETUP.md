# E-Mail-Briefing MVP — Setup & Test-Checkliste

Stufen 1-6 abgeschlossen. Dieses Dokument listet alles, was du **einrichten** und **testen** musst, bevor der MVP live versenden kann.

---

## Teil A — Einmalige Einrichtung

### A1. Supabase-Migration ausfuehren

Tabellen `subscribers` + `subscriber_feedback` anlegen.

```
Supabase Dashboard -> SQL Editor -> New query ->
  Inhalt von migrations/002_subscribers.sql einfuegen -> Run
```

**Pruefen:**
```sql
SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'subscriber%';
-- Erwartet: subscribers, subscriber_feedback
```

---

### A2. Infomaniak-SMTP einrichten

**Im Infomaniak-Kundenbereich:**
1. Mail-Service → Mailbox fuer Versand-Absender anlegen (z.B. `briefing@deine-domain.ch`)
2. Passwort notieren
3. SPF/DKIM pruefen (Mail-Service → Sicherheit): beide muessen aktiv sein, sonst landet Mail im Spam
4. Optional DMARC-Record setzen

### A3. `.env`-Datei pruefen / ergaenzen

Folgende Variablen MUESSEN gesetzt sein:

```dotenv
# Supabase (war vermutlich schon vorhanden)
SUPABASE_DATABASE_URL=postgresql://...
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=...

# Domain-URL — zeigt in allen Mail-Links + Deep-Links auf
# WICHTIG: app.wingcast.ch (Flask-App), NICHT wingcast.ch (Marketing-Page)
WINGCAST_BASE_URL=https://app.wingcast.ch
WINGCAST_MARKETING_URL=https://wingcast.ch

# Infomaniak SMTP
SMTP_HOST=mail.infomaniak.com
SMTP_PORT=465
SMTP_USE_SSL=1
SMTP_USER=briefing@deine-domain.ch
SMTP_PASSWORD=<infomaniak-mailpasswort>
SENDER_EMAIL=briefing@deine-domain.ch
SENDER_NAME=Wingcast
```

**Test:**
```bash
python -c "import config; print('BASE_URL:', config.BASE_URL); print('SMTP:', config.SMTP_HOST, config.SMTP_PORT); print('Pw gesetzt:', bool(config.SMTP_PASSWORD))"
```
Alle drei muessen sinnvolle Werte zeigen.

---

## Teil B — Test-Checkliste pro Stufe

### Stufe 1 — Subscribe + DB

#### B1.1 Landing-Page rendert

- [ ] Server starten: `python main.py`
- [ ] `http://localhost:5000/subscribe` oeffnen
- [ ] Form zeigt: E-Mail-Feld, 29 Regions-Checkboxen, 3 Level-Radios, Submit-Button
- [ ] Link „So sieht eine Briefing-Mail aus →" sichtbar ueber dem Formular

#### B1.2 Validation greift

- [ ] Submit ohne E-Mail → Fehler „Bitte gib deine E-Mail-Adresse ein."
- [ ] Submit ohne Region → Fehler „Bitte waehle mindestens eine Region aus."
- [ ] Submit mit ungueltiger E-Mail (`test@x`) → Fehler „bereits registriert oder ungueltig"

#### B1.3 Erfolgreicher Subscribe

- [ ] Mit `deine-mail@gmail.com` + 2 Regionen + Standard-Level submitten
- [ ] Status-Seite „Fast geschafft!" zeigt deine E-Mail
- [ ] DB pruefen:
```sql
SELECT id, email, status, regions, confirm_token FROM subscribers ORDER BY id DESC LIMIT 1;
-- status='pending', confirm_token gesetzt (langer String)
```

---

### Stufe 2 — Confirm + Welcome-Mail (SMTP)

#### B2.1 Confirm-Mail laeuft lokal (Dry-Run)

Zuerst **ohne** echten SMTP testen — HTML-Preview in Tempdir.

- [ ] `WINGCAST_SMTP_DRY_RUN=1 python main.py` (auf Windows: vorher `set WINGCAST_SMTP_DRY_RUN=1`)
- [ ] Landing ausfuellen und submitten
- [ ] In der Python-Konsole erscheint: `[SMTP DRY-RUN] -> ... geschrieben nach %TEMP%\wingcast_mail_preview\...`
- [ ] HTML-Datei oeffnen: Button „Abo bestaetigen" sichtbar + Fallback-Link

#### B2.2 Confirm-Mail echt per SMTP

- [ ] `python main.py` (ohne DRY_RUN)
- [ ] Subscribe mit **eigener** E-Mail
- [ ] Bestaetigungs-Mail kommt in ~5 Sekunden an
- [ ] Betreff: `Bestaetige dein Wingcast-Abo`
- [ ] Absender: `Wingcast <briefing@...>`
- [ ] Mail rendert in Gmail, Apple Mail, Outlook Web (oder wo du testest)
- [ ] Button klicken → fuehrt auf `/confirm/<token>`

#### B2.3 Confirm + Welcome

- [ ] Nach Klick erscheint Status „Abo aktiviert!"
- [ ] Welcome-Mail kommt in ~5 Sekunden nach
- [ ] Welcome zeigt: deine Regionen, dein Level, „Naechstes Briefing Mo/Mi/Fr 06:30"
- [ ] DB pruefen: `SELECT status, confirmed_at FROM subscribers WHERE email='deine@mail';`
  → `status='active'`, `confirmed_at` gesetzt

#### B2.4 Fehlerpfade

- [ ] Gleiche E-Mail nochmal subscriben → Fehler „bereits registriert"
- [ ] Alten Confirm-Link nochmal klicken → „Link ungueltig oder bereits verwendet"
- [ ] Muell-Token ausprobieren: `/confirm/asdfasdf` → 404-Seite

---

### Stufe 3 — Briefing-Mail + Feedback

#### B3.1 CLI-Preview (Dry-Run, empfohlen zuerst)

- [ ] Voraussetzung: mindestens 1 aktiver Subscriber in der DB
- [ ] `python email_service.py --preview deine@mail`
- [ ] Output zeigt: Subscriber gefunden + briefing_data geladen + OK
- [ ] HTML oeffnen aus `%TEMP%\wingcast_mail_preview\...__Wingcast_KW...html`
- [ ] Pruefen: Verdict-Block oben (wenn >=1 fliegbarer Tag in deinen Regionen), Tages-Sektionen, Spot-Karten mit Sicherheit + Flug, Feedback-Buttons

#### B3.2 Briefing echt versenden

- [ ] `python email_service.py --preview deine@mail --send`
- [ ] Mail kommt an, Betreff enthaelt `KW<nr>`
- [ ] Mobile im Handy pruefen (kein horizontales Scrollen, Buttons gross genug)

#### B3.3 Dashboard-Link aus Mail

- [ ] Button „Im Dashboard ansehen" klicken
- [ ] Browser oeffnet `/briefing?regions=...&day=<idx>`
- [ ] Dashboard zeigt NUR deine Regionen + bester Tag vorausgewaehlt
- [ ] URL wird zu `/briefing` bereinigt (kein `?regions=` mehr nach Laden)

#### B3.4 Feedback-Links

- [ ] In der Mail auf „Ja, passte" klicken
- [ ] Thank-You-Seite erscheint
- [ ] DB pruefen: `SELECT * FROM subscriber_feedback WHERE subscriber_id=<dein-id>;` → 1 Row mit `verdict='correct'`
- [ ] „Nein, lag daneben" testen → analog, verdict='wrong'

---

### Stufe 4 — Scheduler + Pause/Resume

#### B4.1 Zeitpunkte anzeigen

- [ ] `python scheduler.py --next`
- [ ] Output: naechstes Briefing (Mo/Mi/Fr 06:30) + naechste Accuracy (1. des Monats 07:00)

#### B4.2 Sofort-Versand testen (Dry-Run)

- [ ] `WINGCAST_SMTP_DRY_RUN=1 python scheduler.py --now`
- [ ] Output: `[DONE] total=N sent=N skipped=0 failed=0`
- [ ] Fuer jeden aktiven Subscriber liegt HTML in `%TEMP%\wingcast_mail_preview\`

#### B4.3 Scheduler-Thread im Production-Modus

- [ ] `SCHEDULER_TEST_MODE=1 WINGCAST_SMTP_DRY_RUN=1 python main.py`
- [ ] Log zeigt: „Scheduler: test-mode Wartezeit 30s"
- [ ] Nach 30s: „Scheduler: ... sent=N ..."
- [ ] Danach: „Scheduler: naechstes Event=briefing um <Datum>"

#### B4.4 Account-Seite

- [ ] In einer empfangenen Briefing-Mail den „Einstellungen"-Link im Footer klicken
  (oder URL manuell: `<BASE_URL>/account/<action_token>`)
- [ ] Seite zeigt: E-Mail, Status „Aktiv", Level, Regionen
- [ ] „Pause 2 Wochen" klicken → Status wechselt zu „Pausiert bis YYYY-MM-DD"
- [ ] „Jetzt fortsetzen" klicken → zurueck zu „Aktiv"
- [ ] „Pause 1 Monat" testen
- [ ] Wenn pausiert: Scheduler-Run skippt diesen Subscriber
  ```bash
  python scheduler.py --now   # Log zeigt Subscriber NICHT
  ```

#### B4.5 Unsubscribe

- [ ] Auf Account-Seite oder im Mail-Footer „Abmelden" klicken
- [ ] Status-Seite „Abgemeldet"
- [ ] DB: `status='unsubscribed'`
- [ ] Scheduler-Run verschickt nichts mehr an diese E-Mail
- [ ] Wieder Subscribe mit gleicher E-Mail → funktioniert (Re-Subscribe-Pfad)

---

### Stufe 5 — Deep-Link Dashboard

#### B5.1 URL-Parameter wirken

- [ ] `http://localhost:5000/briefing?regions=alpstein,loetschental&day=2` oeffnen
- [ ] Nur die 2 Regionen sichtbar
- [ ] Tag-Index 2 vorausgewaehlt
- [ ] Nach Laden: URL steht auf `/briefing` (Params wurden entfernt)
- [ ] localStorage persistent: Reload ohne Params zeigt gleiche Ansicht

#### B5.2 Edge-Cases

- [ ] `/briefing?day=banana` → kein Crash, day bleibt auf Default
- [ ] `/briefing?day=-1` → ignoriert
- [ ] `/briefing` (ohne Params) → normales Dashboard-Verhalten

---

### Stufe 6 — Safety-Header, Live-Preview, Accuracy

#### B6.1 Safety-Header erscheint bei Warnungen

- [ ] Fachlich: Es muss ein Tag in deinen Regionen geben, dessen Spot-Analyse
      `Foehn`, `Gewitter`, `Sturm` oder `Windscherung` erwaehnt
- [ ] Pragmatisch zum Testen: warte auf einen Foehn-Tag oder forciere via Mock
- [ ] Preview-Mail zeigt rote Box ganz oben: „[!] Sicherheits-Hinweis" mit den Tagen

#### B6.2 Live-Preview auf der Landing

- [ ] `/subscribe` oeffnen
- [ ] „So sieht eine Briefing-Mail aus →" klicken (neuer Tab)
- [ ] Preview rendert mit aktuellen echten Daten, ALLE Regionen
- [ ] Unsubscribe/Feedback-Links sind neutralisiert (`#`) — ins Leere klicken schadet nicht
- [ ] Dashboard-Link fuehrt auf echtes `/briefing`

#### B6.3 Accuracy-Mail

- [ ] Voraussetzung: Du brauchst mindestens 3 Feedback-Eintraege in den letzten 30 Tagen
- [ ] Schnell testen: 3× Feedback per `/feedback/<token>/correct` + `/wrong` klicken
- [ ] `python scheduler.py --accuracy-now`
- [ ] Log: `[ACCURACY] -> deine@mail (#id) OK (N%)`
- [ ] Mail kommt an, zeigt grosse Prozent-Zahl, Framing nach Bucket (>=80 gruen, >=60 amber, sonst rot)
- [ ] Subscriber mit <3 Feedbacks werden geskippt (Log: „zu wenig Feedback (N) -> skip")

---

## Teil C — End-to-End-Test (empfohlener Ablauf vor Launch)

**Stelle dich als neuer Pilot vor, der Wingcast entdeckt.**

1. - [ ] Landing `/subscribe` oeffnen — Hero klar? Preview-Link funktioniert?
2. - [ ] Preview-Mail anschauen — wirkt vertrauenswuerdig?
3. - [ ] Subscribe mit deiner eigenen E-Mail
4. - [ ] Confirm-Mail kommt → Klick → Welcome-Mail kommt
5. - [ ] Warte auf naechsten Mo/Mi/Fr 06:30 ODER forciere: `python scheduler.py --now`
6. - [ ] Briefing-Mail in deinem Posteingang — Mobile pruefen
7. - [ ] Dashboard-Link aus Mail → landet auf gefilterter Ansicht
8. - [ ] Feedback „Ja, passte" klicken → Thank-You
9. - [ ] Footer: „Einstellungen" klicken → Account-Seite
10. - [ ] Pause 14 Tage setzen → kommende Briefings werden geskippt
11. - [ ] Resume → Briefings gehen wieder
12. - [ ] Abmelden → Status-Seite → neue Subscribes mit gleicher E-Mail funktionieren

Wenn alle 12 Punkte gruen: MVP ist launch-fertig.

---

## Teil D — Troubleshooting

| Symptom | Wahrscheinliche Ursache | Fix |
|---|---|---|
| POST /subscribe → „Service nicht verfuegbar" | `SUPABASE_DATABASE_URL` fehlt | `.env` pruefen |
| Mail kommt nicht an, kein Log-Fehler | Mail im Spam gelandet | SPF/DKIM bei Infomaniak pruefen |
| `SMTP Auth fehlgeschlagen` | Passwort falsch oder Mailbox nicht freigeschaltet | Infomaniak-Kundenbereich pruefen |
| `relation "subscribers" does not exist` | Migration `002_subscribers.sql` nicht gelaufen | Teil A1 ausfuehren |
| Links zeigen auf `https://example.invalid/...` | `WINGCAST_BASE_URL` nicht gesetzt | `.env` setzen + Server neu starten |
| Links zeigen auf `http://localhost:5000/...` | `WINGCAST_BASE_URL` zeigt auf localhost (Dev-Wert) | In `/home/deploy/flychat/.env` auf `https://app.wingcast.ch` setzen + `sudo systemctl restart wingcast` |
| `/preview/briefing` → 503 | Engine noch nicht geladen (Vercel-Kaltstart) | Nach 30s nochmal laden |
| Scheduler sendet nichts | `WINGCAST_BRIEFINGS=0` oder keine aktiven Subscriber | Log pruefen, `SELECT * FROM subscribers WHERE status='active';` |
| Briefing-Link im Dashboard filtert nicht | Browser-Cache | Hard-Reload (Ctrl+Shift+R), static-file-Version pruefen |
| Accuracy-Mail wird nicht gesendet | <3 Feedbacks in 30 Tagen | Mehr Feedback sammeln oder Window erhoehen |

---

## Teil E — Operative Hinweise nach Launch

### Monitoring

- Log-Tail: `python main.py 2>&1 | tee -a /var/log/wingcast.log`
- Kritische Keywords: `SMTP send fehlgeschlagen`, `list_active failed`, `EXCEPTION`

### Regelmaessige Checks

- [ ] Taeglich: `SELECT status, COUNT(*) FROM subscribers GROUP BY status;`
- [ ] Woechentlich: Bounce-Rate in Infomaniak-Webmail pruefen
- [ ] Monatlich: Accuracy-Stats pruefen
  ```sql
  SELECT verdict, COUNT(*) FROM subscriber_feedback
   WHERE created_at >= NOW() - INTERVAL '30 days' GROUP BY verdict;
  ```

### Scheduler-Kontrolle

- Scheduler deaktivieren: `WINGCAST_BRIEFINGS=0 python main.py`
- Scheduler manuell triggern:
  - `python scheduler.py --now` (Briefing sofort)
  - `python scheduler.py --accuracy-now` (Accuracy sofort)
  - `python scheduler.py --next` (zeigt naechste Events)

### Einzelne Mail-Preview ohne Versand

```bash
python email_service.py --preview <email>     # Dry-Run (default)
python email_service.py --preview <email> --send   # echt verschicken
```
