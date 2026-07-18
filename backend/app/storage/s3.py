"""S3-compatible ``ObjectStorage`` adapter (ADR 0010 Phase 6).

Uses boto3's synchronous S3 client and wraps blocking calls with
``asyncio.to_thread`` so the async protocol stays non-blocking on the event
loop without pulling in aioboto3. Suitable for MinIO (local/CI) and managed S3.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from typing import TypeVar

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

from app.storage.protocol import (
    ChecksumMismatch,
    ObjectMetadata,
    ObjectNotFound,
    ObjectStorageError,
    StorageUnavailable,
    validate_object_key,
)

_CHUNK_SIZE = 64 * 1024
_DEFAULT_REGION = "us-east-1"
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound", "NoSuchBucket"})
_UNAVAILABLE_CODES = frozenset(
    {
        "SlowDown",
        "Throttling",
        "ThrottlingException",
        "RequestTimeout",
        "ServiceUnavailable",
        "TooManyRequestsException",
        "InternalError",
        "ServiceFailure",
    }
)

T = TypeVar("T")


class S3ObjectStorage:
    """boto3-backed ``ObjectStorage`` for S3-compatible endpoints (e.g. MinIO)."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = _DEFAULT_REGION,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._bucket = bucket
        self._region = region or _DEFAULT_REGION
        # Path-style addressing works reliably with MinIO and custom endpoints.
        self._client: BaseClient = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=self._region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )

    async def ensure_bucket(self) -> None:
        """Create the configured bucket if it does not already exist."""

        def _ensure() -> None:
            try:
                self._client.head_bucket(Bucket=self._bucket)
                return
            except ClientError as exc:
                if not _is_not_found(exc):
                    _raise_mapped_client_error(exc)
                # Fall through to create.
            if self._region == _DEFAULT_REGION:
                self._client.create_bucket(Bucket=self._bucket)
            else:
                self._client.create_bucket(
                    Bucket=self._bucket,
                    CreateBucketConfiguration={"LocationConstraint": self._region},
                )

        await self._run(_ensure)

    async def put(
        self,
        key: str,
        data: bytes | AsyncIterator[bytes],
        content_type: str,
        *,
        expected_checksum_sha256: str | None = None,
    ) -> ObjectMetadata:
        key = validate_object_key(key)
        body, checksum = await self._buffer_and_hash(data)
        if expected_checksum_sha256 is not None and expected_checksum_sha256.lower() != checksum:
            raise ChecksumMismatch(
                "computed SHA-256 does not match expected checksum",
                details={
                    "key": key,
                    "expected": expected_checksum_sha256,
                    "actual": checksum,
                },
            )

        def _put() -> dict:
            return self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )

        response = await self._run(_put, key=key)
        version_id = response.get("VersionId")
        etag = str(response.get("ETag", "")).strip('"')
        object_version = version_id or etag
        return ObjectMetadata(
            key=key,
            checksum_sha256=checksum,
            size_bytes=len(body),
            content_type=content_type,
            object_version=object_version,
        )

    async def get(self, key: str) -> bytes:
        key = validate_object_key(key)

        def _get() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()

        return await self._run(_get, key=key)

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        key = validate_object_key(key)

        def _open() -> object:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"]

        body = await self._run(_open, key=key)
        try:
            first = True
            while True:
                try:
                    chunk = await asyncio.to_thread(body.read, _CHUNK_SIZE)
                except (
                    ClientError,
                    EndpointConnectionError,
                    ConnectionError,
                    BotoCoreError,
                ) as exc:
                    _raise_mapped(exc, key=key)
                if not chunk:
                    if first:
                        yield b""
                    break
                first = False
                yield chunk
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                await asyncio.to_thread(close)

    async def exists(self, key: str) -> bool:
        key = validate_object_key(key)

        def _head() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
                return True
            except ClientError as exc:
                if _is_not_found(exc):
                    return False
                _raise_mapped_client_error(exc, key=key)
                raise  # pragma: no cover — _raise_mapped_client_error always raises

        return await self._run(_head, key=key)

    async def delete(self, key: str) -> None:
        key = validate_object_key(key)

        def _delete() -> None:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if _is_not_found(exc):
                    raise ObjectNotFound(
                        "object not found",
                        details={"key": key},
                    ) from exc
                _raise_mapped_client_error(exc, key=key)
            self._client.delete_object(Bucket=self._bucket, Key=key)

        await self._run(_delete, key=key)

    async def _buffer_and_hash(self, data: bytes | AsyncIterator[bytes]) -> tuple[bytes, str]:
        hasher = hashlib.sha256()
        if isinstance(data, bytes):
            hasher.update(data)
            return data, hasher.hexdigest()
        chunks: list[bytes] = []
        async for chunk in data:
            hasher.update(chunk)
            chunks.append(chunk)
        body = b"".join(chunks)
        return body, hasher.hexdigest()

    async def _run(self, op: Callable[[], T], *, key: str | None = None) -> T:
        try:
            return await asyncio.to_thread(op)
        except ObjectStorageError:
            raise
        except (ClientError, EndpointConnectionError, ConnectionError, BotoCoreError) as exc:
            _raise_mapped(exc, key=key)
            raise  # pragma: no cover — _raise_mapped always raises


def _client_error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def _client_http_status(exc: ClientError) -> int | None:
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return int(status) if status is not None else None


def _is_not_found(exc: ClientError) -> bool:
    code = _client_error_code(exc)
    status = _client_http_status(exc)
    return code in _NOT_FOUND_CODES or status == 404


def _raise_mapped_client_error(exc: ClientError, *, key: str | None = None) -> None:
    code = _client_error_code(exc)
    status = _client_http_status(exc)
    details: dict = {"code": code}
    if key is not None:
        details["key"] = key
    if status is not None:
        details["http_status"] = status
    if _is_not_found(exc):
        raise ObjectNotFound("object not found", details=details) from exc
    if (status is not None and status >= 500) or code in _UNAVAILABLE_CODES:
        raise StorageUnavailable(
            "object storage unavailable",
            details=details,
        ) from exc
    raise ObjectStorageError(
        "object storage request failed",
        details=details,
    ) from exc


def _raise_mapped(exc: BaseException, *, key: str | None = None) -> None:
    if isinstance(exc, ObjectStorageError):
        raise exc
    if isinstance(exc, ClientError):
        _raise_mapped_client_error(exc, key=key)
    details: dict = {"error_type": type(exc).__name__}
    if key is not None:
        details["key"] = key
    raise StorageUnavailable(
        "object storage unavailable",
        details=details,
    ) from exc


async def ensure_bucket(storage: S3ObjectStorage) -> None:
    """Ensure ``storage``'s bucket exists (MinIO/local bootstrap helper)."""
    await storage.ensure_bucket()
