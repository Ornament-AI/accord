# Accord

Accord is an open-source payroll system of record for local governments and public
works departments. Organizations maintain employee and payroll facts once, record
only effective-dated changes and monthly exceptions, calculate and approve payroll
through a maker/checker workflow, and generate export-ready Excel/PDF reports from
immutable posted payroll data.

## Principles

- **System of record** — no spreadsheet import path or workbook operating mode.
- **Exact money** — PostgreSQL `NUMERIC` + Python `Decimal`; money over the API is
  a canonical string; `float` is banned from payroll domain code.
- **Temporal truth** — effective-dated master versions; posted payroll retains the
  exact source version IDs and snapshots it was computed from.
- **Immutable posting** — posted results are never edited or deleted; corrections
  use withdrawal before posting, or reversal/supplemental runs after.
- **Defense-in-depth tenancy** — multi-organization from day one, with forced
  PostgreSQL row-level security on every tenant-owned table.
- **Transactional evidence** — every business mutation commits atomically with an
  append-only audit event and an outbox event.

## Stack

FastAPI / Python / PostgreSQL backend, React / TypeScript frontend, WorkOS
authentication, S3-compatible object storage, Docker-based deployment (self-hosted
Compose or managed PostgreSQL + object storage).

## Repository layout

- `backend/` — FastAPI application, domain engine, migrations, tests
- `frontend/` — React application (Atlas-derived design system)
- `deploy/` — Docker Compose, images, nginx, local MinIO profile
- `docs/` — architecture, ADRs, domain reference, report specs, security
- `fixtures/sanitized/` — synthetic test fixtures only; real PII is never committed

## Provenance

Accord transplants the design system and infrastructure conventions of the Atlas
application from a pinned upstream release tag. See
`docs/atlas-upstream-manifest.md` for exact provenance, exclusions, and licenses.

## License

Apache-2.0 — see [LICENSE](LICENSE).
