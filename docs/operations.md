# Accord operations

This page is the operator's runbook. It covers the deploy profiles, first
bring-up, the readiness contract, backup and restore, destructive
migrations, and the release and rollback path. The commands below were
executed against Docker Compose on 2026-07-18 (Docker 29.4.0 / Compose
v5.1.2) during a local deployment rehearsal.

For local development (not deployment), use `scripts/start.sh`,
`scripts/stop.sh`, and `scripts/status.sh` instead; the README documents
that flow.

## Deploy profiles

### A — Self-hosted Compose (Postgres + MinIO)

Use `deploy/docker-compose.yml` for a single-host stack. It runs these
services:

| Service | Role |
|---|---|
| `postgres` | Postgres 18 (`postgres:18.4-alpine`); volume `pgdata` mounted at `/var/lib/postgresql` |
| `minio` + `minio-init` | S3-compatible object storage; bucket `accord-artifacts` |
| `migrations` | One-shot `alembic upgrade head` (runs as the ADR migrator role) |
| `api` | FastAPI backend image |
| `worker` | `python worker.py` durable-job loop |
| `web` | nginx + SPA; publishes `127.0.0.1:${ACCORD_WEB_PORT:-8085}` |

On first boot, Postgres runs `deploy/object-storage/postgres-init-roles.sh`.
That script applies `backend/scripts/create_roles.sql` and sets passwords
for `accord_migrator`, `accord_app`, and `accord_worker` (ADR-0001). The
Compose defaults wire each service to the right role:

- `MIGRATIONS_DATABASE_URL` → `accord_migrator`
- `DATABASE_URL` (api) → `accord_app`
- worker `DATABASE_URL` → `accord_worker` (override with
  `WORKER_DATABASE_URL`)

### B — Managed Postgres + S3

Use the same application images (`api`, `worker`, `web`), but:

1. Point `DATABASE_URL` / `MIGRATIONS_DATABASE_URL` / the worker DSN at
   managed Postgres, after applying `backend/scripts/create_roles.sql` once
   per cluster.
2. Set the `OBJECT_STORAGE_*` variables to the cloud S3 endpoint, bucket,
   and IAM keys. Omit the `minio` / `minio-init` services.
3. Run migrations as a one-shot job (`alembic upgrade head`) before rolling
   `api` / `worker`.
4. Terminate TLS at your load balancer. Keep the nginx `web` service as the
   SPA plus `/api/` reverse proxy, or swap in an equivalent edge proxy.

Ops secrets still follow the ADR-0003 names (`WORKOS_*`,
`SESSION_SECRET_KEY`, and so on).

## Bring-up (self-hosted Compose)

From the repo root:

```bash
# 1) Env (gitignored). Copy the template and fill the required secrets.
cp deploy/.env.example deploy/.env
# Required at minimum: ACCORD_DB_PASSWORD, WORKOS_CLIENT_ID, WORKOS_API_KEY,
# WORKOS_WEBHOOK_SECRET, SESSION_SECRET_KEY.
# Leave DATABASE_URL / MIGRATIONS_DATABASE_URL empty to use the ADR role defaults.

# 2) Validate compose interpolation
docker compose -f deploy/docker-compose.yml --env-file deploy/.env config -q

# 3) Build images + start the stack (multi-stage backend + web; migrations one-shot)
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

Confirm the MinIO bucket exists (init logs or `mc ls`). You can also run
`./scripts/smoke-test.sh`, which checks `/api/healthz`, `/api/readyz`, the
web root, and the running Compose services in one pass.

## `/api/readyz` contract

`GET /api/healthz` → always `{"status":"ok"}` when the process is up. This
is the liveness probe.

`GET /api/readyz` → readiness with component detail
(`backend/app/api/routes/health.py`):

| Field | Meaning |
|---|---|
| `status` | `ok` (HTTP 200) or `degraded` (HTTP 503) |
| `database` | `ok` or hard-fail 503 `"Database connection is not ready."` |
| `auth` | `ok` or hard-fail 503 `"Auth provider is not ready."` |
| `jobs` | `ok` / `unavailable` (jobs table probe) |
| `storage` | `ok` / `unconfigured` / `unavailable` |
| `reports` | `ok` / `empty` / `missing` |

Degraded rule: any component value other than `ok` or `unconfigured` yields
HTTP 503 with `"status":"degraded"`. Unconfigured storage alone is still
ready.

**Verbatim ready response from this rehearsal (HTTP 200):**

```json
{"status":"ok","database":"ok","auth":"ok","jobs":"ok","storage":"ok","reports":"ok"}
```

Compose marks `api` healthy only when `/api/readyz` succeeds (not merely
`/api/healthz`), so `web` will not start until the API is ready.

## Backup / PITR / restore

### Logical backup + scratch restore (Compose)

Helper: [`scripts/backup-restore.sh`](../scripts/backup-restore.sh). Its
subcommands are `backup`, `restore-scratch`, and `verify-counts`, each
parameterized by container name, database name, user, and password.

Rehearsal (row counts before/after = **3** on `rehearsal_probe`):

```bash
export ACCORD_DB_PASSWORD='…'   # same as deploy/.env

# Optional: seed a countable table for the rehearsal
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

A production restore into the live database (not scratch) should:

1. Stop `api` / `worker` (and pause writers).
2. Restore with `pg_restore` (or plain SQL) into a new database, then cut
   DNS/DSN over. Restore in place only during a declared maintenance window.
3. Re-run `alembic current` and the smoke-test checklist below.
4. Use backup credentials that are **not** `accord_app` (cluster superuser
   or a dedicated backup role).

### PITR (managed Postgres)

PITR means point-in-time recovery: restoring the database to an exact past
moment. For profile B, enable the provider's continuous backups / WAL
archiving (for example RDS PITR, Cloud SQL point-in-time recovery, Neon
branching). Practice:

1. Note a restore target timestamp **before** a known bad write.
2. Restore a new instance to that timestamp.
3. Re-point `DATABASE_URL` / the migrator DSN; run the smoke checks.
4. Keep object-storage versioning or cross-region replication if artifacts
   must rewind with the database.

Compose MinIO is **not** PITR. Release updates therefore stop MinIO together
with the application writers and create one SHA-bound recovery pair: the
PostgreSQL custom dump and the matching `accord_minio-data` volume archive.
Both checksum files and both readback listings must verify before migrations
can start.

### Object storage persistence

The named volume `minio-data` survives `docker compose restart`. Rehearsal:

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

Two migrations discard legacy master data, and the loss cannot be undone:

- `f9c2b4e6a813` drops `employee_groups` and
  `employee_posting_versions.employee_group_id`.
- `a0d4f8b2c615` drops `payroll_units` and
  `employee_posting_versions.payroll_unit_id` (originally `NOT NULL`, that
  is, real posting assignments).

Both refuse to run when legacy rows or references exist, and they report the
exact counts. To proceed on a deployment that still has legacy data:

1. Take a verified backup (see "Backup / PITR / restore") and confirm that a
   scratch restore succeeds.
2. If the legacy assignments are still needed for reporting, export them
   first (`COPY employee_groups TO …`, `COPY payroll_units TO …`, and the
   referencing `employee_posting_versions` columns).
3. Decide explicitly that the data may be discarded. Then re-run with
   `ACCORD_ALLOW_LEGACY_DROP=1` in the migration environment. The discarded
   row counts are logged.

Rollback is forward-only once data existed: `a0d4f8b2c615` refuses to
downgrade while `employee_posting_versions` has rows, because unit
assignments cannot be reinvented — restore the pre-migration backup instead.
With no posting rows, the downgrade faithfully restores the original schema,
including `payroll_unit_id NOT NULL`.

## Release / rollback (`.github/workflows/deploy.yml`)

After CI succeeds on `main`, the release workflow builds the backend and web
images for that exact commit. It records their registry digests, packages the
self-contained Compose deployment, validates the shared on-prem contract,
and signs its checksums with the protected `onprem-release` environment key.
The four immutable assets are stored in the durable GitHub Release
`onprem-sha-<full-sha>`.

The protected `onprem-release` environment stores `ONPREM_DEPLOYED_SHA`, which
is authoritative deployment evidence for migration rehearsal. Publication
fails closed when this value is absent, invalid, or not an ancestor of the
candidate. A successful operator deployment updates it only after all live
proofs pass, so skipped published releases are never mistaken for the schema
currently on the VM.

Publishing a release never changes the VM. A human must explicitly run the
operator command below.

### One-time host installation

Install the fixed root-owned wrapper and narrow sudo rule once:

```bash
MSIDC_SSH_TARGET=msidc ./scripts/install-release-wrapper.sh
```

This is the last routine password prompt. It grants password-free sudo only to
`/usr/local/bin/deploy-accord`; the wrapper accepts only a full SHA and a
strictly shaped staging directory, then authenticates all release assets before
running bundled code. Re-run the installer only when the reviewed wrapper
itself changes. The installer snapshots the wrapper and environment validator
from authenticated canonical `Ornament-AI/accord` main, requires successful CI
for that exact SHA, and removes obsolete persisted GHCR keys while rejecting
unsupported process-control variables before the environment becomes
root-owned.

Routine releases also need a GitHub Packages token with `read:packages`. Keep
it in a secret manager and expose it as `ACCORD_GHCR_READ_TOKEN`, or install it
once in the macOS Keychain service `ornament-ai-accord-ghcr-read` under the
GitHub username used by `gh`. The scripts never prompt for it, store it in the
repository, copy it into `.env`, or write Docker credentials outside a temporary
directory. Before staging, they prove that it can read both exact image digests
from the signed manifest.

Before the first cutover, run the manual `Backfill On-Prem Rollback Release`
workflow on `main` and verify that
`onprem-sha-8cc2f95d00d35ab6eb9d4ace31b2f605af10d10d` contains all four signed
assets. This one-time backfill preserves the currently deployed release as a
verified rollback target. Its backend and web digests are fixed from the
read-only live-container evidence recorded on 2026-08-25. The workflow also
verifies the retained, checksum-pinned Docker build records from successful
Deploy run `32671105169`, then pulls the immutable references and verifies their
OCI revision labels before signing. It never resolves the mutable `sha-...`
tags as signing inputs.

### Release steps (operator)

1. Confirm CI and the On-Prem Release workflow are green for the same full SHA.
2. Deploy that published SHA:

   ```bash
   MSIDC_SSH_TARGET=msidc ./scripts/deploy.sh <full-sha>
   ```

   The command downloads the four durable assets, verifies their Ed25519
   signature and checksums locally, stages them, and invokes only the fixed VM
   wrapper. It streams the operator's GitHub Packages credential over standard
   input for this invocation only; the wrapper uses a temporary Docker config
   and never writes the credential into `.env` or the VM user's home. The
   wrapper repeats verification, preserves the root-owned `.env`,
   quiesces API, worker, and web, creates and verifies SHA-bound PostgreSQL and
   MinIO-volume backups, atomically promotes the release, then proves image digests,
   `APP_VERSION`, migrations, health, readiness, auth, worker startup, and the
   public endpoint.
   After those live proofs succeed, the command records the deployed full SHA
   in the protected `onprem-release` environment for the next migration
   rehearsal. Failure to update that evidence is reported as an incomplete
   deployment operation even though the live proof already succeeded. The
   root deployment lock remains held through this evidence write and is
   released only after the wrapper receives the matching nonce-bound receipt,
   so concurrent operators cannot overwrite the live SHA with stale evidence.

The normal signed updater is deliberately not an empty-host bootstrapper: it
requires the existing root-owned `.env`, live Accord stack, PostgreSQL volume,
and MinIO volume so it can take a paired backup. Use the separate, one-time
bootstrap only on a host with no Accord containers, current volumes, or legacy
`deploy_*` volumes:

```bash
ACCORD_BOOTSTRAP_ENV_FILE=/absolute/operator-owned/accord.env \
  MSIDC_SSH_TARGET=msidc \
  ./scripts/bootstrap-release-host.sh <current-main-full-sha>
```

The environment file must be a non-symlink owned by the operator with mode
`0600`. The bootstrap authenticates the signed release before asking for sudo,
then refuses a non-empty host. It installs the fixed wrapper and root-only
environment, records a one-shot fresh-host marker, and uses the same digest,
version, migration, auth, worker, readiness, and public proofs as updates. An
empty host has no user data to back up; the wrapper records SHA-bound bootstrap
evidence instead. After first success, all releases use `scripts/deploy.sh` and
the paired PostgreSQL and MinIO backup path. Neither path accepts the legacy
`ACCORD_CONFIRMED_FRESH_INSTALL` bypass.

### Rollback

1. Identify the previous known-good full Git SHA. Review migration
   compatibility before changing the running app.
2. Run `./scripts/deploy.sh <previous-full-sha>`. The previous SHA must have a
   signed durable `onprem-sha-<sha>` release; rollback uses the same verified
   installer and proof path as forward deployment.
3. **Do not** auto-downgrade Alembic. If the new release's migrations
   already applied and are incompatible with the old app, keep API, worker,
   web, and MinIO stopped. Verify both checksum files in the SHA-bound release
   evidence, then restore the PostgreSQL dump and its matching
   `.minio.tar.gz` archive to `accord_minio-data` as one recovery point before
   starting the old images. Never restore only one member of the pair. Use a
   declared maintenance window and root-only host access for this recovery,
   or forward fix with a new signed release.
4. Re-run the smoke checks (`/api/readyz`, web root, worker logs).

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
2. **minio-init config dir** — set `MC_CONFIG_DIR=/tmp/mc` and `HOME=/tmp`
   so `mc` can write its config under `cap_drop: ALL`.
3. **ADR role bootstrap** — `postgres-init-roles.sh` plus DSN defaults to
   `accord_migrator` / `accord_app` / `accord_worker`, so the Alembic RLS
   policies and the runtime roles succeed on first boot.
