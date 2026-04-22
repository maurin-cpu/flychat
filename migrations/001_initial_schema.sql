-- ============================================================================
-- Gleitcast Initial Schema (Supabase / Postgres)
-- ============================================================================
-- Ersetzt:
--   data/wetterdaten.json         → forecasts + regions_forecasts + weather_meta
--   data/spot_analyses.json       → spot_analyses
--   data/region_analyses.json     → region_analyses
--   InstantDB-Subscriptions       → Supabase Realtime auf diese Tabellen
--
-- Behaelt (nicht migriert):
--   data/station_observations.db  → bleibt lokal SQLite (funktioniert gut)
--
-- Ausfuehren: Supabase Dashboard → SQL Editor → "New query" → diesen File
-- einfuegen → "Run". Idempotent (CREATE IF NOT EXISTS).
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) WEATHER_META: globale Refresh-Metadaten (Single-Row-Tabelle)
--    Ersetzt: wetterdaten.json["_meta"]
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weather_meta (
    id              TEXT PRIMARY KEY DEFAULT 'global',
    last_updated    TIMESTAMPTZ,
    spots_count     INTEGER,
    forecast_days   INTEGER,
    fetch_status    TEXT,
    fetch_status_reason TEXT,
    payload         JSONB,            -- Gesamtes _meta-Dict fuer Vorwaertskompatibilitaet
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 2) FORECASTS: Pro Spot ein JSONB-Eintrag (hourly_data, pressure_level_data, …)
--    Ersetzt: wetterdaten.json["<spot_name>"]
--    Wird bei jedem Refresh ueberschrieben (UPSERT).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forecasts (
    spot_name       TEXT PRIMARY KEY,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    elevation_m     DOUBLE PRECISION,
    payload         JSONB NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_forecasts_updated ON forecasts (updated_at DESC);

-- ---------------------------------------------------------------------------
-- 3) REGIONS_FORECASTS: Pro Region ein JSONB-Eintrag
--    Ersetzt: wetterdaten.json["_regions"]["<region_id>"]
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regions_forecasts (
    region_id       TEXT PRIMARY KEY,
    region_name     TEXT,
    elevation_ref   DOUBLE PRECISION,
    payload         JSONB NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_regions_forecasts_updated ON regions_forecasts (updated_at DESC);

-- ---------------------------------------------------------------------------
-- 4) SPOT_ANALYSES: Pro Spot × Datum eine LLM-Analyse
--    Ersetzt: spot_analyses.json[<spot>][<date>]
--    Composite-PK (spot_name, analysis_date).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS spot_analyses (
    spot_name       TEXT NOT NULL,
    analysis_date   DATE NOT NULL,
    payload         JSONB NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (spot_name, analysis_date)
);

CREATE INDEX IF NOT EXISTS idx_spot_analyses_date ON spot_analyses (analysis_date);
CREATE INDEX IF NOT EXISTS idx_spot_analyses_updated ON spot_analyses (updated_at DESC);

-- ---------------------------------------------------------------------------
-- 5) REGION_ANALYSES: Pro Region × Datum eine LLM-Analyse
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS region_analyses (
    region_id       TEXT NOT NULL,
    analysis_date   DATE NOT NULL,
    payload         JSONB NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (region_id, analysis_date)
);

CREATE INDEX IF NOT EXISTS idx_region_analyses_date ON region_analyses (analysis_date);
CREATE INDEX IF NOT EXISTS idx_region_analyses_updated ON region_analyses (updated_at DESC);

-- ---------------------------------------------------------------------------
-- 6) Trigger: updated_at automatisch pflegen
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_forecasts_updated ON forecasts;
CREATE TRIGGER trg_forecasts_updated
    BEFORE UPDATE ON forecasts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_regions_forecasts_updated ON regions_forecasts;
CREATE TRIGGER trg_regions_forecasts_updated
    BEFORE UPDATE ON regions_forecasts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_spot_analyses_updated ON spot_analyses;
CREATE TRIGGER trg_spot_analyses_updated
    BEFORE UPDATE ON spot_analyses
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_region_analyses_updated ON region_analyses;
CREATE TRIGGER trg_region_analyses_updated
    BEFORE UPDATE ON region_analyses
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_weather_meta_updated ON weather_meta;
CREATE TRIGGER trg_weather_meta_updated
    BEFORE UPDATE ON weather_meta
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 7) Row Level Security (RLS)
--    Backend nutzt SERVICE_ROLE_KEY (bypassed RLS).
--    Frontend nutzt ANON_KEY → braucht SELECT-Policy fuer Realtime.
-- ---------------------------------------------------------------------------
ALTER TABLE weather_meta       ENABLE ROW LEVEL SECURITY;
ALTER TABLE forecasts          ENABLE ROW LEVEL SECURITY;
ALTER TABLE regions_forecasts  ENABLE ROW LEVEL SECURITY;
ALTER TABLE spot_analyses      ENABLE ROW LEVEL SECURITY;
ALTER TABLE region_analyses    ENABLE ROW LEVEL SECURITY;

-- Public READ fuer alle Tabellen (Frontend braucht Realtime-Subscriptions)
DROP POLICY IF EXISTS "public read" ON weather_meta;
CREATE POLICY "public read" ON weather_meta FOR SELECT USING (true);

DROP POLICY IF EXISTS "public read" ON forecasts;
CREATE POLICY "public read" ON forecasts FOR SELECT USING (true);

DROP POLICY IF EXISTS "public read" ON regions_forecasts;
CREATE POLICY "public read" ON regions_forecasts FOR SELECT USING (true);

DROP POLICY IF EXISTS "public read" ON spot_analyses;
CREATE POLICY "public read" ON spot_analyses FOR SELECT USING (true);

DROP POLICY IF EXISTS "public read" ON region_analyses;
CREATE POLICY "public read" ON region_analyses FOR SELECT USING (true);

-- ---------------------------------------------------------------------------
-- 8) Realtime-Publication
--    Damit Frontend per Supabase-JS `supabase.channel(...).on(...)` Events bekommt.
-- ---------------------------------------------------------------------------
-- Die Tabellen zur Realtime-Publication hinzufuegen (falls nicht schon drin).
-- supabase_realtime ist die Standard-Publication fuer Supabase Realtime.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'weather_meta'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE weather_meta;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'forecasts'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE forecasts;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'regions_forecasts'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE regions_forecasts;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'spot_analyses'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE spot_analyses;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'region_analyses'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE region_analyses;
    END IF;
END $$;

COMMIT;
