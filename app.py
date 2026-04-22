"""
Vercel Entry Point für Gleitcast.
Lazy-Initialisierung der Engine beim ersten Request (kein langer Cold-Start).
"""

import os

from dotenv import load_dotenv
load_dotenv()

from web import app, init_app
from chat_engine import GleitcastEngine
from instantdb_client import InstantDBClient
import config

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        instantdb = None
        supabase_active = bool(os.environ.get("SUPABASE_URL", "").strip()
                               and os.environ.get("SUPABASE_ANON_KEY", "").strip())
        # InstantDB nur wenn Supabase NICHT konfiguriert (Fallback-Modus)
        if not supabase_active and config.INSTANTDB_ADMIN_TOKEN:
            instantdb = InstantDBClient(
                app_id=config.INSTANTDB_APP_ID,
                admin_token=config.INSTANTDB_ADMIN_TOKEN,
                api_url=config.INSTANTDB_API_URL,
            )
        _engine = GleitcastEngine(instantdb_client=instantdb)
        init_app(_engine)
        # Kein refresh_weather() beim Cold-Start - verhindert Timeout (viele API-Calls).
        # Nutzer triggert /api/refresh-weather manuell.
    return _engine


@app.before_request
def _ensure_engine():
    _get_engine()
