"""Capability matrix assertions (ADR-0002 §8)."""

from __future__ import annotations

from app.auth.capabilities import CAPABILITIES, ROLE_CAPABILITIES, capabilities_for_role


def test_all_roles_present():
    expected = {
        "organization_administrator",
        "payroll_preparer",
        "payroll_reviewer",
        "payroll_approver",
        "report_releaser",
        "auditor",
    }
    assert set(ROLE_CAPABILITIES) == expected


def test_organization_administrator_has_full_set():
    assert capabilities_for_role("organization_administrator") == CAPABILITIES


def test_payroll_preparer_matrix():
    assert capabilities_for_role("payroll_preparer") == frozenset(
        {
            "manage_master_data",
            "view_master_data",
            "create_run",
            "submit_run",
            "generate_reports",
            "view_audit",
        }
    )


def test_payroll_reviewer_matrix():
    assert capabilities_for_role("payroll_reviewer") == frozenset(
        {
            "view_master_data",
            "generate_reports",
            "view_audit",
        }
    )


def test_payroll_approver_matrix():
    assert capabilities_for_role("payroll_approver") == frozenset(
        {
            "approve_run",
            "generate_reports",
            "view_audit",
        }
    )


def test_report_releaser_matrix():
    assert capabilities_for_role("report_releaser") == frozenset(
        {
            "post_run",
            "generate_reports",
            "release_reports",
            "view_audit",
        }
    )


def test_auditor_matrix():
    assert capabilities_for_role("auditor") == frozenset(
        {
            "generate_reports",
            "view_audit",
        }
    )


def test_unknown_role_empty():
    assert capabilities_for_role("not_a_role") == frozenset()


def test_every_granted_capability_is_known():
    for role, caps in ROLE_CAPABILITIES.items():
        assert caps <= CAPABILITIES, role
