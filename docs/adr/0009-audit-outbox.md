# ADR 0009: Append-only audit log and transactional outbox

- **Status:** Accepted
- **Date:** 2026-07-17
- **Deciders:** Accord platform architecture
- **Related:** [ADR 0008](0008-command-workflow-idempotency.md) (command handlers commit audit + outbox with mutations), [ADR 0010](0010-jobs-object-storage.md) (`artifact.download` auditing and job side effects), [payroll-domain.md](../payroll-domain.md)

---

## Context

Accord is a multi-tenant payroll system of record for Indian local-government / public-works salaried staff ([payroll-domain.md](../payroll-domain.md)). Every business mutation that changes tenant-owned state must leave an immutable evidence trail — who acted, what command ran, which entity changed, and complete before/after entity snapshots — and must be able to notify downstream integrations without dual-write races.

Two failure modes drive this ADR:

1. **Missing or editable audit.** If audit is written only in application logs, or if the runtime DB role can `UPDATE`/`DELETE` history, the trail is not trustworthy for maker/checker review, posting, reversal, or compliance review of artifact downloads.
2. **Dual-write between DB and messaging.** If the API commits a payroll `post` and then separately publishes to a queue or webhook, a crash between those steps loses the event (or, with naive retries, duplicates inconsistently relative to committed state).

The transactional outbox pattern inserts the integration event into PostgreSQL in the **same transaction** as the business mutation; a separate dispatcher delivers later. Audit rows are written in that same unit of work and must not be editable by the application at runtime — enforcement at the database privilege layer, not only in ORM conventions.

Command handlers and idempotency are defined in [ADR 0008](0008-command-workflow-idempotency.md). Sensitive download auditing for export artifacts is required by [ADR 0010](0010-jobs-object-storage.md).

---

## Decision

### 1. Append-only `audit_events`

Every successful business mutation that changes tenant-owned state writes one or more `audit_events` rows in the **same database transaction** as the mutation (unit of work). Sensitive read paths that are compliance-relevant — notably `artifact.download` — also insert audit rows even though they do not mutate business aggregates ([ADR 0010](0010-jobs-object-storage.md)).

#### Table: `audit_events`

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | `uuid` PK | Stable event id; consumers may later stream or reference this id. |
| `organization_id` | `uuid` NOT NULL | Tenant scope; RLS applies. |
| `actor_user_id` | `uuid` NULL | Authenticated user who performed the action; NULL for system-originated events. |
| `actor_snapshot` | `jsonb` NULL | Immutable actor id, name, and email captured at event time. |
| `entity_type` | `text` NOT NULL | Affected aggregate/entity kind, e.g. `payroll_run`, `export_artifact`, `employee`. |
| `entity_id` | `uuid` NOT NULL | Primary key of the affected entity. |
| `entity_label` | `text` NULL | Immutable human-readable label captured when the event is written; NULL on legacy rows. |
| `command` | `text` NOT NULL | Action name aligned with ADR 0008 commands where applicable: `calculate`, `submit`, `approve`, `post`, `artifact.download`, etc. |
| `event_kind` | `text` NULL | `mutation` or `access` for new rows; NULL identifies an immutable legacy event. |
| `before_state` | `jsonb` NULL | Complete persisted scalar/JSON entity state immediately before a new mutation. |
| `after_state` | `jsonb` NULL | Complete persisted scalar/JSON entity state immediately after a new mutation. |
| `request_id` | `text` NULL | Correlation / tracing id from API middleware (e.g. `X-Request-Id`). |
| `idempotency_key` | `text` NULL | Present when the mutation was driven by an idempotent command ([ADR 0008](0008-command-workflow-idempotency.md)). |
| `changed_count` | `integer` NOT NULL DEFAULT `0` | Count of user-visible changed fields after technical bookkeeping fields are suppressed. |
| `created_at` | `timestamptz` NOT NULL DEFAULT `now()` | Immutable event timestamp (transaction commit time semantics via insert-in-txn). |
| `metadata` | `jsonb` NOT NULL DEFAULT `'{}'` | Non-secret event context. Access events store the complete resource snapshot under `resource`. |
| `summary` | `jsonb` NOT NULL | Legacy compatibility payload. New read contracts do not expose it. |

**Indexes (normative intent):**

- `(organization_id, created_at DESC)` — tenant timelines.
- `(organization_id, entity_type, entity_id, created_at DESC)` — entity history.
- `(organization_id, request_id)` where `request_id IS NOT NULL` — request correlation.
- Optional unique partial index on `(organization_id, idempotency_key, command)` only if product rules require a hard uniqueness guarantee beyond ADR 0008’s idempotency store; default is to rely on command idempotency, not audit uniqueness.

**RLS:** `organization_id = current_setting('app.current_org_id')::uuid` (or the project’s established org GUC name), fail closed when unset.

#### Unit of work / transactional write pattern

```text
BEGIN;
  SET LOCAL app.current_org_id = '<org uuid>';
  -- business mutation (e.g. payroll_runs status → posted; pin run version)
  INSERT INTO audit_events (...);
  INSERT INTO outbox_events (...);  -- when an integration event is required
COMMIT;
```

Rules:

1. Application services use a single unit-of-work / DB session per request or command. The audit insert is invoked by the same service method that performs the mutation — not by an async listener after commit.
2. If the mutation rolls back, the audit row rolls back with it. There is **no** “audit of failed commits” in this table; failed attempts may be logged to application logs/metrics instead.
3. Idempotent command **replays** ([ADR 0008](0008-command-workflow-idempotency.md)) must **not** insert a second audit row; they return the stored response without re-entering the mutation path.
4. Ordinary read-only operations do not audit. **Exception:** `artifact.download` **does** insert an audit row ([ADR 0010](0010-jobs-object-storage.md)).
5. New mutation events store complete persisted scalar/JSON fields belonging to the audited entity in `before_state` and `after_state`. Related-table expansion and binary contents are excluded. The history UI computes a changed-field diff and suppresses tenant ids, timestamps, and lock/version bookkeeping.
6. Access events use `event_kind = 'access'`, leave Before/After NULL, and store a complete JSON-safe resource snapshot plus request context in `metadata`; they never manufacture a mutation.
7. Existing rows remain byte-for-byte immutable. NULL `event_kind` marks them as legacy, and read clients show a minimal unavailable-detail message rather than exposing raw `summary` JSON.

### 2. No UPDATE or DELETE on `audit_events` for the runtime app role

Runtime application roles **must not** be able to modify or remove audit history. Soft-delete of audit rows is **forbidden**. Corrections are new compensating audit events (and, where applicable, domain reversals), not edits to prior rows.

#### Role separation

| Role | Purpose |
| --- | --- |
| `accord_migrator` | Owns tables; runs migrations; can `ALTER` structure; can `GRANT`/`REVOKE`. Not used by the API process. |
| `accord_app` | Runtime API (and any in-process worker that shares the app DSN). DML for business tables as needed; on `audit_events`: **SELECT + INSERT only**. |
| `accord_readonly` | Optional analytics/support role: **SELECT only** on audit (and other approved tables). |

Table ownership: `audit_events` (and `outbox_events`) are **owned by `accord_migrator`**. `accord_app` is never the owner.

#### GRANT / REVOKE (normative)

After table creation (as migrator / table owner):

```sql
-- Revoke broad defaults
REVOKE ALL ON TABLE audit_events FROM PUBLIC;

-- Runtime app: append + read only
GRANT SELECT, INSERT ON TABLE audit_events TO accord_app;
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM accord_app;

-- Optional support / analytics
GRANT SELECT ON TABLE audit_events TO accord_readonly;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM accord_readonly;
```

Additionally:

1. No group role grants `UPDATE`/`DELETE`/`TRUNCATE` on `audit_events` to `accord_app`.
2. Optional hardening: a trigger or `CREATE RULE` that raises on `UPDATE`/`DELETE` for non-migrator sessions — belt and suspenders; **privileges are the primary control**.
3. Partitioning, archival, or cold-storage moves run only as `accord_migrator` (or a dedicated admin procedure), never via the application role, and are change-controlled.

Schema migrations that rewrite audit storage run as `accord_migrator` in maintenance windows.

### 3. Transactional outbox: `outbox_events`

For integrations (notifications, external sync, webhooks — sinks may be phased in later), every integration-worthy business mutation inserts an outbox row in the **same transaction** as the mutation and its audit event. This eliminates dual-write inconsistency between committed DB state and “message sent.”

#### Table: `outbox_events`

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | `uuid` PK | Event id; **consumers MUST dedupe on this**. |
| `organization_id` | `uuid` NOT NULL | Tenant scope; RLS applies. |
| `event_type` | `text` NOT NULL | Stable name, e.g. `payroll_run.posted`, `artifact.available`. |
| `aggregate_type` | `text` NOT NULL | Aggregate root kind, e.g. `payroll_run`, `export_artifact`. |
| `aggregate_id` | `uuid` NOT NULL | Aggregate root id. |
| `payload` | `jsonb` NOT NULL | Integration payload (ids, hashes, totals — prefer references over full PII dumps). |
| `status` | `text` NOT NULL | `pending` \| `processing` \| `processed` \| `failed` \| `dead_letter`. |
| `attempt_count` | `integer` NOT NULL DEFAULT 0 | Delivery attempts by the dispatcher. |
| `available_at` | `timestamptz` NOT NULL DEFAULT `now()` | Earliest next claim time (supports backoff). |
| `created_at` | `timestamptz` NOT NULL DEFAULT `now()` | Insert time (same transaction as the mutation). |
| `processed_at` | `timestamptz` NULL | Set when delivery succeeds. |
| `last_error` | `text` NULL | Last delivery error summary (no secrets). |
| `locked_by` | `text` NULL | Dispatcher instance id while processing. |
| `lock_expires_at` | `timestamptz` NULL | Claim lease expiry; stale locks become reclaimable. |
| `audit_event_id` | `uuid` NULL | Optional reference to the paired `audit_events.id`. |

**Indexes (normative intent):**

- Partial index on `(available_at, created_at)` WHERE `status IN ('pending', 'failed')` for polling.
- `(organization_id, event_type, created_at DESC)` for tenant/event browsing.
- Index or FK on `audit_event_id` when the FK is enforced.

**RLS:** same org GUC pattern as other tenant tables. The dispatcher sets org context per claimed row, or uses a security-definer claim function and then sets the tenant GUC before tenant-scoped side effects ([ADR 0010](0010-jobs-object-storage.md)).

**Privileges for outbox (runtime):** `accord_app` needs `SELECT`, `INSERT`, and `UPDATE` on `outbox_events` (status/lock/attempt fields only via application code). `DELETE`/`TRUNCATE` remain revoked for `accord_app`. `accord_readonly` gets `SELECT` only. Ownership stays with `accord_migrator`.

```sql
REVOKE ALL ON TABLE outbox_events FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON TABLE outbox_events TO accord_app;
REVOKE DELETE, TRUNCATE ON TABLE outbox_events FROM accord_app;
GRANT SELECT ON TABLE outbox_events TO accord_readonly;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE outbox_events FROM accord_readonly;
```

### 4. Outbox dispatcher

**Decision:** A **separate dispatcher process** — same backend Docker image, different entrypoint/command — polls and claims unprocessed outbox rows. This matches the deployment pattern for background workers described in [ADR 0010](0010-jobs-object-storage.md): one image, multiple process roles.

The dispatcher is not in-process inside the API request path. API handlers only insert `pending` rows; delivery is asynchronous.

#### Claim pattern (`FOR UPDATE SKIP LOCKED`)

```sql
UPDATE outbox_events
SET status = 'processing',
    locked_by = $worker_id,
    lock_expires_at = now() + interval '5 minutes',
    attempt_count = attempt_count + 1
WHERE id IN (
  SELECT id FROM outbox_events
  WHERE status IN ('pending', 'failed')
    AND available_at <= now()
    AND (lock_expires_at IS NULL OR lock_expires_at < now())
  ORDER BY available_at, created_at
  FOR UPDATE SKIP LOCKED
  LIMIT $batch
)
RETURNING *;
```

After successful delivery to the downstream sink (or a no-op sink in early phases): set `status = 'processed'`, `processed_at = now()`, clear lock fields. On failure: set `status = 'failed'`, `available_at = now() + exponential_backoff`, store `last_error`. After a configured max attempts (e.g. 20), set `status = 'dead_letter'` for operator intervention.

Multiple dispatcher replicas are safe because `SKIP LOCKED` prevents two workers from claiming the same row concurrently; expired leases allow reclaim after a crash.

### 5. Delivery semantics: at-least-once

Outbox delivery is **at-least-once**:

- The dispatcher may crash after successful delivery but before marking `processed`.
- Retry will redeliver the same `outbox_events.id` and payload.

**Therefore:** every consumer of outbox events **MUST be idempotent** and **MUST dedupe by `outbox_events.id`** (or a deterministic derived idempotency key that includes that id). Exactly-once delivery is not promised at the transport layer.

Early phases may run a dispatcher that only logs and marks processed (no external sink). The insert-in-same-transaction contract still holds so later sinks can be enabled without rewriting command services ([ADR 0008](0008-command-workflow-idempotency.md)).

### 6. What gets audit vs outbox

| Change | `audit_events` | `outbox_events` |
| --- | --- | --- |
| Payroll `calculate` | Always | Optional (usually no; calculation is internal) |
| Payroll `validate` | No (read-only validation) | No |
| Payroll `submit` | Always | Yes — e.g. `payroll_run.submitted` (maker/checker notify) |
| Payroll `approve` | Always | Yes — e.g. `payroll_run.approved` |
| Payroll `reject` | Always | Yes — e.g. `payroll_run.rejected` |
| Payroll `withdraw` | Always | Yes if integrations listen; else audit-only acceptable in Phase 0 |
| Payroll `post` | Always | Yes — e.g. `payroll_run.posted` (downstream remittance/export triggers) |
| Payroll `reverse` | Always | Yes — e.g. `payroll_run.reversed` |
| Monthly exception / draft override edit | Yes (full entity snapshot) | No |
| Effective-dated master version append | Yes (full entity snapshot) | No (unless a sync sink is added later) |
| Artifact finalized (export ready) | Always | Yes — `artifact.available` |
| Artifact purged / expired | Always | Yes — `artifact.purged` |
| Artifact download | Always (`command = artifact.download`) | No (unless a compliance sink is added later) |
| Pure UI preference / non-tenant settings | No | No |

Payroll lifecycle terms (`submit`, `approve`, `post`, `reverse`, maker/checker) follow [payroll-domain.md](../payroll-domain.md) and the workflow enumeration in ADR 0007 / command surface in ADR 0008.

---

## Consequences

**Positive:**

- Command services ([ADR 0008](0008-command-workflow-idempotency.md)) and artifact flows ([ADR 0010](0010-jobs-object-storage.md)) share one transactional evidence pattern: mutation + audit (+ optional outbox) commit together or not at all.
- Database privileges make audit tampering by a compromised or buggy app role much harder than ORM-only conventions.
- At-least-once outbox with consumer dedupe is operationally simple and avoids distributed transactions.
- Early no-op dispatcher still records the contract; sinks can be added without rewriting handlers.

**Negative / costs:**

- Operators must provision `accord_migrator` vs `accord_app` (and optional `accord_readonly`) in every environment (Compose and cloud); a single superuser DSN for the API is non-compliant with this ADR.
- Complete snapshots increase audit storage and personal-data retention. Growth requires a later retention/archival policy (migrator-only); the application never deletes audit rows.
- Every outbox consumer must implement idempotent handlers keyed by outbox id; accidental non-idempotent sinks will double-apply on retry.
- Dispatcher is another process to monitor (lag, dead letters, lock expiry).

**Operational expectations:**

- Metrics: outbox age of oldest `pending`/`failed`, dead-letter count, claim latency, audit insert failures (should be zero if unit of work is correct).
- Alerts on dead-letter growth and dispatcher heartbeat loss.

---

## Alternatives Considered

| Alternative | Why rejected |
| --- | --- |
| Audit written by async bus / listener after commit | Loses the atomic evidence guarantee; crash = mutation without audit. |
| Application-only “no update” convention on audit | Insufficient; a bug or compromised role could rewrite history. DB `REVOKE UPDATE, DELETE, TRUNCATE` is required. |
| Allow `UPDATE` on audit for “corrections” | Corrections are new compensating events (and domain reversals), not edits to prior evidence. |
| Write directly to SQS/Rabbit/Kafka from the API | Dual-write unless an outbox is still the source of truth; outbox-first keeps one DB transaction as the commit boundary. |
| Exactly-once dispatcher with distributed transactions (2PC) | Unnecessary complexity for payroll integrations; idempotent consumers are the standard fix. |
| In-process outbox flush at end of request | Couples API latency to sink availability; crashes after commit but before flush still need a poller — so a separate dispatcher is required anyway. |
| Store audit only in object storage / SIEM | Useful as a secondary sink later, but the system of record for “did this command happen with this before/after” remains PostgreSQL in the mutation transaction. |

---

## Open questions (later phase)

- Concrete retention duration for hot `audit_events` vs cold archive.
- Payload PII minimization standards per `event_type`.
- Whether dead-letter outbox rows surface in an admin UI in v1 or remain ops-only SQL.
- Whether `calculate` ever emits outbox events for fan-out to reporting prewarm jobs.
