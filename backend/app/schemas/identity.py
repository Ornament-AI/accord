"""Pydantic schemas for auth identity endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr


class PasswordLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)


class MagicCodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class MagicCodeLoginRequest(MagicCodeRequest):
    code: str = Field(min_length=6, max_length=16)
