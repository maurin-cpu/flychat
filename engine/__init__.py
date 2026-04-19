"""
Flychat Engine Package — aufgeteilt aus dem ehemaligen 6500-Zeilen-Monolith chat_engine.py.

Struktur:
    _common.py          — Konstanten + Pure-Helpers (keine Engine-State-Abhaengigkeit)
    weather_context.py  — _build_weather_context + Formatierungs-Helfer
    spot_analyzer.py    — run_spot_analyses_stream + Safety/Flyability fuer Spots
    region_analyzer.py  — run_region_analyses_* + Region-Varianten
    chat_orchestrator.py— answer + answer_stream + Tool-Loop

Backwards-Kompatibilitaet:
    `from chat_engine import FlychatEngine` funktioniert weiterhin — chat_engine.py
    re-exportiert aus diesem Package.
"""
