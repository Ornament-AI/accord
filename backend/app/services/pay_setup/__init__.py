"""Pay-setup master data services, split by aggregate.

One module per aggregate keeps each effective-dated series (ADR 0005) in one
place; this package facade preserves the flat ``pay_setup.*`` service API the
routes call.

- ``components`` — pay component catalog + component rate versions
- ``recurring`` — recurring instruction headers + instruction versions
- ``advances`` — advance accounts + installment versions
- ``accommodation`` — accommodation assignments + charge versions
- ``report_config`` — report configuration store + payroll export profile
"""

from app.services.pay_setup.accommodation import (
    create_accommodation,
    create_accommodation_charge_version,
    list_accommodation,
    update_accommodation,
)
from app.services.pay_setup.advances import (
    create_advance,
    create_advance_installment_version,
    list_advances,
)
from app.services.pay_setup.components import (
    create_component_rate_version,
    create_pay_component,
    list_component_rate_versions,
    list_pay_components,
    update_pay_component,
)
from app.services.pay_setup.recurring import (
    create_recurring_instruction,
    create_recurring_instruction_version,
    list_recurring_instruction_versions,
    list_recurring_instructions,
)
from app.services.pay_setup.report_config import (
    get_payroll_export_profile,
    list_report_configurations,
    upsert_payroll_export_profile,
    upsert_report_configuration,
    validate_report_config_key,
)

__all__ = [
    "create_accommodation",
    "create_accommodation_charge_version",
    "create_advance",
    "create_advance_installment_version",
    "create_component_rate_version",
    "create_pay_component",
    "create_recurring_instruction",
    "create_recurring_instruction_version",
    "get_payroll_export_profile",
    "list_accommodation",
    "list_advances",
    "list_component_rate_versions",
    "list_pay_components",
    "list_recurring_instruction_versions",
    "list_recurring_instructions",
    "list_report_configurations",
    "update_pay_component",
    "update_accommodation",
    "upsert_payroll_export_profile",
    "upsert_report_configuration",
    "validate_report_config_key",
]
