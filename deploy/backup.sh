#!/usr/bin/env bash
# Manual encrypted backup of the production database (same format as the weekly GitHub Action).
# Usage:  DATABASE_URL='postgresql://...:5432/postgres' ./deploy/backup.sh
# Restore: gpg -d FILE.sql.gz.gpg | gunzip | psql "$TARGET_DATABASE_URL"
set -euo pipefail
: "${DATABASE_URL:?Set DATABASE_URL (Supabase session-mode URI, port 5432)}"
command -v pg_dump >/dev/null || { echo "pg_dump not found - install the PostgreSQL 17 client"; exit 1; }
umask 077
OUT="stockinsights-$(date -u +%Y-%m-%d-%H%M).sql.gz.gpg"
pg_dump "$DATABASE_URL" --schema=public --no-owner --no-privileges --exclude-table-data=public.kv_cache \
  | gzip -9 | gpg --symmetric --cipher-algo AES256 -o "$OUT"
echo "Wrote $OUT ($(du -h "$OUT" | cut -f1)). Keep the passphrase somewhere safe - without it the backup is unreadable."
