"""Protocol conformance tests for ``ObjectStorage`` implementations.

Phase-6 seam
------------
These tests are parametrized over a ``storage_factory`` fixture list. Today
only ``InMemoryObjectStorage`` is registered. When Phase 6 adds a MinIO/S3
adapter, append another factory (and any needed setup/teardown) to
``STORAGE_FACTORIES`` so the **same** test bodies exercise the new backend:

    STORAGE_FACTORIES = [
        pytest.param(in_memory_factory, id="memory"),
        pytest.param(minio_factory, id="minio"),  # Phase 6
    ]
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from uuid import uuid4

import pytest

from app.storage import (
    ChecksumMismatch,
    InMemoryObjectStorage,
    InvalidObjectKey,
    ObjectNotFound,
    ObjectStorage,
    StorageUnavailable,
    build_object_key,
    validate_object_key,
)

StorageFactory = Callable[[], ObjectStorage]


def _in_memory_factory() -> ObjectStorage:
    return InMemoryObjectStorage()


STORAGE_FACTORIES = [
    pytest.param(_in_memory_factory, id="memory"),
]


@pytest.fixture(params=STORAGE_FACTORIES)
def storage(request: pytest.FixtureRequest) -> ObjectStorage:
    """Build an ``ObjectStorage`` under test (parametrized seam for Phase 6)."""
    factory: StorageFactory = request.param
    return factory()


@pytest.mark.asyncio
async def test_put_get_roundtrip_and_checksum(storage: ObjectStorage) -> None:
    org = uuid4()
    key = build_object_key(org)
    body = b"payroll-bytes-42"
    meta = await storage.put(key, body, "application/octet-stream")

    assert meta.key == key
    assert meta.size_bytes == len(body)
    assert meta.content_type == "application/octet-stream"
    assert meta.checksum_sha256 == hashlib.sha256(body).hexdigest()
    assert meta.object_version
    assert await storage.get(key) == body


@pytest.mark.asyncio
async def test_stream_yields_object_bytes(storage: ObjectStorage) -> None:
    key = build_object_key(uuid4())
    body = b"x" * 100_000
    await storage.put(key, body, "application/octet-stream")
    chunks: list[bytes] = []
    async for chunk in storage.stream(key):
        chunks.append(chunk)
    assert b"".join(chunks) == body


@pytest.mark.asyncio
async def test_get_missing_key_raises_object_not_found(storage: ObjectStorage) -> None:
    key = build_object_key(uuid4())
    with pytest.raises(ObjectNotFound):
        await storage.get(key)


@pytest.mark.asyncio
async def test_delete_then_get_raises_object_not_found(storage: ObjectStorage) -> None:
    key = build_object_key(uuid4())
    await storage.put(key, b"tmp", "text/plain")
    await storage.delete(key)
    with pytest.raises(ObjectNotFound):
        await storage.get(key)


@pytest.mark.asyncio
async def test_exists_true_false(storage: ObjectStorage) -> None:
    key = build_object_key(uuid4())
    assert await storage.exists(key) is False
    await storage.put(key, b"present", "text/plain")
    assert await storage.exists(key) is True


def test_key_validator_accepts_valid_opaque_keys() -> None:
    org = uuid4()
    obj = uuid4()
    key = f"{org}/{obj}"
    assert validate_object_key(key) == key
    assert build_object_key(org, obj) == key


@pytest.mark.parametrize(
    "bad_key",
    [
        "not-a-uuid/also-not",
        "acme-corp/payslips-2024",
        f"{uuid4()}/payslip.pdf",
        f"{uuid4()}/{uuid4()}/extra",
        f"{uuid4()}",
        f"../{uuid4()}",
        f"{uuid4()}/../{uuid4()}",
        f"/{uuid4()}/{uuid4()}",
        f"{uuid4()}//{uuid4()}",
        "",
        "employee-name/bank-file",
    ],
)
def test_key_validator_rejects_invalid_keys(bad_key: str) -> None:
    with pytest.raises(InvalidObjectKey):
        validate_object_key(bad_key)


@pytest.mark.asyncio
async def test_storage_unavailable_fault_injection() -> None:
    store = InMemoryObjectStorage()
    key = build_object_key(uuid4())
    store.inject_fault()
    with pytest.raises(StorageUnavailable):
        await store.put(key, b"nope", "text/plain")
    # Fault is one-shot; subsequent ops succeed.
    meta = await store.put(key, b"ok", "text/plain")
    assert meta.size_bytes == 2


@pytest.mark.asyncio
async def test_put_checksum_mismatch(storage: ObjectStorage) -> None:
    key = build_object_key(uuid4())
    with pytest.raises(ChecksumMismatch):
        await storage.put(
            key,
            b"body",
            "text/plain",
            expected_checksum_sha256="0" * 64,
        )
    assert await storage.exists(key) is False


@pytest.mark.asyncio
async def test_put_accepts_async_iterator(storage: ObjectStorage) -> None:
    key = build_object_key(uuid4())

    async def gen():
        yield b"chunk-a"
        yield b"chunk-b"

    meta = await storage.put(key, gen(), "application/octet-stream")
    assert await storage.get(key) == b"chunk-achunk-b"
    assert meta.checksum_sha256 == hashlib.sha256(b"chunk-achunk-b").hexdigest()
