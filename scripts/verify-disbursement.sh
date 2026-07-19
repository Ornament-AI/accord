#!/usr/bin/env bash
#
# verify-disbursement.sh — verify the NPS off-bill / disbursement model end to end.
#
# Background: department sign-off 18 Jul 2026 confirmed that the NPS employer
# share is OFF-BILL (never added to gross) and that the bank/RTGS total is a
# SEPARATE figure from treasury-face "Net Payable". See the "Resolved" section
# of docs/payroll-domain.md.
#
# Expected June 2026 golden figures:
#   net_payable (treasury-face)        3,838,095
#   offbill_employer_remittance (NPS)    152,943
#   employee_disbursement              3,991,038   = net_payable + off-bill NPS
#
# Usage:
#   ./scripts/verify-disbursement.sh           # core checks (no database needed)
#   ./scripts/verify-disbursement.sh --with-db # also run the DB-backed suite
#
# Exit code 0 = all executed checks passed.

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
ROOT="$(pwd)"

WITH_DB=0
[[ "${1:-}" == "--with-db" ]] && WITH_DB=1

if [[ -t 1 ]]; then
  R=$'\e[31m'; G=$'\e[32m'; Y=$'\e[33m'; B=$'\e[1m'; N=$'\e[0m'
else
  R=""; G=""; Y=""; B=""; N=""
fi

PASS=0; FAIL=0; SKIP=0
pass() { printf '%s  PASS%s  %s\n' "$G" "$N" "$1"; PASS=$((PASS+1)); }
fail() { printf '%s  FAIL%s  %s\n' "$R" "$N" "$1"; FAIL=$((FAIL+1)); }
skip() { printf '%s  SKIP%s  %s\n' "$Y" "$N" "$1"; SKIP=$((SKIP+1)); }
head() { printf '\n%s== %s ==%s\n' "$B" "$1" "$N"; }

# --- interpreter -------------------------------------------------------------
if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PY="$ROOT/backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  echo "No usable python interpreter found." >&2
  exit 1
fi
printf 'python: %s (%s)\n' "$PY" "$("$PY" --version 2>&1)"

HAVE_PYTEST=0
"$PY" -m pytest --version >/dev/null 2>&1 && HAVE_PYTEST=1

# --- 1. fixture validator ----------------------------------------------------
head "1. June 2026 fixture validator"
if "$PY" fixtures/sanitized/june-2026/validate.py >/tmp/accord_validate.log 2>&1; then
  pass "validate.py — $(grep -c '^PASS:' /tmp/accord_validate.log) checks"
else
  fail "validate.py (see /tmp/accord_validate.log)"
  grep '^FAIL' /tmp/accord_validate.log | head -20
fi

# --- 2. independent recompute of the disbursement identity -------------------
# Recomputed straight from pay.json through the engine — deliberately does NOT
# read expected_totals.json, so it is an independent check of the identity.
head "2. Engine disbursement identity (independent recompute)"
DISB_OUT="$("$PY" - <<'PYEOF' 2>&1
import json, sys
sys.path.insert(0, "backend")
try:
    from app.domain.payroll.engine import calculate_run
    from app.domain.payroll.inputs import RunCalcInput, EmployeeCalcInput, ComponentInput
    from app.domain.payroll.money import Money
    from app.domain.payroll.rounding import ROUND_NONE
except Exception as exc:  # pragma: no cover
    print("IMPORT_ERROR", exc); sys.exit(2)

pay = json.load(open("fixtures/sanitized/june-2026/pay.json"))
emps = []
for e in pay["employees"]:
    comps = tuple(
        ComponentInput(
            component_code=l["component_code"],
            classification=l["classification"],
            calc_kind="direct_monthly_amount",
            amount=Money.from_str(str(l["amount"])),
            rounding_rule=ROUND_NONE,
            informational=l.get("informational", False),
            excluded_from_totals=l.get("excluded_from_totals", False),
            employer_transfer=l.get("employer_transfer", False),
            transfer_of=l.get("transfer_of"),
            accommodation_location=l.get("accommodation_location"),
        )
        for l in e["lines"]
    )
    emps.append(EmployeeCalcInput(employee_ref=e["employee_id"], components=comps))

rr = calculate_run(RunCalcInput(period="2026-06", org_ref="ORG", employees=tuple(emps)))

net = rr.net_payable.to_canonical_str()
off = rr.offbill_employer_remittance.to_canonical_str()
dis = rr.disbursement.to_canonical_str()
sum_dis = Money.sum([x.disbursement for x in rr.employees]).to_canonical_str()
sum_net = Money.sum([x.net_payable for x in rr.employees]).to_canonical_str()

checks = [
    ("net_payable == 3838095.00", net == "3838095.00", net),
    ("offbill_employer_remittance == 152943.00", off == "152943.00", off),
    ("disbursement == 3991038.00", dis == "3991038.00", dis),
    ("disbursement == net + offbill",
     rr.disbursement == rr.net_payable + rr.offbill_employer_remittance, f"{net}+{off}"),
    ("sum(employee disbursement) == run disbursement", sum_dis == dis, sum_dis),
    ("sum(employee net_payable) == run net_payable", sum_net == net, sum_net),
    ("disbursement != net_payable (must NOT be equal)", dis != net, f"{dis} vs {net}"),
    ("per-employee identity holds for all 32",
     all(x.disbursement == x.net_payable + x.offbill_employer_remittance for x in rr.employees)
     and len(rr.employees) == 32, f"n={len(rr.employees)}"),
]
bad = 0
for label, okv, got in checks:
    print(("OK  " if okv else "BAD ") + label + ("" if okv else f"  (got {got})"))
    bad += 0 if okv else 1
sys.exit(1 if bad else 0)
PYEOF
)"
DISB_RC=$?
while IFS= read -r line; do
  case "$line" in
    OK\ *)  pass "${line#OK  }" ;;
    BAD\ *) fail "${line#BAD }" ;;
    IMPORT_ERROR*) fail "engine import failed: ${line#IMPORT_ERROR }" ;;
    *) [[ -n "$line" ]] && printf '        %s\n' "$line" ;;
  esac
done <<< "$DISB_OUT"
[[ $DISB_RC -eq 2 ]] && fail "could not import the payroll engine"

# --- 2b. catalog-driven (service) path ---------------------------------------
# The engine only knows a line is an employer transfer if the pay-component
# catalog says so. Master-data-driven runs build ComponentInput WITHOUT those
# flags and rely on run_calculation.py stamping them from the catalog; if that
# stamping is missing, offbill silently becomes 0 and disbursement collapses
# onto net payable. This mirrors that stamping and guards the regression
# without needing a database.
head "2b. Catalog-driven service path (employer-transfer stamping)"
if "$PY" - <<'PYEOF' >/tmp/accord_stamp.log 2>&1
import json, sys
from types import SimpleNamespace
sys.path.insert(0, "backend")
from app.domain.payroll.engine import calculate_run
from app.domain.payroll.inputs import RunCalcInput, EmployeeCalcInput, ComponentInput
from app.domain.payroll.money import Money
from app.domain.payroll.rounding import ROUND_NONE
from app.services.run_calculation import _stamp_employer_transfer_metadata

FIX = "fixtures/sanitized/june-2026/"
pay = json.load(open(FIX + "pay.json"))
doc = json.load(open(FIX + "components.json"))
rows = doc if isinstance(doc, list) else doc.get("components")
catalog = {
    c["code"]: SimpleNamespace(
        employer_transfer=bool(c.get("employer_transfer", False)),
        transfer_of=c.get("pairs_with"),
    )
    for c in rows
}

emps = []
for e in pay["employees"]:
    by_code = {}
    for l in e["lines"]:
        by_code[l["component_code"]] = ComponentInput(
            component_code=l["component_code"],
            classification=l["classification"],
            calc_kind="direct_monthly_amount",
            amount=Money.from_str(str(l["amount"])),
            rounding_rule=ROUND_NONE,
            informational=l.get("informational", False),
            excluded_from_totals=l.get("excluded_from_totals", False),
        )
    by_code = _stamp_employer_transfer_metadata(by_code, catalog)
    emps.append(EmployeeCalcInput(employee_ref=e["employee_id"], components=tuple(by_code.values())))

rr = calculate_run(RunCalcInput(period="2026-06", org_ref="ORG", employees=tuple(emps)))
assert rr.net_payable.to_canonical_str() == "3838095.00", rr.net_payable
assert rr.offbill_employer_remittance.to_canonical_str() == "152943.00", (
    f"off-bill collapsed to {rr.offbill_employer_remittance} — catalog stamping lost"
)
assert rr.disbursement.to_canonical_str() == "3991038.00", rr.disbursement
PYEOF
then
  pass "catalog stamping yields off-bill 152,943 / disbursement 3,991,038"
else
  fail "catalog stamping (see /tmp/accord_stamp.log)"; tail -8 /tmp/accord_stamp.log
fi

# --- 3. domain test suite ----------------------------------------------------
# --noconftest skips the DB-backed root conftest; these tests are pure.
head "3. Domain test suite (pure, no database)"
if [[ $HAVE_PYTEST -eq 1 ]]; then
  for t in test_engine_june_golden test_engine test_validation; do
    if (cd backend && "$PY" -m pytest "tests/domain/$t.py" --noconftest -q -p no:cacheprovider \
          >/tmp/accord_$t.log 2>&1); then
      pass "$t.py — $(grep -Eo '[0-9]+ passed' /tmp/accord_$t.log | tail -1)"
    else
      fail "$t.py (see /tmp/accord_$t.log)"
      tail -15 "/tmp/accord_$t.log"
    fi
  done
else
  skip "pytest not installed for $PY"
fi

# --- 4. lint -----------------------------------------------------------------
head "4. Lint (ruff) on changed engine files"
if "$PY" -m ruff --version >/dev/null 2>&1; then
  if "$PY" -m ruff check backend/app/domain/payroll/engine.py \
        backend/app/domain/payroll/results.py >/tmp/accord_ruff.log 2>&1; then
    pass "ruff check clean"
  else
    fail "ruff check"; cat /tmp/accord_ruff.log
  fi
else
  skip "ruff not installed for $PY"
fi

# --- 5. DB-backed suite (opt-in) --------------------------------------------
head "5. DB-backed suite (reports / posting / e2e)"
if [[ $WITH_DB -eq 0 ]]; then
  skip "not requested — re-run with --with-db to include"
elif [[ $HAVE_PYTEST -eq 0 ]]; then
  skip "pytest not installed for $PY"
else
  # Stage 2 (persistence + report wiring) must be applied for these to pass.
  if (cd backend && "$PY" -m pytest tests/reports tests/services/test_run_posting.py \
        tests/services/test_run_calculation.py tests/e2e \
        -q -p no:cacheprovider >/tmp/accord_db.log 2>&1); then
    pass "DB-backed suite"
  else
    if grep -qiE 'could not connect|connection refused|operationalerror' /tmp/accord_db.log; then
      skip "Postgres not reachable (set TEST_DATABASE_URL / start Postgres)"
    else
      fail "DB-backed suite (see /tmp/accord_db.log)"
      tail -25 /tmp/accord_db.log
    fi
  fi
fi

# --- summary -----------------------------------------------------------------
printf '\n%s== summary ==%s\n' "$B" "$N"
printf 'passed: %d   failed: %d   skipped: %d\n' "$PASS" "$FAIL" "$SKIP"
if [[ $FAIL -eq 0 ]]; then
  printf '%sAll executed checks passed.%s\n' "$G" "$N"
  printf 'net_payable 3,838,095  +  off-bill NPS 152,943  =  disbursement 3,991,038\n'
  exit 0
fi
printf '%s%d check(s) failed.%s\n' "$R" "$FAIL" "$N"
exit 1
