"""wingcast-mcp — Forecast-Daten (Rohdaten + deterministische Kennzahlen) per MCP.

Experiment (16.09.2026): ein externes Claude soll aus Meteogramm-Daten selbst
ableiten, wo man fliegen kann — ohne die LLM-Analysen der App.

Aufbau:
  export.py     laeuft im App-Prozess (Engine im Speicher), schreibt data/mcp_export/
  store.py      liest den Export (Pointer CURRENT, mtime-Reload), kein Engine-Import
  screening.py  reine Filter-/Rangfunktionen ueber die Screening-Zeilen
  formatting.py Text-Tabellen fuer Claude (Tokens sparen, Verlauf sichtbar halten)
  server.py     FastMCP-Tools/Resources/Prompts
"""
