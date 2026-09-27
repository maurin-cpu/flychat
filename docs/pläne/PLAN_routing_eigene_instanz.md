# Plan: Eigene Routing-Instanz — Fahrzeit-Suche bis 4 Stunden

**Stand:** 2026-09-27 · **Status:** Schritt 1 umgesetzt (nicht deployt), Schritt 2 **nicht gestartet** · **Betroffener Code:** `routing.py`, `engine/chat_orchestrator.py`, `config.py`, `scripts/prewarm_travel_times.py`, `tests/test_routing_travel_time.py`, `tests/test_travel_time_cache.py` · **Befundlage:** `validation/chat/BEFUNDE.md` §7

## Für den Manager

Ein Pilot fragte am 25.09. nach Fluggebieten „maximal 1h30 ab Grenchen". Die App
antwortete dreimal „Dienst gerade ausgefallen, bitte nochmal versuchen" — und war
damit weg. Der Dienst war nie ausgefallen: Der kostenlose Kartendienst rechnet
grundsätzlich nur 60 Minuten. Die Vorgabe lautet jetzt **mindestens 4 Stunden**.

Gebaut und getestet ist alles, was dafür nötig ist: Die Ausrede ist raus, die
Fläche auf der Karte ist als Grundlage abgelöst, und die App nennt zu jedem
Gebiet die echte Fahrzeit („Weissenstein, 30 Min."). Wo die schnelle
Sammelabfrage nichts liefert — das sind rund 60 % unserer Startplätze — füllt sie
die Lücke mit einzelnen Abfragen nach. Ein Speicher auf der Platte macht
wiederholte Fragen sofort beantwortbar.

**Der Gratis-Dienst trägt das aber nicht mehr, und das ist jetzt belegt:** Am
27.09. hat er diesen Entwicklungsrechner nach einem Messtag auf IP-Ebene
ausgesperrt, während er den Produktivserver in 0,1 Sekunden weiter bediente. Ein
Vorwärmlauf sind mehrere hundert Anfragen pro Startort — vom Produktivserver aus
gestartet würde er genau die Funktion sperren, die der Chat live braucht. Das
Vorwärm-Skript verweigert darum von sich aus den Start gegen den Gratis-Dienst.

**Damit ist der eigene Kartendienst keine Komfortfrage mehr, sondern die
Voraussetzung für die 4 Stunden.** Er kostet ein Server-Upgrade, geschätzt 10–15
Euro im Monat, Tarif noch zu belegen. Nebeneffekte: schneller, parallele Anfragen
erlaubt, und keine fremde Abhängigkeit, die uns ohne Vorwarnung aussperrt.

**Entscheidung, die aussteht:** Server vergrößern — ja oder nein. Solange nicht,
liegt die Grenze faktisch bei dem, was eine einzelne Chat-Antwort in ihrem
Zeitbudget schafft; die App sagt dem Piloten dann selbst, dass die Liste noch
nicht vollständig ist.

---

## Die gemessenen Grenzen des Gratis-Dienstes

Alles am 27.09.2026 gegen `valhalla1.openstreetmap.de` (FOSSGIS) nachgemessen,
nicht aus Dokumentation übernommen:

| Verfahren | Grenze | Antwort bei Überschreitung |
|---|---|---|
| Isochrone (Fläche) | **60 Minuten** | HTTP 400 `Exceeded max time: 60` |
| Isochrone (Fläche) | **100 km** | HTTP 400 `Exceeded max distance: 100` |
| Matrix (Fahrzeiten) | **150 km je Route** | HTTP 400 `Path distance exceeds … 150000 meters` |

Dazu eine vierte Grenze, die **nicht** dokumentiert ist und erst beim Messen auffiel:

> Die Matrix liefert für rund **60 % unserer Startplätze keine Fahrzeit** —
> `time: null` ohne Fehlermeldung. Nicht wegen der Entfernung: Rinderalp liegt
> 63 km entfernt, und ein einzelner `/route`-Aufruf zum selben Punkt antwortet
> sauber mit **155 Minuten / 110 km**. Ursache ist die Anbindung an das
> Straßennetz — Startplatz-Koordinaten liegen am Berg. `radius`,
> `search_cutoff` und `minimum_reachability` ändern nichts.

Diese Lücke schließt der **einzelne** Routen-Aufruf vollständig: 25 von 25 zuvor
leeren Zielen kamen korrekt zurück, mit Fahrzeiten von 107 bis 241 Minuten. Er
kostet 0,77 s je Ziel — der Grund für Speicher, Zeitbudget und Vorwärmen.

## Die fünfte Grenze: der Dienst sperrt

Am 27.09.2026, nach einem Tag Messungen inklusive eines Versuchs mit 6 parallelen
Anfragen (davon kamen **1 von 25** durch, und es dauerte länger als sequenziell):

| Von wo | `/status` des Dienstes |
|---|---|
| Entwicklungsrechner | Connect-Timeout, dauerhaft |
| Produktivserver | HTTP 200 in 0,108 s |

Es ist also keine Störung, sondern eine Sperre gegen uns — freundlich gesagt eine
Fair-Use-Regel eines gespendeten Dienstes. Konsequenzen:

1. **Parallelisierung ist keine Option.** Einzelwege bleiben sequenziell,
   0,77 s je Ziel (gemessen an 25 Zielen, 25 Treffer).
2. **Vorwärmen gehört nicht an den öffentlichen Dienst.**
   `scripts/prewarm_travel_times.py` bricht dort von sich aus ab und nennt den
   Grund; `--trotzdem-oeffentlich` ist die bewusste Ausnahme.
3. **Das Zeitbudget im Chat ist damit die eigentliche Grenze**, nicht die
   60 Minuten. `TRAVEL_TIME_CHAT_BUDGET_S` (Default 20 s) entscheidet, wie viele
   Lücken eine Antwort noch füllt; der Rest wird benannt und beim nächsten Mal
   aus dem Speicher geliefert.

## Schritt 1 — umgesetzt am 27.09.2026 (noch nicht deployt)

1. **`RoutingLimitError`** (`routing.py`) trennt die feste Grenze vom
   vorübergehenden Ausfall. Wer eine feste Grenze als „später erneut versuchen"
   ausgibt, baut eine Schleife, die nicht enden kann — genau der Fall vom 25.09.
   `isochrone()` wirft ihn **vor** dem HTTP-Aufruf, wenn die Zeit über der
   konfigurierten Grenze liegt.
2. **`travel_times(lat, lon, targets, mode)`** — Fahrzeit zu vielen Zielen in
   einer Anfrage (Valhalla-Matrix), blockweise, mit 30-Tage-Zwischenspeicher.
   Rückgabe je Ziel: `{"minutes": …, "reason": None|"no_route"|"limit"}`. Ein
   fehlendes Ergebnis wird **benannt, nie geschätzt**.
3. **Abbruch an der Streckengrenze.** Ziele nach Luftlinie sortiert; reißt ein
   Block die 150-km-Grenze, sucht eine Binärsuche die Bruchstelle und alles
   dahinter wird markiert statt einzeln angefragt. Das war der Unterschied
   zwischen **152 s und 10 s** je Anfrage (gemessen, 334 Kandidaten ab Grenchen).
4. **Luftlinien-Vorfilter** mit 120 km/h Obergrenze: Was weiter weg liegt, kann
   die Fahrzeit nie einhalten, weil die Fahrstrecke immer länger ist als die
   Luftlinie. Kann also keinen echten Treffer verlieren.
5. **Der wichtigste Test** hält fest, dass ein echter Ausfall (HTTP 503) **nicht**
   als Grenze verharmlost wird — die Verwechslung darf sich nicht umgekehrt
   einschleichen.
6. **Fläche abgelöst.** `find_spots_within_travel_time` benutzt keine Isochrone
   mehr — weder als Filter noch als Zeichnung. Die Funktion `routing.isochrone()`
   bleibt bestehen, weil `mcp_server/geo.py` sie nutzt.
7. **Einzelweg als Lückenfüller** (`routing.route_minutes()`): Wo die
   Sammelabfrage `null` liefert, fragt der Chat einzeln nach — nächste Ziele
   zuerst, begrenzt durch `TRAVEL_TIME_CHAT_BUDGET_S`. Gemessen: 25 von 25
   zuvor leeren Zielen kamen so korrekt zurück (107–241 Minuten).
8. **Speicher auf der Platte** (`data/travel_times_cache.json`, gitignored,
   30 Tage): mergendes, atomares Schreiben, mtime-Abgleich beim Lesen. Ohne die
   Datei wäre Vorwärmen sinnlos — Skript und Server sind zwei Prozesse. Eine
   Zeitnot (`reason="budget"`) wird ausdrücklich **nicht** gespeichert, sonst
   friert ein halbes Ergebnis für 30 Tage ein.
9. **`scripts/prewarm_travel_times.py`** wärmt je Startort vor — Abonnenten-
   Regionen, Ortsliste oder einzelner Ort. Schreibt nach jedem Startort, ein
   Abbruch verliert höchstens den laufenden. Gegen den öffentlichen Dienst
   verweigert es den Start (siehe oben).
10. **25 Tests** in `tests/test_routing_travel_time.py` und
   `tests/test_travel_time_cache.py`, ohne Netz. Gesamtsuite 740 grün.

**Offen vor dem Deploy:** Sichtprüfung im laufenden Chat — dafür muss die IP-Sperre
abgelaufen sein oder der Test vom Server aus laufen. Danach Commit + Deploy.

**Bekannte Restbaustelle, bewusst nicht angefasst:** `mcp_server/geo.py` fällt bei
Isochronen-Ausfall auf einen Luftlinien-Radius zurück (`_minutes_to_km`, „Auto
~55 km/h effektiv") und benennt die Methode in der Antwort. Das ist eine
*geschätzte* Reichweite — dieselbe Klasse von Aussage, die der Chat jetzt
vermeidet. Beim Umstellen auf die eigene Instanz mitnehmen.

## Schritt 2 — eigene Instanz (nicht gestartet)

Erst hier sind 4 Stunden möglich. Reihenfolge:

1. **Server-Tarif prüfen und entscheiden.** Heute: 3 GB Speicher (1 GB frei),
   2 Kerne, 17 GB Platte, kein Docker. Das trägt keine zweite Karten-Anwendung.
   Kandidat ist der nächstgrößere Hetzner-Tarif; Preis vor der Buchung belegen,
   nicht schätzen.
2. **Kachel-Aufbau nicht auf dem Produktivserver.** Das Aufbereiten der
   OSM-Daten braucht deutlich mehr Speicher als der Betrieb. Auf dem
   Entwicklungsrechner oder einer temporären Maschine bauen, Ergebnis
   übertragen. Umfang der Daten vorher messen, nicht annehmen.
3. **Abdeckung festlegen.** 4 Stunden ab der Schweiz reicht weit ins Ausland.
   Unsere 494 Startplätze sind schweizerisch — für die Fahrzeit zählt aber das
   Straßennetz auf dem Weg, nicht nur am Ziel. Ein Ausschnitt nur Schweiz
   verfälscht Routen, die über deutsches oder französisches Gebiet führen.
   Vermutlich also Alpenraum statt nur Schweiz. **Messen**: dieselben
   Startplätze gegen beide Ausschnitte rechnen und die Abweichung zeigen.
4. **Anbindungsproblem lösen.** Auf eigener Instanz sind Snapping-Parameter
   frei wählbar; ob damit die 60 % Startplätze ohne Route verschwinden, ist
   **unbewiesen**. Prüfen, bevor 4 Stunden versprochen werden. Fällt es nicht
   weg, ist die Alternative eine Parkplatz-Koordinate je Startplatz — das ist
   Datenarbeit, nicht Technik, und gehört dann in die Spot-CSV.
5. **Grenzen umstellen** über `VALHALLA_MAX_ISOCHRONE_MINUTES` und
   `VALHALLA_MAX_MATRIX_KM` (Umgebungsvariablen, genau dafür angelegt) —
   mit den Werten der eigenen Instanz, wieder gemessen statt angenommen.
6. **Ausfall der eigenen Instanz.** Sie wird zur eigenen Baustelle. Ein Ausfall
   muss als Ausfall erscheinen (`RoutingError`), nicht als Grenze — und das Gate
   am messbaren Ergebnis festmachen, nicht an der bekannten Fehlerursache.

## Eiserne Regel für diesen Plan

Keine Fahrzeit erfinden. Keine Luftlinie in eine Fahrzeit umrechnen. Wo keine Zahl
vorliegt, wird das gesagt. Der ganze Befund aus `BEFUNDE.md` §7 ist nicht, dass die
Grenze existiert — sondern dass die App darüber gelogen hat.
