"""
E-Mail-Versand fuer Gleitcast-Briefings (Stufe 2).

Nutzt stdlib smtplib gegen Infomaniak SMTP. Keine externe Dependency.

Konfiguration (config.py / .env):
  SMTP_HOST, SMTP_PORT, SMTP_USE_SSL, SMTP_USER, SMTP_PASSWORD
  SENDER_EMAIL, SENDER_NAME, BASE_URL

Dry-Run:
  Env GLEITCAST_SMTP_DRY_RUN=1  -> schreibt HTML-Preview nach /tmp (bzw. %TEMP%)
                                    statt einen echten SMTP-Call zu machen.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
import tempfile
import threading
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Any, Optional

from flask import render_template

import config

logger = logging.getLogger(__name__)

# Tier-Display-Werte (Accessibility: Farbe + Text + Symbol, WCAG-konform auf weiss)
_TIER_META = {
    "violet": {
        "label": "Legendaer",
        "color": "#6d28d9",      # 5.3:1 auf #fff
        "bg":    "#ede9fe",
        "icon":  "*",            # stilisiertes Highlight
    },
    "green": {
        "label": "Fliegbar",
        "color": "#15803d",      # 4.7:1 auf #fff
        "bg":    "#dcfce7",
        "icon":  "+",
    },
    "conditional": {
        "label": "Bedingt",
        "color": "#b45309",      # 4.6:1 auf #fff (amber-700)
        "bg":    "#fef3c7",
        "icon":  "!",
    },
    "gray": {
        "label": "Abgleiter",
        "color": "#78716c",      # 5.3:1 — selten genutzt im Mail (gefiltert)
        "bg":    "#f5f5f4",
        "icon":  "-",
    },
    "none": {
        "label": "Nichts fliegbar",
        "color": "#64748b",
        "bg":    "#f1f5f9",
        "icon":  "o",
    },
}

_TIER_RANK = {"violet": 3, "green": 2, "conditional": 1, "gray": 0, "none": -1}

_WEEKDAY_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_WEEKDAY_DE_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

# Sicherheits-Keywords fuer Safety-Header (case-insensitive).
# Reihenfolge = Schweregrad (hoechste zuerst).
_SAFETY_KEYWORDS = [
    ("thunderstorm", ["gewitter", "thunderstorm", "cape ", "blitz"], "Gewitter"),
    ("foehn",        ["föhn", "foehn", "fön"],                      "Föhn"),
    ("storm",        ["sturm", "starker wind", "orkan"],            "Sturm"),
    ("shear",        ["windscherung", "scherung", "shear"],         "Windscherung"),
]


# ----------------------------------------------------------------------
# Low-level: SMTP-Versand
# ----------------------------------------------------------------------

def _build_message(to: str, subject: str, html: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((config.SENDER_NAME, config.SENDER_EMAIL))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=_sender_domain())
    msg.set_content(text or "")              # text/plain part
    msg.add_alternative(html, subtype="html")  # text/html part
    return msg


def _sender_domain() -> str:
    addr = config.SENDER_EMAIL
    if "@" in addr:
        return addr.split("@", 1)[1]
    return "localhost"


def _dry_run_enabled() -> bool:
    return os.environ.get("GLEITCAST_SMTP_DRY_RUN", "").strip() in ("1", "true", "yes")


def _dry_run_write(to: str, subject: str, html: str) -> Path:
    tmp_dir = Path(tempfile.gettempdir()) / "gleitcast_mail_preview"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    # Windows verbietet: <>:"/\|?* und trailing . / Leerzeichen
    import re
    def _safe(s: str) -> str:
        s = s.replace("@", "_at_")
        s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
        return s.strip(". ")
    safe_to = _safe(to)
    safe_subj = _safe(subject)[:60].replace(" ", "_")
    fname = f"{safe_to}__{safe_subj}.html"
    path = tmp_dir / fname
    path.write_text(html, encoding="utf-8")
    return path


def send_email(to: str, subject: str, html: str, text: str = "") -> bool:
    """Synchron. Gibt True bei Erfolg, False bei Fehler zurueck.

    Dry-Run-Modus: Schreibt HTML-Preview in tempdir und logged Pfad.
    """
    if not to or "@" not in to:
        logger.error("send_email: ungueltige Empfaenger-Adresse '%s'", to)
        return False

    if _dry_run_enabled():
        path = _dry_run_write(to, subject, html)
        logger.info("[SMTP DRY-RUN] -> %s (subject=%r) geschrieben nach %s",
                    to, subject, path)
        return True

    host = config.SMTP_HOST
    port = config.SMTP_PORT
    user = config.SMTP_USER or config.SENDER_EMAIL
    password = config.SMTP_PASSWORD
    use_ssl = config.SMTP_USE_SSL

    if not password:
        logger.error("send_email: SMTP_PASSWORD nicht gesetzt — Mail an %s nicht gesendet", to)
        return False

    msg = _build_message(to, subject, html, text)

    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                smtp.login(user, password)
                smtp.send_message(msg)
        logger.info("SMTP send OK -> %s (subject=%r)", to, subject)
        return True
    except smtplib.SMTPAuthenticationError as e:
        logger.error("SMTP Auth fehlgeschlagen (%s@%s:%s): %s", user, host, port, e)
        return False
    except (smtplib.SMTPException, OSError) as e:
        logger.error("SMTP send fehlgeschlagen -> %s: %s", to, e)
        return False


def send_email_async(to: str, subject: str, html: str, text: str = "") -> None:
    """Fire-and-forget: startet einen Daemon-Thread fuer den SMTP-Call,
    damit Flask-Request-Handler nicht 1-5s blockieren.
    Bei Fehler wird nur geloggt (kein Retry). Fuer MVP OK.
    """
    t = threading.Thread(
        target=send_email,
        args=(to, subject, html, text),
        name=f"smtp-{to}",
        daemon=True,
    )
    t.start()


# ----------------------------------------------------------------------
# High-level: spezifische Mail-Arten
# ----------------------------------------------------------------------

def _build_urls(*, confirm_token: Optional[str] = None,
                action_token: Optional[str] = None,
                login_token: Optional[str] = None) -> dict[str, str]:
    base = config.BASE_URL.rstrip("/")
    marketing = config.MARKETING_URL.rstrip("/")
    urls = {
        "base": base,
        "marketing": marketing,
        "datenschutz": f"{marketing}/datenschutz",
        "impressum": f"{marketing}/impressum",
    }
    if confirm_token:
        urls["confirm"] = f"{base}/confirm/{confirm_token}"
    if action_token:
        urls["unsubscribe"] = f"{base}/unsubscribe/{action_token}"
        urls["account"] = f"{base}/account/{action_token}"
    if login_token:
        urls["login"] = f"{base}/login/{login_token}"
    return urls


def send_confirm_email(email: str, confirm_token: str, *, async_send: bool = True) -> bool:
    """Double-Opt-In-Mail nach /subscribe POST."""
    urls = _build_urls(confirm_token=confirm_token)
    html = render_template("email/confirm.html", email=email, urls=urls)
    text = render_template("email/confirm.txt", email=email, urls=urls)
    subject = "Bestaetige dein Gleitcast-Abo"

    if async_send:
        send_email_async(email, subject, html, text)
        return True
    return send_email(email, subject, html, text)


def send_login_email(email: str, login_token: str, *, async_send: bool = True) -> bool:
    """Magic-Link Login-Mail. 30 Minuten gueltig, One-Time."""
    urls = _build_urls(login_token=login_token)
    html = render_template("email/login.html", email=email, urls=urls)
    text = render_template("email/login.txt", email=email, urls=urls)
    subject = "Dein Gleitcast Login-Link"
    if async_send:
        send_email_async(email, subject, html, text)
        return True
    return send_email(email, subject, html, text)


def send_welcome_email(email: str, action_token: str, regions: list[str],
                       skill_level: str = "standard", *, async_send: bool = True) -> bool:
    """Willkommens-Mail direkt nach erfolgreichem /confirm."""
    urls = _build_urls(action_token=action_token)
    html = render_template(
        "email/welcome.html",
        email=email, urls=urls, regions=regions, skill_level=skill_level,
    )
    text = render_template(
        "email/welcome.txt",
        email=email, urls=urls, regions=regions, skill_level=skill_level,
    )
    subject = "Willkommen bei Gleitcast"

    if async_send:
        send_email_async(email, subject, html, text)
        return True
    return send_email(email, subject, html, text)


# ======================================================================
# BRIEFING-MAIL (Stufe 3): filtern, aggregieren, senden
# ======================================================================

def _derive_day_tier(my_spots: list[dict]) -> str:
    """Tages-Gesamt-Tier aus den Subscriber-Spots ableiten.
    Reihenfolge: violet (>=1 Spot violet+safe) > green (>=1 Spot green+safe)
    > conditional (>=1 Spot is_conditional) > none (leer).
    """
    if not my_spots:
        return "none"
    has_violet = any(s.get("fly_status") == "violet" and not s.get("is_conditional") for s in my_spots)
    if has_violet:
        return "violet"
    has_green = any(s.get("fly_status") == "green" and not s.get("is_conditional") for s in my_spots)
    if has_green:
        return "green"
    return "conditional"


def _spot_tier(spot: dict) -> str:
    """Tier fuer einen einzelnen Spot. Bronze (gray) ist bereits aus briefing_data gefiltert."""
    if spot.get("is_conditional"):
        return "conditional"
    fs = spot.get("fly_status", "")
    if fs == "violet":
        return "violet"
    if fs == "green":
        return "green"
    return "gray"


def _format_window(best_window: str) -> str:
    """Normalisiert best_window fuer die Mail-Anzeige."""
    if not best_window:
        return ""
    # Manchmal ISO-Zeiten, manchmal schon "11:00-15:00". Passthrough, trim.
    return str(best_window).strip()


def _extract_safety_warnings(days_with_all_my_spots: list) -> list[dict]:
    """Scannt alle Subscriber-Spots aller Tage nach Sicherheits-Keywords und
    baut pro Kategorie ein Warning-Objekt.

    Args:
      days_with_all_my_spots: Liste von (day_label_dict, list_of_my_spots)

    Returns:
      [{category, label, days_short: ['Sa','So']}] — sortiert nach Schweregrad.
    """
    seen = {}  # category -> {"label": ..., "days_short": set}

    for day_label, my_spots in days_with_all_my_spots:
        day_short = day_label.get("short", "") if isinstance(day_label, dict) else ""
        for spot in my_spots:
            text_parts = [
                spot.get("safety_feedback") or "",
                spot.get("conditional_reason") or "",
                spot.get("recommendation") or "",
            ]
            haystack = " ".join(text_parts).lower()
            if not haystack.strip():
                continue
            for cat, keywords, label in _SAFETY_KEYWORDS:
                if any(kw in haystack for kw in keywords):
                    entry = seen.setdefault(cat, {"category": cat, "label": label,
                                                  "days_short": set()})
                    if day_short:
                        entry["days_short"].add(day_short)

    # Reihenfolge nach Schweregrad (in _SAFETY_KEYWORDS definiert)
    order = [cat for cat, _, _ in _SAFETY_KEYWORDS]
    result = []
    for cat in order:
        if cat not in seen:
            continue
        e = seen[cat]
        result.append({
            "category": e["category"],
            "label":    e["label"],
            "days_short": sorted(
                e["days_short"],
                key=lambda d: _WEEKDAY_DE.index(d) if d in _WEEKDAY_DE else 99,
            ),
        })
    return result


def _build_region_matrix(days_out: list[dict], subscriber_regions: set) -> list[dict]:
    """Region x Tag Heatmap.

    Pro Subscriber-Region: fuer jeden Tag besten Tier + Rating bestimmen
    (ueber ALLE my_spots des Tages, nicht nur Top-3).
    Leere Tage kriegen tier='none'. Regionen ohne einen einzigen fliegbaren
    Tag werden ausgefiltert. Sortiert nach best_rating descending.

    Args:
      days_out: die bereits aufbereiteten Day-Dicts mit my_spots_all
      subscriber_regions: Menge der abonnierten region_ids
    """
    # region_id -> {name, days: [{tier, rating} per day], best_rating}
    matrix = {}
    n_days = len(days_out)

    for day_idx, day in enumerate(days_out):
        for spot in day.get("_my_spots_all", []):
            rid = spot.get("region_id")
            if not rid or rid not in subscriber_regions:
                continue
            rname = spot.get("region_name") or rid

            tier = _spot_tier(spot)
            rating = float(spot.get("rating") or 0)

            entry = matrix.setdefault(rid, {
                "region_id": rid,
                "region_name": rname,
                "days": [{"tier": "none", "rating": 0.0, "spot_count": 0}
                         for _ in range(n_days)],
                "best_rating": 0.0,
            })
            cell = entry["days"][day_idx]
            # Bester Tier gewinnt, bei Gleichstand besseres Rating
            if (_TIER_RANK.get(tier, -1) > _TIER_RANK.get(cell["tier"], -1)
                    or (tier == cell["tier"] and rating > cell["rating"])):
                cell["tier"] = tier
                cell["rating"] = rating
            cell["spot_count"] += 1
            entry["best_rating"] = max(entry["best_rating"], rating)

    # Meta pro Zelle einhaengen + Sortierung
    out = []
    for entry in matrix.values():
        for cell in entry["days"]:
            meta = _TIER_META.get(cell["tier"], _TIER_META["none"])
            cell["tier_color"] = meta["color"]
            cell["tier_bg"]    = meta["bg"]
            cell["tier_label"] = meta["label"]
            cell["rating_display"] = f"{cell['rating']:.1f}" if cell["rating"] > 0 else ""
        out.append(entry)

    out.sort(key=lambda e: e["best_rating"], reverse=True)
    return out


def _group_spots_by_region(shown_spots: list[dict],
                           region_ratings_by_id: dict[str, float],
                           *, max_regions: int = 3,
                           max_spots_per_region: int = 3) -> list[dict]:
    """Gruppiert shown_spots nach region_id, kappt auf top max_regions × max_spots_per_region.

    region_tier = bester Spot-Tier der Region (Rang via _TIER_RANK).
    region_rating = aus region_ratings_by_id (briefing_data.top_regions),
                    Fallback Max-Rating der Spots in der Region.
    Spots pro Region nach rating DESC, Regionen nach region_rating DESC.
    """
    groups: dict[str, dict] = {}
    for s in shown_spots:
        rid = s.get("region_id") or ""
        if rid not in groups:
            groups[rid] = {
                "region_id":   rid,
                "region_name": s.get("region_name") or rid,
                "spots":       [],
            }
        groups[rid]["spots"].append(s)

    out = []
    for rid, g in groups.items():
        spots = sorted(g["spots"], key=lambda s: float(s.get("rating") or 0), reverse=True)
        spots = spots[:max_spots_per_region]
        g["spots"] = spots
        region_tier = max((sp.get("tier", "gray") for sp in spots),
                          key=lambda t: _TIER_RANK.get(t, -1))
        meta = _TIER_META.get(region_tier, _TIER_META["gray"])
        rating = region_ratings_by_id.get(rid)
        if rating is None or rating <= 0:
            rating = max((float(sp.get("rating") or 0) for sp in spots), default=0.0)
        g["region_rating"] = float(rating)
        g["region_rating_display"] = f"{float(rating):.1f}"
        g["region_tier"] = region_tier
        g["tier_color"] = meta["color"]
        g["tier_label"] = meta["label"]
        out.append(g)

    out.sort(key=lambda x: x["region_rating"], reverse=True)
    return out[:max_regions]


def _aggregate_windows(windows: list[str]) -> str:
    """Min-Start → Max-End ueber mehrere 'HH:MM-HH:MM' Strings."""
    starts, ends = [], []
    for w in windows:
        if not w or "-" not in w:
            continue
        try:
            s, e = w.split("-", 1)
            s, e = s.strip(), e.strip()
            if ":" in s and ":" in e:
                starts.append(s)
                ends.append(e)
        except Exception:
            continue
    if not starts:
        return ""
    return f"{min(starts)}-{max(ends)}"


def _day_fly_summary(my_spots: list[dict], day_tier: str) -> str:
    """Ein-Satz-Fliegbarkeit fuer Day-Header. Aggregiert peak climb + Fenster."""
    if not my_spots or day_tier == "none":
        return ""
    climbs = [float(s.get("peak_climb_rate") or 0) for s in my_spots]
    peak = max((c for c in climbs if c > 0), default=0.0)
    span = _aggregate_windows([s.get("best_window") for s in my_spots])

    label_map = {
        "violet": "Top-Bedingungen",
        "green": "Solide Thermik",
        "conditional": "Eingeschraenkt fliegbar",
    }
    bits = [label_map.get(day_tier, "")]
    if peak > 0:
        bits.append(f"Peak {peak:.1f} m/s")
    if span:
        bits.append(f"Fenster {span}")
    text = ", ".join(b for b in bits if b)
    return text + "." if text else ""


def _day_safety_summary(my_spots: list[dict]) -> str:
    """Ein-Satz-Sicherheit fuer Day-Header. Nutzt _SAFETY_KEYWORDS.

    Returns 'Stabil, keine Warnungen.' wenn nichts gefunden.
    """
    if not my_spots:
        return ""
    seen_labels: list[str] = []
    for s in my_spots:
        haystack = " ".join([
            s.get("safety_feedback") or "",
            s.get("conditional_reason") or "",
            s.get("recommendation") or "",
        ]).lower()
        if not haystack.strip():
            continue
        for cat, keywords, label in _SAFETY_KEYWORDS:
            if any(kw in haystack for kw in keywords) and label not in seen_labels:
                seen_labels.append(label)
    if seen_labels:
        return f"Vorsicht: {', '.join(seen_labels[:2])}."
    return "Stabil, keine Warnungen."


def _date_label(date_str: str) -> dict:
    """Label fuer Tages-Kopfzeile: {'short': 'Mo', 'long': 'Montag, 18.04.', 'weekday': 'Mo'}."""
    try:
        dt = datetime.fromisoformat(date_str)
    except Exception:
        return {"short": date_str, "long": date_str, "weekday": ""}
    wd_idx = dt.weekday()
    short = _WEEKDAY_DE[wd_idx]
    long_ = f"{_WEEKDAY_DE_LONG[wd_idx]}, {dt.strftime('%d.%m.')}"
    return {"short": short, "long": long_, "weekday": short, "date": date_str}


def build_briefing_context(subscriber: dict, briefing_data: dict,
                           *, top_n_regions_per_day: int = 3,
                           top_n_spots_per_region: int = 3) -> dict:
    """
    Filtert briefing_data auf Subscriber-Regionen und baut den Template-Kontext
    fuer templates/email/briefing.html.

    Args:
      subscriber: {id, email, regions, skill_level, action_token}
      briefing_data: Output von GleitcastEngine.build_briefing_data()
      top_n_regions_per_day: Maximale Anzahl Regionen pro Tag (Default 3)
      top_n_spots_per_region: Maximale Anzahl Spots pro Region (Default 3)

    Returns:
      dict fuer Jinja2 mit days[], verdict{}, urls{}, tier_meta{} etc.
    """
    subscriber_regions = set(subscriber.get("regions") or [])
    action_token = subscriber.get("action_token") or ""

    # Subscriber-Filter: Tier-Set + Min-Rating. Default = alle Tiers (kein Filter).
    # Gilt fuer die Day-Details (welche Spots im Briefing gelistet werden).
    # Region-Matrix + Safety-Scan bleiben unfiltered (informativer Charakter).
    allowed_tiers = set(subscriber.get("min_tier_set") or ("violet", "green", "conditional", "gray"))
    try:
        min_rating = float(subscriber.get("min_rating") or 0.0)
    except (TypeError, ValueError):
        min_rating = 0.0

    def _passes_filter(spot: dict) -> bool:
        if _spot_tier(spot) not in allowed_tiers:
            return False
        if min_rating > 0:
            try:
                if float(spot.get("rating", 0) or 0) < min_rating:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    days_out = []
    days_with_all_my_spots = []  # fuer Safety-Header Scan (ALLE Spots, nicht nur Top-9)
    for day in briefing_data.get("days", []):
        date_str = day.get("date", "")
        all_spots = day.get("top_spots", []) or []
        my_spots_unfiltered = [s for s in all_spots if s.get("region_id") in subscriber_regions]
        my_spots = [s for s in my_spots_unfiltered if _passes_filter(s)]
        day_label_dict = _date_label(date_str)
        # Safety-Scan auf UNFILTERED (Warnungen sind unabhaengig von Tier/Rating wichtig)
        days_with_all_my_spots.append((day_label_dict, my_spots_unfiltered))

        # Spot-Pool fuer Gruppierung: alle my_spots, gekappt erst innerhalb der Gruppen
        shown = []
        for s in my_spots:
            tier = _spot_tier(s)
            meta = _TIER_META.get(tier, _TIER_META["gray"])
            shown.append({
                **s,
                "tier": tier,
                "tier_label": meta["label"],
                "tier_color": meta["color"],
                "tier_bg":    meta["bg"],
                "tier_icon":  meta["icon"],
                "window":     _format_window(s.get("best_window", "")),
                "rating_display": f"{float(s.get('rating', 0) or 0):.1f}",
            })

        day_tier = _derive_day_tier(my_spots)
        meta = _TIER_META[day_tier]

        # Region-Rating-Lookup aus briefing_data.top_regions, Fallback Max-Spot-Rating
        day_top_regions = day.get("top_regions") or []
        region_rating_lookup = {r.get("region_id"): float(r.get("rating") or 0)
                                for r in day_top_regions if r.get("region_id")}
        region_groups = _group_spots_by_region(
            shown, region_rating_lookup,
            max_regions=top_n_regions_per_day,
            max_spots_per_region=top_n_spots_per_region,
        )

        # Day-Rating = Max ueber gezeigte Spots; Day-Summaries
        displayed_spots = [sp for g in region_groups for sp in g["spots"]]
        day_rating = max((float(sp.get("rating") or 0) for sp in displayed_spots),
                         default=0.0)
        fly_summary = _day_fly_summary(my_spots, day_tier)
        safety_summary = _day_safety_summary(my_spots)

        days_out.append({
            "date": date_str,
            "label": day_label_dict,
            "tier": day_tier,
            "tier_label": meta["label"],
            "tier_color": meta["color"],
            "tier_bg":    meta["bg"],
            "tier_icon":  meta["icon"],
            "shown_spots": displayed_spots,
            "region_groups": region_groups,
            "day_rating": day_rating,
            "day_rating_display": f"{day_rating:.1f}" if day_rating > 0 else "",
            "fly_summary": fly_summary,
            "safety_summary": safety_summary,
            "more_count":  max(0, len(my_spots) - len(displayed_spots)),
            # Intern fuer Heatmap-Aggregation: UNFILTERED, damit das Region-x-Tag-Raster
            # immer alle abonnierten Regionen abbildet (auch wenn user 'gray' gefiltert hat).
            "_my_spots_all": my_spots_unfiltered,
        })

    # Verdict = bester Tag (Tier-Rank, dann Rating des Top-Spots)
    def _day_score(d):
        top_rating = d["shown_spots"][0]["rating"] if d["shown_spots"] else 0.0
        return (_TIER_RANK.get(d["tier"], -1), float(top_rating or 0))

    best_day = max(days_out, key=_day_score, default=None)
    best_day_idx = days_out.index(best_day) if best_day else 0

    # Verdict nur zeigen, wenn bester Tag wenigstens 'conditional' ist
    verdict = None
    if best_day and best_day["tier"] != "none":
        top_spot = best_day["shown_spots"][0] if best_day["shown_spots"] else None
        verdict = {
            "day": best_day,
            "spot": top_spot,
            "headline": _verdict_headline(best_day, top_spot),
        }

    # Deep-Link ins Dashboard
    regions_csv = ",".join(sorted(subscriber_regions))
    base = config.BASE_URL.rstrip("/")
    deep_link = f"{base}/briefing?regions={regions_csv}&day={best_day_idx}"

    # Action-URLs
    marketing = config.MARKETING_URL.rstrip("/")
    urls = {
        "base": base,
        "dashboard":        deep_link,
        "feedback_correct": f"{base}/feedback/{action_token}/correct",
        "feedback_wrong":   f"{base}/feedback/{action_token}/wrong",
        "unsubscribe":      f"{base}/unsubscribe/{action_token}",
        "account":          f"{base}/account/{action_token}",
        "datenschutz":      f"{marketing}/datenschutz",
        "impressum":        f"{marketing}/impressum",
    }

    today = datetime.now()
    warnings = _extract_safety_warnings(days_with_all_my_spots)

    # Heatmap-Matrix der Subscriber-Regionen
    region_matrix = _build_region_matrix(days_out, subscriber_regions)

    # Kurzlabels fuer Heatmap-Kopfzeile (Mo/Di/Mi/...)
    day_short_labels = [d["label"].get("short", "") for d in days_out]

    # Deep-Links pro Kachel vorberechnen (damit Template clean bleibt)
    # Pattern: /briefing?regions=<id>&day=<N>  — der Frontend-Parser filtert
    # dann den Dashboard-View auf diese Region und waehlt den Tag-Tab.
    for r in region_matrix:
        r["url"] = f"{base}/briefing?regions={r['region_id']}"
        for day_idx, cell in enumerate(r["days"]):
            cell["day_idx"] = day_idx
            if cell["tier"] != "none":
                cell["url"] = f"{base}/briefing?regions={r['region_id']}&day={day_idx}"
            else:
                cell["url"] = None

    # Spot-Links enthalten zusaetzlich &spot=<name> — das Frontend filtert dann
    # auf genau diesen einen Spot (Focus-Modus mit "Alle anzeigen"-Clear).
    from urllib.parse import quote
    for day_idx, day in enumerate(days_out):
        for s in day["shown_spots"]:
            spot_q = quote(s.get("spot") or "", safe="")
            s["url"] = (f"{base}/briefing?regions={s['region_id']}"
                        f"&day={day_idx}&spot={spot_q}")

    # WhatsApp-Share: kurzer Text + Deep-Link. wa.me/?text=<URL-encoded>
    # Der Deep-Link enthaelt schon die Subscriber-Regionen + besten Tag,
    # Empfaenger landet gefiltert. Rich-Preview kommt per OG-Tags auf /briefing.
    if verdict:
        share_msg = f"{verdict['headline']} — Gleitcast-Briefing KW{today.isocalendar().week}:"
    else:
        share_msg = f"Mein Gleitcast-Briefing für KW{today.isocalendar().week}:"
    share_payload = f"{share_msg}\n{deep_link}"
    share = {
        "url":          deep_link,
        "text":         share_msg,
        "whatsapp":     f"https://wa.me/?text={quote(share_payload, safe='')}",
        "telegram":     f"https://t.me/share/url?url={quote(deep_link, safe='')}&text={quote(share_msg, safe='')}",
        "mailto":       f"mailto:?subject={quote('Gleitcast Briefing KW' + str(today.isocalendar().week))}&body={quote(share_payload, safe='')}",
    }

    return {
        "subscriber_email": subscriber.get("email", ""),
        "days": days_out,
        "verdict": verdict,
        "best_day_idx": best_day_idx,
        "urls": urls,
        "share": share,
        "warnings": warnings,
        "briefing_date": today.strftime("%d.%m.%Y"),
        "briefing_weekday": _WEEKDAY_DE_LONG[today.weekday()],
        "kw": today.isocalendar().week,
        "region_matrix": region_matrix,
        "day_short_labels": day_short_labels,
        "tier_meta": _TIER_META,
    }


def _verdict_headline(day: dict, spot: Optional[dict]) -> str:
    """Ein-Satz-Headline fuer den Verdict-Block."""
    weekday_long = _WEEKDAY_DE_LONG[datetime.fromisoformat(day["date"]).weekday()]
    if day["tier"] == "violet":
        if spot:
            return f"{weekday_long} ist dein Tag — {spot['spot']} legendaer"
        return f"{weekday_long} wird legendaer"
    if day["tier"] == "green":
        if spot:
            return f"Bester Tag: {weekday_long} — {spot['spot']} fliegbar"
        return f"{weekday_long} ist fliegbar"
    if day["tier"] == "conditional":
        if spot:
            return f"{weekday_long} bedingt — {spot['spot']} nur mit Vorsicht"
        return f"{weekday_long} bedingt fliegbar"
    return "Diese Woche nichts in deinen Regionen"


def send_briefing_email(subscriber: dict, briefing_data: dict,
                        *, async_send: bool = True) -> bool:
    """Rendert und versendet das Haupt-Briefing fuer einen Subscriber."""
    ctx = build_briefing_context(subscriber, briefing_data)
    html = render_template("email/briefing.html", **ctx)
    text = render_template("email/briefing.txt", **ctx)

    # Betreff dynamisch: wenn bester Tag legendaer -> markant, sonst sachlich
    verdict = ctx.get("verdict")
    today = datetime.now()
    kw = today.isocalendar().week
    if verdict and verdict["day"]["tier"] == "violet":
        subject = f"Gleitcast KW{kw}: {verdict['headline']}"
    elif verdict and verdict["day"]["tier"] == "green":
        subject = f"Gleitcast KW{kw}: {verdict['headline']}"
    elif verdict:
        subject = f"Gleitcast KW{kw}: Bedingte Woche"
    else:
        subject = f"Gleitcast KW{kw}: Diese Woche nichts in deinen Regionen"

    to = subscriber.get("email")
    if not to:
        logger.error("send_briefing_email: kein email-Feld im Subscriber-Dict")
        return False

    if async_send:
        send_email_async(to, subject, html, text)
        return True
    return send_email(to, subject, html, text)


# ======================================================================
# ACCURACY-MAIL (Stufe 6): Monatsrueckblick mit Vorhersage-Genauigkeit
# ======================================================================

_MONTH_DE = ["", "Januar", "Februar", "Maerz", "April", "Mai", "Juni",
             "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _accuracy_framing(pct: int) -> tuple[str, str]:
    """Liefert (hex_color, message) passend zum Accuracy-Wert."""
    if pct >= 80:
        return ("#15803d",
                "Sehr gute Trefferquote! Die Modell-Kombination scheint fuer deine "
                "Regionen gut kalibriert zu sein. Danke fuer dein Feedback — "
                "das hilft uns, die Prognose weiter zu schaerfen.")
    if pct >= 60:
        return ("#b45309",
                "Solide Trefferquote. Es gibt noch Luft nach oben — oft liegen "
                "Abweichungen an lokalen Effekten, die selbst die besten Modelle "
                "nicht vollstaendig erfassen. Dein Feedback hilft uns dabei.")
    return ("#b91c1c",
            "Die Vorhersage hat dir letzten Monat oft nicht gepasst. Das tut uns leid. "
            "Vielleicht sind die gewaehlten Regionen fuer dein Home-Terrain zu grob — "
            "du kannst sie in den Einstellungen anpassen.")


def send_accuracy_email(subscriber: dict, stats: dict, *, async_send: bool = True) -> bool:
    """Rendert und versendet die Monats-Accuracy-Mail."""
    if stats.get("total", 0) < 3 or stats.get("accuracy_pct") is None:
        logger.info("send_accuracy_email: zu wenig Feedback (%s) -> skip %s",
                    stats.get("total"), subscriber.get("email"))
        return False

    color, message = _accuracy_framing(stats["accuracy_pct"])
    last_month = datetime.now().replace(day=1) - timedelta(seconds=1)
    month_label = f"{_MONTH_DE[last_month.month]} {last_month.year}"

    urls = _build_urls(action_token=subscriber.get("action_token", ""))
    ctx = {
        "stats": stats,
        "color": color,
        "message": message,
        "month_label": month_label,
        "urls": urls,
    }
    html = render_template("email/accuracy.html", **ctx)
    text = render_template("email/accuracy.txt", **ctx)

    subject = f"Gleitcast {month_label}: Deine Vorhersage zu {stats['accuracy_pct']}% korrekt"
    to = subscriber.get("email")
    if not to:
        return False
    if async_send:
        send_email_async(to, subject, html, text)
        return True
    return send_email(to, subject, html, text)


# ======================================================================
# CLI: python email_service.py --preview <email>
# ======================================================================

def _cli_preview(email: str, wet_run: bool = False) -> int:
    """Laedt Engine, baut briefing_data, rendert + versendet/speichert Preview.
    Return-Code fuer sys.exit().
    """
    import sys
    from subscriber import get_manager_from_env

    # Subscriber nachschlagen
    sub_mgr = get_manager_from_env()
    if sub_mgr is None:
        print("FEHLER: SubscriberManager konnte nicht initialisiert werden.", file=sys.stderr)
        return 2

    subscriber = sub_mgr.get_by_email(email)
    if not subscriber:
        print(f"FEHLER: Subscriber mit E-Mail '{email}' nicht gefunden.", file=sys.stderr)
        return 3
    print(f"[OK] Subscriber: #{subscriber['id']} {subscriber['email']} "
          f"({subscriber['status']}), Regionen: {subscriber['regions']}")

    # Engine + briefing_data
    from chat_engine import GleitcastEngine
    eng = GleitcastEngine()
    try:
        eng.load_weather_from_cache()
    except Exception as e:
        print(f"WARN: load_weather_from_cache: {e}", file=sys.stderr)

    briefing_data = eng.build_briefing_data()
    print(f"[OK] briefing_data: {len(briefing_data.get('days', []))} Tage")

    # Render + Send (in Dry-Run standardmaessig)
    if not wet_run:
        os.environ["GLEITCAST_SMTP_DRY_RUN"] = "1"

    # Flask app_context fuer render_template
    from web import app as flask_app
    with flask_app.app_context(), flask_app.test_request_context():
        ok = send_briefing_email(subscriber, briefing_data, async_send=False)
    print(f"[{'OK' if ok else 'FEHLER'}] send_briefing_email -> {subscriber['email']}")
    if not wet_run:
        preview_dir = Path(tempfile.gettempdir()) / "gleitcast_mail_preview"
        print(f"Preview-HTML liegt in: {preview_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    ap = argparse.ArgumentParser(description="Gleitcast Mail CLI")
    ap.add_argument("--preview", metavar="EMAIL",
                    help="Rendert das Briefing fuer den Subscriber mit dieser E-Mail "
                         "(Dry-Run: schreibt HTML nach tempdir).")
    ap.add_argument("--send", action="store_true",
                    help="Mit --preview: tatsaechlich per SMTP versenden statt Dry-Run.")
    args = ap.parse_args()

    if args.preview:
        sys.exit(_cli_preview(args.preview, wet_run=args.send))
    ap.print_help()
    sys.exit(0)
