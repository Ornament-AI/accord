#!/usr/bin/env bash
# Accord MSIDC setup/update entrypoint. It only deploys immutable images and
# preserves the host-owned .env file across bundle updates.

set -euo pipefail

G='\033[0;32m' Y='\033[1;33m' R='\033[0;31m' N='\033[0m'
info() { echo -e "${G}✓${N} $1"; }
warn() { echo -e "${Y}!${N} $1"; }
die() { echo -e "${R}✗${N} $1" >&2; exit 1; }

safe_source_env() {
	local envfile="$1"
	local line key value lineno=0
	while IFS= read -r line || [[ -n "$line" ]]; do
		lineno=$((lineno + 1))
		line="${line#"${line%%[![:space:]]*}"}"
		line="${line%"${line##*[![:space:]]}"}"
		[[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
		[[ "$line" == export\ * ]] && line="${line#export }"
		key="${line%%=*}"
		value="${line#*=}"
		key="${key%"${key##*[![:space:]]}"}"
		key="${key#"${key%%[![:space:]]*}"}"
		value="${value#"${value%%[![:space:]]*}"}"
		value="${value%"${value##*[![:space:]]}"}"
		[[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
			|| die ".env line $lineno has an invalid variable name"
		if [[ "$key" == "ACCORD_CONFIRMED_FRESH_INSTALL" ]]; then
			warn "Ignoring obsolete ACCORD_CONFIRMED_FRESH_INSTALL in .env"
			continue
		fi
		if [[ "$key" == "GHCR_USERNAME" || "$key" == "GHCR_TOKEN" \
			|| "$key" == "ACCORD_RELEASE_GHCR_USERNAME" \
			|| "$key" == "ACCORD_RELEASE_GHCR_TOKEN" ]]; then
			warn "Ignoring registry credential $key in .env; credentials are invocation-only"
			continue
		fi
		case "$key" in
			ACCORD_DB_PASSWORD|ACCORD_DB_USER|ACCORD_DB_NAME|ACCORD_TAG|ACCORD_WEB_PORT|\
			DATABASE_URL|MIGRATIONS_DATABASE_URL|WORKER_DATABASE_URL|WORKOS_CLIENT_ID|\
			WORKOS_API_KEY|WORKOS_REDIRECT_URI|WORKOS_WEBHOOK_SECRET|SESSION_SECRET_KEY|\
			SESSION_COOKIE_NAME|ENVIRONMENT|CORS_ORIGINS|PUBLIC_APP_URL|BASE_URL|LOG_LEVEL|\
			DEV_AUTH_BYPASS|DB_POOL_SIZE|DB_STATEMENT_TIMEOUT_MS|OBJECT_STORAGE_ENDPOINT|\
			OBJECT_STORAGE_BUCKET|OBJECT_STORAGE_ACCESS_KEY|OBJECT_STORAGE_SECRET_KEY)
				;;
			*) die ".env line $lineno uses unsupported variable $key" ;;
		esac
		if [[ ${#value} -ge 2 ]]; then
			local first="${value:0:1}" last="${value: -1}"
			if [[ "$first" == "$last" && ( "$first" == '"' || "$first" == "'" ) ]]; then
				value="${value:1:${#value}-2}"
			fi
		fi
		# Values are assigned literally (no eval/source), so shell
		# metacharacters cannot be interpreted here. Rejecting them would
		# break strong auto-generated secrets (e.g. containing $, (, ), ;).
		export "$key=$value"
	done <"$envfile"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

PREVIOUS_API_IMAGE=""
PREVIOUS_WEB_IMAGE=""
REGISTRY_CONFIG=""
DEPLOY_MUTATED=false
DEPLOY_SUCCEEDED=false
diagnose_failure() {
	local code=$?
	trap - EXIT
	if (( code != 0 )) && $DEPLOY_MUTATED && ! $DEPLOY_SUCCEEDED; then
		warn "Deployment failed. Accord was not declared healthy."
		docker compose --env-file .env ps 2>/dev/null || true
		docker compose --env-file .env logs --tail 80 2>/dev/null || true
		[[ -z "$PREVIOUS_API_IMAGE" ]] || warn "Previous backend image: $PREVIOUS_API_IMAGE"
		[[ -z "$PREVIOUS_WEB_IMAGE" ]] || warn "Previous web image: $PREVIOUS_WEB_IMAGE"
		warn "Do not downgrade Alembic automatically. Restore the prior tag only after checking migration compatibility."
	fi
	[[ -z "$REGISTRY_CONFIG" ]] || rm -rf -- "$REGISTRY_CONFIG"
	exit "$code"
}
trap diagnose_failure EXIT

guard_persistent_volume_ownership() {
	local current_count=0 legacy_found=false
	for volume in accord_pgdata accord_minio-data; do
		docker volume inspect "$volume" >/dev/null 2>&1 && current_count=$((current_count + 1))
	done
	(( current_count == 2 )) && return 0
	(( current_count == 0 )) \
		|| die "Accord persistent volumes are incomplete; restore the missing volume before deploying"
	for volume in deploy_pgdata deploy_minio-data; do
		docker volume inspect "$volume" >/dev/null 2>&1 && legacy_found=true
	done
	if $legacy_found; then
		die "Legacy deploy_* volumes exist while Accord volumes do not. Migrate the prior Accord install or remove only separately proved unrelated volumes before using the authenticated fresh-host bootstrap."
	fi
	return 0
}

command -v docker >/dev/null 2>&1 || die "Docker is not installed"
command -v curl >/dev/null 2>&1 || die "curl is not installed"
docker compose version >/dev/null 2>&1 || die "Docker Compose is not installed"

REQUESTED_SHA="${ACCORD_EXPECTED_SHA:-}"
EPHEMERAL_GHCR_USERNAME="${ACCORD_RELEASE_GHCR_USERNAME:-}"
EPHEMERAL_GHCR_TOKEN="${ACCORD_RELEASE_GHCR_TOKEN:-}"
[[ -f .env && ! -L .env ]] || die "$SCRIPT_DIR/.env must be a regular non-symlink file"
safe_source_env .env
unset GHCR_USERNAME GHCR_TOKEN ACCORD_RELEASE_GHCR_USERNAME ACCORD_RELEASE_GHCR_TOKEN
if [[ -n "$REQUESTED_SHA" ]]; then
	[[ "$REQUESTED_SHA" =~ ^[0-9a-f]{40}$ ]] || die "ACCORD_EXPECTED_SHA is invalid"
	export ACCORD_EXPECTED_SHA="$REQUESTED_SHA"
	export ACCORD_TAG="sha-$REQUESTED_SHA"
fi
ACCORD_WEB_PORT_VALUE="${ACCORD_WEB_PORT:-8085}"

[[ "${ACCORD_TAG:-}" =~ ^sha-[0-9a-f]{40}$ ]] \
	|| die "ACCORD_TAG must be an immutable sha-<40 lowercase hex> tag"
if [[ -n "${ACCORD_EXPECTED_SHA:-}" && "$ACCORD_TAG" != "sha-$ACCORD_EXPECTED_SHA" ]]; then
	die "ACCORD_TAG does not match the requested deployment SHA"
fi
[[ "$ACCORD_WEB_PORT_VALUE" =~ ^[0-9]+$ ]] \
	&& (( ACCORD_WEB_PORT_VALUE >= 1 && ACCORD_WEB_PORT_VALUE <= 65535 )) \
	|| die "ACCORD_WEB_PORT must be a valid TCP port"
[[ "${ENVIRONMENT:-}" == "production" ]] || die "ENVIRONMENT must be production"
[[ "${DEV_AUTH_BYPASS:-}" == "false" ]] || die "DEV_AUTH_BYPASS must be false"

MISSING=""
for var in ACCORD_DB_PASSWORD WORKOS_CLIENT_ID WORKOS_API_KEY \
	WORKOS_WEBHOOK_SECRET SESSION_SECRET_KEY OBJECT_STORAGE_ACCESS_KEY \
	OBJECT_STORAGE_SECRET_KEY PUBLIC_APP_URL BASE_URL CORS_ORIGINS \
	WORKOS_REDIRECT_URI; do
	[[ -n "${!var:-}" ]] || MISSING="$MISSING $var"
done
[[ -z "$MISSING" ]] || die "Missing required variables:$MISSING"

[[ "$ACCORD_DB_PASSWORD" =~ ^[A-Za-z0-9._~-]+$ ]] \
	|| die "ACCORD_DB_PASSWORD must use URL-unreserved characters only"
(( ${#SESSION_SECRET_KEY} >= 32 )) || die "SESSION_SECRET_KEY must be at least 32 characters"
[[ "$OBJECT_STORAGE_ACCESS_KEY" != "minioadmin" \
	&& "$OBJECT_STORAGE_SECRET_KEY" != "minioadmin" ]] \
	|| die "Default MinIO credentials are forbidden in production"

PUBLIC_APP_URL="${PUBLIC_APP_URL%/}"
BASE_URL="${BASE_URL%/}"
[[ "$PUBLIC_APP_URL" =~ ^https://[^/]+$ ]] \
	|| die "PUBLIC_APP_URL must be one HTTPS origin"
[[ "$BASE_URL" == "$PUBLIC_APP_URL" ]] \
	|| die "BASE_URL must equal PUBLIC_APP_URL"
[[ "$CORS_ORIGINS" == "$PUBLIC_APP_URL" ]] \
	|| die "CORS_ORIGINS must equal PUBLIC_APP_URL"
[[ "$WORKOS_REDIRECT_URI" == "$PUBLIC_APP_URL/api/auth/callback" ]] \
	|| die "WORKOS_REDIRECT_URI must be PUBLIC_APP_URL/api/auth/callback"

if [[ -n "$EPHEMERAL_GHCR_TOKEN" ]]; then
	REGISTRY_CONFIG="$(mktemp -d /tmp/accord-docker-config.XXXXXXXXXX)"
	chmod 0700 "$REGISTRY_CONFIG"
	export DOCKER_CONFIG="$REGISTRY_CONFIG"
	printf '%s' "$EPHEMERAL_GHCR_TOKEN" | docker login ghcr.io \
		-u "$EPHEMERAL_GHCR_USERNAME" --password-stdin >/dev/null \
		|| die "GHCR login failed"
	info "GHCR login ready"
else
	die "ephemeral GHCR credentials were not provided by the operator command"
fi

docker compose --env-file .env config -q
info "Compose configuration is valid"
guard_persistent_volume_ownership

PREVIOUS_API_CID="$(docker compose --env-file .env ps -q api 2>/dev/null || true)"
PREVIOUS_WEB_CID="$(docker compose --env-file .env ps -q web 2>/dev/null || true)"
[[ -z "$PREVIOUS_API_CID" ]] \
	|| PREVIOUS_API_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$PREVIOUS_API_CID" 2>/dev/null || true)"
[[ -z "$PREVIOUS_WEB_CID" ]] \
	|| PREVIOUS_WEB_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$PREVIOUS_WEB_CID" 2>/dev/null || true)"

info "Pulling Accord $ACCORD_TAG images"
docker compose --env-file .env pull --quiet

compose_image() {
	docker compose --env-file .env config --format json \
		| python3 -c 'import json,sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])' "$1"
}
for service in api worker web; do
	ref="$(compose_image "$service")"
	[[ "$ref" =~ ^ghcr\.io/ornament-ai/accord/(backend|web)@sha256:[0-9a-f]{64}$ ]] \
		|| die "$service is not pinned to an Accord image digest"
	revision="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$ref")"
	[[ "$revision" == "${ACCORD_TAG#sha-}" ]] \
		|| die "$ref has revision $revision instead of ${ACCORD_TAG#sha-}; production was not changed"
done
info "Pulled images have the expected revision label"

info "Starting Accord"
DEPLOY_MUTATED=true
[[ -z "${ACCORD_MIGRATION_STATE_FILE:-}" ]] || : >"$ACCORD_MIGRATION_STATE_FILE"
docker compose --env-file .env up -d --no-build

for _ in $(seq 1 60); do
	if curl -fsS --max-time 5 \
		"http://127.0.0.1:${ACCORD_WEB_PORT:-8085}/api/readyz" >/dev/null 2>&1; then
		break
	fi
	sleep 2
done
curl -fsS --max-time 5 \
	"http://127.0.0.1:${ACCORD_WEB_PORT:-8085}/api/readyz" >/dev/null \
	|| { docker compose --env-file .env ps; docker compose --env-file .env logs --tail 80; die "Accord readiness failed"; }

for service in api worker web; do
	cid="$(docker compose --env-file .env ps -q "$service")"
	[[ -n "$cid" ]] || die "$service container is missing"
	actual="$(docker inspect --format '{{.Config.Image}}' "$cid")"
	expected="$(compose_image "$service")"
	[[ "$actual" == "$expected" ]] \
		|| die "$service is running $actual instead of $expected"
	revision="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$cid")"
	[[ "$revision" == "${ACCORD_TAG#sha-}" ]] \
		|| die "$service image revision $revision does not match ${ACCORD_TAG#sha-}"
done
info "Backend, worker, and web are pinned to $ACCORD_TAG with matching revision labels"

docker compose --env-file .env run --rm --no-deps migrations alembic current \
	| grep -q '(head)' || die "Alembic is not at head"
info "Waiting for worker startup proof..."
WORKER_READY=false
for _ in $(seq 1 15); do
	if docker compose --env-file .env logs worker 2>&1 | grep -q 'worker_started'; then
		WORKER_READY=true
		break
	fi
	sleep 2
done
$WORKER_READY || die "Worker startup proof is missing"

ACCORD_SMOKE_REQUIRE_DOCKER=true \
	bash "$SCRIPT_DIR/smoke-test.sh" "http://127.0.0.1:${ACCORD_WEB_PORT:-8085}"

READY_BODY="$(curl -fsS --max-time 10 "http://127.0.0.1:${ACCORD_WEB_PORT:-8085}/api/readyz")"
python3 - "$READY_BODY" <<'PY'
import json
import sys

ready = json.loads(sys.argv[1])
for key in ("status", "database", "auth", "jobs", "storage", "reports"):
    expected = "ok"
    if ready.get(key) != expected:
        raise SystemExit(f"readiness field {key} is {ready.get(key)!r}, expected {expected!r}")
PY
AUTH_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 \
	"http://127.0.0.1:${ACCORD_WEB_PORT:-8085}/api/auth/me")"
[[ "$AUTH_STATUS" == "401" ]] || die "unauthenticated auth probe returned $AUTH_STATUS instead of 401"
curl -fsS --max-time 15 "$PUBLIC_APP_URL/api/readyz" >/dev/null \
	|| die "public readiness probe failed"

info "Accord is healthy at $PUBLIC_APP_URL ($ACCORD_TAG)"
DEPLOY_SUCCEEDED=true
[[ -z "$REGISTRY_CONFIG" ]] || rm -rf -- "$REGISTRY_CONFIG"
trap - EXIT
