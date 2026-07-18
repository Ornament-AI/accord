"""Object storage protocol and in-memory test double (ADR 0010 Phase 1)."""

from app.storage.memory import InMemoryObjectStorage
from app.storage.protocol import (
    ChecksumMismatch,
    InvalidObjectKey,
    ObjectMetadata,
    ObjectNotFound,
    ObjectStorage,
    ObjectStorageError,
    StorageUnavailable,
    build_object_key,
    validate_object_key,
)

__all__ = [
    "ChecksumMismatch",
    "InMemoryObjectStorage",
    "InvalidObjectKey",
    "ObjectMetadata",
    "ObjectNotFound",
    "ObjectStorage",
    "ObjectStorageError",
    "StorageUnavailable",
    "build_object_key",
    "validate_object_key",
]
