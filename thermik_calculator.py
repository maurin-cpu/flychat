import math
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# METEOROLOGISCHE KONSTANTEN (physikalisch, nicht konfigurierbar)
# ============================================================================
G = 9.81              # Erdbeschleunigung (m/s^2)
CP = 1005.0           # Spezifische Wärmekapazität trockener Luft (J/(kg*K))
R_D = 287.05          # Gaskonstante für trockene Luft (J/(kg*K))
L_V = 2.5e6           # Verdampfungswärme Wasser (J/kg)
DALR = 0.0098         # Trockenadiabatischer Temperaturgradient (K/m) (~1°C/100m)
SALR = 0.006          # Feuchtadiabatischer Gradient (K/m) (vereinfacht, ~0.6°C/100m)
RHO = 1.1             # Vereinfachte Luftdichte auf typischer Starthöhe (kg/m^3)
MU = 0.0002           # Entrainment-Rate (m^-1) - Rate der Einmischung von Umgebungsluft


def _get_season(timestamp: str) -> str:
    """Bestimmt die Jahreszeit aus einem Timestamp."""
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        month = dt.month
        if month in (12, 1, 2):
            return "winter"
        elif month in (3, 4, 5):
            return "spring"
        elif month in (6, 7, 8):
            return "summer"
        else:
            return "autumn"
    except Exception:
        return "spring"  # Fallback


def _get_thermal_param(key: str, timestamp: str = None, default=None):
    """Holt einen Thermik-Parameter aus config.py, jahreszeitabhängig wenn nötig."""
    try:
        from config import THERMAL_PARAMS
        value = THERMAL_PARAMS.get(key, default)
        if isinstance(value, dict) and timestamp:
            season = _get_season(timestamp)
            return value.get(season, default)
        return value
    except ImportError:
        return default


def _terrain_factor(elevation_m: float) -> float:
    """
    Gibt einen Faktor 0.0 (Mittelland) bis 1.0 (Alpin) zurück,
    basierend auf der Elevation. Lineare Interpolation zwischen den
    konfigurierten Schwellen.

    Beispiele:
      730m (Uetliberg)  → 0.0  (reine Mittelland-Parameter)
      947m (Zugerberg)  → 0.15 (leicht alpin)
      1800m (Engelberg) → 1.0  (volle Alpin-Parameter)
      2120m (First)     → 1.0  (volle Alpin-Parameter)
    """
    elev_low = _get_thermal_param("terrain_elev_low", default=800)
    elev_high = _get_thermal_param("terrain_elev_high", default=1800)
    if elevation_m <= elev_low:
        return 0.0
    elif elevation_m >= elev_high:
        return 1.0
    else:
        return (elevation_m - elev_low) / (elev_high - elev_low)


def _compute_free_atm_gamma(profile: List[Dict], blh_msl: float, elevation_m: float) -> float:
    """
    Berechnet den potentiellen Temperatur-Gradienten (γ_θ) der freien Atmosphaere
    oberhalb der aktuellen BLH. Fuer das Encroachment-Modell (Tennekes 1973).

    γ_θ = dT/dz + DALR   (K/m)

    Groesseres γ_θ = stabilere Atmosphaere = langsameres BLH-Wachstum.
    """
    ref_height = max(blh_msl, elevation_m + 200)
    above = sorted(
        [p for p in profile if p['height'] > ref_height
         and p.get('temp') is not None],
        key=lambda p: p['height']
    )

    if len(above) < 2:
        return 0.004  # Fallback: typische Stabilitaet (leicht stabil)

    # Gradient ueber 2-3 Schichten fuer Robustheit
    p_low = above[0]
    p_high = above[min(2, len(above) - 1)]
    dh = p_high['height'] - p_low['height']

    if dh < 100:
        return 0.004

    dT_dz = (p_high['temp'] - p_low['temp']) / dh   # negativ bei normalem Lapse Rate
    gamma_theta = dT_dz + DALR                        # potentieller Temp-Gradient

    # Clamp: min 0.002 (sehr instabil), max 0.020 (starke Inversion)
    return max(0.002, min(0.020, gamma_theta))


def calculate_dewpoint(temp_c: float, rh_percent: float) -> float:
    """Berechnet den Taupunkt mittels Magnus-Formel."""
    if temp_c is None or rh_percent is None or rh_percent <= 0:
        return None
    A = 17.625
    B = 243.04
    alpha = math.log(rh_percent / 100.0) + ((A * temp_c) / (B + temp_c))
    return (B * alpha) / (A - alpha)


def calculate_lcl_approx(temp_c: float, dewpoint_c: float, elevation_m: float) -> float:
    """Näherungsweise Berechnung des Lifting Condensation Level (Wolkenbasis in m.ü.M.).
    Faustregel: (T - Td) * 125 = LCL in Metern über Grund."""
    if temp_c is None or dewpoint_c is None:
        return None
    spread = max(0, temp_c - dewpoint_c)
    lcl_agl = spread * 125.0
    return elevation_m + lcl_agl


def estimate_sensible_heat_flux(shortwave_radiation: float, sunshine_duration_s: float,
                                timestamp: str = None) -> float:
    """
    Fallback-Schätzung des sensiblen Wärmeflusses (H) aus der Globalstrahlung.

    Physikalische Herleitung:
      Rn ≈ 0.60-0.70 × SW (nach Albedo + Langwellen-Verlust)
      H/Rn ≈ 0.30-0.45 (Bowen-Ratio, jahreszeitabhängig)
      → H ≈ 0.15-0.30 × SW (je nach Jahreszeit)

    Koeffizient wird jahreszeitabhängig aus config.THERMAL_PARAMS geladen.
    """
    if shortwave_radiation is None or shortwave_radiation <= 0:
        return 0.0
    coeff = _get_thermal_param("global_radiation_to_H", timestamp, default=0.20)
    return shortwave_radiation * coeff


def calculate_topography_bonus(
    timestamp: str,
    slope_azimuth: float,
    slope_angle: float,
    lat: float = 46.8  # Mittelwert Schweiz
) -> float:
    """
    Berechnet den dynamischen Sonnen-Einstrahlungsbonus für einen Hang im Vergleich zum Flachland.
    Gibt einen Faktor zurück (z.B. 1.0 für Flachland, 1.8 für einen Südhang im Winter).
    """
    if not timestamp or slope_azimuth is None or slope_angle is None or slope_angle == 0:
        return 1.0

    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        doy = dt.timetuple().tm_yday
        
        # Sonnen-Deklination (delta) in Rad
        delta_deg = -23.44 * math.cos(math.radians((360.0 / 365.0) * (doy + 10)))
        delta = math.radians(delta_deg)
        
        # Hour Angle (h) in Rad (Grobe Näherung basierend auf UTC Stunde + Lon Korrektur)
        solar_hour = dt.hour + (8.5 / 15.0) # ~Lokalzeit Zürich
        h_deg = 15.0 * (solar_hour - 12.0)
        h = math.radians(h_deg)
        
        phi = math.radians(lat)
        beta = math.radians(slope_angle)
        
        # Umrechnung slope_azimuth (0=N, 90=E, 180=S, 270=W) in Formel-Azimuth (0=Süd, West=positiv)
        gamma_deg = slope_azimuth - 180.0
        gamma = math.radians(gamma_deg)
        
        # Solare Elevation (alpha) für flachen Boden
        sin_alpha = math.sin(phi)*math.sin(delta) + math.cos(phi)*math.cos(delta)*math.cos(h)
        
        if sin_alpha <= 0.05: # unter ~3 Grad (Sonne geht auf/unter oder ist dunkel)
            return 1.0
            
        # Einfallswinkel auf dem Hang (cos_theta)
        term1 = math.sin(delta)*math.sin(phi)*math.cos(beta)
        term2 = -math.sin(delta)*math.cos(phi)*math.sin(beta)*math.cos(gamma)
        term3 = math.cos(delta)*math.cos(phi)*math.cos(beta)*math.cos(h)
        term4 = math.cos(delta)*math.sin(phi)*math.sin(beta)*math.cos(gamma)*math.cos(h)
        term5 = math.cos(delta)*math.sin(beta)*math.sin(gamma)*math.sin(h)
        
        cos_theta = term1 + term2 + term3 + term4 + term5
        
        if cos_theta <= 0:
            return 0.5 # Hang liegt im Schatten -> Thermik deutlich schlechter als im Flachland
            
        # Bonus berechnen: Verhältnis Hang-Strahlung zu Flachland-Strahlung
        bonus = cos_theta / sin_alpha

        # Cap aus Config (Default 1.3 — Hang-Enhancement für Konvektion ist moderat)
        topo_max = _get_thermal_param("topo_bonus_max", timestamp, default=1.3)
        return min(topo_max, max(0.5, bonus))
        
    except Exception as e:
        logger.error(f"Fehler in calculate_topography_bonus: {e}")
        return 1.0


def calculate_seasonal_bowen_ratio_adjustment(timestamp: str) -> float:
    """
    Berechnet einen Faktor zur Anpassung des Sensiblen Wärmeflusses (H) basierend 
    auf dem saisonalen Vegetationszyklus (Verdunstung via Pflanzen / Latent Heat).
    """
    if not timestamp:
        return 1.0
        
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        doy = dt.timetuple().tm_yday
        
        # Saisonale Logik (Mitteleuropa):
        # Jan-Mrz (1-90): Boden feucht, aber keine Pflanzen -> 1.0
        # Apr-Jun (90-180): Starkes Pflanzenwachstum ("Lush Vegetation"), saugt Wasser -> verdunstet viel -> H sinkt
        # Jul-Sep (181-270): Trockenere Böden, reife Pflanzen -> H steigt an (Autumn Bonus)
        # Okt-Dez (271-365): Pflanzen tot, H normal -> 1.0
        
        if 90 <= doy < 180:
            # Linearer Drop bis Mitte Mai (DOY 135 -> 0.85), dann Erholung
            if doy < 135:
                return 1.0 - 0.15 * ((doy - 90) / 45.0)
            else:
                return 0.85 + 0.15 * ((doy - 135) / 45.0)
        elif 180 <= doy < 270:
            # Linearer Anstieg bis Mitte August (DOY 225 -> 1.15), dann Drop
            if doy < 225:
                return 1.0 + 0.15 * ((doy - 180) / 45.0)
            else:
                return 1.15 - 0.15 * ((doy - 225) / 45.0)
        else:
            return 1.0
    except Exception:
        return 1.0


def interpolate_temp_at_height(elevation_ref: float, profile: List[Dict]) -> Optional[float]:
    """
    Elevated Heat Source: Interpoliert die Temperatur auf der Referenzhöhe
    aus dem vertikalen Temperaturprofil (Druckniveau-Daten).

    Für alpine Startplätze ist das entscheidend, da temperature_2m sich auf das
    Modellgelände bezieht (oft im Tal), während der Startplatz höher liegt.
    Wir interpolieren linear zwischen den beiden Druckniveaus, die die
    Referenzhöhe einschliessen.

    Args:
        elevation_ref: Referenzhöhe des Startplatzes (m MSL)
        profile: Liste von {'height': m, 'temp': °C} Dictionaries

    Returns:
        Interpolierte Temperatur in °C oder None wenn keine Daten verfügbar
    """
    if not profile:
        return None

    sorted_p = sorted(
        [p for p in profile if p.get('height') is not None and p.get('temp') is not None],
        key=lambda x: x['height']
    )
    if not sorted_p:
        return None

    # Finde die zwei Schichten, die elevation_ref einschliessen
    below = None
    above = None
    for layer in sorted_p:
        if layer['height'] <= elevation_ref:
            below = layer
        elif above is None:
            above = layer

    # Randfall: elevation_ref liegt unter oder über allen Profildaten
    if below is None and above is None:
        return None
    if below is None:
        return above['temp']
    if above is None:
        return below['temp']

    # Lineare Interpolation zwischen den beiden einschliessenden Schichten
    dh = above['height'] - below['height']
    if dh <= 0:
        return below['temp']
    frac = (elevation_ref - below['height']) / dh
    return below['temp'] + frac * (above['temp'] - below['temp'])


def calculate_thermic_clouds(low_clouds: float, mid_clouds: float, high_clouds: float) -> dict:
    """
    Berechnet die thermisch relevante Bewölkung und einen Anzeige-Sonnenindex.
    Gewichtung nach Regtherm-Logik: Tiefe Wolken blockieren Einstrahlung fast komplett (100%),
    mittlere teilweise (50%), hohe Cirren dämpfen nur leicht (10%).

    sun_index = 100 - display_cloud (100 = klar). sun_factor = 0.5 + 0.5 * (sun_index/100)
    linear 0.5..1.0 — nur für Anzeige/Diagnostik; die Steigrate wird nicht damit multipliziert
    (Bewölkung steckt bereits in H über die modellierte Strahlung).
    """
    low = low_clouds or 0.0
    mid = mid_clouds or 0.0
    high = high_clouds or 0.0

    display_cloud = (low * 1.0) + (mid * 0.5) + (high * 0.1)
    display_cloud = max(0.0, min(100.0, display_cloud))

    sun_index = 100.0 - display_cloud
    sun_factor = 0.5 + 0.5 * (sun_index / 100.0)

    return {
        'display_cloud': display_cloud,
        'sun_index': sun_index,
        'sun_factor': sun_factor
    }


def calculate_thermal_profile(
    surface_temp: float,
    surface_dewpoint: float,
    elevation_m: float,
    pressure_levels_data: List[Dict],
    boundary_layer_height_agl: float = None,
    sunshine_duration_s: float = None,
    surface_sensible_heat_flux: float = None,
    surface_latent_heat_flux: float = None,
    shortwave_radiation: float = None,
    direct_radiation: float = None,
    diffuse_radiation: float = None,
    soil_moisture: float = None,
    soil_temperature: float = None,
    updraft: float = None,
    et0: float = None,
    vpd: float = None,
    lifted_index: float = None,
    convective_inhibition: float = None,
    snow_depth: float = None,
    timestamp: str = None,
    slope_azimuth: float = None,
    slope_angle: float = None,
    low_cloud: float = 0,
    mid_cloud: float = 0,
    high_cloud: float = 0,
    boundary_layer_height_gfs: float = None,
    previous_max_height: float = None,
    cumulative_buoyancy: float = None,
    peak_H: float = None,
    peak_shortwave: float = None,
) -> Dict:
    """
    Berechnet das Thermik-Profil mit physikalisch fundiertem Modell.

    Implementiert folgende Konzepte (angelehnt an RegTherM):
    1. Elevated Heat Source - Paketaufstieg startet auf Referenzhöhe (elevation_m)
    2. Entrainment - Einmischung von Umgebungsluft (mu = 0.0002 m^-1)
    3. Deardorff w* - Konvektionsgeschwindigkeit aus sensiblem Wärmefluss
    4. Dual w*-Strategie - Minimum aus Parcel-w* und Deardorff-w* (konservativ)
    5. Bodenfeuchte-Bremse - Rating-Reduktion bei nassem Boden (LE > H)

    Args:
        surface_temp: Temperatur 2m über Grund am Gitterpunkt (°C)
        surface_dewpoint: Taupunkt am Startplatz (°C)
        elevation_m: Referenzhöhe des Startplatzes (m MSL)
        pressure_levels_data: Liste von {'height', 'temp', 'pressure'} Dictionaries
        boundary_layer_height_agl: Grenzschichthöhe über Grund (m)
        sunshine_duration_s: Sonnenscheindauer in Sekunden (0-3600)
        surface_sensible_heat_flux: Sensibler Wärmefluss (W/m²), positiv = aufwärts
        surface_latent_heat_flux: Latenter Wärmefluss (W/m²), positiv = aufwärts
        shortwave_radiation: Globalstrahlung (W/m²) - für Fallback-Schätzung von H

    Returns:
        Dict mit max_height, lcl, climb_rate, rating, ti_profile, diagnostics, data_warnings
    """
    data_warnings = []

    if surface_temp is None:
        return {'error': 'Fehlende Bodentemperatur'}

    # Profil sortiert von unten nach oben (nur gültige Einträge)
    profile = sorted(
        [p for p in pressure_levels_data
         if p.get('height') is not None and p.get('temp') is not None],
        key=lambda x: x['height']
    )

    # =========================================================================
    # 1. ELEVATED HEAT SOURCE + SOLARE ÜBERHITZUNG
    # =========================================================================
    # XC Therm / Burnair Methode: Die Erdoberfläche heizt die bodennahe Luft
    # über die gemessene 2m-Temperatur hinaus auf ("superadiabatische Schicht").
    # Ein Thermikschlauch startet mit dieser überhitzten Temperatur, NICHT mit
    # der Umgebungstemperatur. Der Überschuss ΔT hängt vom sensiblen Wärmefluss ab.
    #
    # Physik: ΔT_excess ≈ H / (ρ · cp · w_mix)
    #   mit w_mix ≈ 0.5-1.0 m/s (konvektive Mischgeschwindigkeit)
    #   → bei H=240 W/m²: ΔT ≈ 240 / (1.225 · 1005 · 0.8) ≈ 0.24°C pro 1 W/m² ≈ 2.4°C
    #
    # Empirisch kalibriert: ΔT = min(5, H / 80)
    #   H=100 → +1.3°C, H=200 → +2.5°C, H=300 → +3.8°C, H=400 → +5°C
    
    start_temp = interpolate_temp_at_height(elevation_m, profile)
    if start_temp is None:
        start_temp = surface_temp
        data_warnings.append(
            "Keine Profildaten für Starthöhe verfügbar - nutze temperature_2m als Fallback"
        )

    # =========================================================================
    # 2. SENSIBLER WÄRMEFLUSS (H) - mit zweistufigem Fallback
    # =========================================================================
    # Primär: surface_sensible_heat_flux direkt von der API (z.B. icon_seamless)
    # Fallback: Empirische Schätzung aus Globalstrahlung × 0.3 × Sonnenfaktor
    H = surface_sensible_heat_flux
    h_is_estimated = False

    # Prüfe ob H gültig ist (nicht None, nicht NaN)
    h_valid = H is not None and not (isinstance(H, float) and math.isnan(H))

    if not h_valid:
        # Fallback 1: Bessere Schätzung aus direkter + diffuser Strahlung
        if direct_radiation is not None and diffuse_radiation is not None:
            # --- PHYSIKALISCHE H-BERECHNUNG ---
            # 1. Topografie-Bonus (nur gedämpfter Anteil wirkt auf konvektive Thermik)
            raw_topo_bonus = calculate_topography_bonus(timestamp, slope_azimuth, slope_angle)
            topo_H_fraction = _get_thermal_param("topo_bonus_H_fraction", timestamp, default=0.3)
            # Effektiver Topo-Bonus: z.B. raw=1.5 → eff = 1.0 + (1.5-1.0)*0.3 = 1.15
            effective_topo = 1.0 + (raw_topo_bonus - 1.0) * topo_H_fraction

            # 2. Saisonale Bowen-Ratio (Vegetationszyklus)
            veg_factor = calculate_seasonal_bowen_ratio_adjustment(timestamp)

            # 3. Strahlungskoeffizienten aus Config (jahreszeitabhängig, physikalisch hergeleitet)
            dir_coeff = _get_thermal_param("direct_radiation_to_H", timestamp, default=0.25)
            diff_coeff = _get_thermal_param("diffuse_radiation_to_H", timestamp, default=0.10)

            dir_h = direct_radiation * dir_coeff * effective_topo
            diff_h = diffuse_radiation * diff_coeff

            H = (dir_h + diff_h) * veg_factor

            # H-Cap: terrain-aware (Mittelland vs. Alpin)
            h_cap_base = _get_thermal_param("H_cap", timestamp, default=220)
            h_cap_alpine = _get_thermal_param("alpine_H_cap", timestamp, default=280)
            t_factor = _terrain_factor(elevation_m)
            h_cap = h_cap_base + t_factor * (h_cap_alpine - h_cap_base)
            H = min(h_cap, H)

            if H > 0:
                data_warnings.append(
                    f"H geschätzt: {H:.0f} W/m² (dir={direct_radiation:.0f}×{dir_coeff}, diff={diffuse_radiation:.0f}×{diff_coeff}) "
                    f"| Topo: {raw_topo_bonus:.2f}→eff {effective_topo:.2f}x | Veg: {veg_factor:.2f}x"
                )
        else:
            # Fallback 2: Pauschale Schätzung aus Globalstrahlung
            raw_topo_bonus = calculate_topography_bonus(timestamp, slope_azimuth, slope_angle)
            topo_H_fraction = _get_thermal_param("topo_bonus_H_fraction", timestamp, default=0.3)
            # 60% Direkt, 40% Diffus → gemischter Topo-Effekt (nur Direktanteil)
            mixed_topo = 1.0 + (raw_topo_bonus - 1.0) * topo_H_fraction * 0.6
            veg_factor = calculate_seasonal_bowen_ratio_adjustment(timestamp)

            H = estimate_sensible_heat_flux(shortwave_radiation, sunshine_duration_s, timestamp)
            H *= mixed_topo
            H *= veg_factor

            h_cap_base = _get_thermal_param("H_cap", timestamp, default=220)
            h_cap_alpine = _get_thermal_param("alpine_H_cap", timestamp, default=280)
            t_factor = _terrain_factor(elevation_m)
            h_cap = h_cap_base + t_factor * (h_cap_alpine - h_cap_base)
            H = min(h_cap, H)

            if H > 0:
                data_warnings.append(
                    f"H aus Globalstrahlung geschätzt: {H:.0f} W/m² "
                    f"| Topo(mix): {mixed_topo:.2f}x | Veg: {veg_factor:.2f}x"
                )
        if H <= 0 and h_is_estimated:
            data_warnings.append(
                "Kein sensibler Wärmefluss verfügbar (weder API noch Strahlung)"
            )

    # Negativen Flux abfangen (nachts fliesst Wärme vom Boden ab -> keine Thermik)
    H = max(0.0, H)

    # =========================================================================
    # 2.5 SCHNEEDECKEN-BLOCKADE (Albedo & Schmelzwärme)
    # =========================================================================
    # Terrain-differenzierte Schnee-Dämpfung:
    # Mittelland: Flache Wiesen unter Schnee → 80% Reduktion (H*0.20, max 50 W/m²)
    # Alpin: Mischoberflächen (Felswände + Schnee) → 50% Reduktion (H*0.50, max 150 W/m²)
    if snow_depth is not None and snow_depth > 0.05:  # > 5cm Schnee
        t_factor = _terrain_factor(elevation_m)
        # Interpoliere zwischen Mittelland (0.20) und Alpin (0.50) Dämpfung
        mittelland_damping = 0.20
        alpine_damping = _get_thermal_param("alpine_snow_damping_factor", timestamp, default=0.50)
        snow_factor = mittelland_damping + t_factor * (alpine_damping - mittelland_damping)
        # Interpoliere H-Max zwischen Mittelland (50) und Alpin (150)
        mittelland_h_max = 50.0
        alpine_h_max = _get_thermal_param("alpine_snow_H_max", timestamp, default=150)
        snow_h_max = mittelland_h_max + t_factor * (alpine_h_max - mittelland_h_max)
        H = min(snow_h_max, H * snow_factor)
        data_warnings.append(
            f"Schneedecke ({snow_depth:.2f}m): H auf {H:.0f} W/m² reduziert "
            f"(Terrain-Faktor={t_factor:.2f}, Damping={snow_factor:.0%})"
        )

    # =========================================================================
    # 3. LATENTER WÄRMEFLUSS (LE) - für Bodenfeuchte-Bremse
    # =========================================================================
    # Der latente Wärmefluss zeigt, wieviel Energie in Verdunstung geht.
    # Fehlt dieser Wert, überspringen wir die Bodenfeuchte-Bremse.
    LE = surface_latent_heat_flux
    le_valid = LE is not None and not (isinstance(LE, float) and math.isnan(LE))

    if not le_valid:
        # Fallback: LE aus Bodenfeuchte schätzen
        # ACHTUNG: soil_moisture_0_to_1cm (oberste 1cm) ist IMMER relativ feucht
        # (typisch 0.15-0.25 bei normalen Bedingungen). Die Bodenfeuchte-Bremse
        # soll nur bei wirklich nassem Boden greifen (z.B. nach Regen, SM > 0.35).
        # Daher: Linearer Ansatz mit konservativem Schwellwert.
        if soil_moisture is not None and H > 0:
            # Unter 0.30: normaler Boden -> kaum Verdunstungseffekt
            # 0.30-0.45: zunehmend nass -> LE steigt linear bis 2*H
            # Über 0.45: gesättigt -> LE = 2*H (Bremse feuert)
            if soil_moisture > 0.30:
                moisture_excess = min(1.0, (soil_moisture - 0.30) / 0.15)
                LE = moisture_excess * 2.0 * H
                le_valid = True
                data_warnings.append(
                    f"LE aus Bodenfeuchte geschätzt: {LE:.0f} W/m² "
                    f"(soil_moisture={soil_moisture:.3f}, nass={moisture_excess:.2f})"
                )
            else:
                # Normaler Boden: LE niedrig, keine Bremse
                LE = soil_moisture / 0.30 * 0.3 * H  # max 30% von H
                le_valid = False  # Nicht genug für Bremse
        else:
            LE = 0.0
            data_warnings.append(
                "Latenter Wärmefluss nicht verfügbar - Bodenfeuchte-Bremse wird übersprungen"
            )

    # =========================================================================
    # 4. LCL (Wolkenbasis) berechnen
    # =========================================================================
    lcl_msl = None
    if surface_dewpoint is not None:
        lcl_msl = calculate_lcl_approx(start_temp, surface_dewpoint, elevation_m)

    # =========================================================================
    # 5. PAKETAUFSTIEG MIT ENTRAINMENT (Schicht für Schicht)
    # =========================================================================
    # Terrain-differenzierte Entrainment-Rate:
    #   Mittelland (MU=0.0002): Mehr Einmischung, weniger organisierte Thermik
    #   Alpin (MU=0.00015): Weniger Einmischung, Talwindsysteme + Felswände
    #     erzeugen organisiertere, stärkere Thermik-Schläuche
    t_factor = _terrain_factor(elevation_m)
    alpine_mu = _get_thermal_param("alpine_MU", timestamp, default=0.00015)
    effective_mu = MU + t_factor * (alpine_mu - MU)  # 0.0002 → 0.00015

    # Cumulus-Entrainment: Über LCL reduzierte Einmischung (Morrison et al. 2021)
    # Feuchte Thermiken breiten sich 1.7x weniger aus → kompakterer Kern
    moist_mu_factor = _get_thermal_param("moist_entrainment_factor", timestamp, default=0.6)
    effective_mu_moist = effective_mu * moist_mu_factor

    ti_profile = []
    max_thermal_height = elevation_m
    cumulative_temp_diff = 0.0
    valid_layers = 0

    parcel_temp = start_temp
    prev_height = elevation_m

    for layer in profile:
        h = layer['height']
        if h <= elevation_m:
            continue

        env_temp = layer['temp']
        dh = h - prev_height

        if dh <= 0:
            continue

        # --- Adiabatischer Aufstieg mit Entrainment ---
        # Über LCL: reduzierte Entrainment (feuchte Thermiken mischen weniger)
        if lcl_msl and h > lcl_msl:
            if prev_height < lcl_msl:
                # Übergangsschicht: Trocken bis LCL, dann feucht darüber
                dh_dry = lcl_msl - prev_height
                dh_moist = h - lcl_msl
                # Trockenadiabatischer Teil + normale Entrainment
                parcel_temp = (parcel_temp
                               - DALR * dh_dry
                               - effective_mu * (parcel_temp - env_temp) * dh_dry)
                # Feuchtadiabatischer Teil + reduzierte Entrainment
                parcel_temp = (parcel_temp
                               - SALR * dh_moist
                               - effective_mu_moist * (parcel_temp - env_temp) * dh_moist)
            else:
                # Komplett über LCL: feuchtadiabatisch + reduzierte Entrainment
                parcel_temp = (parcel_temp
                               - SALR * dh
                               - effective_mu_moist * (parcel_temp - env_temp) * dh)
        else:
            # Unter LCL: trockenadiabatisch + normale Entrainment
            parcel_temp = (parcel_temp
                           - DALR * dh
                           - effective_mu * (parcel_temp - env_temp) * dh)

        # Thermal Index (TI) = Umgebung minus Paket
        # Negativer TI = Paket ist WÄRMER als Umgebung = STEIGEN!
        ti = env_temp - parcel_temp
        ti_profile.append({
            'height': h,
            'pressure': layer.get('pressure'),
            'parcel_temp': round(parcel_temp, 2),
            'env_temp': env_temp,
            'ti': round(ti, 2)
        })

        # Prüfe ob das Paket noch steigt (0.5K Toleranz für Trägheit der Blase)
        if parcel_temp >= env_temp - 0.5:
            max_thermal_height = h
            cumulative_temp_diff += (parcel_temp - env_temp)
            valid_layers += 1
        else:
            # Inversion oder Sperrschicht erreicht -> Thermik-Obergrenze
            break

        prev_height = h

    # =========================================================================
    # 5b. SOLARE ÜBERHITZUNG → PARCEL-BASIERTE BLH
    # =========================================================================
    # Der solare Überschuss macht das Paket wärmer als die Umgebung.
    # Die Höhe, wo das Paket die Umgebungstemperatur erreicht, ist die
    # konvektive Grenzschichthöhe (CBL). Diese Methode braucht kein Modell-BLH!
    #
    # Wenn der erste Aufstieg keine Instabilität fand (max_thermal_height < 350m über Start),
    # führen wir einen ZWEITEN Aufstieg mit überhitztem Paket durch.
    
    parcel_found_instability = (max_thermal_height - elevation_m) > 350
    dt_excess = 0.0
    
    if not parcel_found_instability and H > 30:
        # Berechne solaren Überschuss (aus Config)
        solar_max = _get_thermal_param("solar_excess_max_C", timestamp, default=1.5)
        solar_div = _get_thermal_param("solar_excess_H_divisor", timestamp, default=200)
        if snow_depth is not None and snow_depth > 0.05:
            dt_excess = 0.0
            data_warnings.append("Keine solare Überhitzung möglich wegen Schneedecke.")
        else:
            dt_excess = min(solar_max, H / solar_div)
            
        heated_start = start_temp + dt_excess
        
        # Zweiter Paketaufstieg mit überhitzter Starttemperatur
        parcel_temp_h = heated_start
        prev_height_h = elevation_m
        max_thermal_height = elevation_m
        cumulative_temp_diff = 0.0
        valid_layers = 0
        ti_profile = []  # Reset TI-Profil
        
        for layer in profile:
            h = layer['height']
            if h <= elevation_m:
                continue
            env_temp = layer['temp']
            dh = h - prev_height_h
            if dh <= 0:
                continue
            
            # Adiabatischer Aufstieg (vereinfacht ohne Entrainment für BLH-Bestimmung)
            if lcl_msl and h > lcl_msl:
                if prev_height_h < lcl_msl:
                    dh_dry = lcl_msl - prev_height_h
                    dh_moist = h - lcl_msl
                    parcel_temp_h -= DALR * dh_dry + SALR * dh_moist
                else:
                    parcel_temp_h -= SALR * dh
            else:
                parcel_temp_h -= DALR * dh
            
            # Entrainment für 2. Aufstieg (terrain-aware, mit Config-Faktor)
            # Über LCL: zusätzlich reduziert (feuchte Thermiken mischen weniger)
            mu_factor = _get_thermal_param("second_ascent_entrainment_factor", timestamp, default=1.0)
            mu_light = effective_mu * mu_factor
            if lcl_msl and h > lcl_msl:
                mu_light *= moist_mu_factor
            parcel_temp_h -= mu_light * (parcel_temp_h - env_temp) * dh
            
            ti = env_temp - parcel_temp_h
            ti_profile.append({
                'height': h,
                'pressure': layer.get('pressure'),
                'parcel_temp': round(parcel_temp_h, 2),
                'env_temp': env_temp,
                'ti': round(ti, 2)
            })
            
            if parcel_temp_h >= env_temp - 0.3:  # Engere Toleranz bei überhitztem Paket
                max_thermal_height = h
                cumulative_temp_diff += (parcel_temp_h - env_temp)
                valid_layers += 1
            else:
                break
            
            prev_height_h = h
        
    # =========================================================================
    # 5c. BLH-PLAUSIBILISIERUNG & CROSS-CHECK (GFS)
    # =========================================================================
    # Wir nutzen primär die eigene Parcel-Berechnung (max_thermal_height).
    # GFS dient nur noch als Vergleich (Cross-Check).
    
    if boundary_layer_height_gfs is not None and surface_temp is not None and start_temp is not None:
        # GFS Boden-Niveau schätzen (Gradient ca. 0.8°C/100m)
        dt_gfs = surface_temp - start_temp
        model_elev_diff = dt_gfs / 0.008  
        gfs_surface_msl = min(elevation_m, elevation_m - model_elev_diff)
        gfs_blh_msl = gfs_surface_msl + boundary_layer_height_gfs
        
        # Cross-Check gegen Parcel-Ergebnis
        diff = abs(max_thermal_height - gfs_blh_msl)
        if diff >= 1000:
            data_warnings.append(f"Info: GFS-Modell weicht stark ab (Diff={diff:.0f}m).")

    # H-basierte Fallback-Schaetzung der Thermiktiefe
    # Greift wenn weder Parcel noch BLH verfügbar, aber Sonne heizt.
    if max_thermal_height <= elevation_m and H > 50:
        z_i_est = int(min(2000, max(300, H * 5)))
        max_thermal_height = elevation_m + z_i_est
        data_warnings.append(
            f"H-Schaetzung: Thermiktiefe ~{z_i_est}m (H={H:.0f} W/m²)"
        )

    # =========================================================================
    # 5e. ENCROACHMENT-MODELL (Carson/Tennekes 1973)
    # =========================================================================
    # Physikalisch fundierte Obergrenze fuer die BLH basierend auf der
    # kumulierten Bodenheizung des Tages. Verhindert unphysikalische Spruenge.
    #
    # Formel: h² = h₀² + [2·(1+2A) / γ_θ] × Σ(w'θ'_s · Δt)
    #
    A_ENTRAIN = 0.2              # Entrainment-Verhaeltnis (Stull 1988)
    H0_INIT = 100.0              # Initiale Mischungsschicht bei Tagesbeginn (m)
    DT_SECONDS = 3600.0          # Zeitschritt = 1 Stunde

    # Kinematischer Waermefluss dieser Stunde
    w_theta_s = H / (RHO * CP) if H > 0 else 0.0
    buoyancy_contribution = w_theta_s * DT_SECONDS   # K·m (Beitrag dieser Stunde)

    # Kumulierter Waermefluss (wird von aussen uebergeben)
    total_buoyancy = (cumulative_buoyancy or 0.0) + buoyancy_contribution

    # γ_θ aus dem aktuellen Temperaturprofil
    gamma_theta = _compute_free_atm_gamma(profile, max_thermal_height, elevation_m)

    # Encroachment-BLH berechnen
    h_enc_msl = None
    if gamma_theta > 0 and total_buoyancy > 0:
        h_enc_agl = math.sqrt(H0_INIT**2 + 2 * (1 + 2 * A_ENTRAIN) / gamma_theta * total_buoyancy)
        h_enc_msl = elevation_m + h_enc_agl

        # Encroachment als Obergrenze verwenden
        if max_thermal_height > h_enc_msl:
            data_warnings.append(
                f"Encroachment-Cap: {max_thermal_height:.0f}m → {h_enc_msl:.0f}m "
                f"(γ_θ={gamma_theta*1000:.1f} K/km, cum={total_buoyancy:.0f} K·m)"
            )
            max_thermal_height = h_enc_msl

    # =========================================================================
    # 5d. THERMAL INERTIA (H-skaliert)
    # =========================================================================
    # Die Grenzschicht fällt nicht sofort zusammen wenn eine Wolke die Sonne
    # kurz verdeckt. Aber der Verfall skaliert mit dem Verhältnis H/peak_H:
    #   Am Peak (Mittag): 5% Verfall -> Glättung gegen Wolkenschwankungen
    #   Bei sinkendem H:  bis 30% Verfall -> Abend-Zusammenbruch
    #   Bei H=0:          30% Verfall -> schneller aber nicht instantaner Kollaps
    if previous_max_height is not None and previous_max_height > elevation_m:
        if peak_H is not None and peak_H > 0 and H > 0:
            h_ratio = min(1.0, H / peak_H)
            decay_rate = 0.05 + (1.0 - h_ratio) * 0.25
        elif H > 0:
            decay_rate = 0.05
        else:
            decay_rate = 0.30

        inertia_height = previous_max_height - ((previous_max_height - elevation_m) * decay_rate)
        inertia_height = max(elevation_m, inertia_height)

        if max_thermal_height < inertia_height:
            data_warnings.append(
                f"Thermik-Inertia: {max_thermal_height:.0f}m -> {inertia_height:.0f}m "
                f"(Verfall {decay_rate:.0%}, H/peak={H:.0f}/{peak_H or 0:.0f})"
            )
            max_thermal_height = inertia_height

    # =========================================================================
    # 5f. GFS/MODEL PBL CAP (Triple-Constraint)
    # =========================================================================
    # Das NWP-Modell (GFS) berechnet die BLH mit Bulk-Richardson-Schema und
    # vollständiger Strahlungsbilanz. Sobald am Abend die Ausstrahlung überwiegt,
    # sinkt die Modell-BLH rapide. Dieser Cap überschreibt die Thermal Inertia.
    pbl_cap_applied = False
    if boundary_layer_height_gfs is not None:
        gfs_blh_msl = elevation_m + boundary_layer_height_gfs
        if max_thermal_height > gfs_blh_msl:
            data_warnings.append(
                f"GFS-PBL-Cap: {max_thermal_height:.0f}m -> {gfs_blh_msl:.0f}m "
                f"(GFS BLH={boundary_layer_height_gfs:.0f}m AGL)"
            )
            max_thermal_height = gfs_blh_msl
            pbl_cap_applied = True

    # =========================================================================
    # 6. DUAL W*-BERECHNUNG (Geometrisches-Mittel-Strategie)
    # =========================================================================
    # Zwei unabhaengige Konvektionsgeschwindigkeiten (w*):
    #
    # a) w*_parcel: Aus der mittleren Temperaturdifferenz (Parcel-Aufstieg)
    # b) w*_deardorff: Aus dem sensiblen Waermefluss (Energie-Ansatz)
    #
    # Geometrisches Mittel sqrt(a*b).
    # CLIMB_FACTOR kalibriert die theoretische Aufwindgeschwindigkeit auf die
    # tatsächliche Steigrate des Gleitschirms, der versucht die besten Kerne zu zentrieren.
    # Physikalisch: Ein Gleitschirm erzielt typischerweise ~50% der theoretischen w* Geschwindigkeit
    # wegen Eigensinken im Kreisflug (-1.0m/s bis -1.5m/s) und unperfekter Zentrierung.
    CLIMB_FACTOR = _get_thermal_param("climb_factor", timestamp, default=0.50)

    # =========================================================================
    # 6. DUAL W*-BERECHNUNG (Modifiziert mit Regtherm Sun-Factor)
    # =========================================================================
    thermic_clouds = calculate_thermic_clouds(low_cloud, mid_cloud, high_cloud)
    display_cloud = thermic_clouds['display_cloud']
    sun_index = thermic_clouds['sun_index']
    sun_factor = thermic_clouds['sun_factor']

    T_kelvin = start_temp + 273.15
    z_i = max_thermal_height - elevation_m

    w_star_parcel = 0.0
    w_star_deardorff = 0.0
    avg_climb = 0.0
    mean_dT = 0.0
    limiting_factor = "model_pbl_cap" if pbl_cap_applied else "keine_thermik"

    H_MIN_THRESHOLD = 30.0
    if z_i > 50 and H >= H_MIN_THRESHOLD:
        if valid_layers > 0:
            mean_dT = cumulative_temp_diff / valid_layers

        # a) W* aus Parcel-Methode
        if mean_dT > 0 and valid_layers > 0:
            w_star_parcel = math.sqrt((G / T_kelvin) * mean_dT * z_i)

        # b) W* nach Deardorff
        if H > 0 and z_i > 0:
            buoyancy_flux = H / (RHO * CP)
            w_star_deardorff = ((G / T_kelvin) * buoyancy_flux * z_i) ** (1.0 / 3.0)

        # c) RASP / BLIPMAP Standard: W* wird exklusiv nach Deardorff berechnet!
        # Das Parcel-Verfahren (w*_parcel) tendiert bei trockener Thermik zu 
        # extremen Überschätzungen (stammt eig. aus der CAPE-Ansatz für Gewitter).
        # We scale Deardorff w* by 1.45 to reflect the "core" updraft strength
        # that gliders actively try to center within (XC Therm / Regtherm alignment).
        if w_star_deardorff > 0:
            raw_w_star = w_star_deardorff * 1.45
            limiting_factor = "inversion_stability"
        elif w_star_parcel > 0:
            # Reiner Fallback falls H=0 aber Paket trotzdem instabil (Föhn/Dynamik)
            raw_w_star = w_star_parcel * 0.5
            limiting_factor = "solar_energy"
        else:
            raw_w_star = 0.0

        # Kalibrierungsfaktor: w* -> reales Gleitschirm-Steigen
        damping_threshold = _get_thermal_param("climb_factor_damping_threshold", timestamp, default=4.0)
        if raw_w_star > damping_threshold:
            climb_factor = max(0.40, CLIMB_FACTOR - (raw_w_star - damping_threshold) * 0.05)
        else:
            climb_factor = CLIMB_FACTOR

        avg_climb = raw_w_star * climb_factor
        
        # HINWEIS: W*-Deardorff beinhaltet die Bewölkungsdämpfung bereits physikalisch
        # über den surface_sensible_heat_flux (H), weshalb wir hier nicht nochmals 
        # künstlich mit einem "sun_factor" multiplizieren dürfen (sonst doppelte Bestrafung).
        # DWD-Updraft-Blending (Default: deaktiviert)
        if _get_thermal_param("use_dwd_updraft_blending", timestamp, default=False):
            if updraft is not None and updraft > 0:
                dwd_scale = _get_thermal_param("dwd_updraft_scale", timestamp, default=2.0)
                dwd_climb = updraft * dwd_scale * CLIMB_FACTOR
                blended = 0.70 * avg_climb + 0.30 * dwd_climb
                if blended > avg_climb:
                    avg_climb = blended
                    data_warnings.append(
                        f"Updraft-Blending: DWD={dwd_climb:.1f} m/s → {avg_climb:.1f} m/s"
                    )

        # Absolute Hard-Cap
        hard_cap = _get_thermal_param("climb_hard_cap", timestamp, default=4.5)
        avg_climb = min(hard_cap, avg_climb)

    elif z_i > 50:
        limiting_factor = "H_below_threshold"
        data_warnings.append(
            f"H unter Schwellenwert: {H:.0f} W/m² < {H_MIN_THRESHOLD:.0f} -> keine nutzbare Thermik"
        )

    # =========================================================================
    # 6b. KONVEKTIVER VIGOR (min von H/peak_H und SW/peak_SW)
    # =========================================================================
    # ICON-D2 liefert hier oft keine BLH; GFS sinkt teils erst spaet. H und
    # Globalstrahlung sind stark korreliert — ein Produkt wuerde denselben
    # Abendverfall doppelt daempfen. Ein Limit genuegt: min(...) (keine Doppelzaehlung).
    convective_vigor = None
    if (
        peak_H is not None and peak_H > 0
        and peak_shortwave is not None and peak_shortwave > 0
        and shortwave_radiation is not None
    ):
        h_ratio = max(0.0, min(1.0, H / peak_H))
        sw_ratio = max(0.0, min(1.0, shortwave_radiation / peak_shortwave))
        convective_vigor = min(h_ratio, sw_ratio)
        if avg_climb > 0 and convective_vigor < 0.999:
            avg_climb *= convective_vigor
            if convective_vigor < 0.92:
                data_warnings.append(
                    f"Konvektions-Vigor: x{convective_vigor:.2f} "
                    f"(H/peak={h_ratio:.2f}, SW/peak={sw_ratio:.2f})"
                )

    # =========================================================================
    # 7. BEWERTUNG (Rating 0-10)
    # =========================================================================
    rating = 0
    if avg_climb > 0: rating = 1
    if avg_climb >= 0.2: rating = 2
    if avg_climb >= 0.5: rating = 3
    if avg_climb >= 0.8: rating = 5
    if avg_climb >= 1.5: rating = 7
    if avg_climb >= 2.5: rating = 9
    if avg_climb >= 3.5: rating = 10

    # Bewölkungs-Hinweis (Sun Index < 10 = extreme Bewölkung): nur Rating deckeln.
    # Steigrate kommt aus H/Deardorff — nicht zusaetzlich per Wolkenfeld auf 0 setzen
    # (Modelltreue; vgl. schwache Thermik bei XC/Burnair bei Regen/Bewölkung).
    if sun_index < 10:
        rating = min(2, rating)

    # CIN-Bremse: Konvektive Hemmung reduziert Rating
    if convective_inhibition is not None:
        if convective_inhibition < -100:
            rating = max(0, rating - 2)
            data_warnings.append(
                f"CIN-Bremse: CIN={convective_inhibition:.0f} J/kg (stark) → Rating -2"
            )
        elif convective_inhibition < -50:
            rating = max(0, rating - 1)
            data_warnings.append(
                f"CIN-Bremse: CIN={convective_inhibition:.0f} J/kg (mässig) → Rating -1"
            )

    # Minimale Thermikhöhe: Unter 150m ueber Start ist Thermik kaum nutzbar
    if max_thermal_height < elevation_m + 150:
        rating = min(rating, 1)
        avg_climb = 0.0

    # =========================================================================
    # 8. BODENFEUCHTE-BREMSE (Latenter Wärmefluss)
    # =========================================================================
    # Wenn der latente Wärmefluss (Verdunstung) den sensiblen (Thermik)
    # übersteigt, ist der Boden nass: Die Sonnenenergie geht primär in
    # Verdunstung statt in die Lufterwärmung -> schwächere Thermik.
    # In diesem Fall reduzieren wir das Rating um 2 Punkte.
    bowen_ratio = None
    if le_valid:
        if abs(LE) > 0:
            bowen_ratio = H / abs(LE)
        else:
            # LE = 0 bedeutet keine Verdunstung -> sehr trockener Boden
            bowen_ratio = 99.0

        # Bremse nur anwenden wenn überhaupt Thermik vorhanden ist (H > 0)
        if abs(LE) > H and H > 0:
            rating = max(0, rating - 2)
            data_warnings.append(
                f"Bodenfeuchte-Bremse: LE ({LE:.0f} W/m²) > H ({H:.0f} W/m²) "
                f"-> Rating um 2 reduziert (Bowen={bowen_ratio:.2f})"
            )

    # =========================================================================
    # 9. DIAGNOSTIK (für LLM-Kontext und Debugging)
    # =========================================================================
    diagnostics = {
        'w_star_parcel': round(w_star_parcel, 2),
        'w_star_deardorff': round(w_star_deardorff, 2),
        'limiting_factor': limiting_factor,
        'sensible_heat_flux': round(H, 1),
        'sensible_heat_flux_estimated': h_is_estimated,
        'latent_heat_flux': round(LE, 1) if le_valid else None,
        'bowen_ratio': round(bowen_ratio, 2) if bowen_ratio is not None else None,
        'mean_dT': round(mean_dT, 2),
        'thermal_depth_m': round(z_i),
        'start_temp_used': round(start_temp, 1),
        'boundary_layer_height_agl': round(boundary_layer_height_agl) if boundary_layer_height_agl is not None else None,
        'soil_moisture': round(soil_moisture, 3) if soil_moisture is not None else None,
        'lifted_index': round(lifted_index, 1) if lifted_index is not None else None,
        'convective_inhibition': round(convective_inhibition, 0) if convective_inhibition is not None else None,
        'vapour_pressure_deficit': round(vpd, 2) if vpd is not None else None,
        'sun_index': round(sun_index, 1),
        'display_cloud': round(display_cloud, 1),
        'sun_factor': round(sun_factor, 3),
        'boundary_layer_height_gfs': round(boundary_layer_height_gfs) if boundary_layer_height_gfs is not None else None,
        'buoyancy_contribution': round(buoyancy_contribution, 1),
        'cumulative_buoyancy': round(total_buoyancy, 1),
        'gamma_theta': round(gamma_theta, 5),
        'encroachment_blh': round(h_enc_msl) if h_enc_msl is not None else None,
        'pbl_cap_applied': pbl_cap_applied,
        'peak_H': round(peak_H, 1) if peak_H is not None else None,
        'peak_shortwave': round(peak_shortwave, 1) if peak_shortwave is not None else None,
        'convective_vigor': round(convective_vigor, 3) if convective_vigor is not None else None,
    }

    return {
        'max_height': round(max_thermal_height),
        'lcl': round(lcl_msl) if lcl_msl else None,
        'climb_rate': round(avg_climb, 1),
        'rating': rating,
        'ti_profile': ti_profile,
        'diagnostics': diagnostics,
        'data_warnings': data_warnings,
    }


def analyze_hour(hourly_data: Dict, pressure_data: Dict, time_index: int,
                 elevation_m: float = 850.0, slope_azimuth: float = None,
                 slope_angle: float = None) -> Dict:
    """
    Extrahiert die Daten für eine spezifische Stunde und berechnet die Thermik.
    Convenience-Funktion, die alle Parameter aus den API-Rohdaten extrahiert
    und an calculate_thermal_profile() weiterleitet.
    """
    try:
        surf_temp = hourly_data.get('temperature_2m', [])[time_index]
        surf_dew = hourly_data.get('dewpoint_2m', [])

        if not surf_dew or len(surf_dew) <= time_index:
            rh_2m = hourly_data.get('relative_humidity_2m', [])
            if rh_2m and len(rh_2m) > time_index:
                surf_dew_val = calculate_dewpoint(surf_temp, rh_2m[time_index])
            else:
                surf_dew_val = surf_temp - 5  # Grobe Schätzung als Fallback
        else:
            surf_dew_val = surf_dew[time_index]

        blh = hourly_data.get('boundary_layer_height', [])
        blh_val = blh[time_index] if blh and len(blh) > time_index else None

        sun = hourly_data.get('sunshine_duration', [])
        sun_val = sun[time_index] if sun and len(sun) > time_index else 3600.0

        # Neue Flux-Parameter (können None sein -> Fallback im Calculator)
        shf = hourly_data.get('surface_sensible_heat_flux', [])
        shf_val = shf[time_index] if shf and len(shf) > time_index else None

        lhf = hourly_data.get('surface_latent_heat_flux', [])
        lhf_val = lhf[time_index] if lhf and len(lhf) > time_index else None

        swr = hourly_data.get('shortwave_radiation', [])
        swr_val = swr[time_index] if swr and len(swr) > time_index else None

        # Neue Parameter extrahieren
        def _get_val(key):
            arr = hourly_data.get(key, [])
            return arr[time_index] if arr and len(arr) > time_index else None

        dir_rad = _get_val('direct_radiation')
        diff_rad = _get_val('diffuse_radiation')
        sm = _get_val('soil_moisture_0_to_1cm')
        st = _get_val('soil_temperature_0cm')
        upd = _get_val('updraft')
        et0_val = _get_val('et0_fao_evapotranspiration')
        vpd_val = _get_val('vapour_pressure_deficit')
        li_val = _get_val('lifted_index')
        cin_val = _get_val('convective_inhibition')
        snow_depth_val = _get_val('snow_depth')

        # Timestamp holen
        times = hourly_data.get('time', [])
        ts_val = times[time_index] if times and len(times) > time_index else None

        # Höhendaten extrahieren
        p_levels = []
        for level in [1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 600]:
            h_key = f"geopotential_height_{level}hPa"
            t_key = f"temperature_{level}hPa"

            if h_key in pressure_data and t_key in pressure_data:
                h_arr = pressure_data[h_key]
                t_arr = pressure_data[t_key]
                if len(h_arr) > time_index and len(t_arr) > time_index:
                    p_levels.append({
                        'pressure': level,
                        'height': h_arr[time_index],
                        'temp': t_arr[time_index]
                    })

        return calculate_thermal_profile(
            surface_temp=surf_temp,
            surface_dewpoint=surf_dew_val,
            elevation_m=elevation_m,
            pressure_levels_data=p_levels,
            boundary_layer_height_agl=blh_val,
            sunshine_duration_s=sun_val,
            surface_sensible_heat_flux=shf_val,
            surface_latent_heat_flux=lhf_val,
            shortwave_radiation=swr_val,
            direct_radiation=dir_rad,
            diffuse_radiation=diff_rad,
            soil_moisture=sm,
            soil_temperature=st,
            updraft=upd,
            et0=et0_val,
            vpd=vpd_val,
            lifted_index=li_val,
            convective_inhibition=cin_val,
            snow_depth=snow_depth_val,
            timestamp=ts_val,
            slope_azimuth=slope_azimuth,
            slope_angle=slope_angle,
            low_cloud=_get_val('cloud_cover_low'),
            mid_cloud=_get_val('cloud_cover_mid'),
            high_cloud=_get_val('cloud_cover_high'),
            boundary_layer_height_gfs=_get_val('boundary_layer_height_gfs'),
        )

    except Exception as e:
        logger.error(f"Fehler bei Thermik-Berechnung: {e}")
        return {'error': str(e)}
