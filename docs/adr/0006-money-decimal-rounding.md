# ADR 0006: Money, decimal, and rounding policy

- **Status:** Accepted (Phase 0)
- **Date:** 2026-07-17
- **Related:** [payroll-domain.md](../payroll-domain.md), [ADR 0005](0005-effective-dated-master-data.md), [ADR 0007](0007-payroll-run-calculation-model.md)

## Context

Accord is a payroll system for Indian local-government / public-works salaried staff. Money must be exact and auditable. Binary floating point (`float` / IEEE-754) introduces representation error unacceptable for statutory deductions, GPF/NPS/EPF, and treasury remittances.

Government payroll often rounds many components to the **nearest whole rupee**, but not every component follows the same rule. Rounding must be named, configurable per component, and recorded on every calculation trace line (ADR 0007).

Fixture aggregates such as the Proven June 2026 invariants in [payroll-domain.md](../payroll-domain.md) must be reproducible byte-identically.

## Decision

### Storage and in-process types

| Layer | Rule |
| --- | --- |
| PostgreSQL | `NUMERIC` (arbitrary precision) for **all** money amounts and **all** rates. Prefer explicit precision/scale on columns, e.g. `NUMERIC(18, 2)` for final INR amounts, `NUMERIC(18, 6)` (or similar) for rates—exact scales documented per column family. |
| Python payroll domain | `decimal.Decimal` **only**. |
| Python payroll domain | `float` is **banned** (literals, `float()` casts, and arithmetic that promotes to float). |

### Automated float guard (to implement in CI)

Concrete guard (Phase 0 specifies; implementation later):

1. Maintain a path allowlist for payroll domain packages, e.g. `accord/payroll/**`, `accord/domain/payroll/**` (final package layout TBD).
2. CI job runs an AST scan (e.g., a small `tools/check_no_float_in_payroll.py` or a Ruff/custom lint plugin) that fails if within those modules it finds:
   - `ast.Constant` / `ast.Num` with `isinstance(value, float)`
   - calls to `float(...)`
   - `ast.BinOp` results are not typed at AST level—so also forbid importing / using `math` functions that return float on money paths where practical; primary enforcement is no float literals and no `float()` calls
3. Optionally forbid `from __future__ import annotations` only—no; keep focus on float.
4. Unit test in CI: given a temporary fixture file containing `x = 1.5` or `float("1.5")` under the payroll path, the guard must exit non-zero; a clean tree exits zero.

This guard is mandatory before payroll calculation code merges.

### API serialization

- Money values in JSON are **canonical decimal strings**, never JSON numbers. Example: `"5073200.00"`.
- Format: base-10 string with explicit scale for money (2 decimal places for final INR amounts unless a field is documented otherwise).
- Rates are also decimal strings with a **documented scale** (recommend **4–6** decimal digits for percentage rates, e.g. `"0.1200"` for 12% stored as a fraction, or `"12.0000"` if the field is defined as percent—**field docs must state which**).
- Parsing on input: reject JSON numbers for money/rate fields; accept only strings that parse cleanly to `Decimal`.

### Currency and precision

- **Currency:** INR.
- **Final stored / displayed monetary amounts:** 2 decimal places (paise), unless a component’s rounding policy rounds to whole rupees (still store as `NUMERIC` with scale 2, e.g. `100.00`).
- **Intermediate calculation context:** Python `decimal.Context(prec=28, rounding=...)` (or equivalent explicit context) during multi-step calculations **before** applying the component’s final named rounding rule.
- Do not accumulate in float at any stage.

### Named rounding modes / rules

Define a registry of **named** rounding rules. Examples (names are normative for traces):

| Rule name | Meaning |
| --- | --- |
| `ROUND_HALF_UP_PAISE` | Round to 2 decimal places, half away from zero / half-up (document exact `decimal` rounding constant: `ROUND_HALF_UP`). |
| `ROUND_HALF_UP_RUPEE` | Round to **0** decimal places (nearest whole rupee) using half-up. |
| `ROUND_DOWN_RUPEE` | Truncate toward zero / floor toward 0 rupees as defined when implemented—must be specified before use. |
| `ROUND_NONE` | Intermediate-only; not allowed as final statutory output without an explicit product exception. |

**Government payroll convention:** many/most salary components round to the nearest **whole rupee**, not paise. This is **not** a global hardcode. Each pay component’s effective-dated config (ADR 0005) selects which **named** rounding rule applies.

**Audit requirement:** every calculation trace line (ADR 0007) records:

- `unrounded_value`
- `rounding_rule` (named rule id/string)
- `rounded_value`

### Determinism and content hashing

- Same inputs + same engine version + same component config versions ⇒ **byte-identical** canonical serialized run output and **identical content hashes**.
- Canonical serialization for hashing: stable key ordering, decimal strings with fixed scale, UTF-8, no insignificant whitespace variance (define a canonical JSON or CBOR snapshot format when implementing).
- Hash algorithm: **SHA-256** over the canonical snapshot bytes.
- Every `payroll_run_version` records:
  - `engine_version` (string, semver or commit-stamped engine id)
  - `content_hash` (SHA-256 hex)
  - references to source master version ids (ADR 0005)

Re-running calculation on the same draft inputs must either produce the same hash or create a new run version only when inputs/config/engine differ—never silently drift.

## Consequences

**Positive:**

- Statutory and treasury amounts remain exact and explainable.
- Per-component rounding matches government practice without baking one rule into the engine core.
- Float ban is enforceable in CI.

**Negative / costs:**

- API clients must handle decimal strings (not native JSON numbers).
- Developers must use `Decimal` discipline; float guard may need occasional allowlist exceptions for non-money math (should be rare and outside payroll domain paths).

**Open questions:**

- Exact `decimal.Rounding` constant for each named rule when edge cases (negative recoveries) appear in workbooks.
- Whether remittance files require whole-rupee enforcement even when internal display shows paise—confirm per treasury/AG specification.
