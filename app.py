"""
Vercel Entry Point für Gleitcast.
Lazy-Initialisierung der Engine beim ersten Request (kein langer Cold-Start).
"""

import os

from dotenv import load_dotenv
load_dotenv()

from web import app, init_app
from chat_engine import GleitcastEngine

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = GleitcastEngine()
        init_app(_engine)
        # Kein refresh_weather() beim Cold-Start - verhindert Timeout (viele API-Calls).
        # Nutzer triggert /api/refresh-weather manuell.
    return _engine


@app.before_request
def _ensure_engine():
    _get_engine()
