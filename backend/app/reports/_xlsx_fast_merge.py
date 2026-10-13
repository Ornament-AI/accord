"""Scale-safe merged-cell registration for report rendering.

``Worksheet.merge_cells`` routes through ``MultiCellRange.add``, which scans
every existing range before inserting — quadratic once a sheet accumulates
thousands of merges (per-employee payslip blocks, consolidated workbook
copies).  Registering directly on the ranges set keeps the same semantics:
the set itself prevents duplicates and ``_clean_merge_range`` still recreates
interior ``MergedCell`` placeholders and propagates borders, so rendered
output is unchanged.
"""

from __future__ import annotations

from openpyxl.worksheet.cell_range import CellRange
from openpyxl.worksheet.merge import MergedCellRange
from openpyxl.worksheet.worksheet import Worksheet


def merge_cells_fast(
    ws: Worksheet,
    *,
    start_row: int,
    start_column: int,
    end_row: int,
    end_column: int,
) -> None:
    merged = MergedCellRange(
        ws,
        CellRange(
            min_col=start_column,
            min_row=start_row,
            max_col=end_column,
            max_row=end_row,
        ).coord,
    )
    ws.merged_cells.ranges.add(merged)
    ws._clean_merge_range(merged)
