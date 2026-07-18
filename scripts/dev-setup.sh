#!/usr/bin/env bash
# One-time local Postgres + backend venv bootstrap for Accord.
#
# Usage:
#   ./scripts/dev-setup.sh          # ensure role/DBs on an already-running Postgres
#   ./scripts/dev-setup.sh --start  # start Homebrew postgresql@18 first, then ensure
#
# Creates the simple local role/db that scripts/start.sh expects (ACCORD_DB_*),
# plus accord_test for pytest. Also refreshes ADR-0001 roles (accord_app /
# accord_migrator / accord_worker) against the app database when
# backend/scripts/create_roles.sql is present.
#
# Adapted from Atlas scripts/dev-setup.sh (v1.1.0): ATLAS_* -> ACCORD_*, default
# port 5432 (shared Homebrew cluster) instead of a dedicated launchd service.

set -euo pipefail

usage() {
	cat <<'EOF'
Usage:
  ./scripts/dev-setup.sh          # verify/prep native Postgres + app role/DBs
  ./scripts/dev-setup.sh --start  # start Homebrew postgresql@18 first

Environment overrides:
  PGHOST, PGPORT, PGUSER, PGPASSWORD   admin connection for setup
  ACCORD_DB_USER, ACCORD_DB_PASSWORD   local app role credentials
  ACCORD_DB_NAME, ACCORD_TEST_DB_NAME  app/test database names
  ACCORD_ROLE_PASSWORD                 password for ADR roles (default: ACCORD_DB_PASSWORD)
EOF
}

START_DB=false
case "${1:-}" in
	"")
		;;
	--start)
		START_DB=true
		shift
		;;
	-h|--help)
		usage
		exit 0
		;;
	*)
		usage >&2
		exit 2
		;;
esac
[[ $# -eq 0 ]] || { usage >&2; exit 2; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DEV_UI_APP_ID="accord"
DEV_UI_APP_NAME="Accord"
DEV_UI_COLOR="35"
# shellcheck source=scripts/lib/dev-ui.sh
source "$ROOT/scripts/lib/dev-ui.sh"
info() { ui_step "$1"; }
warn() { ui_warn "$1"; }
die()  { ui_die "$1"; }

ui_header "Dev Setup"

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
ADMIN_USER="${PGUSER:-}"
ADMIN_DB="${PGDATABASE:-postgres}"
APP_USER="${ACCORD_DB_USER:-accord}"
APP_PASSWORD="${ACCORD_DB_PASSWORD:-accord}"
APP_DB="${ACCORD_DB_NAME:-accord}"
TEST_DB="${ACCORD_TEST_DB_NAME:-accord_test}"
ROLE_PASSWORD="${ACCORD_ROLE_PASSWORD:-$APP_PASSWORD}"
ROLES_SQL="$ROOT/backend/scripts/create_roles.sql"

find_postgres_tool() {
	local tool="$1" prefix formula
	if command -v "$tool" >/dev/null 2>&1; then
		command -v "$tool"
		return 0
	fi

	if command -v brew >/dev/null 2>&1; then
		for formula in postgresql@18 postgresql; do
			prefix="$(brew --prefix "$formula" 2>/dev/null || true)"
			if [[ -n "$prefix" && -x "$prefix/bin/$tool" ]]; then
				printf '%s\n' "$prefix/bin/$tool"
				return 0
			fi
		done
	fi

	return 1
}

PSQL="$(find_postgres_tool psql || true)"
CREATEDB="$(find_postgres_tool createdb || true)"
PG_ISREADY="$(find_postgres_tool pg_isready || true)"
[[ -n "$PSQL" ]] || die "Missing psql. Install PostgreSQL locally (for macOS: brew install postgresql@18)."
[[ -n "$CREATEDB" ]] || die "Missing createdb. Install PostgreSQL locally (for macOS: brew install postgresql@18)."

ensure_homebrew_postgres() {
	local formula="" prefix=""
	[[ -n "$PG_ISREADY" ]] || die "Missing pg_isready. Install PostgreSQL locally (for macOS: brew install postgresql@18)."

	if "$PG_ISREADY" -h "$PGHOST" -p "$PGPORT" -q; then
		info "PostgreSQL already ready at $PGHOST:$PGPORT"
		return 0
	fi

	command -v brew >/dev/null 2>&1 || die "Postgres not reachable at $PGHOST:$PGPORT and Homebrew is missing. Start PostgreSQL manually and retry."

	for formula in postgresql@18 postgresql; do
		prefix="$(brew --prefix "$formula" 2>/dev/null || true)"
		if [[ -n "$prefix" ]]; then
			info "Starting Homebrew $formula via brew services"
			brew services start "$formula" >/dev/null
			break
		fi
	done
	[[ -n "$prefix" ]] || die "No Homebrew postgresql@18/postgresql formula found. Install with: brew install postgresql@18"

	for _attempt in {1..30}; do
		if "$PG_ISREADY" -h "$PGHOST" -p "$PGPORT" -q; then
			info "PostgreSQL ready at $PGHOST:$PGPORT"
			return 0
		fi
		sleep 0.5
	done

	die "PostgreSQL did not become ready at $PGHOST:$PGPORT after brew services start"
}

if [[ "$START_DB" == "true" ]]; then
	ensure_homebrew_postgres
fi

PSQL_ADMIN=("$PSQL" -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -d "$ADMIN_DB")
CREATEDB_ADMIN=("$CREATEDB" -h "$PGHOST" -p "$PGPORT")
if [[ -n "$ADMIN_USER" ]]; then
	PSQL_ADMIN+=(-U "$ADMIN_USER")
	CREATEDB_ADMIN+=(-U "$ADMIN_USER")
fi

info "Checking native Postgres at $PGHOST:$PGPORT"
if ! "${PSQL_ADMIN[@]}" -Atqc "SELECT 1" >/dev/null 2>&1; then
	die "Cannot connect to local Postgres as admin. Start it (e.g. brew services start postgresql@18) or run: ./scripts/dev-setup.sh --start"
fi

# Quote role/db identifiers safely for dynamic SQL (local identifiers only).
sql_ident() {
	local value="$1"
	[[ "$value" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "Unsafe SQL identifier: $value"
	printf '%s' "$value"
}

APP_USER_SQL="$(sql_ident "$APP_USER")"
APP_DB_SQL="$(sql_ident "$APP_DB")"


info "Ensuring '$APP_USER' local app role"
# CREATE ROLE cannot take a psql :'var' password inside DO; create then ALTER.
"${PSQL_ADMIN[@]}" <<SQL >/dev/null
DO \$\$
BEGIN
	IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$APP_USER_SQL') THEN
		CREATE ROLE "$APP_USER_SQL" LOGIN SUPERUSER CREATEDB;
	END IF;
END
\$\$;
SQL
"${PSQL_ADMIN[@]}" -v app_password="$APP_PASSWORD" <<SQL >/dev/null
ALTER ROLE "$APP_USER_SQL" WITH LOGIN SUPERUSER CREATEDB PASSWORD :'app_password';
SQL

ensure_db() {
	local db_name="$1"
	local db_sql
	db_sql="$(sql_ident "$db_name")"
	if "${PSQL_ADMIN[@]}" -Atqc "SELECT 1 FROM pg_database WHERE datname = '$db_sql'" | grep -qx 1; then
		info "$db_name database already exists"
	else
		"${CREATEDB_ADMIN[@]}" -O "$APP_USER" "$db_name"
		info "Created $db_name database"
	fi
	"${PSQL_ADMIN[@]}" -qc "ALTER DATABASE \"$db_sql\" OWNER TO \"$APP_USER_SQL\";" >/dev/null
}

ensure_db "$APP_DB"
ensure_db "$TEST_DB"

info "Verified app/test database access"
if ! PGPASSWORD="$APP_PASSWORD" "$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$APP_USER" -d "$APP_DB" -Atqc "SELECT 1" >/dev/null 2>&1; then
	die "Cannot connect as $APP_USER to $APP_DB after bootstrap"
fi
if ! PGPASSWORD="$APP_PASSWORD" "$PSQL" -h "$PGHOST" -p "$PGPORT" -U "$APP_USER" -d "$TEST_DB" -Atqc "SELECT 1" >/dev/null 2>&1; then
	die "Cannot connect as $APP_USER to $TEST_DB after bootstrap"
fi

if [[ -f "$ROLES_SQL" ]]; then
	info "Ensuring ADR-0001 roles (accord_app / accord_migrator / accord_worker)"
	"${PSQL_ADMIN[@]}" -f "$ROLES_SQL" >/dev/null
	"${PSQL_ADMIN[@]}" -d "$APP_DB" \
		-v role_password="$ROLE_PASSWORD" \
		-v db_name="$APP_DB_SQL" <<'EOSQL' >/dev/null
ALTER ROLE accord_migrator WITH PASSWORD :'role_password';
ALTER ROLE accord_app WITH PASSWORD :'role_password';
ALTER ROLE accord_worker WITH PASSWORD :'role_password';
GRANT ALL ON SCHEMA public TO accord_migrator;
GRANT USAGE ON SCHEMA public TO accord_app, accord_worker;
GRANT CONNECT ON DATABASE :"db_name" TO accord_app, accord_migrator, accord_worker;
EOSQL
	info "ADR roles ready on $APP_DB"
else
	warn "Skipping ADR roles — missing $ROLES_SQL"
fi

if [[ ! -f backend/.venv/bin/activate ]]; then
	info "Creating backend virtualenv"
	python3 -m venv backend/.venv
	backend/.venv/bin/pip install -q --upgrade pip
	backend/.venv/bin/pip install -q -r backend/requirements.txt -r backend/requirements-dev.txt
	info "Created backend virtualenv"
else
	info "Backend virtualenv already present"
fi

echo ""
info "Development environment ready!"
echo ""
echo "  Start app:        ./scripts/start.sh"
echo "  Native Postgres:  $APP_DB and $TEST_DB on $PGHOST:$PGPORT as $APP_USER"
echo "  ADR DSNs (opt):   see backend/.env.example (accord_app / accord_migrator)"
echo ""
