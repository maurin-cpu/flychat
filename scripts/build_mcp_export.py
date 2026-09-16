"""Schreibt den MCP-Export (data/mcp_export/) von Hand — Experiment-Modus.

Braucht ein aktuelles data/wetterdaten.json (lokal: .\\scripts\\sync_from_server.ps1).
Der Foehn-Fetch geht gegen Open-Meteo; scheitert er, tragen die Zeilen
foehn_level="unknown".

Nutzung (im Projektroot):
  python scripts/build_mcp_export.py
  python scripts/build_mcp_export.py --out data/mcp_export
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

# Wie main.py:17 — VOR allen Engine-Imports, sonst weichen Schwellen von der App ab.
import config_overrides

config_overrides.init()

from chat_engine import WingcastEngine  # noqa: E402
from mcp_server.export import build_export  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="MCP-Export aus dem Wetter-Cache schreiben")
    p.add_argument("--out", default=None, help="Zielordner (Standard: data/mcp_export)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    t0 = time.time()
    engine = WingcastEngine()
    engine.load_weather_from_cache()
    print(f"[EXPORT] Engine geladen in {time.time() - t0:.1f}s")
    build_dir = build_export(engine, args.out)
    print(f"[EXPORT] fertig: {build_dir} ({time.time() - t0:.1f}s gesamt)")


if __name__ == "__main__":
    main()
