"""
Konfigurationsdatei für Wingcast
Adaptiert von uetliberg_ticker/config.py - Multi-Spot, Chat-basiert.
"""

import atexit
import json
import logging
import os
import queue
import tempfile
import threading
from pathlib import Path

# .env so früh wie möglich laden, damit alle Importer (auch web.py, das nicht
# selbst load_dotenv aufruft) Zugriff auf Secrets wie OPENMETEO_API_KEY haben.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional

# ============================================================================
# API-KONFIGURATION (Open-Meteo)
# ============================================================================

# Open-Meteo API Key (optional). Wenn gesetzt → Customer API mit höheren Limits
# (5 Mio. Calls/Monat statt 10k/Tag im Free Tier).
OPENMETEO_API_KEY = os.environ.get("OPENMETEO_API_KEY", "").strip()

if OPENMETEO_API_KEY:
    API_URL = "https://customer-api.open-meteo.com/v1/forecast"
else:
    API_URL = "https://api.open-meteo.com/v1/forecast"


def with_api_key(params):
    """
    Helper: Injiziert apikey in das Open-Meteo Request-Params Dict, falls
    OPENMETEO_API_KEY gesetzt ist. Mutiert das Dict in-place und gibt es zurück.
    """
    if OPENMETEO_API_KEY:
        params["apikey"] = OPENMETEO_API_KEY
    return params

# ============================================================================
# WETTERMODELLE — zentrale Konfiguration (SoT: docs/WETTERMODELLE.md)
# ============================================================================
#
# Jede Wettergroesse wird vom physikalisch passendsten Modell geliefert.
# Pro Tag waehlt fetch_weather._process_spot_weather den besten verfuegbaren
# Tier (Funktion `is_model_valid_for_day`).
#
#   Modell  | Aufloesung | Horizont | Kalibrierung    | PL? | BLH?
#   --------|------------|----------|-----------------|-----|------
#   CH1     | 1.1 km     | 33 h     | Schweiz (MeteoSwiss) | nein | nein
#   CH2     | 2.1 km     | 5 d      | Schweiz (MeteoSwiss) | nein | nein
#   D2      | 2.2 km     | 48 h     | Pan-Europa (DWD)    | ja   | nein
#   EU      | 13 km      | 5 d      | Pan-Europa (DWD)    | ja   | nein
#   GFS     | 25 km      | 5 d      | Global (NOAA)       | ja   | ja
#
# Open-Meteo-Limit: CH1/CH2 liefern NUR Surface-Variablen. Hoehenwind +
# T_850/T_700 + Geopotenzial gibt es nur via D2/EU. BLH gibt es seit Mai 2026
# nur noch via GFS (ICON-BLH-Felder kommen leer zurueck).
#
# --- SURFACE-Schicht (Wind, Wolken, Temp, Feuchte, Strahlung, Precip, CAPE) ---
# Tag-Voting 4-Tier: CH1 -> CH2 -> D2 -> EU. Einheitlich fuer ALLE Surface-
# Variablen, die CH-Modelle liefern (siehe CH_SURFACE_PARAMS unten).
#
# Tier-Logik:
#   1. CH1 (1.1 km, 33h)  — Schweiz, hoechste Aufloesung Tag 1
#   2. CH2 (2.1 km, 5d)   — Schweiz, Tag 2-5
#   3. D2  (2.2 km, 48h)  — Pan-Europa, faengt CH-rand-Spots auf (Tessin Sued,
#                            Walliser Suedtaeler, suedl. Engadin) wo CH1/CH2
#                            null liefern. D2 deckt Alpenraum + Norditalien
#                            grosszuegig ab und hat 2.2 km — deutlich besser
#                            als EU (13 km) im Grenzgebiet.
#   4. EU  (13 km, 5d)    — Notfall, nur Tag 3-5 ausserhalb der CH-Coverage.
SURFACE_PRIMARY_MODEL   = "meteoswiss_icon_ch1"   # Tier 1: Tag 1 (33h), 1.1 km
SURFACE_SECONDARY_MODEL = "meteoswiss_icon_ch2"   # Tier 2: Tag 2-5 (120h), 2.1 km
SURFACE_TERTIARY_MODEL  = "icon_d2"               # Tier 3: CH-rand, Tag 1-2 (48h), 2.2 km
SURFACE_FALLBACK_MODEL  = "icon_eu"               # Tier 4: Notfall, 13 km

# --- D2-SPEZIFISCHE Surface-Variablen + PRESSURE-LEVEL ---
# Variablen, die CH1/CH2 ueber Open-Meteo NICHT exponieren — bleiben bei D2/EU.
# soil_moisture/soil_temperature: thermik_calculator nutzt sie fuer LE-Berechnung
# updraft: D2-spezifischer Mass-Flux-Output
# alle *_hPa Vars: nur D2 (Tag 1-2) und EU (Tag 3-5)
PRESSURE_LEVEL_PRIMARY_MODEL  = "icon_d2"          # Tag 1-2 (48h), 2.2 km
PRESSURE_LEVEL_FALLBACK_MODEL = "icon_eu"          # Tag 3-5, 13 km

# --- BOUNDARY-LAYER-HEIGHT (Thermik-PBL-Cap) ---
# Nur GFS liefert BLH via Open-Meteo. Wird in thermik_calculator als optionaler
# Cap fuer die Parcel-BLH genutzt (Modi: gfs_pbl_cap_mode pro Terrain-Zone).
BLH_MODEL = "gfs_seamless"                          # 5 d, 25 km

# --- NIEDERSCHLAG dichte 16-RP-Aggregation ---
# Eigener Batch im Region-Pfad. Konvektionsaufloesend + CH-kalibriert →
# Schauer-Geographie (Stau/Lee/Foehn) sichtbar. Hybrid-Filter aus
# meteo_research/precipitation_aggregation.md funktioniert nur auf
# konvektionsaufloesenden Modellen (CH1/CH2/D2), nicht auf EU.
PRECIP_DENSE_MODEL = "meteoswiss_icon_ch2"          # 5 d, 2.1 km

# --- BOEEN-MULTI-MAX-MERGE (Sicherheits-Layer) ---
# Konservatives max(D2, CH1, CH2) auf wind_gusts_10m (siehe BOEEN_MODELL.md).
GUST_MERGE_MODELS = ["icon_d2", "meteoswiss_icon_ch1", "meteoswiss_icon_ch2"]

# --- HORIZONTE pro Modell (forecast_days fuer Batch-Calls) ---
FORECAST_DAYS_CH1 = 2   # real ~33h, 2d genuegt
FORECAST_DAYS_CH2 = 5
FORECAST_DAYS_D2  = 2   # D2 hat 48h
FORECAST_DAYS_EU  = 5
FORECAST_DAYS_GFS = 5

# --- ENSEMBLE-GEWITTER (ICON-CH2-EPS, Kontrolllauf + 20 Member) ---
# Gewitter kamen bisher nur aus EINEM deterministischen Lauf. Fuer Konvektion
# ist das die unzuverlaessigste verfuegbare Information: die Zelle muss zufaellig
# genau auf einem Referenzpunkt zuenden. Das Ensemble ersetzt das nicht, es
# ergaenzt es um eine Wahrscheinlichkeit. Siehe ensemble_thunder.py.
#
# ACHTUNG: Der Ensemble-Endpunkt laeuft nur OHNE unseren Kunden-API-Key
# (mit Key: HTTP 403 "requires API Professional or Enterprise plan").
ENSEMBLE_MODEL = "meteoswiss_icon_ch2"

# Weiche Warnstufen als Anteil der Member mit Gewitter-Code im Flugfenster.
# NICHT KALIBRIERT und rueckwirkend auch NICHT kalibrierbar: Open-Meteo fuellt
# die Vergangenheit im Ensemble mit einer einzigen Reihe — aelter als rund drei
# Tage sind alle 21 Member identisch (gemessen 31.07.2026, siehe
# scripts/calibrate_ensemble_threshold.py). Der Weg ist vorwaerts sammeln:
# snapshot_weather.py archiviert thunder_ensemble taeglich.
#
# MENTION 20 -> 15 am 31.07.2026: Fallbeispiel Zentralschweizer Voralpen,
# Sa 01.08. — 19 % der Member, deterministisch 17.1 mm/h bei CAPE 380 ohne
# Gewitter-Code. Bei 20 % fiel der Tag komplett durch. Kosten der Senkung im
# damaligen 5-Tage-Fenster: 88 statt 82 von 145 Region-Tagen (+6). 15 ist
# ebenso ungemessen wie 20 — nur an einem echten Fall ausgerichtet statt frei
# gewaehlt. Mit den vorwaerts gesammelten Daten ersetzen.
#
# Diese Schwellen setzen NIE ein No-Go, sie steuern nur die Erwaehnung.
ENSEMBLE_THUNDER_MENTION_PCT  = 15   # ab hier ueberhaupt erwaehnen ("moeglich")
# --- Schwellen fuer das BLITZ-SYMBOL im Meteogramm ---
# Bewusst eigene Zahlen: die Anzeige darf nachgezogen werden, ohne die
# Text-Stufen (MENTION/ELEVATED/HIGH) zu bewegen. Ein Satz im Analysetext ist
# billig, ein Blitz im Meteogramm ist laut.
#
# TAGES-Schwelle ABGESCHAFFT am 02.08.2026 (Schritt 1, PLAN_gewitter_anzeige
# Teil B). Sie fuellte das ganze Schwerpunkt-Fenster mit Blitzen, sobald der
# TAGESWERT ueber der Schwelle lag. Dieser Tageswert ist aber der Anteil der
# Member, die IRGENDWANN im Flugfenster an IRGENDEINEM der 16 Referenzpunkte
# zuenden — im Sommer nahezu gesaettigt (Median 95 % ueber alle Blitzstunden
# vom 02.08.). Eine Tagesaussage auf Stunden zu malen erzeugte 53 der damals
# 217 Blitzstunden, viele davon bei blankem Himmel. Der Tageswert bleibt fuer
# den TEXT zustaendig (ENSEMBLE_THUNDER_MENTION_PCT), nicht fuer das Symbol.

# STUNDEN-Schwelle: der Blitz kommt jetzt AUSSCHLIESSLICH aus dem stuendlichen
# Member-Anteil — die einzige Groesse im Ensemble, die wirklich stuendlich ist.
#
# Warum ueberhaupt: das Meteogramm zeigte Gewitter nur aus dem
# deterministischen weather_code — genau der Quelle, die Konvektion
# regelmaessig verpasst. Die KI bekam die Ensemble-Aussage, die Anzeige nicht.
# Ab jetzt speist dieselbe Quelle beides.
#
# Mengengeruest im 5-Tage-Fenster vom 31.07.2026 (1740 Region-Flugstunden):
#   weather_code allein   4 Stunden (0.2 %)
#   Ensemble >= 30 %    216 Stunden (12.4 %)
#   Ensemble >= 40 %    174 Stunden (10.0 %)
#   Ensemble >= 50 %    141 Stunden ( 8.1 %)
# 40 gewaehlt: deutlich mehr als heute, aber keine Dauerbeblitzung. UNGEMESSEN
# wie alle Ensemble-Schwellen — mit den vorwaerts gesammelten Daten ersetzen.
ENSEMBLE_THUNDER_METEOGRAM_PCT = 40
ENSEMBLE_THUNDER_ELEVATED_PCT = 40   # "erhoeht"
ENSEMBLE_THUNDER_HIGH_PCT     = 60   # "hoch"

# --- MINDESTANTEIL DER REFERENZPUNKTE (02.08.2026) ---
# Bis hierher galt: zuendet EIN einziger der 7 Referenzpunkte in einem Member,
# zaehlt dieser Member fuer die GANZE Region als Gewitter
# (merge_points_per_member -> _severest, also ein ODER ueber die Flaeche).
#
# Messbefund vom 02.08. gegen XC Therm (25 zuordenbare Regionen): 5 Regionen,
# in denen nur wir Gewitter zeigten, alle im Voralpenguertel 1400-1860 m —
# genau dort spannen die 7 Punkte vom Talboden bis zum Grat und sind damit am
# unterschiedlichsten, das ODER schlaegt also am staerksten durch. Dasselbe
# ODER erzeugt die zu breiten Zeitfenster: ueber einen Nachmittag zuendet
# fast immer irgendein Punkt, es entsteht ein Plateau statt einer Spitze
# (unsere Fenster 3-6 h gegen 0.5-1.5 h bei XC Therm).
#
# 2 von 7: ein einzelner Punkt gilt als vereinzelt und traegt die Region
# nicht mehr allein. UNGEMESSEN — rueckwirkend nicht pruefbar, weil wir nur
# das fertige Ergebnis speichern und nicht die einzelnen Punkte. Wirkt erst
# ab dem naechsten Wetterlauf; danach erneut gegen XC Therm vergleichen.
ENSEMBLE_THUNDER_POINT_QUORUM = 2

# --- PLAUSIBILITAETS-ANKER fuer das Blitz-Symbol (02.08.2026, Schritt 2) ---
# Das Ensemble kennt nur Wettercodes. Bewoelkung, Niederschlag und CAPE
# derselben Stunde stammen aus dem deterministischen Lauf und wurden nie
# gegengelesen — die beiden mussten sich nie einig sein und waren es meist
# nicht: von 217 Blitzstunden am 02.08. hatten 85 % keinen Niederschlag,
# 53 % unter 50 % Bewoelkung, 50 % beides zugleich (Tessin Zentral 04.08.
# 14:00 zeigte einen Blitz bei 2 % Bewoelkung).
#
# Ein Ensemble-Blitz erscheint nur noch, wenn der deterministische Lauf in
# DERSELBEN Stunde ueberhaupt etwas zeigt:
#     NIEDERSCHLAG und (CAPE oder Lifted Index)
#
# Wirkung gemessen (137 Regionstage, 02.08.): 36 % -> 19 % der Regionstage.
#
# --- VERSCHAERFT am 03.08.2026: Regen-PFLICHT statt Wolken-Alternative ---
# Erster Saison-Backtest (15.05.-02.08., 2320 Regionstage, Wahrheit =
# SwissMetNet-Gewittersignatur: Regen >= 4 mm/h + Boeensprung >= 15 km/h
# oder Temperatursturz >= 2 K):
#
#   Anker-Variante                Gewittertage durch   stille Tage durch
#   (Wolke50|Regen)&(CAPE|LI)        113/124 = 91 %      1331/2196 = 61 %
#   nur Regen      &(CAPE|LI)        112/124 = 90 %       528/2196 = 24 %
#
# Die Wolken-Alternative filterte praktisch nichts — im Sommer hat fast jede
# Region irgendwo >= 50 % Bewoelkung (Maximum ueber 7 Referenzpunkte). Die
# Regen-Pflicht kostet ueber die ganze Saison genau EINEN Gewittertag
# (Tessin Nord 16.07., det. Lauf voellig trocken, Gewitter erst 17 Uhr) und
# drittelt das Fehlalarm-Potenzial. Am Lauf vom 02.08.: 33 -> 15 Blitz-
# stunden, darunter fallen genau die am Testtag GEMESSEN widerlegten
# Fehlalarme (Alpstein 99 % Sonne, Mittelland Zentral 94 %).
# Der Fall "Modelle sehen Gewitter, aber kein Regen" bleibt im TEXT
# erwaehnt (MENTION-Schwelle) und wandert spaeter in die weiche
# Ueberentwicklungs-Stufe. THUNDER_ANCHOR_CLOUD_PCT damit entfernt.
#
# Gilt NUR fuer den Ensemble-Weg. Ein deterministischer Gewittercode 95/96/99
# bleibt ungefiltert — er stammt aus demselben Lauf wie Wolken und Regen und
# ist damit per Konstruktion in sich stimmig; ihn zu unterdruecken hiesse, ein
# hartes Modellsignal wegzurechnen.
#
# CIN ist BEWUSST NICHT Teil des Ankers: In den Alpen druecken
# Talwind-Konvergenzen die Luft mechanisch durch den Deckel, und ein mittlerer
# Deckel macht das Nachmittagsgewitter heftiger statt harmloser. Ein
# CIN-Filter wuerde Blitze ausgerechnet an den gefaehrlichsten Tagen
# unterdruecken.
#
# Der Lifted Index waere der trennschaerfste Wert (Median -2,1 in
# Blitzstunden gegen -0,9 sonst, gemessen 01.08.), fehlt Regionen aber im
# Abruf — kommt mit Schritt 3 zusammen mit dem DWD-Blitzpotenzial.
#
THUNDER_ANCHOR_PRECIP_MM  = 0.1   # mm/h in dieser Stunde (PFLICHT seit 03.08.)
THUNDER_ANCHOR_CAPE_JKG   = 300   # J/kg in dieser Stunde
# Instabilitaet gilt als gegeben bei CAPE ODER Lifted Index. Das ODER ist der
# Kern der Hoehenkorrektur (02.08.2026): CAPE wird vom Boden aufwaerts
# gerechnet und ist zwischen Regionen unterschiedlicher Hoehe nicht
# vergleichbar — auf 2450 m beginnt die Saeule oberhalb der feuchten
# Grenzschicht. Gemessen: CAPE-Median 860 in den Voralpen, 295 im Hochgebirge,
# und Oberwallis erreichte den ganzen 02.08. hoechstens 290, waehrend XC Therm
# dort 1,5 h Gewitter zeigte. Mit CAPE allein waere die Schwelle dort eine
# zweite Sperre gewesen.
# -1.0 ist bewusst schwach angesetzt (Literatur: < -2 Gewitter moeglich,
# < -4 kraeftig) — der Anker soll nur Unmoegliches ausschliessen, nicht
# vorsortieren. UNGEMESSEN.
THUNDER_ANCHOR_LI         = -1.0  # Lifted Index in dieser Stunde (kleiner = instabiler)

# --- UEBERENTWICKLUNG (weiche Vorwarn-Stufe, 03.08.2026) ---
# "Quellwolken koennen hochschiessen" — die Stufe VOR dem Gewitter. Sperrt
# nie, hohler Blitz + Satz in der KI-Analyse. Vier Bedingungen, alle in
# derselben Stunde (Herleitung + Saison-Backtest: docs/GEWITTER.md par.0c —
# Top<=-20 @>=75% Punkte + Anker erkannte 2 von 3 Konvektionstagen,
# ~3-4 h Vorlauf):
#   1. Wolkentop-Temperatur <= OVERDEV_TOP_TEMP_C an >= OVERDEV_TOP_SHARE_PCT
#      der Referenzpunkte (ICON-EU convective_cloud_top — einziges Modell,
#      das das Feld fuellt; CH1/CH2 liefern es nicht, D2 praktisch leer)
#   2. KONSISTENZ-REGEL (User 03.08.): Bewoelkung im ANGEZEIGTEN Lauf
#      >= OVERDEV_CLOUD_MIN_PCT — das Meteogramm darf nie wolkenlos zeigen
#      und daneben Ueberentwicklung behaupten (dieselbe Lehre wie der
#      Blitz bei 2 % Bewoelkung)
#   3. Instabilitaet: CAPE ODER Lifted Index (THUNDER_ANCHOR_*-Schwellen)
#   4. Blauthermik-Gate: erreicht die Thermik die Wolkenbasis nicht
#      (max_height deutlich unter LCL), waechst keine Quellwolke -> keine
#      Warnung. Nutzt das eigene Thermikmodell (Spot-Median je Region).
# Harte Blitz-Stunde gewinnt immer: dort KEIN Zusatzsymbol.
# UNGEMESSEN im Detail — Schwellen laufen im Validierungs-Scoreboard
# parallel mit und werden nach ~4 Wochen geeicht.
OVERDEV_TOP_TEMP_C     = -20.0  # Wolkentop kaelter als das -> gewittertaugliche Tiefe
OVERDEV_TOP_SHARE_PCT  = 75     # Anteil der Referenzpunkte mit kaltem Top
OVERDEV_CLOUD_MIN_PCT  = 30     # Konsistenz: angezeigte Bewoelkung in DIESER Stunde
OVERDEV_THERMIK_MARGIN_M = 200  # Blauthermik-Gate: max_height + Marge < LCL -> aus

# --- SURFACE-PARAMS die CH1/CH2 ueber Open-Meteo liefern ---
# Mai 2026 verifiziert. Diese Liste wird im Wind/CH1/CH2-Batch verwendet.
# Im Tag-Voting (CH1->CH2->EU) gelten diese Variablen als "CH-eligible".
CH_SURFACE_PARAMS = [
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "temperature_2m", "relative_humidity_2m",
    "cloud_base", "cloud_cover",
    "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "shortwave_radiation", "direct_radiation", "diffuse_radiation",
    "sunshine_duration",
    "precipitation", "precipitation_probability", "rain",
    "weather_code",
    "cape", "convective_inhibition",
    "pressure_msl", "surface_pressure",
    "et0_fao_evapotranspiration", "vapour_pressure_deficit",
    "snow_depth",
]

# --- Legacy-Aliase (Rueckwaertskompatibilitaet fuer Skripte) ---
# Neuer Code soll die kanonischen Namen oben benutzen.
WIND_MODEL    = SURFACE_PRIMARY_MODEL
THERMAL_MODEL = PRESSURE_LEVEL_PRIMARY_MODEL
FALLBACK_MODEL = PRESSURE_LEVEL_FALLBACK_MODEL
PRECIP_MODEL  = PRECIP_DENSE_MODEL
CH1_MODEL = SURFACE_PRIMARY_MODEL
CH2_MODEL = SURFACE_SECONDARY_MODEL
CH1_FORECAST_DAYS = FORECAST_DAYS_CH1
CH2_FORECAST_DAYS = FORECAST_DAYS_CH2
API_MODEL = SURFACE_PRIMARY_MODEL

API_TIMEOUT = 30
FORECAST_DAYS = 5

# Aktive Oberflaechen-/Ausgabesprache (global, vom Admin umstellbar).
# "de" = exakt wie bisher (validiert, keine Zusatz-Anweisung an die LLMs).
# "en" = Oberflaeche/Chat sofort englisch; Spot-/Region-Analysen werden beim
# naechsten Neu-Berechnen englisch erzeugt (bestehender Run-Button).
LANG = "de"
# Vorhersage-Zeitachse: Wanduhrzeit Schweiz (MESZ/MEZ). Open-Meteo liefert `time` in dieser Zone.
TIMEZONE = "Europe/Zurich"

# Referenzpunkte auf der Karte anzeigen (Linien vom Startplatz zu den
# regionalen Thermik-Referenzpunkten beim Hover). False = ausgeblendet.
SHOW_REFERENCE_POINTS = False

# Niederschlags-Referenzpunkte (16 pro Region, CVT-verteilt) auf der Karte
# anzeigen. Visuell klar abgegrenzt von den 7 Haupt-RPs: kleinere blaue
# Kreise mit Tropfen-Symbolik, halbtransparent, keine Beschriftung. Quelle:
# data/regionen_referenzpunkte_precip.geojson (siehe scripts/create_precip_refpoints.py).
SHOW_PRECIP_REFPOINTS = False

# OSM-Peaks/Paesse/Saettel auf allen Karten anzeigen (osm.org-Stil, braune
# Symbole + Label). Daten aus data/osm_peaks_{major,minor}.geojson, gerendert
# via static/js/osm-peaks-layer.js mit Viewport-Culling. True = einblenden.
SHOW_OSM_PEAKS = True

# ============================================================================
# FLUGSTUNDEN-KONFIGURATION
# ============================================================================

FLIGHT_HOURS_START = 6    # Start-Stunde für Flugstunden (0-23)
FLIGHT_HOURS_END = 18    # End-Stunde für Flugstunden (0-23, exklusiv)

# ============================================================================
# WINDRICHTUNGS-TOLERANZ
# ============================================================================
# Erlaubte Abweichung der Windrichtung vom Startplatz-Sektor, als Prozent
# der Sektorbreite. Wird symmetrisch an beide Sektor-Enden angehängt.
# Beispiel: Sektor N-W (= 270°–360°, Breite 90°) + 10% → ±9° Puffer
#           → effektiv erlaubt von 261° bis 9°.
# 0.0 = strikt (nur innerhalb des deklarierten Sektors).
WIND_DIRECTION_TOLERANCE_PCT = 0.10

# ============================================================================
# PFAD-KONFIGURATION
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.absolute()
DATA_DIR = PROJECT_ROOT / "data"

# Spot-CSV: "pge" = Paragliding-Earth-Quelle (495 Spots, Default, Mai 2026),
# "test" = reduziertes Set für Entwicklung (28 Spots, PGE-Schema).
# Beide CSVs nutzen das PGE-Schema (Sektor-Spalten wind_N..wind_NW,
# bemerkungen_flug, bemerkungen_sicherheit).
USE_SPOT_CSV = os.environ.get("WINGCAST_SPOT_CSV", "pge")
CSV_PATH = DATA_DIR / f"fluggebiete_{USE_SPOT_CSV}.csv"
# Region-Referenzpunkte: Default ist CVT-7 (Apr 2026, 7 Punkte im
# Polygon-Innern via Lloyd-CVT). Legacy-Modus nutzt die alten 4 Punkte
# am Polygon-Rand (Greedy Max-Min-Distance). Fallback-Option bei Problemen
# mit der neuen Aggregation. Beide Files muessen in data/ vorliegen.
USE_LEGACY_REGION_REFPOINTS = False
REGIONEN_GEOJSON_PATH = DATA_DIR / "regionen_referenzpunkte.geojson"
REGIONEN_GEOJSON_LEGACY_PATH = DATA_DIR / "regionen_referenzpunkte_legacy4.geojson"
# 16 dichte CVT-Punkte pro Region — NUR fuer Niederschlag (Coverage-Statistik).
# Generiert via scripts/create_precip_refpoints.py.
REGIONEN_GEOJSON_PRECIP_PATH = DATA_DIR / "regionen_referenzpunkte_precip.geojson"
# Master-File fuer Region-Properties (Name, terrain_type, elevation_ref,
# kritischer_foehn, description). Geometrie + reference_points kommen aus
# der GeoJSON, alle textuellen Felder aus dieser CSV.
REGIONEN_CSV_PATH = DATA_DIR / "regionen.csv"

# Vercel: Nur /tmp ist schreibbar. Readonly-Daten (CSV, GeoJSON) bleiben in data/
if os.environ.get("VERCEL"):
    _WRITABLE_DIR = Path("/tmp/wingcast")
    _WRITABLE_DIR.mkdir(parents=True, exist_ok=True)
    WEATHER_JSON_PATH = _WRITABLE_DIR / "wetterdaten.json"
    HISTORY_DIR = _WRITABLE_DIR / "history"
    STATION_DB_PATH = _WRITABLE_DIR / "station_observations.db"
    SUBSCRIBERS_DB_PATH = _WRITABLE_DIR / "subscribers.db"
    FEEDBACK_DB_PATH = _WRITABLE_DIR / "feedback.db"
else:
    WEATHER_JSON_PATH = DATA_DIR / "wetterdaten.json"
    HISTORY_DIR = DATA_DIR / "history"
    STATION_DB_PATH = DATA_DIR / "station_observations.db"
    SUBSCRIBERS_DB_PATH = DATA_DIR / "subscribers.db"
    FEEDBACK_DB_PATH = DATA_DIR / "feedback.db"

# ============================================================================
# SPOT SOURCE AREAS (manuelle Overrides fuer Referenzpunkte)
# ============================================================================
# Pro Spot koennen 4 regionale Referenzpunkte [lat, lon] definiert werden.
# Der Startplatz selbst wird automatisch als Punkt 1 hinzugefuegt.
# Spots ohne Eintrag nutzen die Punkte aus dem Regionen-GeoJSON.

SPOT_SOURCE_AREAS = {
    "Balderen": [
        [47.4150, 8.5900],   # Noerdlich (Altstetten/Hoengg)
        [47.2500, 8.7500],   # Sued-Oestlich (Meilen/Zuerichsee)
        [47.4300, 8.4700],   # Westlich (Dietikon/Schlieren)
        [47.1600, 8.6600],   # Suedlich (Horgen/Zugersee)
    ],
}

# ============================================================================
# WETTERPARAMETER
# ============================================================================

HOURLY_PARAMS = [
    "temperature_2m",
    "relative_humidity_2m",
    "cloud_base",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "cloud_cover",
    "precipitation",
    "rain",
    "precipitation_probability",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "sunshine_duration",
    "cape",
    "boundary_layer_height",
    "surface_pressure",
    "pressure_msl",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "soil_moisture_0_to_1cm",
    "soil_temperature_0cm",
    "updraft",
    "et0_fao_evapotranspiration",
    "vapour_pressure_deficit",
    "snow_depth",
    "weather_code",  # WMO: 95/96/99 = Gewitter
]

# Parameter die via GFS-Supplementary-Call geholt werden (bei icon_seamless oft null)
GFS_SUPPLEMENTARY_PARAMS = [
    "lifted_index",
    "convective_inhibition",
]

# Parameter für den Cross-Check (werden als {param}_gfs gespeichert)
GFS_CROSSCHECK_PARAMS = [
    "boundary_layer_height",
]

# ============================================================================
# NIEDERSCHLAG — REGIONALE AGGREGATION (Hybrid-Filter)
# ============================================================================
# Konvektive Schauer (ICON-D2, 2.2km Aufloesung) erzeugen einzelne Zellen,
# die typisch nur 1-3 von N Referenzpunkten treffen. Reine Quorum-Filter
# (z.B. "30% der RPs muessen Regen melden") killen konvektive Signale
# systematisch.
#
# Industrie-Standard (DWD operational seit 2012, Ebert 2008 "Neighborhood
# Method"): Innerhalb einer Region-Box parallel Maximum + Fractional Coverage
# berechnen. Maximum ist konservativ (worst case), Coverage gibt die
# Verteilungsinformation.
#
# Konservative Schwellen fuer Paragliding (false-negative-averse):
#   - SIGNIFICANT_MM: Ab dieser Peak-Intensitaet wird der Wert OHNE Quorum
#     durchgelassen — eine echte Zelle reicht, egal an wie vielen RPs.
#     WMO/DWD "trace to light precipitation" beginnt bei 0.1 mm/h, in der
#     Praxis spuert ein Pilot ab 0.2 mm/h die Naesse am Schirm.
#   - NOISE_MM: Werte unterhalb gelten als Modell-Rauschen (Float-Spikes,
#     numerische Artefakte) und werden auf 0 geclipt.
#   - COVERAGE_QUORUM: Bei mittleren Werten (NOISE..SIGNIFICANT) gilt
#     weiterhin das alte 30%-Quorum als Fallback, damit verstreute leichte
#     Trace-Werte (z.B. 0.08 mm an 1 RP von 7) nicht zu Fehlalarm fuehren.
PRECIP_SIGNIFICANT_MM = 0.2     # Peak >= 0.2 mm/h → echte Zelle, durchlassen
PRECIP_NOISE_MM = 0.05          # Peak < 0.05 mm/h → Rauschen, auf 0 clipen
PRECIP_COVERAGE_QUORUM = 0.3    # Bei NOISE..SIGNIFICANT: mind. 30% RPs nass

# ============================================================================
# HÖHENWIND-PARAMETER (Pressure Level Daten)
# ============================================================================

PRESSURE_LEVELS = [1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 600]

PRESSURE_LEVEL_PARAMS = []
for _level in PRESSURE_LEVELS:
    PRESSURE_LEVEL_PARAMS.extend([
        f"temperature_{_level}hPa",
        f"wind_speed_{_level}hPa",
        f"wind_direction_{_level}hPa",
        f"geopotential_height_{_level}hPa"
    ])

# ============================================================================
# SYNOPTIK / WETTERLAGE-BLOCK
# ============================================================================
# Konfiguration fuer engine/synoptic_context.py — der "Wetterlage"-Block
# im Wingcast und in der E-Mail. Erzeugt deterministisch eine 5-Tages-
# Einordnung der Grosswetterlage (Druckeinfluss CH, Druckzentren Europa,
# uebergeordnete Stroemung, Niederschlagsmuster Nord/Sued der Alpen,
# Phaenomene wie Foehn/Bise/Vb-Tief).
#
# Wichtig: Alle Klassifikatoren sind deterministisch (Stage-Inversion-Pattern
# analog engine/decision_engine.py). Der LLM bekommt nur die fertigen
# Strukturfelder, keine Rohzahlen. Jedes Feld traegt Provenance (inputs +
# thresholds + decided_by) fuer Audit-Logs.

# --- Europa-Druckraster (Mini-API-Call fuer Druckzentren) ----------------
# 15 Punkte ueber Europa fuer Hoch-/Tief-Erkennung via lokale Extrema.
# Jeder Punkt hat ein statisches Region-Label, das im LLM-Output erscheint.
# Auswahl deckt synoptisch relevante Bereiche fuer CH-Wetter ab:
#   - Atlantik / Britische Inseln (Westlage, Sturmtiefs)
#   - Skandinavien / Mitteleuropa (Bisenlage, Hochdruckbruecken)
#   - Mittelmeer / Norditalien (Suedfoehn, Vb-/Genua-Tief)
EUROPE_PRESSURE_GRID = [
    {"lat": 64.0, "lon": -20.0, "label": "Island"},
    {"lat": 57.0, "lon":  -4.0, "label": "Schottland"},
    {"lat": 52.0, "lon": -15.0, "label": "Atlantik vor Irland"},
    {"lat": 51.0, "lon":   0.0, "label": "England"},
    {"lat": 47.0, "lon":   2.0, "label": "Frankreich"},        # nahe CH/West
    {"lat": 40.0, "lon":  -3.0, "label": "Spanien"},
    {"lat": 65.0, "lon":  15.0, "label": "Nordskandinavien"},
    {"lat": 58.0, "lon":  14.0, "label": "Suedskandinavien"},
    {"lat": 50.0, "lon":  13.0, "label": "Mitteleuropa"},
    {"lat": 44.0, "lon":   9.0, "label": "Norditalien"},
    {"lat": 41.0, "lon":   6.0, "label": "Westliches Mittelmeer"},
    {"lat": 42.0, "lon":  16.0, "label": "Adria"},
    {"lat": 50.0, "lon":  25.0, "label": "Osteuropa"},
    {"lat": 44.0, "lon":  33.0, "label": "Schwarzes Meer"},
    {"lat": 38.0, "lon": -25.0, "label": "Azoren"},
]

# --- Druckzentren-Detektion ---------------------------------------------
# Mindest-Gradient zur Umgebung fuer eine "echte" Hoch/Tief-Erkennung.
# Schwaecher = wird verworfen, NICHT erfunden (Halluzinations-Schutz).
SYNOPTIC_PRESSURE_CENTER_MIN_GRADIENT_HPA = 5.0

# --- CH-Druckeinfluss-Klassifikation ------------------------------------
# Schwellen fuer "Hochdruck" / "Tiefdruck" / "neutral" aus pressure_msl
# (CH-Mittel ueber 14 Regionen, 12 UTC).
SYNOPTIC_HOCH_HPA = 1020.0      # >= 1020 hPa → Hochdruckeinfluss
SYNOPTIC_TIEF_HPA = 1010.0      # <= 1010 hPa → Tiefdruckeinfluss
SYNOPTIC_STRONG_TIEF_HPA = 1000.0  # <= 1000 → starker Tiefdruckeinfluss
# Trend-Schwelle: |ΔP/Tag| ueber dieser Schwelle = signifikante Tendenz
SYNOPTIC_PRESSURE_TREND_THRESHOLD_HPA = 2.0

# --- Uebergeordnete Stroemung (700 hPa) ---------------------------------
# Stuerkeklassen fuer 700-hPa-Wind (CH-Mittel)
SYNOPTIC_FLOW_SCHWACH_KMH = 15      # < 15 km/h → schwach
SYNOPTIC_FLOW_MAESSIG_KMH = 30      # 15-30 → maessig
SYNOPTIC_FLOW_KRAEFTIG_KMH = 50     # 30-50 → kraeftig
                                     # > 50 → stuermisch
# Richtungs-Sektoren (Hauptwindrichtung)
SYNOPTIC_FLOW_SECTORS = [
    (337.5,  22.5, "Nord"),
    ( 22.5,  67.5, "Nordost"),
    ( 67.5, 112.5, "Ost"),
    (112.5, 157.5, "Suedost"),
    (157.5, 202.5, "Sued"),
    (202.5, 247.5, "Suedwest"),
    (247.5, 292.5, "West"),
    (292.5, 337.5, "Nordwest"),
]

# --- Bise-Detektion ------------------------------------------------------
# Bisenlage = Hoch NO-Europa + Tief Mittelmeer + NE-Stroemung ueber CH.
# Detektion deterministisch aus Druckraster + 700hPa-Wind.
SYNOPTIC_BISE_DELTA_P_THRESHOLD_HPA = 4.0  # Druckgefaelle NE-Europa <-> Mittelmeer
SYNOPTIC_BISE_WIND_DIR_MIN = 30            # 700hPa-Wind aus NE-Sektor
SYNOPTIC_BISE_WIND_DIR_MAX = 90
SYNOPTIC_BISE_WIND_MIN_KMH = 15            # Mindest-Stroemung fuer Bise-Label

# --- Vb-/Genua-Tief-Erkennung -------------------------------------------
# Klassisches Vb-Pattern: Tief verlagert sich von Westmittelmeer/Genua
# nordostwaerts ueber Norditalien Richtung Mitteleuropa → Stau Alpennordseite.
# Erkennung: Druckzentrum im Norditalien-/Adria-Bereich UND niedriger Druck.
SYNOPTIC_VB_BOX_LAT_MIN = 40.0
SYNOPTIC_VB_BOX_LAT_MAX = 46.0
SYNOPTIC_VB_BOX_LON_MIN = 5.0
SYNOPTIC_VB_BOX_LON_MAX = 18.0
SYNOPTIC_VB_MAX_MSL_HPA = 1010.0   # Druck im Zentrum muss unter dieser Schwelle liegen

# --- Niederschlag Nord/Sued der Alpen -----------------------------------
# Trennlinie: Regionen mit Schwerpunkt noerdlich oder suedlich der
# Alpenhauptkette. Wird aus regionen.csv abgeleitet (s. synoptic_context.py).
# Schwellen fuer Niederschlagscharakter pro Tag:
SYNOPTIC_PRECIP_DRY_MM = 0.5         # Tages-Peak unter dieser Schwelle = trocken
SYNOPTIC_PRECIP_LIGHT_MM = 2.0       # 0.5-2 mm = leicht
SYNOPTIC_PRECIP_MODERATE_MM = 8.0    # 2-8 mm = maessig, > 8 = stark
SYNOPTIC_PRECIP_COVERAGE_FLAECHIG = 0.7   # Coverage >= 70% = flaechig (stratiform)
SYNOPTIC_PRECIP_COVERAGE_KONVEKTIV = 0.4  # Coverage < 40% + CAPE = konvektiv/Schauer
# DEPRECATED (ungenutzt seit Pure-LLM-Synoptik, Mai 2026): CAPE ist KEIN
# Gewitter-Signal mehr. Gewitter = weather_code 95/96/99 (gewitter_share,
# s. synoptic_context.py / skills/synoptic_overview.md). CAPE = nur noch
# Ueberentwicklungs-Indikator. Siehe docs/GEWITTER.md.
SYNOPTIC_PRECIP_CAPE_KONVEKTIV = 300      # DEPRECATED — ungenutzt
SYNOPTIC_PRECIP_GEWITTER_MIN_WETSHARE = 0.10  # DEPRECATED — ungenutzt

# --- Wind-Fliegbarkeit Nord/Sued der Alpen (wind_pattern) -----------------
# Deterministisches Wind-Aggregat pro Tag/Seite fuer den Synoptik-Block —
# damit die Flug-Bilanz nicht "excellent flying day" sagt, waehrend die
# Region-Analysen am Hoehenwind scheitern (Vorfall 05.07.2026: 23/29
# Regionen Rating 1 wg. Hoehenwind, Synoptik nannte den Tag "excellent").
# Vereinfachtes Flugband relativ zur Spot-Hoehe (die Spot-Analyse nutzt das
# Thermik-Top-Band; fuers CH-weite Aggregat reicht die feste Naeherung):
SYNOPTIC_WIND_BAND_LOWER_M = 200     # Band-Unterkante: Spot-Hoehe + 200 m
SYNOPTIC_WIND_BAND_UPPER_M = 2000    # Band-Oberkante: Spot-Hoehe + 2000 m
SYNOPTIC_WIND_HOURS = (10, 17)       # Kern-Flugfenster (lokale Stunden)
# Kumulative Verteilungs-Baender: Anteil Spots ueber X km/h (Flugband/Boeen).
# Gibt dem Synoptik-LLM das volle Windbild statt eines Schwellen-Flags.
SYNOPTIC_WIND_DIST_BANDS_KMH = (10, 20, 30, 40, 50, 60)
# Kritisch-Schwellen: bewusst identisch zu WIND_WARN_KMH/WIND_DANGER_KMH
# bzw. GUST_WARN_KMH/GUST_DANGER_KMH (dort definiert) — kein zweites Regime.
SYNOPTIC_PRECIP_CAPE_GEWITTER = 800       # DEPRECATED — ungenutzt (CAPE ≠ Gewitter)
SYNOPTIC_PRECIP_SHOWER_MIN_WETSHARE = 0.10  # min. Anteil nasser Spots fuer seitenweite "Schauer"/"Regen"-Aussage; sonst trocken — verhindert dass 1-3% lokale Zellen die ganze Alpenseite als nass labeln

# --- Flugwetter-Zonen (Synoptik 2.0) ------------------------------------
# 4 Zonen als Erzaehl- und Aggregations-Einheit des Wetterlage-Blocks.
# Zuordnung Region -> Zone steht als `zone`-Spalte in data/regionen.csv
# (Region ist atomar — keine Region wird auf mehrere Zonen aufgeteilt).
# Spots erben die Zone ueber ihr `analyse_region`-Feld (fluggebiete_dhv.csv).
SYNOPTIC_ZONES = ("alpennordhang", "wallis", "tessin", "graubuenden_engadin")
SYNOPTIC_ZONE_LABELS = {
    "alpennordhang":       {"de": "Alpennordhang", "en": "Northern Alps"},
    "wallis":              {"de": "Wallis", "en": "Valais"},
    "tessin":              {"de": "Tessin", "en": "Ticino"},
    "graubuenden_engadin": {"de": "Graubuenden & Engadin",
                            "en": "Grisons & Engadine"},
}
# Tagesfenster (lokale Stunden, [start, end)) — Niederschlag/Wind werden pro
# Fenster aggregiert, damit der Block Tagesverlauf statt Tagespauschale kann
# ("Vormittag trocken, ab dem Nachmittag Zellen"). Vorfall 25.07.2026:
# Tagessummen machten aus einem fliegbaren Vormittag einen "Ruhetag".
SYNOPTIC_DAY_WINDOWS = (
    ("morning", 6, 10),
    ("midday", 10, 14),
    ("afternoon", 14, 18),
    ("evening", 18, 21),
)
# Stunden-Schwelle fuer "nass" innerhalb eines Fensters (mm/h) — ein Spot
# zaehlt im Fenster als nass, wenn eine Stunde >= dieser Wert liegt.
SYNOPTIC_PRECIP_WINDOW_WET_MM = 0.2
# Zugbahn-Detektor: Einsetz-Zeit pro Zonen-Gruppe = erste Stunde, in der
# der Anteil nasser Spots die ONSET_SHARE erreicht. Richtungs-Aussage erst
# ab MIN_DIFF_H Stunden Versatz zwischen den Gruppen (sonst "gleichzeitig").
SYNOPTIC_ZUGBAHN_ONSET_SHARE = 0.10
SYNOPTIC_ZUGBAHN_MIN_DIFF_H = 2
SYNOPTIC_ZUGBAHN_MIN_SPOTS = 5
# West/Ost-Split INNERHALB des Alpennordhangs (nur fuer die Zugbahn-Messung,
# keine Erzaehl-Einheit): westlich/oestlich dieser Laenge.
SYNOPTIC_ZUGBAHN_WEST_OST_SPLIT_LON = 8.0

# --- Schneefallgrenze (saisonal) ----------------------------------------
# Nur Maerz-Mai und Oktober-November ausweisen (im Sommer irrelevant,
# im Hochwinter erwartbar).
SYNOPTIC_SNOWLINE_MONTHS = (3, 4, 5, 10, 11)

# --- T850-Trend (Luftmassen-Charakter) ----------------------------------
# Schwelle fuer "deutlich kuehler/waermer" Aenderung ueber die Woche
SYNOPTIC_T850_TREND_THRESHOLD_K = 4.0  # |ΔT850| >= 4 K binnen 24-48h = signifikant

# --- Konfidenz-Decay je Forecast-Tag ------------------------------------
# Sprachhaerte sinkt mit Forecast-Distanz (Pilot-Erwartung aus Recherche).
SYNOPTIC_CONFIDENCE_BY_DAY = {
    0: "high",    # Heute
    1: "high",    # Morgen
    2: "medium",  # Tag 3
    3: "low",     # Tag 4
    4: "low",     # Tag 5
}

# --- Synoptik-Karte (/synoptik): dichtes NE-Atlantik/Europa-Druckraster ---
# Grundlage der interaktiven Bodendruckkarte (Isobaren + H/T-Zentren im
# Met-Office-Stil). Eigenes, dichtes Raster — unabhaengig vom 15-Punkte-Grid
# oben, das nur der Label-Detektion fuer den LLM-Text dient.
# Domain wie die Met-Office-Bodendruckkarten: Neufundland bis Osteuropa,
# Kanaren bis Spitzbergen — Sturmtiefs entstehen weit draussen im Atlantik.
# Modell: ecmwf_ifs025 (global) — icon_eu endet bei 23.5°W und faellt damit aus.
# Wichtig: Domain muss DEUTLICH groesser sein als der sichtbare Karten-
# ausschnitt (VIEW_BOUNDS in synoptic-map.js, 30W-35E / 30-67N) — die Karte
# fuellt je nach Seitenverhaeltnis mehr Flaeche, und an der Domaingrenze
# enden die Isobaren als sichtbarer "Schnitt".
SYNOPTIC_GRID_LAT_MAX = 75.0    # Nordrand (Spitzbergen/Groenland-See)
SYNOPTIC_GRID_LAT_MIN = 20.0    # Suedrand (Sahara)
SYNOPTIC_GRID_LON_MIN = -65.0   # Westrand (Neufundland)
SYNOPTIC_GRID_LON_MAX = 57.5    # Ostrand (Ural/Kaspisches Meer)
SYNOPTIC_GRID_DLAT = 2.5
SYNOPTIC_GRID_DLON = 3.5        # 3.5° lon ≈ 2.2° lat-Aequivalent bei 50°N -> 23 x 36 = 828 Punkte
SYNOPTIC_GRID_HOURS_LOCAL = (0, 6, 12, 18)  # Ausgabezeiten in Lokalzeit (TIMEZONE),
                                            # konsistent mit den Meteogramm-Zeiten
SYNOPTIC_GRID_CHUNK_SIZE = 90   # Punkte pro Open-Meteo Multi-Location-Call (URL-Laenge)
# Zentren-Detektion auf dem dichten Raster (find_grid_pressure_centers):
# kleinere Gradient-Schwelle als beim 15-Punkte-Grid, weil das Fenster
# raeumlich enger ist; Suppression verhindert Zentren-Cluster.
SYNOPTIC_GRID_CENTER_MIN_GRADIENT_HPA = 2.0
SYNOPTIC_GRID_CENTER_WINDOW_CELLS = 3        # Extrema-Fenster-Radius (~600 km)
SYNOPTIC_GRID_CENTER_MIN_DIST_KM = 500.0     # Mindestabstand zwischen Zentren
# Doppelfilter gegen flache Hitzetief-/MSLP-Reduktions-Artefakte (Sommer/Gebirge):
# (a) orographisches Masking — Kandidat verworfen, wenn Zellen-Elevation groesser
#     ist (IMILAST-Bandbreite 1000–1500 m; konservativ 1000, da Grid grob).
# (b) Zirkulations-Check gegen das 700-hPa-Windfeld — Tief braucht zyklonale,
#     Hoch antizyklonale mittlere Tangentialkomponente >= dieser Schwelle.
SYNOPTIC_GRID_CENTER_MAX_ELEV_M = 1000.0
SYNOPTIC_GRID_CENTER_MIN_TANGENTIAL_MS = 2.0
SYNOPTIC_GRID_CACHE_PATH = DATA_DIR / "synoptic_grid.json"

# --- Audit & Cache -------------------------------------------------------
SYNOPTIC_CACHE_PATH = DATA_DIR / "synoptic_context.json"
SYNOPTIC_AUDIT_DIR = DATA_DIR / "synoptic_audit"
SYNOPTIC_AUDIT_KEEP_DAYS = 30   # ältere Audit-Files werden rotiert geloescht

# Vercel-Override (writable nur in /tmp)
if os.environ.get("VERCEL"):
    SYNOPTIC_CACHE_PATH = _WRITABLE_DIR / "synoptic_context.json"
    SYNOPTIC_AUDIT_DIR = _WRITABLE_DIR / "synoptic_audit"
    SYNOPTIC_GRID_CACHE_PATH = _WRITABLE_DIR / "synoptic_grid.json"

# ============================================================================
# THERMIK-BERECHNUNGS-PARAMETER
# ============================================================================

THERMAL_PARAMS = {
    # --- Strahlung → Sensibler Wärmefluss (H) ---
    "direct_radiation_to_H": {
        "winter": 0.22,
        "spring": 0.28,
        "summer": 0.30,
        "autumn": 0.26,
    },
    "diffuse_radiation_to_H": {
        "winter": 0.08,
        "spring": 0.10,
        "summer": 0.14,
        "autumn": 0.11,
    },
    "global_radiation_to_H": {
        "winter": 0.15,
        "spring": 0.18,
        "summer": 0.22,
        "autumn": 0.18,
    },

    # --- H Hard-Cap (W/m²) ---
    "H_cap": {
        "winter": 150,
        "spring": 250,
        "summer": 300,
        "autumn": 200,
    },

    # --- Topografie-Bonus ---
    "topo_bonus_max": 1.45,
    "topo_bonus_H_fraction": 0.4,

    # --- Solare Überhitzung ---
    "solar_excess_max_C": 2.5,
    "solar_excess_H_divisor": 100,

    # --- Entrainment 2. Aufstieg ---
    "second_ascent_entrainment_factor": 0.75,

    # --- Climb-Factor ---
    "climb_factor": {
        "winter": 0.60,
        "spring": 0.85,
        "summer": 0.80,
        "autumn": 0.70,
    },
    "climb_factor_damping_threshold": {
        "winter": 3.5,
        "spring": 4.5,
        "summer": 4.0,
        "autumn": 3.8,
    },
    "climb_hard_cap": 4.5,

    # --- DWD-Updraft-Blending ---
    "use_dwd_updraft_blending": True,
    "dwd_updraft_scale": 2.0,

    # --- Terrain-Differenzierung (Mittelland vs. Alpin) ---
    # Höhenschwellen für lineare Interpolation
    "terrain_elev_low": 800,     # Unterhalb: reine Mittelland-Parameter
    "terrain_elev_high": 1800,   # Oberhalb: reine Alpin-Parameter

    # Alpine H-Cap (höher wegen Felswand-Heizung + Talwindsysteme)
    "alpine_H_cap": {
        "winter": 180,
        "spring": 310,
        "summer": 350,
        "autumn": 240,
    },

    # Alpine Entrainment (weniger Einmischung bei organisierten Alpen-Thermiken)
    "alpine_MU": 0.00015,

    # Cumulus-Entrainment-Reduktion über LCL (Morrison et al. 2021:
    # Feuchte Thermiken haben 1.7x kleinere Ausbreitungsraten → weniger Einmischung)
    "moist_entrainment_factor": 0.6,  # MU über LCL wird auf 60% reduziert (= 40% weniger Einmischung)

    # Alpine Schnee-Dämpfung (weniger aggressiv: Mischoberflächen Fels/Schnee)
    "alpine_snow_damping_factor": 0.50,   # Mittelland: 0.20 (80% Reduktion)
    "alpine_snow_H_max": 150,             # Mittelland: 50 W/m²

    # --- Pressure-Level-Interpolation (Schritt 1 der Terrain-Kalibrierung) ---
    # Vor dem Parcel-Ascent wird das Druckniveau-Profil linear auf feine
    # Hoehenschritte (m) interpoliert. Standard in RASP/RegTherm/XC-Therm.
    # Verbessert Aufloesung im Hochalpinen (native ICON-Levels 400-500 m).
    # 0 = deaktiviert. Default 100 m.
    # Quellen: meteo_research/thermal_model_calibration.md, Wang (2021),
    # Markowski & Richardson (2010).
    "parcel_interp_dz_m": 100,

    # --- GFS-PBL-Cap-Modus (Schritt 3 der Terrain-Kalibrierung) ---
    # Wie wird die GFS-Boundary-Layer-Hoehe als Obergrenze fuer max_thermal_height
    # behandelt? Drei Modi pro Terrain-Zone:
    #   - "hard"        : klassischer harter Cap (max_thermal_height = min(...)).
    #                     Sinnvoll im Mittelland, wo GFS BLH gut kalibriert ist.
    #   - "soft"        : 50/50-Blend zwischen Parcel-Ergebnis und GFS-BLH.
    #                     Vermeidet, dass eine leicht unterschaetzte GFS-BLH die
    #                     Thermik komplett wegschneidet.
    #   - "sanity_only" : Kein Cap, nur Warnung wenn Differenz gross. Wichtig im
    #                     Hochalpinen, weil GFS BLH dort um 200-500 m systematisch
    #                     unterschaetzt ist (Guo 2022).
    "gfs_pbl_cap_mode": {
        "mittelland": "hard",
        "jura":       "hard",
        "voralpen":   "soft",
        "alpen":      "soft",
        "hochalpin":  "sanity_only",
    },
    # Gewicht der GFS-BLH im "soft"-Blend (0.0 = ignorieren, 1.0 = harter Cap).
    # 0.5 = arithmetisches Mittel zwischen Parcel und GFS-BLH.
    "gfs_pbl_soft_weight": 0.5,
    # Schwelle (m) ab der im "sanity_only"-Modus eine Warnung emittiert wird.
    "gfs_pbl_sanity_warn_m": 1500,

    # --- Schnee-Daempfung (Schritt 4 der Terrain-Kalibrierung) ---
    # Wenn snow_depth > 5 cm, wird der sensible Waermefluss H reduziert (Albedo,
    # Schmelzwaerme). 5-Zonen-Aufteilung statt 2-Zonen-Interpolation:
    #   - Mittelland: Flache Wiesen unter Schnee → 80% Reduktion (factor 0.20)
    #   - Jura:       Bewaldet, etwas mehr Restwaerme → 70% Reduktion
    #   - Voralpen:   Mischhang/Wald, 60% Reduktion
    #   - Alpen:      Felswaende + Schnee mosaikartig, 50% Reduktion
    #   - Hochalpin:  Schneefreie Felsbaender, Sonnenintensitaet → 35% Reduktion
    # Quellen: meteo_research/thermal_model_calibration.md (Albedo-Profile),
    # docs/THERMIK_TERRAIN_KALIBRIERUNG.md.
    "snow_damping_factor": {
        "mittelland": 0.20,
        "jura":       0.30,
        "voralpen":   0.40,
        "alpen":      0.50,
        "hochalpin":  0.65,
    },
    "snow_H_max": {
        "mittelland":  50,
        "jura":       100,
        "voralpen":   120,
        "alpen":      150,
        "hochalpin":  180,
    },

    # --- H-Ramp statt harter H_MIN_THRESHOLD (Schritt 5 der Terrain-Kalibrierung) ---
    # Frueher: harter Schwellenwert H_MIN_THRESHOLD = 30 W/m^2 → unter dieser
    # Schwelle 0% Thermik, darueber 100%. Diskontinuierlich + nicht terrain-aware.
    # Neu: linearer Ramp [h_ramp_low, h_ramp_high] (W/m^2). Unter low = 0,
    # ueber high = full, linear in between. Hochalpine Felswaende koppeln
    # bereits bei niedrigem H Konvektion (Hangwindsysteme + organisierte Bloecke),
    # waehrend Mittelland-Flachterrain mehr Brutto-Heizung braucht, um den
    # Convective Trigger zu ueberwinden.
    "h_ramp_low": {
        "mittelland": 30,
        "jura":       25,
        "voralpen":   20,
        "alpen":      15,
        "hochalpin":  10,
    },
    "h_ramp_high": {
        "mittelland": 80,
        "jura":       70,
        "voralpen":   60,
        "alpen":      50,
        "hochalpin":  40,
    },

    # --- Entrainment MU 5-stufig (Schritt 6 der Terrain-Kalibrierung) ---
    # Vorher: MU=0.0002 + alpine_MU=0.00015 (2-Stufen-Interpolation).
    # Neu: 5-stufig pro Zone. Niedrigeres MU im Hochalpinen, weil dort
    # Talwindsysteme + Felswaende organisiertere, kompaktere Schlauche erzeugen
    # (geringere laterale Einmischung mit der Umgebungsluft).
    "entrainment_mu": {
        "mittelland": 0.00022,
        "jura":       0.00020,
        "voralpen":   0.00018,
        "alpen":      0.00015,
        "hochalpin":  0.00012,
    },

    # --- Climb-Factor terrain-Multiplikator (Schritt 6) ---
    # Multiplikator auf den jahreszeitlichen Basis-climb_factor. Im Hochalpinen
    # erzielen Gleitschirme einen groesseren Anteil des theoretischen w*, weil
    # die Schlauche enger und besser zentrierbar sind. Im Mittelland sind die
    # Bloecke breiter und unruhig - geringerer realer Wirkungsgrad.
    "climb_factor_terrain": {
        "mittelland": 0.95,
        "jura":       1.00,
        "voralpen":   1.05,
        "alpen":      1.10,
        "hochalpin":  1.15,
    },

    # --- Mindest-Thermikhoehe AGL (Schritt 2 der Terrain-Kalibrierung) ---
    # Unter dieser Schwelle ueber Startplatz wird die Thermik als nicht nutzbar
    # eingestuft (Rating <= 1, climb = 0).
    # Terrain-differenziert nach `gust_calculator`-Taxonomie (5 Klassen):
    #   - mittelland: Flache Lagen brauchen tiefe Grenzschicht um brauchbar zu
    #     sein (Startthermik oft > 400 m AGL bis verlaesslich).
    #   - jura: Mittelhoehe, etwas niedrigere Schwelle.
    #   - voralpen: Uebergangsbereich.
    #   - alpen: Felswaende und Hangwinde starten schon flach.
    #   - hochalpin: Hohe Gipfel, kurze aber intensive Ablosungen - 150 m
    #     AGL koennen bereits genuegen (Tessin/Wallis-Fix).
    # Die alte 150-m-Konstante galt pauschal und killte Hochgebirgs-Thermik
    # im Modell nicht, sondern verwarf Mittelland-Blasen zu grosszuegig.
    # Quellen: meteo_research/thermal_model_calibration.md,
    # docs/THERMIK_TERRAIN_KALIBRIERUNG.md.
    "min_thermal_depth_agl": {
        "mittelland": 400,
        "jura": 350,
        "voralpen": 300,
        "alpen": 200,
        "hochalpin": 150,
    },

    # --- Rock-Face Bonus bei Schneedecke (Zentralwallis-Fix) ---
    # Im (hoch-)alpinen Gelaende sind suedexponierte Felswaende im Fruehling
    # trotz Schneedecke schneefrei und erreichen Oberflaechentemperaturen von
    # 20-30 Grad C, waehrend T2m durch den Schnee auf ~0 Grad C gepinnt wird.
    # Dies erzeugt eine starke bodennahe Inversion, die den regionalen
    # Paketaufstieg sabotiert (Zentralwallis-Problem: max_h bleibt an elev_ref
    # kleben, obwohl 800 W/m^2 Einstrahlung vorhanden sind).
    #
    # Die beiden Parameter erlauben die solare Ueberhitzung auch unter Schnee,
    # wenn die Terrain-Zone Felswaende enthaelt. Mittelland/Jura: komplett
    # blockiert (keine Rock Faces).
    #
    # dt_excess(snow, alpin) = base_dt * rock_face_base_fraction + rock_face_dt_boost_C
    # mit base_dt = min(solar_excess_max_C, H / solar_excess_H_divisor)
    "rock_face_dt_boost_C": {
        "mittelland": 0.0,
        "jura":       0.0,
        "voralpen":   0.8,
        "alpen":      1.5,
        "hochalpin":  2.5,
    },
    "rock_face_base_fraction": {
        "mittelland": 0.0,
        "jura":       0.0,
        "voralpen":   0.3,
        "alpen":      0.5,
        "hochalpin":  0.7,
    },
}

# ============================================================================
# WIND-SCHERUNG / THERMIK-QUALITAET (Label-Schwellen fuer chat_engine.py)
# Basis: meteo_research/wind_shear_thermal_quality.md
# ============================================================================

# Vertikale Windscherung durch die Mischungsschicht (km/h pro 100 m).
# Ab WARN wird die Thermik sichtbar gekippt, ab DANGER zerrissen.
# Skalierung nach Terrain-Zone (groessere Zonen = groessere Blasen =
# widerstandsfaehiger gegen Scherung, Skalierung ~ sqrt(L_up/L_up_ref)).
#
# WICHTIG: Mittelland/Jura haben HOEHERE Schwellen als Alpen, weil sie auf
# tiefer Elevation liegen (700-1200m) und die normale Grenzschicht-Scherung
# (Ekman-Spirale: ruhig am Boden, 15-25km/h auf 1500m) IMMER 1.0-2.0
# km/h/100m erzeugt. Das ist kein gefaehrliches Wind-Event sondern der
# normale PBL-Gradient. In den Alpen (1800m+) liegt die Oberflaeche
# bereits in/ueber der Grenzschicht — dort zeigt die gleiche Scherung
# tatsaechlich ein Scherungsereignis an.
SHEAR_THRESHOLDS = {
    "mittelland": {"warn": 2.0, "danger": 3.5},
    "jura":       {"warn": 1.8, "danger": 3.0},
    "voralpen":   {"warn": 1.5, "danger": 2.5},
    "alpen":      {"warn": 1.8, "danger": 2.8},
    "hochalpin":  {"warn": 2.0, "danger": 3.0},
}

# Buoyancy-over-Shear-Ratio (Glendening / RASP).
# Proxy-Formel: simple_BS = (w* [m/s]) / (dU_dz [km/h/100m]) * 100
# Eichung zur Standardform: w*=2, dU=1km/h/100m -> simple_BS=200 (sehr gut)
#                           w*=2, dU=2km/h/100m -> simple_BS=100 (Grenze gut/mittel)
#                           w*=1, dU=2km/h/100m -> simple_BS= 50 (zerrissen-Grenze)
# Skaliert relativ zur Standard-B/S (>=10 gut, <=3 unfliegbar): Faktor ~20.
BS_RATIO_THRESHOLDS = {
    "warn":   100,   # entspricht B/S ~ 5  — Thermik wird spuerbar gestoert
    "danger": 60,    # entspricht B/S ~ 3  — Thermik zerrissen, nur Brocken
}

# Gust Factor: delta_gust [m/s] / w* [m/s]   (dimensionslos)
# delta_gust = (wind_gusts_10m - wind_speed_10m) / 3.6
# w* kommt aus climb_rate des Thermik-Modells.
GUST_FACTOR_THRESHOLDS = {
    "warn":   1.0,   # Turbulenz ~ Auftrieb, Blase fleckig
    "danger": 2.0,   # Turbulenz > 2x Auftrieb, Blase fragmentiert
}

# Konvektive Böen-Korrektur (Panofsky et al. 1977 + COSMO gust diagnostic):
# Auf konvektiven Tagen enthält wind_gusts_10m einen Beitrag von ~α × σ_u/w* × w*
# mit α ≈ 3.0 (COSMO) und σ_u/w* ≈ 0.6 (Panofsky 1977) → 1.8 × w*.
# Dieser Anteil IST die Thermik-Konvektion, keine mechanische Störung.
# Vor GF-Berechnung wird dieser Anteil abgezogen.
CONVECTIVE_GUST_BETA = 1.8

# Unter diesem mechanischen Exzess (m/s) wird bei GF >= danger
# FRAGMENTED statt UNUSABLE vergeben — das Problem ist schwache Thermik,
# nicht extreme Turbulenz.
GF_DANGER_MIN_MECHANICAL_MS = 3.0

# Mittlerer Grundwind durch die Mischungsschicht (km/h).
# Alternative/ergaenzende Schwelle falls SHEAR-Berechnung wegen fehlender
# pressure levels nicht verfuegbar ist.
BL_MEAN_WIND_THRESHOLDS = {
    "mittelland": {"warn": 20, "danger": 28},
    "jura":       {"warn": 22, "danger": 30},
    "voralpen":   {"warn": 25, "danger": 32},
    "alpen":      {"warn": 28, "danger": 35},
    "hochalpin":  {"warn": 30, "danger": 38},
}

# Minimum climb_rate fuer Tag-Aktivierung — unter diesem Wert wird keine
# Thermik-Qualitaets-Warnung ausgegeben (keine Thermik -> keine Zerrissenheit).
THERMAL_QUALITY_MIN_CLIMB = 0.3   # m/s

# Produktive-Thermik-Schwellen (Flyability-Tier-Berechnung)
PRODUCTIVE_CLIMB_MIN = 0.7      # m/s — Mindest-Climb fuer "produktive" Stunde
# Wolken-Schwellen: tief und mittel getrennt (meteo_research/cloud_cover_thermal_impact.md Sektion 6).
# Tiefe Wolken (<3000m) werfen direkten Schatten auf die Quellflaeche → harter Kill ab 80% (FAA).
# Mittlere Wolken (3000-6000m, Altostratus) reduzieren Einstrahlung nur indirekt, sitzen ueber der
# Thermik-Arbeitshoehe → "praktisch tot" laut FAA erst >87%, daher lockerer bei 90%.
PRODUCTIVE_LOW_CLOUD_MAX = 80   # % — Max cloud_cover_low fuer "produktive" Stunde
PRODUCTIVE_MID_CLOUD_MAX = 90   # % — Max cloud_cover_mid fuer "produktive" Stunde
PRODUCTIVE_CLOUD_MAX = 80       # % — DEPRECATED, behalten fuer Abwaertskompatibilitaet. Nutze LOW/MID getrennt.
PRODUCTIVE_HOURS_FOR_GREEN = 4  # Mindest-Stunden fuer gray->green Upgrade
PRODUCTIVE_HOURS_DOWNGRADE = 2  # Untere Schwelle: green/violet -> gray

# ─── OVERCAST-DANGER (Sicherheits-Gate, killt clean_hours → not_safe) ───
# Gefahr = dichte, geschlossene Wolkendecke AUF oder UNTER Startplatzhoehe:
#   - "Start in die Wolke" (Decke auf Platzhoehe) ODER
#   - "Decke unter mir, komme nicht sicher zum Landeplatz runter" (Talstratus).
# Wolken OBERHALB des Platzes sind KEINE Gefahr (nur Thermik-Reducer) → kein Stop.
# Open-Meteo-Schichten (verifiziert): low 0-3km, mid 3-8km, high >8km, MSL.
# Fuer "Decke unter mir" zaehlt immer die TIEFE Schicht (Talstratus ist low);
# bei hochalpinem Startplatz (elev >= MID_BAND_MIN) liegt der Platz selbst in der
# mittleren Schicht → dann zaehlt zusaetzlich cloud_cover_mid.
# Hergeleitet aus Scheidegg-2026-06-05-Analyse: alte Regel (base<elev+500 AND
# total_cover>=75) flaggte Luftraum 464m UEBER dem Platz faelschlich als not_safe.
OVERCAST_DANGER_BASE_BUFFER_M = 100   # m — Decke gilt als "auf Platzhoehe" bis elev+dies
OVERCAST_DANGER_COVER_PCT = 80        # % — ab dieser Bedeckung = geschlossene Decke
OVERCAST_MID_BAND_MIN_M = 3000        # m — ab hier liegt der Platz in der mittleren Schicht

# ─── CLOUDS-Reducer-Zone (Flyability, KEIN Stop) ───
# Wolkenbasis ueber dem Startplatz, aber nicht hoch (BASE_BUFFER..REDUCER_BASE_MAX):
# fliegbar, aber eingeschraenkte Arbeitshoehe → CLOUDS-`reducer`-Tag (Label
# "Basis nahe Startplatz"), Status bleibt gruen. Darueber: kein Effekt. Darunter
# (auf/unter Platz, dicht): OVERCAST-DANGER (Stop). Nur wenn tiefe Decke vorhanden.
OVERCAST_REDUCER_BASE_MAX_M = 400     # m — obere Grenze der Reducer-Zone ueber Platz
OVERCAST_REDUCER_COVER_PCT = 75       # % — Mindest-tiefe-Bedeckung fuer Reducer

# Violett-Kriterien (XC-Tag). LLM entscheidet final, aber TAGESPROFIL zeigt diese
# Schwellen als Violett-Kandidat-Hint. Research: meteo_research/cloud_cover_thermal_impact.md
# - Wolken-Maxima 50/50 matchen FAA-Daempfungsgrenze: darueber beginnt signifikante
#   Einstrahlungsreduktion (Altostratus ab ~50%, Cu-Dampfung ab 50-60%). Violett =
#   optimale Cu-Zone (12-50% SCT) oder Blau (0%), keine Ueberentwicklung.
# - Peak 2.5 m/s und 5h produktiv strenger als green (4h) = "gute Konsistenz" fuer XC.
# - ROUGH/UNUSABLE<30% = saubere Thermik, keine Bart-Zentrierungsprobleme.
VIOLET_PEAK_MIN = 2.5           # m/s — Mindest-Peak fuer Violett-Kandidat
VIOLET_HOURS_MIN = 5            # Mindest-produktive-Stunden fuer Violett
VIOLET_ROUGH_MAX = 30           # % — Max ROUGH-UNUSABLE-Anteil
VIOLET_UNUSABLE_MAX = 30        # % — Max Gesamt-UNUSABLE-Anteil
VIOLET_CLOUD_LOW_MAX = 50       # % — Max Ø tiefe Wolken ueber Thermikstunden
VIOLET_CLOUD_MID_MAX = 50       # % — Max Ø mittlere Wolken ueber Thermikstunden
VIOLET_RATING_MIN = 9           # Mindest-Rating (0-10) fuer violet — nur Ausnahmetage
# PRODUCTIVE_BAND_DEPTH_MIN entfernt (war 400 m, physikalisch unfundiert).
# Ersetzt durch thermik_calculator.min_band_depth(climb_peak, terrain_zone):
# climb-abhaengig (3 Kurbeln × 7 s × Netto-Steigen) und terrain-differenziert.
# Siehe meteo_research/band_depth_calibration.md.

# ─── Wind-Schwellen (Boden + Hoehe einheitlich, Spot + Region) ───
# Konservative Auslegung: Ab WIND_DANGER_KMH ist die Stunde gefaehrlich,
# zwischen WIND_WARN_KMH und WIND_DANGER_KMH "kraeftig" (sportlich).
# Gilt fuer Bodenwind (10m) UND Hoehenwind W(z) im Flugbereich.
# Flugbereich = elevation_ref bis thermal_top + 1000m (effective_ceiling).
WIND_WARN_KMH = 20              # Wind 20–30 km/h → [WIND-WARN] / [ALOFT-WIND-WARN]
WIND_DANGER_KMH = 30            # Wind > 30 km/h → [WIND-DANGER] / [ALOFT-WIND-DANGER]

# Idealbereich Bodenwind fuer Thermik-Spots (Default-Annahme).
# Soaring-Spots (z.B. Balderen) brauchen oft mehr — siehe Spot-Bemerkung im
# Datenblock. Fuer wind_safety_rating in der Sub-Rating-Bewertung (siehe
# skills/shared/_safety_subratings.md): 9-10 = innerhalb dieses Bereichs.
WIND_IDEAL_MIN_KMH = 5          # km/h — unter diesem: zu schwach fuer typische Bedingungen
WIND_IDEAL_MAX_KMH = 20         # km/h — ab diesem: ueber Komfortzone (= WIND_WARN_KMH)

# ─── Start-Fenster-Schwellen (Windrichtung + Gefahrenfreiheit) ───
# Eine "saubere Stunde" = WIND-OK (Spot-Sektor) UND keine DANGER-Tags.
# Tag-Status haengt am laengsten zusammenhaengenden Block sauberer Stunden:
#   < CLEAN_WINDOW_MIN_HOURS   → not_safe (kein ausreichendes Start-Fenster)
#   >= CLEAN_WINDOW_GREEN_HOURS → safe/green moeglich (LLM entscheidet conditional vs safe)
# Schwellen sind absichtlich identisch: keine Zwischenzone "max conditional" mehr —
# entweder reicht das Fenster (>=3h) oder nicht (<3h). Pre-Filter wendet dieselbe
# Schwelle deterministisch auf wind_ok_count an (siehe analyzers._prefilter_not_safe).
# WIND-WRONG Stunden NACH dem Start-Fenster sind kein Grund fuer UNFLIEGBAR —
# der Pilot ist bereits in der Luft, Landung i.d.R. auf separatem Landeplatz.
CLEAN_WINDOW_MIN_HOURS = 2       # h — unterhalb: not_safe
CLEAN_WINDOW_GREEN_HOURS = 2     # h — ab hier: safe/green moeglich

# Bei Flaute ist die Windrichtung bedeutungsloses Rauschen (Thermik-/Talwind-
# Drehen, kein Gradient) — unter dieser Schwelle kann man aus jeder Richtung
# starten, die Sektor-Pruefung wird uebersprungen (immer WIND-OK). Deckt sich mit
# der Nullwind-Grenze (Abhebe-Airspeed ~30 km/h; <5 km/h aendert das Laufen kaum)
# und WIND_IDEAL_MIN_KMH. Siehe validation/xcontest/I013_DIAGNOSE.md (Hebel A).
WIND_DIRECTION_IRRELEVANT_BELOW_KMH = 5   # km/h — darunter: Richtung egal, immer WIND-OK

# Richtungsdreher-Anmerkung (nur caution_notes, KEIN Status-Downgrade):
# Erfasst den groessten Richtungsdreher innerhalb eines gleitenden Fensters von
# bis zu WIND_DIRECTION_SWING_WINDOW_H Stunden — sowohl abrupte 1h-Spruenge als
# auch langsames Drehen ueber 2-3h (z.B. 120° ueber 3h = unbestaendiger Wind).
# Ab WIND_DIRECTION_SWING_NOTE_DEG° gibt es einen Pilot-Hinweis in caution_notes.
WIND_DIRECTION_SWING_NOTE_DEG = 45   # Grad — Schwelle fuer caution_notes-Hinweis
WIND_DIRECTION_SWING_WINDOW_H = 3    # Stunden — max Fensterbreite fuer Drift-Erkennung

# ─── Boeen-Schwellen (Boden + Hoehe einheitlich, nur Spots) ───
# Boden: wind_gusts_10m (nach Bias-Korrektur + Multi-Modell-Merge).
# Hoehe: T(z) = W(z) + exp-Decay vom Bodenboeen-Exzess (Turbulenzrisiko).
GUST_WARN_KMH = 30              # Boeen > 30 km/h → [GUST-WARN] / [ALOFT-GUST-WARN]
GUST_DANGER_KMH = 40            # Boeen > 40 km/h → [GUST-DANGER] / [ALOFT-GUST-DANGER]

# ─── CAPE-Schwellen (Konvektionsenergie, J/kg) ───
# CAPE-DANGER (hart): extreme Instabilität ODER CAPE + Regen (aktive Ueberentwicklung).
# CAPE-WARN (soft):   Potenzial vorhanden, Modell prognostiziert keinen Trigger.
CAPE_WARN_JKG = 800             # CAPE > 800 J/kg → [CAPE-WARN]
CAPE_DANGER_JKG = 1500          # CAPE > 1500 J/kg → [CAPE-DANGER]
# Deckel-Gate (docs/GEWITTER.md §8 A1): Konvektive Hemmung (CIN, positiv) ueber
# dieser Schwelle ohne Trigger deckelt die Konvektion → das weiche [CAPE-WARN]
# wird unterdrueckt (verhindert "CAPE bei blauem Himmel"-Fehlalarme). Greift NUR
# beim weichen WARN, nie bei [CAPE-DANGER]; ohne CIN-Wert keine Unterdrueckung.
CAPE_LID_CIN_JKG = 150          # CIN > 150 J/kg (positiv!) = geschlossener Deckel

# Wind/Boeen-Trend Schwellen (Stunden) — gilt fuer Boden + Hoehe summiert:
# - CONDITIONAL_HOURS: safe → conditional (Trend-Pattern wirft sauberes Fenster).
# - NOTSAFE_HOURS:    Wind-Trend DURCHGEHEND_DANGER / EINGEKESSELT (Fenster<3h)
#                     → harter NO-GO. Boeen-Trend → LLM-Empfehlung "bevorzugt NoGo".
WIND_TREND_CONDITIONAL_HOURS = 3
WIND_TREND_NOTSAFE_HOURS = 3
GUST_TREND_FLOOR_HOURS = 3       # Min. Stunden fuer Boeen-Floor (Boden+Hoehe summiert)

# ============================================================================
# INSTANTDB-KONFIGURATION
# ============================================================================

# ============================================================================
# STATIONSDATEN + BIAS-KORREKTUR
# ============================================================================

WINDS_MOBI_API = "https://winds.mobi/api/2.3"
STATION_SEARCH_RADIUS_KM = 30
STATION_MAX_ELEV_DIFF_M = 300   # Vorher 500 — enger, weniger Expositions-Verfälschung
STATION_MAX_PER_SPOT = 3
BIAS_CORRECTION_ENABLED = False   # Bias-Korrektur auf wind_gusts_10m anwenden (Spots + Regionen)
MULTI_MODEL_GUST_MERGE = False    # wind_gusts_10m = max(D2, CH1, CH2). False = nur WIND_MODEL verwenden
BIAS_LOOKBACK_DAYS = 14
BIAS_ALPHA = 0.85         # Exponentieller Gewichtungsfaktor (jüngere Paare stärker)
BIAS_MIN_PAIRS = 5        # Mindestanzahl Paare bevor Bias angewendet wird
BIAS_MAX_CORRECTION = 15  # Max ±15 km/h Korrektur (Sicherheitslimit)
BIAS_ELEV_DECAY_HG = 400  # H_g für Höhenkorrektur Station→Spot (m)

# ============================================================================
# TAEGLICHER ABLAUF (Wetter-Refresh + LLM-Analyse + Briefing-Versand)
# ============================================================================
# Sequenzieller Job: refresh_weather() -> build_briefing_data() (LLM) -> Mails.
# Wochentage: 0=Mo, 1=Di, 2=Mi, 3=Do, 4=Fr, 5=Sa, 6=So
DAILY_RUN_WEEKDAYS = {0, 1, 2, 3, 4, 5, 6}  # Default: jeden Tag
DAILY_RUN_HOUR     = 6
DAILY_RUN_MINUTE   = 0

# ============================================================================
# E-MAIL-BRIEFING (SMTP Infomaniak)
# ============================================================================
# BASE_URL = App-Domain (Flask), MARKETING_URL = Marketing-Webpage (Next.js).
# In Produktion: BASE_URL=https://app.wingcast.ch, MARKETING_URL=https://wingcast.ch
BASE_URL        = os.environ.get("WINGCAST_BASE_URL",      "https://app.wingcast.ch")
MARKETING_URL   = os.environ.get("WINGCAST_MARKETING_URL", "https://wingcast.ch")

# PUBLIC_DEMO_MODE: oeffnet den Chat-Berater OHNE Login (fuer oeffentliche
# Tests, z.B. Reddit). Normalbetrieb: der Chat verlangt Login (Registrierung).
# Ist der Schalter an, faellt die Login-Pflicht am /api/chat weg und die Chat-UI
# wird auch anonymen Besuchern gezeigt; jeder Browser bekommt einen eigenen
# anonymen Verlauf. ACHTUNG: kein Rate-Limit — jede Nachricht ruft das LLM auf
# (Kosten/Missbrauch bei oeffentlichem Link). Nach dem Test wieder auf "0".
PUBLIC_DEMO_MODE = os.environ.get("PUBLIC_DEMO_MODE", "0") == "1"

# PostHog Product-Analytics (nur nach Opt-in-Consent im Browser geladen).
# Leerer KEY => Analytics komplett deaktiviert (Banner erscheint dann nicht).
POSTHOG_KEY     = os.environ.get("POSTHOG_KEY", "").strip()
POSTHOG_HOST    = os.environ.get("POSTHOG_HOST", "https://eu.i.posthog.com").strip()
POSTHOG_UI_HOST = os.environ.get("POSTHOG_UI_HOST", "https://eu.posthog.com").strip()

# Infomaniak SMTP (Standardwerte aus ihrer Doku; Port 465 SSL oder 587 STARTTLS)
SMTP_HOST       = os.environ.get("SMTP_HOST", "mail.infomaniak.com")
SMTP_PORT       = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USE_SSL    = os.environ.get("SMTP_USE_SSL", "1") == "1"   # True = SSL:465, False = STARTTLS:587
SMTP_USER       = os.environ.get("SMTP_USER", "")               # meist = SENDER_EMAIL
SMTP_PASSWORD   = os.environ.get("SMTP_PASSWORD", "")
SENDER_EMAIL    = os.environ.get("SENDER_EMAIL", "briefing@example.invalid")
SENDER_NAME     = os.environ.get("SENDER_NAME", "Wingcast")

# Admin = passwortlos: Admin ist, wer mit dieser E-Mail eingeloggt ist
# (Magic-Link-Session). Kein Passwort mehr.
ADMIN_EMAIL     = os.environ.get("ADMIN_EMAIL", "mutschgito@hotmail.com")

# Betriebsalarm fuer Datenketten, die an fremden Quellen haengen (zurzeit das
# DWD-Frontenarchiv, scripts/fronten_alarm.py). BEWUSST NICHT ADMIN_EMAIL:
# das ist die Magic-Link-Identitaet des Admins, und der Wetterlage-Alarm haengt
# daran — wer den Betriebsempfaenger aendert, wuerde die sonst ungefragt
# mitverschieben.
OPS_ALERT_EMAIL = os.environ.get("OPS_ALERT_EMAIL", "info@wingcast.ch")

# Salt fuer die IP-Anonymisierung im Feedback (SHA-256). Reiner Hash-Salt,
# keine Auth-Funktion.
FEEDBACK_SALT   = os.environ.get("FEEDBACK_SALT", "wingcast-feedback")

# ============================================================================
# ROUTING / GEOCODING (Phase 1)
# ============================================================================
# Public Valhalla (FOSSGIS-gehostet) für Isochronen + Routing.
# Public Nominatim für Geocoding. Bei Ausfall: kein Fallback — siehe routing.py.
VALHALLA_URL = os.environ.get("VALHALLA_URL", "https://valhalla1.openstreetmap.de")
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org")
ROUTING_TIMEOUT = 15  # seconds (Valhalla + Nominatim HTTP)
ROUTING_USER_AGENT = "Wingcast/1.0 (paragliding weather app)"
GEOCODE_CACHE_TTL = 24 * 3600  # 24h in-memory cache für Nominatim

# ============================================================================
# LLM-PROVIDER + MODELL (Chat + Analyse getrennt konfigurierbar)
# ============================================================================
# Vier unterstuetzte Provider: "openai" | "anthropic" | "gemini" | "deepseek"
#   - openai    : gpt-4o-mini (guenstig, Batch-API, bekannt stabil)
#   - anthropic : Claude Haiku 4.5 (beste Tool-Call + DE-Qualitaet)
#   - gemini    : Gemini 2.5 Flash / Flash-Lite (guenstigste Option)
#   - deepseek  : DeepSeek-V3 (sehr guenstig, OpenAI-kompatibel, China-gehostet, keine Batch-API)
#
# Hybrid-Setup moeglich: z.B. Chat=deepseek (Prosa), Analyse=openai (Batch-Rabatt).
# Jeder aktive Provider braucht den entsprechenden API-Key als ENV-Variable.

CHAT_PROVIDER = os.environ.get("CHAT_PROVIDER", "openai").lower()
ANALYSIS_PROVIDER = os.environ.get("ANALYSIS_PROVIDER", "openai").lower()

# Modell pro Provider + Anwendung. ENV-Overrides erlauben Feintuning.
LLM_MODELS = {
    "openai": {
        "chat":     os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        "analysis": os.environ.get("OPENAI_ANALYSIS_MODEL", "gpt-4o-mini"),
    },
    "anthropic": {
        "chat":     os.environ.get("ANTHROPIC_CHAT_MODEL", "claude-haiku-4-5"),
        "analysis": os.environ.get("ANTHROPIC_ANALYSIS_MODEL", "claude-haiku-4-5"),
    },
    "gemini": {
        "chat":     os.environ.get("GEMINI_CHAT_MODEL", "gemini-2.5-flash"),
        "analysis": os.environ.get("GEMINI_ANALYSIS_MODEL", "gemini-2.5-flash-lite"),
    },
    "deepseek": {
        # Verfuegbare Modelle:
        #   deepseek-v4-flash   = V4 Flash (284B MoE, $0.14/$0.28 per Mtok, 1M context)
        #   deepseek-v4-pro     = V4 Pro   (1.6T MoE, $0.435/$0.87 per Mtok, 1M context)
        # Abgeschaltet 24.07.2026: deepseek-chat / deepseek-reasoner. deepseek-chat
        # war seit ~24.04.2026 ohnehin nur ein Alias auf v4-flash (non-thinking).
        "chat":     os.environ.get("DEEPSEEK_CHAT_MODEL", "deepseek-v4-flash"),
        "analysis": os.environ.get("DEEPSEEK_ANALYSIS_MODEL", "deepseek-v4-flash"),
    },
}

# Top-Level-Attribute fuer Admin-UI-Override (config_overrides.setattr greift hier).
# get_model() liest bevorzugt diese Attribute, damit Aenderungen via Admin-UI
# ohne Neustart wirken (chat_engine cached pro Init — Neustart trotzdem noetig,
# damit aktive Engine-Instanzen das neue Modell sehen).
OPENAI_CHAT_MODEL        = LLM_MODELS["openai"]["chat"]
OPENAI_ANALYSIS_MODEL    = LLM_MODELS["openai"]["analysis"]
ANTHROPIC_CHAT_MODEL     = LLM_MODELS["anthropic"]["chat"]
ANTHROPIC_ANALYSIS_MODEL = LLM_MODELS["anthropic"]["analysis"]
GEMINI_CHAT_MODEL        = LLM_MODELS["gemini"]["chat"]
GEMINI_ANALYSIS_MODEL    = LLM_MODELS["gemini"]["analysis"]
DEEPSEEK_CHAT_MODEL      = LLM_MODELS["deepseek"]["chat"]
DEEPSEEK_ANALYSIS_MODEL  = LLM_MODELS["deepseek"]["analysis"]

# Mapping Modellname -> Provider. Wird vom Admin-UI verwendet, um aus einem
# einzelnen CHAT_MODEL/ANALYSIS_MODEL-Dropdown den Provider abzuleiten.
# Bei neuen Modellen hier eintragen — sonst greift der Auto-Provider nicht.
MODEL_PROVIDER_MAP: dict[str, str] = {
    # OpenAI
    "gpt-5.5": "openai", "gpt-5.4": "openai", "gpt-5.4-mini": "openai",
    "gpt-5.4-nano": "openai", "gpt-5.3-codex": "openai",
    "gpt-4o": "openai", "gpt-4o-mini": "openai",
    # Anthropic
    "claude-opus-4-7": "anthropic", "claude-opus-4-6": "anthropic",
    "claude-sonnet-4-6": "anthropic", "claude-opus-4-5": "anthropic",
    "claude-sonnet-4-5": "anthropic", "claude-haiku-4-5": "anthropic",
    # Gemini
    "gemini-2.5-pro": "gemini", "gemini-2.5-flash": "gemini",
    "gemini-2.5-flash-lite": "gemini",
    # DeepSeek
    "deepseek-v4-pro": "deepseek", "deepseek-v4-flash": "deepseek",
    "deepseek-chat": "deepseek", "deepseek-reasoner": "deepseek",
}

# Single Source of Truth fuer Admin-UI: ein Modellname pro Anwendung.
# Provider wird beim Override automatisch via MODEL_PROVIDER_MAP abgeleitet
# und CHAT_PROVIDER/ANALYSIS_PROVIDER + per-provider-Modell-Attr nachgezogen.
def _resolve_provider_and_model(name: str, purpose: str) -> tuple[str, str]:
    """Toleriert wenn jemand einen Modellnamen statt Provider-Namen in ENV
    geschrieben hat (z.B. ANALYSIS_PROVIDER=deepseek-v4-pro). Liefert immer
    ein gueltiges (provider, model)-Paar."""
    if name in LLM_MODELS:
        return name, LLM_MODELS[name][purpose]
    if name in MODEL_PROVIDER_MAP:
        prov = MODEL_PROVIDER_MAP[name]
        logging.getLogger(__name__).warning(
            "%s_PROVIDER='%s' ist ein Modellname, kein Provider — interpretiere als provider=%s, model=%s.",
            purpose.upper(), name, prov, name)
        return prov, name
    logging.getLogger(__name__).warning(
        "%s_PROVIDER='%s' unbekannt — falle zurueck auf 'openai'.", purpose.upper(), name)
    return "openai", LLM_MODELS["openai"][purpose]


CHAT_PROVIDER, CHAT_MODEL         = _resolve_provider_and_model(CHAT_PROVIDER, "chat")
ANALYSIS_PROVIDER, ANALYSIS_MODEL = _resolve_provider_and_model(ANALYSIS_PROVIDER, "analysis")
# Per-provider-Attr nachziehen, damit get_model() konsistent bleibt
LLM_MODELS[CHAT_PROVIDER]["chat"]         = CHAT_MODEL
LLM_MODELS[ANALYSIS_PROVIDER]["analysis"] = ANALYSIS_MODEL
globals()[f"{CHAT_PROVIDER.upper()}_CHAT_MODEL"]         = CHAT_MODEL
globals()[f"{ANALYSIS_PROVIDER.upper()}_ANALYSIS_MODEL"] = ANALYSIS_MODEL

# SYNOPTIC_MODEL — separates Modell fuer den Wetterlage-Block (1x/Tag Call).
# Default = ANALYSIS_MODEL (Rueckwaerts-kompatibel). Ueber ENV `SYNOPTIC_MODEL`
# oder Admin-UI separat ueberschreibbar (z.B. deepseek-v4-flash,
# waehrend ANALYSIS_MODEL fuer die Massen-Spot-Analyse auf deepseek-chat bleibt).
# Hinweis: der Thinking-Modus fuer diesen Call haengt an SYNOPTIC_THINKING
# (unten), NICHT an DEEPSEEK_DISABLE_THINKING.
_synoptic_override = os.environ.get("SYNOPTIC_MODEL", "").strip()
if _synoptic_override and _synoptic_override in MODEL_PROVIDER_MAP:
    SYNOPTIC_MODEL    = _synoptic_override
    SYNOPTIC_PROVIDER = MODEL_PROVIDER_MAP[_synoptic_override]
else:
    SYNOPTIC_MODEL    = ANALYSIS_MODEL
    SYNOPTIC_PROVIDER = ANALYSIS_PROVIDER

# API-Keys (nur der aktive Provider muss gesetzt sein)
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
DEEPSEEK_API_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")

# Rueckwaertskompatibilitaet: OPENAI_MODEL (alter ENV-Name) ueberschreibt beide Defaults
_legacy_model = os.environ.get("OPENAI_MODEL", "").strip()
if _legacy_model:
    LLM_MODELS["openai"]["chat"] = _legacy_model
    LLM_MODELS["openai"]["analysis"] = _legacy_model


def get_api_key(provider: str) -> str:
    """Gibt den API-Key fuer einen Provider zurueck."""
    return {
        "openai":    OPENAI_API_KEY,
        "anthropic": ANTHROPIC_API_KEY,
        "gemini":    GEMINI_API_KEY,
        "deepseek":  DEEPSEEK_API_KEY,
    }.get(provider, "")


def get_model(provider: str, purpose: str) -> str:
    """purpose = 'chat' oder 'analysis'.

    Top-Level-Attribute (z.B. OPENAI_CHAT_MODEL) haben Vorrang vor LLM_MODELS,
    damit Admin-UI-Overrides via setattr(config, ...) sofort greifen.
    """
    attr = f"{provider.upper()}_{purpose.upper()}_MODEL"
    val = globals().get(attr)
    if val:
        return val
    return LLM_MODELS.get(provider, {}).get(purpose, "")


# ============================================================================
# LLM-ANALYSE-KONFIGURATION
# ============================================================================

# OPENAI_ANALYSIS_MODE — gilt AUSSCHLIESSLICH wenn ANALYSIS_PROVIDER=openai.
# "parallel" = schnell (viele gleichzeitige Calls), "batch" = guenstig
# (OpenAI Batch API, 50% billiger, dauert 5-30 Min).
#
# Anthropic, Gemini und DeepSeek haben KEINE Batch-API → bei diesen Providern
# wird der Wert zur Laufzeit ignoriert und immer parallel ausgefuehrt
# (Auto-Fallback unten + Dispatcher in engine/analyzers.py).
#
# Wird ueblicherweise via Admin-UI gesetzt (data/config_overrides.json), nicht ENV.
OPENAI_ANALYSIS_MODE = os.environ.get(
    "OPENAI_ANALYSIS_MODE",
    # Backwards-Compat: alter ENV-Name LLM_ANALYSIS_MODE als Fallback
    os.environ.get("LLM_ANALYSIS_MODE", "parallel"),
)
if OPENAI_ANALYSIS_MODE == "batch" and ANALYSIS_PROVIDER != "openai":
    logging.getLogger(__name__).warning(
        "OPENAI_ANALYSIS_MODE=batch greift nur mit ANALYSIS_PROVIDER=openai "
        "(aktuell: '%s'). Wird zur Laufzeit ignoriert → parallel.",
        ANALYSIS_PROVIDER,
    )
    OPENAI_ANALYSIS_MODE = "parallel"

# DEEPSEEK_DISABLE_THINKING — schaltet den Thinking-Modus fuer die Massen-Analyse
# (Spot-/Region-Calls in engine/analyzers.py) ab. Gilt nur fuer DeepSeek-V4-Modelle,
# die Thinking per Default an haben.
#
# Begruendung (A/B-Test 27.07.2026, 81 Spot-Tage, Details in cost_testing/doku.md):
# thinking vs non-thinking = 91.4% identische safety_status, 0 gefaehrliche Flips
# (not_safe -> fliegbar). Die Jitter-Baseline (2x non-thinking) liegt bei 95.1% —
# die Mode-Differenz ist also vom normalen Sampling-Rauschen nicht unterscheidbar.
# Dafuer: ~785 statt ~2750 Output-Tokens/Call, 3.9x schneller, ~36% guenstiger.
# Auf "0" setzen, um Thinking wieder einzuschalten (z.B. fuer Vergleichslaeufe).
DEEPSEEK_DISABLE_THINKING = os.environ.get("DEEPSEEK_DISABLE_THINKING", "1") == "1"

# SYNOPTIC_THINKING — Thinking-Modus fuer den Wetterlage-Call (1x/Tag,
# engine/synoptic_llm.py). Eigener Schalter, weil der Call NICHT an
# DEEPSEEK_DISABLE_THINKING haengt (das gilt nur fuer die Massen-Analyse).
#
# Default AUS (Messung 01.08.2026, echter Prod-Call gegen synoptic_context):
#   - thinking AN:  message.content in 8/8 Laeufen LEER (Antwort landet in
#     message.reasoning_content, finish_reason=stop) -> Scheduler-Ausfall
#     06:22 am 01.08.; 1/8 Laeufe lief ins Endlos-Reasoning (12k Tokens,
#     gar keine Antwort). Treiber ist die Ausgabemenge (4 Zonen x 3 Tage),
#     nicht die Prompt-Groesse: reduziert auf 1 Zone/1 Tag fuellt content.
#   - thinking AUS: content gefuellt 3/3, valides JSON, ~810-910 out_tok.
#   - Qualitaets-A/B (3 Laeufe je Modus, _validate()-Treffer): AN = 6/1/0,
#     AUS = 1/0/1 — kein Qualitaetsvorteil durch Reasoning; plausibel, weil
#     der Payload nur fertig klassifizierte Felder enthaelt, keine Rohzahlen.
# Auf "1" setzen, um Thinking wieder zu aktivieren (erst sinnvoll, wenn der
# Payload Rohdaten/Zeitachse enthaelt — siehe docs/pläne). Der
# reasoning_content-Fallback in synoptic_llm._call_llm() faengt den
# Leer-content-Fall dann ab.
SYNOPTIC_THINKING = os.environ.get("SYNOPTIC_THINKING", "0") == "1"

# Anzahl paralleler LLM-Calls im "parallel"-Modus.
# OpenAI gpt-4o-mini erlaubt bis 500 RPM (Tier 1). Default 10 ist konservativ.
# Hoeher = schneller, aber mehr Quota-Verbrauch pro Sekunde.
LLM_MAX_WORKERS = int(os.environ.get("LLM_MAX_WORKERS", "20"))

# Poll-Intervall (Sekunden) im "batch"-Modus, wie oft der Batch-Status geprüft wird.
LLM_BATCH_POLL_INTERVAL = int(os.environ.get("LLM_BATCH_POLL_INTERVAL", "30"))

# Stall-Timeout (Sekunden): Wenn ein OpenAI-Batch so lange ohne Progress
# (completed-Counter unverändert) bleibt, wird er gecancelt und der Daily-Run
# fällt einmalig auf Parallel-Modus zurück. Default 60 min.
LLM_BATCH_STALL_TIMEOUT_S = int(os.environ.get("LLM_BATCH_STALL_TIMEOUT_S", "3600"))


# ============================================================================
# LLM-Kosten-Telemetrie
# Preise in USD pro 1 Mio Tokens. Schluessel: Modell-ID.
# - in / out          : Standard-Tarif (parallel/sync)
# - in_batch / out_batch : OpenAI Batch-API (50% Rabatt)
# - cached_in         : Anthropic Prompt-Cache-Hit (10%) bzw. OpenAI auto-cache (50%)
# Stand: 2026-04. Bei Preisaenderung hier zentral pflegen.
# ============================================================================
MODEL_PRICES = {
    "gpt-4o-mini":      {"in": 0.150, "out": 0.600, "cached_in": 0.075, "in_batch": 0.075, "out_batch": 0.300},
    "gpt-4o":           {"in": 2.500, "out": 10.000, "cached_in": 1.250, "in_batch": 1.250, "out_batch": 5.000},
    "gpt-4.1-mini":     {"in": 0.400, "out": 1.600, "cached_in": 0.100, "in_batch": 0.200, "out_batch": 0.800},
    "claude-haiku-4-5": {"in": 1.000, "out": 5.000, "cached_in": 0.100, "in_batch": 0.500, "out_batch": 2.500},
    "claude-sonnet-4-6":{"in": 3.000, "out": 15.000, "cached_in": 0.300, "in_batch": 1.500, "out_batch": 7.500},
    "gemini-2.5-flash": {"in": 0.300, "out": 2.500, "cached_in": 0.075, "in_batch": 0.150, "out_batch": 1.250},
    "gemini-2.5-flash-lite": {"in": 0.100, "out": 0.400, "cached_in": 0.025, "in_batch": 0.050, "out_batch": 0.200},
    # DeepSeek: keine Batch-API (in_batch/out_batch == in/out). Cache-Hit-Rabatt automatisch (kein Opt-in).
    # DeepSeek V4 (Apr 2026): 1M-Kontext, MoE, optional Thinking-Mode.
    # Gegen https://api-docs.deepseek.com/quick_start/pricing verifiziert 2026-07-27.
    "deepseek-v4-flash": {"in": 0.140, "out": 0.280, "cached_in": 0.0028, "in_batch": 0.140, "out_batch": 0.280},
    "deepseek-v4-pro":   {"in": 0.435, "out": 0.870, "cached_in": 0.003625, "in_batch": 0.435, "out_batch": 0.870},
    # HISTORISCH — deepseek-chat/-reasoner waren ab ~24.04.2026 nur Aliase auf
    # v4-flash und wurden am 24.07.2026 abgeschaltet. Zeilen bleiben nur stehen,
    # damit alte cost_telemetry-Eintraege noch ein Preisschema finden. Nicht mehr
    # als aktive Modelle waehlbar. Achtung: est_usd-Werte vor 25.07.2026 sind mit
    # diesen (veralteten) Preisen gerechnet und fuer Aera-Vergleiche unbrauchbar.
    "deepseek-chat":     {"in": 0.270, "out": 1.100, "cached_in": 0.070, "in_batch": 0.270, "out_batch": 1.100},
    "deepseek-reasoner": {"in": 0.550, "out": 2.190, "cached_in": 0.140, "in_batch": 0.550, "out_batch": 2.190},
}

# Pfad fuer JSONL-Telemetrie (eine Zeile pro Analyse-Lauf).
import pathlib as _pathlib
COST_TELEMETRY_PATH = _pathlib.Path(os.environ.get(
    "COST_TELEMETRY_PATH",
    str(_pathlib.Path(__file__).parent / "data" / "cost_telemetry.jsonl"),
))


def atomic_write_json(path, data, indent=2, ensure_ascii=False):
    """Schreibt JSON atomar via temp-file + os.replace().
    Verhindert Corruption wenn ein paralleler Reader waehrend des Writes liest.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Async-Write-Queue fuer grosse JSON-Dateien (z.B. wetterdaten.json, 196 MB).
# Entkoppelt den 3-5s File-IO vom Aufrufer. Caveat: Der Daten-Dict darf NACH
# queue_atomic_write_json() nicht mehr mutiert werden (keine Defensivkopie
# wegen Speicherdruck bei 196 MB). Nutzer ist fuer Immutability verantwortlich.
# ---------------------------------------------------------------------------
_write_queue = None
_write_worker = None
_write_worker_lock = threading.Lock()
_write_logger = logging.getLogger(__name__ + ".async_write")


def _writer_loop():
    while True:
        job = _write_queue.get()
        try:
            if job is None:
                return
            path, data, indent, ensure_ascii = job
            try:
                atomic_write_json(path, data, indent=indent, ensure_ascii=ensure_ascii)
            except Exception as e:
                _write_logger.error("Async-Write fehlgeschlagen (%s): %s", path, e)
        finally:
            _write_queue.task_done()


def _ensure_async_writer():
    global _write_queue, _write_worker
    with _write_worker_lock:
        if _write_worker is not None:
            return
        _write_queue = queue.Queue()
        _write_worker = threading.Thread(
            target=_writer_loop, daemon=True, name="atomic-writer"
        )
        _write_worker.start()
        atexit.register(_flush_async_writer)


def _flush_async_writer(timeout: float = 30.0):
    """Wartet bis zu timeout Sekunden auf Abschluss aller pending Writes."""
    if _write_queue is None:
        return
    # queue.join() hat kein Timeout → Workaround ueber Polling
    import time as _time
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        if _write_queue.unfinished_tasks == 0:
            return
        _time.sleep(0.1)
    _write_logger.warning(
        "Async-Write Flush-Timeout nach %ss — %d Jobs ausstehend",
        timeout, _write_queue.unfinished_tasks,
    )


def queue_atomic_write_json(path, data, indent=2, ensure_ascii=False):
    """Non-blocking: Reiht einen atomaren JSON-Write in die Hintergrund-Queue ein.

    WICHTIG: `data` darf nach diesem Aufruf NICHT mehr mutiert werden (keine Kopie).
    Bei Crash zwischen Enqueue und Flush geht der Write verloren — OK fuer
    re-fetchbare Daten wie wetterdaten.json, NICHT fuer LLM-Analysen.
    """
    _ensure_async_writer()
    _write_queue.put((path, data, indent, ensure_ascii))