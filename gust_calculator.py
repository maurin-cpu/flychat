"""
Turbulenzrisiko-Berechnung: 2-Produkt-Architektur (Windprofil + Turbulenzrisiko).

Zwei getrennte Produkte:
  W(z) — Windprofil: Reiner ICON-D2 Modellwind (keine Korrektur)
  T(z) — Turbulenzrisiko: W(z) + Exzess × Gauss-Kernel (rein Gauss, kein Running-Max)

Methode:
- Exzess am Boden: ΔG = max(0, wind_gusts_10m - W(10m))
- T(z) = W(z) + ΔG × exp(-z_agl² / (2 × L_up²))        [Gauss-Kernel]
- L_up ist terrain-abhängig (Korrelationslänge aufwärts)
- PBL als weiches Sicherheitsnetz (sigmoid blend → ws über PBL)

Der Gauss-Kernel fällt sanfter ab als die frühere Exponentialfunktion —
das ist beabsichtigt, weil T(z) ein Sicherheitssignal ist.

Terrain-Korrelationslängen L_up (aus TERRAIN_OI_L_UP):
- mittelland:  350m  (1.0×H_g, Oberflächenrauigkeit)
- jura:        450m  (1.2×H_g, Ridge-Turbulenz)
- voralpen:    550m  (1.3×H_g, Talflanken)
- alpen:       650m  (1.4×H_g, Alpentäler)
- hochalpin:   750m  (1.5×H_g, freie Exposition)

Fallback: Elevation-basierte Interpolation wenn kein terrain_type bekannt.

Referenzen:
- Letson et al. 2019: Turbulenz-Zerfallshöhe H_g = 300-600m → L_up ≈ 1.0-1.5×H_g
- Dörnbrack & Nappo 1997: Kohärenzskala 2000-3000m (Schwerewellen, NICHT Turbulenz-Decay)
- Validierung: Burnair-Vergleich zeigt Übereinstimmung mit L_up ≈ H_g
"""

import csv
import math
import logging
import statistics
from pathlib import Path
from shapely.geometry import Point

logger = logging.getLogger(__name__)

# Alte Skalenhöhen (Legacy, nicht mehr aktiv verwendet — Gauss-Kernel nutzt L_up)
# Referenz: Letson et al. 2019 (300-600m für flaches Terrain)
# TERRAIN_HG = {
#     "mittelland": 350, "jura": 380, "voralpen": 420, "alpen": 450, "hochalpin": 500,
# }
TERRAIN_HG = {
    "mittelland": 350,    # Wald/Siedlung, lokale Turbulenz zerfällt schnell
    "jura": 380,          # Ketten/Kämme, Ridge-Turbulenz
    "voralpen": 420,      # Hügelland bis steile Talflanken
    "alpen": 450,         # Alpentäler, Kalkfelsen, kanalisierte Winde
    "hochalpin": 500,     # Freie Exposition, Gletscherwind
}

# OI-Korrelationslänge aufwärts pro Terrain-Typ (m)
# Bestimmt, wie weit beobachtete Boden-Böen das Höhenprofil beeinflussen.
#
# Physik:
# - Die vertikale KOHÄRENZSKALA (Dörnbrack & Nappo 1997: 2000-3000m) beschreibt
#   Schwerewellen-Phasenkopplung, NICHT Turbulenz-Zerfall.
# - Für Turbulenz-Decay ist die Zerfallshöhe H_g relevant (Letson et al. 2019:
#   300-600m). L_up ≈ 1.0-1.5×H_g deckt den physikalischen Zerfallsbereich ab.
# - Burnair-Validierung: Mit L_up≈H_g stimmen die Höhen-Böen mit Beobachtungen
#   überein (2000m: ~10 km/h, 3500m: ~20 km/h statt 22/32 mit alten Werten).
TERRAIN_OI_L_UP = {
    "mittelland": 350,     # 1.0×H_g, Oberflächenrauigkeit
    "jura": 450,           # 1.2×H_g, Ridge-Turbulenz
    "voralpen": 550,       # 1.3×H_g, Talflanken
    "alpen": 650,          # 1.4×H_g, Alpentäler
    "hochalpin": 750,      # 1.5×H_g, freie Exposition
}

# Terrain-abhängiger BLH-Kopplungsfaktor [0..1]
# Wie stark die Grenzschichthöhe (BLH) die effektive Korrelationslänge L_up
# erweitert. L_up_eff = max(L_up_terrain, coupling × BLH).
#
# Physik:
# - L_up beschreibt vertikale Turbulenz-KOHÄRENZ (Reibung, Schwerewellen).
# - BLH beschreibt thermische DURCHMISCHUNG durch konvektive Aufwinde.
# - Das sind zwei verschiedene Mechanismen. In flachem Terrain ist L_up rein
#   reibungs-/rauigkeitsbestimmt (Letson et al. 2019). Konvektive Mischung
#   erweitert die thermische Reichweite, aber nicht die Turbulenz-Kohärenz.
# - Im Bergland koppeln Schwerewellen + Mountain-Venting die PBL an die freie
#   Atmosphäre. Dort transportiert die konvektive Schicht tatsächlich Boden-
#   Turbulenz nach oben → Kopplung physikalisch gerechtfertigt.
#
# Werte: linear vom flachen (kein Boost) zum hochalpinen (moderater Boost).
# Reduziert vs. früher (0.0-1.0), damit BLH die neuen L_up-Werte nicht aufbläst.
TERRAIN_BLH_COUPLING = {
    "mittelland": 0.0,     # rein reibungsbestimmt, kein BLH-Boost
    "jura":       0.05,    # minimaler Ridge-Effekt
    "voralpen":   0.15,    # moderate Kopplung
    "alpen":      0.20,    # Alpentäler, begrenzte BLH-Erweiterung
    "hochalpin":  0.25,    # freie Exposition, moderater Boost
}

# Fallback-Schwellen (wenn kein terrain_type bekannt)
ELEV_LOW = 800
ELEV_HIGH = 1800
HG_FALLBACK_LOW = 350
HG_FALLBACK_HIGH = 500

# Cache für regionen.csv
_region_terrain_cache = None


def _load_region_terrain():
    """Lädt terrain_type pro Region aus data/regionen.csv (einmalig)."""
    global _region_terrain_cache
    if _region_terrain_cache is not None:
        return _region_terrain_cache

    _region_terrain_cache = {}
    csv_path = Path(__file__).resolve().parent / "data" / "regionen.csv"
    if not csv_path.exists():
        logger.warning("regionen.csv nicht gefunden: %s", csv_path)
        return _region_terrain_cache

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rid = row.get("id", "").strip()
            tt = row.get("terrain_type", "").strip()
            if rid and tt:
                _region_terrain_cache[rid] = tt

    logger.info("%d Regionen-Terrain-Typen geladen", len(_region_terrain_cache))
    return _region_terrain_cache


def get_scale_height(elevation_m, region_id=None):
    """
    Bestimmt die Skalenhöhe H_g für den exponentiellen Turbulenz-Zerfall.

    1. Wenn region_id bekannt → terrain_type aus regionen.csv → exakter H_g
    2. Fallback: Elevation-basierte Interpolation
    """
    if region_id:
        terrain_map = _load_region_terrain()
        terrain_type = terrain_map.get(region_id)
        if terrain_type and terrain_type in TERRAIN_HG:
            return TERRAIN_HG[terrain_type]

    # Fallback: lineare Interpolation aus Elevation
    if elevation_m <= ELEV_LOW:
        return HG_FALLBACK_LOW
    elif elevation_m >= ELEV_HIGH:
        return HG_FALLBACK_HIGH
    else:
        frac = (elevation_m - ELEV_LOW) / (ELEV_HIGH - ELEV_LOW)
        return HG_FALLBACK_LOW + frac * (HG_FALLBACK_HIGH - HG_FALLBACK_LOW)


def get_oi_scale_lengths(elevation_m, region_id=None):
    """
    Bestimmt OI-Korrelationslängen (L_up, L_down) für die Böenprofil-Korrektur.

    L_up: Wie weit beobachtete Bodenböen das Profil AUFWÄRTS beeinflussen.
        - Flach: 1.0×H_g (nur Rauigkeitsturbulenz)
        - Bergig: 1.5×H_g (Turbulenz-Zerfallsskala)
    L_down: Wie weit Böenexzess ABWÄRTS reicht = H_g (Terrain-Zerfall).

    Returns:
        (L_up, L_down) in Metern
    """
    hg = get_scale_height(elevation_m, region_id)

    if region_id:
        terrain_map = _load_region_terrain()
        terrain_type = terrain_map.get(region_id)
        if terrain_type and terrain_type in TERRAIN_OI_L_UP:
            return TERRAIN_OI_L_UP[terrain_type], hg

    # Fallback: Elevation-basierte Interpolation (1.0× flach → 1.5× alpin)
    if elevation_m <= ELEV_LOW:
        return 1.0 * hg, hg
    elif elevation_m >= ELEV_HIGH:
        return 1.5 * hg, hg
    else:
        frac = (elevation_m - ELEV_LOW) / (ELEV_HIGH - ELEV_LOW)
        mult = 1.0 + 0.5 * frac
        return mult * hg, hg


def get_L_up(elevation_m, region_id=None):
    """
    Bestimmt die Gauss-Korrelationslänge L_up für den Turbulenz-Decay.

    L_up bestimmt, wie weit der Bodenböen-Exzess nach oben reicht:
    - Flach: 350m (1.0×H_g, Oberflächenrauigkeit)
    - Alpin: 750m (1.5×H_g, freie Exposition)

    Returns:
        L_up in Metern
    """
    if region_id:
        terrain_map = _load_region_terrain()
        terrain_type = terrain_map.get(region_id)
        if terrain_type and terrain_type in TERRAIN_OI_L_UP:
            return TERRAIN_OI_L_UP[terrain_type]

    # Fallback: Elevation-basierte Interpolation
    L_UP_LOW = 350    # mittelland
    L_UP_HIGH = 750   # hochalpin
    if elevation_m <= ELEV_LOW:
        return L_UP_LOW
    elif elevation_m >= ELEV_HIGH:
        return L_UP_HIGH
    else:
        frac = (elevation_m - ELEV_LOW) / (ELEV_HIGH - ELEV_LOW)
        return L_UP_LOW + frac * (L_UP_HIGH - L_UP_LOW)


def get_blh_coupling(elevation_m, region_id=None):
    """
    Terrain-abhängiger Kopplungsfaktor [0..1] für die BLH→L_up-Erweiterung.

    Steuert, wie stark die Grenzschichthöhe in die effektive Korrelations-
    länge L_up einfliesst. Siehe TERRAIN_BLH_COUPLING für Begründung.

    Returns:
        Kopplungsfaktor zwischen 0.0 (flach, keine BLH-Erweiterung) und 1.0
        (hochalpin, volle BLH-Erweiterung).
    """
    if region_id:
        terrain_map = _load_region_terrain()
        terrain_type = terrain_map.get(region_id)
        if terrain_type and terrain_type in TERRAIN_BLH_COUPLING:
            return TERRAIN_BLH_COUPLING[terrain_type]

    # Fallback: Elevation-basierte lineare Interpolation
    if elevation_m <= ELEV_LOW:
        return TERRAIN_BLH_COUPLING["mittelland"]
    elif elevation_m >= ELEV_HIGH:
        return TERRAIN_BLH_COUPLING["hochalpin"]
    else:
        frac = (elevation_m - ELEV_LOW) / (ELEV_HIGH - ELEV_LOW)
        low = TERRAIN_BLH_COUPLING["mittelland"]
        high = TERRAIN_BLH_COUPLING["hochalpin"]
        return low + frac * (high - low)


def get_effective_L_up(elevation_m, region_id=None, blh=None):
    """
    Berechnet die effektive Korrelationslänge L_up unter Berücksichtigung
    der Grenzschichthöhe (BLH) — terrain-abhängig gewichtet.

    Frühere Implementierung war L_up_eff = max(L_up_terrain, BLH). Das
    überzeichnete im Mittelland die Höhen-Böen, weil eine Reibungs-Skala
    durch eine konvektive Mischschicht ersetzt wurde — zwei physikalisch
    unterschiedliche Längen.

    Neue Logik:
        L_up_eff = max(L_up_terrain, coupling × BLH)

    mit `coupling = get_blh_coupling(...)`. In flachem Terrain ist
    coupling=0 und damit fällt der BLH-Anteil weg; im Hochalpinen ist
    coupling=1 und das frühere Verhalten bleibt erhalten.

    Args:
        elevation_m: Referenz-Elevation (m MSL)
        region_id: Optional, für terrain_type-Lookup aus regionen.csv
        blh: Boundary Layer Height (m AGL), optional

    Returns:
        Effektive Korrelationslänge L_up in Metern
    """
    L_up_terrain = get_L_up(elevation_m, region_id)
    if blh is None or blh <= 0:
        return L_up_terrain
    coupling = get_blh_coupling(elevation_m, region_id)
    return max(L_up_terrain, coupling * blh)


def estimate_altitude_gusts(
    wind_speed_10m,
    wind_gusts_10m,
    pressure_levels_data,
    elevation_m,
    boundary_layer_height=None,
    region_id=None,
):
    """
    Berechnet Turbulenzrisiko T(z) für jedes Druckniveau (Gauss-Kernel).

    Modell: T_raw(z) = W(z) + exzess × exp(-z_agl² / (2 × L_up²))
    - exzess = max(0, wind_gusts_10m - W(10m))
    - Gauss-Kernel: sanfterer Abfall als alte Exponentialfunktion
    - T(z) ist ein Sicherheitssignal, kein physikalisches Turbulenzmodell
    - PBL als weiches Sicherheitsnetz

    Args:
        wind_speed_10m: Mittlerer Wind am Boden (km/h)
        wind_gusts_10m: Böen am Boden (km/h)
        pressure_levels_data: Liste von Dicts mit
            {pressure, altitude, wind_speed, wind_direction, temperature}
        elevation_m: Spot-Elevation (m MSL)
        boundary_layer_height: PBL-Höhe über Grund (m AGL), optional
        region_id: Regions-ID für terrain_type Lookup (optional)

    Returns:
        Liste von Dicts mit wind_gusts (=T(z)) und turbulence_excess Feldern
    """
    if not pressure_levels_data:
        return pressure_levels_data

    # Guard: need valid surface data
    if (wind_speed_10m is None or wind_gusts_10m is None
            or wind_speed_10m <= 0):
        result = []
        for level in pressure_levels_data:
            entry = dict(level)
            entry["wind_gusts"] = entry.get("wind_speed", 0)
            entry["turbulence_excess"] = 0
            result.append(entry)
        return result

    # Absolute gust excess at surface (km/h)
    delta_surface = max(0, wind_gusts_10m - wind_speed_10m)
    # Cap at 30 km/h — beyond this we're in convective/storm territory
    delta_surface = min(delta_surface, 30)

    L_up = get_L_up(elevation_m, region_id)

    result = []
    for level in pressure_levels_data:
        entry = dict(level)
        altitude = entry.get("altitude", 0)
        wind_speed = entry.get("wind_speed", 0)

        z_agl = altitude - elevation_m

        # Gauss-Kernel: exp(-z_agl² / (2 × L_up²))
        # Symmetric: abs(z_agl) squared means both directions decay equally
        z_eff = abs(z_agl)
        decay = math.exp(-(z_eff * z_eff) / (2.0 * L_up * L_up))
        gust_excess = delta_surface * decay

        # PBL sigmoid blend: smooth transition instead of hard cutoff
        # blend → 1 near surface, → 0 well above PBL
        if boundary_layer_height is not None and boundary_layer_height > 0:
            pbl_cap = elevation_m + boundary_layer_height * 1.2
            blend = 1.0 / (1.0 + math.exp((altitude - pbl_cap) / 75))
            gust_excess *= blend

        entry["wind_gusts"] = round(wind_speed + gust_excess, 1)
        entry["turbulence_excess"] = round(gust_excess, 1)
        result.append(entry)

    return result


# ============================================================================
# Multi-Spot Bodenexzess-Aggregation (für Regionen)
# ============================================================================

# Maximaler physikalisch sinnvoller Bodenexzess (Plausibilitäts-Cap, km/h).
# Beyond 30 km/h Exzess sind wir im Sturm-Regime — niemand fliegt da, der Cap
# ist nur eine Notbremse gegen Open-Meteo-Daten-Glitches und Sensor-Defekte.
_MAX_SURFACE_EXCESS_KMH = 30.0


def aggregate_spot_excess(values):
    """
    Robust aggregiert Bodenexzess-Werte mehrerer Spots zu einem Region-Wert.

    Verwendet:
    - Median (≥3 Werte): ausreißer-immun per Definition. Ein einzelner Düsen-
      oder Lee-Spot kann den Median nicht verschieben.
    - Mittel (2 Werte): Median ist bei N=2 mathematisch identisch zum Mittel,
      aber nicht ausreißer-stabil — daher explizit gleich behandelt.
    - Direkter Wert (1 Wert): Pass-through.
    - Cap bei _MAX_SURFACE_EXCESS_KMH: Plausibilitäts-Notbremse gegen Daten-
      Glitches (passive Sicherheit, greift im Normalbetrieb nie).

    Diese Funktion wird im Region-Höhenprofil verwendet, um aus den 10m-
    Bodenexzessen aller Spots einer Region einen einzigen robusten Anker für
    die Gauss-Decay-Berechnung zu erzeugen. Spot-Höhen werden bewusst NICHT
    als vertikale Anker verwendet, weil 10m-Bodenmessungen keine Höhen-
    messungen der freien Atmosphäre sind.

    Args:
        values: Liste von Exzess-Werten (km/h, gust_10m - wind_10m).

    Returns:
        Aggregierter Exzess in km/h (0.0 wenn keine Werte).
    """
    if not values:
        return 0.0
    clean = [max(0.0, float(v)) for v in values if v is not None]
    if not clean:
        return 0.0
    if len(clean) == 1:
        return min(_MAX_SURFACE_EXCESS_KMH, clean[0])
    if len(clean) == 2:
        return min(_MAX_SURFACE_EXCESS_KMH, sum(clean) / 2.0)
    # ≥3 Werte: Median ist ausreißer-immun
    return min(_MAX_SURFACE_EXCESS_KMH, statistics.median(clean))


# ============================================================================
# Multi-Anchor Böen-Profil (für Regionen mit Spots)
# ============================================================================

# Höhenbänder für Deduplizierung (m)
_ANCHOR_BAND_WIDTH = 50


def collect_gust_anchors(region_polygon, spots, weather_data, timestamp, ref_anchor=None):
    """
    Sammelt Böen-Ankerpunkte aus Spots innerhalb eines Region-Polygons.

    Für jeden Spot wird wind_gusts_10m und wind_speed_10m aus den gecachten
    Wetterdaten für den gegebenen Timestamp extrahiert.

    Dedupliziert ähnliche Höhen (50m-Bänder): höchste Böe gewinnt.

    Args:
        region_polygon: Shapely Polygon der Region
        spots: Liste aller Spots (Dicts mit name, latitude, longitude, elevation_m)
        weather_data: Dict {spot_name: {hourly_data: {timestamp: {...}}, ...}}
        timestamp: ISO-Timestamp-String (z.B. "2024-03-15T12:00")
        ref_anchor: Optionaler Referenzpunkt-Anker {elevation_m, gust_kmh, wind_speed_kmh, source}

    Returns:
        Sortierte Liste: [{elevation_m, gust_kmh, wind_speed_kmh, source}, ...]
        Leere Liste wenn keine Anker gefunden.
    """
    raw_anchors = []

    # Referenzpunkt als Anker einbeziehen (echte Open-Meteo Bodendaten)
    if ref_anchor is not None:
        raw_anchors.append(ref_anchor)

    for spot in spots:
        # Point-in-Polygon Check
        pt = Point(spot["longitude"], spot["latitude"])
        if not region_polygon.contains(pt):
            continue

        spot_data = weather_data.get(spot["name"])
        if not spot_data:
            continue

        hourly = spot_data.get("hourly_data", {})
        hour_data = hourly.get(timestamp)
        if not hour_data:
            continue

        gust = hour_data.get("wind_gusts_10m")
        ws = hour_data.get("wind_speed_10m")
        if gust is None or ws is None:
            continue

        raw_anchors.append({
            "elevation_m": spot["elevation_m"],
            "gust_kmh": float(gust),
            "wind_speed_kmh": float(ws),
            "source": spot["name"],
        })

    if not raw_anchors:
        return []

    # Deduplizieren: 50m-Bänder, höchste Böe gewinnt
    raw_anchors.sort(key=lambda a: a["elevation_m"])
    deduped = []
    for anchor in raw_anchors:
        band = anchor["elevation_m"] // _ANCHOR_BAND_WIDTH
        if deduped and (deduped[-1]["elevation_m"] // _ANCHOR_BAND_WIDTH) == band:
            # Gleiche Höhenband → konservativ: höchste Böe behalten
            if anchor["gust_kmh"] > deduped[-1]["gust_kmh"]:
                deduped[-1] = anchor
        else:
            deduped.append(anchor)

    return deduped


def estimate_altitude_gusts_multi_anchor(
    anchors,
    pressure_levels_data,
    elevation_ref,
    boundary_layer_height=None,
    region_id=None,
):
    """
    Berechnet Turbulenzrisiko T(z) mit mehreren Ankerpunkten (Multi-Anchor-Modell).

    - Zwischen Ankern: Lineare Interpolation des Gust-Excess (gust - wind_speed)
    - Über höchstem Anker: Gauss-Kernel Decay nach oben
    - Unter tiefstem Anker: Gauss-Kernel Decay nach unten
    - Constraint: gust >= wind_speed immer
    - PBL-Safety-Net: über PBL×1.2 → kein Gust-Excess

    Args:
        anchors: Sortierte Liste von Ankerpunkten [{elevation_m, gust_kmh, wind_speed_kmh}, ...]
        pressure_levels_data: Liste von Dicts mit {pressure, altitude, wind_speed, ...}
        elevation_ref: Referenzhöhe der Region (m MSL)
        boundary_layer_height: PBL-Höhe über Grund (m AGL), optional
        region_id: Regions-ID für terrain_type Lookup (optional)

    Returns:
        Liste von Dicts mit wind_gusts (=T(z)) und turbulence_excess Feldern
    """
    if not pressure_levels_data:
        return pressure_levels_data

    if not anchors:
        result = []
        for level in pressure_levels_data:
            entry = dict(level)
            entry["wind_gusts"] = entry.get("wind_speed", 0)
            entry["turbulence_excess"] = 0
            result.append(entry)
        return result

    L_up = get_L_up(elevation_ref, region_id)
    lowest = anchors[0]
    highest = anchors[-1]

    result = []
    for level in pressure_levels_data:
        entry = dict(level)
        altitude = entry.get("altitude", 0)
        wind_speed = entry.get("wind_speed", 0)

        # Bestimme Gust-Excess basierend auf Anker-Position
        if altitude <= lowest["elevation_m"]:
            # Unter tiefstem Anker: Gauss-Kernel Decay nach unten
            anchor_excess = max(0, lowest["gust_kmh"] - lowest["wind_speed_kmh"])
            dist = lowest["elevation_m"] - altitude
            decay = math.exp(-(dist * dist) / (2.0 * L_up * L_up))
            gust_excess = anchor_excess * decay
        elif altitude >= highest["elevation_m"]:
            # Über höchstem Anker: Gauss-Kernel Decay nach oben
            anchor_excess = max(0, highest["gust_kmh"] - highest["wind_speed_kmh"])
            dist = altitude - highest["elevation_m"]
            decay = math.exp(-(dist * dist) / (2.0 * L_up * L_up))
            gust_excess = anchor_excess * decay
        else:
            # Zwischen Ankern: lineare Interpolation des Gust-Excess
            gust_excess = _interpolate_excess_between_anchors(anchors, altitude)

        # PBL sigmoid blend: smooth transition instead of hard cutoff
        if boundary_layer_height is not None and boundary_layer_height > 0:
            pbl_cap = elevation_ref + boundary_layer_height * 1.2
            blend = 1.0 / (1.0 + math.exp((altitude - pbl_cap) / 75))
            gust_excess *= blend

        # Cap excess (same as single-anchor model)
        gust_excess = min(gust_excess, 30)
        entry["wind_gusts"] = round(max(wind_speed + gust_excess, wind_speed), 1)
        entry["turbulence_excess"] = round(gust_excess, 1)
        result.append(entry)

    return result


def _interpolate_excess_between_anchors(anchors, altitude):
    """Lineare Interpolation des Gust-Excess zwischen Ankerpunkten."""
    for i in range(len(anchors) - 1):
        low = anchors[i]
        high = anchors[i + 1]
        if low["elevation_m"] <= altitude <= high["elevation_m"]:
            dh = high["elevation_m"] - low["elevation_m"]
            if dh == 0:
                excess_low = max(0, low["gust_kmh"] - low["wind_speed_kmh"])
                return excess_low
            frac = (altitude - low["elevation_m"]) / dh
            excess_low = max(0, low["gust_kmh"] - low["wind_speed_kmh"])
            excess_high = max(0, high["gust_kmh"] - high["wind_speed_kmh"])
            return excess_low + frac * (excess_high - excess_low)
    # Sollte nicht erreicht werden (caller prüft Bereich)
    return 0


def interpolate_gust_from_anchors(anchors, target_altitude):
    """
    Gibt Böen-Schätzung auf einer beliebigen Höhe aus Ankerpunkten zurück.

    Verwendet für WIND-Klassifizierung auf Referenzhöhe in chat_engine.py.

    - Zwischen Ankern: lineare Interpolation der Böen
    - Unter tiefstem Anker: Wert des tiefsten Ankers
    - Über höchstem Anker: Wert des höchsten Ankers

    Args:
        anchors: Sortierte Liste [{elevation_m, gust_kmh, wind_speed_kmh}, ...]
        target_altitude: Zielhöhe (m MSL)

    Returns:
        (gust_kmh, wind_speed_kmh) Tuple oder (None, None) wenn keine Anker
    """
    if not anchors:
        return None, None

    if len(anchors) == 1:
        return anchors[0]["gust_kmh"], anchors[0]["wind_speed_kmh"]

    lowest = anchors[0]
    highest = anchors[-1]

    # Unter tiefstem Anker
    if target_altitude <= lowest["elevation_m"]:
        return lowest["gust_kmh"], lowest["wind_speed_kmh"]

    # Über höchstem Anker
    if target_altitude >= highest["elevation_m"]:
        return highest["gust_kmh"], highest["wind_speed_kmh"]

    # Zwischen Ankern: lineare Interpolation
    for i in range(len(anchors) - 1):
        low = anchors[i]
        high = anchors[i + 1]
        if low["elevation_m"] <= target_altitude <= high["elevation_m"]:
            dh = high["elevation_m"] - low["elevation_m"]
            if dh == 0:
                return low["gust_kmh"], low["wind_speed_kmh"]
            frac = (target_altitude - low["elevation_m"]) / dh
            gust = low["gust_kmh"] + frac * (high["gust_kmh"] - low["gust_kmh"])
            ws = low["wind_speed_kmh"] + frac * (high["wind_speed_kmh"] - low["wind_speed_kmh"])
            return round(gust, 1), round(ws, 1)

    return highest["gust_kmh"], highest["wind_speed_kmh"]


# ============================================================================
# OI-Korrektur auf Pressure-Levels (für chat_engine, spiegelt das Chart)
# ============================================================================

def _interp_ws_at(ws_pairs, target_alt):
    """Lineare Interpolation eines Werts aus sortierten (alt, value)-Paaren."""
    if not ws_pairs:
        return 0.0
    pts = sorted(ws_pairs, key=lambda x: x[0])
    if target_alt <= pts[0][0]:
        return pts[0][1]
    if target_alt >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        if pts[i][0] <= target_alt <= pts[i + 1][0]:
            dh = pts[i + 1][0] - pts[i][0]
            frac = (target_alt - pts[i][0]) / dh if dh > 0 else 0
            return pts[i][1] + frac * (pts[i + 1][1] - pts[i][1])
    return pts[-1][1]


def apply_oi_gust_correction(
    pressure_levels,
    anchors,
    elevation_ref,
    boundary_layer_height=None,
    region_id=None,
):
    """
    OI-(Optimal-Interpolation)-Korrektur des Böenprofils auf Pressure-Level-Höhen.

    Spiegelt das Verhalten von web.format_altitude_wind_for_charts (das auf
    einem 250m-Grid arbeitet), damit Region-Klassifizierer in chat_engine und
    Chart die gleichen Böenwerte an den gleichen Höhen sehen.

    Algorithmus:
    1. Sammle Anker und ersetze deren wind_speed durch den FREIATMOSPHÄRISCHEN
       Wind an der Ankerhöhe (interpoliert aus den Pressure-Level wind_speeds).
       Damit wird Doppelzählung des terrain-gedämpften 10m-Bodenwinds vermieden.
    2. Berechne pro Anker den Böen-Exzess (gust - free_atm_wind), capped at 30 km/h.
    3. Verteile den Exzess via asymmetrischem Gauss-Kernel auf jede Pressure-
       Level-Höhe (L_up aufwärts terrain-abhängig, L_down=H_g abwärts).
    4. wind_gusts = max(model_gust, ws + interpolated_excess).
    5. PBL sigmoid blend: über der PBL geht T(z) → W(z).

    Args:
        pressure_levels: Liste von Dicts (altitude, wind_speed, wind_gusts, ...).
            Typischerweise das Ergebnis von estimate_altitude_gusts_multi_anchor.
        anchors: Sortierte Liste [{elevation_m, gust_kmh, wind_speed_kmh}, ...].
            Beliebige Kombination aus Surface- und Spot-Ankern.
        elevation_ref: Referenzhöhe der Region/des Spots (m MSL) für L_up Lookup.
        boundary_layer_height: PBL-Höhe (m AGL), optional. Erweitert L_up
            terrain-abhängig (siehe get_effective_L_up): in flachem Mittelland
            kein BLH-Boost, im Hochalpinen volle Kopplung. Vermeidet die
            Vermischung von Reibungs-Korrelationslänge und konvektiver
            Mischschicht im Flachland.
        region_id: Regions-ID für terrain_type Lookup (optional).

    Returns:
        Neue Liste von Pressure-Level-Dicts mit OI-korrigierten wind_gusts und
        turbulence_excess Feldern (kopiert die Eingabe-Dicts).
    """
    if not pressure_levels:
        return pressure_levels
    if not anchors:
        return pressure_levels

    # Nach Höhe aufsteigend sortieren (für Running-Max bottom-to-top)
    levels_sorted = sorted(
        (dict(lv) for lv in pressure_levels),
        key=lambda l: l.get("altitude", 0),
    )

    # Free-atmosphere wind speed pairs (für Interpolation an Anker-Höhen)
    ws_pairs = [(lv.get("altitude", 0), lv.get("wind_speed", 0)) for lv in levels_sorted]

    # Anker mit free-atmosphere wind_speed (statt terrain-gedämpftem 10m-Wind)
    obs_excess = []  # [(elev, excess_kmh), ...]
    for a in anchors:
        elev = a.get("elevation_m")
        gust = a.get("gust_kmh")
        if elev is None or gust is None:
            continue
        ws_free = _interp_ws_at(ws_pairs, elev)
        excess = max(0.0, float(gust) - float(ws_free))
        # Cap excess (gleiche Logik wie estimate_altitude_gusts_multi_anchor)
        excess = min(excess, 30.0)
        obs_excess.append((elev, excess))

    if not obs_excess:
        return pressure_levels

    # OI-Korrelationslängen (terrain-abhängig).
    # L_up wird via get_effective_L_up gerechnet — terrain-gewichteter
    # BLH-Boost statt blindem max(L_up, BLH).
    _, L_down = get_oi_scale_lengths(elevation_ref, region_id)
    L_up = get_effective_L_up(elevation_ref, region_id, boundary_layer_height)

    # Pro Pressure-Level: Gauss-gewichteter Exzess aus allen Ankern
    for lv in levels_sorted:
        z = lv.get("altitude", 0)
        ws = lv.get("wind_speed", 0)
        gust_bg = lv.get("wind_gusts", ws)

        w_sum = 0.0
        excess_sum = 0.0
        for z_a, exc in obs_excess:
            dz = z - z_a
            # Asymmetrischer Kernel: breit aufwärts, eng abwärts
            L = L_up if dz >= 0 else L_down
            w = math.exp(-(dz * dz) / (2.0 * L * L))
            w_sum += w
            excess_sum += w * exc
        excess_weighted = excess_sum / max(1.0, w_sum)
        gust_oi = ws + excess_weighted

        # PBL sigmoid blend (gleiches Verhalten wie estimate_altitude_gusts_multi_anchor)
        if boundary_layer_height is not None and boundary_layer_height > 0:
            pbl_cap = elevation_ref + boundary_layer_height * 1.2
            blend = 1.0 / (1.0 + math.exp((z - pbl_cap) / 75))
            gust_oi = ws + (gust_oi - ws) * blend

        gust_final = max(gust_bg, gust_oi)
        lv["wind_gusts"] = round(gust_final, 1)
        lv["turbulence_excess"] = round(max(0.0, gust_final - ws), 1)

    # Running-Maximum wurde entfernt: OI-Gauss + PBL-Sigmoid produzieren bereits
    # eine monoton abklingende T(z)-Kurve. Running-Max zog lokale Wind-Dips
    # (W(z)-Shear) künstlich hoch und verletzte die Asymmetrie von L_up/L_down.
    # Höhenböen folgen jetzt reiner Gauss-Decay oberhalb des Ankers.

    return levels_sorted
