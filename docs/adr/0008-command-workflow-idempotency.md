# ADR 0008: Command workflow and idempotency

- **Status:** Accepted
- **Date:** 2026-07-17
- **Deciders:** Accord platform architecture
- **Related:** [ADR 0007](0007-payroll-run-calculation-model.md), [ADR 0009](0009-audit-outbox.md), [docs/payroll-domain.md](../payroll-domain.md), [ADR 0001](0001-tenancy-rls-database-roles.md) (org-scoped `idempotency_keys` tenancy), [ADR 0002](0002-workos-authentication-sessions.md) (capability matrix)

## Context

Payroll runs move through a maker/checker lifecycle (see [payroll-domain.md](../payroll-domain.md)): draft inputs → immutable calculation snapshots (ADR 0007) → validation → submission → approval → posting → optional reversal. A generic REST update could change status by accident or by attack. That would bypass dual control, break the audit trail, and allow double-posting under retries.

Clients and workers retry. Operators race each other. So the system must:

1. Change workflow status **only through explicit, named commands**.
2. Bind each submission to one **immutable calculated run version** and a **content hash**.
3. Enforce **approver ≠ submitter** in both the service and the database.
4. Post **exactly once** under row locks, with audit + outbox in the same transaction (ADR 0009).
5. Give each command an **idempotency key, scoped per organization**. Flag key reuse with a changed payload. Clean up old keys by TTL.
6. Serialize mutating commands with row locks, plus optional advisory locks. Draft edits use optimistic concurrency instead.

## Decision

### 1. Command-only workflow status changes

All payroll run **status** transitions occur **only** through these named commands:

| Command | Intent |
| --- | --- |
| `calculate` | Produce a new immutable `payroll_run_version` and move/keep the run in a calculable workflow state. |
| `validate` | Run structural / reconciliation checks against the current bound or latest calculated version; mark `validated`. |
| `submit` | Maker submits one immutable calculated version + content hash for checker review. |
| `withdraw` | Maker (or authorized role) pulls back a `submitted` or `approved` run before post so inputs may be edited again. |
| `approve` | Checker accepts the bound submitted version (maker/checker SoD). |
| `reject` | Checker rejects the submission; run returns to a reworkable pre-submit state. |
| `post` | Commit the approved bound version to books/remittance; emit audit + outbox (ADR 0009). |
| `reverse` | Formal counter-document for a `posted` run without mutating the posted snapshot. |

**Hard rules:**

1. **Generic CRUD / PATCH / PUT must never change workflow status.** Create-run and draft-input APIs may set the initial `draft` value, and only at insert time. After that, `status` belongs to the commands.
2. Enforcement is layered:
   - **(a) Schemas:** Generic create/update schemas for runs and draft inputs **omit** `status`. They also omit `bound_run_version_id`, `submission_content_hash`, `submitted_by_id`, and `approved_by_id` as writable fields. Clients cannot patch status.
   - **(b) Service layer:** Only dedicated command service functions update status. In code these are `calculate_run_command` (`backend/app/services/run_calculation/`), `validate_run`, `submit_run`, `withdraw_run`, `approve_run`, `reject_run` (`backend/app/services/run_workflow.py`), and `post_run` / `reverse_run` (`backend/app/services/run_posting.py`). Generic handlers go through repositories that refuse status columns.
   - **(c) Database:** A `BEFORE UPDATE` trigger on `payroll_runs` raises if `OLD.status IS DISTINCT FROM NEW.status`, unless the session has run `SET LOCAL app.allow_workflow_transition = 'true'` inside the command transaction. Command services set that GUC for the length of the transaction only. Generic code paths never set it.

### 2. Statuses and transition matrix

**Statuses (closed set):** `draft`, `calculated`, `validated`, `submitted`, `approved`, `rejected`, `withdrawn`, `posted`, `reversed`.

**Commands (closed set):** `calculate`, `validate`, `submit`, `withdraw`, `approve`, `reject`, `post`, `reverse`.

Each cell shows the **to-status** on success, or `rejected` with a short reason. HTTP mapping for rejected cells: usually **409 Conflict** for an illegal transition, hash mismatch, or SoD breach; **404** when the run is missing; capability failures per ADR 0002.

| From status | calculate | validate | submit | withdraw | approve | reject | post | reverse |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `draft` | `calculated` | rejected: need calculate | rejected: need validate | rejected: not submitted/approved | rejected: not submitted | rejected: not submitted | rejected: not approved | rejected: not posted |
| `calculated` | `calculated` | `validated` | rejected: need validate | rejected: not submitted/approved | rejected: not submitted | rejected: not submitted | rejected: not approved | rejected: not posted |
| `validated` | `calculated` | `validated` | `submitted` | rejected: not submitted/approved | rejected: not submitted | rejected: not submitted | rejected: not approved | rejected: not posted |
| `submitted` | rejected: withdraw first | rejected: withdraw first | rejected: already submitted | `withdrawn` | `approved` | `rejected` | rejected: not approved | rejected: not posted |
| `approved` | rejected: withdraw first | rejected: withdraw first | rejected: already approved | `withdrawn` | rejected: already approved | rejected: withdraw or post | `posted` | rejected: not posted |
| `rejected` | `calculated` | rejected: need calculate | rejected: need validate | rejected: not submitted/approved | rejected: not submitted | rejected: already rejected | rejected: not approved | rejected: not posted |
| `withdrawn` | `calculated` | rejected: need calculate | rejected: need validate | rejected: already withdrawn | rejected: not submitted | rejected: not submitted | rejected: not approved | rejected: not posted |
| `posted` | rejected: terminal (use reverse) | rejected: terminal | rejected: terminal | rejected: terminal | rejected: terminal | rejected: terminal | rejected: already posted | `reversed` |
| `reversed` | rejected: terminal (new run for corrections) | rejected: terminal | rejected: terminal | rejected: terminal | rejected: terminal | rejected: terminal | rejected: terminal | rejected: already reversed |

**Normative notes on the matrix:**

- `calculate` from `calculated` or `validated` **always appends a new** immutable `payroll_run_version` (ADR 0007). From `validated`, success **demotes** status to `calculated`, because the prior validation no longer applies to the new version.
- `validate` from `validated` may re-run checks against the same latest version and stay `validated` (idempotent success if checks still pass).
- `submit` is allowed **only** from `validated`. It binds `bound_run_version_id` + `submission_content_hash` (section 3).
- `withdraw` is allowed from `submitted` **or** `approved` (pre-post only). Success clears the submission binding fields (or marks them inactive) and lands in `withdrawn`. Draft input edits then need a fresh `calculate` → `validate` → `submit` cycle.
- `reject` is allowed **only** from `submitted` (checker path). From `approved`, the checker must not reject. Use `withdraw` (authorized) or proceed to `post`.
- `post` is allowed **only** from `approved`. `reverse` is allowed **only** from `posted`. Both `posted` and `reversed` are terminal for the primary run row.
- Two identical, legal commands may race each other. That case goes through **idempotency** (section 6). We do not invent extra matrix cells for it.

### 3. Submission binds immutable version + content hash

On successful `submit`:

1. The command selects exactly one `payroll_run_versions` row. Normally that is the latest successful calculation for the run. The caller may instead supply an explicit `run_version_id`, which must belong to the run.
2. It computes **SHA-256** over a canonical UTF-8 byte string of a JSON document that includes **at least**:
   - `organization_id`, `payroll_run_id`, `payroll_period_id`
   - `bound_run_version_id`
   - **canonical JSON of calculated inputs** — the pinned effective-dated master / config version ids, and the draft-exception identities as consumed by that version (stable key order, decimal strings per ADR 0006)
   - **canonical JSON of calculated outputs** — employee lines (amounts + the trace fields needed for identity) and run-level **totals** (gross, deductions, net, employer share, etc.)
3. It stores on `payroll_runs`:
   - `bound_run_version_id` — the immutable version id
   - `submission_content_hash` — lowercase hex SHA-256 of that canonical document
4. It records `submitted_by_id` / `submitted_at` and sets status `submitted`.

**Edit policy while locked for review:**

- While status is `submitted` or `approved`, any API that mutates draft inputs returns **HTTP 409**. The operator must `withdraw` first, then edit, then `calculate` (new version), `validate`, and `submit` again (new hash).
- `approve` and `post` **recompute or reload** the hash for `bound_run_version_id` and require it to equal `submission_content_hash`. A mismatch means tampering or the wrong version → **409**.

### 4. Maker / checker: approver ≠ submitter

Dual control is mandatory for `approve`:

1. **Service layer:** Before moving `submitted` → `approved`, assert `actor_user_id <> run.submitted_by_id`. A person who holds both capabilities in the ADR 0002 matrix still cannot approve their own submission.
2. **Database CHECK** on `payroll_runs`:

```sql
CONSTRAINT payroll_runs_approver_ne_submitter CHECK (
  approved_by_id IS NULL
  OR submitted_by_id IS NULL
  OR approved_by_id <> submitted_by_id
)
```

`reject` does not set `approved_by_id`. `post` does not relax SoD. Posting may be a separate capability (ADR 0002), held by the same user as the approver or a different one. Product policy may tighten this later. This ADR **requires** only submitter ≠ approver.

### 5. Posting: single transaction, locks, audit, outbox

`post` procedure (normative order):

1. `BEGIN`
2. `SELECT … FROM payroll_runs WHERE id = $run_id FOR UPDATE` (with tenant context bound per ADR 0001).
3. Recheck everything: status is `approved`; `bound_run_version_id` is present; the recomputed content hash **equals** `submission_content_hash`; the validation artifacts for that version still pass (or a stored validation stamp is present); the run totals match the bound version totals.
4. In **one** transaction: set status `posted` (with `SET LOCAL app.allow_workflow_transition = 'true'`), write posting metadata (`posted_by_id`, `posted_at`), insert **`audit_events`**, insert **`outbox_events`** for downstream consumers.
5. `COMMIT`

If any recheck fails, the whole transaction aborts. There is no partial post. See **[ADR 0009](0009-audit-outbox.md)** for the `audit_events` / `outbox_events` shape, delivery, and retention. An idempotent replay of `post` with the same idempotency key returns the original success snapshot. A second distinct key that races in after the first commit sees rejected: already posted / 409.

Posted snapshot rows stay immutable. The app denies writes to them, and DB triggers block writes too, as release gate H requires. The only economic undo is `reverse`.

### 6. Organization-scoped idempotency

Every payroll command that changes state **requires** an `Idempotency-Key` header (or equivalent). Keys live in `idempotency_keys`, scoped by `organization_id` (RLS per ADR 0001). This ADR **extends** the sketch in ADR 0001 to the command schema below.

#### Table: `idempotency_keys`

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | `uuid` PK | Surrogate primary key. |
| `organization_id` | `uuid` NOT NULL | Tenant scope; part of uniqueness; RLS. |
| `idempotency_key` | `text` NOT NULL | Client-supplied key string. |
| `request_hash` | `text` NOT NULL | SHA-256 of canonical request payload (command name + body + resource identity). |
| `command_name` | `text` NOT NULL | One of the eight commands (or other registered mutating commands). |
| `resource_type` | `text` NOT NULL | e.g. `payroll_run`. |
| `resource_id` | `uuid` NOT NULL | Target resource id. |
| `status` | `text` NOT NULL | `in_progress` \| `completed` \| `failed`. |
| `response_snapshot` | `jsonb` NULL | Stored HTTP status + body for replay when `completed` (and optionally `failed`). |
| `locked_at` | `timestamptz` NULL | When the in-progress lease was taken. |
| `lock_owner` | `text` NULL | Worker/request instance id holding the lease. |
| `created_at` | `timestamptz` NOT NULL | First sighting of the key. |
| `expires_at` | `timestamptz` NOT NULL | Expiry for TTL cleanup (**created_at + 72 hours**). |
| `completed_at` | `timestamptz` NULL | When status became `completed` or terminal `failed`. |

**Constraints:** `UNIQUE (organization_id, idempotency_key)`; CHECK on `status` in (`in_progress`, `completed`, `failed`).

**Behavior:**

| Case | Result |
| --- | --- |
| Same org + key + **same** `request_hash` | Replay: if `completed`, return `response_snapshot` without re-executing side effects; if `in_progress`, wait/retry or 409 conflict-in-flight per implementation choice (prefer short wait then 409). |
| Same org + key + **different** `request_hash` | **HTTP 409** — key reuse with divergent payload. |
| New key | Insert `in_progress`, execute command, store snapshot, mark `completed` (or `failed` with snapshot of error). |

**TTL:** 72 hours from creation. A scheduled cleanup job **deletes expired** rows (`expires_at < now()`). Clients must not assume keys live longer than 72 hours.

### 7. Concurrency controls

| Mechanism | Where used |
| --- | --- |
| `SELECT … FOR UPDATE` on `payroll_runs` | All eight workflow commands; mandatory for `submit`, `approve`, `reject`, `withdraw`, `post`, `reverse`. |
| Optional transaction-scoped **advisory locks** | `pg_advisory_xact_lock(hashtext(organization_id::text), hashtext(run_id::text))` (or equivalent two-int form) when commands also touch related draft tables and need a coarser serialize point. |
| Optimistic `input_version` (integer) | Draft input / monthly exception updates (ADR 0007): client supplies expected version; mismatch → **409**; success increments version. Does **not** replace FOR UPDATE on commands. |

Every command transaction that changes status sets `app.allow_workflow_transition` locally, as in section 1.

## Consequences

**Positive:**

- Workflow status cannot drift through generic APIs or a forgotten WHERE clause. The DB GUC + trigger is a hard backstop.
- The submission hash plus the bound version means approve and post verify “what was calculated”, not “whatever is latest”.
- Maker/checker SoD holds even against raw SQL that sets both columns wrongly.
- Posting runs exactly once, under a row lock and an idempotency key. Audit and outbox commit in the same transaction (ADR 0009).
- Retries are safe. Key/payload abuse fails loudly with a 409.

**Negative / costs:**

- More endpoints and more client discipline (commands + Idempotency-Key) than a single PATCH-status resource.
- Keys are kept for 72 hours, and a cleanup job must run. That adds ops load.
- Withdraw-from-approved adds one more ops path. It must be gated with care (capability + audit).

**Follow-ons:**

- Reports read posted snapshots only ([report-catalog.md](../report-specs/report-catalog.md)).

## Alternatives Considered

| Alternative | Why rejected |
| --- | --- |
| PATCH `status` on `payroll_runs` with server-side transition guards only | Easy to miss a handler; no DB GUC backstop; blurs CRUD vs workflow; fails threat-model “command-only workflow.” |
| Soft delete / overwrite of calculated lines instead of immutable versions + submit hash | Breaks audit and maker/checker review of a fixed snapshot (conflicts ADR 0007). |
| Allow submitter to approve when dual-roled | Violates dual control for government payroll; CHECK constraint forbids it. |
| Idempotency only in Redis / in-memory | Not durable across restarts; Accord Phase 0 prefers Postgres (aligned with ADR 0001 / ADR 0010). |
| Infinite retention of idempotency keys | Unbounded growth; 72h TTL + delete job is sufficient for client retries. |
| Separate workflow engine / external BPMN | Overkill for a fixed eight-command matrix; harder to keep hash binding and posting atomicity co-located with the run row. |
| Advisory locks only, no `FOR UPDATE` on the run | Weaker coupling to the row being posted; `FOR UPDATE` is the primary serialize point; advisory locks are optional sharpening. |
