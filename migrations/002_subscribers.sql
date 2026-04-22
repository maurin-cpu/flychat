-- ============================================================================
-- Gleitcast Email-Briefing Subscribers (Stufe 1)
-- ============================================================================
-- Ergaenzt 001_initial_schema.sql um Subscriber-Management fuer das
-- E-Mail-Briefing-MVP. Backend-only: RLS aktiviert, aber KEINE public-read-Policy
-- (Subscriber-Daten sind PII, duerfen nur via Service-Role-Key gelesen werden).
--
-- Ausfuehren: Supabase Dashboard -> SQL Editor -> "New query" -> diesen File
-- einfuegen -> "Run". Idempotent (CREATE IF NOT EXISTS).
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) SUBSCRIBERS: Ein Row pro E-Mail-Abo
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscribers (
    id              SERIAL PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,

    -- Region-IDs (aus data/regionen.csv, z.B. ['bern_oberland', 'zentralschweiz'])
    regions         TEXT[] NOT NULL DEFAULT '{}',

    -- 'beginner' | 'standard' | 'expert'
    skill_level     TEXT NOT NULL DEFAULT 'standard',

    -- Lifecycle-Status
    --   pending       = registriert, noch nicht bestaetigt (Double-Opt-In)
    --   active        = bestaetigt, bekommt Briefings Mo/Mi/Fr
    --   paused        = pausiert bis paused_until (Subscriber kann selbst setzen)
    --   unsubscribed  = dauerhaft abgemeldet
    status          TEXT NOT NULL DEFAULT 'pending',
    paused_until    DATE,

    -- Aktions-Tokens (passwordless)
    --   confirm_token = einmal-Token fuer Double-Opt-In (nach Confirm geloescht)
    --   action_token  = persistent, wird in jeder Briefing-Mail mitgesendet
    --                   fuer /account/:token, /unsubscribe/:token, /feedback/:token/:verdict
    confirm_token   TEXT UNIQUE,
    action_token    TEXT UNIQUE NOT NULL,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at    TIMESTAMPTZ,
    last_sent_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT subscribers_status_valid
        CHECK (status IN ('pending', 'active', 'paused', 'unsubscribed')),
    CONSTRAINT subscribers_skill_level_valid
        CHECK (skill_level IN ('beginner', 'standard', 'expert'))
);

CREATE INDEX IF NOT EXISTS idx_subscribers_status_active
    ON subscribers (status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_subscribers_confirm_token
    ON subscribers (confirm_token) WHERE confirm_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_subscribers_action_token
    ON subscribers (action_token);

-- ---------------------------------------------------------------------------
-- 2) SUBSCRIBER_FEEDBACK: 1-Click-Feedback aus Briefing-Mails
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscriber_feedback (
    id              SERIAL PRIMARY KEY,
    subscriber_id   INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    briefing_date   DATE NOT NULL,
    verdict         TEXT NOT NULL,            -- 'correct' | 'wrong'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT subscriber_feedback_verdict_valid
        CHECK (verdict IN ('correct', 'wrong'))
);

CREATE INDEX IF NOT EXISTS idx_subscriber_feedback_subscriber
    ON subscriber_feedback (subscriber_id);
CREATE INDEX IF NOT EXISTS idx_subscriber_feedback_date
    ON subscriber_feedback (briefing_date);

-- ---------------------------------------------------------------------------
-- 3) Trigger: updated_at pflegen (nutzt bestehende set_updated_at() Funktion)
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_subscribers_updated ON subscribers;
CREATE TRIGGER trg_subscribers_updated
    BEFORE UPDATE ON subscribers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 4) RLS: Enabled, aber KEINE public-read-Policy (PII-Schutz).
--    Nur Service-Role-Key (bypassed RLS) darf subscribers lesen/schreiben.
-- ---------------------------------------------------------------------------
ALTER TABLE subscribers          ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriber_feedback  ENABLE ROW LEVEL SECURITY;

COMMIT;
