"""
mail_tracking.py — Oeffnungs- und Klick-Messung fuer das Briefing-Mail.

Bausteine
  * signierte URLs (HMAC ueber Subscriber-ID, kein DB-Token noetig):
      /t/o/<sid>/<sig>.gif?d=YYYY-MM-DD          Oeffnungs-Pixel (1x1 GIF)
      /t/c/<sid>/<sig>?d=YYYY-MM-DD&u=<ziel>     Klick-Weiterleitung
  * Client-Einstufung beim Pixel-Aufruf: Apple Mail laedt Bilder ueber
    seinen Privacy-Proxy VOR dem Lesen -> "geoeffnet" ist dort nicht belegt
    (valid=False). Gmail-/Yahoo-Proxy und normale Browser-Kennungen gelten
    als echte Oeffnung. Outlook blockiert Bilder standardmaessig; kommt ein
    Aufruf, hat der Nutzer sie freigeschaltet -> echt.
  * Server-seitiger PostHog-Versand (unabhaengig vom Browser-Consent, weil
    kein Browser-Tracking): Events briefing_sent/opened/clicked plus
    Personen-Eigenschaften (briefing_last_opened_at, ..._valid, ...).

Es werden keine IP-Adressen und keine rohen User-Agents gespeichert, nur die
Einstufung (client) und ob sie als Oeffnung zaehlt (valid).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

import config

logger = logging.getLogger(__name__)

# 1x1 transparentes GIF
PIXEL_GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")

_SECRET = os.environ.get("FLASK_SECRET_KEY", "wingcast-dev-key").encode("utf-8")


# ----------------------------------------------------------------------
# Signierte URLs
# ----------------------------------------------------------------------
def sign(subscriber_id: int) -> str:
    msg = f"mailtrack:{int(subscriber_id)}".encode("utf-8")
    return hmac.new(_SECRET, msg, hashlib.sha256).hexdigest()[:20]


def verify(subscriber_id: int, sig: str) -> bool:
    try:
        return hmac.compare_digest(sign(int(subscriber_id)), str(sig or ""))
    except (TypeError, ValueError):
        return False


def pixel_url(base: str, subscriber_id: int, briefing_date: str) -> str:
    return f"{base.rstrip('/')}/t/o/{int(subscriber_id)}/{sign(subscriber_id)}.gif?d={briefing_date}"


def click_url(base: str, subscriber_id: int, briefing_date: str, target: str) -> str:
    if not target:
        return target
    q = urllib.parse.urlencode({"d": briefing_date, "u": target})
    return f"{base.rstrip('/')}/t/c/{int(subscriber_id)}/{sign(subscriber_id)}?{q}"


def is_allowed_target(url: str) -> bool:
    """Nur eigene Domains als Weiterleitungsziel (kein offener Redirect)."""
    if not url:
        return False
    allowed = [config.BASE_URL.rstrip("/"), config.MARKETING_URL.rstrip("/")]
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    for a in allowed:
        ap = urllib.parse.urlsplit(a)
        if ap.netloc and p.netloc.lower() == ap.netloc.lower():
            return True
    # lokale Entwicklung
    return p.hostname in ("localhost", "127.0.0.1")


# ----------------------------------------------------------------------
# Client-Einstufung
# ----------------------------------------------------------------------
# Apple Mail (Mac/iOS) und Apples Privacy-Proxy melden sich als reines
# AppleWebKit ohne Safari-/Version-Token. Kein anderer verbreiteter Client
# tut das.
_APPLE_RE = re.compile(r"AppleWebKit/[\d.]+ \(KHTML, like Gecko\)\s*$")


def classify_client(user_agent: str, ip: str = "") -> tuple[str, bool]:
    """-> (client, valid). valid=False heisst: Aufruf belegt KEINE Oeffnung."""
    ua = (user_agent or "").strip()
    ip = (ip or "").strip()
    if "GoogleImageProxy" in ua:
        return "gmail", True
    if "YahooMailProxy" in ua:
        return "yahoo", True
    if ip.startswith("17.") or _APPLE_RE.search(ua) or "com.apple.mail" in ua.lower():
        return "apple_mail", False
    if "Outlook" in ua or "MSOffice" in ua or "Microsoft Office" in ua:
        return "outlook", True
    if "Thunderbird" in ua:
        return "thunderbird", True
    if not ua:
        return "unknown", False
    return "browser", True


# ----------------------------------------------------------------------
# PostHog (server-seitig)
# ----------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def posthog_capture(distinct_id: str, event: str, properties: Optional[dict] = None,
                    set_props: Optional[dict] = None, *, wait: bool = False) -> None:
    """Schickt ein Event an PostHog. Standard: im Hintergrund-Thread, damit
    der Pixel-/Redirect-Request nicht auf PostHog wartet."""
    key = getattr(config, "POSTHOG_KEY", "")
    if not key or not distinct_id:
        return
    props = dict(properties or {})
    props.setdefault("app", "server")
    props.setdefault("$lib", "wingcast-server")
    if set_props:
        props["$set"] = dict(set_props)
    payload = json.dumps({
        "api_key": key,
        "event": event,
        "distinct_id": distinct_id,
        "properties": props,
        "timestamp": _now_iso(),
    }).encode("utf-8")
    url = f"{config.POSTHOG_HOST.rstrip('/')}/capture/"

    def _send():
        try:
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                r.read()
        except Exception as e:  # noqa: BLE001 — Tracking darf nie stoeren
            logger.warning("posthog_capture %s failed: %s", event, e)

    if wait:
        _send()
    else:
        threading.Thread(target=_send, daemon=True).start()


def subscriber_person_props(sub: dict) -> dict:
    """Personen-Eigenschaften eines Abonnenten fuer PostHog."""
    regions = sub.get("regions") or []
    return {
        "email": sub.get("email"),
        "subscriber_id": sub.get("id"),
        "subscriber_status": sub.get("status"),
        "subscriber_since": sub.get("created_at"),
        "skill_level": sub.get("skill_level"),
        "regions_count": len(regions),
        "briefing_last_sent_at": sub.get("last_sent_at"),
        "app_last_seen_at": sub.get("last_seen_at"),
        "briefing_last_opened_at": sub.get("last_open_at"),
        "briefing_last_open_client": sub.get("last_open_client"),
        "briefing_last_open_valid": (bool(sub.get("last_open_valid"))
                                     if sub.get("last_open_at") else None),
        "briefing_last_valid_open_at": sub.get("last_valid_open_at"),
        "briefing_last_clicked_at": sub.get("last_click_at"),
    }


# ----------------------------------------------------------------------
# Ereignisse verbuchen (DB + PostHog)
# ----------------------------------------------------------------------
def record_open(mgr, subscriber_id: int, briefing_date: str,
                user_agent: str, ip: str) -> None:
    client, valid = classify_client(user_agent, ip)
    sub = mgr.record_email_event(subscriber_id, "open", briefing_date, client, valid)
    if not sub:
        return
    now = _now_iso()
    set_props = {
        "briefing_last_opened_at": now,
        "briefing_last_open_client": client,
        "briefing_last_open_valid": valid,
    }
    if valid:
        set_props["briefing_last_valid_open_at"] = now
    posthog_capture(sub["email"], "briefing_opened",
                    {"briefing_date": briefing_date, "client": client, "valid": valid},
                    set_props)


def record_click(mgr, subscriber_id: int, briefing_date: str, target: str) -> None:
    sub = mgr.record_email_event(subscriber_id, "click", briefing_date, "click", True)
    if not sub:
        return
    now = _now_iso()
    # Ein Klick belegt die Oeffnung sicher — auch wenn das Pixel vorher als
    # Apple-Vorabruf eingestuft wurde.
    posthog_capture(sub["email"], "briefing_clicked",
                    {"briefing_date": briefing_date, "target": target},
                    {"briefing_last_clicked_at": now,
                     "briefing_last_valid_open_at": now,
                     "briefing_last_open_valid": True})


def record_sent(sub: dict, briefing_date: str) -> None:
    # Der Versand kennt nur die Versand-Spalten (list_active), nicht
    # last_open_at & Co. Ein $set mit None wuerde in PostHog die letzte
    # Oeffnung jeden Morgen auf null zuruecksetzen (so geschehen 23./24.09.)
    # — deshalb nur Werte setzen, die wirklich vorliegen.
    props = {k: v for k, v in subscriber_person_props(sub).items() if v is not None}
    posthog_capture(sub.get("email", ""), "briefing_sent",
                    {"briefing_date": briefing_date},
                    {**props, "briefing_last_sent_at": _now_iso()})
