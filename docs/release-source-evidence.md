# Committed release source evidence

This is an offline, inactive adapter. `activation_allowed` is always `false`. It supplies source evidence, not a complete component manifest, successful runtime receipt, backup-health proof or permission to deploy. Configuration and secret **version identifiers** require a separately approved authoritative collector; none are guessed or read from the environment here.

`deploy/release-inputs.json` declares component build inputs, shared dependencies, deployment/config/proxy/storage/auth roots and migration/seed/recovery/startup/job/file/write/API effects. The canonical reader hashes committed Git blobs and executable modes. It reads neither dirty working files nor ambient credentials. Missing declared paths, symlinks/submodules and invalid declarations fail closed. Unassigned tracked files enter the conservative shared-runtime fingerprint; this intentionally overclassifies changes until reviewed rather than granting a frontend shortcut.

The three canonical modules and app profile under `scripts/recovery/vendor/` are byte-for-byte copies of `Ornament-AI/msidc-infra` commit `f08c8d70799b0f0d6c4535a2397496793ec082d0`. `SOURCE.json` pins every copied hash. Do not locally reformat them or invent app policy.

## Local use

Run from the repository root with an exact committed source and a new output path:

```sh
python3 scripts/recovery/build_release_inputs.py \
  --repository . --source <exact-40-character-commit> --output /tmp/accord-source-evidence.json
python3 scripts/tests/test_release_input_evidence.py
```

The CLI obtains the declaration from that same commit. It creates a private output file exclusively and refuses overwrites/symlink targets. It has no runtime binding or activation option.

For a normal exact-source publication, the existing packager includes `release-inputs.json` and generated `release-build-inputs.json` in its existing signed v2 archive/file inventory. Build-only vendor code does not enter the deployed executable surface. Existing signed-v2 semantics and validator pins are unchanged. Historical rollback publication where release and tooling commits differ retains the existing package path without generating source evidence or claiming classification eligibility. A declaration at a later tooling commit is not evidence for that historical source.

## Application boundaries

The API, migrations and worker share the complete `backend/` build context and requirements. Web binds pnpm manifests, frontend and nginx. PostgreSQL and role-sync bind canonical `backend/scripts/create_roles.sql`; release packaging stages those bytes into `deploy/create_roles.sql`. MinIO, bucket initialization, role-password synchronization and their Compose mounts are distinct components.

Startup effects conservatively aggregate the API's read-only database/queue checks with mutating role-sync and bucket bootstrap; `role-sync` is the source-group owner, not an ownership attestation for every component. The CLI-only organization/member bootstrap is a mutating seed effect that does not run on startup. Worker jobs, lease recovery, artifact maintenance and outbox processing are declared. A consistent PostgreSQL plus MinIO recovery set and complete worker/object-store/external-writer fencing remain unproved. Do not substitute a tar of a live object store for that proof.

Every backend effect includes the complete `backend/app/` dependency envelope.
The API, migration and worker entrypoints share that image, import model
registries, and register service/report/job handlers; a short entrypoint list
cannot establish that their behavior stayed unchanged. This deliberately
overclassifies backend helper changes, including new nested modules, rather
than losing payroll, tenancy or database changes behind component build inputs.
The auth root additionally covers API routes and mounting code, session and
CSRF middleware, identity/member/bootstrap services, tenancy/database helpers
and imported model definitions. Authorization is also enforced inside payroll
maker/checker services and tenant-scoped workers/artifact operations. Their
service, domain, report, job and storage dependencies therefore remain in the
conservative auth boundary; the import-closure regression prevents an imported
local helper from silently disappearing from that boundary. Those changes require a dedicated infrastructure
plan even when another effect already includes the file. Frontend-only source
changes do not enter these roots or effects.

## Validation and remaining gates

The focused suite checks canonical hashes, full component topology, Docker dependency coverage, startup/job source sensitivity, frontend/backend separation, unknown-file conservatism, missing-input refusal and committed-source CLI behavior. It runs the real offline packager with synthetic digests (and synthetic protocol provenance for Delta) and verifies the v2-bound source bytes; these are not real image builds or hosted CI evidence. No database, Docker daemon, registry, credentials or production service is used.

Regressions mutate real committed payroll, tenancy and database blobs in a
disposable Git object database, exercise auth classification with synthetic
protocol evidence, and verify that each evidence-only PR path enables the
backend CI lane. The numerical values in those protocol fixtures are test data,
not approved backup or retention thresholds.

Personal exact-head review, configured CI, authoritative runtime config/secret versions, authenticated prior successful receipt and current locked observation, approved backup/restore-health policy, compatible old clients and full application failure/paired-restore rehearsals remain required before any new execution path. Numeric thresholds remain undecided. Preserve existing full deployment backups, scheduled full daily copies and retention. No new fast path, reduced backup, overlap, pruning or automatic fallback is enabled by this change.

Merge the canonical [infra #15](https://github.com/Ornament-AI/msidc-infra/pull/15)
correction first, then this adapter PR and the other dependent source-evidence
PRs. Keep the vendor commit and hashes aligned with that reviewed canonical
commit; merging these offline adapters does not authorize installation or
activation.
