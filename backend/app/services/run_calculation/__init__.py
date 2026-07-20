"""Payroll run calculation, split along its natural seams.

- ``_convert`` — pure DB/domain converters and snapshot serializers
- ``resolution`` — master-data resolution into typed engine inputs
- ``snapshots`` — immutable report snapshots stored on the run version
- ``command`` — the orchestrating ``calculate_run_command``

Only ``calculate_run_command`` is public service API.
"""

from app.services.run_calculation.command import calculate_run_command

__all__ = ["calculate_run_command"]
