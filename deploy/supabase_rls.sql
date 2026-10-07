-- ============================================================
-- Stock Insights – Enable RLS on all public tables
-- Run this in the Supabase SQL Editor. Safe to re-run any time.
-- ============================================================

-- ── 0. Create tables added in v3 (the backend also creates these on startup) ──
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS ntfy_topic TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS trader_profile TEXT;

CREATE TABLE IF NOT EXISTS public.notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES public.users(id),
    kind TEXT NOT NULL,
    ticker TEXT,
    title TEXT NOT NULL,
    body TEXT,
    data TEXT,
    dedup_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ,
    UNIQUE(user_id, dedup_key)
);
CREATE TABLE IF NOT EXISTS public.iv_history (
    ticker TEXT NOT NULL,
    day TEXT NOT NULL,
    iv DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (ticker, day)
);
CREATE TABLE IF NOT EXISTS public.user_alerts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES public.users(id),
    ticker TEXT NOT NULL,
    kind TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    note TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggered_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS public.journal (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES public.users(id),
    ticker TEXT NOT NULL,
    side TEXT NOT NULL DEFAULT 'long',
    shares DOUBLE PRECISION NOT NULL,
    entry_date TEXT NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    exit_date TEXT,
    exit_price DOUBLE PRECISION,
    stop DOUBLE PRECISION,
    target DOUBLE PRECISION,
    setup TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS public.kv_cache (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS public.theses (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES public.users(id),
    ticker TEXT NOT NULL,
    thesis TEXT NOT NULL,
    next_earnings TEXT,
    last_check TEXT,
    last_checked_at TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, ticker)
);
CREATE TABLE IF NOT EXISTS public.idea_log (
    id SERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT,
    ticker TEXT NOT NULL,
    expiry TEXT NOT NULL,
    legs TEXT NOT NULL,
    legs_key TEXT NOT NULL,
    net DOUBLE PRECISION NOT NULL,
    risk DOUBLE PRECISION,
    spot DOUBLE PRECISION NOT NULL,
    delta DOUBLE PRECISION,
    created_day TEXT NOT NULL,
    settle_price DOUBLE PRECISION,
    pnl DOUBLE PRECISION,
    UNIQUE(kind, ticker, expiry, legs_key)
);
ALTER TABLE public.closed_options ADD COLUMN IF NOT EXISTS opened_at TEXT;
CREATE INDEX IF NOT EXISTS idx_notifications_user ON public.notifications(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_user_alerts_active ON public.user_alerts(active);
CREATE INDEX IF NOT EXISTS idx_journal_user ON public.journal(user_id);

-- ── 1. Drop any accidental legacy policies ──────────────────
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT tablename, policyname
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = ANY(ARRAY[
        'users', 'holdings', 'options', 'transactions', 'watchlist', 'closed_trades',
        'closed_options', 'refresh_tokens', 'notifications', 'iv_history',
        'user_alerts', 'journal', 'kv_cache', 'theses', 'idea_log',
        'accounting_events', 'universe_snapshots', 'account_cash', 'nav_snapshots', 'applied_splits',
        'watchlist_lists', 'applied_actions'
      ])
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', r.policyname, r.tablename);
  END LOOP;
END $$;

-- ── 2. Enable RLS, add service-role policy, revoke public access ──
-- The backend connects via DATABASE_URL as the `postgres` superuser, which
-- bypasses RLS. The service_role policy covers direct REST API use; no
-- policies exist for `anon`/`authenticated`, so the public REST API sees nothing.
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'users', 'holdings', 'options', 'transactions', 'watchlist', 'closed_trades',
    'closed_options', 'refresh_tokens', 'notifications', 'iv_history',
    'user_alerts', 'journal', 'kv_cache', 'theses', 'idea_log',
    'accounting_events', 'universe_snapshots', 'account_cash', 'nav_snapshots', 'applied_splits',
    'watchlist_lists', 'applied_actions'
  ] LOOP
    IF to_regclass('public.' || t) IS NULL THEN
      RAISE NOTICE 'Skipping missing table %', t;
      CONTINUE;
    END IF;
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
                   'service_role_all_' || t, t);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', t);
  END LOOP;
END $$;

-- ── 3. Verify ───────────────────────────────────────────────
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
