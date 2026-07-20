#!/usr/bin/env python3
"""Seed the sanitized June 2026 golden fixture into a running Accord API.

The reference pay-bill spreadsheet is the provenance for this fixture; product
data is the synthetic golden set under fixtures/sanitized/june-2026/ (no real
PII). Replays the same HTTP sequence as backend/tests/e2e/test_june_golden_e2e.py
against a live server (dev-auth session).

Usage:
  backend/.venv/bin/python scripts/seed_june_fixture.py
  backend/.venv/bin/python scripts/seed_june_fixture.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from tests.e2e.fixture_loader import (  # noqa: E402
	ACCOMMODATION_COMPONENT_CODES,
	ADVANCE_COMPONENT_CODES,
	BASIC_CODE,
	RECURRING_COMPONENT_CODES,
	EmployeeSeed,
	JuneFixture,
	line_amount,
	load_june_fixture,
	map_quarters_location,
	map_regime,
	money_str,
)

EFFECTIVE_FROM = "2026-01-01"


class SeedError(RuntimeError):
	pass


def _require(resp: httpx.Response, *, context: str) -> dict[str, Any] | list[Any] | None:
	if resp.status_code >= 400:
		raise SeedError(f"{context}: {resp.status_code} {resp.text}")
	if resp.status_code == 204 or not resp.content:
		return None
	return resp.json()


def _login(client: httpx.Client) -> None:
	resp = client.get("/api/auth/login", follow_redirects=False)
	if resp.status_code not in {200, 302}:
		raise SeedError(f"login failed: {resp.status_code} {resp.text}")
	me = _require(client.get("/api/auth/me"), context="GET /api/auth/me")
	assert isinstance(me, dict)
	if me.get("access_state") != "active" or not me.get("organization"):
		raise SeedError(
			"No active organization membership. Bootstrap with "
			"scripts/provision_organization.py and ensure this user is a member, then re-run."
		)
	org = me["organization"]
	print(f"Authenticated as {me.get('email')} in org {org.get('name')} ({org.get('slug')})")


def _assert_empty(client: httpx.Client) -> None:
	employees = _require(client.get("/api/employees", params={"page_size": 1}), context="list employees")
	assert isinstance(employees, dict)
	if int(employees.get("total") or 0) > 0:
		raise SeedError(
			f"Org already has {employees['total']} employees. "
			"Seed into an empty org, or wipe master data first."
		)
	# Standard pay components are seeded at organization bootstrap and are
	# expected to exist; _create_components reuses them by code (as the golden
	# e2e test does) and only creates the fixture components that are missing.


def _create_org_structure(
	client: httpx.Client,
	fixture: JuneFixture,
) -> tuple[dict[str, UUID], UUID, UUID]:
	office_ids: dict[str, UUID] = {}
	for office in fixture.organization.offices:
		body = _require(
			client.post(
				"/api/offices",
				json={
					"name": office.name,
					"jurisdiction": office.jurisdiction,
				},
			),
			context=f"create office {office.name}",
		)
		assert isinstance(body, dict)
		office_ids[office.fixture_id] = UUID(body["id"])
		print(f"  office {office.name}")

	post = _require(
		client.post(
			"/api/posts",
			json={"designation": "Synthetic Clerk", "class_name": "III"},
		),
		context="create post",
	)
	assert isinstance(post, dict)
	print("  post Synthetic Clerk")
	return office_ids, UUID(post["id"])


def _create_components(client: httpx.Client, fixture: JuneFixture) -> dict[str, UUID]:
	listing = _require(client.get("/api/pay-components"), context="list components")
	assert isinstance(listing, list)
	existing: dict[str, dict[str, Any]] = {row["code"]: row for row in listing}

	component_ids: dict[str, UUID] = {}
	display_order = 0
	for comp in fixture.components:
		display_order += 1
		body = existing.get(comp.code)
		if body is None:
			body = _require(
				client.post(
					"/api/pay-components",
					json={
						"code": comp.code,
						"name": comp.name,
						"classification": comp.api_classification,
						"display_order": display_order,
						"employer_transfer": comp.employer_transfer,
						"transfer_of": comp.transfer_of,
					},
				),
				context=f"create component {comp.code}",
			)
		assert isinstance(body, dict)
		component_id = UUID(body["id"])
		component_ids[comp.code] = component_id

		if comp.code in RECURRING_COMPONENT_CODES or comp.code == BASIC_CODE:
			resp = client.post(
				f"/api/pay-components/{component_id}/rate-versions",
				json={
					"effective_from": EFFECTIVE_FROM,
					"calc_kind": "fixed_recurring_amount",
					"amount": "0.00",
					"rounding_rule": "ROUND_HALF_UP_RUPEE",
				},
			)
			# 409 means a rate version already covers EFFECTIVE_FROM (e.g. a
			# previous seed run); the resolver only needs one to exist.
			if resp.status_code not in {201, 409}:
				raise SeedError(f"rate version {comp.code}: {resp.status_code} {resp.text}")
		print(f"  component {comp.code}")

	if len(component_ids) != len(fixture.components):
		raise SeedError(
			f"expected {len(fixture.components)} components, got "
			f"{len(component_ids)}: {sorted(component_ids)}"
		)
	return component_ids


def _profile_payload(employee: EmployeeSeed) -> dict[str, Any]:
	regime, gpf_jurisdiction = map_regime(employee.regime)
	profile: dict[str, Any] = {
		"name": employee.name,
		"sevarth_id": employee.sevarth_id,
		"pan": employee.pan,
		"date_of_birth": "1985-01-15",
		"date_of_joining": "2010-06-01",
		"retirement_regime": regime,
	}
	if regime == "gpf":
		profile["gpf_jurisdiction"] = gpf_jurisdiction
		profile["gpf_account_number"] = employee.gpf_account
		if employee.pran:
			profile["pran"] = employee.pran
	elif regime == "nps":
		profile["pran"] = employee.pran or f"9000{employee.fixture_id[-4:].zfill(8)}"
	elif regime == "epf":
		profile["epf_number"] = employee.epf_number or f"SYNTEPF/{employee.fixture_id}/UAN"
	return profile


def _create_employee(
	client: httpx.Client,
	employee: EmployeeSeed,
	*,
	office_ids: dict[str, UUID],
	post_id: UUID,
) -> UUID:
	basic = line_amount(employee, BASIC_CODE)
	if basic is None:
		raise SeedError(f"{employee.fixture_id} missing BASIC")
	body = _require(
		client.post(
			"/api/employees",
			json={
				"employee_number": employee.fixture_id,
				"effective_from": EFFECTIVE_FROM,
				"profile": _profile_payload(employee),
				"posting": {
					"office_id": str(office_ids[employee.office_id]),
					"post_id": str(post_id),
				},
				"pay": {"pay_matrix_level": "L10", "basic_pay": money_str(basic)},
				"bank": {
					"account_number": employee.bank_account,
					"ifsc": employee.ifsc,
					"bank_name": "Synthetic Bank",
					"branch": "Synthetic Branch",
					"is_primary_salary": True,
				},
			},
		),
		context=f"create employee {employee.fixture_id}",
	)
	assert isinstance(body, dict)
	return UUID(body["id"])


def _seed_employee_amounts(
	client: httpx.Client,
	employee: EmployeeSeed,
	*,
	employee_id: UUID,
	component_ids: dict[str, UUID],
) -> None:
	for line in employee.lines:
		code = line.component_code
		if code == BASIC_CODE:
			continue
		if code in RECURRING_COMPONENT_CODES:
			_require(
				client.post(
					f"/api/employees/{employee_id}/recurring-instructions",
					json={
						"component_id": str(component_ids[code]),
						"effective_from": EFFECTIVE_FROM,
						"amount": money_str(line.amount),
						"reason": f"June fixture {code}",
					},
				),
				context=f"{employee.fixture_id} recurring {code}",
			)
			continue
		if code in ADVANCE_COMPONENT_CODES:
			principal = max(line.amount * Decimal("24"), line.amount)
			_require(
				client.post(
					f"/api/employees/{employee_id}/advances",
					json={
						"advance_type": "hba",
						"principal": money_str(principal),
						"sanctioned_on": EFFECTIVE_FROM,
						"reference": f"HBA-{employee.fixture_id}",
						"installment": {
							"installment_amount": money_str(line.amount),
							"installments_total": 24,
							"installments_recovered_opening": 0,
							"effective_from": EFFECTIVE_FROM,
						},
					},
				),
				context=f"{employee.fixture_id} advance {code}",
			)
			continue
		if code == "ACCOMMODATION_LICENSE_FEE":
			if employee.accommodation is None:
				raise SeedError(f"{employee.fixture_id} missing accommodation")
			foregone = line_amount(employee, "FOREGONE_HRA")
			charge: dict[str, Any] = {
				"license_fee": money_str(line.amount),
				"effective_from": EFFECTIVE_FROM,
			}
			if foregone is not None:
				charge["informational_hra_foregone"] = money_str(foregone)
			_require(
				client.post(
					f"/api/employees/{employee_id}/accommodation",
					json={
						"quarters_location": map_quarters_location(
							employee.accommodation.location
						),
						"quarters_identifier": f"Q-{employee.fixture_id}",
						"charge": charge,
					},
				),
				context=f"{employee.fixture_id} accommodation",
			)
			continue
		if code in ACCOMMODATION_COMPONENT_CODES:
			continue
		raise SeedError(f"No seeding strategy for {employee.fixture_id} line {code}")


def seed(base_url: str) -> None:
	fixture = load_june_fixture()
	print(f"Loaded fixture: {len(fixture.employees)} employees, period {fixture.organization.period}")
	print(f"Provenance: fixtures/sanitized/june-2026 (from June 2026 pay-bill structure)")

	with httpx.Client(base_url=base_url.rstrip("/"), timeout=60.0) as client:
		_login(client)
		_assert_empty(client)

		print("Org structure…")
		office_ids, post_id = _create_org_structure(client, fixture)

		print("Pay components…")
		component_ids = _create_components(client, fixture)

		print("Employees…")
		for employee in fixture.employees:
			employee_id = _create_employee(
				client,
				employee,
				office_ids=office_ids,
				post_id=post_id,
			)
			_seed_employee_amounts(
				client,
				employee,
				employee_id=employee_id,
				component_ids=component_ids,
			)
			print(f"  {employee.fixture_id} {employee.name}")

		employees = _require(
			client.get("/api/employees", params={"page_size": 100}),
			context="verify employees",
		)
		assert isinstance(employees, dict)
		print(
			f"Done. {employees.get('total')} employees in org; "
			f"open the app and browse Employees / Pay Components."
		)


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"--base-url",
		default="http://127.0.0.1:8000",
		help="Accord API base URL (default: http://127.0.0.1:8000)",
	)
	args = parser.parse_args()
	try:
		seed(args.base_url)
	except SeedError as exc:
		print(f"error: {exc}", file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
