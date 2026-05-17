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

# Tier-Display-Werte (Accessibility: Farbe + Text + Symbol, WCAG-konform auf weiss).
# Phase 2 RATING_CONCEPT v1.3: User-Labels konsistent zur App-Sprache —
# Sterne-zentriert in den Mails, Tier-Sprache nur intern.
_TIER_META = {
    "violet": {
        "label": "Top-Tag",
        "color": "#6d28d9",      # 5.3:1 auf #fff
        "bg":    "#ede9fe",
        "icon":  "*",
    },
    "green": {
        "label": "Sicher",
        "color": "#15803d",      # 4.7:1 auf #fff
        "bg":    "#dcfce7",
        "icon":  "+",
    },
    "conditional": {
        "label": "Vorsicht",
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
        "label": "Nicht fliegbar",
        "color": "#64748b",
        "bg":    "#f1f5f9",
        "icon":  "o",
    },
}

_TIER_RANK = {"violet": 3, "green": 2, "conditional": 1, "gray": 0, "none": -1}


def _stars_for_spot(spot: dict) -> int:
    """Mappt experience_rating (1-5) auf 0-5 Sterne fuer Mail-Bubbles."""
    r = _rating_for_spot(spot)
    if r <= 0: return 0
    return min(5, r)  # 1:1 mapping in 1-5 scale


def _rating_display(spot: dict) -> str:
    """RATING_ARCHITECTURE v2.1: experience_rating 1-5 als String. Leer bei not_safe."""
    r = _rating_for_spot(spot)
    return str(r) if r > 0 else ""


def _rating_for_spot(spot: dict) -> int:
    """RATING_ARCHITECTURE v2.1: experience_rating 1-5."""
    val = spot.get("experience_rating")
    if isinstance(val, (int, float)) and 0 <= val <= 5:
        return int(val)
    # Migration-Tolerance: alte cached Werte 6 → 5 mappen
    if isinstance(val, (int, float)) and val == 6:
        return 5
    return 0


def _safety_band_for_spot(spot: dict) -> str:
    """FE-Mapping aus safety_status (RATING_ARCHITECTURE v2.0)."""
    s = spot.get("safety_status", "")
    if s == "safe":        return "green"
    if s == "conditional": return "amber"
    if s == "not_safe":    return "red"
    return "no_data"


def _stars_glyph_text(n: int) -> str:
    """5-Char Stern-Glyphe fuer Plain-Text-Mail (★★★ ··)."""
    n = max(0, min(5, int(n or 0)))
    return ("★" * n) + ("·" * (5 - n))

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


def _base_url_is_local(url: str) -> bool:
    u = (url or "").lower()
    return ("localhost" in u) or ("127.0.0.1" in u) or ("0.0.0.0" in u) or ("://[::1]" in u)


# Startup-Sanity: laute Warnung, wenn BASE_URL auf localhost zeigt. Live-Mails
# mit localhost-Links sind ein bekanntes Fehlbild (Prod-.env nicht gesetzt).
if _base_url_is_local(config.BASE_URL):
    logger.warning(
        "BASE_URL zeigt auf localhost (%r) — reale Mail-Sends werden blockiert. "
        "Setze GLEITCAST_BASE_URL=https://app.gleitcast.ch in der Prod-.env "
        "oder GLEITCAST_SMTP_DRY_RUN=1 für lokale Previews.",
        config.BASE_URL,
    )


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

    # Safety-Net fuer Prod-Misconfig: blockt nur wenn ausserhalb eines
    # HTTP-Requests (Scheduler/Cron) UND config.BASE_URL auf localhost zeigt.
    # In einem Request laufen die URLs jetzt automatisch ueber request.host_url
    # (siehe _resolve_base_url), das ist in Dev legitim auf localhost.
    if _base_url_is_local(config.BASE_URL):
        in_request = False
        try:
            from flask import has_request_context
            in_request = has_request_context()
        except Exception:
            pass
        if not in_request:
            logger.error(
                "send_email: kein Request-Kontext und BASE_URL=%r zeigt auf localhost — "
                "Mail an %s NICHT gesendet (Scheduler/Cron-Pfad). "
                "Fix: GLEITCAST_BASE_URL in Prod-.env auf https://app.gleitcast.ch setzen.",
                config.BASE_URL, to,
            )
            return False

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

def _resolve_base_url() -> str:
    """Liefert die Basis-URL fuer Mail-Links.

    Wenn wir in einem Flask-Request laufen (User triggert /subscribe oder /login):
      → nimm den aktuellen Host. So bekommt localhost-Entwicklung localhost-Links
        und Prod (app.gleitcast.ch) bekommt Prod-Links — automatisch.

    Wenn kein Request aktiv ist (Scheduler, CLI-Skript, Daily-Briefing-Job):
      → config.BASE_URL als Fallback (typischerweise gesetzt via Env-Var
        GLEITCAST_BASE_URL=https://app.gleitcast.ch).
    """
    try:
        from flask import has_request_context, request
        if has_request_context():
            host_url = (request.host_url or "").rstrip("/")
            if host_url:
                return host_url
    except Exception:
        pass
    return config.BASE_URL.rstrip("/")


def _build_urls(*, confirm_token: Optional[str] = None,
                action_token: Optional[str] = None,
                login_token: Optional[str] = None) -> dict[str, str]:
    base = _resolve_base_url()
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
    # RATING_ARCHITECTURE v2.1: tier aus experience_rating ableiten.
    has_violet = any(_rating_for_spot(s) >= 5 and not s.get("is_conditional") for s in my_spots)
    if has_violet:
        return "violet"
    has_green = any(_rating_for_spot(s) >= 3 and not s.get("is_conditional") for s in my_spots)
    if has_green:
        return "green"
    return "conditional"


def _spot_tier(spot: dict) -> str:
    """Tier fuer einen einzelnen Spot aus experience_rating (1-5)."""
    if spot.get("is_conditional"):
        return "conditional"
    r = _rating_for_spot(spot)
    if r >= 5: return "violet"
    if r >= 3: return "green"
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


def _week_summary_prose(days_out: list[dict], warnings: list[dict]) -> str:
    """1-2 Saetze zur Wochen-Gesamtsituation.

    Beispiele:
      "Mittwoch ist dein Tag der Woche. Freitag meiden wegen Foehn."
      "Drei starke Tage: Mi, Do, Sa. Sonst bedingt."
      "Diese Woche bleib am Boden - kein einziger fliegbarer Tag."
    """
    strong = [d for d in days_out if d["tier"] in ("violet", "green")]
    conditional = [d for d in days_out if d["tier"] == "conditional"]
    none = [d for d in days_out if d["tier"] == "none"]

    if not strong and not conditional:
        return "Diese Woche bleib am Boden — kein fliegbarer Tag in deinen Regionen."

    parts: list[str] = []

    # Satz 1: Top-Tage
    if not strong:
        parts.append("Keine Top-Bedingungen, nur bedingt fliegbar.")
    elif len(strong) == 1:
        d = strong[0]
        wd_long = _WEEKDAY_DE_LONG[datetime.fromisoformat(d["date"]).weekday()]
        parts.append(f"{wd_long} ist dein Tag der Woche.")
    elif len(strong) <= 3:
        wds = ", ".join(d["label"]["short"] for d in strong)
        parts.append(f"{len(strong)} starke Tage: {wds}.")
    else:
        parts.append(f"{len(strong)} starke Tage diese Woche.")

    # Satz 2: Warnungen oder Schlecht-Tage
    if warnings:
        # erste Warnung mit Tagen
        w = warnings[0]
        if w.get("days_short"):
            wds = "/".join(w["days_short"])
            parts.append(f"{w['label']} an {wds} — meiden.")
        else:
            parts.append(f"{w['label']} aufziehend — meiden.")
    elif none:
        wds = "/".join(d["label"]["short"] for d in none[:2])
        parts.append(f"{wds} nichts fliegbar.")

    return " ".join(parts)


_FOEHN_RANK = {"none": 0, "low": 1, "moderate": 2, "high": 3}
_PHENOMENON_KEYWORDS = [
    ("Gewitter",     ["gewitter", "thunderstorm", "blitz", "cape "]),
    ("Schauer",      ["schauer", "regen", "niederschlag", "precip"]),
    ("Sturm",        ["sturm", "orkan", "starker wind", "boeen", "starke boe"]),
    ("Windscherung", ["windscherung", "scherung", "shear"]),
]


def _build_week_lead_input(days_out: list[dict]) -> str:
    """Kompakte, LLM-freundliche Wochenuebersicht aus Subscriber-Regionen.

    Pro Tag eine Zeile:
      Mo 27.04 [tier]: Foehn=<low|mod|high|—>, Phaenomene=Schauer/Gewitter,
        Wind: <wind_summary der Top-Region, gekuerzt>

    Gibt leeren String zurueck, wenn keine Regions-Daten verfuegbar sind —
    dann sollte der Aufrufer auf den deterministischen Fallback gehen.
    """
    lines: list[str] = []
    _tier_de = {
        "violet": "top",
        "green": "gut",
        "conditional": "bedingt",
        "gray": "abgleiter",
        "none": "nichts",
    }

    for d in days_out:
        regions = d.get("_regions_meteo") or []
        wd_short = d["label"].get("short", "")
        try:
            iso = datetime.fromisoformat(d["date"]).strftime("%d.%m.")
        except Exception:
            iso = d.get("date", "")
        tier_de = _tier_de.get(d.get("tier", "none"), d.get("tier", "?"))

        max_foehn = max(
            (_FOEHN_RANK.get(r.get("foehn_risk", "none"), 0) for r in regions),
            default=0,
        )
        foehn_label = {0: "—", 1: "low", 2: "mod", 3: "high"}[max_foehn]

        haystack = " ".join(
            (str(r.get("wind_summary", "")) + " " + " ".join(r.get("caution_notes") or []))
            .lower()
            for r in regions
        )
        phenomena = [
            label for label, kws in _PHENOMENON_KEYWORDS
            if any(k in haystack for k in kws)
        ]
        phen_str = "/".join(phenomena) if phenomena else "—"

        wind_line = ""
        for r in regions:
            ws = (r.get("wind_summary") or "").strip()
            if ws:
                wind_line = ws[:140] + ("…" if len(ws) > 140 else "")
                wind_line = f"{r.get('region_name', '?')}: {wind_line}"
                break

        line = f"{wd_short} {iso} [{tier_de}]: Foehn={foehn_label}, Phänomene={phen_str}"
        if wind_line:
            line += f"\n    Wind: {wind_line}"
        lines.append(line)

    if not any(d.get("_regions_meteo") for d in days_out):
        return ""

    return "\n".join(lines)


def _week_summary_llm(days_out: list[dict], warnings: list[dict]) -> str:
    """1-2 Saetze Wochen-Lead, vom LLM generiert.

    Faellt bei jedem Fehler (kein API-Key, Timeout, leerer Output, leerer Input)
    auf den deterministischen _week_summary_prose zurueck — Briefing-Versand
    darf nie wegen LLM blockieren.
    """
    fallback = _week_summary_prose(days_out, warnings)

    user_input = _build_week_lead_input(days_out)
    if not user_input:
        return fallback

    try:
        import config as _config
        from llm_client import build_client
        from prompts import _load_skill  # type: ignore
    except Exception as e:
        logger.warning("week_lead LLM: Imports fehlgeschlagen (%s) — Fallback.", e)
        return fallback

    provider = _config.CHAT_PROVIDER
    api_key = _config.get_api_key(provider)
    model = _config.get_model(provider, "chat")
    if not api_key or not model:
        return fallback

    try:
        system_prompt = _load_skill("email_week_lead.md")
    except Exception as e:
        logger.warning("week_lead LLM: Skill-Datei fehlt (%s) — Fallback.", e)
        return fallback

    client = build_client(provider, api_key, timeout=15.0)
    if client is None:
        return fallback

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=0.0,
            max_tokens=120,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("week_lead LLM: Aufruf fehlgeschlagen (%s) — Fallback.", e)
        return fallback

    if not text:
        return fallback

    text = text.strip().strip('"').strip("'")
    if len(text) > 300:
        text = text[:297].rstrip() + "…"
    return text


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
            stars = _stars_for_spot(spot)

            entry = matrix.setdefault(rid, {
                "region_id": rid,
                "region_name": rname,
                "days": [{"tier": "none", "rating": 0.0, "stars": 0, "spot_count": 0}
                         for _ in range(n_days)],
                "best_rating": 0.0,
            })
            cell = entry["days"][day_idx]
            # Bester Tier gewinnt, bei Gleichstand besseres Rating
            if (_TIER_RANK.get(tier, -1) > _TIER_RANK.get(cell["tier"], -1)
                    or (tier == cell["tier"] and rating > cell["rating"])):
                cell["tier"] = tier
                cell["rating"] = rating
            # Sterne unabhaengig: max ueber alle Spots in dieser Region/Tag
            if stars > cell["stars"]:
                cell["stars"] = stars
            # v1.4: Integer-Rating 1-10 (max ueber alle Spots in dieser Region/Tag)
            r10 = _rating_for_spot(spot)
            if r10 > cell.get("rating_int", 0):
                cell["rating_int"] = r10
            cell["spot_count"] += 1
            entry["best_rating"] = max(entry["best_rating"], rating)
            entry["best_rating_int"] = max(entry.get("best_rating_int", 0), r10)

    def _mix_hex_with_white(hex_str: str, alpha: float) -> str:
        hex_str = hex_str.lstrip('#')
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
        r_new = int(r * alpha + 255 * (1 - alpha))
        g_new = int(g * alpha + 255 * (1 - alpha))
        b_new = int(b * alpha + 255 * (1 - alpha))
        return f"#{r_new:02x}{g_new:02x}{b_new:02x}"

    # Meta pro Zelle einhaengen + Sortierung
    out = []
    for entry in matrix.values():
        for cell in entry["days"]:
            meta = _TIER_META.get(cell["tier"], _TIER_META["none"])
            
            # v1.4: Integer 1-10 statt Decimal
            rating_int = cell.get("rating_int", 0)
            cell["rating_display"] = str(rating_int) if rating_int > 0 else ""
            
            # Dynamische Intensitaet:
            if cell["tier"] in ("green", "amber", "violet") and rating_int > 0:
                alpha = 0.4 + (rating_int / 10.0) * 0.6
                cell["tier_color"] = _mix_hex_with_white(meta["color"], alpha)
                cell["tier_text_color"] = meta["color"] if alpha < 0.65 else "#ffffff"
            else:
                cell["tier_color"] = meta["color"]
                cell["tier_text_color"] = "#ffffff"
                
            cell["tier_bg"]    = meta["bg"]
            cell["tier_label"] = meta["label"]
            cell["stars_glyph"] = _stars_glyph_text(cell["stars"])
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
        # v1.4: Integer 1-10 — max ueber Spots der Gruppe (nutzt experience_rating, fallback)
        g["region_rating_int"] = max((_rating_for_spot(sp) for sp in spots), default=0)
        g["region_rating_display"] = (str(g["region_rating_int"])
                                      if g["region_rating_int"] > 0 else "")
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
        "conditional": "Mit Vorsicht fliegbar",
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
            stars = _stars_for_spot(s)
            band = _safety_band_for_spot(s)
            shown.append({
                **s,
                "tier": tier,
                "tier_label": meta["label"],
                "tier_color": meta["color"],
                "tier_bg":    meta["bg"],
                "tier_icon":  meta["icon"],
                "stars": stars,
                "stars_glyph": _stars_glyph_text(stars),
                "safety_band": band,
                "window":     _format_window(s.get("best_window", "")),
                # v1.4: Integer 1-10 (RATING_CONCEPT v1.4)
                "rating_int": _rating_for_spot(s),
                "rating_display": _rating_display(s),
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
        # v1.4: Integer 1-10 fuer Display
        day_rating_int = max((sp.get("rating_int", 0) for sp in displayed_spots),
                             default=0)
        fly_summary = _day_fly_summary(my_spots, day_tier)
        safety_summary = _day_safety_summary(my_spots)

        # top_spots_flat: 3 beste Spots des Tages regionen-uebergreifend (flach sortiert
        # nach rating). Fuer Mobile-First Spot-Buttons in v5_dense — 3-Spot-Garantie
        # auch wenn die Top-Region nur 1-2 Spots hat (faellt auf naechste Regionen
        # zurueck). region_name bleibt pro Spot erhalten (durch ** s spread aus shown).
        top_spots_flat = sorted(
            displayed_spots,
            key=lambda s: float(s.get('rating') or 0),
            reverse=True,
        )[:3]

        # Day-Sterne = max ueber gezeigte Spots
        day_stars = max((sp.get("stars", 0) for sp in displayed_spots), default=0)
        days_out.append({
            "date": date_str,
            "label": day_label_dict,
            "tier": day_tier,
            "tier_label": meta["label"],
            "tier_color": meta["color"],
            "tier_bg":    meta["bg"],
            "tier_icon":  meta["icon"],
            "stars": day_stars,
            "stars_glyph": _stars_glyph_text(day_stars),
            "shown_spots": displayed_spots,
            "region_groups": region_groups,
            "top_spots_flat": top_spots_flat,
            "day_rating": day_rating,
            "day_rating_int": day_rating_int,
            # v1.4: Integer 1-10 statt Decimal
            "day_rating_display": (str(day_rating_int) if day_rating_int > 0 else ""),
            "fly_summary": fly_summary,
            "safety_summary": safety_summary,
            "more_count":  max(0, len(my_spots) - len(displayed_spots)),
            # Intern fuer Heatmap-Aggregation: UNFILTERED, damit das Region-x-Tag-Raster
            # immer alle abonnierten Regionen abbildet (auch wenn user 'gray' gefiltert hat).
            "_my_spots_all": my_spots_unfiltered,
            "_regions_meteo": [r for r in (day.get("regions_meteo") or [])
                               if r.get("region_id") in subscriber_regions],
        })

    # Verdict = bester Tag (Tier-Rank, dann Rating des Top-Spots)
    def _day_score(d):
        top_rating = d["shown_spots"][0]["rating"] if d["shown_spots"] else 0.0
        return (_TIER_RANK.get(d["tier"], -1), float(top_rating or 0))

    best_day = max(days_out, key=_day_score, default=None)
    best_day_idx = days_out.index(best_day) if best_day else 0

    # Verdict nur zeigen, wenn bester Tag wenigstens 'conditional' ist
    # - headline: voll (für Subject/Share/Preheader — muss standalone Sinn machen)
    # - headline_short: kompakt für E-Mail-Hero (Eyebrow zeigt schon Wochentag,
    #   Tier-Pill zeigt schon Status — Headline fokussiert auf WAS/WO)
    verdict = None
    if best_day and best_day["tier"] != "none":
        top_spot = best_day["shown_spots"][0] if best_day["shown_spots"] else None
        verdict = {
            "day": best_day,
            "spot": top_spot,
            "headline":       _verdict_headline(best_day, top_spot),
            "headline_short": _verdict_headline_short(best_day, top_spot),
        }

    # Heute-Markierung pro Tag (für 5-Tage-Streifen)
    today_iso = datetime.now().date().isoformat()
    for day in days_out:
        day["is_today"] = (day.get("date") == today_iso)

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

    # Per-Day-Compact: 5-Tage-Streifen + One-Liner pro Tag
    # - reason_short: Warnungs-Label (Föhn/Sturm) ODER fly_summary-Kopf ODER Fallback
    # - compact_top_region: beste Region-Gruppe (für starke Tage als One-Liner)
    # - tier_color_strip / tier_bg_strip: rot für "none" (= "meiden") statt grau,
    #   damit der Streifen Wetter-Stop visuell anders kommuniziert als die
    #   Heatmap (wo none=grau bleibt = "kein Spot dieser Region").
    warnings_per_day_short: dict[str, list[str]] = {}
    for w in warnings:
        for ds in w.get("days_short", []):
            warnings_per_day_short.setdefault(ds, []).append(w["label"])

    for day in days_out:
        wd_short = day["label"].get("short", "")
        warn_labels = warnings_per_day_short.get(wd_short, [])
        if warn_labels:
            day["reason_short"] = " · ".join(warn_labels[:2])
        elif day["tier"] == "none":
            day["reason_short"] = "Nichts fliegbar"
        elif day["tier"] == "conditional":
            fs = (day.get("fly_summary") or "").rstrip(".")
            head = fs.split(",")[0].strip() if fs else ""
            day["reason_short"] = head or "Bedingt fliegbar"
        else:
            day["reason_short"] = ""

        if day["tier"] in ("violet", "green") and day.get("region_groups"):
            day["compact_top_region"] = day["region_groups"][0]
        else:
            day["compact_top_region"] = None

        if day["tier"] == "none":
            day["tier_color_strip"] = "#b91c1c"   # red-700 — "meiden"
            day["tier_bg_strip"]    = "#fef2f2"
        else:
            day["tier_color_strip"] = day["tier_color"]
            day["tier_bg_strip"]    = day["tier_bg"]

        # Stichworte fuer "Pro Tag"-Cards: + (gut) / ! (schlecht)
        # Quelle: fly_summary (Peak/Fenster) bzw. safety_summary ("Vorsicht: ...").
        # Optional — nur setzen wenn nicht-trivial.
        fs = day.get("fly_summary") or ""
        if "," in fs:
            # Prefix "Top-Bedingungen,"/"Solide Thermik," abschneiden,
            # Rest sind die Stichpunkte (Peak, Fenster).
            day["notable_good"] = fs.split(",", 1)[1].strip().rstrip(".")
        else:
            day["notable_good"] = ""

        ss = day.get("safety_summary") or ""
        if ss.lower().startswith("vorsicht"):
            day["notable_bad"] = ss.replace("Vorsicht:", "").strip().rstrip(".")
        else:
            day["notable_bad"] = ""

    # Heatmap-Matrix der Subscriber-Regionen
    region_matrix = _build_region_matrix(days_out, subscriber_regions)

    # Lead-Prosa (1-2 Saetze zur Wochen-Gesamtsituation)
    # LLM-generiert mit Fallback auf deterministischen Prose-Builder.
    week_lead = _week_summary_llm(days_out, warnings)

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
        # Streifen-Link: Dashboard mit Subscriber-Regionen + diesem Tag
        day["strip_url"] = f"{base}/briefing?regions={regions_csv}&day={day_idx}"
        for s in day["shown_spots"]:
            spot_q = quote(s.get("spot") or "", safe="")
            s["url"] = (f"{base}/briefing?regions={s['region_id']}"
                        f"&day={day_idx}&spot={spot_q}")


    # WhatsApp-Share: kurzer Text + Deep-Link. wa.me/?text=<URL-encoded>
    # Der Deep-Link enthaelt schon die Subscriber-Regionen + besten Tag,
    # Empfaenger landet gefiltert. Rich-Preview kommt per OG-Tags auf /briefing.
    if verdict:
        share_msg = f"{verdict['headline']} — Gleitcast Wochencast KW{today.isocalendar().week}:"
    else:
        share_msg = f"Mein Gleitcast Wochencast für KW{today.isocalendar().week}:"
    share_payload = f"{share_msg}\n{deep_link}"
    share = {
        "url":          deep_link,
        "text":         share_msg,
        "whatsapp":     f"https://wa.me/?text={quote(share_payload, safe='')}",
        "telegram":     f"https://t.me/share/url?url={quote(deep_link, safe='')}&text={quote(share_msg, safe='')}",
        "mailto":       f"mailto:?subject={quote('Gleitcast Wochencast KW' + str(today.isocalendar().week))}&body={quote(share_payload, safe='')}",
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
        "week_lead": week_lead,
        "day_short_labels": day_short_labels,
        "tier_meta": _TIER_META,
    }


def _verdict_headline(day: dict, spot: Optional[dict]) -> str:
    """Ein-Satz-Headline fuer den Verdict-Block (voll, fuer Subject/Share/Preheader)."""
    weekday_long = _WEEKDAY_DE_LONG[datetime.fromisoformat(day["date"]).weekday()]
    if day["tier"] == "violet":
        if spot:
            return f"{weekday_long} ist dein Tag — {spot['spot']} ist Top"
        return f"{weekday_long} wird ein Top-Tag"
    if day["tier"] == "green":
        if spot:
            return f"Bester Tag: {weekday_long} — {spot['spot']} sicher fliegbar"
        return f"{weekday_long} ist sicher fliegbar"
    if day["tier"] == "conditional":
        if spot:
            return f"{weekday_long} mit Vorsicht — {spot['spot']}"
        return f"{weekday_long} nur mit Vorsicht"
    return "Diese Woche nichts in deinen Regionen"


def _verdict_headline_short(day: dict, spot: Optional[dict]) -> str:
    """Kompakte Headline fuer E-Mail-Hero.

    Eyebrow zeigt bereits 'BESTER TAG · Donnerstag, 23.04.', die Tier-Pill rechts
    zeigt 'SICHER'/'TOP'. Headline soll daher nur WAS/WO sagen — kein Wochentag,
    keine Tier-Wiederholung.
    """
    if not spot:
        if day["tier"] == "violet":
            return "Top-Bedingungen erwartet"
        if day["tier"] == "green":
            return "Solide Thermik"
        if day["tier"] == "conditional":
            return "Nur mit Vorsicht fliegbar"
        return "Diese Woche nichts in deinen Regionen"

    spot_name = spot.get("spot", "")
    window = spot.get("window") or _format_window(spot.get("best_window", ""))
    base = f"{spot_name}, {window}" if window else spot_name

    if day["tier"] == "violet":
        return f"{base} — Top"
    if day["tier"] == "conditional":
        return f"{base} — mit Vorsicht"
    return base  # green: kein Modifier (Tier-Pill sagt schon "Sicher")


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
