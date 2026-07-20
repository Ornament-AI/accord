#!/usr/bin/env bash
# Run Accord's privileged singleton-organization/member provisioning CLI from
# the immutable backend image while keeping the operation off the HTTP surface.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
	cat <<'EOF'
Usage:
  deploy/provision.sh organization <name> <slug> <admin-email>
  deploy/provision.sh member <email> <role>
EOF
}

[[ -f "$SCRIPT_DIR/.env" ]] || { echo "Missing $SCRIPT_DIR/.env" >&2; exit 1; }

case "${1:-}" in
	organization)
		[[ $# -eq 4 ]] || { usage >&2; exit 2; }
		docker compose -f "$SCRIPT_DIR/docker-compose.yml" --env-file "$SCRIPT_DIR/.env" \
			run --rm --no-deps \
			-v "$ROOT/scripts:/provision/scripts:ro" \
			api python /provision/scripts/provision_organization.py \
			--name "$2" --slug "$3" --admin-email "$4"
		;;
	member)
		[[ $# -eq 3 ]] || { usage >&2; exit 2; }
		docker compose -f "$SCRIPT_DIR/docker-compose.yml" --env-file "$SCRIPT_DIR/.env" \
			run --rm --no-deps \
			-v "$ROOT/scripts:/provision/scripts:ro" \
			api python /provision/scripts/provision_member.py \
			--email "$2" --role "$3"
		;;
	*)
		usage >&2
		exit 2
		;;
esac
