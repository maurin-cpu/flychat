"""
Wingcast Engine Package — aufgeteilt aus dem ehemaligen 6500-Zeilen-Monolith chat_engine.py.

Struktur:
    _common.py          — Konstanten + Pure-Helpers (keine Engine-State-Abhaengigkeit)
    weather_context.py  — WeatherContextMixin: _build_weather_context, Thermik/Shear/Gust
                          Helpers, _build_single_{spot,region}_context
    analyzers.py        — AnalyzersMixin: Spot- + Region-Analyzers, Batch-Modus,
                          run_{spot,region,all}_analyses[_stream], Briefing-Datenpfad
    chat_orchestrator.py— ChatOrchestratorMixin: answer + answer_stream + Tool-Loop
                          (geocode, isochrone, map-actions)

Backwards-Kompatibilitaet:
    `from chat_engine import WingcastEngine` funktioniert weiterhin — chat_engine.py
    kombiniert die Mixins via Mehrfachvererbung:
        class WingcastEngine(ChatOrchestratorMixin, AnalyzersMixin, WeatherContextMixin):
            ...
"""
