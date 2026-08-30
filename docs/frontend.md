# Frontend architecture

This page explains how Accord's browser application is put together and where
to make common changes. It complements the route inventory in
[`developer-reference.md`](developer-reference.md) and the end-to-end setup in
[`../frontend/e2e/README.md`](../frontend/e2e/README.md).

## Runtime shape

The frontend is a React and TypeScript single-page application built by Vite.
`frontend/src/main.tsx` mounts `App`, and `frontend/src/App.tsx` owns the global
provider order:

```text
Icon defaults
  -> application error boundary
  -> TanStack Query client
  -> motion and reduced-motion policy
  -> theme and notifications
  -> authentication state
  -> route tree
```

Keep providers that own application-wide state here. Page-specific state should
stay in its page module or in a domain API hook.

## Authentication and access states

`frontend/src/contexts/AuthContext.tsx` loads `GET /api/auth/me` and validates
the response before exposing it to the rest of the application. The backend can
return three access states:

| State | Meaning | Browser result |
| --- | --- | --- |
| `unbootstrapped` | The deployment has no organization | Show **Deployment Not Ready** |
| `unprovisioned` | The user is signed in but has no membership | Show **Not Provisioned** |
| `active` | Organization and membership are both present | Render the protected application shell |

`ProtectedLayout` in `frontend/src/route-components.tsx` applies those states.
Unauthenticated users go to `/login` with a sanitized `returnTo` value.

The UI reads capabilities from the active membership. `NAV_REGISTRY` hides
navigation that the user cannot use, while `CapabilityGate` protects direct
page access. These checks improve the interface; they do not replace backend
authorization. Every protected API route must still enforce its capability.

Logout clears both authentication state and the TanStack Query cache before
remounting the protected shell. New identity-changing flows must preserve that
cache boundary so data from one session cannot remain visible in another.

## Routes and page ownership

`frontend/src/router.tsx` is the route source of truth. Page modules are lazy
loaded through `frontend/src/route-components.tsx`.

| Product area | Route | Main module |
| --- | --- | --- |
| Employees | `/employees`, `/employees/:employeeId` | `frontend/src/pages/employees/` |
| Offices and posts | `/organization/*` | `frontend/src/pages/org-setup/` |
| Pay components | `/pay-components/*` | `frontend/src/pages/pay-components/` |
| Pay runs | `/pay-runs/*` | `frontend/src/pages/pay-runs/` |
| Reports | `/reports/*` | `frontend/src/pages/reports/` |
| Audit | `/audit` | `frontend/src/pages/audit/` |

The protected shell lives in `frontend/src/components/protected-shell.tsx`.
It owns the sidebar, registered page header, scroll reset, suspense boundary,
and route transitions. Table-heavy routes can opt out of exit animation with
the `stableRouteTransition` route handle.

Primary navigation is data-driven. `frontend/src/lib/nav-registry.ts` maps
paths to capabilities, and its Reports children come from
`frontend/src/lib/reports/report-registry.ts`. The backend report catalog is
canonical. `scripts/generate-report-catalog.py` writes its product-sheet
membership, order, and titles to a checked-in frontend input. Backend tests and
the CI drift check fail if that generated input becomes stale; frontend tests
then verify that every backend-defined sheet has a stable route and navigation
entry.

## API and server state

Most authenticated domain HTTP calls pass through
`frontend/src/lib/api/http.ts`. Session bootstrap is the deliberate exception:
`AuthContext` calls `/api/auth/me` directly because an unauthenticated response
is normal there. The shared HTTP layer:

- resolves the base URL through `VITE_API_BASE_URL`;
- includes the session cookie by default;
- converts failed responses into `ApiError` values;
- understands the backend Problem Detail envelope;
- redirects an expired session to `/login`; and
- handles binary downloads and `Content-Disposition` filenames.

Server-state domain modules under `frontend/src/lib/api/`, such as employees,
payroll runs, reports, and audit, follow one pattern:

1. define hierarchical query-key factories;
2. provide plain async fetcher functions; and
3. expose React Query hooks whose successful mutations invalidate the affected
   keys.

The shared client in `frontend/src/lib/query-client.ts` treats data as fresh for
30 seconds and keeps unused cache entries for 30 minutes. Queries may retry
network errors, HTTP 408/429, and server errors at most twice. Mutations never
retry automatically. Preserve that rule for financial commands: an automatic
mutation retry can duplicate work unless the command's idempotency contract
explicitly makes it safe.

API response types come from
`frontend/src/types/api.generated.ts`. Do not edit that file by hand. After a
backend schema change, regenerate it from the repository root:

```bash
pnpm generate:api
```

Commit the backend schema change and the regenerated TypeScript contract
together.

## Components and styling

Reusable primitives live in `frontend/src/components/ui/`. They wrap Base UI
where behavior is complex and use Tailwind classes for styling. Product-level
components live one level higher under `frontend/src/components/`; page-only
components stay beside their page.

Before adding a primitive, check the existing library for keyboard behavior,
focus management, overlays, date selection, responsive sheets, tables, and
empty/error states. Reusing those contracts keeps accessibility and visual
behavior consistent.

## Verification

Run the frontend checks from the repository root:

```bash
pnpm --filter frontend lint
pnpm --filter frontend format:check
pnpm --filter frontend typecheck
pnpm --filter frontend test:run
pnpm --filter frontend build
```

Vitest and Testing Library cover utilities, providers, UI primitives, and page
modules. MSW supplies API behavior for component tests. Playwright covers the
signed-in setup, master data, the payroll workflow through submit and the
self-approval denial, the reports empty state, and automated accessibility
checks. The report generate, poll, and download journey is intentionally
skipped because the local dev-auth harness supplies only one identity and
cannot produce a posted run through the UI. API, service, and frontend
integration tests remain the evidence for report generation and download.
Playwright runs against a separately prepared full stack:

```bash
pnpm --filter frontend e2e
```

See [`testing.md`](testing.md) for the full test strategy and
[`../frontend/e2e/README.md`](../frontend/e2e/README.md) for browser-test setup.

## Change checklist

When adding a page or workflow:

1. add or update the route in `router.tsx` and lazy export in
   `route-components.tsx`;
2. add navigation only when the page belongs in the primary sidebar;
3. apply a capability gate in the UI and enforce the same rule in the backend;
4. use a domain API module and stable query keys instead of calling `fetch`
   directly from a component;
5. invalidate all affected server-state keys after a successful mutation;
6. regenerate API types when the backend contract changed; and
7. add focused component coverage plus Playwright coverage for a new critical
   user journey.
