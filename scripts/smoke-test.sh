#!/usr/bin/env bash
# Accord Smoke Test — verifies a running deployment is healthy.
#
# Usage:
#   ./scripts/smoke-test.sh                       # default: http://127.0.0.1:8082
#   ./scripts/smoke-test.sh http://10.0.0.5:8080   # custom base URL
#
# Adapted from Atlas deploy/smoke-test.sh (v1.1.0): default target points at
# the local deploy/docker-compose.yml `web` port (127.0.0.1:8082) instead of
# a fixed production domain; Docker service names renamed db/backend/web ->
# postgres/api/web; the Atlas-domain auth-probe path (/api/bills) is replaced
# with a generic readyz-based check since Accord has no such route yet — full
# authn-enforcement smoke coverage should be added once the API surface
# exists.
#
# Exit codes:
#   0  — all checks passed
#   1  — one or more checks failed

set -uo pipefail

G='\033[0;32m' Y='\033[1;33m' R='\033[0;31m' N='\033[0m'
info() { echo -e "${G}✓${N} $1"; }
warn() { echo -e "${Y}!${N} $1"; }
die()  { echo -e "${R}✗${N} $1" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---- Base URL ---------------------------------------------------------------
BASE_URL="${1:-http://127.0.0.1:8082}"
# Strip trailing slash
BASE_URL="${BASE_URL%/}"

# ---- Counters ---------------------------------------------------------------
PASS=0
FAIL=0
SKIP=0

check_pass() { PASS=$((PASS + 1)); info "$1"; }
check_fail() { FAIL=$((FAIL + 1)); echo -e "${R}✗${N} $1"; }
check_skip() { SKIP=$((SKIP + 1)); warn "$1 (skipped)"; }

echo ""
echo "Accord Smoke Test"
echo "=================="
echo "Target: $BASE_URL"
echo ""

# ---- 1. Health check (/api/healthz) ----------------------------------------
echo "--- Health check ---"
HTTP_CODE="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$BASE_URL/api/healthz" 2>/dev/null)"
HTTP_CODE="${HTTP_CODE:-000}"
if [[ "$HTTP_CODE" == "200" ]]; then
    check_pass "GET /api/healthz returned 200"
else
    check_fail "GET /api/healthz returned $HTTP_CODE (expected 200)"
fi

# ---- 2. Readiness check (/api/readyz) --------------------------------------
echo "--- Readiness check ---"
READYZ_BODY="$(curl -s -m 10 "$BASE_URL/api/readyz" 2>/dev/null)"
READYZ_CODE="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$BASE_URL/api/readyz" 2>/dev/null)"
READYZ_CODE="${READYZ_CODE:-000}"
if [[ "$READYZ_CODE" == "200" ]]; then
    if echo "$READYZ_BODY" | grep -q '"database".*:.*"ok"'; then
        check_pass "GET /api/readyz returned 200 with database: ok"
    else
        check_fail "GET /api/readyz returned 200 but missing database: ok in response"
    fi
else
    check_fail "GET /api/readyz returned $READYZ_CODE (expected 200)"
fi

# ---- 3. Web root reachable ---------------------------------------------------
echo "--- Web root ---"
WEB_CODE="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$BASE_URL/" 2>/dev/null)"
WEB_CODE="${WEB_CODE:-000}"
if [[ "$WEB_CODE" == "200" ]]; then
    check_pass "GET / returned 200"
else
    check_fail "GET / returned $WEB_CODE (expected 200)"
fi

# ---- 4. Docker services running ---------------------------------------------
echo "--- Docker services ---"
if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    REQUIRED_SERVICES="postgres api web"
    for svc in $REQUIRED_SERVICES; do
        if (cd "$ROOT" && docker compose -f deploy/docker-compose.yml ps --status running --format '{{.Service}}' 2>/dev/null | grep -qx "$svc"); then
            SVC_STATUS=$(cd "$ROOT" && docker compose -f deploy/docker-compose.yml ps "$svc" --format '{{.Status}}' 2>/dev/null)
            check_pass "Service '$svc' is running ($SVC_STATUS)"
        else
            check_fail "Service '$svc' is not running"
        fi
    done
else
    check_skip "Docker services check — docker compose not available"
fi

# ---- Summary ----------------------------------------------------------------
echo ""
echo "================================"
TOTAL=$((PASS + FAIL + SKIP))
echo -e "Results: ${G}$PASS passed${N}, ${R}$FAIL failed${N}, ${Y}$SKIP skipped${N} ($TOTAL checks)"
echo "================================"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    die "Smoke test failed with $FAIL error(s)."
fi

info "All smoke tests passed."
exit 0
