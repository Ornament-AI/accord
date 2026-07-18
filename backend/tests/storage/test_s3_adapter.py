"""Unit and MinIO integration tests for ``S3ObjectStorage``.

Integration tests require a reachable S3-compatible endpoint (default MinIO at
``http://127.0.0.1:9000``). Override with:

- ``ACCORD_TEST_S3_ENDPOINT``
- ``ACCORD_TEST_S3_ACCESS_KEY``
- ``ACCORD_TEST_S3_SECRET_KEY``
- ``ACCORD_TEST_S3_REGION``

When the endpoint health check fails, integration tests are skipped; unit tests
that stub the boto3 client still run.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from botocore.exceptions import ClientError, EndpointConnectionError

from app.storage.protocol import (
    ChecksumMismatch,
    InvalidObjectKey,
    ObjectNotFound,
    ObjectStorageError,
    StorageUnavailable,
    build_object_key,
)
from app.storage.s3 import S3ObjectStorage, ensure_bucket

_ENDPOINT = os.environ.get("ACCORD_TEST_S3_ENDPOINT", "http://127.0.0.1:9000")
_ACCESS_KEY = os.environ.get("ACCORD_TEST_S3_ACCESS_KEY", "minioadmin")
_SECRET_KEY = os.environ.get("ACCORD_TEST_S3_SECRET_KEY", "minioadmin")
_REGION = os.environ.get("ACCORD_TEST_S3_REGION", "us-east-1")


def _minio_reachable() -> bool:
    """Probe MinIO/S3 health; used by module-level skipif for integration tests."""
    health_url = _ENDPOINT.rstrip("/") + "/minio/health/live"
    try:
        with urllib.request.urlopen(health_url, timeout=1.0) as resp:
            return 200 <= getattr(resp, "status", 0) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


_MINIO_AVAILABLE = _minio_reachable()
requires_minio = pytest.mark.skipif(
    not _MINIO_AVAILABLE,
    reason=(
        "MinIO not reachable at ACCORD_TEST_S3_ENDPOINT "
        f"(default http://127.0.0.1:9000; probed {_ENDPOINT}/minio/health/live); "
        "start MinIO to run S3 integration tests"
    ),
)


def _client_error(
    code: str,
    *,
    operation: str = "GetObject",
    http_status: int | None = None,
) -> ClientError:
    response: dict[str, Any] = {"Error": {"Code": code, "Message": code}}
    if http_status is not None:
        response["ResponseMetadata"] = {"HTTPStatusCode": http_status}
    return ClientError(response, operation)


def _storage_with_mock_client() -> tuple[S3ObjectStorage, MagicMock]:
    storage = S3ObjectStorage(
        endpoint_url="http://127.0.0.1:9000",
        bucket="accord-unit-test",
        access_key="test",
        secret_key="test",
        region="us-east-1",
    )
    mock = MagicMock()
    storage._client = mock
    return storage, mock


# ---------------------------------------------------------------------------
# Unit tests (no server)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name,call",
    [
        ("get", lambda s: s.get("not-a-uuid/also-not")),
        ("exists", lambda s: s.exists("bad-key")),
        ("delete", lambda s: s.delete("employee-name/bank-file")),
        (
            "put",
            lambda s: s.put("acme-corp/payslips", b"x", "text/plain"),
        ),
    ],
)
async def test_invalid_key_raises_before_client_call(method_name: str, call: Any) -> None:
    storage, mock = _storage_with_mock_client()
    with pytest.raises(InvalidObjectKey):
        await call(storage)
    assert mock.mock_calls == [], f"expected no client calls for {method_name}"


@pytest.mark.asyncio
async def test_invalid_key_stream_raises_before_client_call() -> None:
    storage, mock = _storage_with_mock_client()
    with pytest.raises(InvalidObjectKey):
        async for _ in storage.stream("not-a-uuid/also-not"):
            pass
    assert mock.mock_calls == []


@pytest.mark.asyncio
async def test_put_buffers_async_iterator_and_computes_checksum() -> None:
    storage, mock = _storage_with_mock_client()
    mock.put_object.return_value = {"ETag": '"abc123"', "VersionId": "v1"}
    key = build_object_key(uuid4())
    body = b"chunk-achunk-b"

    async def gen() -> AsyncIterator[bytes]:
        yield b"chunk-a"
        yield b"chunk-b"

    meta = await storage.put(key, gen(), "application/octet-stream")
    assert meta.checksum_sha256 == hashlib.sha256(body).hexdigest()
    assert meta.size_bytes == len(body)
    assert meta.object_version == "v1"
    mock.put_object.assert_called_once()
    kwargs = mock.put_object.call_args.kwargs
    assert kwargs["Body"] == body
    assert kwargs["ContentType"] == "application/octet-stream"
    assert kwargs["Key"] == key


@pytest.mark.asyncio
async def test_put_checksum_mismatch_does_not_call_put_object() -> None:
    storage, mock = _storage_with_mock_client()
    key = build_object_key(uuid4())
    with pytest.raises(ChecksumMismatch):
        await storage.put(
            key,
            b"body",
            "text/plain",
            expected_checksum_sha256="0" * 64,
        )
    mock.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_get_maps_no_such_key_to_object_not_found() -> None:
    storage, mock = _storage_with_mock_client()
    mock.get_object.side_effect = _client_error("NoSuchKey", http_status=404)
    key = build_object_key(uuid4())
    with pytest.raises(ObjectNotFound):
        await storage.get(key)


@pytest.mark.asyncio
async def test_get_maps_404_status_to_object_not_found() -> None:
    storage, mock = _storage_with_mock_client()
    mock.get_object.side_effect = _client_error("404", http_status=404)
    key = build_object_key(uuid4())
    with pytest.raises(ObjectNotFound):
        await storage.get(key)


@pytest.mark.asyncio
async def test_exists_maps_not_found_to_false() -> None:
    storage, mock = _storage_with_mock_client()
    mock.head_object.side_effect = _client_error("NotFound", http_status=404)
    key = build_object_key(uuid4())
    assert await storage.exists(key) is False


@pytest.mark.asyncio
async def test_delete_missing_raises_object_not_found() -> None:
    storage, mock = _storage_with_mock_client()
    mock.head_object.side_effect = _client_error("NoSuchKey", http_status=404)
    key = build_object_key(uuid4())
    with pytest.raises(ObjectNotFound):
        await storage.delete(key)
    mock.delete_object.assert_not_called()


@pytest.mark.asyncio
async def test_maps_endpoint_connection_error_to_storage_unavailable() -> None:
    storage, mock = _storage_with_mock_client()
    mock.get_object.side_effect = EndpointConnectionError(endpoint_url=_ENDPOINT)
    key = build_object_key(uuid4())
    with pytest.raises(StorageUnavailable):
        await storage.get(key)


@pytest.mark.asyncio
async def test_maps_5xx_client_error_to_storage_unavailable() -> None:
    storage, mock = _storage_with_mock_client()
    mock.get_object.side_effect = _client_error("InternalError", http_status=500)
    key = build_object_key(uuid4())
    with pytest.raises(StorageUnavailable):
        await storage.get(key)


@pytest.mark.asyncio
async def test_maps_throttling_to_storage_unavailable() -> None:
    storage, mock = _storage_with_mock_client()
    mock.get_object.side_effect = _client_error("SlowDown", http_status=503)
    key = build_object_key(uuid4())
    with pytest.raises(StorageUnavailable):
        await storage.get(key)


@pytest.mark.asyncio
async def test_maps_other_client_error_to_object_storage_error() -> None:
    storage, mock = _storage_with_mock_client()
    mock.get_object.side_effect = _client_error("AccessDenied", http_status=403)
    key = build_object_key(uuid4())
    with pytest.raises(ObjectStorageError) as exc_info:
        await storage.get(key)
    assert not isinstance(exc_info.value, (ObjectNotFound, StorageUnavailable))


# ---------------------------------------------------------------------------
# Integration tests (live MinIO)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def s3_storage() -> AsyncIterator[S3ObjectStorage]:
    if not _MINIO_AVAILABLE:
        pytest.skip(
            "MinIO not reachable at ACCORD_TEST_S3_ENDPOINT "
            f"(default http://127.0.0.1:9000; probed {_ENDPOINT}/minio/health/live)"
        )
    bucket = f"accord-test-{uuid4().hex}"
    storage = S3ObjectStorage(
        endpoint_url=_ENDPOINT,
        bucket=bucket,
        access_key=_ACCESS_KEY,
        secret_key=_SECRET_KEY,
        region=_REGION,
    )
    await ensure_bucket(storage)
    try:
        yield storage
    finally:
        await _teardown_bucket(storage)


async def _teardown_bucket(storage: S3ObjectStorage) -> None:
    client = storage._client
    bucket = storage._bucket

    def _cleanup() -> None:
        try:
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket):
                for obj in page.get("Contents", []) or []:
                    client.delete_object(Bucket=bucket, Key=obj["Key"])
            client.delete_bucket(Bucket=bucket)
        except ClientError:
            # Best-effort cleanup for throwaway test buckets.
            pass

    await asyncio.to_thread(_cleanup)


@requires_minio
@pytest.mark.asyncio
async def test_put_get_roundtrip_and_checksum(s3_storage: S3ObjectStorage) -> None:
    org = uuid4()
    key = build_object_key(org)
    body = b"payroll-bytes-42"
    meta = await s3_storage.put(key, body, "application/octet-stream")

    assert meta.key == key
    assert meta.size_bytes == len(body)
    assert meta.content_type == "application/octet-stream"
    assert meta.checksum_sha256 == hashlib.sha256(body).hexdigest()
    assert meta.object_version
    assert await s3_storage.get(key) == body


@requires_minio
@pytest.mark.asyncio
async def test_stream_yields_object_bytes(s3_storage: S3ObjectStorage) -> None:
    key = build_object_key(uuid4())
    body = b"x" * 100_000
    await s3_storage.put(key, body, "application/octet-stream")
    chunks: list[bytes] = []
    async for chunk in s3_storage.stream(key):
        chunks.append(chunk)
    assert b"".join(chunks) == body


@requires_minio
@pytest.mark.asyncio
async def test_get_missing_key_raises_object_not_found(s3_storage: S3ObjectStorage) -> None:
    key = build_object_key(uuid4())
    with pytest.raises(ObjectNotFound):
        await s3_storage.get(key)


@requires_minio
@pytest.mark.asyncio
async def test_delete_then_get_raises_object_not_found(s3_storage: S3ObjectStorage) -> None:
    key = build_object_key(uuid4())
    await s3_storage.put(key, b"tmp", "text/plain")
    await s3_storage.delete(key)
    with pytest.raises(ObjectNotFound):
        await s3_storage.get(key)


@requires_minio
@pytest.mark.asyncio
async def test_exists_true_false(s3_storage: S3ObjectStorage) -> None:
    key = build_object_key(uuid4())
    assert await s3_storage.exists(key) is False
    await s3_storage.put(key, b"present", "text/plain")
    assert await s3_storage.exists(key) is True


@requires_minio
@pytest.mark.asyncio
async def test_put_checksum_mismatch(s3_storage: S3ObjectStorage) -> None:
    key = build_object_key(uuid4())
    with pytest.raises(ChecksumMismatch):
        await s3_storage.put(
            key,
            b"body",
            "text/plain",
            expected_checksum_sha256="0" * 64,
        )
    assert await s3_storage.exists(key) is False


@requires_minio
@pytest.mark.asyncio
async def test_put_accepts_async_iterator(s3_storage: S3ObjectStorage) -> None:
    key = build_object_key(uuid4())

    async def gen() -> AsyncIterator[bytes]:
        yield b"chunk-a"
        yield b"chunk-b"

    meta = await s3_storage.put(key, gen(), "application/octet-stream")
    assert await s3_storage.get(key) == b"chunk-achunk-b"
    assert meta.checksum_sha256 == hashlib.sha256(b"chunk-achunk-b").hexdigest()
