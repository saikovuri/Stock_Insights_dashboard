-- ============================================================
-- Stock Insights – Enable RLS on all public tables
-- Run this in the Supabase SQL Editor (one-time migration)
-- ============================================================

-- ── 1. Enable RLS on every table ────────────────────────────
ALTER TABLE public.users              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.holdings           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.options            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transactions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.watchlist          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.closed_trades      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.closed_options     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.refresh_tokens     ENABLE ROW LEVEL SECURITY;

-- ── 2. Drop any accidental legacy policies ──────────────────
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT tablename, policyname
    FROM pg_policies
    WHERE schemaname = 'public'
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', r.policyname, r.tablename);
  END LOOP;
END $$;

-- ── 3. Service-role bypass policies (backend uses service role) ──
-- The app connects via psycopg2 with the Supabase service-role
-- DATABASE_URL, which runs as the `postgres` superuser and
-- already bypasses RLS. These policies cover any direct
-- `service_role` JWT connections via the REST API as well.

CREATE POLICY "service_role_all_users"
  ON public.users FOR ALL
  TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_all_holdings"
  ON public.holdings FOR ALL
  TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_all_options"
  ON public.options FOR ALL
  TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_all_transactions"
  ON public.transactions FOR ALL
  TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_all_watchlist"
  ON public.watchlist FOR ALL
  TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_all_closed_trades"
  ON public.closed_trades FOR ALL
  TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_all_closed_options"
  ON public.closed_options FOR ALL
  TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_all_refresh_tokens"
  ON public.refresh_tokens FOR ALL
  TO service_role USING (true) WITH CHECK (true);

-- ── 4. Revoke anon/authenticated direct access ──────────────
-- No policies are created for `anon` or `authenticated` roles,
-- so the Supabase public REST API returns zero rows / permission
-- denied for every table. The backend is unaffected because it
-- connects via the direct DATABASE_URL (postgres superuser).

REVOKE ALL ON public.users          FROM anon, authenticated;
REVOKE ALL ON public.holdings       FROM anon, authenticated;
REVOKE ALL ON public.options        FROM anon, authenticated;
REVOKE ALL ON public.transactions   FROM anon, authenticated;
REVOKE ALL ON public.watchlist      FROM anon, authenticated;
REVOKE ALL ON public.closed_trades  FROM anon, authenticated;
REVOKE ALL ON public.closed_options FROM anon, authenticated;
REVOKE ALL ON public.refresh_tokens FROM anon, authenticated;

-- ── 5. Verify ───────────────────────────────────────────────
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
