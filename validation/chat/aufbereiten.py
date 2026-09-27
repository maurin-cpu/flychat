#!/usr/bin/env python3
"""Schreibt pro Nutzer eine Datei mit dem reinen Chat-Verlauf.

Quelle: validation/chat/konversationen/<session>.json — 1:1 vom Server
        (scp deploy@178.105.39.152:~/flychat/data/history/*.json).
Ziel:   validation/chat/user_07.md, anon_03.md, ... — eine Datei pro Nutzer,
        darin nur: was der Pilot geschrieben hat, was Wingcast geantwortet hat.

Ein Nutzer = eine Datei
-----------------------
Die History haengt am eingeloggten Nutzer, nicht am Geraet (`_chat_session_id()`
in web.py): `user_<sub_id>` sammelt alles, was diese Person je gefragt hat.
Anonyme Besucher aus der Demo-Phase bekommen `anon_<uuid>` pro Browser — naeher
als das kommt man einer Person dort nicht. Die langen UUIDs werden hier zu
`anon_01`, `anon_02`, ... durchnummeriert, chronologisch nach letzter Aktivitaet.

Woran man einen neuen Chat erkennt
----------------------------------
Einzelne Nachrichten tragen keinen Zeitstempel. Aber die **erste** Frage eines
Chats bekommt vom Server ein Prelude vorangestellt (System-Kontext, AKTUELZEIT,
DATUM-MAPPING, Wetterlage), abgetrennt durch den Marker "Frage des Piloten: ".
Taucht der Marker mitten im Verlauf erneut auf, wurde ein neuer Chat begonnen.
In `user_7` passiert das viermal, bei allen anderen genau einmal.

Was hier wegfaellt
------------------
System-Prompt, Prelude, Tool-Aufrufe und Tool-Antworten. Assistant-Nachrichten
ohne Text (reine Tool-Aufrufe) werden uebersprungen, ihr Antworttext kommt in der
naechsten Nachricht und wird mit der Frage zusammengefuehrt. Uebrig bleibt der
Dialog. Nicht aufloesbare Spot-Namen stehen als Notiz im Dateikopf, weil sie
erklaeren, warum manche Antworten ausweichen — im Verlauf selbst stehen sie nicht.

Datenschutz
-----------
Session-IDs sind pseudonym, keine E-Mails. Die Zuordnung sub_id -> E-Mail liegt in
data/subscribers.db und bleibt dort. Die erzeugten Dateien sind gitignored.

Aufruf:  python validation/chat/aufbereiten.py
"""

import io
import json
import glob
import os
import re

HIER = os.path.dirname(os.path.abspath(__file__))
ROH = os.path.join(HIER, "konversationen")
MARKER = "Frage des Piloten: "
NICHT_GEFUNDEN = re.compile(r'"error"\s*:\s*"(?:Spot|Region)\s+\'([^\']+)\'\s+nicht gefunden"')


def chats(msgs):
    """Zerlegt einen Verlauf in Chats, jeder Chat eine Liste von (Rolle, Text).

    Neuer Chat immer dann, wenn eine Nutzernachricht das Prelude traegt.
    """
    alle, aktuell, offene_frage = [], [], None
    for m in msgs:
        rolle = m.get("role")
        if rolle not in ("user", "assistant"):
            continue
        inhalt = m.get("content")
        if not isinstance(inhalt, str):
            inhalt = "" if inhalt is None else str(inhalt)

        if rolle == "user":
            neuer_chat = MARKER in inhalt
            text = inhalt.split(MARKER, 1)[1].strip() if neuer_chat else inhalt.strip()
            if neuer_chat and aktuell:
                alle.append(aktuell)
                aktuell = []
            aktuell.append(("pilot", text))
            offene_frage = True
        else:
            text = inhalt.strip()
            if not text:
                continue  # reiner Tool-Aufruf, kein Dialog
            if aktuell and aktuell[-1][0] == "wingcast" and not offene_frage:
                aktuell[-1] = ("wingcast", aktuell[-1][1] + "\n\n" + text)
            else:
                aktuell.append(("wingcast", text))
            offene_frage = False
    if aktuell:
        alle.append(aktuell)
    return alle


def fehlende_spots(msgs):
    treffer = []
    for m in msgs:
        if m.get("role") == "tool":
            inhalt = m.get("content") or ""
            treffer += NICHT_GEFUNDEN.findall(str(inhalt))
    return sorted(set(treffer))


def main() -> None:
    dateien = sorted(glob.glob(os.path.join(ROH, "*.json")))
    if not dateien:
        print("Keine Rohdaten in", ROH)
        print("Erst holen:  scp deploy@178.105.39.152:~/flychat/data/history/*.json", ROH)
        return

    # Alte Dateien aus frueheren Laeufen wegraeumen
    for alt in glob.glob(os.path.join(HIER, "20*.md")) + \
               glob.glob(os.path.join(HIER, "user_*.md")) + \
               glob.glob(os.path.join(HIER, "anon_*.md")):
        os.remove(alt)

    eintraege = []
    for pfad in dateien:
        session = os.path.basename(pfad)[:-5]
        d = json.load(io.open(pfad, encoding="utf-8"))
        msgs = d.get("messages", [])
        cs = chats(msgs)
        if not cs:
            continue
        eintraege.append({
            "session": session,
            "registriert": session.startswith("user_"),
            "zuletzt": str(d.get("last_activity") or ""),
            "chats": cs,
            "fehlend": fehlende_spots(msgs),
            "fragen": sum(1 for c in cs for r, _ in c if r == "pilot"),
        })

    eintraege.sort(key=lambda e: (not e["registriert"], e["zuletzt"]))

    anon_nr = 0
    for e in eintraege:
        if e["registriert"]:
            nr = e["session"].split("_", 1)[1]
            e["name"] = f"user_{int(nr):02d}" if nr.isdigit() else e["session"]
        else:
            anon_nr += 1
            e["name"] = f"anon_{anon_nr:02d}"

    for e in eintraege:
        ziel = os.path.join(HIER, f"{e['name']}.md")
        with io.open(ziel, "w", encoding="utf-8") as f:
            art = "Registrierter Nutzer" if e["registriert"] else "Anonym (Demo-Phase)"
            f.write(f"# {e['name']}\n\n")
            f.write(f"{art} · {e['fragen']} Fragen · {len(e['chats'])} Chat"
                    f"{'s' if len(e['chats']) != 1 else ''} · zuletzt aktiv {e['zuletzt'][:16].replace('T', ' ')}\n\n")
            if e["fehlend"]:
                f.write(f"> Nicht gefundene Spots in diesem Verlauf: {', '.join(e['fehlend'])}\n\n")
            f.write(f"<!-- Rohdaten: konversationen/{e['session']}.json -->\n\n")
            for i, c in enumerate(e["chats"], 1):
                if len(e["chats"]) > 1:
                    f.write(f"---\n\n## Neuer Chat ({i} von {len(e['chats'])})\n\n")
                else:
                    f.write("---\n\n")
                for rolle, text in c:
                    wer = "**Pilot:**" if rolle == "pilot" else "**Wingcast:**"
                    f.write(f"{wer} {text}\n\n")

    with io.open(os.path.join(HIER, "00-INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# Chat-Verlaeufe — eine Datei pro Nutzer\n\n")
        f.write("Erzeugt von `aufbereiten.py`. Alles hier ist gitignored, es sind echte Gespraeche.\n")
        f.write("Auswertung ohne Personenbezug: [BEFUNDE.md](BEFUNDE.md).\n\n")
        f.write("| Datei | Nutzer | Fragen | Chats | zuletzt aktiv | erste Frage |\n")
        f.write("|---|---|---|---|---|---|\n")
        for e in eintraege:
            erste = e["chats"][0][0][1].replace("\n", " ").replace("|", "/")[:60]
            art = "registriert" if e["registriert"] else "anonym"
            f.write(f"| [`{e['name']}`]({e['name']}.md) | {art} | {e['fragen']} | {len(e['chats'])} | "
                    f"{e['zuletzt'][:16].replace('T', ' ')} | {erste} |\n")

    alle_fehlend = {}
    for e in eintraege:
        for name in e["fehlend"]:
            alle_fehlend.setdefault(name, []).append(e["name"])
    with io.open(os.path.join(HIER, "00-FEHLSCHLAEGE.md"), "w", encoding="utf-8") as f:
        f.write("# Spot-Namen, die der Resolver nicht gefunden hat\n\n")
        f.write("| Name | Nutzer |\n|---|---|\n")
        for name, wer in sorted(alle_fehlend.items(), key=lambda kv: -len(kv[1])):
            f.write(f"| {name} | {', '.join(sorted(set(wer)))} |\n")

    reg = sum(1 for e in eintraege if e["registriert"])
    print(f"{len(eintraege)} Dateien geschrieben ({reg} registriert, {len(eintraege) - reg} anonym)")
    print(f"{len(alle_fehlend)} verschiedene Spot-Namen nicht gefunden")


if __name__ == "__main__":
    main()
