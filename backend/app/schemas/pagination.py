"""Shared pagination response contract and page math."""

from collections.abc import Sequence
from typing import Any, Generic, Self, TypeVar

from pydantic import BaseModel, model_validator


T = TypeVar("T")


def page_count(*, total: int, page_size: int) -> int:
    """Return total pages, keeping empty result sets on page 1."""
    if total < 0:
        raise ValueError("total must be non-negative")
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
    return max(1, (total + page_size - 1) // page_size)


def page_offset(*, page: int, page_size: int) -> int:
    """Return SQL offset for 1-indexed pagination params."""
    if page < 1:
        raise ValueError("page must be at least 1")
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
    return (page - 1) * page_size


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @model_validator(mode="after")
    def validate_page_contract(self) -> Self:
        if self.page < 1:
            raise ValueError("page must be at least 1")
        expected_total_pages = page_count(total=self.total, page_size=self.page_size)
        if self.total_pages != expected_total_pages:
            raise ValueError("total_pages does not match total and page_size")
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size")
        return self

    @classmethod
    def model_parametrized_name(cls, params: tuple[type[Any], ...]) -> str:
        item_type = params[0]
        name = getattr(item_type, "__name__", "Response")
        return f"Paginated{name}"

    @classmethod
    def from_items(
        cls,
        *,
        items: Sequence[T],
        total: int,
        page: int,
        page_size: int,
    ) -> Self:
        return cls(
            items=list(items),
            total=total,
            page=page,
            page_size=page_size,
            total_pages=page_count(total=total, page_size=page_size),
        )
