"""Object storage protocol and opaque key helpers (ADR 0010).

Phase 1 defines the contract and exceptions only. Concrete S3/MinIO adapters
land in Phase 6. Keys are normative ``{organization_id}/{object_uuid}`` —
opaque, with no human-readable or business data in the path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4


class ObjectStorageError(Exception):
    """Base error for object storage operations."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ObjectNotFound(ObjectStorageError):
    """Raised when the requested object key does not exist."""


class ChecksumMismatch(ObjectStorageError):
    """Raised when computed SHA-256 does not match an expected value."""


class StorageUnavailable(ObjectStorageError):
    """Raised when the storage backend is temporarily unavailable."""


class InvalidObjectKey(ObjectStorageError):
    """Raised when an object key is not opaque ``{uuid}/{uuid}`` form."""


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    """Metadata recorded for a stored object (ADR 0010 §4 / export_artifacts)."""

    key: str
    checksum_sha256: str
    size_bytes: int
    content_type: str
    # Etag / object version id (may double as S3 version id per ADR 0010 §4).
    object_version: str


def validate_object_key(key: str) -> str:
    """Validate and normalize an opaque object key.

    Normative format (ADR 0010 §4): ``{organization_id}/{object_uuid}`` where
    both segments are UUID strings. Rejects path traversal, extra segments,
    empty parts, and human-readable/business path components.

    Returns the canonical ``str(UUID)/str(UUID)`` form.
    """
    if not isinstance(key, str) or not key:
        raise InvalidObjectKey("object key must be a non-empty string")
    if "\\" in key or key.startswith("/") or key.endswith("/"):
        raise InvalidObjectKey(
            "object key must be opaque '{organization_id}/{object_uuid}'",
            details={"key": key},
        )
    if ".." in key or "//" in key:
        raise InvalidObjectKey(
            "object key must not contain path traversal or fragments",
            details={"key": key},
        )
    parts = key.split("/")
    if len(parts) != 2:
        raise InvalidObjectKey(
            "object key must be exactly '{organization_id}/{object_uuid}'",
            details={"key": key},
        )
    org_raw, object_raw = parts
    try:
        organization_id = UUID(org_raw)
        object_id = UUID(object_raw)
    except ValueError as exc:
        raise InvalidObjectKey(
            "object key segments must be UUIDs",
            details={"key": key},
        ) from exc
    # Reject non-canonical UUID spellings (e.g. urn:, braces, hex without dashes)
    # so keys stay uniformly opaque and log-safe.
    if org_raw.lower() != str(organization_id) or object_raw.lower() != str(object_id):
        raise InvalidObjectKey(
            "object key UUIDs must be canonical 8-4-4-4-12 hex form",
            details={"key": key},
        )
    return f"{organization_id}/{object_id}"


def build_object_key(
    organization_id: UUID,
    object_id: UUID | None = None,
) -> str:
    """Build a normative opaque key ``{organization_id}/{object_uuid}``."""
    oid = object_id if object_id is not None else uuid4()
    return validate_object_key(f"{organization_id}/{oid}")


@runtime_checkable
class ObjectStorage(Protocol):
    """Async object storage contract (ADR 0010 §4).

    Implementations must compute SHA-256 on put and expose opaque-key
    addressing. Downloads are backend-streamed at the API layer; this protocol
    is the storage seam used by workers and download handlers.
    """

    async def put(
        self,
        key: str,
        data: bytes | AsyncIterator[bytes],
        content_type: str,
        *,
        expected_checksum_sha256: str | None = None,
    ) -> ObjectMetadata:
        """Store bytes (or a byte stream), compute SHA-256, return metadata.

        If ``expected_checksum_sha256`` is provided and does not match the
        computed digest, raise ``ChecksumMismatch`` and do not retain the
        object as successfully finalized.
        """
        ...

    async def get(self, key: str) -> bytes:
        """Return the full object body, or raise ``ObjectNotFound``."""
        ...

    def stream(self, key: str) -> AsyncIterator[bytes]:
        """Yield object body chunks, or raise ``ObjectNotFound``.

        Declared as a normal method returning an async iterator so callers can
        ``async for chunk in storage.stream(key)``.
        """
        ...

    async def exists(self, key: str) -> bool:
        """Return whether ``key`` currently exists."""
        ...

    async def delete(self, key: str) -> None:
        """Delete ``key``, or raise ``ObjectNotFound`` if missing."""
        ...
