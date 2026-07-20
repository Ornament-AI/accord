#!/usr/bin/env bash
# Destructive reset for allowlisted local test databases only (ADR 0011).
# Never invoked automatically by Playwright, CI defaults, or dev-setup.
set -euo pipefail

ALLOWLIST_DBS=("accord_e2e" "accord_test")

usage() {
  cat <<'EOF'
Usage:
  scripts/reset_e2e_db.sh --i-understand-this-deletes-data [--db NAME]

Drops and recreates a local Postgres database used for Accord e2e/tests.
Refuses any database name outside the allowlist: accord_e2e, accord_test.
Prints the exact target before destroying data.
EOF
}

CONFIRM=""
DB_NAME="${ACCORD_E2E_DB_NAME:-accord_e2e}"
HOST="${PGHOST:-127.0.0.1}"
PORT="${PGPORT:-5432}"
USER_NAME="${PGUSER:-accord}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --i-understand-this-deletes-data)
      CONFIRM="yes"
      shift
      ;;
    --db)
      DB_NAME="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$CONFIRM" != "yes" ]]; then
  echo "Refusing to run: pass --i-understand-this-deletes-data explicitly." >&2
  usage >&2
  exit 2
fi

allowed=0
for name in "${ALLOWLIST_DBS[@]}"; do
  if [[ "$DB_NAME" == "$name" ]]; then
    allowed=1
    break
  fi
done
if [[ "$allowed" -ne 1 ]]; then
  echo "Refusing non-test database name '$DB_NAME' (allowlist: ${ALLOWLIST_DBS[*]})." >&2
  exit 2
fi

echo "About to DROP and recreate database:"
echo "  host=$HOST port=$PORT user=$USER_NAME dbname=$DB_NAME"
echo "This permanently deletes all data in that database."

dropdb --if-exists -h "$HOST" -p "$PORT" -U "$USER_NAME" "$DB_NAME"
createdb -h "$HOST" -p "$PORT" -U "$USER_NAME" "$DB_NAME"
echo "Recreated $DB_NAME. Run migrations (e.g. scripts/start.sh or alembic upgrade head),"
echo "then: backend/.venv/bin/python scripts/provision_organization.py --name ... --slug ... --admin-email ..."
