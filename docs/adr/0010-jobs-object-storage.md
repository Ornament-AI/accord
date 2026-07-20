# ADR 0010: Durable jobs queue and object storage for export artifacts

- **Status:** Accepted
- **Date:** 2026-07-17
- **Deciders:** Accord platform architecture
- **Related:** [ADR 0008](0008-command-workflow-idempotency.md) (command handlers enqueue work), [ADR 0009](0009-audit-outbox.md) (`artifact.download` audit), [ADR 0001](0001-tenancy-rls-database-roles.md) (org GUC / RLS), [docs/report-specs/report-catalog.md](../report-specs/report-catalog.md), [payroll-domain.md](../payroll-domain.md)

---

## Context

Accord generates payroll export artifacts: bank files, statutory reports, payslips, and other catalogued outputs ([report-catalog.md](../report-specs/report-catalog.md)). They are produced after workflow commands such as `post` ([ADR 0008](0008-command-workflow-idempotency.md)). Generation is CPU- and I/O-bound. It must survive API restarts, and it must stay organization-scoped under RLS.

Payroll downloads are sensitive, and compliance rules apply to them. Every successful download must produce an append-only `audit_events` row with command `artifact.download` ([ADR 0009](0009-audit-outbox.md)). If we hand clients raw storage URLs, they can skip the app’s authz checks and that audit row.

The platform also needs background work: it must generate reports, purge expired artifacts, reconcile orphans, and reap stale leases. Redis + Celery would add a second durability and tenancy story. PostgreSQL already owns the transactional truth for runs, audit, and outbox.

This ADR decides four things: (1) a durable PostgreSQL job queue (not Redis/Celery); (2) S3-compatible object storage with opaque keys and checksums; (3) **backend-streamed downloads** as the primary model (not presigned); (4) a DB-first consistency protocol for `export_artifacts`.

---

## Decision

### 1. Durable PostgreSQL `jobs` queue (not Redis/Celery)

Background work is rows in `jobs`. Workers claim with `SELECT … FOR UPDATE SKIP LOCKED`. They hold a time-bounded lease, heartbeat while running, and move through an explicit status set. Redis, Celery, RQ, Sidekiq, and equivalent brokers are **out of scope** for v1. PostgreSQL is the sole queue durability store.

#### Job statuses (closed set)

| Status | Meaning |
| --- | --- |
| `queued` | Eligible when `available_at <= now()`. |
| `running` | Claimed; lease must be heartbeated. |
| `succeeded` | Terminal success; `result` may hold a small JSON summary. |
| `failed` | Transient failure; may re-queue with backoff if attempts remain. |
| `dead_letter` | Terminal after `max_attempts` exhausted (or non-retryable error). |
| `cancelled` | Terminal; cooperative cancel completed or applied before claim. |

`cancelled` is allowed. Workers treat `cancel_requested = true` as cooperative: stop at a safe checkpoint, then set `status = cancelled`.

#### Table: `jobs`

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | `uuid` PK | Stable job id; referenced by `export_artifacts.job_id` and audit metadata. |
| `organization_id` | `uuid` NOT NULL | Tenant scope; RLS via `app.current_org_id`. |
| `job_type` | `text` NOT NULL | Handler key, e.g. `export.generate`, `storage.reconcile_orphans`, `storage.purge_expired`, `jobs.reap_leases`. |
| `status` | `text` NOT NULL | `queued` \| `running` \| `succeeded` \| `failed` \| `dead_letter` \| `cancelled`. |
| `payload` | `jsonb` NOT NULL DEFAULT `'{}'` | Input args (ids, report_type, template_version). No secrets. |
| `result` | `jsonb` NULL | Small success summary (artifact id, checksum, size). Not bulk bytes. |
| `dedupe_key` | `text` NULL | Org-scoped dedupe token for in-flight uniqueness. |
| `attempt_count` | `int` NOT NULL DEFAULT `0` | Claim/start attempts so far. |
| `max_attempts` | `int` NOT NULL DEFAULT `5` | Cap before `dead_letter`. |
| `available_at` | `timestamptz` NOT NULL DEFAULT `now()` | Not claimable before this instant (backoff/delay). |
| `lease_owner` | `text` NULL | Worker instance id holding the lease. |
| `lease_expires_at` | `timestamptz` NULL | Lease deadline; reaper requeues if expired while `running`. |
| `heartbeat_at` | `timestamptz` NULL | Last successful heartbeat from lease owner. |
| `cancel_requested` | `boolean` NOT NULL DEFAULT `false` | Cooperative cancel flag set by API/admin. |
| `created_at` | `timestamptz` NOT NULL DEFAULT `now()` | Enqueue time. |
| `started_at` | `timestamptz` NULL | Transition to `running` for current attempt. |
| `finished_at` | `timestamptz` NULL | Terminal time (`succeeded` / `dead_letter` / `cancelled`). |
| `last_error` | `text` NULL | Truncated error from latest failure. |
| `created_by` | `uuid` NULL | Acting user when enqueued interactively; NULL for system. |

**RLS:** `organization_id = current_setting('app.current_org_id')::uuid`, fail closed when unset ([ADR 0001](0001-tenancy-rls-database-roles.md)). Cross-org maintenance jobs use a privileged role, not the normal app role.

**Org-scoped dedupe unique partial index** (at most one in-flight job per key when present):

```sql
CREATE UNIQUE INDEX jobs_org_type_dedupe_inflight_uidx
  ON jobs (organization_id, job_type, dedupe_key)
  WHERE dedupe_key IS NOT NULL
    AND status IN ('queued', 'running');
```

Prefer to insert the job in the **same transaction** as the commanding mutation (e.g. `post` → `export.generate`), per [ADR 0008](0008-command-workflow-idempotency.md). If the enqueue is deferred, use the outbox ([ADR 0009](0009-audit-outbox.md)).

---

### 2. Claim, lease, heartbeat, backoff, cancel

#### Claim: `FOR UPDATE SKIP LOCKED`

```sql
BEGIN;
SET LOCAL app.current_org_id = '<org uuid>';  -- or privileged cross-org claim, then set per job

WITH candidate AS (
  SELECT id
  FROM jobs
  WHERE status = 'queued'
    AND available_at <= now()
    AND cancel_requested = false
  ORDER BY available_at ASC, created_at ASC
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
UPDATE jobs AS j
SET status = 'running',
    attempt_count = j.attempt_count + 1,
    lease_owner = :worker_id,
    lease_expires_at = now() + interval '60 seconds',
    heartbeat_at = now(),
    started_at = now(),
    last_error = NULL
FROM candidate c
WHERE j.id = c.id
RETURNING j.*;

COMMIT;
```

After any cross-org claim, the worker **must** `SET LOCAL app.current_org_id` to the claimed row’s `organization_id`. That applies to every later job transaction: the handler, artifact writes, and audit.

#### Lease and heartbeat

Default lease: **60s** (configurable per `job_type`). While `running`, extend the lease on a cadence under the window (e.g. every 20s):

```sql
UPDATE jobs
SET heartbeat_at = now(),
    lease_expires_at = now() + interval '60 seconds'
WHERE id = :job_id
  AND status = 'running'
  AND lease_owner = :worker_id
  AND cancel_requested = false;
```

A zero-row heartbeat means the cancel flag flipped. The worker stops at a safe point and sets `cancelled`.

#### Exponential backoff then `dead_letter`

On a retryable failure: record `last_error`. If `attempt_count < max_attempts`, set `status = queued`, clear the lease fields, and set  
`available_at = now() + (interval '1 second' * (2 ^ least(attempt_count, 8)))`  
(exponential backoff with a cap, optional jitter). If attempts are exhausted, set `status = dead_letter` and `finished_at = now()`. Non-retryable errors (invalid payload, missing posted run, unknown `report_type`) go straight to `dead_letter`.

#### Cooperative cancel

- `queued` + `cancel_requested` → `cancelled` right away (the claimer skips these rows).
- `running` + cancel → observed on heartbeat/checkpoints; no new side effects; then `cancelled`.
- Terminal jobs ignore cancel.

---

### 3. Worker process model

| Concern | Decision |
| --- | --- |
| Image | **Same backend Docker image** as the API. |
| Entrypoint | Different entrypoint/command: the API runs `uvicorn app.main:app`; the worker runs `python worker.py` (`backend/worker.py`). |
| Org GUC | Every job txn: `SET LOCAL app.current_org_id` to the claimed org before tenant writes. |
| Shutdown | On `SIGTERM`: stop claiming; drain in-flight up to grace; exit (leases expire → reaper). |
| Lease reaper | `running` with `lease_expires_at < now()` → requeue (`queued`, clear lease) or `dead_letter` if attempts exhausted. |

```sql
UPDATE jobs
SET status = 'queued',
    lease_owner = NULL,
    lease_expires_at = NULL,
    heartbeat_at = NULL,
    available_at = now()
WHERE status = 'running'
  AND lease_expires_at < now()
  AND attempt_count < max_attempts;
```

---

### 4. S3-compatible object storage

| Environment | Backend |
| --- | --- |
| Local / CI | **MinIO** (S3 API). |
| Cloud | Managed **S3** (or API-compatible equivalent). |

**Object key (normative):** `{organization_id}/{object_uuid}`

Keys are **opaque**. No employee names, account numbers, period labels, report titles, or other readable business data may appear in the path. The org prefix helps lifecycle ops, but **DB + RLS remain authoritative** for authz. On finalize, record the **SHA-256**, size, and etag/version on `export_artifacts`. The bucket is private. Only the app’s own credentials can reach it.

---

### 5. Primary download model: backend-streamed (not presigned)

**Primary model:** the API checks the caller’s rights, opens the object with server credentials, and **streams** the bytes over the authenticated Accord HTTPS session.

**Justification:**

1. **Payroll sensitivity** — bank files, payslips, and statutory extracts must not be reachable through URLs that can be passed around. Such URLs can outlive a session or leak via logs and referrers.
2. **Per-request authorization** — each download re-checks org membership, capabilities, the artifact’s `retention_state` / `status`, and run visibility.
3. **Reliable audit** — the stream handler inserts `audit_events` with `command = 'artifact.download'` ([ADR 0009](0009-audit-outbox.md)), with `entity_type = 'export_artifact'`, actor, request id, and metadata. A presigned GET to storage **bypasses** this path.

**Tradeoff vs presigned:**

| | Backend-streamed (primary) | Presigned (not primary) |
| --- | --- | --- |
| Authz | Every request hits Accord | Only at URL mint time |
| Audit | Natural `artifact.download` row | Easy to miss or double-count |
| Ops | API bandwidth / buffering | Offloads bandwidth to S3/MinIO |
| Leakage | No durable client-held URL | URL is a bearer capability until expiry |

**Presigned URLs are NOT the primary download model.** They are not used for end-user payroll artifact download in v1. Any future internal use needs an ADR amendment, plus audit evidence of equal strength. Every download is audit-logged per [ADR 0009](0009-audit-outbox.md).

---

### 6. Consistency: DB intent → upload → finalize

```text
1) INSERT export_artifacts status=pending, object_key assigned (bytes absent)
2) Upload object bytes to S3/MinIO at object_key
3) Finalize: status=available + checksum_sha256 + size_bytes + etag/object_version + finalized_at
```

| Step | Failure | Handling |
| --- | --- | --- |
| 1 Intent insert | DB error | Job retries; no object written. |
| 2 Upload | Storage error / timeout | Leave `pending`; retry idempotent PUT to same key. |
| 2 Upload | Crash mid-PUT | Row stays `pending`; retry or orphan reconciler. |
| 3 Finalize | DB error after PUT | Object may exist; retry finalize via HEAD/re-hash. |
| 3 Finalize | Checksum mismatch | Do not mark `available`; delete/overwrite object; fail attempt. |

Never mark a row `available` without a verified SHA-256 and size. Download handlers ignore non-`available` rows.

**Orphan reconciliation** (`storage.reconcile_orphans`):

1. **Stuck pending** rows older than a threshold → re-drive upload/finalize, or mark failed and delete the partial object.
2. **Orphaned objects** (a storage key with no DB row, or failed past grace) → delete from storage.
3. **Missing objects** (`available` but HEAD 404) → mark unhealthy / re-queue generation; never silently serve.

---

### 7. `export_artifacts` schema, retention, audit

#### Table: `export_artifacts`

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | `uuid` PK | Artifact id returned to clients. |
| `organization_id` | `uuid` NOT NULL | Tenant scope; RLS. |
| `posted_run_id` | `uuid` NOT NULL | Posted payroll run this artifact belongs to. |
| `run_version_id` | `uuid` NOT NULL | Immutable version bound at post ([ADR 0008](0008-command-workflow-idempotency.md)). |
| `report_type` | `text` NOT NULL | Catalog key from [report-catalog.md](../report-specs/report-catalog.md). |
| `template_version` | `text` NOT NULL | Report template version used for generation. |
| `engine_version` | `text` NOT NULL | Generator/engine build version for reproducibility. |
| `created_by` | `uuid` NULL | User, or NULL when system/worker created. |
| `created_at` | `timestamptz` NOT NULL DEFAULT `now()` | Intent row creation time. |
| `checksum_sha256` | `text` NULL | Hex SHA-256; required when `available`. |
| `object_key` | `text` NOT NULL | Opaque `{organization_id}/{object_uuid}`. |
| `object_version` | `text` NULL | S3 version id and/or **etag** on finalize. |
| `content_type` | `text` NOT NULL | MIME type served on download. |
| `size_bytes` | `bigint` NULL | Object size; required when `available`. |
| `retention_state` | `text` NOT NULL DEFAULT `'active'` | `active` \| `expired` \| `purged`. |
| `expires_at` | `timestamptz` NULL | When retention may expire the artifact. |
| `status` | `text` NOT NULL | At least `pending`, `available`, `failed`. |
| `finalized_at` | `timestamptz` NULL | When status became `available`. |
| `job_id` | `uuid` NULL | Generating `jobs.id`. |

**Indexes:** `(organization_id, posted_run_id, report_type, created_at DESC)`; `(organization_id, status, created_at)`; `(organization_id, retention_state, expires_at)`; unique `(organization_id, object_key)`.

**Retention purge** (`storage.purge_expired`): select `active` rows with `expires_at < now()` → mark `expired` → delete the object → mark `purged`. Downloads of non-`active` / non-`available` rows fail authz (no stream). Purge and reconcile use the same queue, lease, and org GUC rules.

**Download auditing:** every successful stream authorization writes `audit_events` with `command = 'artifact.download'` ([ADR 0009](0009-audit-outbox.md)). No bytes may flow without that audit row.

---

## Consequences

**Positive:** One durability system (PostgreSQL) covers commands, audit, outbox, jobs, and artifact metadata. `SKIP LOCKED` scales to multiple workers. Opaque keys plus checksums reduce leakage. Backend-streamed downloads make the `artifact.download` audit enforceable. The DB-first pending → available flow supports crash recovery.

**Costs:** The API bears download bandwidth (acceptable for payroll sizes; revisit only via a new ADR). Workers must get leases, heartbeats, and `SIGTERM` right. The cross-org poller needs a privileged path. Running the orphan reconciler is not optional. Alert on `dead_letter` growth, stuck `pending` artifacts, and expired leases that were never reaped.

---

## Alternatives Considered

### A. Redis / Celery as primary queue

**Rejected for v1.** It adds a second durability/tenancy boundary, and handlers still need DB idempotency. Postgres `SKIP LOCKED` handles the export/purge/reconcile volume.

### B. Presigned URLs as primary download

**Rejected as primary.** It undercuts per-request authz and reliable `artifact.download` auditing ([ADR 0009](0009-audit-outbox.md)). Bandwidth offload does not justify the compliance gap. Backend streaming is mandatory for user-facing downloads; **presigned is not primary**.

### C. Upload-first (object then DB row)

**Rejected.** A crash after the PUT leaves objects that nothing references. A DB intent row (`pending`) first gives a control-plane record for reconciliation.

### D. Human-readable object keys

**Rejected.** Keys show up in logs and listings, and payroll identifiers must not live in paths. Opaque `{organization_id}/{object_uuid}` only.

### E. Separate worker image/codebase

**Rejected.** Risk of domain drift. Same image, different entrypoint.

### F. Synchronous in-request generation only

**Rejected** for posted-run catalog exports. Timeouts and scaling demand durable jobs. Tiny sync previews (if any) sit outside this artifact store.
