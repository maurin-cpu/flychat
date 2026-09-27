"""
Routing- und Geocoding-Modul für Wingcast (Phase 1).

Stellt drei Funktionen für den Chat-Tool-Use bereit:
- geocode(query): Adresse → lat/lon (Nominatim)
- isochrone(lat, lon, minutes, mode): Erreichbare Zone (Valhalla)
- spots_in_polygon(polygon, spots): Welche Spots liegen drin (shapely)

Bei Ausfall der externen Services wird `RoutingError` geworfen — KEIN Fallback.
"""

import json
import logging
import math
import os
import time
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)


# ============================================================================
# EXCEPTIONS
# ============================================================================

class RoutingError(Exception):
    """Routing-Service (Valhalla / Nominatim) ist nicht erreichbar oder lieferte
    eine ungültige Antwort. Wird vom Chat-Engine in eine ehrliche Fehlermeldung
    übersetzt — kein Fallback auf Haversine-Kreise oder OSRM."""
    pass


class RoutingLimitError(RoutingError):
    """Die Anfrage überschreitet eine **feste** Grenze des Routing-Dienstes.

    Abgrenzung zu RoutingError, und der ganze Grund für diese Klasse: Ein
    RoutingError kann vorübergehend sein, ein RoutingLimitError nie. Wer einen
    RoutingLimitError als "bitte später erneut versuchen" ausgibt, schickt den
    Nutzer in eine Schleife, die nicht enden kann — genau das ist am 25.09.2026
    passiert (validation/chat/BEFUNDE.md §7). Die Antwort muss die Grenze nennen.
    """
    pass


# ============================================================================
# GEOCODE-CACHE (in-memory, 24h)
# ============================================================================
# Nominatim erlaubt nur 1 Request/Sekunde + verlangt korrekten User-Agent.
# Caching ist Pflicht für freundliche Nutzung.

_GEOCODE_CACHE: dict = {}  # key -> (timestamp, result)
_LAST_NOMINATIM_REQUEST: float = 0.0


def _cache_get(key: str):
    entry = _GEOCODE_CACHE.get(key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > config.GEOCODE_CACHE_TTL:
        _GEOCODE_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value):
    _GEOCODE_CACHE[key] = (time.time(), value)


def _throttle_nominatim():
    """Stelle sicher, dass mindestens 1 Sekunde zwischen Nominatim-Calls liegt."""
    global _LAST_NOMINATIM_REQUEST
    elapsed = time.time() - _LAST_NOMINATIM_REQUEST
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)
    _LAST_NOMINATIM_REQUEST = time.time()


# ============================================================================
# GEOCODING (Nominatim)
# ============================================================================

def geocode(query: str, lang: str = "de") -> Optional[dict]:
    """Geokodiert eine Adresse / Ortsangabe via Nominatim.

    Args:
        query: Free-text query, z.B. "Zürich" oder "Bahnhofstrasse 1, Bern".
        lang: Sprache der Antwort (Display-Name).

    Returns:
        Dict {lat, lon, display_name} oder None wenn nichts gefunden wurde.

    Raises:
        RoutingError: Wenn Nominatim nicht erreichbar ist oder einen HTTP-Fehler liefert.
    """
    if not query or not query.strip():
        return None

    cache_key = f"{lang}::{query.strip().lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug(f"geocode cache hit: {query}")
        return cached

    _throttle_nominatim()

    url = f"{config.NOMINATIM_URL}/search"
    params = {
        "q": query.strip(),
        "format": "json",
        "limit": 1,
        "accept-language": lang,
        "addressdetails": 0,
    }
    headers = {
        "User-Agent": config.ROUTING_USER_AGENT,
        "X-Client-Id": config.ROUTING_CLIENT_ID,
        "Accept": "application/json",
    }

    try:
        resp = requests.get(
            url, params=params, headers=headers, timeout=config.ROUTING_TIMEOUT
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Nominatim request failed: {e}")
        raise RoutingError(f"Nominatim nicht erreichbar: {e}") from e

    if resp.status_code != 200:
        logger.error(f"Nominatim HTTP {resp.status_code}: {resp.text[:200]}")
        raise RoutingError(f"Nominatim HTTP {resp.status_code}")

    try:
        items = resp.json()
    except ValueError as e:
        raise RoutingError(f"Nominatim ungültige JSON-Antwort: {e}") from e

    if not items:
        _cache_put(cache_key, None)
        return None

    first = items[0]
    try:
        result = {
            "lat": float(first["lat"]),
            "lon": float(first["lon"]),
            "display_name": first.get("display_name", query),
        }
    except (KeyError, ValueError) as e:
        raise RoutingError(f"Nominatim Antwort unvollständig: {e}") from e

    _cache_put(cache_key, result)
    return result


# ============================================================================
# ISOCHRONE (Valhalla)
# ============================================================================

_VALID_COSTING = {"auto", "bicycle", "pedestrian"}


def isochrone(lat: float, lon: float, minutes: int, mode: str = "auto") -> dict:
    """Berechnet eine Isochrone (erreichbare Zone) via Valhalla.

    Args:
        lat: Origin Latitude (WGS84).
        lon: Origin Longitude (WGS84).
        minutes: Gewünschte Reisezeit in Minuten (1-360).
        mode: Verkehrsmittel — "auto", "bicycle" oder "pedestrian".

    Returns:
        GeoJSON FeatureCollection mit (i.d.R.) genau einem Polygon-Feature.
        Format kompatibel mit Leaflet L.geoJSON().

    Raises:
        RoutingError: Wenn Valhalla nicht erreichbar ist, ein HTTP-Fehler kommt
            oder die Antwort kein verwertbares Polygon enthält.
        ValueError: Wenn Argumente ungültig sind (sofortige Validierung).
    """
    if mode not in _VALID_COSTING:
        raise ValueError(f"Unbekannter Modus '{mode}', erlaubt: {sorted(_VALID_COSTING)}")
    if not (1 <= minutes <= 360):
        raise ValueError(f"minutes muss zwischen 1 und 360 liegen, war {minutes}")
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise ValueError(f"Ungültige Koordinaten: ({lat}, {lon})")

    # Feste Grenze des Dienstes vorab abfangen, damit der Aufrufer sie benennen
    # kann statt einen HTTP 400 als Ausfall zu deuten.
    if minutes > config.VALHALLA_MAX_ISOCHRONE_MINUTES:
        raise RoutingLimitError(
            f"Isochronen sind bei diesem Dienst auf "
            f"{config.VALHALLA_MAX_ISOCHRONE_MINUTES} Minuten begrenzt "
            f"(angefragt: {minutes})"
        )

    url = f"{config.VALHALLA_URL.rstrip('/')}/isochrone"
    payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": mode,
        "contours": [{"time": minutes, "color": "4f46e5"}],
        "polygons": True,
        "denoise": 0.5,
        "generalize": 50,
        "id": "wingcast",
    }
    headers = {
        "User-Agent": config.ROUTING_USER_AGENT,
        "X-Client-Id": config.ROUTING_CLIENT_ID,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        resp = requests.post(
            url, json=payload, headers=headers, timeout=config.ROUTING_TIMEOUT
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Valhalla isochrone request failed: {e}")
        raise RoutingError(f"Valhalla nicht erreichbar: {e}") from e

    if resp.status_code != 200:
        logger.error(f"Valhalla HTTP {resp.status_code}: {resp.text[:200]}")
        raise RoutingError(f"Valhalla HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as e:
        raise RoutingError(f"Valhalla ungültige JSON-Antwort: {e}") from e

    if not isinstance(data, dict) or "features" not in data:
        raise RoutingError("Valhalla Antwort ohne 'features' Feld")

    features = data.get("features") or []
    if not features:
        raise RoutingError("Valhalla Antwort ohne Polygone")

    # Sicherstellen, dass es eine FeatureCollection ist (Valhalla liefert das normalerweise so).
    if data.get("type") != "FeatureCollection":
        data = {"type": "FeatureCollection", "features": features}

    return data


# ============================================================================
# FAHRZEITEN ZU VIELEN ZIELEN (Valhalla)
# ============================================================================
# Warum Fahrzeit statt Isochrone — am 27.09.2026 alles nachgemessen:
#
#   Isochrone (Flaeche)  deckelt bei 60 Minuten. Feste Hausregel des Gratis-
#                        Dienstes, kein Ausfall. Wird hier nicht mehr benutzt.
#   Matrix (Sammel)      schnell (100 Ziele in 2.9 s), aber liefert fuer ~60 %
#                        unserer Startplaetze `time: null` — die Koordinate liegt
#                        am Berg, nicht an der Strasse.
#   Route (einzeln)      loest genau diese Luecke: 25 von 25 zuvor leeren Zielen
#                        kamen korrekt zurueck (107-241 Minuten). Kostet 0.77 s
#                        je Ziel, und der Dienst erlaubt KEINE parallelen
#                        Anfragen (6 Threads -> 1 von 25 durchgekommen).
#
# Daraus die Bauweise: Sammelabfrage zuerst, Luecken einzeln nachfuellen, alles
# dauerhaft zwischenspeichern. Weil Fahrzeiten sich nicht aendern, ist ein
# einmal gefuellter Speicher fuer immer gut — deshalb liegt er auf der Platte
# und nicht im Prozess: nur so nuetzt das Vorwaermen per Skript dem Server.

_MATRIX_CACHE: dict = {}          # key -> (timestamp, eintrag)
_CACHE_DATEI_MTIME: float = -1.0  # zuletzt gelesener Stand der Platte
_CACHE_SCHMUTZIG: bool = False    # gibt es Eintraege, die noch nicht auf Platte sind?


def _matrix_cache_key(olat: float, olon: float, tlat: float, tlon: float, mode: str) -> str:
    """Schluessel als String, damit er sich unveraendert in JSON schreiben laesst.

    ~100 m Raster auf der Startseite: Piloten tippen "Grenchen", nicht
    Koordinaten, und 100 m aendern keine Fahrzeit. Ziele sind Fixpunkte und
    werden feiner gerundet.
    """
    return f"{olat:.3f},{olon:.3f}|{tlat:.5f},{tlon:.5f}|{mode}"


def _cache_datei_laden(force: bool = False) -> None:
    """Liest den Speicher von der Platte, wenn sich dort etwas geaendert hat.

    Der Chat-Server und das Vorwaerm-Skript sind verschiedene Prozesse. Ohne
    diesen mtime-Abgleich wuerde der Server ein Vorwaermen nie mitbekommen.
    """
    global _CACHE_DATEI_MTIME
    pfad = getattr(config, "TRAVEL_TIME_CACHE_PATH", None)
    if pfad is None:
        return
    try:
        mtime = os.path.getmtime(pfad)
    except OSError:
        return
    if not force and mtime <= _CACHE_DATEI_MTIME:
        return
    try:
        with open(pfad, "r", encoding="utf-8") as f:
            roh = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning(f"Fahrzeit-Speicher nicht lesbar ({e}) — wird neu aufgebaut")
        return
    jetzt = time.time()
    geladen = 0
    for key, wert in (roh.get("eintraege") or {}).items():
        try:
            ts = float(wert["ts"])
        except (KeyError, TypeError, ValueError):
            continue
        if jetzt - ts > config.TRAVEL_TIME_CACHE_TTL:
            continue
        # Was im Prozess liegt, ist mindestens so frisch — nicht ueberschreiben.
        if key in _MATRIX_CACHE and _MATRIX_CACHE[key][0] >= ts:
            continue
        _MATRIX_CACHE[key] = (ts, {"minutes": wert.get("minutes"),
                                   "reason": wert.get("reason")})
        geladen += 1
    _CACHE_DATEI_MTIME = mtime
    if geladen:
        logger.info(f"Fahrzeit-Speicher: {geladen} Eintraege von Platte gelesen")


def cache_datei_schreiben() -> int:
    """Schreibt neue Eintraege auf die Platte (mergend, atomar). Gibt die Anzahl zurueck.

    Mergend, weil Server und Vorwaerm-Skript parallel schreiben koennen: erst den
    Stand der Platte dazuladen, dann alles gemeinsam ersetzen. Im schlimmsten
    Fall geht ein Eintrag verloren und wird neu berechnet — kein Schaden.
    """
    global _CACHE_SCHMUTZIG, _CACHE_DATEI_MTIME
    pfad = getattr(config, "TRAVEL_TIME_CACHE_PATH", None)
    if pfad is None or not _MATRIX_CACHE:
        return 0
    _cache_datei_laden()
    daten = {"eintraege": {
        key: {"ts": ts, "minutes": e.get("minutes"), "reason": e.get("reason")}
        for key, (ts, e) in _MATRIX_CACHE.items()
    }}
    try:
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        tmp = f"{pfad}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(daten, f)
        os.replace(tmp, pfad)
        _CACHE_DATEI_MTIME = os.path.getmtime(pfad)
    except OSError as e:
        logger.warning(f"Fahrzeit-Speicher nicht schreibbar: {e}")
        return 0
    _CACHE_SCHMUTZIG = False
    return len(daten["eintraege"])


def _matrix_cache_get(key: str):
    entry = _MATRIX_CACHE.get(key)
    if not entry:
        return False, None
    ts, value = entry
    if time.time() - ts > config.TRAVEL_TIME_CACHE_TTL:
        _MATRIX_CACHE.pop(key, None)
        return False, None
    return True, value


def max_straight_line_km(minutes: int) -> float:
    """Obergrenze der Luftlinie, die in `minutes` ueberhaupt erreichbar sein kann.

    Dient als Vorfilter: Was weiter weg liegt, kann die Fahrzeit nie einhalten,
    weil die Fahrstrecke immer laenger ist als die Luftlinie. Bewusst grosszuegig
    (120 km/h) — der Filter darf keinen echten Treffer verlieren, er soll nur die
    offensichtlich unmoeglichen Ziele sparen.
    """
    return minutes / 60.0 * config.TRAVEL_TIME_MAX_KMH


def _matrix_request(lat: float, lon: float, chunk: list, mode: str) -> list:
    """Eine Sammelabfrage. Gibt Minuten je Ziel zurueck (None = keine Zahl)."""
    url = f"{config.VALHALLA_URL.rstrip('/')}/sources_to_targets"
    payload = {
        "sources": [{"lat": lat, "lon": lon}],
        "targets": [{"lat": t[0], "lon": t[1]} for t in chunk],
        "costing": mode,
    }
    headers = {
        "User-Agent": config.ROUTING_USER_AGENT,
        "X-Client-Id": config.ROUTING_CLIENT_ID,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url, json=payload, headers=headers, timeout=config.ROUTING_TIMEOUT * 4
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Valhalla matrix request failed: {e}")
        raise RoutingError(f"Valhalla nicht erreichbar: {e}") from e

    if resp.status_code == 400:
        # 154 = eine Route im Block ist laenger als erlaubt. Welche, sagt Valhalla
        # nicht — der Aufrufer teilt den Block darum auf.
        raise RoutingLimitError(f"Valhalla HTTP 400: {resp.text[:160]}")
    if resp.status_code != 200:
        logger.error(f"Valhalla matrix HTTP {resp.status_code}: {resp.text[:200]}")
        raise RoutingError(f"Valhalla HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as e:
        raise RoutingError(f"Valhalla ungültige JSON-Antwort: {e}") from e

    rows = data.get("sources_to_targets") or []
    if not rows:
        raise RoutingError("Valhalla Matrix-Antwort ohne 'sources_to_targets'")
    row = rows[0] if isinstance(rows[0], list) else rows

    out: list = [None] * len(chunk)
    for entry in row:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("to_index")
        secs = entry.get("time")
        if idx is None or not (0 <= idx < len(chunk)):
            continue
        out[idx] = None if secs is None else secs / 60.0
    return out


def route_minutes(lat: float, lon: float, tlat: float, tlon: float,
                  mode: str = "auto") -> Optional[float]:
    """Fahrzeit zu EINEM Ziel per /route, in Minuten. None = keine Route.

    Der Lueckenfueller: Wo die Sammelabfrage `null` liefert, antwortet dieser Weg
    zuverlaessig (gemessen 25 von 25). Dafuer kostet er eine Anfrage pro Ziel,
    und parallel geht nicht — der Dienst sperrt das.
    """
    url = f"{config.VALHALLA_URL.rstrip('/')}/route"
    payload = {
        "locations": [{"lat": lat, "lon": lon}, {"lat": tlat, "lon": tlon}],
        "costing": mode,
        "directions_options": {"units": "kilometers"},
    }
    headers = {
        "User-Agent": config.ROUTING_USER_AGENT,
        "X-Client-Id": config.ROUTING_CLIENT_ID,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            url, json=payload, headers=headers, timeout=config.ROUTING_TIMEOUT * 2
        )
    except requests.exceptions.RequestException as e:
        raise RoutingError(f"Valhalla nicht erreichbar: {e}") from e

    if resp.status_code == 400:
        return None  # keine Route / zu weit — kein Fehler, nur keine Zahl
    if resp.status_code != 200:
        raise RoutingError(f"Valhalla HTTP {resp.status_code}")
    try:
        summary = resp.json()["trip"]["summary"]
        return float(summary["time"]) / 60.0
    except (ValueError, KeyError, TypeError) as e:
        raise RoutingError(f"Valhalla Route-Antwort unbrauchbar: {e}") from e


def travel_times(lat: float, lon: float, targets: list, mode: str = "auto",
                 budget_seconds: Optional[float] = None,
                 fill_gaps: bool = True) -> list:
    """Fahrzeit vom Startpunkt zu jedem Ziel, in Minuten.

    Args:
        lat, lon: Startpunkt (WGS84).
        targets: Liste von (lat, lon)-Tupeln.
        mode: "auto" | "bicycle" | "pedestrian".
        budget_seconds: Zeitbudget fuer das Nachfuellen der Luecken. None = kein
            Budget (fuer das Vorwaerm-Skript). Im Chat gehoert hier eine Zahl
            hin, sonst wartet der Pilot minutenlang.
        fill_gaps: Luecken der Sammelabfrage einzeln nachfragen.

    Returns:
        Liste gleicher Laenge wie `targets`, je Eintrag ein Dict:
        `{"minutes": float|None, "reason": str|None}`. `reason` bei fehlender
        Zahl: "no_route" (keine Verbindung), "limit" (Route laenger als der
        Dienst erlaubt), "budget" (Zeit war um — beim naechsten Mal da, weil
        gefragte Ziele gespeichert werden). Ein fehlendes Ergebnis wird **nie**
        stillschweigend weggelassen, damit die Antwort die Luecke benennen kann.

    Raises:
        RoutingError: Dienst nicht erreichbar / unbrauchbare Antwort. Eine
            ueberschrittene Laengengrenze ist KEIN Fehler, sondern steht als
            `reason="limit"` beim betroffenen Ziel.
        ValueError: mode unbekannt.
    """
    if mode not in _VALID_COSTING:
        raise ValueError(f"Unbekannter Modus '{mode}', erlaubt: {sorted(_VALID_COSTING)}")
    if not targets:
        return []

    global _CACHE_SCHMUTZIG
    start_zeit = time.monotonic()
    _cache_datei_laden()
    results: list = [None] * len(targets)

    def restbudget() -> Optional[float]:
        if budget_seconds is None:
            return None
        return budget_seconds - (time.monotonic() - start_zeit)

    # 1 · Speicher zuerst — wiederholte Fragen vom selben Ort kosten dann nichts.
    offen: list = []
    for i, (tlat, tlon) in enumerate(targets):
        hit, value = _matrix_cache_get(_matrix_cache_key(lat, lon, tlat, tlon, mode))
        if hit and value.get("reason") != "budget":
            results[i] = value
        else:
            offen.append(i)

    # 2 · Offene Ziele per Sammelabfrage, nach Luftlinie sortiert. Die Sortierung
    #     ist mehr als Kosmetik: Die Streckengrenze des Dienstes wird dadurch an
    #     einer Stelle erreicht statt verteilt, und alles dahinter liegt weiter
    #     weg — dort kann abgebrochen werden statt jedes Ziel einzeln gegen die
    #     Wand laufen zu lassen (das kostete vorher 152 s je Anfrage).
    offen.sort(key=lambda i: haversine_km(lat, lon, targets[i][0], targets[i][1]))
    chunk_size = max(1, config.VALHALLA_MATRIX_CHUNK)

    def zuweisen(indices: list, minuten: list):
        for pos, i in enumerate(indices):
            m = minuten[pos]
            results[i] = (
                {"minutes": None, "reason": "no_route"} if m is None
                else {"minutes": round(m, 1), "reason": None}
            )

    def laengster_ok_prefix(block: list) -> int:
        """Groesste Prefix-Laenge, die der Dienst noch berechnet (Binaersuche)."""
        lo, hi = 0, len(block)
        while lo < hi:
            mitte = (lo + hi + 1) // 2
            try:
                minuten = _matrix_request(lat, lon, [targets[i] for i in block[:mitte]], mode)
            except RoutingLimitError:
                hi = mitte - 1
                continue
            zuweisen(block[:mitte], minuten)
            lo = mitte
        return lo

    abgebrochen_ab = None
    for start in range(0, len(offen), chunk_size):
        block = offen[start:start + chunk_size]
        try:
            zuweisen(block, _matrix_request(lat, lon, [targets[i] for i in block], mode))
        except RoutingLimitError:
            ok = laengster_ok_prefix(block)
            abgebrochen_ab = start + ok
            break
        time.sleep(0.2)  # freundlich zum oeffentlichen Dienst

    if abgebrochen_ab is not None:
        # Alles ab hier liegt weiter weg als das erste Ziel, das die Streckengrenze
        # riss — also ebenfalls darueber. Wird benannt, nicht geraten.
        for i in offen[abgebrochen_ab:]:
            if results[i] is None:
                results[i] = {"minutes": None, "reason": "limit"}

    # 3 · Luecken der Sammelabfrage einzeln nachfuellen, naechste zuerst.
    #     Das ist der Schritt, der die ~60 % Startplaetze ohne Strassenanbindung
    #     rettet. Er ist langsam (0.77 s je Ziel, parallel gesperrt), darum das
    #     Budget — und darum das Vorwaermen per Skript.
    if fill_gaps:
        luecken = [i for i in offen
                   if results[i] is not None and results[i].get("reason") == "no_route"]
        luecken.sort(key=lambda i: haversine_km(lat, lon, targets[i][0], targets[i][1]))
        for i in luecken:
            rest = restbudget()
            if rest is not None and rest <= 1.0:
                for j in luecken[luecken.index(i):]:
                    results[j] = {"minutes": None, "reason": "budget"}
                break
            try:
                m = route_minutes(lat, lon, targets[i][0], targets[i][1], mode)
            except RoutingError as e:
                logger.info(f"Einzelweg fehlgeschlagen ({e}) — Ziel bleibt ohne Zahl")
                continue
            if m is not None:
                results[i] = {"minutes": round(m, 1), "reason": None}

    # 4 · Speicher fuellen (auch die Absagen — sie aendern sich ebenso wenig).
    #     "budget" wird NICHT gespeichert: das war unsere Zeitnot, keine Aussage
    #     ueber die Strecke, und beim naechsten Mal soll es erneut versucht werden.
    jetzt = time.time()
    for i, (tlat, tlon) in enumerate(targets):
        if results[i] is None:
            results[i] = {"minutes": None, "reason": "no_route"}
        if results[i].get("reason") == "budget":
            continue
        _MATRIX_CACHE[_matrix_cache_key(lat, lon, tlat, tlon, mode)] = (jetzt, results[i])
        _CACHE_SCHMUTZIG = True
    return results


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Luftlinie in km. Nur fuer Vorfilter und Sortierung, nie als Fahrzeit."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ============================================================================
# POINT-IN-POLYGON FILTER
# ============================================================================

def spots_in_polygon(polygon_geojson: dict, spots: list) -> list:
    """Filtert Spots, die innerhalb eines GeoJSON-Polygons liegen.

    Args:
        polygon_geojson: GeoJSON FeatureCollection oder Feature mit Polygon /
            MultiPolygon / GeometryCollection.
        spots: Liste von Spot-Dicts mit `latitude` + `longitude` Schlüsseln.

    Returns:
        Subset der spots-Liste, die innerhalb des Polygons liegen.
    """
    try:
        from shapely.geometry import shape, Point
        from shapely.ops import unary_union
    except ImportError as e:
        raise RoutingError(f"shapely fehlt: {e}") from e

    if not polygon_geojson or not spots:
        return []

    # Geometrien sammeln (FeatureCollection → einzelne Geometrien)
    geometries = []
    if polygon_geojson.get("type") == "FeatureCollection":
        for feat in polygon_geojson.get("features", []):
            geom = feat.get("geometry")
            if geom:
                geometries.append(geom)
    elif polygon_geojson.get("type") == "Feature":
        geom = polygon_geojson.get("geometry")
        if geom:
            geometries.append(geom)
    else:
        # Direkte Geometrie
        geometries.append(polygon_geojson)

    if not geometries:
        return []

    # Geometrien zu shapely-Objekten + ggf. Vereinigung
    shp_geoms = []
    for g in geometries:
        try:
            s = shape(g)
            if not s.is_valid:
                s = s.buffer(0)  # repair self-intersections
            shp_geoms.append(s)
        except Exception as e:
            logger.warning(f"Ungültige Geometrie übersprungen: {e}")
            continue

    if not shp_geoms:
        return []

    try:
        merged = unary_union(shp_geoms) if len(shp_geoms) > 1 else shp_geoms[0]
    except Exception as e:
        logger.warning(f"unary_union fehlgeschlagen: {e}")
        merged = shp_geoms[0]

    matched = []
    for spot in spots:
        lat = spot.get("latitude")
        lon = spot.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            pt = Point(float(lon), float(lat))
        except (TypeError, ValueError):
            continue
        if merged.contains(pt) or merged.intersects(pt):
            matched.append(spot)

    return matched
