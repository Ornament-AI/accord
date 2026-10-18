# Accord agent guide

Read [README](README.md) for setup and the payroll hard rules,
[developer reference](docs/developer-reference.md) for implementation, and
[security](docs/security.md) for identity, capabilities and database roles.

## Setup and verification

- Use the checked-in manifests, lockfile and CI toolchain; root `package.json`
  pins pnpm. Do not assume a particular Cursor snapshot, PATH symlink or database
  has already been provisioned.
- From the root, `./scripts/dev-setup.sh` prepares local dependencies/databases;
  `./scripts/start.sh` applies migrations and starts the API and Vite. Use
  `./scripts/status.sh` and `./scripts/stop.sh` for the managed processes.
  macOS Homebrew provisioning may use `./scripts/dev-setup.sh --start`.
  Follow the selected environment's startup instructions on Linux.
- `pnpm verify` is the combined local gate. Focused frontend checks are
  `pnpm lint`, `pnpm typecheck`, `pnpm test` and `pnpm build`.
  See [testing](docs/testing.md) for backend and browser prerequisites.
- Backend tests require an explicitly verified disposable test database; the
  name containing `test` is not proof of a safe host. Never use the local dev
  superuser role in a shared, staging or production environment.
- Organization bootstrap is CLI-only (ADR 0011). A fresh database needs an org
  and matching admin before login; use README's first-sign-in procedure rather
  than assuming a pre-seeded VM. Dev auth bypass is local/test only.

## Code Review Rules

- Flag binary floats in payroll calculations or money transport. Use Decimal /
  PostgreSQL NUMERIC and decimal-string API values.
- Flag edits or deletion of posted payroll and loss of the dated master-data
  versions/snapshots it used. Withdraw before posting; reverse after posting.
- Commit required audit evidence and integration-worthy outbox events atomically
  with the mutation. Follow [ADR 0009's audit/outbox matrix](docs/adr/0009-audit-outbox.md#6-what-gets-audit-vs-outbox):
  monthly exceptions, master-data version appends and artifact downloads are
  audit-only unless their integration contract adds a sink. Do not require
  unnecessary outbox rows or make a spreadsheet the system of record.
- Preserve the one-organization-per-deployment boundary, WorkOS identity,
  membership capabilities, session-bound CSRF and least-privilege database roles.
  UI visibility alone is not authorization; follow the security doc's exceptions.
