"""
Schreibt den gleichen Wetter-Kontext-Text, den die KI bei vollem Rohkontext sieht
(_build_weather_context), in eine Datei zum Ansehen.

Enthält am Ende Föhn: Snapshot (═══ FÖHN-INDIKATOR ═══) plus Zeitreihe
(═══ FÖHN — ZEITREIHE & GRADIENTEN (KI) ═══) — identisch zu dem, was an die KI geht.

Nutzung (im Projektroot):
  python scripts/dump_weather_context.py
  python scripts/dump_weather_context.py --force          # API neu laden
  python scripts/dump_weather_context.py -o mein_dump.txt
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from chat_engine import FlychatEngine


def main() -> None:
    p = argparse.ArgumentParser(description="Wetter-Kontext für die KI in eine Datei schreiben")
    p.add_argument(
        "-o",
        "--output",
        default="weather_context_dump.txt",
        help="Ausgabedatei (Standard: weather_context_dump.txt im aktuellen Verzeichnis)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Wetter neu von der API laden (ignoriert ggf. Cache-Frische)",
    )
    args = p.parse_args()

    engine = FlychatEngine()
    engine.refresh_weather(force=args.force)
    text = engine._build_weather_context()

    out_path = os.path.abspath(args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"Geschrieben: {out_path}")
    print(f"Zeichen: {len(text):,}")


if __name__ == "__main__":
    main()
