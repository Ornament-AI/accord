# Accord operations

Deployment profiles, bring-up, readiness contract, backup/restore, and release
rehearsal for Accord. Commands below were executed against Docker Compose on
2026-07-18 (Docker 29.4.0 / Compose v5.1.2) during a local deployment rehearsal.

## Deploy profiles

### A — Self-hosted Compose (Postgres + MinIO)

Use `deploy/docker-compose.yml` for a single-host stack:

| Service | Role |
|---|---|
| `postgres` | Postgres 18; volume `pgdata` at `/var/lib/postgresql` |
| `minio` + `minio-init` | S3-compatible object storage; bucket `accord-artifacts` |
| `migrations` | One-shot `alembic upgrade head` (ADR migrator role) |
| `api` | FastAPI backend image |
| `worker` | `python worker.py` durable-job loop |
| `web` | nginx + SPA; publishes `127.0.0.1:${ACCORD_WEB_PORT:-8085}` |

First boot runs `deploy/object-storage/postgres-init-roles.sh`, which applies
`backend/scripts/create_roles.sql` and sets passwords for `accord_migrator`,
`accord_app`, and `accord_worker` (ADR-0001). Compose defaults:

- `MIGRATIONS_DATABASE_URL` → `accord_migrator`
- `DATABASE_URL` (api) → `accord_app`
- worker `DATABASE_URL` → `accord_worker` (override with `WORKER_DATABASE_URL`)

### B — Managed Postgres + S3

Same application images (`api`, `worker`, `web`), but:

1. Point `DATABASE_URL` / `MIGRATIONS_DATABASE_URL` / worker DSN at managed
   Postgres after applying `backend/scripts/create_roles.sql` once per cluster.
2. Set `OBJECT_STORAGE_*` to the cloud S3 endpoint, bucket, and IAM keys
   (omit MinIO / `minio-init`).
3. Run migrations as a one-shot job (`alembic upgrade head`) before rolling
   `api` / `worker`.
4. Terminate TLS at your load balancer; keep nginx `web` as the SPA + `/api/`
   reverse-proxy, or swap for an equivalent edge proxy.

Ops secrets still follow ADR-0003 names (`WORKOS_*`, `SESSION_SECRET_KEY`, etc.).

## Bring-up (self-hosted Compose)

From the repo root:

```bash
# 1) Env (gitignored). Copy template and fill required secrets.
cp deploy/.env.example deploy/.env
# Required at minimum: ACCORD_DB_PASSWORD, WORKOS_CLIENT_ID, WORKOS_API_KEY,
# WORKOS_WEBHOOK_SECRET, SESSION_SECRET_KEY.
# Leave DATABASE_URL / MIGRATIONS_DATABASE_URL empty to use ADR role defaults.

# 2) Validate compose interpolation
docker compose -f deploy/docker-compose.yml --env-file deploy/.env config -q

# 3) Build images + start stack (multi-stage backend + web; migrations one-shot)
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

Teardown (destroys volumes — rehearsal only):

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env down -v
```

### Smoke checks after bring-up

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env ps -a
# postgres healthy; minio healthy; migrations Exited (0);
# minio-init Exited (0); api healthy; worker Up; web Up on 127.0.0.1:8085

curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8085/api/healthz
# {"status":"ok"} / HTTP 200

curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8085/api/readyz
# see contract below / HTTP 200

curl -sS -D - http://127.0.0.1:8085/ -o /tmp/accord-index.html | head
# SPA index.html (title Accord, <div id="root">)

docker logs accord-worker-1 2>&1 | tail
# worker_entrypoint_starting / worker_started

docker compose -f deploy/docker-compose.yml --env-file deploy/.env run --rm --no-deps \
  -e MIGRATIONS_DATABASE_URL -e DATABASE_URL \
  migrations alembic current
# expect: <revision> (head)
```

Confirm the MinIO bucket exists (init logs or `mc ls`).

## `/api/readyz` contract

`GET /api/healthz` → always `{"status":"ok"}` when the process is up (liveness).

`GET /api/readyz` → readiness with component detail:

| Field | Meaning |
|---|---|
| `status` | `ok` (HTTP 200) or `degraded` (HTTP 503) |
| `database` | `ok` or hard-fail 503 `"Database connection is not ready."` |
| `auth` | `ok` or hard-fail 503 `"Auth provider is not ready."` |
| `jobs` | `ok` / `unavailable` (jobs table probe) |
| `storage` | `ok` / `unconfigured` / `unavailable` |
| `reports` | `ok` / `empty` / `missing` |

Degraded rule: any component value other than `ok` or `unconfigured` yields
HTTP 503 with `"status":"degraded"`. Unconfigured storage alone is still ready.

**Verbatim ready response from this rehearsal (HTTP 200):**

```json
{"status":"ok","database":"ok","auth":"ok","jobs":"ok","storage":"ok","reports":"ok"}
```

Compose marks `api` healthy only when `/api/readyz` succeeds (not merely
`/api/healthz`), so `web` will not start until the API is ready.

## Backup / PITR / restore

### Logical backup + scratch restore (Compose)

Helper: [`scripts/backup-restore.sh`](../scripts/backup-restore.sh)
(parameterized by container name, database name, user, password).

Rehearsal (row counts before/after = **3** on `rehearsal_probe`):

```bash
export ACCORD_DB_PASSWORD='…'   # same as deploy/.env

# Optional: seed a countable table for rehearsal
docker exec -i -e PGPASSWORD="$ACCORD_DB_PASSWORD" accord-postgres-1 \
  psql -U accord -d accord -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS rehearsal_probe (
  id serial PRIMARY KEY,
  label text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
TRUNCATE rehearsal_probe;
INSERT INTO rehearsal_probe (label) VALUES ('alpha'), ('beta'), ('gamma');
SQL

./scripts/backup-restore.sh verify-counts \
  --container accord-postgres-1 --db accord --user accord \
  --password "$ACCORD_DB_PASSWORD" --verify-table rehearsal_probe
# [verify] … row_count=3

./scripts/backup-restore.sh backup \
  --container accord-postgres-1 --db accord --user accord \
  --password "$ACCORD_DB_PASSWORD" --out /tmp/accord-rehearsal.dump \
  --verify-table rehearsal_probe

./scripts/backup-restore.sh restore-scratch \
  --container accord-postgres-1 --db accord --user accord \
  --password "$ACCORD_DB_PASSWORD" --dump /tmp/accord-rehearsal.dump \
  --scratch accord_restore_scratch --verify-table rehearsal_probe
# row_count_before=3 → row_count_after=3
```

Production restore into the live database (not scratch) should:

1. Stop `api` / `worker` (and pause writers).
2. Restore with `pg_restore` (or plain SQL) into a new database, cut DNS/DSN
   over, or restore in place only during a declared maintenance window.
3. Re-run `alembic current` and the smoke-test checklist below.
4. Use backup credentials that are **not** `accord_app` (cluster superuser /
   dedicated backup role).

### PITR (managed Postgres)

For profile B, enable provider continuous backups / WAL archiving (e.g. RDS
PITR, Cloud SQL point-in-time recovery, Neon branching). Practice:

1. Note a restore target timestamp **before** a known bad write.
2. Restore a new instance to that timestamp.
3. Re-point `DATABASE_URL` / migrator DSN; run smoke checks.
4. Keep object-storage versioning or cross-region replication if artifacts must
   rewind with the database.

Compose MinIO is **not** PITR; use volume snapshots plus the logical dump above.

### Object storage persistence

Named volume `minio-data` survives `docker compose restart`. Rehearsal:

```bash
# put
echo 'accord-rehearsal-object-v1' > /tmp/accord-minio-probe.txt
docker run --rm --network accord_backend-net --entrypoint /bin/sh \
  -e MC_CONFIG_DIR=/tmp/mc -e HOME=/tmp \
  -v /tmp/accord-minio-probe.txt:/probe.txt:ro \
  minio/mc:RELEASE.2025-04-16T18-13-26Z \
  -c 'mc alias set a http://minio:9000 minioadmin minioadmin && mc cp /probe.txt a/accord-artifacts/rehearsal/probe.txt'

docker compose -f deploy/docker-compose.yml --env-file deploy/.env restart

# get (after /api/readyz is 200 again)
docker run --rm --network accord_backend-net --entrypoint /bin/sh \
  -e MC_CONFIG_DIR=/tmp/mc -e HOME=/tmp \
  minio/mc:RELEASE.2025-04-16T18-13-26Z \
  -c 'mc alias set a http://minio:9000 minioadmin minioadmin && mc cat a/accord-artifacts/rehearsal/probe.txt'
# accord-rehearsal-object-v1
```

`docker compose … down -v` deletes `pgdata` and `minio-data`.

## Destructive migrations (legacy master-data removal)

Two migrations irreversibly discard legacy master data:

- `f9c2b4e6a813` drops `employee_groups` and
  `employee_posting_versions.employee_group_id`.
- `a0d4f8b2c615` drops `payroll_units` and
  `employee_posting_versions.payroll_unit_id` (originally `NOT NULL`, i.e.
  real posting assignments).

Both refuse to run when legacy rows or references exist, reporting exact
counts. To proceed on a deployment that still has legacy data:

1. Take a verified backup (see "Backup / PITR / restore") and confirm a
   scratch restore succeeds.
2. If the legacy assignments are still needed for reporting, export them
   first (`COPY employee_groups TO …`, `COPY payroll_units TO …`, and the
   referencing `employee_posting_versions` columns).
3. Decide explicitly that the data may be discarded, then re-run with
   `ACCORD_ALLOW_LEGACY_DROP=1` in the migration environment. The discarded
   row counts are logged.

Rollback is forward-only once data existed: `a0d4f8b2c615` refuses to
downgrade while `employee_posting_versions` has rows, because unit
assignments cannot be reinvented — restore the pre-migration backup instead.
With no posting rows, downgrade faithfully restores the original schema,
including `payroll_unit_id NOT NULL`.

## Release / rollback (`.github/workflows/deploy.yml`)

Tag-triggered pipeline (`push` of `v*`):

1. **build-and-push-backend** / **build-and-push-web** — build and push
   `ghcr.io/ornament-ai/accord/{backend,web}` with tags:
   - `${{ github.ref_name }}` (e.g. `v1.2.3`)
   - `sha-<full-git-sha>`
2. **migrations-release-upgrade** — on a scratch Postgres, upgrade previous `v*`
   tag → current tag with Alembic, then `alembic check` and head match.
   First release (no prior `v*`) skips replay; images still publish.
3. **deployment-summary** — writes image/tag/sha to the job summary.

### Release steps (operator)

1. Ensure CI is green on the commit to ship.
2. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. Wait for Deploy workflow success (images + migration replay).
4. On the host, set `ACCORD_TAG=sha-<full-sha>` in `deploy/.env`.
5. Deploy the exact release commit from a trusted checkout:

   ```bash
   MSIDC_SSH_TARGET=msidcadmin@msidcacct ./scripts/deploy.sh <full-sha>
   ```

   The script syncs only the deploy bundle (never `.env`), then `setup.sh`
   validates the production/WorkOS settings, pulls immutable images, starts
   with `--no-build`, and runs VM-local smoke proof.
6. Route `accord.innovastra.app` through the MSIDC Cloudflare Tunnel to
   `http://localhost:8085`, then run the public smoke checks.

On a first shared-host install, `setup.sh` refuses to proceed when legacy
`deploy_pgdata` or `deploy_minio-data` volumes exist but Accord's isolated
volumes do not. Migrate them if they belong to an earlier Accord install. Set
`ACCORD_CONFIRMED_FRESH_INSTALL=true` on the one deploy command only after
proving they belong to another application; do not store this acknowledgment
in `.env`. The MSIDC first install was audited on that basis.

### Rollback

1. Identify the previous known-good full Git SHA and review migration
   compatibility before changing the running app.
2. Set `ACCORD_TAG=sha-<previous-full-sha>` in the host `.env`, then run
   `./scripts/deploy.sh <previous-full-sha>` from a trusted checkout. This keeps
   rollback on the same pull, no-build, revision-label, and smoke-proof path.
3. **Do not** auto-downgrade Alembic. If the new release’s migrations already
   applied and are incompatible with the old app, restore the database from
   backup/PITR to a pre-migration point, then start the old images — or forward
   fix with a new tag.
4. Re-run smoke checks (`/api/readyz`, web root, worker logs).

## Smoke-test checklist

- [ ] `docker compose -f deploy/docker-compose.yml --env-file deploy/.env config -q`
- [ ] `postgres` healthy; `minio` healthy; `minio-init` exited 0; bucket present
- [ ] `migrations` exited 0; `alembic current` shows `(head)`
- [ ] `GET /api/healthz` → 200 `{"status":"ok"}`
- [ ] `GET /api/readyz` → 200 with `database`/`auth`/`jobs` ok; `storage`
      ok or unconfigured; `reports` ok (non-empty)
- [ ] `GET /` on web → SPA `index.html` (Accord title / `#root`)
- [ ] `worker` container Up; logs include `worker_started`
- [ ] Logical backup + scratch restore row counts match
      (`scripts/backup-restore.sh`)
- [ ] Object put → `compose restart` → object get succeeds (volume intact)

## Compose fixes validated in rehearsal

These were required for a clean bring-up (see `deploy/docker-compose.yml`):

1. **Postgres 18 volume** — mount `pgdata` at `/var/lib/postgresql` (not
   `…/data`); the 18+ image rejects the old path.
2. **minio-init config dir** — set `MC_CONFIG_DIR=/tmp/mc` and `HOME=/tmp` so
   `mc` can write under `cap_drop: ALL`.
3. **ADR role bootstrap** — `postgres-init-roles.sh` + DSN defaults to
   `accord_migrator` / `accord_app` / `accord_worker` so Alembic RLS policies
   and runtime roles succeed on first boot.
