#!/usr/bin/env python3
"""Validate and optionally sanitize Accord's literal deployment environment."""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import sys

ALLOWED = {
    "ACCORD_DB_PASSWORD",
    "ACCORD_DB_USER",
    "ACCORD_DB_NAME",
    "ACCORD_TAG",
    "ACCORD_WEB_PORT",
    "DATABASE_URL",
    "MIGRATIONS_DATABASE_URL",
    "WORKER_DATABASE_URL",
    "WORKOS_CLIENT_ID",
    "WORKOS_API_KEY",
    "WORKOS_REDIRECT_URI",
    "WORKOS_WEBHOOK_SECRET",
    "SESSION_SECRET_KEY",
    "SESSION_COOKIE_NAME",
    "ENVIRONMENT",
    "CORS_ORIGINS",
    "PUBLIC_APP_URL",
    "BASE_URL",
    "LOG_LEVEL",
    "DEV_AUTH_BYPASS",
    "DB_POOL_SIZE",
    "DB_STATEMENT_TIMEOUT_MS",
    "OBJECT_STORAGE_ENDPOINT",
    "OBJECT_STORAGE_BUCKET",
    "OBJECT_STORAGE_ACCESS_KEY",
    "OBJECT_STORAGE_SECRET_KEY",
}
OBSOLETE = {
    "ACCORD_CONFIRMED_FRESH_INSTALL",
    "ACCORD_RELEASE_GHCR_USERNAME",
    "ACCORD_RELEASE_GHCR_TOKEN",
    "GHCR_USERNAME",
    "GHCR_TOKEN",
}
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def read_regular(path: str) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= 1_048_576:
            raise SystemExit("deployment environment must be a bounded regular file")
        content = os.read(descriptor, 1_048_577)
        after = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(content) != before.st_size or any(
            getattr(before, field) != getattr(after, field) for field in stable_fields
        ):
            raise SystemExit("deployment environment changed while being read")
        return content
    finally:
        os.close(descriptor)


def sanitized(content: bytes) -> bytes:
    text = content.decode("utf-8")
    retained: list[str] = []
    for lineno, raw in enumerate(text.splitlines(keepends=True), 1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            retained.append(raw)
            continue
        candidate = line[7:] if line.startswith("export ") else line
        key = candidate.split("=", 1)[0].strip()
        if KEY.fullmatch(key) is None:
            raise SystemExit(f"deployment environment line {lineno} has an invalid key")
        if key in OBSOLETE:
            continue
        if key not in ALLOWED:
            raise SystemExit(
                f"deployment environment line {lineno} uses unsupported variable {key}"
            )
        retained.append(raw)
    return "".join(retained).encode("utf-8")


def main() -> int:
    if len(sys.argv) not in {2, 4}:
        raise SystemExit("usage: validate-deploy-env.py SOURCE [--sanitize DESTINATION]")
    source = sys.argv[1]
    output = sanitized(read_regular(source))
    if len(sys.argv) == 2:
        return 0
    if sys.argv[2] != "--sanitize":
        raise SystemExit("second argument must be --sanitize")
    destination = Path(sys.argv[3])
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        view = memoryview(output)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
