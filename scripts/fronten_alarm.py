"""Ausfall-Alarm fuer die DWD-Frontenkette (Plan §6, Vorgabe vom 27.07.2026).

Die Frontenkette haengt an einer fremden Quelle. Bricht sie weg, darf das nicht
still passieren — sonst faellt es erst auf, wenn wochenlang keine Front mehr
gemeldet wurde und niemand sagen kann, ob das Wetter oder die Kette schuld war.

DREI FAELLE, bewusst unterschieden, weil sie verschiedene Reaktionen brauchen:

  quelle_weg     Download schlaegt fehl, HTTP-Fehler, Datei fehlt oder ist kein
                 lesbares PNG  ->  DWD-Server oder Pfad geaendert.
  layout         Der Projektions-Waechter faellt unter die Profilschwelle oder
                 die Legenden-Invariante bricht  ->  Karte da, aber unsere
                 Kalibrierung passt nicht mehr. DER GEFAEHRLICHSTE FALL: ohne
                 Waechter wuerden falsche Linien ausgeliefert.
  zeichnung_weg  Null Abschnitte auf der GESAMTEN Karte  ->  Farbschema oder
                 Zeichenweise geaendert.

ZUM DRITTEN FALL — der Bezugsrahmen entscheidet. "Keine Front IN UNSEREM
GEBIET" ist bei stabiler Hochdrucklage voellig normal und darf niemals
alarmieren. "Keine Front auf der GESAMTEN Karte" ist etwas anderes: der
Ausschnitt reicht von Groenland bis Nordafrika, dort ist praktisch immer
irgendwo eine Front gezeichnet (gemessen 27.07. ueber elf Karten: 13 bis 19
Abschnitte, nie null). Deshalb zaehlt die Regel ganzkartig — und braucht damit
keine Vorab-Klimatologie.

BETRIEBSVERHALTEN
  - Hoechstens EINE Mail pro Lauf, nicht eine pro Karte.
  - Keine Wiederholung: erneut gemeldet wird erst bei Zustandswechsel oder nach
    WIEDERHOLUNG_TAGE Dauerausfall. Ein taeglich gleicher Alarm wird ignoriert.
  - Entwarnung, wenn es wieder laeuft — sonst weiss niemand, ob der Fehler noch
    offen ist.

Der Zustand liegt in `data/dwd_fronten_archiv/alarm_zustand.json` und ist
VERSIONIERT: die Cloud-Routine hat keinen bleibenden Datentraeger, ohne Commit
waere die Wiederholungssperre nach jedem Lauf vergessen.

Run:
  python scripts/fronten_alarm.py --zustand        # aktuellen Zustand zeigen
  python scripts/fronten_alarm.py --testmail       # Versandweg pruefen
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ZUSTAND_DATEI = ROOT / "data" / "dwd_fronten_archiv" / "alarm_zustand.json"
WIEDERHOLUNG_TAGE = 7

# Reihenfolge = Dringlichkeit. Treten mehrere Faelle in einem Lauf auf, benennt
# die Mail den gefaehrlichsten zuerst: ein Layoutwechsel erzeugt still falsche
# Linien, ein Ausfall erzeugt nur nichts.
FAELLE = {
    "layout": "Kartenlayout passt nicht mehr zur Kalibrierung",
    "quelle_weg": "Quelle nicht erreichbar",
    "zeichnung_weg": "Keine Frontfarben auf der gesamten Karte",
}


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


def lade_zustand() -> dict:
    try:
        return json.loads(ZUSTAND_DATEI.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _speichere_zustand(z: dict) -> None:
    ZUSTAND_DATEI.parent.mkdir(parents=True, exist_ok=True)
    ZUSTAND_DATEI.write_text(json.dumps(z, indent=1, ensure_ascii=False),
                             encoding="utf-8")


class Alarm:
    """Sammelt die Stoerungen eines Laufs und entscheidet am Ende ueber Versand.

    Sammeln statt sofort senden ist der Kern: scheitert der ganze Lauf, waeren
    es sonst fuenf Mails fuer einen Vorfall.
    """

    def __init__(self, versand: bool = True, quelle: str = "Frontenarchiv"):
        self.versand = versand
        self.quelle = quelle
        self.stoerungen: list[dict] = []

    # -- Meldewege -----------------------------------------------------------

    def stoerung(self, fall: str, was: str, url: str = "",
                 wert: float | None = None, schwelle: float | None = None) -> None:
        assert fall in FAELLE, fall
        self.stoerungen.append({"fall": fall, "was": was, "url": url,
                                "wert": wert, "schwelle": schwelle})

    def aus_meldung(self, text: str, was: str, url: str = "") -> None:
        """Ordnet die Ausgabe der Extraktion einem Fall zu.

        Die Extraktion laeuft als Subprozess; ihr Abbruchgrund steht nur im
        Text. Die beiden Marker sind dort bewusst stabil gehalten.
        """
        t = (text or "").upper()
        if "LAYOUT PASST NICHT MEHR" in t or "LEGENDE" in t:
            self.stoerung("layout", was, url)
        else:
            self.stoerung("quelle_weg", f"{was}: {(text or '').strip()[:300]}", url)

    # -- Auswertung ----------------------------------------------------------

    def _aktueller_fall(self) -> str | None:
        for fall in FAELLE:                      # FAELLE ist nach Dringlichkeit sortiert
            if any(s["fall"] == fall for s in self.stoerungen):
                return fall
        return None

    def abschluss(self) -> str:
        """Am Ende des Laufs aufrufen. Gibt zurueck, was entschieden wurde."""
        z = lade_zustand()
        alt, fall = z.get("fall"), self._aktueller_fall()
        jetzt = _jetzt()

        if fall is None:
            if not alt:
                return "kein Alarm (Kette laeuft)"
            self._sende_entwarnung(z, jetzt)
            _speichere_zustand({"fall": None, "seit": jetzt.isoformat(timespec="seconds"),
                                "zuletzt_gemeldet": None,
                                "letzte_entwarnung": jetzt.isoformat(timespec="seconds")})
            return f"Entwarnung gesendet (vorher: {alt})"

        seit = z.get("seit") if alt == fall else jetzt.isoformat(timespec="seconds")
        wechsel = alt != fall
        faellig = False
        if not wechsel and z.get("zuletzt_gemeldet"):
            try:
                faellig = (jetzt - datetime.fromisoformat(z["zuletzt_gemeldet"])
                           ) > timedelta(days=WIEDERHOLUNG_TAGE)
            except ValueError:
                faellig = True

        if wechsel or faellig:
            self._sende_alarm(fall, seit, jetzt, wiederholung=faellig)
            gemeldet = jetzt.isoformat(timespec="seconds")
            ergebnis = (f"Alarm gesendet ({fall}"
                        f"{', Wiederholung' if faellig else ''})")
        else:
            gemeldet = z.get("zuletzt_gemeldet")
            ergebnis = (f"Alarm unterdrueckt ({fall} unveraendert seit "
                        f"{seit} — naechste Meldung nach "
                        f"{WIEDERHOLUNG_TAGE} Tagen)")

        _speichere_zustand({"fall": fall, "seit": seit,
                            "zuletzt_gemeldet": gemeldet,
                            "stoerungen": self.stoerungen})
        return ergebnis

    # -- Versand -------------------------------------------------------------

    def _text_alarm(self, fall: str, seit: str, jetzt: datetime,
                    wiederholung: bool) -> tuple[str, str]:
        zeilen = []
        for s in self.stoerungen:
            z = f"- [{s['fall']}] {s['was']}"
            if s.get("wert") is not None and s.get("schwelle") is not None:
                z += f" (Waechter {s['wert']:.3f} < Schwelle {s['schwelle']:.3f})"
            if s.get("url"):
                z += f"\n    {s['url']}"
            zeilen.append(z)
        betreff = (f"[Wingcast] Frontenkette: {FAELLE[fall]}"
                   f"{' (dauert an)' if wiederholung else ''}")
        text = (
            f"Die {self.quelle}-Kette liefert nicht mehr.\n\n"
            f"Fall:      {fall} — {FAELLE[fall]}\n"
            f"Seit:      {seit}\n"
            f"Zeitpunkt: {jetzt.isoformat(timespec='seconds')}\n\n"
            f"Betroffen:\n" + "\n".join(zeilen) + "\n\n"
            f"Produktverhalten: die Frontenebene wird ausgeblendet statt falsche\n"
            f"Linien zu zeichnen. Der Text kann mangels Frontobjekt ohnehin kein\n"
            f"Frontwort verwenden (Belegpflicht greift von selbst).\n\n"
            f"Naechste Meldung erst bei Zustandswechsel oder nach "
            f"{WIEDERHOLUNG_TAGE} Tagen.\n"
        )
        return betreff, text

    def _sende_alarm(self, fall, seit, jetzt, wiederholung) -> None:
        self._sende(*self._text_alarm(fall, seit, jetzt, wiederholung))

    def _sende_entwarnung(self, z: dict, jetzt: datetime) -> None:
        self._sende(
            "[Wingcast] Frontenkette laeuft wieder",
            f"Die {self.quelle}-Kette liefert wieder.\n\n"
            f"Vorheriger Fall: {z.get('fall')} — "
            f"{FAELLE.get(z.get('fall'), '?')}\n"
            f"Seit:            {z.get('seit')}\n"
            f"Behoben:         {jetzt.isoformat(timespec='seconds')}\n")

    def _sende(self, betreff: str, text: str) -> None:
        print(f"  ALARM-MAIL: {betreff}")
        if not self.versand:
            print("  (Versand abgeschaltet — nur Anzeige)")
            return
        try:
            import config
            import email_service
            html = "<pre>" + text.replace("<", "&lt;").replace(">", "&gt;") + "</pre>"
            ok = email_service.send_email(config.OPS_ALERT_EMAIL, betreff, html, text)
            print(f"  -> {config.OPS_ALERT_EMAIL}: "
                  f"{'gesendet' if ok else 'NICHT gesendet (siehe Log)'}")
        except Exception as e:
            # Ein Alarm, der selbst scheitert, darf den Lauf nicht mitnehmen —
            # die Archivierung ist wichtiger als die Meldung darueber.
            print(f"  ALARM-VERSAND FEHLGESCHLAGEN: {e}")


def selftest() -> int:
    """Prueft die Zustandsmaschine ohne echten Versand.

    Die Regeln "eine Mail pro Lauf", "keine Wiederholung" und "Entwarnung" sind
    genau die, an denen ein Alarmsystem stirbt: zu viel gemeldet und es wird
    ignoriert, zu wenig und der Ausfall bleibt unbemerkt.
    """
    global ZUSTAND_DATEI
    import tempfile
    gesendet: list[str] = []

    class _Probe(Alarm):
        def _sende(self, betreff, text):
            gesendet.append(betreff)

    with tempfile.TemporaryDirectory() as tmp:
        ZUSTAND_DATEI = Path(tmp) / "zustand.json"
        ok = True

        def pruefe(nr, erwartet_mails, beschreibung, ergebnis):
            nonlocal ok
            if len(gesendet) != erwartet_mails:
                print(f"  FEHLER {nr}: {beschreibung} — {erwartet_mails} Mail(s) "
                      f"erwartet, {len(gesendet)} gesendet ({ergebnis})")
                ok = False
            else:
                print(f"  ok {nr}  {beschreibung} ({ergebnis})")

        # 1. Erster Ausfall meldet — und zwar EINMAL, obwohl drei Karten fehlen.
        a = _Probe()
        for i in range(3):
            a.stoerung("quelle_weg", f"Karte {i} nicht erreichbar")
        pruefe(1, 1, "erster Ausfall: eine Mail fuer drei Stoerungen", a.abschluss())

        # 2. Derselbe Fall im naechsten Lauf meldet NICHT erneut.
        a = _Probe()
        a.stoerung("quelle_weg", "immer noch weg")
        pruefe(2, 1, "unveraenderter Ausfall bleibt still", a.abschluss())

        # 3. Zustandswechsel meldet wieder — anderer Fall, andere Ursache.
        a = _Probe()
        a.stoerung("layout", "Waechter unter Schwelle")
        pruefe(3, 2, "Wechsel des Falls meldet erneut", a.abschluss())

        # 4. Mehrere Faelle gleichzeitig: der gefaehrlichste bestimmt die Mail.
        a = _Probe()
        a.stoerung("zeichnung_weg", "0 Abschnitte")
        a.stoerung("layout", "Waechter unter Schwelle")
        if a._aktueller_fall() != "layout":
            print(f"  FEHLER 4: Dringlichkeit falsch ({a._aktueller_fall()})")
            ok = False
        else:
            print("  ok 4  Layoutfall geht dem Zeichnungsfall vor")
        a.abschluss()

        # 5. Nach WIEDERHOLUNG_TAGE meldet der Dauerausfall erneut.
        z = lade_zustand()
        z["zuletzt_gemeldet"] = (_jetzt() - timedelta(days=WIEDERHOLUNG_TAGE + 1)
                                ).isoformat(timespec="seconds")
        _speichere_zustand(z)
        vorher = len(gesendet)
        a = _Probe()
        a.stoerung("layout", "seit einer Woche")
        a.abschluss()
        if len(gesendet) != vorher + 1:
            print("  FEHLER 5: Dauerausfall meldet sich nach 7 Tagen nicht erneut")
            ok = False
        else:
            print(f"  ok 5  Dauerausfall meldet nach {WIEDERHOLUNG_TAGE} Tagen erneut")

        # 6. Laeuft es wieder, kommt die Entwarnung — genau einmal.
        vorher = len(gesendet)
        _Probe().abschluss()
        entwarnt = len(gesendet) == vorher + 1
        vorher = len(gesendet)
        _Probe().abschluss()
        if not entwarnt or len(gesendet) != vorher:
            print("  FEHLER 6: Entwarnung fehlt oder wiederholt sich")
            ok = False
        else:
            print("  ok 6  Entwarnung genau einmal, danach Ruhe")

    print("Selbsttest bestanden" if ok else "SELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true",
                    help="Zustandsmaschine pruefen (ohne Versand)")
    ap.add_argument("--zustand", action="store_true", help="Zustand anzeigen")
    ap.add_argument("--testmail", action="store_true",
                    help="Probealarm senden (Versandweg pruefen, Zustand "
                         "bleibt unberuehrt)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.testmail:
        import config
        a = Alarm(quelle="Frontenarchiv (PROBE)")
        a.stoerung("quelle_weg", "Probealarm, keine echte Stoerung",
                   url="https://opendata.dwd.de/weather/charts/analysis/")
        betreff, text = a._text_alarm("quelle_weg", _jetzt().isoformat(timespec="seconds"),
                                      _jetzt(), wiederholung=False)
        print(f"Empfaenger: {config.OPS_ALERT_EMAIL}\n")
        print(text)
        a._sende(betreff, text)
        return 0

    z = lade_zustand()
    if not z or not z.get("fall"):
        print(f"Kein offener Alarm. ({ZUSTAND_DATEI.relative_to(ROOT)}"
              f"{'' if ZUSTAND_DATEI.exists() else ' existiert noch nicht'})")
        if z.get("letzte_entwarnung"):
            print(f"Letzte Entwarnung: {z['letzte_entwarnung']}")
        return 0
    print(f"Offener Alarm: {z['fall']} — {FAELLE.get(z['fall'], '?')}")
    print(f"  seit             {z.get('seit')}")
    print(f"  zuletzt gemeldet {z.get('zuletzt_gemeldet')}")
    for s in z.get("stoerungen", []):
        print(f"  - [{s['fall']}] {s['was']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
