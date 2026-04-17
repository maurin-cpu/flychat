import json
import argparse
import os
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description="Inspect weather data from wetterdaten.json")
    parser.add_argument("--spot", type=str, help="Name of the spot to inspect")
    parser.add_argument("--date", type=str, help="Date to inspect (YYYY-MM-DD)")
    parser.add_argument("--type", type=str, choices=["wind", "cloud", "thermal", "radiation", "all"], default="all", help="Type of data to display")
    parser.add_argument("--list-spots", action="store_true", help="List all available spots")
    parser.add_argument("--file", type=str, default="data/wetterdaten.json", help="Path to the weather JSON file")

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}")
        return

    with open(args.file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if args.list_spots:
        spots = [k for k in data.keys() if k != "_meta"]
        print("Available spots:")
        for s in sorted(spots):
            print(f"  - {s}")
        return

    if not args.spot:
        print("Error: Please specify a spot using --spot or use --list-spots")
        return

    if args.spot not in data:
        print(f"Error: Spot '{args.spot}' not found in data.")
        return

    spot_data = data[args.spot]
    hourly = spot_data.get("hourly_data", {})
    
    if not hourly:
        print(f"No hourly data found for {args.spot}.")
        return

    print(f"\n=== Inspection: {args.spot} ===")
    if "_meta" in data:
        print(f"Last updated: {data['_meta'].get('last_updated', 'unknown')}")
    
    sorted_times = sorted(hourly.keys())
    
    for ts in sorted_times:
        if args.date and not ts.startswith(args.date):
            continue
        
        h = hourly[ts]
        time_part = ts.split("T")[1][:5]
        
        output = [f"{time_part}"]
        
        if args.type in ["wind", "all"]:
            ws = h.get("wind_speed_10m", "N/A")
            wg = h.get("wind_gusts_10m", "N/A")
            wd = h.get("wind_direction_10m", "N/A")
            output.append(f"Wind: {ws} / {wg} km/h ({wd}°)")
            
        if args.type in ["cloud", "all"]:
            c = h.get("cloud_cover", "N/A")
            cl = h.get("cloud_cover_low", "N/A")
            cm = h.get("cloud_cover_mid", "N/A")
            ch = h.get("cloud_cover_high", "N/A")
            output.append(f"Clouds: {c}% (L:{cl} M:{cm} H:{ch})")
            
        if args.type in ["radiation", "all"]:
            sw = h.get("shortwave_radiation", "N/A")
            dr = h.get("direct_radiation", "N/A")
            output.append(f"Rad: {sw} / {dr} W/m2")
            
        if args.type in ["thermal", "all"]:
            bl = h.get("boundary_layer_height", "N/A")
            temp = h.get("temperature_2m", "N/A")
            output.append(f"T: {temp}°C | BL: {bl}m")

        print(" | ".join(output))

if __name__ == "__main__":
    main()
