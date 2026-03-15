import re

with open("fetch_weather.py", "r", encoding="utf-8") as f:
    code = f.read()

# ADD IMPORTS
if "from thermik_calculator" not in code:
    code = code.replace("import config", "import config\nfrom thermik_calculator import calculate_thermal_profile, calculate_dewpoint")

# REWRITE get_weather_for_location
new_func = """def get_weather_for_location(location_name, latitude, longitude):
    \"\"\"
    Ruft stündliche Wettervorhersage ab (Hybrid-Modell: ICON-CH1 + Seamless + GFS).
    Nutzt ein 3-Punkte-Raster für Bewölkung und wendet Smart Burn-Off an.
    Gibt (hourly_data, pressure_level_data, reference_points) zurück.
    \"\"\"
    pl_params = ",".join(config.PRESSURE_LEVEL_PARAMS)
    
    # 3-Punkte Raster für "homogene Regionen" Durchschnitt (Balderen-Sumpf Glättung)
    # ca. 1.5km Offset. Punkt 1: Original. Punkt 2: NO. Punkt 3: NW.
    ref_points = [
        [latitude, longitude],
        [latitude + 0.015, longitude + 0.020],
        [latitude - 0.015, longitude + 0.020]
    ]
    lat_str = ",".join(str(round(p[0], 4)) for p in ref_points)
    lon_str = ",".join(str(round(p[1], 4)) for p in ref_points)

    params_ch1 = {
        "latitude": lat_str,
        "longitude": lon_str,
        "models": config.API_MODEL,
        "hourly": ",".join(config.HOURLY_PARAMS) + "," + pl_params,
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.TIMEZONE,
    }

    params_seamless = {
        "latitude": lat_str,
        "longitude": lon_str,
        "models": "icon_seamless",
        "hourly": ",".join(config.HOURLY_PARAMS) + "," + pl_params,
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.TIMEZONE,
    }
    
    def _average_clouds(data_list):
        if not data_list or not isinstance(data_list, list): return data_list
        primary = data_list[0]
        if "hourly" not in primary: return primary
        
        for k in ["cloud_cover", "cloud_cover_low"]:
            if k not in primary["hourly"]: continue
            arrays = [d["hourly"].get(k, []) for d in data_list if "hourly" in d]
            if not arrays or not arrays[0]: continue
            
            avg_arr = []
            for i in range(len(arrays[0])):
                vals = [arr[i] for arr in arrays if i < len(arr) and arr[i] is not None]
                avg_arr.append(round(sum(vals)/len(vals)) if vals else None)
            primary["hourly"][k] = avg_arr
        return primary

    try:
        data_ch1 = None
        try:
            print(f"  [INFO] {config.API_MODEL} (3-Punkte) für {location_name}...")
            resp_ch1 = requests.get(config.API_URL, params=params_ch1, timeout=config.API_TIMEOUT)
            resp_ch1.raise_for_status()
            res_json = resp_ch1.json()
            data_ch1_list = res_json if isinstance(res_json, list) else [res_json]
            data_ch1 = _average_clouds(data_ch1_list)
        except requests.exceptions.RequestException as e:
            print(f"  [WARN] {config.API_MODEL} fehlgeschlagen: {e}")

        print(f"  [INFO] Seamless (3-Punkte) für {location_name}...")
        resp_sl = requests.get(config.API_URL, params=params_seamless, timeout=config.API_TIMEOUT)
        resp_sl.raise_for_status()
        res_json = resp_sl.json()
        data_sl_list = res_json if isinstance(res_json, list) else [res_json]
        data_sl = _average_clouds(data_sl_list)

        hourly_ch1 = data_ch1.get("hourly", {}) if data_ch1 else {}
        hourly_sl = data_sl.get("hourly", {})

        times_sl = hourly_sl.get("time", [])
        if not times_sl:
            print(f"  [WARN] Keine Seamless Daten für {location_name}")
            return None, None, ref_points

        hourly_data = {}
        pressure_level_data = {}

        for i, time_str in enumerate(times_sl):
            entry = {}
            for param in config.HOURLY_PARAMS:
                val = hourly_sl.get(param, [None])[i] if i < len(hourly_sl.get(param, [])) else None
                entry[param] = val
            hourly_data[time_str] = entry

            pl_entry = {}
            for param in config.PRESSURE_LEVEL_PARAMS:
                val = hourly_sl.get(param, [None])[i] if i < len(hourly_sl.get(param, [])) else None
                pl_entry[param] = val
            pressure_level_data[time_str] = pl_entry

        times_ch1 = hourly_ch1.get("time", []) if hourly_ch1 else []
        for i, time_str in enumerate(times_ch1):
            if time_str not in hourly_data: continue
            for param in config.HOURLY_PARAMS:
                val_ch1 = hourly_ch1.get(param, [None])[i] if i < len(hourly_ch1.get(param, [])) else None
                if val_ch1 is not None:
                    hourly_data[time_str][param] = val_ch1
            if time_str in pressure_level_data:
                for param in config.PRESSURE_LEVEL_PARAMS:
                    val_ch1 = hourly_ch1.get(param, [None])[i] if i < len(hourly_ch1.get(param, [])) else None
                    if val_ch1 is not None:
                        pressure_level_data[time_str][param] = val_ch1

        for time_str in hourly_data:
            cb = hourly_data[time_str].get("cloud_base")
            if cb is not None and cb > 6000:
                hourly_data[time_str]["cloud_base"] = None

        try:
            params_gfs = {
                "latitude": latitude,
                "longitude": longitude,
                "hourly": ",".join(config.GFS_SUPPLEMENTARY_PARAMS),
                "models": "gfs_seamless",
                "forecast_days": config.FORECAST_DAYS,
                "timezone": config.TIMEZONE,
            }
            resp_gfs = requests.get(config.API_URL, params=params_gfs, timeout=10)
            resp_gfs.raise_for_status()
            hourly_gfs = resp_gfs.json().get("hourly", {})
            gfs_times = hourly_gfs.get("time", [])
            filled = 0
            for i, ts in enumerate(gfs_times):
                if ts in hourly_data:
                    for p in config.GFS_SUPPLEMENTARY_PARAMS:
                        if hourly_data[ts].get(p) is None:
                            val = hourly_gfs.get(p, [None])[i] if i < len(hourly_gfs.get(p, [])) else None
                            if val is not None:
                                hourly_data[ts][p] = val
                                filled += 1
            print(f"  [INFO] GFS-Supplement: {filled} Werte aufgefüllt")
        except Exception as e:
            print(f"  [WARN] GFS-Supplement fehlgeschlagen: {e}")

        burn_off_count = 0
        elevation = data_sl.get("elevation", 0)
        for ts, data in hourly_data.items():
            temp = data.get("temperature_2m")
            rh = data.get("relative_humidity_2m", 50)
            radiation = data.get("direct_radiation")
            bl_height = data.get("boundary_layer_height", 0)
            
            if temp is not None and radiation is not None and radiation > 50:
                dewpoint = calculate_dewpoint(temp, rh)
                profile = calculate_thermal_profile(
                    T_s=temp, Td_s=dewpoint, p_s=1013,
                    pl_data=pressure_level_data.get(ts, {}),
                    elevation=elevation,
                    time_str=ts
                )
                climb_rate = profile.get("climb_rate", 0)
                
                # INVERSIONSBRUCH BURN OFF
                if climb_rate >= 1.0 and bl_height is not None and bl_height > 1000:
                    raw_low = data.get("cloud_cover_low", 0)
                    if raw_low > 15:
                        burn_factor = min(1.0, (climb_rate - 1.0) / 1.5)
                        removed_clouds = raw_low * burn_factor
                        data["cloud_cover_low"] = max(0, int(raw_low - removed_clouds))
                        
                        raw_tot = data.get("cloud_cover", 0)
                        data["cloud_cover"] = max(0, int(raw_tot - removed_clouds))
                        burn_off_count += 1
                        
        if burn_off_count > 0:
            print(f"  [INFO] Smart Burn-Off angewendet an {burn_off_count} Stunden (Ghost-Clouds entfernt).")

        print(f"  [INFO] {len(hourly_data)} Zeitstempel für {location_name}")
        return hourly_data, pressure_level_data, ref_points

    except requests.exceptions.RequestException as e:
        print(f"  [FEHLER] API-Fehler für {location_name}: {e}")
        return None, None, ref_points
    except Exception as e:
        import traceback
        print(f"  [FEHLER] Unerwarteter Fehler für {location_name}: {e}")
        traceback.print_exc()
        return None, None, ref_points"""

start_idx = code.find("def get_weather_for_location")
end_idx = code.find("def fetch_all_spots")
if start_idx != -1 and end_idx != -1:
    code = code[:start_idx] + new_func + "\n\n\n" + code[end_idx:]

code = code.replace("hourly_data, pressure_level_data = result", "hourly_data, pressure_level_data, ref_points = result")
code = code.replace('"pressure_level_data": pressure_level_data,', '"pressure_level_data": pressure_level_data,\n            "reference_points": ref_points,')

with open("fetch_weather.py", "w", encoding="utf-8") as f:
    f.write(code)

print("SUCCESS: fetch_weather.py updated.")
