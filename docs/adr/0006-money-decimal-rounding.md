# ADR 0006: Money, decimal, and rounding policy

- **Status:** Accepted (Phase 0)
- **Date:** 2026-07-17
- **Related:** [payroll-domain.md](../payroll-domain.md), [ADR 0005](0005-effective-dated-master-data.md), [ADR 0007](0007-payroll-run-calculation-model.md)

## Context

Accord runs payroll for salaried staff in Indian local government and public works. Money must be exact and easy to audit. Binary floating point (`float` / IEEE-754) cannot store most decimal values exactly. That error is not acceptable for statutory deductions, GPF/NPS/EPF, or treasury remittances.

Government payroll often rounds components to the nearest **whole rupee**. But not every component follows the same rule. So each rounding rule must have a name, and each component must be able to pick its own rule in config. Every calculation trace line records the rule it used (ADR 0007).

Fixture totals must be reproducible byte for byte. One example is the Proven June 2026 invariants in [payroll-domain.md](../payroll-domain.md).

## Decision

### Storage and in-process types

| Layer | Rule |
| --- | --- |
| PostgreSQL | `NUMERIC` (arbitrary precision) for **all** money amounts and **all** rates. Prefer explicit precision/scale on columns, e.g. `NUMERIC(18, 2)` for final INR amounts, `NUMERIC(18, 6)` (or similar) for rates—exact scales documented per column family. |
| Python payroll domain | `decimal.Decimal` **only**. |
| Python payroll domain | `float` is **banned** (literals, `float()` casts, and arithmetic that promotes to float). |

### Automated float guard (CI)

The guard works like this:

1. Keep a path allowlist for the payroll domain package. That package now lives at `backend/app/domain/payroll/`.
2. A CI job runs an AST scan over those modules. The scan fails when it finds:
   - `ast.Constant` / `ast.Num` with `isinstance(value, float)`
   - calls to `float(...)`
   - `ast.BinOp` results are not typed at the AST level. So, where practical, also forbid `math` functions that return float on money paths. The primary rule stays simple: no float literals and no `float()` calls.
3. We considered also forbidding `from __future__ import annotations`. We do not; the guard stays focused on float.
4. A unit test in CI proves the guard works. Given a fixture file with `x = 1.5` or `float("1.5")` under the payroll path, the guard must exit non-zero. A clean tree exits zero.

The scan is implemented as `backend/tests/domain/test_no_float_guard.py`, with the scanner in `backend/tests/domain/_float_guard.py`. (The original sketch named a `tools/check_no_float_in_payroll.py` script; the test module is the real home.)

Payroll calculation code must not merge without this guard.

### API serialization

- Money values in JSON are **canonical decimal strings**, never JSON numbers. Example: `"5073200.00"`.
- Format: a base-10 string with an explicit scale for money. Final INR amounts use 2 decimal places unless a field’s docs say otherwise.
- Rates are also decimal strings with a **documented scale**. We recommend **4–6** decimal digits for percentage rates. A rate stored as a fraction looks like `"0.1200"` for 12%. A rate defined as a percent looks like `"12.0000"`. **The field docs must state which form applies.**
- On input, reject JSON numbers for money and rate fields. Accept only strings that parse cleanly to `Decimal`.

### Currency and precision

- **Currency:** INR.
- **Final stored / displayed monetary amounts:** 2 decimal places (paise). A component’s rounding policy may round to whole rupees. Even then, store the value as `NUMERIC` with scale 2, e.g. `100.00`.
- **Intermediate calculation context:** use Python `decimal.Context(prec=28, rounding=...)` (or an equivalent explicit context) during multi-step math, **before** applying the component’s final named rounding rule.
- Never accumulate in float at any stage.

### Named rounding modes / rules

Define a registry of **named** rounding rules. Examples follow; the names are normative for traces.

| Rule name | Meaning |
| --- | --- |
| `ROUND_HALF_UP_PAISE` | Round to 2 decimal places, half away from zero / half-up (document exact `decimal` rounding constant: `ROUND_HALF_UP`). |
| `ROUND_HALF_UP_RUPEE` | Round to **0** decimal places (nearest whole rupee) using half-up. |
| `ROUND_DOWN_RUPEE` | Truncate toward zero / floor toward 0 rupees as defined when implemented—must be specified before use. |
| `ROUND_NONE` | Intermediate-only; not allowed as final statutory output without an explicit product exception. |

**Government payroll convention:** many or most salary components round to the nearest **whole rupee**, not paise. This is **not** a global hardcode. Each pay component’s effective-dated config (ADR 0005) selects which **named** rounding rule applies.

**Audit requirement:** every calculation trace line (ADR 0007) records:

- `unrounded_value`
- `rounding_rule` (named rule id/string)
- `rounded_value`

### Determinism and content hashing

- Same inputs, same engine version, and same component config versions must yield **byte-identical** canonical run output and **identical content hashes**.
- Canonical serialization for hashing means: stable key order, decimal strings with fixed scale, UTF-8, and no stray whitespace. Define a canonical JSON or CBOR snapshot format at implementation time.
- Hash algorithm: **SHA-256** over the canonical snapshot bytes.
- Every `payroll_run_version` records:
  - `engine_version` (string; semver or a commit-stamped engine id)
  - `content_hash` (SHA-256 hex)
  - references to the source master version ids (ADR 0005)

Re-running a calculation on the same draft inputs must give the same hash. A new run version may appear only when inputs, config, or engine differ. Output must never drift silently.

## Consequences

**Positive:**

- Statutory and treasury amounts stay exact and easy to explain.
- Per-component rounding matches government practice. No single rule is baked into the engine core.
- CI can enforce the float ban.

**Negative / costs:**

- API clients must handle decimal strings, not native JSON numbers.
- Developers must keep `Decimal` discipline. The float guard may need rare allowlist exceptions for non-money math outside payroll domain paths.

**Open questions:**

- The exact `decimal` rounding constant for each named rule, once edge cases (negative recoveries) appear in workbooks.
- Whether remittance files must enforce whole rupees even when internal display shows paise. Confirm per treasury/AG specification.
