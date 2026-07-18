"""Pydantic schemas for organization create/switch inputs."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.services.organizations import RESERVED_SLUGS, SLUG_RE


class CreateOrganizationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        if not (2 <= len(value) <= 50):
            raise ValueError("Slug must be between 2 and 50 characters.")
        if not SLUG_RE.fullmatch(value):
            raise ValueError(
                "Slug must be lowercase kebab-case (letters, digits, and single hyphens)."
            )
        if value in RESERVED_SLUGS:
            raise ValueError(f"Slug '{value}' is reserved.")
        return value
