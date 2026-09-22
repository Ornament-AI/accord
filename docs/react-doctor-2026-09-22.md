# React Doctor verification — 2026-09-22

**Status: Blocked below 100/100.**

Base: `0e45a6805a227e334aa93c1530a2645f9e236cf5` (`origin/main` at inventory time). Work was isolated on `codex/react-doctor-20260922`.

Tool: React Doctor 0.9.14, freshly resolved with `npx react-doctor@latest`; Node 24.21.0. No exclusions, ignore files, new suppressions, disabled rules, deleted application behavior, or relaxed checks were used.

## App inventory and full scans

| Root | Baseline score / findings | Final score / findings | Uncached audit score / findings |
| --- | --- | --- | --- |
| `frontend` | 57/100 · 109 | 60/100 · 107 | 60/100 · 107 |

Scans were run from each root above. Baseline and final command: `npx react-doctor@latest --verbose`. Audit command: `npx react-doctor@latest --verbose --no-cache --no-respect-inline-disables`. Default full scope was retained. Normal build outputs were left in place for final scans. The scanner applies its own built-in scope; no project exclusions were added.

Full text logs and diagnostic arrays are in [react-doctor-2026-09-22/](react-doctor-2026-09-22/). The strict audit deliberately exposes any pre-existing inline suppressions; it is not replaced with a changed-files scan.

## Changes and stop condition

Moved header registration cleanup out of the state updater, keeping updater callbacks pure. Added meaningful Strict Mode and stale-registration regression tests. Two findings were removed. The remaining findings and the scanner blocker are retained.

`no-loading-flag-reset-outside-finally` reports `loadUser` even though its awaited helper, `fetchCurrentUser`, catches network, response parsing, and validation failures and returns null. Both continuations clear loading. This finding is not evidence of a rejected promise leaving the spinner stuck. A scanner change is needed to recognize the non-throwing helper contract; no rule override or redundant error path was added.

Source evidence: [frontend/src/contexts/AuthContext.tsx:113](https://github.com/Ornament-AI/accord/blob/0e45a6805a227e334aa93c1530a2645f9e236cf5/frontend/src/contexts/AuthContext.tsx#L113).

The requested 100/100 target is not achieved. Work stopped at this verified scanner or validation blocker under the task stop rule. Remaining actionable findings are included in the full diagnostic arrays; this report does not certify the rest of the code as issue-free.

## Validation

| Command | Result |
| --- | --- |
| `corepack pnpm typecheck` | exit 0 |
| `corepack pnpm lint` | exit 0 |
| `corepack pnpm test` | exit 0 |
| `corepack pnpm build` | exit 0 |

Local build checks do not prove production configuration or authentication. No production data or credentials were used.

## Scope and preservation

Original checkouts, existing worktrees, branches, stashes, and unrelated work were preserved. This branch contains the focused changes described above and their verification record. At the scan stage, no merge, deployment, or production mutation had occurred. Release tracking is separate.

Non-document source manifest SHA-256: `cbe340db746da50255ae838eba3c56a55ca70138769fc62f40d7652be71aade2`. The full filename/hash manifest and timestamped command results are in `verification.json`.

Evidence formatting: committed text logs remove trailing whitespace and trailing blank lines and replace absolute checkout paths with `<repository>`; all diagnostics and nonblank output lines remain. `log-provenance.json` records original and committed hashes. Verbatim output remains in the local evidence bundle. Validation working directories are repository-relative.

The commands above record the required `@latest` invocations as actually run. To reproduce the recorded scanner version later, use `npx react-doctor@0.9.14 --verbose` (plus the stated strict audit flags).
