"""RFC 9457 ProblemDetail response schema."""

from pydantic import BaseModel, Field


class ProblemValidationError(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str
    error: str | None = Field(default=None)
    request_id: str | None = Field(default=None)
    errors: list[ProblemValidationError] | None = Field(default=None)
