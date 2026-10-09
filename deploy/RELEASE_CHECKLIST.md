# Release Checklist

## Required Before Deployment

1. Review and commit the changes. Require both jobs in `.github/workflows/ci.yml` to pass, including the disposable PostgreSQL job. SQLite and mocked browser success alone are insufficient for a PostgreSQL release.
2. Take a database-native backup and verify that it restores into a disposable database. For SQLite, use its backup API or stop the app and copy the database together with its WAL state; do not copy a live `.db` file alone. For PostgreSQL, use the provider backup/restore workflow or `pg_dump` with credentials supplied locally.
3. Run the new backend once against the restored staging database with the scheduler disabled. Schema changes are additive: new audit/snapshot tables, paper-cost columns and closed-lot provenance. Existing trades are not rewritten. Existing records receive labeled opening snapshots.
4. Apply `deploy/supabase_rls.sql` after schema installation in staging, using the migration owner. It restricts changes to StockPilot tables. Verify anonymous/authenticated REST roles cannot read private records. The existing custom-JWT backend uses trusted database access and must retain explicit user filters; these RLS rules are not Supabase per-user authentication policies.
5. Run `python backend/release_check.py --base-url https://YOUR-STAGING-HOST`. It performs read-only health/provider checks. For signed-in checks, set `STOCKPILOT_SMOKE_TOKEN` locally and add `--authenticated`; never paste credentials into chat, logs or the repository.
6. Inspect provider timestamps and representative stock/option quotes against a broker. A successful price response alone does not prove timeliness or an executable option fill. Exercise known/unknown earnings and provider-failure states.
7. Review informational tax lots and cycle allocations against broker records. Enter actual fees and external cash flows; use total-account NAV immediately before each flow and at period endpoints. Missing historical facts must remain unknown. Wash sales, corporate actions, assignment/exercise and option tax treatment still require review.
8. Only then deploy the same commit. Re-run read-only smoke checks on the deployed host and verify no new database/HTTP errors. `/api/health` returns 503 on database failure; `/health` is only process liveness.

## Research Data

- Historical membership requires a documented dataset with effective dates and actual publication timestamps. Import via `backend/research_universe.py` and set `RESEARCH_UNIVERSE_SOURCE`; do not backfill today's members as historical facts.
- Missing constituent dates or price series suppress scanner historical results. Check delisted securities, corporate actions and source coverage before trusting even populated results.
- Walk-forward choices are made on training history only. The small parameter grid is not a discovery of trading edge. New paper results subtract frozen modeled costs; they are not executed trades.

## Native And Push Release

- Build the frontend with the intended production API origin, then run the existing Capacitor sync/build workflow on the target platform. Do not ship a localhost API URL or stale bundled web assets.
- On a physical Android device and, for an iOS release, an iPhone: test launch, login, refresh-token expiry, account switch, logout, background/resume, offline recovery, deep links and table scrolling.
- With an explicitly opted-in test account, verify notification permission denial/grant, foreground/background delivery, notification navigation and topic revocation after logout. Confirm private financial details are not unintentionally exposed on the lock screen.
- iOS signing/build and physical notification delivery cannot be established by desktop Playwright or a Windows development machine. Do not call the native release verified until these checks are completed.

## Rollback

- Keep the previous application artifact and the verified database backup. Do not drop audit tables or rewrite audit events as part of rollback.
- An older backend may omit newly added provenance/cost fields. If rolling back code, pause financial writes until compatibility is verified; otherwise the audit remains intact but derived reports may have incomplete provenance.
- Prefer correction/reversal entries over deleting financial evidence. Database owners can bypass database protections; production access control and backups remain necessary.