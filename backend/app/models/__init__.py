"""Accord SQLModel package.

Phase 1 exports shared mixins and the RLS policy helper. Phase 2 adds identity
and tenancy tables (users, organizations, memberships, idempotency
keys, sessions). Phase 3 adds org-structure, employee master data (header +
version tables), pay components, recurring instructions, advances,
accommodation, and report configurations. Phase 4 adds payroll run persistence
(periods, runs, draft inputs, and immutable calculation snapshots). Phase 5
adds platform tables (audit, outbox, approvals, jobs, export artifacts,
webhook dedup). Importing this package populates ``SQLModel.metadata`` for
Alembic.
"""

from app.models.accommodation import (
    AccommodationAssignment,
    accommodation_charge_versions,
)
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.base import (
    OrganizationOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    rls_policy_sql,
    utcnow,
)
from app.models.effective import effective_on, select_active_version
from app.models.employees import (
    Employee,
    employee_bank_account_versions,
    employee_pay_versions,
    employee_posting_versions,
    employee_profile_versions,
)
from app.models.identity import (
    IdempotencyKey,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    OrganizationSettings,
    Session,
    User,
)
from app.models.org_structure import Office, Post
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    PayrollRunEmployee,
    PayrollRunInput,
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from app.models.platform import (
    AuditEvent,
    ExportArtifact,
    Job,
    OutboxEvent,
    PayrollApproval,
    WebhookEvent,
)
from app.models.recurring_instructions import (
    RecurringInstruction,
    recurring_instruction_versions,
)
from app.models.reports import ReportConfiguration

__all__ = [
    "AccommodationAssignment",
    "AdvanceAccount",
    "AuditEvent",
    "Employee",
    "ExportArtifact",
    "IdempotencyKey",
    "Job",
    "Office",
    "Organization",
    "OrganizationInvitation",
    "OrganizationMembership",
    "OrganizationOwnedMixin",
    "OrganizationSettings",
    "OutboxEvent",
    "PayComponent",
    "PayrollApproval",
    "PayrollPeriod",
    "PayrollRun",
    "PayrollRunEmployee",
    "PayrollRunInput",
    "Post",
    "RecurringInstruction",
    "ReportConfiguration",
    "Session",
    "TimestampMixin",
    "User",
    "UUIDPrimaryKeyMixin",
    "WebhookEvent",
    "accommodation_charge_versions",
    "advance_installment_versions",
    "component_rate_versions",
    "effective_on",
    "employee_bank_account_versions",
    "employee_pay_versions",
    "employee_posting_versions",
    "employee_profile_versions",
    "payroll_employee_results",
    "payroll_result_lines",
    "payroll_run_versions",
    "recurring_instruction_versions",
    "rls_policy_sql",
    "select_active_version",
    "utcnow",
]
