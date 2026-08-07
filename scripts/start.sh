#!/usr/bin/env bash
# Start local dev environment for Accord.
#
# Usage:
#   ./scripts/start.sh                  # backend + frontend
#   ./scripts/start.sh --backend-only   # backend only
#   ./scripts/start.sh --frontend-only  # frontend only, assumes backend is up
# Stop:
#   ./scripts/stop.sh
#
# Dev-auth users are created lazily by the backend login route; the launcher
# only needs to forward the configured local identity. Listen ports are
# auto-resolved when FRONTEND_PORT / BACKEND_PORT / PGPORT are unset (see
# scripts/lib/ports.sh and scripts/lib/postgres.sh).

set -euo pipefail

START_BACKEND=1
START_FRONTEND=1
for arg in "$@"; do
	case "$arg" in
		--backend-only) START_FRONTEND=0 ;;
		--frontend-only) START_BACKEND=0 ;;
		-h|--help)
			sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*) echo "Unknown flag: $arg" >&2; exit 2 ;;
	esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ACCORD_ROOT="$ROOT"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
STATE_DIR="$ROOT/.accord-dev"
LOG_DIR="$STATE_DIR/logs"

READY_PATH=/api/readyz

PGHOST="${PGHOST:-127.0.0.1}"
APP_USER="${ACCORD_DB_USER:-accord}"
APP_PASSWORD="${ACCORD_DB_PASSWORD:-accord}"
APP_DB="${ACCORD_DB_NAME:-accord}"
DEV_AUTH_BYPASS="${DEV_AUTH_BYPASS:-true}"
DEV_AUTH_EMAIL="${DEV_AUTH_EMAIL:-dev@accord.local}"
DEV_AUTH_NAME="${DEV_AUTH_NAME:-Dev Test User}"
SESSION_SECRET_KEY="${SESSION_SECRET_KEY:-dev-only-local-session-secret}"

mkdir -p "$LOG_DIR"

DEV_UI_APP_ID="accord"
DEV_UI_APP_NAME="Accord"
DEV_UI_COLOR="35"
# shellcheck source=scripts/lib/dev-ui.sh
source "$SCRIPT_DIR/lib/dev-ui.sh"
info() { ui_step "$1"; }
warn() { ui_warn "$1"; }
die() { ui_die "$1"; }
# shellcheck source=scripts/lib/package-manager.sh
source "$SCRIPT_DIR/lib/package-manager.sh"
# shellcheck source=scripts/lib/postgres.sh
source "$SCRIPT_DIR/lib/postgres.sh"
# shellcheck source=scripts/lib/ports.sh
source "$SCRIPT_DIR/lib/ports.sh"

ui_header "Start Local Dev"

# Resolve listen ports before building URL defaults (explicit env / DATABASE_URL win).
# Backend needs a frontend origin for CORS; frontend needs a backend proxy target.
if (( START_BACKEND )); then
	resolve_pg_port
	resolve_backend_port
fi
resolve_frontend_port
if (( !START_BACKEND )); then
	if [[ -z "${BACKEND_PORT:-}" ]]; then
		if cached="$(read_cached_port backend)"; then
			BACKEND_PORT="$cached"
		else
			BACKEND_PORT="$ACCORD_BACKEND_DEFAULT_PORT"
		fi
		export BACKEND_PORT
	fi
fi

DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://$APP_USER:$APP_PASSWORD@$PGHOST:${PGPORT:-5432}/$APP_DB}"
MIGRATIONS_DATABASE_URL="${MIGRATIONS_DATABASE_URL:-$DATABASE_URL}"
CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:$FRONTEND_PORT,http://127.0.0.1:$FRONTEND_PORT}"
BASE_URL="${BASE_URL:-http://127.0.0.1:$FRONTEND_PORT}"
PUBLIC_APP_URL="${PUBLIC_APP_URL:-$BASE_URL}"
API_PROXY_TARGET="${API_PROXY_TARGET:-http://127.0.0.1:$BACKEND_PORT}"

stop_stale_pidfile() {
	local name="$1" pidfile="$STATE_DIR/$name.pid" pid
	[[ -f "$pidfile" ]] || return 0
	pid="$(tr -d '[:space:]' <"$pidfile" 2>/dev/null || true)"
	if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
		warn "stopping stale $name (pid $pid)"
		kill "$pid" 2>/dev/null || true
		sleep 0.3
		kill -9 "$pid" 2>/dev/null || true
	fi
	rm -f "$pidfile"
}

http_status() {
	curl -s -o /dev/null -m 2 -w '%{http_code}' "$1" 2>/dev/null || true
}

backend_ready() {
	[[ "$(http_status "http://127.0.0.1:$BACKEND_PORT$READY_PATH")" == "200" ]]
}

frontend_ready() {
	local status
	status="$(http_status "http://127.0.0.1:$FRONTEND_PORT/")"
	[[ "$status" == "200" || "$status" == "304" ]] || return 1
	[[ "$(http_status "http://127.0.0.1:$FRONTEND_PORT$READY_PATH")" == "200" ]]
}

if (( START_BACKEND )); then
	if [[ ! -d "$BACKEND" || ! -f "$BACKEND/requirements.txt" ]]; then
		die "backend/ lane not yet landed (missing backend/requirements.txt) — cannot start backend. Run ./scripts/start.sh --frontend-only, or wait for the backend lane."
	fi

	PSQL="$(find_postgres_tool psql || true)"
	[[ -n "$PSQL" ]] || die "psql missing. Install PostgreSQL 18 (e.g. 'brew install postgresql@18') and ensure it is running."

	if [[ ! -f "$BACKEND/.venv/bin/activate" ]]; then
		warn "Creating backend virtualenv..."
		python3 -m venv "$BACKEND/.venv"
		"$BACKEND/.venv/bin/pip" install -q --upgrade pip
		"$BACKEND/.venv/bin/pip" install -q -r "$BACKEND/requirements.txt"
		"$BACKEND/.venv/bin/pip" install -q -r "$BACKEND/requirements-dev.txt"
		info "Backend venv created"
	fi

	if ! PGPASSWORD="$APP_PASSWORD" "$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$APP_USER" -d "$APP_DB" -Atqc "SELECT 1" >/dev/null 2>&1; then
		die "Postgres not ready for $APP_DB at $PGHOST:$PGPORT as $APP_USER. Run: ./scripts/dev-setup.sh (or ./scripts/dev-setup.sh --start)"
	fi
	info "Postgres $APP_DB at $PGHOST:$PGPORT"
fi

if (( START_FRONTEND )); then
	if [[ ! -d "$FRONTEND" || ! -f "$FRONTEND/package.json" ]]; then
		die "frontend/ lane not yet landed (missing frontend/package.json) — cannot start frontend. Run ./scripts/start.sh --backend-only, or wait for the frontend lane."
	fi
	[[ -d "$FRONTEND/node_modules" ]] || die "Frontend deps missing. Run: cd frontend && pnpm install"
fi

backend_up=0
frontend_up=0
(( START_BACKEND )) && backend_ready && backend_up=1
(( START_FRONTEND )) && frontend_ready && frontend_up=1

if (( (!START_BACKEND || backend_up) && (!START_FRONTEND || frontend_up) )); then
	(( START_BACKEND )) && info "backend already running on http://127.0.0.1:$BACKEND_PORT"
	(( START_FRONTEND )) && info "frontend already running on http://127.0.0.1:$FRONTEND_PORT"
	exit 0
fi

if (( START_BACKEND && !backend_up )); then
	if port_is_listening "$BACKEND_PORT"; then
		if port_matches_pidfile "$BACKEND_PORT" "$STATE_DIR/backend.pid"; then
			stop_stale_pidfile backend
		else
			die "Backend port $BACKEND_PORT is in use by another process. Set BACKEND_PORT to a free port and retry."
		fi
	fi
	(
		cd "$BACKEND"
		if [[ -d migrations/versions ]]; then
			info "running alembic upgrade head"
			if ! DATABASE_URL="$DATABASE_URL" MIGRATIONS_DATABASE_URL="$MIGRATIONS_DATABASE_URL" PYTHONPATH=. .venv/bin/alembic upgrade head 2>&1 | tee -a "$LOG_DIR/backend.log"; then
				die "Alembic migration failed (see $LOG_DIR/backend.log)"
			fi
		else
			warn "no migrations found under backend/migrations/versions — skipping alembic upgrade"
		fi

		info "starting backend on http://127.0.0.1:$BACKEND_PORT"
		nohup env \
			DATABASE_URL="$DATABASE_URL" \
			MIGRATIONS_DATABASE_URL="$MIGRATIONS_DATABASE_URL" \
			ENVIRONMENT=development \
			DEV_AUTH_BYPASS="$DEV_AUTH_BYPASS" \
			DEV_AUTH_EMAIL="$DEV_AUTH_EMAIL" \
			DEV_AUTH_NAME="$DEV_AUTH_NAME" \
			SESSION_SECRET_KEY="$SESSION_SECRET_KEY" \
			CORS_ORIGINS="$CORS_ORIGINS" \
			BASE_URL="$BASE_URL" \
			PUBLIC_APP_URL="$PUBLIC_APP_URL" \
			.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port "$BACKEND_PORT" \
			</dev/null >>"$LOG_DIR/backend.log" 2>&1 &
		echo $! >"$STATE_DIR/backend.pid"
	)

	for _attempt in {1..30}; do
		backend_ready && break
		sleep 1
	done
	backend_ready || die "Backend failed to start (see $LOG_DIR/backend.log)"
	info "backend ready on http://127.0.0.1:$BACKEND_PORT"
elif (( START_BACKEND )); then
	info "backend already running on http://127.0.0.1:$BACKEND_PORT"
fi

if (( START_FRONTEND )); then
	frontend_up=0
	frontend_ready && frontend_up=1
fi

if (( START_FRONTEND && !frontend_up )); then
	resolve_pnpm
	if port_is_listening "$FRONTEND_PORT"; then
		if port_matches_pidfile "$FRONTEND_PORT" "$STATE_DIR/frontend.pid"; then
			stop_stale_pidfile frontend
		else
			die "Frontend port $FRONTEND_PORT is in use by another process. Set FRONTEND_PORT to a free port and retry."
		fi
	fi
	(
		cd "$FRONTEND"
		info "starting frontend on http://127.0.0.1:$FRONTEND_PORT"
		nohup env API_PROXY_TARGET="$API_PROXY_TARGET" \
			VITE_DEV_AUTH_BYPASS="$DEV_AUTH_BYPASS" \
			"${PNPM_CMD[@]}" exec vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort \
			</dev/null >>"$LOG_DIR/frontend.log" 2>&1 &
		echo $! >"$STATE_DIR/frontend.pid"
	)

	for _attempt in {1..20}; do
		frontend_ready && break
		sleep 0.5
	done
	frontend_ready || die "Frontend failed to start or proxy API traffic (see $LOG_DIR/frontend.log)"
	info "frontend ready on http://127.0.0.1:$FRONTEND_PORT"
elif (( START_FRONTEND )); then
	info "frontend already running on http://127.0.0.1:$FRONTEND_PORT"
fi

echo
info "Logs in $LOG_DIR/"
(( START_BACKEND )) && echo "  Backend:  http://127.0.0.1:$BACKEND_PORT"
(( START_FRONTEND )) && echo "  Frontend: http://127.0.0.1:$FRONTEND_PORT"
echo "  Stop:     ./scripts/stop.sh"
