import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.pagination import PaginatedResponse, page_count, page_offset


class _Row(BaseModel):
    id: int


class _RowPage(PaginatedResponse[_Row]):
    pass


def test_page_count_zero_rows_keeps_single_empty_page():
    assert page_count(total=0, page_size=50) == 1
    assert _RowPage.from_items(items=[], total=0, page=1, page_size=50).model_dump() == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 50,
        "total_pages": 1,
    }


def test_page_count_exact_boundary_does_not_add_extra_page():
    assert page_count(total=100, page_size=50) == 2
    assert page_offset(page=2, page_size=50) == 50
    page = _RowPage.from_items(items=[_Row(id=2)], total=100, page=2, page_size=50)
    assert page.total_pages == 2


def test_page_beyond_total_preserves_requested_page_with_empty_items():
    page = _RowPage.from_items(items=[], total=3, page=4, page_size=2)
    assert page.model_dump() == {
        "items": [],
        "total": 3,
        "page": 4,
        "page_size": 2,
        "total_pages": 2,
    }


def test_paginated_response_rejects_raw_total_page_drift():
    with pytest.raises(ValidationError):
        _RowPage(items=[], total=3, page=1, page_size=2, total_pages=99)


def test_paginated_response_rejects_more_items_than_page_size():
    with pytest.raises(ValidationError):
        _RowPage(
            items=[_Row(id=1), _Row(id=2), _Row(id=3)],
            total=3,
            page=1,
            page_size=2,
            total_pages=2,
        )
