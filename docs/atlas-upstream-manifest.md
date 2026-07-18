# Atlas → Accord upstream transplant manifest

Research-only inventory of portable infrastructure from the Atlas monorepo.
Every path below was verified to exist on disk at the listed commit via
`test -e` / `ls` / `find`. Versions were read from config/lock/requirements
files (not guessed).

## 1. Upstream identity

- Repo path: `/Users/darshan/Documents/GitHub/atlas`
- Commit: `4d5d1f980f3b17144cc6f6173974ff9205fb573a`
- Tag: `v1.1.0` (annotated, local — not yet pushed; cut 2026-07-17 at commit `4d5d1f980f3b17144cc6f6173974ff9205fb573a` after Gate A verification: 19/19 checks, 1519 backend + 1155 frontend tests, 0 skipped, v1.0.0→HEAD migration replay verified)

Verified with: `git -C /Users/darshan/Documents/GitHub/atlas rev-parse HEAD`

## 2. Copy inventory

Paths are relative to the Atlas repo root. Grouped by transplant area.

### A. Backend infrastructure

#### Config / DB / app factory / logging / exceptions

| Path | Role |
|------|------|
| `backend/app/__init__.py` | Package init |
| `backend/app/config.py` | Settings (`pydantic-settings`); also contains Firebase / upload / restore / data-action fields that must be stripped or rewritten for Accord |
| `backend/app/db.py` | Async SQLAlchemy/SQLModel engine + session setup (`application_name`: `"atlas-api"` → rename) |
| `backend/app/main.py` | FastAPI app factory, lifespan, CORS, request-ID middleware (`X-Request-ID`), exception handlers, router mount |
| `backend/app/logging_config.py` | Structlog / logging setup |
| `backend/app/exceptions.py` | Custom exception hierarchy (`OrnamentError` and subclasses) |
| `backend/app/timezone.py` | Timezone helpers |

#### API response helpers / ProblemDetail / deps

| Path | Role |
|------|------|
| `backend/app/api/__init__.py` | API package init |
| `backend/app/api/responses.py` | Response helpers (includes `atlas-{slug}-…` download filename pattern → rename) |
| `backend/app/api/helpers.py` | Shared API helpers |
| `backend/app/api/deps.py` | FastAPI dependencies (auth principal, `X-Data-Action-Password` helpers — destructive-action pieces should not be carried into Accord as-is) |
| `backend/app/schemas/errors.py` | ProblemDetail / error schemas |
| `backend/app/schemas/pagination.py` | Shared pagination schemas (generic; transplantable) |

#### Security headers / middleware / health

| Path | Role |
|------|------|
| `backend/app/middleware/__init__.py` | Middleware package init |
| `backend/app/middleware/security_headers.py` | Security headers middleware |
| `backend/app/middleware/rate_limit.py` | Rate limiting (also used for data-action password attempts — review before copy) |
| `backend/app/api/routes/health.py` | `/api/healthz` and `/api/readyz` |
| `backend/app/auth/__init__.py` | Auth package init |
| `backend/app/auth/principal.py` | Auth principal type |

> **Not listed for copy (see §3):** `backend/app/middleware/firebase_auth.py`, upload/restore/data-action services.

#### Alembic

| Path | Role |
|------|------|
| `backend/alembic.ini` | Alembic config |
| `backend/migrations/env.py` | Alembic env (Atlas-branded docstring / default DB URL) |
| `backend/migrations/script.py.mako` | Migration template |

> Do **not** copy `backend/migrations/versions/**` (62 Atlas domain revisions).

#### Pytest bootstrap

| Path | Role |
|------|------|
| `backend/tests/conftest.py` | Root pytest fixtures / test DB bootstrap (`atlas_test`, `ATLAS_ALLOW_WEAK_SECRETS`) |
| `backend/tests/middleware/conftest.py` | Middleware test bootstrap |
| `backend/tests/migrations/conftest.py` | Migrations test bootstrap |

#### OpenAPI export / dependency pins / Docker / env example

| Path | Role |
|------|------|
| `backend/scripts/export_openapi.py` | OpenAPI export script |
| `scripts/generate-api-types.sh` | Wrapper that calls OpenAPI export + frontend typegen (`DEV_UI_APP_ID="atlas"`) |
| `scripts/test-backend.sh` | Backend test runner script |
| `backend/requirements.txt` | Runtime dependency pins |
| `backend/requirements-dev.txt` | Dev/test dependency pins |
| `backend/Dockerfile` | Backend image (`python:3.14.6-slim`) |
| `backend/.dockerignore` | Backend Docker ignore |
| `backend/.env.example` | Env template (Atlas DB / Firebase / data-action — rewrite for Accord) |
| `pyproject.toml` | Root Ruff + pytest config (not a package metadata file) |
| `uv.lock` | Only records `requires-python = ">=3.14"` (not a full dependency lock) |

### B. Frontend design system

#### CSS / theme tokens

| Path | Role |
|------|------|
| `frontend/src/index.css` | Primary theme tokens (light `:root` + dark `.dark`), `@font-face`, `--atlas-motion-*` tokens, toast/scrollbar utilities |
| `frontend/src/styles/shadcn-tailwind.css` | Tailwind / shadcn layer imported from `index.css` |
| `frontend/components.json` | shadcn config (`css`: `src/index.css`, style `base-nova`) |
| `frontend/src/theme-init.ts` | FOUC-prevention theme boot (`ATLAS_THEME` localStorage key) |
| `frontend/src/lib/ui/providers/theme-provider.tsx` | `ThemeProvider` (`dark` \| `light` \| `system`) |
| `frontend/src/lib/branding.ts` | `APP_NAME = "Atlas"`, `APP_SUBTITLE = "HAM"`, `APP_ORGANIZATION = "Innovastra"` |
| `frontend/src/lib/motion.ts` | `atlasMotion` motion tokens |

#### Fonts (`frontend/public/fonts/**`) — every file

| Path | Family / role |
|------|----------------|
| `frontend/public/fonts/ibm-plex-sans-latin-400-normal.woff2` | IBM Plex Sans 400 |
| `frontend/public/fonts/ibm-plex-sans-latin-500-normal.woff2` | IBM Plex Sans 500 |
| `frontend/public/fonts/ibm-plex-sans-latin-600-normal.woff2` | IBM Plex Sans 600 |
| `frontend/public/fonts/ibm-plex-sans-latin-700-normal.woff2` | IBM Plex Sans 700 |
| `frontend/public/fonts/ibm-plex-mono-latin-400-normal.woff2` | IBM Plex Mono 400 |
| `frontend/public/fonts/noto-sans-devanagari-400-700-normal.woff2` | Noto Sans Devanagari 400–700 |
| `frontend/public/fonts/OFL.txt` | SIL OFL 1.1 — IBM Plex |
| `frontend/public/fonts/noto-sans-devanagari-OFL.txt` | SIL OFL 1.1 — Noto Sans Devanagari |

Backend PDF font assets (optional if Accord generates PDFs with same fonts):

| Path | Role |
|------|------|
| `backend/app/assets/fonts/NotoSans-Regular.ttf` | Noto Sans for PDF |
| `backend/app/assets/fonts/NotoSansDevanagari-Regular.ttf` | Noto Sans Devanagari for PDF |
| `backend/app/assets/licenses/NotoFonts-OFL.txt` | OFL notice for backend fonts |

#### `frontend/src/components/ui/**` — every file (59)

**Primitives / modules (46):**

- `frontend/src/components/ui/alert-dialog.tsx`
- `frontend/src/components/ui/alert.tsx`
- `frontend/src/components/ui/attachment.tsx`
- `frontend/src/components/ui/avatar.tsx`
- `frontend/src/components/ui/badge-variants.ts`
- `frontend/src/components/ui/badge.tsx`
- `frontend/src/components/ui/breadcrumb.tsx`
- `frontend/src/components/ui/button-variants.ts`
- `frontend/src/components/ui/button.tsx`
- `frontend/src/components/ui/calendar.tsx`
- `frontend/src/components/ui/card.tsx`
- `frontend/src/components/ui/chart.tsx`
- `frontend/src/components/ui/checkbox.tsx`
- `frontend/src/components/ui/collapsible.tsx`
- `frontend/src/components/ui/combobox.tsx`
- `frontend/src/components/ui/date-picker.tsx`
- `frontend/src/components/ui/date-range-picker.tsx`
- `frontend/src/components/ui/dialog.tsx`
- `frontend/src/components/ui/dropdown-menu.tsx`
- `frontend/src/components/ui/empty.tsx`
- `frontend/src/components/ui/error-with-retry.tsx`
- `frontend/src/components/ui/input-group.tsx`
- `frontend/src/components/ui/input.tsx`
- `frontend/src/components/ui/label.tsx`
- `frontend/src/components/ui/lazy-recharts.tsx`
- `frontend/src/components/ui/light-rays.tsx`
- `frontend/src/components/ui/month-picker.tsx`
- `frontend/src/components/ui/pagination.tsx`
- `frontend/src/components/ui/popover.tsx`
- `frontend/src/components/ui/select.tsx`
- `frontend/src/components/ui/separator.tsx`
- `frontend/src/components/ui/sheet.tsx`
- `frontend/src/components/ui/sidebar.tsx`
- `frontend/src/components/ui/skeleton.tsx`
- `frontend/src/components/ui/slider.tsx`
- `frontend/src/components/ui/sonner.tsx`
- `frontend/src/components/ui/sortable-column-header.tsx`
- `frontend/src/components/ui/spinner.tsx`
- `frontend/src/components/ui/table.tsx`
- `frontend/src/components/ui/tabs-variants.ts`
- `frontend/src/components/ui/tabs.tsx`
- `frontend/src/components/ui/textarea.tsx`
- `frontend/src/components/ui/theme-switcher.tsx`
- `frontend/src/components/ui/toggle.tsx`
- `frontend/src/components/ui/tooltip.tsx`
- `frontend/src/components/ui/use-sidebar-resize.ts`

**UI tests (13):**

- `frontend/src/components/ui/__tests__/base-ui-contract.test.ts`
- `frontend/src/components/ui/__tests__/calendar.test.tsx`
- `frontend/src/components/ui/__tests__/date-picker.test.tsx`
- `frontend/src/components/ui/__tests__/date-range-picker.test.tsx`
- `frontend/src/components/ui/__tests__/empty.test.tsx`
- `frontend/src/components/ui/__tests__/input-group.test.tsx`
- `frontend/src/components/ui/__tests__/lazy-recharts.test.tsx`
- `frontend/src/components/ui/__tests__/month-picker.test.tsx`
- `frontend/src/components/ui/__tests__/overlay-positioners.test.tsx`
- `frontend/src/components/ui/__tests__/pagination.test.tsx`
- `frontend/src/components/ui/__tests__/popover.test.tsx`
- `frontend/src/components/ui/__tests__/table.test.tsx`
- `frontend/src/components/ui/__tests__/tabs.test.tsx`

#### App shell components (actual filenames)

| Role | Path |
|------|------|
| Protected shell | `frontend/src/components/protected-shell.tsx` |
| App layout | `frontend/src/components/app-layout.tsx` |
| Page shell | `frontend/src/components/page-shell.tsx` |
| Page toolbar | `frontend/src/components/page-toolbar.tsx` |
| App sidebar | `frontend/src/components/app-sidebar.tsx` (Atlas nav labels / storage keys — rewrite) |
| Sidebar section nav | `frontend/src/components/app-sidebar-section-nav.tsx` |
| Site header | `frontend/src/components/site-header.tsx` |
| Page glow | `frontend/src/components/page-glow.tsx` |
| App shell context | `frontend/src/contexts/AppShellContext.tsx` |
| App entry | `frontend/src/App.tsx` |
| Main entry | `frontend/src/main.tsx` |
| Router shell | `frontend/src/router.tsx` (strip domain routes; keep shell wiring patterns) |
| Login page (shell pattern) | `frontend/src/pages/LoginPage.tsx` (rewrite Atlas copy) |
| Not-found page | `frontend/src/pages/NotFoundPage.tsx` |
| HTML shell | `frontend/index.html` |
| Favicon | `frontend/src/favicon.svg` |

#### Shared table / form / dialog / loading / error components

| Path | Role |
|------|------|
| `frontend/src/components/loading-state.tsx` | Loading skeleton state |
| `frontend/src/components/empty-state.tsx` | Empty state wrapper |
| `frontend/src/components/error-boundary.tsx` | Error boundary |
| `frontend/src/components/invalid-route-state.tsx` | Invalid route state UI |
| `frontend/src/components/data-table-shell.tsx` | Data table shell |
| `frontend/src/components/data-table-skeleton.tsx` | Table skeleton |
| `frontend/src/components/column-visibility.tsx` | Persisted column visibility |
| `frontend/src/components/pagination-controls.tsx` | Pagination controls |
| `frontend/src/components/table-actions-menu.tsx` | Table actions menu |
| `frontend/src/components/table-interactions.ts` | Table interaction helpers |

#### Query client / HTTP / download / error utilities

| Path | Role |
|------|------|
| `frontend/src/lib/query-client.ts` | TanStack Query client + presets |
| `frontend/src/lib/api/http.ts` | `fetchWithAuth`, `fetchJson`, `fetchBlob`, `fetchDownload`, `DATA_ACTION_PASSWORD_HEADER` |
| `frontend/src/lib/api/query-utils.ts` | Query param helpers |
| `frontend/src/lib/api-url.ts` | `VITE_API_BASE_URL` helper |
| `frontend/src/lib/download.ts` | `downloadBlob` |
| `frontend/src/lib/errors.ts` | `ApiError`, `getErrorMessage` |
| `frontend/src/lib/content-disposition.ts` | Filename from `Content-Disposition` |
| `frontend/src/lib/utils.ts` | `cn` helpers + `ATLAS_TIME_ZONE` (rename) |

> Domain-coupled query modules exist and should be rewritten, not transplanted as-is:
> `frontend/src/lib/query-keys.ts`, `frontend/src/lib/query-options.ts`,
> `frontend/src/lib/query-invalidation.ts`, `frontend/src/lib/api/core.ts`,
> `frontend/src/lib/export-filenames.ts` (`datedAtlasExportFilename` → `atlas-…` filenames).

#### Vitest helpers / frontend toolchain

| Path | Role |
|------|------|
| `frontend/src/test-setup.ts` | Vitest setup (jest-dom, matchMedia mock) |
| `frontend/src/test/helpers.ts` | `mockAuth`, `mockQuery`, `mockToast`, Base UI helpers |
| `frontend/vite.config.ts` | Vite + Vitest config (`setupFiles: ./src/test-setup.ts`) |
| `frontend/package.json` | Frontend package (`name`: `frontend`) |
| `package.json` | Root workspace (`name`: `atlas`) |
| `pnpm-workspace.yaml` | Workspace: `frontend` |
| `pnpm-lock.yaml` | Lockfile |

### C. Deploy / CI

| Path | Role |
|------|------|
| `backend/Dockerfile` | Backend image build |
| `deploy/Dockerfile.web` | Frontend multi-stage build (`node:24.18.0-alpine` → `nginx:1.30-alpine`) |
| `docker-compose.yml` | Local compose (`postgres`, `backend`) |
| `deploy/docker-compose.yml` | Deploy compose (`db`, `migrate`, `backend`, `web`) |
| `deploy/nginx/nginx.conf` | Nginx SPA config (CSP includes Atlas Firebase host) |
| `.github/workflows/ci.yml` | CI workflow |
| `.github/workflows/deploy.yml` | Deploy / image publish workflow |
| `deploy/smoke-test.sh` | Deploy smoke test script |
| `deploy/build-and-push.sh` | Image build/push helper |
| `deploy/package.sh` | Deploy package helper |
| `deploy/setup.sh` | Deploy setup helper |
| `deploy/.env.example` | Deploy env template |
| `.dockerignore` | Root Docker ignore |

> Atlas-named deploy scripts exist and can be used as templates after rename:
> `deploy/deploy-atlas.sh`, `deploy/deploy-atlas-wrapper.sh`, `deploy/set-atlas-tag.sh`.

## 3. Exclusion list

Do **not** copy these into Accord. Each path was verified to exist.

### Atlas domain models (`backend/app/models/`)

| Path | Reason |
|------|--------|
| `backend/app/models/agency.py` | Agency domain entity |
| `backend/app/models/bill.py` | Bill domain entity |
| `backend/app/models/bill_document.py` | Bill document entity |
| `backend/app/models/package.py` | Package domain entity |
| `backend/app/models/package_document.py` | Package document entity |
| `backend/app/models/office_note.py` | Office note domain entity |
| `backend/app/models/office_note_document.py` | Office note document entity |
| `backend/app/models/spv.py` | SPV / project domain entity |
| `backend/app/models/spv_snapshot.py` | SPV snapshot entity |
| `backend/app/models/spv_document.py` | SPV document entity |
| `backend/app/models/user.py` | Atlas user/role model |
| `backend/app/models/lender.py` | Lender domain entity |
| `backend/app/models/lender_allocation.py` | Lender allocation entity |
| `backend/app/models/lender_compliance.py` | Lender compliance entity |
| `backend/app/models/funding_event.py` | Funding event entity |
| `backend/app/models/funding_event_document.py` | Funding event document entity |
| `backend/app/models/funding_allocation_document.py` | Funding allocation document entity |
| `backend/app/models/tds_challan.py` | TDS challan entity |
| `backend/app/models/tds_ledger_opening_balance.py` | TDS ledger entity |
| `backend/app/models/pending_debt_document.py` | Pending debt document entity |
| `backend/app/models/portfolio_document.py` | Portfolio document entity |
| `backend/app/models/data_entry_extension.py` | Cutover / data-entry extension state |
| `backend/app/models/feature_entitlement.py` | Paid Atlas module entitlements |
| `backend/app/models/fixed_deposit_interest_entry.py` | FD interest domain entity |
| `backend/app/models/report_cost_statement_input.py` | Cost-statement report inputs |
| `backend/app/models/document_base.py` | Domain document base |
| `backend/app/models/enums.py` | Domain enums |
| `backend/app/models/base.py` | ORM base wired to domain models |
| `backend/app/models/__init__.py` | Model package exports |

### Domain API routers

| Path | Reason |
|------|--------|
| `backend/app/api/routes/projects.py` | SPV/projects API |
| `backend/app/api/routes/packages.py` | Packages API |
| `backend/app/api/routes/bills.py` | Bills API |
| `backend/app/api/routes/bill_documents.py` | Bill documents API |
| `backend/app/api/routes/package_documents.py` | Package documents API |
| `backend/app/api/routes/office_notes.py` | Office notes API |
| `backend/app/api/routes/office_note_documents.py` | Office note documents API |
| `backend/app/api/routes/spv_documents.py` | SPV documents API |
| `backend/app/api/routes/portfolio_documents.py` | Portfolio documents API |
| `backend/app/api/routes/row_documents.py` | Row documents API |
| `backend/app/api/routes/pending_bills.py` | Pending bills API |
| `backend/app/api/routes/pending_debt.py` | Pending debt API |
| `backend/app/api/routes/idc_paid.py` | IDC paid API |
| `backend/app/api/routes/tranches.py` | Tranches API |
| `backend/app/api/routes/tds_challans.py` | TDS challans API |
| `backend/app/api/routes/lenders_compliance.py` | Lenders compliance API |
| `backend/app/api/routes/fms.py` | FMS API |
| `backend/app/api/routes/rundown.py` | Rundown API |
| `backend/app/api/routes/auth.py` | Atlas auth user endpoints |
| `backend/app/api/routes/admin.py` | Reset / restore-point admin actions |
| `backend/app/api/routes/maintenance.py` | Restore maintenance status |
| `backend/app/api/routes/data_entry_extension.py` | Cutover / data-entry gates |
| `backend/app/api/routes/data_entry_mutations.py` | Data-entry mutations entry |
| `backend/app/api/routes/data_entry_routes/` (entire directory) | Agency/bill/funding/package/TDS mutation routes |
| `backend/app/api/routes/reports.py` | Reports router aggregate |
| `backend/app/api/routes/report_routes/` (entire directory) | All report endpoint modules |
| `backend/app/api/routes/_document_metadata_rules.py` | Domain document metadata rules |
| `backend/app/api/routes/_multipart_form.py` | Domain multipart helpers |
| `backend/app/api/routes/_row_document_factory.py` | Domain row-document factory |

### Workbook import / cutover / parser code

| Path | Reason |
|------|--------|
| `backend/app/api/routes/imports.py` | Workbook import API |
| `backend/app/services/parsers/` (entire directory) | Workbook sheet parsers |
| `backend/app/services/bill_importer.py` | Import orchestration |
| `backend/app/services/bill_import_funding.py` | Import funding helpers |
| `backend/app/services/data_entry_extension.py` | Cutover / import gates |
| `backend/app/services/data_tables.py` | Cutover/history table boundary |
| `backend/app/services/data_entry/` (entire directory; 12 `.py` files) | Data-entry mutation services |
| `backend/app/schemas/imports.py` | Import request/response schemas |
| `backend/app/schemas/data_entry_extension.py` | Cutover schemas |
| `backend/app/schemas/data_entry_mutations.py` | Data-entry mutation schemas |

### Firebase configuration / middleware / auth code

| Path | Reason |
|------|--------|
| `backend/app/middleware/firebase_auth.py` | Firebase Auth middleware |
| `frontend/src/lib/firebase.ts` | Firebase client config (`atlas-main-d05c8.*`) |
| `backend/scripts/set_firebase_user_password.py` | Firebase admin password helper |
| Firebase fields in `backend/app/config.py` / `backend/.env.example` / `deploy/.env.example` | `FIREBASE_*` env + project id `atlas-main-d05c8` |
| `VITE_FIREBASE_*` in `frontend/src/vite-env.d.ts` | Frontend Firebase env typings |

### Data-action password / destructive confirmation

| Path | Reason |
|------|--------|
| `backend/app/services/data_action_lock.py` | Advisory lock for destructive/import actions |
| `DATA_ACTION_PASSWORD` in `backend/app/config.py` | Shared destructive-action password setting |
| `DATA_ACTION_PASSWORD_HEADER = "X-Data-Action-Password"` in `backend/app/api/deps.py` | Header + `require_data_action_password` |
| `frontend/src/lib/api/http.ts` (`DATA_ACTION_PASSWORD_HEADER`) | Client header constant |
| `frontend/src/components/data-entry/DeleteWithPasswordDialog.tsx` | UI requiring data-action password to delete |
| `frontend/src/components/data-entry/__tests__/DeleteWithPasswordDialog.test.tsx` | Tests for password delete dialog |

### Local upload directory handling

| Path | Reason |
|------|--------|
| `backend/app/services/upload.py` | Local upload stream/store (`ATLAS_STREAMED_UPLOAD_CLEANUP_FAILED`) |
| `backend/app/services/file_cleanup.py` | Orphan/upload rollback cleanup (`ATLAS_ORPHAN_*`) |
| `UPLOAD_DIR` in `backend/app/config.py` / `backend/.env.example` | Upload directory setting |
| Runtime dirs `uploads/`, `backend/uploads/` | Local uploaded files (not source to transplant) |

### Restore-point / backup code

| Path | Reason |
|------|--------|
| `backend/app/services/restore_points.py` | Restore-point create/restore around imports |
| `RESTORE_POINT_DIR` / `RESTORE_POINTS_REQUIRED` in config / `.env.example` | Restore-point settings |
| `backend/app/api/routes/admin.py` | Admin reset/restore endpoints |
| `backend/app/api/routes/maintenance.py` | Maintenance mode during restore |
| `deploy/reset_database.sh` | Destructive DB reset script |
| Runtime dir `backups/` | Local backup dumps (not source) |

### Atlas-specific report generation / report semantics

| Path | Reason |
|------|--------|
| `backend/app/api/routes/reports.py` + `backend/app/api/routes/report_routes/` | Report HTTP surface |
| `backend/app/services/agency_excel.py` | Agency Excel export |
| `backend/app/services/amount_statement_report.py` | Amount statement report |
| `backend/app/services/bill_excel.py` | Bill Excel export |
| `backend/app/services/cost_statement_excel.py` / `cost_statement_report.py` | Cost statement |
| `backend/app/services/daily_cashbook_excel.py` / `daily_cashbook_pdf.py` / `daily_cashbook_report.py` | Daily cashbook |
| `backend/app/services/finances_report.py` | Finances report |
| `backend/app/services/financial_progress_excel.py` / `financial_progress_report.py` | Financial progress |
| `backend/app/services/fms_pdf.py` | FMS PDF |
| `backend/app/services/gross_payment_statement_excel.py` | Gross payment statement |
| `backend/app/services/gstr7_excel.py` / `gstr7_pdf.py` / `gstr7_report.py` | GSTR-7 |
| `backend/app/services/liquidated_damages_statement_excel.py` | Liquidated damages |
| `backend/app/services/monthly_liability_register.py` / `monthly_liability_register_excel.py` | Monthly liability |
| `backend/app/services/mpr_excel.py` / `mpr_report.py` | MPR |
| `backend/app/services/office_note_pdf.py` | Office note PDF |
| `backend/app/services/payment_pdf.py` / `payment_pdf_data.py` / `payment_pdf_layout.py` | Payment PDFs |
| `backend/app/services/pdf_table_helpers.py` / `excel_export_helpers.py` / `report_tabular_pdf.py` / `reports_excel.py` / `reports_pdf.py` | Shared report export helpers tied to Atlas reports |
| `backend/app/services/quarterly_financial_statement.py` / `*_excel.py` / `*_pdf.py` | Quarterly financial statement |
| `backend/app/services/tds_return_excel.py` / `tds_return_report.py` | TDS return |
| `frontend/src/pages/reports/` (entire directory) | Report pages |
| `frontend/src/components/reports/` (entire directory) | Report UI components |

### Frontend domain pages / components (do not transplant)

| Path | Reason |
|------|--------|
| `frontend/src/pages/ProjectsHomePage.tsx` | Projects list |
| `frontend/src/pages/ProjectDetailPage.tsx` | Project detail |
| `frontend/src/pages/PackageDetailPage.tsx` | Package detail |
| `frontend/src/pages/OverviewPage.tsx` | Atlas overview dashboard |
| `frontend/src/pages/FmsPage.tsx` | FMS page |
| `frontend/src/pages/LendersCompliancePage.tsx` | Lenders compliance page |
| `frontend/src/pages/HistoryPage.tsx` + `frontend/src/pages/history/` | Domain change history UI |
| `frontend/src/pages/data/` (entire directory) | Data-entry pages (bills, packages, office notes, funding, TDS, agencies, …) |
| `frontend/src/components/bills/` | Bill UI |
| `frontend/src/components/packages/` | Package UI |
| `frontend/src/components/projects/` | Project UI |
| `frontend/src/components/office-notes/` | Office notes UI |
| `frontend/src/components/funding/` | Funding UI |
| `frontend/src/components/lenders-compliance/` | Lenders compliance UI |
| `frontend/src/components/data-entry/` | Domain data-entry dialogs/forms |
| `frontend/src/components/history/` | History UI |
| `backend/migrations/versions/` (62 files) | Atlas schema history |
| `backend/app/history/` | Domain row change-history services |
| `backend/app/schemas/` except `errors.py` and `pagination.py` | Domain request/response schemas |
| `shared/history_changed_count_cases.json` | Atlas history fixture data |

## 4. Rename map

Actual identifiers found via case-insensitive `atlas` greps / file reads. Replace with Accord equivalents when transplanting.

### App / product name strings

| Identifier | Location (verified) |
|------------|---------------------|
| `APP_NAME = "Atlas"` | `frontend/src/lib/branding.ts:1` |
| `APP_SUBTITLE = "HAM"` | `frontend/src/lib/branding.ts:2` |
| `APP_ORGANIZATION = "Innovastra"` | `frontend/src/lib/branding.ts:3` |
| `<title>Atlas</title>` | `frontend/index.html:10` |
| meta description `"Atlas — HAM Expenditure Tracker for MSIDC"` | `frontend/index.html:6` |
| `<title>Atlas</title>` | `frontend/src/favicon.svg:2` |
| `const APP_NAME = "Atlas"` + login copy | `frontend/src/pages/LoginPage.tsx:13,15,145,153` |
| default header title `"Atlas"` | `frontend/src/contexts/AppShellContext.tsx:27` |
| FastAPI `title="Atlas API"` | `backend/app/main.py:140` |
| docstring `"""Atlas API — …"""` | `backend/app/main.py:1` |
| maintenance copy mentioning `"Atlas"` | `backend/app/main.py:193` |
| `DEV_UI_APP_ID="atlas"` / `DEV_UI_APP_NAME="Atlas"` | `scripts/generate-api-types.sh:11-12` |
| README `# Atlas` product description | `README.md` |

### Package names

| Identifier | Location |
|------------|----------|
| `"name": "atlas"` | root `package.json:2` |
| `"name": "frontend"` | `frontend/package.json:2` (not Atlas-branded; keep or rename to `accord-frontend` as desired) |
| `pyproject.toml` | **No** `[project].name` / no `"atlas"` package name (Ruff/pytest tooling only) |

### localStorage / sessionStorage keys / prefixes

| Key | Location |
|-----|----------|
| `ATLAS_THEME` | `frontend/src/theme-init.ts:6`, `frontend/src/lib/ui/providers/theme-provider.tsx:5`, `frontend/src/App.tsx:27` |
| `atlas:sidebar:width:px` | `frontend/src/components/ui/sidebar.tsx:24` |
| `ornament:sidebar:width:px` (legacy migrate-from) | `frontend/src/components/ui/sidebar.tsx:25` |
| `atlas:data-nav:open` | `frontend/src/components/app-sidebar.tsx:46` |
| `atlas:reports-nav:open` | `frontend/src/components/app-sidebar.tsx:47` |
| `atlas:bills:columns:v2` | `frontend/src/pages/data/DataBillsSection.tsx:105` (domain; exclude with page) |
| `atlas:pkg-bills:columns` | `frontend/src/pages/PackageDetailPage.tsx:213` (domain; exclude with page) |
| `auth_error` (sessionStorage) | `frontend/src/lib/api/http.ts` / `LoginPage.tsx` (generic name, not Atlas-prefixed) |

### Cookie names

| Cookie | Location |
|--------|----------|
| `sidebar_state` | `frontend/src/components/ui/sidebar.tsx:22` (`SIDEBAR_COOKIE_NAME`) — generic, not Atlas-prefixed; still review for Accord |

### Env var prefixes / values

| Identifier | Location / notes |
|------------|------------------|
| `ATLAS_DB_USER`, `ATLAS_DB_PASSWORD`, `ATLAS_DB_NAME`, `ATLAS_TEST_DB_NAME` | `scripts/start.sh`, `scripts/dev-setup.sh`, `scripts/test-backend.sh` |
| `ATLAS_PG_DATA_DIR`, `ATLAS_PG_LABEL`, `ATLAS_PG_PLIST`, `ATLAS_PG_LOG_FILE`, `ATLAS_PG_WORKING_DIR`, `ATLAS_HOMEBREW_PREFIX` | `scripts/dev-setup.sh` |
| `ATLAS_TAG` | `deploy/docker-compose.yml`, `deploy/set-atlas-tag.sh`, `deploy/.env.example:32` |
| `ATLAS_DEPLOY_DIR`, `ATLAS_DEPLOY_LOCK_FILE` | `deploy/deploy-atlas.sh` |
| `ATLAS_RESET_ALLOW_UNATTENDED`, `ATLAS_RESET_ALLOW_NON_VM`, `ATLAS_RESET_AUDIT_DIR` | `deploy/reset_database.sh` |
| `ATLAS_ALLOW_WEAK_SECRETS` | `backend/tests/conftest.py:30` |
| `ATLAS_PACKAGE_MANAGER_LOADED` | `scripts/lib/package-manager.sh` |
| Default DB user/db `atlas` | `docker-compose.yml`, `deploy/docker-compose.yml`, `backend/.env.example`, `backend/migrations/env.py` |
| `dev@atlas.local` | `backend/app/config.py:21`, `backend/.env.example:14`, `docker-compose.yml:28` |
| `FIREBASE_PROJECT_ID=atlas-main-d05c8` | `backend/.env.example:11`, `deploy/.env.example:14` |
| `VITE_API_BASE_URL`, `VITE_FIREBASE_*`, `VITE_AUTH_REQUIRED`, `VITE_DEV_AUTH_BYPASS`, `VITE_DEV_AUTH_EMAIL`, `VITE_E2E_TEST_*` | `frontend/src/vite-env.d.ts:4-15` |
| `CORS_ORIGINS=…https://atlas.innovastra.app` | `deploy/docker-compose.yml:62`, `deploy/.env.example:27` |
| Host paths `/opt/atlas/...` | `deploy/.env.example`, `deploy/deploy-atlas.sh`, `deploy/reset_database.sh` |

### Docker image / compose service names

| Identifier | Location |
|------------|----------|
| `ghcr.io/ornament-ai/atlas/backend:${ATLAS_TAG:-latest}` | `deploy/docker-compose.yml:36,53` |
| `ghcr.io/ornament-ai/atlas/web:${ATLAS_TAG:-latest}` | `deploy/docker-compose.yml:104` |
| `REGISTRY: ghcr.io/ornament-ai/atlas` | `.github/workflows/deploy.yml` |
| Compose services (local): `postgres`, `backend` | `docker-compose.yml` |
| Compose services (deploy): `db`, `migrate`, `backend`, `web` | `deploy/docker-compose.yml` |
| No `container_name:` entries found | — |
| Base images (no Atlas name): `python:3.14.6-slim`, `node:24.18.0-alpine`, `nginx:1.30-alpine`, `postgres:18.4-alpine` | Dockerfiles / compose |

### Other code identifiers to rename

| Identifier | Location |
|------------|----------|
| `application_name`: `"atlas-api"` | `backend/app/db.py:39` |
| probe UID `"atlas-startup-probe"` | `backend/app/main.py:103` |
| CSS `--atlas-motion-*`, `.atlas-motion-*`, `@keyframes atlas-*` | `frontend/src/index.css` |
| `atlasMotion` export | `frontend/src/lib/motion.ts` |
| `ATLAS_TIME_ZONE` / `formatDateInAtlasTimeZone` / `todayInAtlasTimeZone` | `frontend/src/lib/utils.ts` |
| `datedAtlasExportFilename` → `atlas-{slug}-{date}.{ext}` | `frontend/src/lib/export-filenames.ts:8-9` |
| Error IDs `ATLAS_STREAMED_UPLOAD_CLEANUP_FAILED`, `ATLAS_ORPHAN_FILE_CLEANUP_FAILED`, `ATLAS_UPLOAD_ROLLBACK_CLEANUP_FAILED` | `backend/app/services/upload.py`, `file_cleanup.py` |
| Deploy script filenames `deploy-atlas.sh`, `deploy-atlas-wrapper.sh`, `set-atlas-tag.sh` | `deploy/` |
| CSP Firebase host `atlas-main-d05c8.firebaseapp.com` | `deploy/nginx/nginx.conf:55` |

## 5. License checklist

### Apache-2.0 notices in Atlas

| Item | Finding |
|------|---------|
| Root `LICENSE` | **Not present** in Atlas at this commit (`test -e LICENSE` → missing) |
| Root `NOTICE` | **Not present** |
| SPDX / Apache license headers in source | **None found** via repo search for `Apache License` / `SPDX-License` |
| `git ls-files '*LICENSE*'` | Only font OFL files (below) |

> Accord already has an Apache-2.0 `LICENSE` at the Accord repo root. Atlas itself does not ship Apache notice files at this commit; preserve Accord’s own LICENSE when scaffolding, and do not invent an Atlas NOTICE that is not upstream.

### Font OFL files (preserve verbatim when copying fonts)

| Path | Covers |
|------|--------|
| `frontend/public/fonts/OFL.txt` | IBM Plex (SIL OFL 1.1) |
| `frontend/public/fonts/noto-sans-devanagari-OFL.txt` | Noto Sans Devanagari (SIL OFL 1.1) |
| `backend/app/assets/licenses/NotoFonts-OFL.txt` | Backend Noto TTF assets (SIL OFL 1.1) |

### Other third-party attribution

| Item | Finding |
|------|---------|
| Dedicated third-party `NOTICE` / `ATTRIBUTIONS` file | **Not found** |
| Build-artifact copies under `frontend/dist/fonts/` | Exist as build output; prefer source paths under `frontend/public/fonts/` |

## 6. Stack versions

Exact pins as read from files. Source noted.

| Component | Version | Source |
|-----------|---------|--------|
| Python (image / runtime) | **3.14.6** | `backend/Dockerfile` (`FROM python:3.14.6-slim`) |
| Python constraint | **>=3.14** | `uv.lock` (`requires-python`) |
| `.python-version` | **absent** | — |
| Ruff format target | **py313** | `pyproject.toml` (comment notes CI/images use 3.14) |
| FastAPI | **0.139.0** | `backend/requirements.txt` (`fastapi[standard]==0.139.0`) |
| SQLModel | **0.0.39** | `backend/requirements.txt` |
| SQLAlchemy | **2.0.51** | `backend/requirements.txt` (`sqlalchemy[asyncio]==2.0.51`) |
| Alembic | **1.18.5** | `backend/requirements.txt` |
| pydantic-settings | **2.14.2** | `backend/requirements.txt` |
| Pydantic (core) | **not directly pinned** in requirements; installed **2.13.4** in `backend/.venv` (`pydantic==2.13.4`, `pydantic_core==2.46.4` via `pip freeze`) | transitive of FastAPI / pydantic-settings |
| uvicorn | **0.50.0** | `backend/requirements.txt` |
| structlog | **26.1.0** | `backend/requirements.txt` |
| pytest | **9.1.1** | `backend/requirements-dev.txt` |
| pytest-asyncio | **1.4.0** | `backend/requirements-dev.txt` |
| httpx (dev) | **0.28.1** | `backend/requirements-dev.txt` |
| ruff | **0.15.20** | `backend/requirements-dev.txt` |
| Node engines | **>=22.22.0** | `frontend/package.json` `engines.node` |
| Node (CI / Docker) | **24.18.0** | `.github/workflows/ci.yml` (`node-version: "24.18.0"`), `deploy/Dockerfile.web` (`node:24.18.0-alpine`) |
| `.nvmrc` | **absent** | — |
| pnpm | **10.34.3** | root `package.json` `packageManager` |
| React | **19.2.7** | `frontend/package.json` + lock |
| react-dom | **19.2.7** | `frontend/package.json` + lock |
| Vite | **8.1.0** | `frontend/package.json` + lock |
| TypeScript (alias `typescript`) | **npm:@typescript/typescript6@6.0.1** | `frontend/package.json` |
| TypeScript 7 toolchain | **npm:typescript@7.0.1-rc** (as `typescript-7`) | `frontend/package.json` |
| Tailwind CSS | **4.3.1** | `frontend/package.json` (`tailwindcss`, `@tailwindcss/vite`) |
| TanStack Query | **5.101.2** | `frontend/package.json` (`@tanstack/react-query`) |
| TanStack Table | **8.21.3** | `frontend/package.json` |
| Vitest | **4.1.9** | `frontend/package.json` |
| @testing-library/react | **16.3.2** | `frontend/package.json` |
| @testing-library/jest-dom | **6.9.1** | `frontend/package.json` |
| jsdom | **29.1.1** | `frontend/package.json` |
| Playwright | **not installed** | absent from `frontend/package.json` / root `package.json`; no Playwright project config found |
| @base-ui/react | **1.6.0** | `frontend/package.json` |
| motion | **12.42.0** | `frontend/package.json` |
| sonner | **2.0.7** | `frontend/package.json` |
| react-router | **8.0.1** | `frontend/package.json` |
| Postgres (compose) | **18.4-alpine** | `docker-compose.yml`, `deploy/docker-compose.yml` |
| nginx (web image) | **1.30-alpine** | `deploy/Dockerfile.web` |

**Note:** Root `uv.lock` is **not** a full Python dependency lockfile; authoritative backend pins are `backend/requirements.txt` and `backend/requirements-dev.txt`.

## 7. Visual parity checklist

Manual checks after transplant, based on behaviors observed in Atlas frontend code:

- [ ] Light-mode CSS variables from `:root` in `frontend/src/index.css` match Atlas (warm “Delta Warm Earthy” OKLCH palette: background/foreground/card/primary/sidebar/chart tokens)
- [ ] Dark-mode `.dark` variables match Atlas (default app theme is **dark** via `ThemeProvider defaultTheme="dark"` in `App.tsx`)
- [ ] `ThemeProvider` themes `dark` \| `light` \| `system` work; FOUC guard in `theme-init.ts` runs before paint
- [ ] Theme preference persists under the renamed storage key (was `ATLAS_THEME`)
- [ ] `theme-switcher` 3-way control (system / light / dark) renders and cycles correctly in shell and compact sidebar modes
- [ ] IBM Plex Sans 400/500/600/700 render from local `public/fonts/*.woff2` `@font-face` rules
- [ ] IBM Plex Mono 400 renders for mono stacks (`--app-font-mono`)
- [ ] Noto Sans Devanagari renders for Devanagari text (unicode-range face + `--app-font-devanagari` fallback stack)
- [ ] Font OFL files remain alongside copied font binaries
- [ ] Sidebar expand/collapse works; cookie `sidebar_state` persists open state
- [ ] Sidebar drag-resize works (`use-sidebar-resize.ts`); width clamped ~240–520px and persisted (was `atlas:sidebar:width:px`)
- [ ] Keyboard shortcut Ctrl/Cmd+B toggles sidebar (from `sidebar.tsx`)
- [ ] Mobile sidebar uses sheet/off-canvas behavior (`SIDEBAR_WIDTH_MOBILE`)
- [ ] App shell composition: `ProtectedShell` → `AppLayout` → `PageShell` / `PageToolbar` / `AppSidebar` / `SiteHeader`
- [ ] Inset sidebar variant and header height (`--header-height`) match Atlas spacing
- [ ] Page transition: non-table routes fade + slight `translateY`; table-heavy routes use stable transition (no flicker)
- [ ] Dialog / alert-dialog / sheet overlay styling matches (dark overlay + backdrop blur observed in theme CSS)
- [ ] Popover / dropdown / tooltip motion classes (`.atlas-motion-*` → renamed) and reduced-motion hard-cut respect `prefers-reduced-motion`
- [ ] Table styling: `ui/table`, sortable headers, data-table shell, skeleton, pagination controls
- [ ] Form controls (input, select, combobox, checkbox, textarea, date/month pickers) match Atlas density and focus rings
- [ ] Loading states (`loading-state`, `spinner`, `skeleton`) match
- [ ] Empty states (`empty-state` / `ui/empty`) match
- [ ] Error states (`error-boundary`, `error-with-retry`, `invalid-route-state`) match
- [ ] Toast/notifications: lazy Sonner toaster; App wires `position="top-center"`; light/dark toast token overrides in `index.css`
- [ ] Focus-visible rings and disabled styles on buttons/inputs match
- [ ] Custom thin scrollbars and table scroll/surface utilities match
- [ ] Brand mark in sidebar/header uses Accord name (was `APP_NAME` / `APP_SUBTITLE`) without Atlas/HAM copy
- [ ] Login page visual layout parity after copy rewrite (same shell/typography, new product strings)
- [ ] Responsive layout: desktop inset shell + mobile collapsed sidebar / stacked toolbar
- [ ] Motion: `LazyMotion` + `MotionConfig reducedMotion="user"` still applied at app root
