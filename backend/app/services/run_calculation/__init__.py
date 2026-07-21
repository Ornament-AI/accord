"""Payroll run calculation, split along its natural seams.

- ``_convert`` — pure DB/domain converters and snapshot serializers
- ``resolution`` — master-data resolution into typed engine inputs, including
  the pure ``stamp_employer_transfer_metadata`` policy helper
- ``snapshots`` — immutable report snapshots stored on the run version
- ``command`` — the orchestrating ``calculate_run_command``

The command and pure catalog-stamping policy are the public service API.
"""

from app.services.run_calculation.command import calculate_run_command
from app.services.run_calculation.resolution import stamp_employer_transfer_metadata

__all__ = ["calculate_run_command", "stamp_employer_transfer_metadata"]
