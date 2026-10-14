# Moving the StockPilot database off Supabase (future option)

**Recommendation: stay on Supabase** unless you have a reason to move: it's free, it's off your laptop (so a dead disk can't take your data), and the weekly encrypted backup workflow already works with it. This guide is here so you can move later without help.

Every option below was rehearsed on 2026-10-10 against the real production database (copies were made into throwaway databases and then deleted):
- Supabase → PostgreSQL 17 on another machine: restore completed with zero errors; row counts matched; the app started on it, wrote a new holding, and its audit triggers and ID sequences worked.
- Supabase → SQLite with [deploy/pg_to_sqlite.py](deploy/pg_to_sqlite.py): all 25 tables copied with matching counts; the app read options, closed trades, watchlist and the accounting report from it.

The "second Supabase project" and "Neon" options were **not** rehearsed; they use the same dump file and the same commands, with the differences called out.

---

## Facts about the current database (as of 2026-10-10)

| Item | Value |
| --- | --- |
| Engine | PostgreSQL 17.6 on Supabase |
| Size | About 13 MB in total; your own data is under 2 MB. The largest table is `kv_cache` (regenerable scan cache). |
| Tables | 25, all in the `public` schema. The backend creates and upgrades them itself at start-up (`database.init_db()`); there are no migration files. |
| Users | 1 login |
| App connection | Supabase **transaction pooler**, port **6543** (`DATABASE_URL` in the server's `backend/.env`) |
| Backup connection | Supabase **session pooler**, port **5432** (the `DATABASE_URL` GitHub secret used by the weekly backup) |
| Special objects | Two trigger functions (`stockpilot_audit_capture`, `stockpilot_audit_immutable`), audit triggers on 5 tables, row-level security with policies for Supabase's `service_role` |

`pg_dump` needs the **session** pooler (port 5432), not the transaction pooler (6543). The session URL is the same as the app's URL with `:6543/` changed to `:5432/`, or copy it from Supabase → your project → **Connect** → **Session pooler**.

---

## Choose an option

| Option | Where the data lives | Cost | Effort | Main risk |
| --- | --- | --- | --- | --- |
| **A. Second free Supabase project** | Supabase (another project or another account) | Free | Low | Same provider; unused free projects pause after 7 days |
| **B. PostgreSQL 17 on the laptop** | Your laptop | Free | Medium | You own backups; laptop disk failure loses anything not backed up |
| **C. SQLite file on the laptop** | One file on your laptop | Free | Lowest | Same as B; fine for one user, but no `pg_dump`-style tooling |
| **D. Neon (another free hosted Postgres)** | Neon | Free tier with compute limits | Low | The always-on scheduler may use up the free compute hours |

If you move to the laptop, pick **B** over C: it's the same engine as today, so the dump/restore and the existing backup format keep working, and moving back to a hosted Postgres later is a single restore.

---

## Before any option

1. **Read the whole option first.** Plan for about 15 minutes of downtime.
2. **Fresh backup.** GitHub → repo → **Actions → Database backup → Run workflow**. When it finishes, download the artifact from that run and keep it with the `BACKUP_PASSPHRASE` (password manager). This is your way back if anything goes wrong.
3. **Know where the server runs** (the home laptop from [setup_laptop.md](setup_laptop.md)). Commands marked **(server)** run there.
4. **Have the Postgres 17 tools** wherever you run `pg_dump`/`psql`. On Ubuntu 24.04 (the laptop):

   ```bash
   sudo apt -y install postgresql-common
   sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y     # adds the official PostgreSQL apt repository
   sudo apt -y install postgresql-client-17                            # B installs the full server instead (step B1)
   pg_dump --version                                                   # must say 17.x
   ```

   Use version 17 (or newer) tools: older `pg_dump` refuses to dump a 17 server. The repository script only supports current Ubuntu releases (it failed on Ubuntu 20.04).
5. **Freeze writes.** The scheduler writes notifications and idea logs every few minutes; a copy taken while it runs misses the newest rows. Stop the server right before dumping, and start it again only after switching `DATABASE_URL`. **(server):**

   ```bash
   sudo systemctl stop stock-insights
   ```

6. **Put the session URL in a variable** (it contains the database password; it won't be saved in your shell history if you paste it after a leading space, and it disappears when you log out). **(server or laptop):**

   ```bash
    export SUPABASE_URL='postgresql://postgres.xxxxxxxx:PASSWORD@aws-0-us-east-1.pooler.supabase.com:5432/postgres'
   psql "$SUPABASE_URL" -Atc "select count(*) from public.users"     # should print 1
   ```

7. **Dump** (keeps everything except the regenerable cache rows):

   ```bash
   umask 077
   pg_dump "$SUPABASE_URL" --schema=public --no-owner --no-privileges \
     --exclude-table-data=public.kv_cache -f ~/stockpilot-dump.sql
   ls -lh ~/stockpilot-dump.sql        # about 180 KB today
   ```

The dump contains three statements that a non-Supabase database rejects. Each option says how to handle them:
- `CREATE SCHEMA public;` and `COMMENT ON SCHEMA public ...` (the schema already exists in a new database);
- `CREATE POLICY ... TO service_role` (that role only exists on Supabase).

---

## Option A: a second free Supabase project

Use this to move to another Supabase account or region, or to keep a tested standby.

**A1. Create the project.** supabase.com → **New project** → choose the organization (a free organization allows two active projects) → name `stockpilot-2` → a **database password of letters and digits only** (other characters must be URL-encoded in `DATABASE_URL`) → region **East US (North Virginia)** or the one nearest your server → **Create**. Wait until it's ready.

**A2. Get its URLs.** Project → **Connect**:
- **Session pooler** URI (port 5432): for restoring and for the GitHub backup secret;
- **Transaction pooler** URI (port 6543): for the app's `DATABASE_URL`.

Replace `[YOUR-PASSWORD]` in each with the password from A1.

**A3. Restore.** Remove the two schema lines, which Supabase already has (the policy lines work as-is because Supabase has `service_role`):

```bash
 export NEW_URL='postgresql://postgres.yyyyyyyy:PASSWORD@aws-0-us-east-1.pooler.supabase.com:5432/postgres'
sed -e '/^CREATE SCHEMA public;$/d' -e '/^COMMENT ON SCHEMA public IS/d' ~/stockpilot-dump.sql > ~/stockpilot-dump-supabase.sql
psql "$NEW_URL" -v ON_ERROR_STOP=1 -q -f ~/stockpilot-dump-supabase.sql && echo RESTORED
```

If it stops with an error, nothing is switched yet: fix the cause, then in the new project's **SQL Editor** run `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` and restore again.

**A4. Lock it down.** In the new project's **SQL Editor**, paste and run [deploy/supabase_rls.sql](deploy/supabase_rls.sql). It's safe to re-run.

**A5. Compare row counts** (`kv_cache` is expected to differ):

```bash
for t in $(psql "$SUPABASE_URL" -Atc "select table_name from information_schema.tables where table_schema='public' order by 1"); do
  a=$(psql "$SUPABASE_URL" -Atc "select count(*) from public.\"$t\""); b=$(psql "$NEW_URL" -Atc "select count(*) from public.\"$t\"")
  [ "$a" = "$b" ] || echo "DIFFERENT: $t old=$a new=$b"
done; echo "compare finished"
```

**A6. Switch the app. (server):** in `~/stock-insights/backend/.env`, set `DATABASE_URL=` to the new **transaction pooler** URI (port 6543), then:

```bash
sudo systemctl start stock-insights
sleep 10; curl -s http://127.0.0.1:8000/api/health; echo
```

Sign in on the website: you should still be logged in (sessions come from `JWT_SECRET`, which didn't change). Check Portfolio and Journal.

**A7. Update the backup secret.** GitHub → Settings → Secrets and variables → Actions → `DATABASE_URL` = the new **session pooler** URI. Then run **Database backup** once by hand and check it succeeds.

**A8. Retire the old project** after a week of normal use: old project → Settings → **Pause project**; delete it later once you're sure.

**Using a second project as a standby instead:** repeat A3–A5 once a month with the latest backup (`gpg -d FILE.sql.gz.gpg | gunzip > ~/stockpilot-dump.sql`, then A3), so you know the recovery works. Free projects with no traffic pause after 7 days; that's fine for a standby. Press **Restore project** in its dashboard before you need it.

---

## Option B: PostgreSQL 17 on the laptop

Do this on the laptop from [setup_laptop.md](setup_laptop.md), with the backend already running there against Supabase.

### B1. Install PostgreSQL 17 (laptop)

```bash
sudo apt -y install postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt -y install postgresql-17
pg_lsclusters          # shows "17 main 5432 online"
```

Ubuntu's PostgreSQL only listens on `localhost`; leave it that way. The firewall from setup_laptop.md blocks port 5432 from outside anyway.

### B2. Create the app's login and database

Make a password of letters and digits (no URL-encoding needed):

```bash
DB_PASS=$(openssl rand -hex 24); echo "$DB_PASS"      # store it in your password manager
sudo -u postgres psql -v ON_ERROR_STOP=1 << SQL
CREATE ROLE stockpilot LOGIN PASSWORD '$DB_PASS';
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN;
CREATE DATABASE stockpilot OWNER stockpilot;
SQL
export LOCAL_URL="postgresql://stockpilot:$DB_PASS@localhost:5432/stockpilot"
psql "$LOCAL_URL" -v ON_ERROR_STOP=1 -c "DROP SCHEMA public"
```

The three `NOLOGIN` roles are placeholders so the dump's Supabase policies restore; they can't log in. Dropping the empty `public` schema lets the dump's `CREATE SCHEMA public` recreate it, owned by `stockpilot`.

### B3. Freeze, dump, restore

Do "Before any option" steps 5–7 (stop the server, set `SUPABASE_URL`, dump). Then:

```bash
psql "$LOCAL_URL" -v ON_ERROR_STOP=1 -q -f ~/stockpilot-dump.sql && echo RESTORED
```

The rehearsal printed one `setval` result (17) and then finished. If it stops with an error, recreate the database and try again:

```bash
sudo -u postgres psql -c "DROP DATABASE stockpilot" -c "CREATE DATABASE stockpilot OWNER stockpilot"
psql "$LOCAL_URL" -c "DROP SCHEMA public"
```

### B4. Compare row counts

```bash
for t in $(psql "$SUPABASE_URL" -Atc "select table_name from information_schema.tables where table_schema='public' order by 1"); do
  a=$(psql "$SUPABASE_URL" -Atc "select count(*) from public.\"$t\""); b=$(psql "$LOCAL_URL" -Atc "select count(*) from public.\"$t\"")
  [ "$a" = "$b" ] || echo "DIFFERENT: $t supabase=$a local=$b"
done; echo "compare finished"
```

Only `kv_cache` should differ (its rows were left out on purpose; the app refills it).

### B5. Start the backend after PostgreSQL on boot

```bash
sudo mkdir -p /etc/systemd/system/stock-insights.service.d
sudo tee /etc/systemd/system/stock-insights.service.d/postgres.conf > /dev/null << 'EOF'
[Unit]
After=postgresql.service
Wants=postgresql.service
EOF
sudo systemctl daemon-reload
```

### B6. Switch the app

Edit `~/stock-insights/backend/.env` and set:

```
DATABASE_URL=postgresql://stockpilot:THE_PASSWORD@localhost:5432/stockpilot
```

Then:

```bash
sudo systemctl start stock-insights
sleep 10; curl -s http://127.0.0.1:8000/api/health; echo        # checks the database
sudo journalctl -u stock-insights -n 30 --no-pager
```

Sign in on the website (you stay logged in), check Portfolio, Journal, Watchlist and Alerts, and add then delete a test journal entry.

### B7. Nightly backups (required: Supabase no longer backs you up)

**B7.1 Passwords for unattended use:**

```bash
echo "localhost:5432:stockpilot:stockpilot:THE_PASSWORD" > ~/.pgpass && chmod 600 ~/.pgpass
openssl rand -base64 32 > ~/.backup-passphrase && chmod 600 ~/.backup-passphrase
cat ~/.backup-passphrase       # store this in your password manager too; without it backups are unreadable
```

**B7.2 Off-laptop copies with rclone (Google Drive example):**

```bash
sudo apt -y install rclone
rclone config
```

Answer: `n` (new remote) → name `gdrive` → storage `drive` → client id/secret: Enter (blank) → scope `1` (full access) or `3` (files created by rclone only, recommended) → service account: Enter → advanced config: `n` → **"Use web browser to automatically authenticate?": `n`**. It prints a command like `rclone authorize "drive" "eyJ..."`.
On Windows: `winget install Rclone.Rclone`, open a new PowerShell, run that exact command, sign in to Google in the browser that opens, and copy the token it prints back into the laptop prompt. Shared drive: `n`. Confirm with `y`, then `q` to quit. Test: `rclone mkdir gdrive:stockpilot-backups && rclone lsd gdrive:`.

**B7.3 The backup script:**

```bash
cat > ~/stockpilot-db-backup.sh << 'EOF'
#!/bin/bash
# Nightly encrypted dump of the local StockPilot database, kept 14 days here and copied to Google Drive.
set -euo pipefail
umask 077
DIR="$HOME/db-backups"; mkdir -p "$DIR"
OUT="$DIR/stockinsights-$(date -u +%Y-%m-%d).sql.gz.gpg"
pg_dump "postgresql://stockpilot@localhost:5432/stockpilot" --schema=public --no-owner --no-privileges \
  --exclude-table-data=public.kv_cache \
  | gzip -9 \
  | gpg --batch --yes --pinentry-mode loopback --passphrase-file "$HOME/.backup-passphrase" \
        --symmetric --cipher-algo AES256 -o "$OUT"
test "$(stat -c%s "$OUT")" -gt 1000
ls -1t "$DIR"/stockinsights-*.sql.gz.gpg | tail -n +15 | xargs -r rm --
rclone copy "$DIR" gdrive:stockpilot-backups --max-age 48h
echo "Backed up $(basename "$OUT")"
EOF
chmod +x ~/stockpilot-db-backup.sh
~/stockpilot-db-backup.sh
```

**B7.4 Run it every night at 07:00 UTC (outside US market hours):**

```bash
sudo tee /etc/systemd/system/stockpilot-db-backup.service > /dev/null << EOF
[Unit]
Description=StockPilot nightly database backup
After=postgresql.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$USER
ExecStart=/bin/bash $HOME/stockpilot-db-backup.sh
EOF
sudo tee /etc/systemd/system/stockpilot-db-backup.timer > /dev/null << 'EOF'
[Unit]
Description=Nightly StockPilot database backup

[Timer]
OnCalendar=*-*-* 07:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now stockpilot-db-backup.timer
systemctl list-timers stockpilot-db-backup.timer --no-pager
```

Check it later: `journalctl -u stockpilot-db-backup -n 20 --no-pager` and `rclone ls gdrive:stockpilot-backups`.

**B7.5 Practise a restore** (once now, then every few months), into a scratch database:

```bash
sudo -u postgres psql -c "CREATE DATABASE restore_test OWNER stockpilot"
psql "postgresql://stockpilot@localhost:5432/restore_test" -c "DROP SCHEMA public"
gpg --batch --pinentry-mode loopback --passphrase-file ~/.backup-passphrase -d "$(ls -1t ~/db-backups/*.gpg | head -1)" \
  | gunzip | psql "postgresql://stockpilot@localhost:5432/restore_test" -v ON_ERROR_STOP=1 -q && echo RESTORE OK
psql "postgresql://stockpilot@localhost:5432/restore_test" -Atc "select count(*) from public.closed_options"
sudo -u postgres psql -c "DROP DATABASE restore_test"
```

If that restore stops with `schema "public" does not exist`, run `CREATE SCHEMA public;` in the scratch database instead of the `DROP SCHEMA` line, and restore again.

**Real recovery after a laptop failure:** set up a new laptop with setup_laptop.md, do B1–B2 and B5, download the newest file from Google Drive (`rclone copy gdrive:stockpilot-backups ~/db-backups`), restore it as in B7.5 but into `stockpilot`, then B6. Or restore it into a new free Supabase project (Option A3 with the decrypted file) and point `DATABASE_URL` there.

### B8. Turn off the GitHub backup workflow

It can't reach the laptop and would fail every Sunday. GitHub → **Actions → Database backup → ⋯ → Disable workflow**. Leave the `DATABASE_URL` secret until the old Supabase project is deleted, then delete it too.

### B9. Retire Supabase

After two weeks of good nightly backups: Supabase project → Settings → **Pause project**. Delete it later, after downloading one last backup from it if you want.

---

## Option C: SQLite file on the laptop

The backend uses SQLite automatically when `DATABASE_URL` is empty; that's how local development already runs. [deploy/pg_to_sqlite.py](deploy/pg_to_sqlite.py) builds a new SQLite file with the app's own schema, copies every table from Postgres into it, and restores the audit triggers.

### C1. Copy

Do "Before any option" steps 5 and 6 (stop the server, set `SUPABASE_URL`). The tools from step 4 aren't needed for this option. Then **(laptop)**:

```bash
mkdir -p ~/stockpilot-data && chmod 700 ~/stockpilot-data
cd ~/stock-insights/backend
SOURCE_DATABASE_URL="$SUPABASE_URL" STOCKPILOT_DB_PATH="$HOME/stockpilot-data/stockinsights.db" \
  venv/bin/python ../deploy/pg_to_sqlite.py
```

(The app's own transaction-pooler URL, port 6543, also works here.)

It lists every table with its row count and must end with `Done: .../stockinsights.db`. If it ends with "Check these", nothing has been switched; delete the file and ask for help or use Option B.

### C2. Switch the app

Edit `~/stock-insights/backend/.env`: make `DATABASE_URL=` empty and add a line with the full path (use your username):

```
DATABASE_URL=
STOCKPILOT_DB_PATH=/home/sai/stockpilot-data/stockinsights.db
```

```bash
sudo systemctl start stock-insights
sleep 10; curl -s http://127.0.0.1:8000/api/health; echo
```

Sign in and check Portfolio, Journal and Watchlist as in B6.

### C3. Nightly backups

```bash
sudo apt -y install sqlite3 rclone
```

Set up `~/.backup-passphrase` and rclone exactly as in B7.1 (passphrase only) and B7.2. Then:

```bash
cat > ~/stockpilot-db-backup.sh << 'EOF'
#!/bin/bash
# Nightly encrypted copy of the StockPilot SQLite database, kept 14 days here and copied to Google Drive.
set -euo pipefail
umask 077
DIR="$HOME/db-backups"; mkdir -p "$DIR"
SNAP="$DIR/snapshot.db"
OUT="$DIR/stockinsights-$(date -u +%Y-%m-%d).db.gz.gpg"
rm -f "$SNAP"
sqlite3 "$HOME/stockpilot-data/stockinsights.db" ".backup '$SNAP'"      # consistent copy while the app runs
gzip -9c "$SNAP" | gpg --batch --yes --pinentry-mode loopback --passphrase-file "$HOME/.backup-passphrase" \
  --symmetric --cipher-algo AES256 -o "$OUT"
rm -f "$SNAP"
ls -1t "$DIR"/stockinsights-*.db.gz.gpg | tail -n +15 | xargs -r rm --
rclone copy "$DIR" gdrive:stockpilot-backups --max-age 48h
echo "Backed up $(basename "$OUT")"
EOF
chmod +x ~/stockpilot-db-backup.sh
~/stockpilot-db-backup.sh
```

Schedule it with the same service and timer as B7.4, but delete the `After=postgresql.service` part of that line.

**Restore a SQLite backup:**

```bash
sudo systemctl stop stock-insights
gpg --batch --pinentry-mode loopback --passphrase-file ~/.backup-passphrase -d ~/db-backups/stockinsights-YYYY-MM-DD.db.gz.gpg \
  | gunzip > ~/stockpilot-data/stockinsights.db.new
mv ~/stockpilot-data/stockinsights.db ~/stockpilot-data/stockinsights.db.old
rm -f ~/stockpilot-data/stockinsights.db-wal ~/stockpilot-data/stockinsights.db-shm
mv ~/stockpilot-data/stockinsights.db.new ~/stockpilot-data/stockinsights.db
sudo systemctl start stock-insights
```

### C4. Retire Supabase

As B8 and B9.

**Moving back from SQLite to Postgres later:** there's no ready-made script for that direction. Use the in-app transfer (Holdings → Data tools → **Export data to another login**, then **Import data from another login** on the Postgres-backed server with the same `JWT_SECRET`). It carries holdings, options, closed trades, transactions, journal and watchlist only; everything else (price alerts, trading rules, account cash and ledger entries, theses, watchlist lists and groups, buy zones, saved trade plans, notification history) has to be re-entered by hand. This is the main reason to prefer Option B.

---

## Option D: Neon (another free hosted Postgres), not rehearsed

Neon (neon.tech) offers free Postgres projects. The steps are Option A's, with these differences:
- Create a project with **Postgres 17**, in **AWS US East (N. Virginia)**. Copy the connection string (it contains `sslmode=require`; keep it).
- Restore: Neon's `public` schema already exists, and it has no `service_role`, so remove the schema lines **and** the policy lines:

  ```bash
  sed -e '/^CREATE SCHEMA public;$/d' -e '/^COMMENT ON SCHEMA public IS/d' -e '/^CREATE POLICY /d' \
    ~/stockpilot-dump.sql > ~/stockpilot-dump-neon.sql
  psql "$NEON_URL" -v ON_ERROR_STOP=1 -q -f ~/stockpilot-dump-neon.sql && echo RESTORED
  ```

  Skip `supabase_rls.sql`; it's Supabase-specific.
- Use the same connection string for `DATABASE_URL` and for the GitHub backup secret.
- **Check the free plan's monthly compute limit** on Neon's pricing page first. Neon suspends idle databases to save compute, but StockPilot's scheduler queries every few minutes, so the database rarely sleeps and can use up the free hours before the month ends.

---

## Troubleshooting

| Message | Meaning and fix |
| --- | --- |
| `pg_dump: error: aborting because of server version mismatch` | Your `pg_dump` is older than 17. Install `postgresql-client-17` ("Before any option", step 4). |
| `could not translate host name` / `Network is unreachable` | Use the **pooler** URLs (`...pooler.supabase.com`), not `db.xxxx.supabase.co`, which is IPv6-only. |
| `pg_dump` fails or hangs | Check you used the session pooler URL (port 5432), not the app's transaction pooler (6543). |
| `schema "public" already exists` | You skipped the `DROP SCHEMA public` (Option B) or the `sed` (Options A and D). |
| `role "service_role" does not exist` | Create the placeholder roles (B2) or remove the policy lines (Option D). |
| `password authentication failed` | Wrong password in the URL, or it contains characters such as `@ : / ? #` that must be URL-encoded. Use a letters-and-digits password. |
| `/api/health` returns 503 after switching | The app can't reach the new database: check `DATABASE_URL` in `.env` (no quotes, no spaces) and `sudo journalctl -u stock-insights -n 50`. To roll back, put the old Supabase URL back and restart. |
| Logged out after switching | `JWT_SECRET` changed. Put the old value back from your password manager. |
| Alerts arrive twice | Two servers are running the scheduler against the same database. Stop one. |

**Rolling back** (any option, as long as the Supabase project still exists): put the old Supabase transaction-pooler URL back into `DATABASE_URL`, `sudo systemctl restart stock-insights`. Anything entered on the new database since the switch is not in Supabase; re-enter it or export it first with the in-app transfer.
