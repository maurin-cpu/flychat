# validation/chat — was Piloten den Chat-Berater wirklich fragen

Dieser Ordner hält die echten Chat-Verläufe aus der App, damit man sie lesen kann statt
sie nur zu zählen. PostHog kennt nur das Event `chat_message_sent` mit Metadaten,
**der Nachrichtentext steht dort bewusst nicht drin.** Die Wahrheit liegt auf dem Server.

## Ein Nutzer, eine Datei

| Datei | Inhalt | in Git? |
|---|---|---|
| `user_01.md` … `user_24.md` | ein registrierter Nutzer, sein kompletter Chat-Verlauf | ❌ lokal |
| `anon_01.md` … `anon_34.md` | ein anonymer Besucher aus der Demo-Phase | ❌ lokal |
| `00-INDEX.md` | Übersicht aller Nutzer mit erster Frage | ❌ lokal |
| `00-FEHLSCHLAEGE.md` | Spot-Namen, die der Resolver nicht fand | ❌ lokal |
| `konversationen/*.json` | Rohdaten, 1:1 vom Server | ❌ lokal |
| `BEFUNDE.md` | aggregierte Auswertung, ohne Gesprächsinhalte | ✅ |
| `aufbereiten.py` | erzeugt die Nutzerdateien aus den Rohdaten | ✅ |
| `README.md`, `.gitignore` | diese Datei, die Sperre | ✅ |

In jeder Nutzerdatei steht nur der Dialog: was der Pilot geschrieben hat, was Wingcast
geantwortet hat. Hat dieselbe Person mehrmals einen neuen Chat begonnen, trennt eine
Überschrift **Neuer Chat (n von m)** die Abschnitte.

**Warum die Gespräche nicht in Git gehen:** Es sind echte Gespräche echter Nutzer.
Die Session-IDs sind zwar pseudonym (`user_<sub_id>`, `anon_<uuid>`, keine E-Mails), aber
die Gespräche selbst enthalten Ortsangaben, Flugvorhaben und Formulierungen, die eine
Person erkennbar machen können. Die Zuordnung `sub_id` → E-Mail liegt in
`data/subscribers.db` und bleibt dort. Das folgt der Linie des Projekts: Nutzer- und
Maschinendaten sind server-lokal und gitignored, nur Code und Auswertung sind versioniert.

## Holen und aufbereiten

```bash
# 1 · Rohdaten vom Server (read-only)
scp deploy@178.105.39.152:~/flychat/data/history/*.json validation/chat/konversationen/

# 2 · Nutzerdateien erzeugen (räumt alte Läufe selbst weg)
python validation/chat/aufbereiten.py
```

## Zwei Dinge, die das Skript lösen muss

**Das Prelude.** Der ersten Frage eines Chats stellt der Server System-Kontext,
`AKTUELZEIT`, `DATUM-MAPPING` und die Wetterlage voran, bis zu 100'000 Zeichen vor der
eigentlichen Frage. Getrennt wird durch den Marker `Frage des Piloten: `, dieselbe Stelle
wie in `ChatEngine.public_history()` (`chat_engine.py`). Ändert sich der Marker dort, muss
er hier mit. Folgefragen tragen kein Prelude und sind schon Klartext, deshalb sind sie oft
sehr kurz („Jura Thal (so)") — der Kontext läuft aus der vorigen Frage weiter.

**Die Tool-Runde.** Zwischen Frage und Antwort liegen `assistant`-Nachrichten mit
`tool_calls` und leerem Text, dann `tool`-Ergebnisse, und erst danach der Antworttext. Wer
nur die erste `assistant`-Nachricht nimmt, sieht eine leere Antwort. Das Skript sammelt
allen Text bis zur nächsten Frage ein und wirft die Tool-Mechanik weg.

Nebenprodukt derselben Tool-Antworten: welche Spots der Resolver **nicht** gefunden hat.
Das steht als Notiz im Kopf der betroffenen Nutzerdatei und gesammelt in
`00-FEHLSCHLAEGE.md`. Es ist der konkreteste Produktbefund aus diesem Ordner.

## Stand 24.09.2026

42 Nutzer, Zeitraum 19.07. bis 24.09.2026. Acht registriert, 34 anonym aus der Demo-Phase.
Die acht registrierten stammen fast alle aus der Meta-Kampagne vom 20.–23.09. und sind die
interessantesten, weil dort erstmals echte Neu-Nutzer gefragt haben.
Auswertung: [BEFUNDE.md](BEFUNDE.md).
