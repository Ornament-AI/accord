"""Unit tests for organization slug validation."""

from __future__ import annotations

import pytest

from app.exceptions import ValidationError
from app.services.organizations import validate_slug


@pytest.mark.parametrize(
    "slug",
    ["acme", "acme-co", "a1", "org-123-payroll"],
)
def test_validate_slug_accepts_valid(slug):
    validate_slug(slug)  # does not raise


@pytest.mark.parametrize(
    "slug",
    [
        "A",
        "UPPER",
        "a",
        "a" * 51,
        "api",
        "admin",
        "-leading",
        "trailing-",
        "double--hyphen",
        "has space",
    ],
)
def test_validate_slug_rejects_invalid(slug):
    with pytest.raises(ValidationError):
        validate_slug(slug)
