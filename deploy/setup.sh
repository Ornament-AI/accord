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
			warn "Ignoring ACCORD_CONFIRMED_FRESH_INSTALL in .env; pass it for one deploy invocation only"
			continue
		fi
		if [[ ${#value} -ge 2 ]]; then
			local first="${value:0:1}" last="${value: -1}"
			if [[ "$first" == "$last" && ( "$first" == '"' || "$first" == "'" ) ]]; then
				value="${value:1:${#value}-2}"
			fi
		fi
		[[ "$value" != *'$'* && "$value" != *'`'* && "$value" != *'('* \
			&& "$value" != *')'* && "$value" != *';'* ]] \
			|| die ".env line $lineno contains unsafe shell metacharacters"
		export "$key=$value"
	done <"$envfile"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

PREVIOUS_API_IMAGE=""
PREVIOUS_WEB_IMAGE=""
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
	if $legacy_found && [[ "${ACCORD_CONFIRMED_FRESH_INSTALL:-false}" != "true" ]]; then
		die "Legacy deploy_* volumes exist while Accord volumes do not. Migrate a prior Accord install, or set ACCORD_CONFIRMED_FRESH_INSTALL=true only after proving those volumes belong to another app."
	fi
	$legacy_found && warn "Leaving unrelated legacy deploy_* volumes untouched for this confirmed fresh install"
}

command -v docker >/dev/null 2>&1 || die "Docker is not installed"
command -v curl >/dev/null 2>&1 || die "curl is not installed"
docker compose version >/dev/null 2>&1 || die "Docker Compose is not installed"

if [[ ! -f .env ]]; then
	cp .env.example .env
	chmod 600 .env
	warn "Created $SCRIPT_DIR/.env. Fill the production secrets, then rerun setup.sh."
	exit 1
fi
chmod 600 .env
safe_source_env .env
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

if [[ -n "${GHCR_TOKEN:-}" ]]; then
	printf '%s' "$GHCR_TOKEN" | docker login ghcr.io \
		-u "${GHCR_USERNAME:-deploy}" --password-stdin >/dev/null \
		|| die "GHCR login failed"
	info "GHCR login ready"
else
	warn "GHCR_TOKEN is unset; using the deploy user's existing Docker login"
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

for image in backend web; do
	ref="ghcr.io/ornament-ai/accord/$image:$ACCORD_TAG"
	revision="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$ref")"
	[[ "$revision" == "${ACCORD_TAG#sha-}" ]] \
		|| die "$ref has revision $revision instead of ${ACCORD_TAG#sha-}; production was not changed"
done
info "Pulled images have the expected revision label"

info "Starting Accord"
DEPLOY_MUTATED=true
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
	case "$service" in
		api|worker) expected="ghcr.io/ornament-ai/accord/backend:$ACCORD_TAG" ;;
		web) expected="ghcr.io/ornament-ai/accord/web:$ACCORD_TAG" ;;
	esac
	[[ "$actual" == "$expected" ]] \
		|| die "$service is running $actual instead of $expected"
	revision="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$cid")"
	[[ "$revision" == "${ACCORD_TAG#sha-}" ]] \
		|| die "$service image revision $revision does not match ${ACCORD_TAG#sha-}"
done
info "Backend, worker, and web are pinned to $ACCORD_TAG with matching revision labels"

docker compose --env-file .env run --rm --no-deps migrations alembic current \
	| grep -q '(head)' || die "Alembic is not at head"
docker compose --env-file .env logs worker 2>&1 | grep -q 'worker_started' \
	|| die "Worker startup proof is missing"

ACCORD_SMOKE_REQUIRE_DOCKER=true \
	bash "$ROOT/scripts/smoke-test.sh" "http://127.0.0.1:${ACCORD_WEB_PORT:-8085}"

info "Accord is healthy at $PUBLIC_APP_URL ($ACCORD_TAG)"
DEPLOY_SUCCEEDED=true
trap - EXIT
