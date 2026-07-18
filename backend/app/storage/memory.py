"""In-memory ``ObjectStorage`` test double (ADR 0010 Phase 1).

Stores object bytes in a process-local dict. Suitable for unit tests and
local protocol exercises — not for production. Concurrent async callers are
serialized with an ``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from uuid import uuid4

from app.storage.protocol import (
    ChecksumMismatch,
    ObjectMetadata,
    ObjectNotFound,
    StorageUnavailable,
    validate_object_key,
)


class InMemoryObjectStorage:
    """Dict-backed ``ObjectStorage`` with real SHA-256 and fault injection."""

    def __init__(
        self,
        *,
        fault_injector: Callable[[], None] | None = None,
    ) -> None:
        self._objects: dict[str, tuple[bytes, ObjectMetadata]] = {}
        self._lock = asyncio.Lock()
        self._fail_next = False
        self._fault_injector = fault_injector

    def inject_fault(self) -> None:
        """Cause the next mutating/read operation to raise ``StorageUnavailable``."""
        self._fail_next = True

    def _maybe_fail(self) -> None:
        if self._fault_injector is not None:
            self._fault_injector()
        if self._fail_next:
            self._fail_next = False
            raise StorageUnavailable("in-memory storage fault injected")

    async def _read_data(self, data: bytes | AsyncIterator[bytes]) -> bytes:
        if isinstance(data, bytes):
            return data
        chunks: list[bytes] = []
        async for chunk in data:
            chunks.append(chunk)
        return b"".join(chunks)

    async def put(
        self,
        key: str,
        data: bytes | AsyncIterator[bytes],
        content_type: str,
        *,
        expected_checksum_sha256: str | None = None,
    ) -> ObjectMetadata:
        key = validate_object_key(key)
        body = await self._read_data(data)
        checksum = hashlib.sha256(body).hexdigest()
        if expected_checksum_sha256 is not None and expected_checksum_sha256.lower() != checksum:
            raise ChecksumMismatch(
                "computed SHA-256 does not match expected checksum",
                details={
                    "key": key,
                    "expected": expected_checksum_sha256,
                    "actual": checksum,
                },
            )
        metadata = ObjectMetadata(
            key=key,
            checksum_sha256=checksum,
            size_bytes=len(body),
            content_type=content_type,
            object_version=uuid4().hex,
        )
        async with self._lock:
            self._maybe_fail()
            self._objects[key] = (body, metadata)
        return metadata

    async def get(self, key: str) -> bytes:
        key = validate_object_key(key)
        async with self._lock:
            self._maybe_fail()
            entry = self._objects.get(key)
            if entry is None:
                raise ObjectNotFound(
                    "object not found",
                    details={"key": key},
                )
            return entry[0]

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        # Materialize under the lock, then yield outside so consumers are not
        # blocked for the full iteration window.
        body = await self.get(key)
        chunk_size = 64 * 1024
        if not body:
            yield b""
            return
        for i in range(0, len(body), chunk_size):
            yield body[i : i + chunk_size]

    async def exists(self, key: str) -> bool:
        key = validate_object_key(key)
        async with self._lock:
            self._maybe_fail()
            return key in self._objects

    async def delete(self, key: str) -> None:
        key = validate_object_key(key)
        async with self._lock:
            self._maybe_fail()
            if key not in self._objects:
                raise ObjectNotFound(
                    "object not found",
                    details={"key": key},
                )
            del self._objects[key]
