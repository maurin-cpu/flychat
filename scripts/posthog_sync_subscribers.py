"""
Spiegelt alle Abonnenten einmalig (oder bei Bedarf erneut) als Personen nach
PostHog — mit Status, Regionen-Anzahl, letztem Versand, letzter Oeffnung usw.
Laufend werden die Werte danach bei jedem Versand/Oeffnen/Klick aktualisiert
(mail_tracking.py). Idempotent, kann beliebig oft laufen.

    python scripts/posthog_sync_subscribers.py [--dry-run]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import mail_tracking  # noqa: E402
from subscriber import get_manager_from_env  # noqa: E402


def main() -> int:
    dry = "--dry-run" in sys.argv
    if not config.POSTHOG_KEY and not dry:
        print("POSTHOG_KEY nicht gesetzt — nichts zu tun")
        return 1
    mgr = get_manager_from_env()
    subs = mgr.list_for_tracking_sync()
    for sub in subs:
        props = mail_tracking.subscriber_person_props(sub)
        if dry:
            print(sub["email"], props)
            continue
        mail_tracking.posthog_capture(sub["email"], "$set", {}, props, wait=True)
    print(f"{len(subs)} Abonnenten {'gelistet' if dry else 'an PostHog gemeldet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
