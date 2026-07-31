"""Erzeugt einen Login-Link fuer die LOKALE Entwicklung — ohne E-Mail-Versand.

WARUM ES LOKAL KEINE MAIL GIBT (zwei unabhaengige Gruende)
----------------------------------------------------------
1. `SMTP_USER`/`SMTP_PASSWORD` sind lokal leer -> es gibt keinen Mailversand.
2. `config.BASE_URL` zeigt per Default auf https://app.wingcast.ch. Selbst ein
   erfolgreicher Versand wuerde also einen Link auf die PRODUKTION enthalten,
   nicht auf den lokalen Server. Zusaetzlich blockiert email_service.py reale
   Sends, wenn BASE_URL auf localhost zeigt.

Der Login-Token wird aber in JEDEM Fall in data/subscribers.db geschrieben —
nur der Weg zum Briefkasten fehlt. Dieses Skript nimmt den Token direkt aus der
Datenbank und baut die lokale URL daraus.

Admin-Rechte: `web.py:_is_admin()` prueft schlicht, ob die eingeloggte
Session-Mail == `config.ADMIN_EMAIL` ist. Wer sich mit dieser Adresse einloggt,
ist Admin — es gibt kein separates Passwort.

NUR FUER LOKALE ENTWICKLUNG. Das Skript braucht Schreibzugriff auf die lokale
subscribers.db; wer den hat, kann die Datenbank ohnehin direkt aendern — es
umgeht also keine Schutzmassnahme, es spart den Mail-Umweg.

Usage:
    python debug_scripts/local_login_link.py                 # ADMIN_EMAIL, Port 5000
    python debug_scripts/local_login_link.py --port 5001
    python debug_scripts/local_login_link.py --email x@y.ch
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config
from subscriber import SubscriberManager


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--email", default=config.ADMIN_EMAIL,
                    help=f"Default: config.ADMIN_EMAIL ({config.ADMIN_EMAIL})")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--ttl", type=int, default=120, help="Gueltigkeit in Minuten")
    args = ap.parse_args(argv)

    mgr = SubscriberManager(config.SUBSCRIBERS_DB_PATH)
    result = mgr.create_login_token(args.email, ttl_minutes=args.ttl)
    if not result:
        print(f"FEHLER: kein Token fuer {args.email!r} — ungueltige Adresse?")
        return 1

    base = f"http://{args.host}:{args.port}"
    url = f"{base}/login/{result['login_token']}"

    is_admin = (args.email or "").strip().lower() == (config.ADMIN_EMAIL or "").strip().lower()
    print()
    print(f"  E-Mail    : {result['email']}")
    print(f"  Account   : {'NEU angelegt' if result.get('is_new') else 'bestehend'}")
    print(f"  Admin     : {'ja' if is_admin else 'NEIN (nicht config.ADMIN_EMAIL)'}")
    print(f"  Gueltig   : {args.ttl} Minuten")
    print()
    print("  Link im Browser oeffnen, dann den Bestaetigungs-Button klicken:")
    print(f"  {url}")
    print()
    print(f"  Danach: {base}/admin")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
