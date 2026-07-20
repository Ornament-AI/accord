"""Role → capability matrix (ADR-0002 §8), backend source of truth.

Rationale (traceability against ADR-0002 §8 columns):

* **Master data CRUD** — ``organization_administrator`` and ``payroll_preparer``
  get both ``manage_master_data`` and ``view_master_data``. ``payroll_reviewer``
  is ADR "scoped" → ``view_master_data`` only. ``payroll_approver`` and
  ``auditor`` are ADR "no" → neither master-data capability.
* **Run post → ``report_releaser``** — ADR grants Run post to
  ``report_releaser`` (and org admin), not ``payroll_approver``.
* **``release_reports`` interpretive** — ADR has a single "Report
  generation/download" column (yes for all six org roles → ``generate_reports``).
  There is no separate release column; ``release_reports`` is granted only to
  ``report_releaser`` (+ org admin) by role-name inference.
* **Run reverse unimplemented** — ADR has a Run reverse column but no matching
  frozen capability string; left as a future-phase seam (do not invent a 13th).
* **Platform support out of scope** — not an ``organization_memberships.role``;
  ``is_platform_admin`` is display-only this phase (no capability bypass).
* **``view_audit`` scoping seam** — granted to every role with any ADR audit
  visibility; finer "scoped vs yes" query filtering is deferred to an audit-log
  read endpoint.
"""

from __future__ import annotations

CAPABILITIES = frozenset(
    {
        "manage_organization",
        "manage_master_data",
        "view_master_data",
        "reveal_sensitive_fields",
        "create_run",
        "submit_run",
        "approve_run",
        "post_run",
        "generate_reports",
        "release_reports",
        "view_audit",
    }
)

MEMBERSHIP_ROLES = frozenset(
    {
        "organization_administrator",
        "payroll_preparer",
        "payroll_reviewer",
        "payroll_approver",
        "report_releaser",
        "auditor",
    }
)

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "organization_administrator": CAPABILITIES,
    "payroll_preparer": frozenset(
        {
            "manage_master_data",
            "view_master_data",
            "create_run",
            "submit_run",
            "generate_reports",
            "view_audit",
        }
    ),
    "payroll_reviewer": frozenset(
        {
            "view_master_data",
            "generate_reports",
            "view_audit",
        }
    ),
    "payroll_approver": frozenset(
        {
            "approve_run",
            "generate_reports",
            "view_audit",
        }
    ),
    "report_releaser": frozenset(
        {
            "post_run",
            "generate_reports",
            "release_reports",
            "view_audit",
        }
    ),
    "auditor": frozenset(
        {
            "generate_reports",
            "view_audit",
        }
    ),
}


def capabilities_for_role(role: str) -> frozenset[str]:
    """Return the capability set for ``role``, or empty if unknown."""
    return ROLE_CAPABILITIES.get(role, frozenset())
