"""
Stationsdaten-basierte Bias-Korrektur für Böen-Vorhersagen.

Sammelt Echtzeit-Messungen von winds.mobi Stationen, vergleicht sie mit
ICON-D2 Modelldaten und berechnet einen Korrektur-Bias pro Spot.

Datenfluss:
1. discover_stations() — Nächste Stationen pro Spot finden (einmalig)
2. collect_observations() — Aktuelle Messwerte holen (bei jedem Refresh)
3. create_pairs() — Forecast vs. Beobachtung vergleichen
4. get_bias() / apply_bias_correction() — Korrektur anwenden

Persistenz: SQLite (data/station_observations.db)
"""

import sqlite3
import logging
import math
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

import config

# Shapely fuer Point-in-Polygon Test (Region-Bias)
try:
    from shapely.geometry import Point as _ShapelyPoint
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False

logger = logging.getLogger(__name__)

# winds.mobi API Timeout
_API_TIMEOUT = 15


def _elevation_correct_gust(station_gust, station_avg, station_alt, spot_alt,
                            forecast_gust=None, H_g=None):
    """
    Korrigiert eine Station-Böe auf die Spot-Höhe.

    Physik: Eine Böe besteht aus zwei Komponenten:
      1. Grundwind — vom Druckgradient + Terrain-Beschleunigung (Speed-Up).
         Auf Gipfeln DEUTLICH höher als im Tal/am Hang (Brasseur 2001).
      2. Turbulenz-Exzess — der Anteil über dem Grundwind, verursacht durch
         mechanische Turbulenz. Nimmt mit Höhendifferenz exponentiell ab.

    Formel (station höher als spot):
        adjusted = forecast_gust + excess × exp(-dz / H_g)

    Nur der Turbulenz-Exzess wird höhenkorrigiert auf den Modell-Forecast
    aufgeschlagen. Der Gipfel-Grundwind wird NICHT als Basis verwendet,
    da er durch terrain-spezifischen Speed-Up (Bernoulli-Effekt) am Gipfel
    systematisch höher ist als am Startplatz.

    Wenn die Station tiefer liegt → Station-Böe direkt (konservativ, da
    der Spot exponierter ist und die Böen mindestens so stark sind).

    Args:
        station_gust: Gemessene Böe an der Station (km/h)
        station_avg: Gemessener Mittelwind an der Station (km/h), kann None sein
        station_alt: Stationshöhe (m MSL)
        spot_alt: Spothöhe (m MSL)
        forecast_gust: Modell-Forecast-Böe am Spot (km/h), als Basis für Korrektur
        H_g: Skalenhöhe für Decay (m), default aus config

    Returns:
        Korrigierte Böe (km/h)
    """
    if H_g is None:
        H_g = config.BIAS_ELEV_DECAY_HG

    dz = station_alt - spot_alt  # positiv = Station höher als Spot

    if dz <= 0:
        # Station liegt gleich hoch oder tiefer → keine Reduktion
        return station_gust

    # Turbulenz-Exzess: Anteil über dem Grundwind, wird höhengedämpft
    avg = station_avg if station_avg is not None else 0.0
    excess = max(0.0, station_gust - avg)
    decay = math.exp(-dz / H_g)

    if forecast_gust is not None:
        # Modell-Forecast als Basis: nur Turbulenz-Exzess übertragen
        # Gipfel-Grundwind (station_avg) wird NICHT verwendet
        return forecast_gust + excess * decay
    else:
        # Fallback ohne Forecast (sollte nicht vorkommen)
        return avg + excess * decay


def _haversine_km(lat1, lon1, lat2, lon2):
    """Distanz zwischen zwei Koordinaten in km (Haversine-Formel)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class StationManager:
    # Kurzlebiger Bias-Cache gegen wiederholte SQLite-Reads im Refresh- und
    # /api/stations/status-Pfad (150+ Spots × mehrere Aufrufer).
    _BIAS_CACHE_TTL_SEC = 60

    def __init__(self, db_path, spots):
        """
        SQLite öffnen/erstellen, Schema anlegen falls nötig.

        Args:
            db_path: Pfad zur SQLite-Datei
            spots: Liste der Spot-Dicts (aus load_spots())
        """
        self.db_path = Path(db_path)
        self.spots = spots
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        # Bias-Cache: spot_name -> (bias_or_None, expiry_ts)
        self._bias_cache = {}
        self._bias_cache_lock = threading.Lock()

    def _init_db(self):
        """Schema erstellen falls nötig."""
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS stations (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    latitude REAL,
                    longitude REAL,
                    altitude REAL,
                    provider TEXT,
                    last_seen TEXT
                );

                CREATE TABLE IF NOT EXISTS spot_station_map (
                    spot_name TEXT,
                    station_id TEXT,
                    distance_km REAL,
                    elevation_diff_m REAL,
                    PRIMARY KEY (spot_name, station_id)
                );

                CREATE TABLE IF NOT EXISTS observations (
                    station_id TEXT,
                    timestamp TEXT,
                    wind_avg REAL,
                    wind_max REAL,
                    wind_direction REAL,
                    temperature REAL,
                    PRIMARY KEY (station_id, timestamp)
                );

                CREATE TABLE IF NOT EXISTS forecast_pairs (
                    spot_name TEXT,
                    timestamp TEXT,
                    station_id TEXT,
                    forecast_gust REAL,
                    observed_gust REAL,
                    model TEXT DEFAULT 'icon_d2',
                    PRIMARY KEY (spot_name, timestamp, station_id)
                );

                CREATE INDEX IF NOT EXISTS idx_obs_time
                    ON observations(station_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_pairs_spot
                    ON forecast_pairs(spot_name, timestamp);
            """)
            conn.commit()
        finally:
            conn.close()

    def _connect(self):
        """SQLite-Verbindung mit WAL-Modus."""
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ===================================================================
    # Station Discovery
    # ===================================================================

    def discover_stations(self):
        """
        Für jeden Spot: nächste Stationen von winds.mobi finden.
        Kriterien: max STATION_SEARCH_RADIUS_KM, max STATION_MAX_ELEV_DIFF_M.
        Speichert bis zu STATION_MAX_PER_SPOT Stationen pro Spot.
        """
        print("[STATIONS] Starte Station-Discovery...")

        # 1. Alle Stationen von winds.mobi holen
        all_stations = self._fetch_all_stations()
        if not all_stations:
            print("[STATIONS] Keine Stationen von winds.mobi erhalten")
            return 0

        print(f"[STATIONS] {len(all_stations)} Stationen von winds.mobi geladen")

        # 2. Stationen in DB speichern
        conn = self._connect()
        try:
            for s in all_stations:
                conn.execute("""
                    INSERT OR REPLACE INTO stations (id, name, latitude, longitude, altitude, provider, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    s["id"], s.get("name", ""), s.get("lat", 0), s.get("lon", 0),
                    s.get("alt", 0), s.get("provider", ""), datetime.now().isoformat()
                ))

            # 3. Pro Spot: nächste Stationen finden
            total_mappings = 0
            conn.execute("DELETE FROM spot_station_map")

            for spot in self.spots:
                candidates = []
                for s in all_stations:
                    dist = _haversine_km(
                        spot["latitude"], spot["longitude"],
                        s.get("lat", 0), s.get("lon", 0)
                    )
                    elev_diff = abs(spot["elevation_m"] - s.get("alt", 0))

                    if dist <= config.STATION_SEARCH_RADIUS_KM and elev_diff <= config.STATION_MAX_ELEV_DIFF_M:
                        candidates.append({
                            "station_id": s["id"],
                            "distance_km": dist,
                            "elevation_diff_m": elev_diff,
                        })

                # Sortieren: Nächste zuerst
                candidates.sort(key=lambda c: c["distance_km"])
                selected = candidates[:config.STATION_MAX_PER_SPOT]

                for c in selected:
                    conn.execute("""
                        INSERT OR REPLACE INTO spot_station_map
                            (spot_name, station_id, distance_km, elevation_diff_m)
                        VALUES (?, ?, ?, ?)
                    """, (spot["name"], c["station_id"], c["distance_km"], c["elevation_diff_m"]))
                    total_mappings += 1

                if selected:
                    names = [c["station_id"] for c in selected]
                    print(f"  {spot['name']}: {len(selected)} Stationen ({', '.join(names[:3])})")
                else:
                    print(f"  {spot['name']}: keine passende Station gefunden")

            conn.commit()
            print(f"[STATIONS] Discovery fertig: {total_mappings} Zuordnungen für {len(self.spots)} Spots")
            return total_mappings

        finally:
            conn.close()

    def _fetch_all_stations(self):
        """Holt alle Schweizer Stationen von winds.mobi."""
        try:
            url = f"{config.WINDS_MOBI_API}/stations/"
            # near-Filter um CH-Zentrum: 200km Radius fängt alle CH-Stationen
            params = {
                "near-lat": 46.8, "near-lon": 8.2, "near-distance": 200000,
                "limit": 2000,
            }
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # API gibt eine Liste von Dicts zurück
            if not isinstance(data, list):
                data = [data]

            # Schweizer Bounding Box filtern (API-Filter unzuverlässig)
            CH_LAT_MIN, CH_LAT_MAX = 45.8, 47.9
            CH_LON_MIN, CH_LON_MAX = 5.9, 10.5

            stations = []
            for s in data:
                loc = s.get("loc", {})
                coords = loc.get("coordinates", [0, 0])
                lon = coords[0] if len(coords) >= 2 else 0
                lat = coords[1] if len(coords) >= 2 else 0

                # Nur Schweizer Stationen
                if not (CH_LAT_MIN <= lat <= CH_LAT_MAX and CH_LON_MIN <= lon <= CH_LON_MAX):
                    continue

                stations.append({
                    "id": s.get("_id", ""),
                    "name": s.get("short", s.get("name", "")),
                    "lat": lat,
                    "lon": lon,
                    "alt": s.get("alt", 0),
                    "provider": s.get("pv-name", s.get("provider", "")),
                })
            return stations

        except Exception as e:
            logger.error(f"winds.mobi Stations-Abruf fehlgeschlagen: {e}")
            return []

    # ===================================================================
    # Observation Collection
    # ===================================================================

    def collect_observations(self):
        """
        Aktuelle Messwerte aller gemappten Stationen holen.
        Soft-fail bei API-Fehler.
        """
        conn = self._connect()
        try:
            # Alle gemappten Station-IDs holen
            rows = conn.execute(
                "SELECT DISTINCT station_id FROM spot_station_map"
            ).fetchall()
            station_ids = [r[0] for r in rows]

            if not station_ids:
                logger.info("[STATIONS] Keine gemappten Stationen — überspringe Collection")
                return 0

            collected = 0
            for sid in station_ids:
                try:
                    obs = self._fetch_station_current(sid)
                    if obs:
                        conn.execute("""
                            INSERT OR REPLACE INTO observations
                                (station_id, timestamp, wind_avg, wind_max, wind_direction, temperature)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (sid, obs["timestamp"], obs["wind_avg"], obs["wind_max"],
                              obs["wind_direction"], obs["temperature"]))
                        collected += 1
                except Exception as e:
                    logger.warning(f"Station {sid} Collection fehlgeschlagen: {e}")

                time.sleep(0.2)  # Rate-Limiting

            conn.commit()
            logger.info(f"[STATIONS] {collected}/{len(station_ids)} Stationen aktualisiert")
            return collected

        finally:
            conn.close()

    def _fetch_station_current(self, station_id):
        """Aktuelle Messwerte einer Station von winds.mobi holen."""
        try:
            url = f"{config.WINDS_MOBI_API}/stations/{station_id}/"
            resp = requests.get(url, timeout=_API_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            last = data.get("last", {})
            if not last:
                return None

            # Timestamp: Unix → ISO
            ts_unix = last.get("_id")
            if ts_unix is None:
                return None
            ts = datetime.fromtimestamp(ts_unix).replace(minute=0, second=0, microsecond=0)

            # winds.mobi liefert m/s → km/h
            wind_avg = last.get("w-avg", 0) * 3.6 if last.get("w-avg") is not None else None
            wind_max = last.get("w-max", 0) * 3.6 if last.get("w-max") is not None else None
            wind_dir = last.get("w-dir")
            temp = last.get("temp")

            return {
                "timestamp": ts.isoformat(),
                "wind_avg": round(wind_avg, 1) if wind_avg is not None else None,
                "wind_max": round(wind_max, 1) if wind_max is not None else None,
                "wind_direction": wind_dir,
                "temperature": temp,
            }
        except Exception as e:
            logger.warning(f"Abruf Station {station_id} fehlgeschlagen: {e}")
            return None

    def backfill_observations(self, days_back=14):
        """
        Historische Beobachtungen für alle gemappten Stationen nachholen.
        Nutzt winds.mobi Historic-Daten.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT station_id FROM spot_station_map"
            ).fetchall()
            station_ids = [r[0] for r in rows]

            if not station_ids:
                return 0

            total = 0
            for sid in station_ids:
                try:
                    count = self._backfill_station(conn, sid, days_back)
                    total += count
                except Exception as e:
                    logger.warning(f"Backfill Station {sid} fehlgeschlagen: {e}")
                time.sleep(0.3)

            conn.commit()
            print(f"[STATIONS] Backfill fertig: {total} historische Beobachtungen eingefügt")
            return total

        finally:
            conn.close()

    def _backfill_station(self, conn, station_id, days_back):
        """Historische Daten einer Station holen und einfügen."""
        try:
            url = f"{config.WINDS_MOBI_API}/stations/{station_id}/historic/"
            # winds.mobi erlaubt maximal 7 Tage pro Request
            duration_seconds = min(days_back, 7) * 86400
            params = {"duration": duration_seconds}
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            measures = resp.json()

            if not isinstance(measures, list) or not measures:
                return 0

            inserted = 0
            seen_hours = set()

            for m in measures:
                ts_unix = m.get("_id")
                if ts_unix is None:
                    continue
                ts = datetime.fromtimestamp(ts_unix)

                # Auf volle Stunde runden, nur eine Messung pro Stunde
                ts_rounded = ts.replace(minute=0, second=0, microsecond=0)
                hour_key = ts_rounded.isoformat()
                if hour_key in seen_hours:
                    continue
                seen_hours.add(hour_key)

                wind_avg = m.get("w-avg", 0) * 3.6 if m.get("w-avg") is not None else None
                wind_max = m.get("w-max", 0) * 3.6 if m.get("w-max") is not None else None

                conn.execute("""
                    INSERT OR IGNORE INTO observations
                        (station_id, timestamp, wind_avg, wind_max, wind_direction, temperature)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (station_id, hour_key,
                      round(wind_avg, 1) if wind_avg is not None else None,
                      round(wind_max, 1) if wind_max is not None else None,
                      m.get("w-dir"), m.get("temp")))
                inserted += 1

            return inserted

        except Exception as e:
            logger.warning(f"Backfill {station_id} fehlgeschlagen: {e}")
            return 0

    def backfill_pairs(self, weather_data, days_back=14):
        """
        Historische Forecast-Observation Paare erstellen.
        Holt ICON-D2 Modellwerte via Open-Meteo past_days und
        matched sie mit den historischen Stationsdaten.

        Höhenkorrektur: Station-Böen werden auf Spot-Höhe projiziert
        bevor sie als observed_gust gespeichert werden.
        """
        conn = self._connect()
        try:
            mappings = conn.execute("""
                SELECT spot_name, station_id FROM spot_station_map
            """).fetchall()

            if not mappings:
                return 0

            # Historische Modelldaten von Open-Meteo holen
            spot_coords = {s["name"]: (s["latitude"], s["longitude"]) for s in self.spots}
            spot_elev = {s["name"]: s["elevation_m"] for s in self.spots}
            unique_spots = list(set(m[0] for m in mappings if m[0] in spot_coords))

            if not unique_spots:
                return 0

            # Stationshöhen laden für Höhenkorrektur
            station_alts = {}
            for row in conn.execute("SELECT id, altitude FROM stations").fetchall():
                station_alts[row[0]] = row[1] or 0

            lats = [str(spot_coords[n][0]) for n in unique_spots]
            lons = [str(spot_coords[n][1]) for n in unique_spots]

            try:
                resp = requests.get(config.API_URL, params=config.with_api_key({
                    "latitude": ",".join(lats),
                    "longitude": ",".join(lons),
                    "hourly": "wind_gusts_10m,wind_speed_10m",
                    "models": config.WIND_MODEL,
                    "past_days": days_back,
                    "forecast_days": 1,
                    "timezone": config.TIMEZONE,
                }), timeout=30)
                resp.raise_for_status()
                batch = resp.json()
                if not isinstance(batch, list):
                    batch = [batch]
            except Exception as e:
                logger.error(f"Open-Meteo Past-Days Abruf fehlgeschlagen: {e}")
                return 0

            # Modellwerte pro Spot indexieren
            # Open-Meteo Timestamps normalisieren: "2026-03-30T16:00" → "2026-03-30T16:00:00"
            model_data = {}
            for i, spot_name in enumerate(unique_spots):
                if i < len(batch):
                    hourly = batch[i].get("hourly", {})
                    times = hourly.get("time", [])
                    gusts = hourly.get("wind_gusts_10m", [])
                    normalized = {}
                    for t, g in zip(times, gusts):
                        # Sicherstellen: ISO mit Sekunden
                        key = t + ":00" if len(t) == 16 else t
                        normalized[key] = g
                    model_data[spot_name] = normalized

            # Paare erstellen (mit Höhenkorrektur auf observed_gust)
            total_pairs = 0
            for spot_name, station_id in mappings:
                if spot_name not in model_data:
                    continue

                s_alt = station_alts.get(station_id, 0)
                sp_alt = spot_elev.get(spot_name, 0)

                obs_rows = conn.execute("""
                    SELECT timestamp, wind_max, wind_avg FROM observations
                    WHERE station_id = ? AND timestamp >= ?
                """, (station_id, (datetime.now() - timedelta(days=days_back)).isoformat())).fetchall()

                for obs_ts, obs_gust, obs_avg in obs_rows:
                    if obs_gust is None:
                        continue
                    forecast_gust = model_data[spot_name].get(obs_ts)
                    if forecast_gust is None:
                        continue

                    # Höhenkorrektur: Turbulenz-Exzess auf Modell-Forecast aufschlagen
                    adjusted_gust = _elevation_correct_gust(
                        obs_gust, obs_avg, s_alt, sp_alt,
                        forecast_gust=forecast_gust)

                    conn.execute("""
                        INSERT OR IGNORE INTO forecast_pairs
                            (spot_name, timestamp, station_id, forecast_gust, observed_gust, model)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (spot_name, obs_ts, station_id, forecast_gust,
                          round(adjusted_gust, 1), config.WIND_MODEL))
                    total_pairs += 1

            conn.commit()
            print(f"[STATIONS] Backfill-Paare: {total_pairs} Forecast-Observation Paare erstellt")
            if total_pairs:
                self._invalidate_bias_cache()
            return total_pairs

        finally:
            conn.close()

    # ===================================================================
    # Forecast-Observation Pairing
    # ===================================================================

    def create_pairs(self, weather_data):
        """
        Für jeden Spot: Aktuellen Forecast-Böenwert mit nächster
        Station-Beobachtung vergleichen und als Paar speichern.

        Höhenkorrektur: Station-Böen werden auf Spot-Höhe projiziert
        bevor sie als observed_gust gespeichert werden.
        """
        if not weather_data:
            return 0

        conn = self._connect()
        try:
            mappings = conn.execute("""
                SELECT spot_name, station_id FROM spot_station_map
            """).fetchall()

            if not mappings:
                return 0

            # Spot- und Stationshöhen laden
            spot_elev = {s["name"]: s["elevation_m"] for s in self.spots}
            station_alts = {}
            for row in conn.execute("SELECT id, altitude FROM stations").fetchall():
                station_alts[row[0]] = row[1] or 0

            # Aktuelle Stunde (für Matching)
            now = datetime.now().replace(minute=0, second=0, microsecond=0)
            # Weather-Daten nutzen Format ohne Sekunden: "2026-04-06T17:00"
            now_short = now.strftime("%Y-%m-%dT%H:%M")
            # Observations nutzen Format mit Sekunden: "2026-04-06T17:00:00"
            now_long = now.isoformat()

            total_pairs = 0
            for spot_name, station_id in mappings:
                spot_data = weather_data.get(spot_name)
                if not spot_data:
                    continue

                hourly = spot_data.get("hourly_data", {})
                forecast_entry = hourly.get(now_short) or hourly.get(now_long)
                if not forecast_entry:
                    continue

                forecast_gust = forecast_entry.get("wind_gusts_10m")
                if forecast_gust is None:
                    continue

                # Station-Beobachtung für diese Stunde (beide Timestamp-Formate)
                obs_row = conn.execute("""
                    SELECT wind_max, wind_avg FROM observations
                    WHERE station_id = ? AND (timestamp = ? OR timestamp = ?)
                """, (station_id, now_long, now_short)).fetchone()

                if obs_row is None or obs_row[0] is None:
                    continue

                observed_gust = obs_row[0]
                observed_avg = obs_row[1]

                # Höhenkorrektur: Turbulenz-Exzess auf Modell-Forecast aufschlagen
                s_alt = station_alts.get(station_id, 0)
                sp_alt = spot_elev.get(spot_name, 0)
                adjusted_gust = _elevation_correct_gust(
                    observed_gust, observed_avg, s_alt, sp_alt,
                    forecast_gust=forecast_gust)

                conn.execute("""
                    INSERT OR REPLACE INTO forecast_pairs
                        (spot_name, timestamp, station_id, forecast_gust, observed_gust, model)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (spot_name, now_long, station_id, forecast_gust,
                      round(adjusted_gust, 1), config.WIND_MODEL))
                total_pairs += 1

            conn.commit()
            logger.info(f"[STATIONS] {total_pairs} neue Forecast-Observation Paare erstellt")
            if total_pairs:
                self._invalidate_bias_cache()
            return total_pairs

        finally:
            conn.close()

    # ===================================================================
    # Bias-Berechnung
    # ===================================================================

    def _invalidate_bias_cache(self):
        """Leert den Bias-Cache (nach forecast_pairs-Writes)."""
        with self._bias_cache_lock:
            self._bias_cache.clear()

    def get_bias(self, spot_name, lookback_days=None):
        """
        Exponentiell gewichteter Durchschnitt der Forecast-Fehler.

        Returns: float (km/h, positiv = Modell unterschätzt) oder None wenn <BIAS_MIN_PAIRS Paare.
        Nutzt Cache fuer Default-lookback (TTL _BIAS_CACHE_TTL_SEC).
        """
        if lookback_days is None:
            lookback_days = config.BIAS_LOOKBACK_DAYS

        use_cache = lookback_days == config.BIAS_LOOKBACK_DAYS
        if use_cache:
            with self._bias_cache_lock:
                hit = self._bias_cache.get(spot_name)
                if hit is not None:
                    value, expiry = hit
                    if time.time() < expiry:
                        return value
                    del self._bias_cache[spot_name]

        result = self._compute_bias(spot_name, lookback_days)

        if use_cache:
            with self._bias_cache_lock:
                self._bias_cache[spot_name] = (result, time.time() + self._BIAS_CACHE_TTL_SEC)
        return result

    def _compute_bias(self, spot_name, lookback_days):
        """Rechnet Bias ungecached aus SQLite."""
        conn = self._connect()
        try:
            cutoff = (datetime.now() - timedelta(days=lookback_days)).isoformat()
            rows = conn.execute("""
                SELECT timestamp, forecast_gust, observed_gust
                FROM forecast_pairs
                WHERE spot_name = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (spot_name, cutoff)).fetchall()

            if len(rows) < config.BIAS_MIN_PAIRS:
                return None

            # Exponentiell gewichteter Durchschnitt
            alpha = config.BIAS_ALPHA
            weight_sum = 0.0
            error_sum = 0.0
            n = len(rows)

            for i, (ts, fc, obs) in enumerate(rows):
                if fc is None or obs is None:
                    continue
                error = obs - fc  # positiv = Modell unterschätzt
                # Jüngere Paare stärker gewichten
                weight = alpha ** (n - 1 - i)
                weight_sum += weight
                error_sum += weight * error

            if weight_sum == 0:
                return None

            bias = error_sum / weight_sum
            return round(bias, 1)
        finally:
            conn.close()

    def apply_bias_correction(self, weather_data):
        """
        Korrigiert wind_gusts_10m für alle Spots in-place.
        Greift nur ein wenn genug Paare vorhanden.

        Bias wird auf ±BIAS_MAX_CORRECTION km/h begrenzt (Sicherheitslimit).
        Deaktivierbar via config.BIAS_CORRECTION_ENABLED.
        """
        if not config.BIAS_CORRECTION_ENABLED:
            logger.info("[STATIONS] Bias-Korrektur deaktiviert (BIAS_CORRECTION_ENABLED=False)")
            return 0
        max_corr = config.BIAS_MAX_CORRECTION
        corrected_count = 0
        for spot in self.spots:
            name = spot["name"]
            bias = self.get_bias(name)
            if bias is None:
                continue

            # Bias cappen: ±max_corr km/h
            capped_bias = max(-max_corr, min(max_corr, bias))
            if abs(capped_bias) < 0.5:
                # Zu klein um anzuwenden
                continue

            spot_data = weather_data.get(name)
            if not spot_data:
                continue

            hourly = spot_data.get("hourly_data", {})
            for ts, entry in hourly.items():
                gust = entry.get("wind_gusts_10m")
                if gust is not None:
                    # Bias addieren (positiv = Modell unterschätzt → erhöhen)
                    corrected = max(0, gust + capped_bias)
                    entry["wind_gusts_10m_raw"] = gust  # Original aufbewahren
                    entry["wind_gusts_10m"] = round(corrected, 1)
                    entry["wind_gust_bias"] = capped_bias

            corrected_count += 1
            cap_info = " [CAPPED]" if abs(bias) > max_corr else ""
            logger.info(f"  Bias-Korrektur {name}: {capped_bias:+.1f} km/h (raw: {bias:+.1f}){cap_info}")

        if corrected_count:
            print(f"[STATIONS] Bias-Korrektur auf {corrected_count} Spots angewendet")
        return corrected_count

    def apply_bias_correction_to_regions(self, region_weather_data, regions_with_polygons):
        """
        Wendet die Bias-Korrektur auch auf Regionen an.
        Deaktivierbar via config.BIAS_CORRECTION_ENABLED.

        WICHTIG: Der Region-Bias wird ausschliesslich aus Spots berechnet, die
        - geografisch INNERHALB des Region-Polygons liegen (Point-in-Polygon) UND
        - hoehenmaessig nahe am elev_ref der Region (|dz| <= 600 m).

        Der Hoehenfilter verhindert, dass exponierte Gipfelspots (Pilatus 2059m)
        die Bias-Berechnung fuer ein mittelhohes Voralpengebiet (elev_ref 1400m)
        verfaelschen. Bias-Werte sind ortsspezifisch und skalieren nicht 1:1
        auf Regionen mit anderer Exposition/Hoehe.

        Aggregation: Median der Spot-Biase (robust gegen Ausreisser).
        Mindestens 2 Spots (nach Filter) mit gueltigem Bias sind noetig.

        Args:
            region_weather_data: Dict {region_id: {hourly_data: {...}, "elevation_ref": X}}
            regions_with_polygons: Liste von Dicts mit "id", "polygon", "elevation_ref".
        """
        if not config.BIAS_CORRECTION_ENABLED:
            logger.info("[STATIONS] Region-Bias-Korrektur deaktiviert (BIAS_CORRECTION_ENABLED=False)")
            return 0
        if not _HAS_SHAPELY:
            logger.warning("[STATIONS] shapely fehlt — Region-Bias uebersprungen")
            return 0
        if not region_weather_data or not regions_with_polygons:
            return 0

        max_corr = config.BIAS_MAX_CORRECTION
        elev_filter_m = 600  # Max. Hoehendifferenz Spot <-> Region elev_ref
        corrected_count = 0

        for region in regions_with_polygons:
            rid = region.get("id")
            polygon = region.get("polygon")
            if not rid or polygon is None:
                continue
            if rid not in region_weather_data:
                continue

            # Region elev_ref: erst aus polygon-Objekt, dann aus weather_data
            region_elev_ref = region.get("elevation_ref")
            if region_elev_ref is None:
                region_elev_ref = region_weather_data[rid].get("elevation_ref", 1000)

            # Spots im Polygon sammeln (mit Hoehenfilter)
            inside_biases = []
            inside_names = []
            skipped_by_elev = 0
            for spot in self.spots:
                try:
                    pt = _ShapelyPoint(spot["longitude"], spot["latitude"])
                except Exception:
                    continue
                if not polygon.contains(pt):
                    continue
                # Hoehenfilter: nur Spots nahe am Region-Elevation-Ref
                spot_elev = spot.get("elevation_m", 0)
                if abs(spot_elev - region_elev_ref) > elev_filter_m:
                    skipped_by_elev += 1
                    continue
                bias = self.get_bias(spot["name"])
                if bias is not None:
                    inside_biases.append(bias)
                    inside_names.append(spot["name"])

            if len(inside_biases) < 2:
                if skipped_by_elev > 0:
                    logger.info(
                        f"  Region-Bias {rid}: uebersprungen "
                        f"(nur {len(inside_biases)} Spots im Hoehenfilter, "
                        f"{skipped_by_elev} durch Hoehe ausgeschlossen)"
                    )
                continue

            # Median der Biase (robust gegen einzelne Ausreisser)
            sorted_biases = sorted(inside_biases)
            n = len(sorted_biases)
            if n % 2:
                region_bias = sorted_biases[n // 2]
            else:
                region_bias = (sorted_biases[n // 2 - 1] + sorted_biases[n // 2]) / 2

            # Gleiche Sicherheits-Policy wie bei Spots
            capped = max(-max_corr, min(max_corr, region_bias))
            if abs(capped) < 0.5:
                continue

            # Auf alle Stundenwerte der Region anwenden
            region_entry = region_weather_data.get(rid, {})
            hourly = region_entry.get("hourly_data", {})
            for ts, entry in hourly.items():
                gust = entry.get("wind_gusts_10m")
                if gust is not None:
                    corrected = max(0, gust + capped)
                    entry["wind_gusts_10m_raw"] = gust
                    entry["wind_gusts_10m"] = round(corrected, 1)
                    entry["wind_gust_bias"] = capped

            corrected_count += 1
            cap_info = " [CAPPED]" if abs(region_bias) > max_corr else ""
            logger.info(
                f"  Region-Bias {rid}: {capped:+.1f} km/h "
                f"(raw: {region_bias:+.1f}, {n} Spots: {', '.join(inside_names[:5])}"
                f"{'...' if n > 5 else ''}){cap_info}"
            )

        if corrected_count:
            print(f"[STATIONS] Region-Bias auf {corrected_count} Regionen angewendet")
        return corrected_count

    # ===================================================================
    # Status / Debug
    # ===================================================================

    def get_status(self):
        """
        Status-Übersicht: Stationen pro Spot, letzte Sammlung,
        Anzahl Paare, aktueller Bias pro Spot.
        """
        conn = self._connect()
        try:
            # Stationen total
            station_count = conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0]

            # Mappings pro Spot
            spot_mappings = {}
            rows = conn.execute("""
                SELECT ssm.spot_name, ssm.station_id, ssm.distance_km, s.name
                FROM spot_station_map ssm
                LEFT JOIN stations s ON ssm.station_id = s.id
                ORDER BY ssm.spot_name, ssm.distance_km
            """).fetchall()
            for spot_name, sid, dist, sname in rows:
                if spot_name not in spot_mappings:
                    spot_mappings[spot_name] = []
                spot_mappings[spot_name].append({
                    "station_id": sid,
                    "station_name": sname,
                    "distance_km": round(dist, 1),
                })

            # Letzte Beobachtung
            last_obs = conn.execute(
                "SELECT MAX(timestamp) FROM observations"
            ).fetchone()[0]

            # Paare total
            pair_count = conn.execute("SELECT COUNT(*) FROM forecast_pairs").fetchone()[0]

            # Bias pro Spot
            bias_per_spot = {}
            for spot in self.spots:
                bias = self.get_bias(spot["name"])
                if bias is not None:
                    bias_per_spot[spot["name"]] = bias

            # Observations total
            obs_count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

            return {
                "stations_total": station_count,
                "observations_total": obs_count,
                "pairs_total": pair_count,
                "last_observation": last_obs,
                "spots_with_bias": len(bias_per_spot),
                "bias_per_spot": bias_per_spot,
                "spot_mappings": spot_mappings,
            }

        finally:
            conn.close()

    def needs_discovery(self):
        """Prüft ob Station-Discovery nötig ist (leere spot_station_map)."""
        conn = self._connect()
        try:
            count = conn.execute("SELECT COUNT(*) FROM spot_station_map").fetchone()[0]
            return count == 0
        finally:
            conn.close()

    def needs_backfill(self):
        """Prüft ob Observation-Backfill nötig ist (keine oder alte Daten)."""
        conn = self._connect()
        try:
            last_obs = conn.execute(
                "SELECT MAX(timestamp) FROM observations"
            ).fetchone()[0]
            if last_obs is None:
                return True
            last_dt = datetime.fromisoformat(last_obs)
            gap = datetime.now() - last_dt
            return gap > timedelta(hours=6)
        finally:
            conn.close()

    def cleanup_old_data(self, keep_days=30):
        """Alte Beobachtungen und Paare aufräumen."""
        conn = self._connect()
        try:
            cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
            del_obs = conn.execute(
                "DELETE FROM observations WHERE timestamp < ?", (cutoff,)
            ).rowcount
            del_pairs = conn.execute(
                "DELETE FROM forecast_pairs WHERE timestamp < ?", (cutoff,)
            ).rowcount
            conn.commit()
            if del_obs or del_pairs:
                logger.info(f"[STATIONS] Cleanup: {del_obs} Beobachtungen, {del_pairs} Paare entfernt")
            if del_pairs:
                self._invalidate_bias_cache()
        finally:
            conn.close()
