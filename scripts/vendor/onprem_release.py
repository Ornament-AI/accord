#!/usr/bin/env python3
"""Validate immutable on-premises release evidence.

Validation is local and read-only. This module never contacts a registry,
GitHub, Docker, or a VM.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import stat
import sys
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn
from urllib.parse import urlsplit

MAX_MANIFEST_BYTES = 128 * 1024
MAX_COMPOSE_BYTES = 1024 * 1024
MAX_FILES = 512
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_BUNDLE_BYTES = 256 * 1024 * 1024
MAX_IMAGES = 32
MAX_PROBES = 32

APPLICATION_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
IMAGE_REF_RE = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+@sha256:[0-9a-f]{64}$"
)


class ManifestError(ValueError):
    """A release manifest or bundle violates the contract."""


def fail(path: str, message: str) -> NoReturn:
    raise ManifestError(f"{path}: {message}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"manifest contains duplicate JSON key: {key}")
        result[key] = value
    return result


def require_object(value: Any, path: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(path, "must be an object")
    actual = set(value)
    missing = sorted(keys - actual)
    unknown = sorted(actual - keys)
    if missing:
        fail(path, f"missing fields: {', '.join(missing)}")
    if unknown:
        fail(path, f"unknown fields: {', '.join(unknown)}")
    return value


def require_list(value: Any, path: str, *, minimum: int, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        fail(path, "must be an array")
    if not minimum <= len(value) <= maximum:
        fail(path, f"must contain between {minimum} and {maximum} entries")
    return value


def require_string(
    value: Any,
    path: str,
    *,
    pattern: re.Pattern[str] | None = None,
    maximum: int = 512,
) -> str:
    if not isinstance(value, str) or not value:
        fail(path, "must be a non-empty string")
    if len(value) > maximum:
        fail(path, f"must be at most {maximum} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        fail(path, "must not contain control characters")
    if pattern is not None and pattern.fullmatch(value) is None:
        fail(path, "has an invalid format")
    return value


def require_int(value: Any, path: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        fail(path, "must be an integer")
    if not minimum <= value <= maximum:
        fail(path, f"must be between {minimum} and {maximum}")
    return value


def require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        fail(path, "must be a boolean")
    return value


def safe_relative_path(value: Any, path: str) -> str:
    candidate = require_string(value, path, maximum=255)
    if "\\" in candidate:
        fail(path, "must use POSIX separators")
    pure = PurePosixPath(candidate)
    if pure.as_posix() != candidate:
        fail(path, "must use a canonical relative path")
    if pure.is_absolute() or candidate in {".", ".."}:
        fail(path, "must be a non-root relative path")
    if any(part in {"", ".", ".."} for part in pure.parts):
        fail(path, "must not contain empty, current, or parent components")
    if len(pure.parts) > 16:
        fail(path, "contains too many path components")
    if any(len(part) > 128 for part in pure.parts):
        fail(path, "contains an oversized path component")
    return candidate


def safe_deploy_root(value: Any, path: str) -> str:
    if value == ".":
        return "."
    return safe_relative_path(value, path)


def validate_url(value: Any, path: str, target: str) -> str:
    url = require_string(value, path, maximum=2048)
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ManifestError(f"{path}: has an invalid URL") from exc
    if parsed.scheme not in {"http", "https"}:
        fail(path, "must use http or https")
    if not parsed.hostname or parsed.username or parsed.password:
        fail(path, "must have a hostname and no embedded credentials")
    if parsed.query or parsed.fragment:
        fail(path, "must not contain a query string or fragment")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ManifestError(f"{path}: has an invalid port") from exc
    hostname = parsed.hostname.rstrip(".").lower()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            hostname.encode("ascii")
        except UnicodeEncodeError:
            fail(path, "hostname must use ASCII DNS labels")
        if len(hostname) > 253 or any(
            DNS_LABEL_RE.fullmatch(label) is None for label in hostname.split(".")
        ):
            fail(path, "hostname has invalid DNS syntax")
        is_loopback = hostname == "localhost" or hostname.endswith(".localhost")
    else:
        mapped = getattr(address, "ipv4_mapped", None)
        is_loopback = address.is_loopback or bool(mapped and mapped.is_loopback)
    if target == "local":
        if not is_loopback:
            fail(path, "local probes must target loopback")
    elif target == "public":
        if parsed.scheme != "https" or is_loopback:
            fail(path, "public probes must use HTTPS and a non-loopback host")
    else:
        fail(path.rsplit(".", 1)[0] + ".target", "must be local or public")
    return url


def validate_manifest(document: Any) -> dict[str, Any]:
    root = require_object(
        document,
        "$",
        {
            "contract_version",
            "application",
            "source",
            "artifact",
            "images",
            "deployment",
        },
    )
    require_int(root["contract_version"], "$.contract_version", minimum=2, maximum=2)
    if root["contract_version"] != 2:
        fail("$.contract_version", "only contract version 2 is supported")

    application = require_string(
        root["application"], "$.application", pattern=APPLICATION_RE
    )
    source = require_object(
        root["source"], "$.source", {"repository", "commit_sha", "workflow_run_id"}
    )
    repository = require_string(
        source["repository"], "$.source.repository", pattern=REPOSITORY_RE
    )
    commit_sha = require_string(
        source["commit_sha"], "$.source.commit_sha", pattern=SHA_RE
    )
    require_int(
        source["workflow_run_id"],
        "$.source.workflow_run_id",
        minimum=1,
        maximum=2**63 - 1,
    )
    if repository.rsplit("/", 1)[1].lower() != application:
        fail("$.source.repository", "repository name must match application")

    artifact = require_object(
        root["artifact"], "$.artifact", {"name", "deploy_root", "files"}
    )
    expected_name = f"onprem-release-{commit_sha}"
    if artifact["name"] != expected_name:
        fail("$.artifact.name", f"must equal {expected_name}")
    deploy_root = safe_deploy_root(artifact["deploy_root"], "$.artifact.deploy_root")
    files = require_list(
        artifact["files"], "$.artifact.files", minimum=1, maximum=MAX_FILES
    )

    seen_paths: set[str] = set()
    total_size = 0
    deploy_root_path = PurePosixPath(deploy_root)
    for index, raw_file in enumerate(files):
        item_path = f"$.artifact.files[{index}]"
        item = require_object(raw_file, item_path, {"path", "sha256", "size"})
        file_path = safe_relative_path(item["path"], f"{item_path}.path")
        pure_file = PurePosixPath(file_path)
        if (
            deploy_root != "."
            and pure_file != deploy_root_path
            and deploy_root_path not in pure_file.parents
        ):
            fail(f"{item_path}.path", "must be inside artifact.deploy_root")
        if file_path in seen_paths:
            fail(f"{item_path}.path", "duplicates an earlier file")
        seen_paths.add(file_path)
        if pure_file.name == ".env" or "secrets" in pure_file.parts:
            fail(
                f"{item_path}.path",
                "release artifacts must not include runtime secrets",
            )
        require_string(item["sha256"], f"{item_path}.sha256", pattern=SHA256_RE)
        size = require_int(
            item["size"], f"{item_path}.size", minimum=1, maximum=MAX_FILE_BYTES
        )
        total_size += size
        if total_size > MAX_BUNDLE_BYTES:
            fail(
                "$.artifact.files",
                f"declared bundle size exceeds {MAX_BUNDLE_BYTES} bytes",
            )

    images = require_list(root["images"], "$.images", minimum=1, maximum=MAX_IMAGES)
    image_services: set[str] = set()
    for index, raw_image in enumerate(images):
        item_path = f"$.images[{index}]"
        item = require_object(raw_image, item_path, {"service", "reference"})
        service = require_string(
            item["service"], f"{item_path}.service", pattern=SERVICE_RE
        )
        if service in image_services:
            fail(f"{item_path}.service", "duplicates an earlier image service")
        image_services.add(service)
        reference = require_string(
            item["reference"], f"{item_path}.reference", pattern=IMAGE_REF_RE
        )
        image_name = reference.split("@", 1)[0]
        if ":" in image_name.rsplit("/", 1)[1]:
            fail(
                f"{item_path}.reference",
                "must not include an image tag before the digest",
            )

    deployment = require_object(
        root["deployment"],
        "$.deployment",
        {
            "adapter",
            "adapter_version",
            "compose_file",
            "migration",
            "probes",
            "runtime_services",
            "singleton_services",
        },
    )
    adapter = require_string(
        deployment["adapter"], "$.deployment.adapter", pattern=APPLICATION_RE
    )
    if adapter != application:
        fail("$.deployment.adapter", "must match application")
    require_int(
        deployment["adapter_version"],
        "$.deployment.adapter_version",
        minimum=1,
        maximum=2**31 - 1,
    )
    compose_file = safe_relative_path(
        deployment["compose_file"], "$.deployment.compose_file"
    )
    if compose_file not in seen_paths:
        fail("$.deployment.compose_file", "must name a declared deploy file")

    runtime_services = require_list(
        deployment["runtime_services"],
        "$.deployment.runtime_services",
        minimum=1,
        maximum=MAX_IMAGES,
    )
    seen_runtime_services: set[str] = set()
    for index, raw_service in enumerate(runtime_services):
        item_path = f"$.deployment.runtime_services[{index}]"
        service = require_string(raw_service, item_path, pattern=SERVICE_RE)
        if service in seen_runtime_services:
            fail(item_path, "duplicates an earlier runtime service")
        seen_runtime_services.add(service)
    if seen_runtime_services != image_services:
        fail(
            "$.deployment.runtime_services",
            "must exactly match the services recorded in images",
        )

    migration = require_object(
        deployment["migration"],
        "$.deployment.migration",
        {"mode", "service", "backup_required"},
    )
    mode = require_string(migration["mode"], "$.deployment.migration.mode", maximum=16)
    if mode not in {"none", "required"}:
        fail("$.deployment.migration.mode", "must be none or required")
    service_value = migration["service"]
    if mode == "required":
        migration_service = require_string(
            service_value, "$.deployment.migration.service", pattern=SERVICE_RE
        )
        if migration_service not in image_services:
            fail(
                "$.deployment.migration.service",
                "must name a digest-bound service in images",
            )
        if not require_bool(
            migration["backup_required"], "$.deployment.migration.backup_required"
        ):
            fail(
                "$.deployment.migration.backup_required",
                "must be true for required migrations",
            )
    else:
        if service_value is not None:
            fail(
                "$.deployment.migration.service",
                "must be null when migration mode is none",
            )
        require_bool(
            migration["backup_required"], "$.deployment.migration.backup_required"
        )

    singleton_services = require_list(
        deployment["singleton_services"],
        "$.deployment.singleton_services",
        minimum=1,
        maximum=MAX_IMAGES,
    )
    seen_singletons: set[str] = set()
    for index, raw_service in enumerate(singleton_services):
        path = f"$.deployment.singleton_services[{index}]"
        service = require_string(raw_service, path, pattern=SERVICE_RE)
        if service in seen_singletons:
            fail(path, "duplicates an earlier singleton service")
        if service not in image_services:
            fail(path, "must name a service in images")
        seen_singletons.add(service)

    probes = require_list(
        deployment["probes"], "$.deployment.probes", minimum=4, maximum=MAX_PROBES
    )
    seen_names: set[str] = set()
    seen_kinds: set[str] = set()
    allowed_kinds = {"health", "readiness", "auth", "public"}
    for index, raw_probe in enumerate(probes):
        item_path = f"$.deployment.probes[{index}]"
        item = require_object(
            raw_probe, item_path, {"name", "kind", "target", "url", "expected_status"}
        )
        name = require_string(item["name"], f"{item_path}.name", pattern=SERVICE_RE)
        if name in seen_names:
            fail(f"{item_path}.name", "duplicates an earlier probe")
        seen_names.add(name)
        kind = require_string(item["kind"], f"{item_path}.kind", maximum=16)
        if kind not in allowed_kinds:
            fail(
                f"{item_path}.kind",
                f"must be one of {', '.join(sorted(allowed_kinds))}",
            )
        if kind in seen_kinds:
            fail(f"{item_path}.kind", "duplicates an earlier required probe kind")
        seen_kinds.add(kind)
        target = require_string(item["target"], f"{item_path}.target", maximum=16)
        validate_url(item["url"], f"{item_path}.url", target)
        expected_status = require_int(
            item["expected_status"],
            f"{item_path}.expected_status",
            minimum=100,
            maximum=599,
        )
        if kind == "public" and target != "public":
            fail(f"{item_path}.target", "public probe kind must use public target")
        if kind != "public" and target != "local":
            fail(f"{item_path}.target", f"{kind} probe kind must use local target")
        if kind == "auth" and expected_status not in {401, 403}:
            fail(f"{item_path}.expected_status", "auth probes must expect 401 or 403")
        if kind != "auth" and not 200 <= expected_status <= 299:
            fail(
                f"{item_path}.expected_status",
                f"{kind} probes must expect a 2xx status",
            )
    missing_kinds = sorted(allowed_kinds - seen_kinds)
    if missing_kinds:
        fail(
            "$.deployment.probes",
            f"missing required probe kinds: {', '.join(missing_kinds)}",
        )
    return root


def validate_adapter(document: Any) -> dict[str, Any]:
    adapter = require_object(
        document,
        "$",
        {
            "contract_version",
            "application",
            "repository",
            "deploy_root",
            "adapter_version",
            "compose_file",
            "migration",
            "singleton_services",
            "runtime_services",
            "probes",
        },
    )
    require_object(
        adapter["migration"],
        "$.migration",
        {"mode", "service", "backup_required"},
    )
    deploy_root = safe_deploy_root(adapter["deploy_root"], "$.deploy_root")
    compose_file = safe_relative_path(adapter["compose_file"], "$.compose_file")
    deploy_prefix = PurePosixPath(deploy_root)
    if deploy_root != "." and deploy_prefix not in PurePosixPath(compose_file).parents:
        fail("$.compose_file", "must be inside deploy_root")
    require_int(adapter["contract_version"], "$.contract_version", minimum=2, maximum=2)
    singleton_services = require_list(
        adapter["singleton_services"],
        "$.singleton_services",
        minimum=1,
        maximum=MAX_IMAGES,
    )
    dummy_digest = "0" * 64
    dummy_commit = "0" * 40
    image_services = require_list(
        adapter["runtime_services"],
        "$.runtime_services",
        minimum=1,
        maximum=MAX_IMAGES,
    )
    manifest = {
        "contract_version": adapter["contract_version"],
        "application": adapter["application"],
        "source": {
            "repository": adapter["repository"],
            "commit_sha": dummy_commit,
            "workflow_run_id": 1,
        },
        "artifact": {
            "name": f"onprem-release-{dummy_commit}",
            "deploy_root": deploy_root,
            "files": [
                {
                    "path": file_path,
                    "sha256": dummy_digest,
                    "size": 1,
                }
                for file_path in dict.fromkeys(
                    [
                        compose_file,
                        (
                            "contract-placeholder"
                            if deploy_root == "."
                            else f"{deploy_root}/contract-placeholder"
                        ),
                    ]
                )
            ],
        },
        "images": [
            {
                "service": service,
                "reference": f"ghcr.io/ornament-ai/placeholder/{service}@sha256:{dummy_digest}",
            }
            for service in image_services
        ],
        "deployment": {
            "adapter": adapter["application"],
            "adapter_version": adapter["adapter_version"],
            "compose_file": compose_file,
            "migration": adapter["migration"],
            "runtime_services": image_services,
            "singleton_services": singleton_services,
            "probes": adapter["probes"],
        },
    }
    validate_manifest(manifest)
    return adapter


def load_json_file(path: Path, *, label: str) -> Any:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
    except OSError as exc:
        raise ManifestError(
            f"{label} must be a readable regular file, not a symlink: {exc}"
        ) from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ManifestError(f"{label} must be a regular file")
        if file_stat.st_size > MAX_MANIFEST_BYTES:
            raise ManifestError(f"{label} exceeds {MAX_MANIFEST_BYTES} bytes")
        with os.fdopen(descriptor, "rb", closefd=True) as source:
            descriptor = -1
            raw = source.read(MAX_MANIFEST_BYTES + 1)
        document = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ManifestError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    finally:
        if descriptor >= 0:
            with suppress(OSError):
                os.close(descriptor)
    return document


def load_manifest(path: Path) -> dict[str, Any]:
    return validate_manifest(load_json_file(path, label="manifest"))


def load_adapter(path: Path) -> dict[str, Any]:
    return validate_adapter(load_json_file(path, label="adapter"))


def canonicalize_digest_reference(reference: str, path: str) -> str:
    name_with_tag, separator, digest = reference.partition("@sha256:")
    if not separator or not SHA256_RE.fullmatch(digest):
        fail(path, "image must be digest-pinned")
    prefix, slash, final_component = name_with_tag.rpartition("/")
    if not slash:
        prefix = "docker.io/library"
        final_component = name_with_tag
    else:
        registry = prefix.split("/", 1)[0]
        if "." not in registry and ":" not in registry and registry != "localhost":
            prefix = f"docker.io/{prefix}"
    repository_component = final_component.split(":", 1)[0]
    canonical = f"{prefix}/{repository_component}@sha256:{digest}"
    require_string(canonical, path, pattern=IMAGE_REF_RE)
    return canonical


def load_compose_lines(path: Path) -> list[str]:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
    except OSError as exc:
        raise ManifestError(
            f"compose file must be a readable regular file, not a symlink: {exc}"
        ) from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ManifestError("compose file must be a regular file")
        if file_stat.st_size > MAX_COMPOSE_BYTES:
            raise ManifestError(f"compose file exceeds {MAX_COMPOSE_BYTES} bytes")
        with os.fdopen(descriptor, "rb", closefd=True) as source:
            descriptor = -1
            raw = source.read(MAX_COMPOSE_BYTES + 1)
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ManifestError(f"compose file is not readable UTF-8: {exc}") from exc
    finally:
        if descriptor >= 0:
            with suppress(OSError):
                os.close(descriptor)

    return text.splitlines()


def locate_compose_services(lines: list[str]) -> tuple[int, int, int, dict[str, int]]:
    services_headers = [
        index for index, line in enumerate(lines) if line == "services:"
    ]
    if len(services_headers) != 1:
        raise ManifestError(
            "compose file must contain exactly one top-level services block"
        )
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or line[0].isspace():
            continue
        key_match = re.fullmatch(r"([a-z][a-z0-9-]*):(?:\s.*)?", line)
        if key_match is None:
            raise ManifestError(
                "compose top-level keys must use simple lowercase block syntax"
            )
        if key_match.group(1) in {"include", "extends"}:
            raise ManifestError("compose file must not use external composition")
    start = services_headers[0] + 1
    end = len(lines)
    for index in range(start, len(lines)):
        line = lines[index]
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            end = index
            break

    significant_lines: list[tuple[int, int]] = []
    for index in range(start, end):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise ManifestError("compose indentation must use spaces")
        significant_lines.append((index, len(line) - len(line.lstrip())))
    if not significant_lines:
        raise ManifestError("compose services block has no direct services")
    service_indent = min(indent for _, indent in significant_lines)
    if service_indent < 1:
        raise ManifestError("compose services must be indented block entries")
    direct_services: dict[str, int] = {}
    for index, indent in significant_lines:
        if indent != service_indent:
            continue
        match = re.fullmatch(
            rf" {{{service_indent}}}([a-z][a-z0-9-]{{0,62}}):(?:\s*#.*)?",
            lines[index],
        )
        if match is None:
            raise ManifestError(
                "compose services must use lowercase block-style names matching "
                "[a-z][a-z0-9-]*"
            )
        name = match.group(1)
        if name in direct_services:
            raise ManifestError(f"compose service {name!r} appears more than once")
        direct_services[name] = index
    return start, end, service_indent, direct_services


def load_digest_bound_compose_image_raw(path: Path, service: str) -> str:
    """Return the strict direct image scalar from one Compose service."""
    service = require_string(service, "service", pattern=SERVICE_RE)
    lines = load_compose_lines(path)
    _, end, service_indent, direct_services = locate_compose_services(lines)
    if service not in direct_services:
        raise ManifestError(f"compose service {service!r} must appear exactly once")

    service_start = direct_services[service] + 1
    service_end = end
    for index in range(service_start, end):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= service_indent:
            service_end = index
            break
    content_lines = [
        line
        for line in lines[service_start:service_end]
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not content_lines:
        raise ManifestError(
            f"compose service {service!r} must have exactly one direct image"
        )
    direct_indent = min(len(line) - len(line.lstrip()) for line in content_lines)
    image_values: list[str] = []
    for line in lines[service_start:service_end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent != direct_indent:
            continue
        key_match = re.fullmatch(
            rf" {{{direct_indent}}}([a-z][a-z0-9_-]*):(?:\s.*)?", line
        )
        if key_match is None:
            raise ManifestError(
                f"compose service {service!r} attributes must use simple block syntax"
            )
        if key_match.group(1) == "extends":
            raise ManifestError("compose file must not use external composition")
        match = re.fullmatch(
            r"""\s+image:\s*(?:"([^"\r\n]+)"|'([^'\r\n]+)'|([^\s#'\"]+))\s*(?:#.*)?""",
            line,
        )
        if match:
            image_values.append(next(value for value in match.groups() if value))
    if len(image_values) != 1:
        raise ManifestError(
            f"compose service {service!r} must have exactly one direct image"
        )

    return image_values[0]


def resolve_compose_image_value(reference: str, service: str) -> str:
    if "$" in reference:
        fail(
            f"compose.services.{service}.image",
            "must be a literal digest reference without interpolation",
        )
    return canonicalize_digest_reference(reference, f"compose.services.{service}.image")


def load_digest_bound_compose_image(path: Path, service: str) -> str:
    reference = load_digest_bound_compose_image_raw(path, service)
    return resolve_compose_image_value(reference, service)


def resolve_runtime_images(
    bundle_root: Path,
    deploy_root: str,
    compose_file: str,
    services: list[str],
) -> list[dict[str, str]]:
    deploy_prefix = PurePosixPath(deploy_root)
    compose_relative = PurePosixPath(compose_file)
    if deploy_root != "." and deploy_prefix not in compose_relative.parents:
        fail("compose_file", "must be inside deploy_root")
    compose_path = bundle_root.joinpath(*compose_relative.parts)
    compose_services = set(locate_compose_services(load_compose_lines(compose_path))[3])
    declared_services = set(services)
    if declared_services != compose_services:
        missing = sorted(compose_services - declared_services)
        unknown = sorted(declared_services - compose_services)
        details: list[str] = []
        if missing:
            details.append(f"missing Compose services: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown services: {', '.join(unknown)}")
        fail("runtime_services", "; ".join(details))
    images: list[dict[str, str]] = []
    for service in services:
        raw_image = load_digest_bound_compose_image_raw(compose_path, service)
        reference = resolve_compose_image_value(raw_image, service)
        images.append({"service": service, "reference": reference})
    return images


def hash_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb", closefd=True) as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def open_regular_file_beneath(
    root: Path, relative: PurePosixPath
) -> tuple[int, os.stat_result]:
    directory_flags = (
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    directory_fd = os.open(root, directory_flags)
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(relative.parts[-1], file_flags, dir_fd=directory_fd)
    except OSError:
        os.close(directory_fd)
        raise
    os.close(directory_fd)
    file_stat = os.fstat(file_fd)
    if not stat.S_ISREG(file_stat.st_mode):
        os.close(file_fd)
        raise ManifestError(f"bundle:{relative.as_posix()}: must be a regular file")
    return file_fd, file_stat


def collect_bundle_files(bundle_root: Path, deploy_root: str) -> list[dict[str, Any]]:
    try:
        root_stat = bundle_root.lstat()
    except OSError as exc:
        raise ManifestError(f"bundle root cannot be inspected: {exc}") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ManifestError("bundle root must be a real directory, not a symlink")
    deploy_relative = PurePosixPath(deploy_root)
    deploy_directory = (
        bundle_root
        if deploy_root == "."
        else bundle_root.joinpath(*deploy_relative.parts)
    )
    try:
        deploy_stat = deploy_directory.lstat()
    except OSError as exc:
        raise ManifestError(f"bundle deploy root cannot be inspected: {exc}") from exc
    if stat.S_ISLNK(deploy_stat.st_mode) or not stat.S_ISDIR(deploy_stat.st_mode):
        raise ManifestError(
            "bundle deploy root must be a real directory, not a symlink"
        )

    paths: list[str] = []
    for current_root, directories, files in os.walk(
        deploy_directory,
        followlinks=False,
        onerror=lambda exc: fail("bundle", f"directory traversal failed: {exc}"),
    ):
        current = Path(current_root)
        for directory in directories:
            candidate = current / directory
            relative = candidate.relative_to(bundle_root).as_posix()
            if candidate.is_symlink():
                fail(f"bundle:{relative}", "path contains a symlink")
            if "secrets" in PurePosixPath(relative).parts:
                fail(
                    f"bundle:{relative}",
                    "release artifacts must not include secret paths",
                )
        for filename in files:
            candidate = current / filename
            relative = candidate.relative_to(bundle_root).as_posix()
            pure = PurePosixPath(relative)
            if candidate.is_symlink():
                fail(f"bundle:{relative}", "path contains a symlink")
            if pure.name == ".env" or "secrets" in pure.parts:
                fail(
                    f"bundle:{relative}",
                    "release artifacts must not include runtime secrets",
                )
            paths.append(relative)

    if not 1 <= len(paths) <= MAX_FILES:
        fail("bundle", f"must contain between 1 and {MAX_FILES} deploy files")
    entries: list[dict[str, Any]] = []
    total_size = 0
    for relative in sorted(paths):
        descriptor, file_stat = open_regular_file_beneath(
            bundle_root, PurePosixPath(relative)
        )
        if not 1 <= file_stat.st_size <= MAX_FILE_BYTES:
            os.close(descriptor)
            fail(
                f"bundle:{relative}",
                f"size must be between 1 and {MAX_FILE_BYTES} bytes",
            )
        total_size += file_stat.st_size
        if total_size > MAX_BUNDLE_BYTES:
            os.close(descriptor)
            fail("bundle", f"size exceeds {MAX_BUNDLE_BYTES} bytes")
        entries.append(
            {
                "path": relative,
                "sha256": hash_descriptor(descriptor),
                "size": file_stat.st_size,
            }
        )
    return entries


def validate_bundle(manifest: dict[str, Any], bundle_root: Path) -> None:
    try:
        root_stat = bundle_root.lstat()
    except OSError as exc:
        raise ManifestError(f"bundle root cannot be inspected: {exc}") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ManifestError("bundle root must be a real directory, not a symlink")
    deploy_root_value = manifest["artifact"]["deploy_root"]
    deploy_root = PurePosixPath(deploy_root_value)
    expected_paths = {entry["path"] for entry in manifest["artifact"]["files"]}
    deploy_directory = (
        bundle_root
        if deploy_root_value == "."
        else bundle_root.joinpath(*deploy_root.parts)
    )
    try:
        deploy_stat = deploy_directory.lstat()
    except OSError as exc:
        raise ManifestError(f"bundle deploy root cannot be inspected: {exc}") from exc
    if stat.S_ISLNK(deploy_stat.st_mode) or not stat.S_ISDIR(deploy_stat.st_mode):
        raise ManifestError(
            "bundle deploy root must be a real directory, not a symlink"
        )

    actual_paths: set[str] = set()
    for current_root, directories, files in os.walk(
        deploy_directory,
        followlinks=False,
        onerror=lambda exc: fail("bundle", f"directory traversal failed: {exc}"),
    ):
        current = Path(current_root)
        for directory in directories:
            candidate = current / directory
            if candidate.is_symlink():
                fail(
                    f"bundle:{candidate.relative_to(bundle_root).as_posix()}",
                    "path contains a symlink",
                )
        for filename in files:
            candidate = current / filename
            relative = candidate.relative_to(bundle_root).as_posix()
            if candidate.is_symlink():
                fail(f"bundle:{relative}", "path contains a symlink")
            actual_paths.add(relative)
    unlisted = sorted(actual_paths - expected_paths)
    missing = sorted(expected_paths - actual_paths)
    if unlisted:
        fail("bundle", f"contains unlisted deploy files: {', '.join(unlisted)}")
    if missing:
        fail("bundle", f"is missing declared deploy files: {', '.join(missing)}")

    for entry in manifest["artifact"]["files"]:
        relative = PurePosixPath(entry["path"])
        try:
            descriptor, file_stat = open_regular_file_beneath(bundle_root, relative)
        except OSError as exc:
            raise ManifestError(
                f"bundle:{entry['path']}: cannot be inspected: {exc}"
            ) from exc
        actual_size = file_stat.st_size
        if actual_size != entry["size"]:
            os.close(descriptor)
            fail(
                f"bundle:{entry['path']}",
                f"size mismatch: expected {entry['size']}, found {actual_size}",
            )
        if hash_descriptor(descriptor) != entry["sha256"]:
            fail(f"bundle:{entry['path']}", "SHA-256 mismatch")

    deployment = manifest["deployment"]
    actual_images = resolve_runtime_images(
        bundle_root,
        manifest["artifact"]["deploy_root"],
        deployment["compose_file"],
        deployment["runtime_services"],
    )
    if actual_images != manifest["images"]:
        fail("bundle", "runtime image bindings do not match the manifest")


def validation_summary(
    manifest: dict[str, Any], bundle_checked: bool
) -> dict[str, Any]:
    return {
        "application": manifest["application"],
        "artifact": manifest["artifact"]["name"],
        "bundle_checked": bundle_checked,
        "commit_sha": manifest["source"]["commit_sha"],
        "contract_version": manifest["contract_version"],
        "file_count": len(manifest["artifact"]["files"]),
        "image_count": len(manifest["images"]),
        "status": "valid",
        "workflow_run_id": manifest["source"]["workflow_run_id"],
    }


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    adapter = load_adapter(args.adapter)
    files = collect_bundle_files(args.bundle_root, adapter["deploy_root"])
    images = resolve_runtime_images(
        args.bundle_root,
        adapter["deploy_root"],
        adapter["compose_file"],
        adapter["runtime_services"],
    )
    manifest = {
        "contract_version": adapter["contract_version"],
        "application": adapter["application"],
        "source": {
            "repository": adapter["repository"],
            "commit_sha": args.commit_sha,
            "workflow_run_id": args.workflow_run_id,
        },
        "artifact": {
            "name": f"onprem-release-{args.commit_sha}",
            "deploy_root": adapter["deploy_root"],
            "files": files,
        },
        "images": images,
        "deployment": {
            "adapter": adapter["application"],
            "adapter_version": adapter["adapter_version"],
            "compose_file": adapter["compose_file"],
            "migration": adapter["migration"],
            "runtime_services": adapter["runtime_services"],
            "singleton_services": adapter["singleton_services"],
            "probes": adapter["probes"],
        },
    }
    validate_manifest(manifest)
    output_parent = args.output.parent.resolve(strict=True)
    deploy_directory = (
        args.bundle_root
        if adapter["deploy_root"] == "."
        else args.bundle_root.joinpath(*PurePosixPath(adapter["deploy_root"]).parts)
    )
    try:
        output_parent.relative_to(deploy_directory.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise ManifestError("output must be outside the deploy surface")
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ManifestError(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes")
    try:
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise ManifestError(f"output must be a new regular file: {exc}") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as destination:
            descriptor = -1
            destination.write(encoded)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return manifest


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser(
        "validate", help="validate a release manifest"
    )
    validate_parser.add_argument("manifest", type=Path)
    validate_parser.add_argument("--bundle-root", type=Path)
    build_parser = subparsers.add_parser("build", help="build a release manifest")
    build_parser.add_argument("--adapter", type=Path, required=True)
    build_parser.add_argument("--bundle-root", type=Path, required=True)
    build_parser.add_argument("--commit-sha", required=True)
    build_parser.add_argument("--workflow-run-id", type=int, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    compose_image_parser = subparsers.add_parser(
        "compose-image", help="read one digest-pinned image from a Compose file"
    )
    compose_image_parser.add_argument("compose_file", type=Path)
    compose_image_parser.add_argument("--service", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "compose-image":
            print(load_digest_bound_compose_image(args.compose_file, args.service))
            return 0
        if args.command == "build":
            manifest = build_manifest(args)
            bundle_checked = True
        else:
            manifest = load_manifest(args.manifest)
            if args.bundle_root is not None:
                validate_bundle(manifest, args.bundle_root)
            bundle_checked = args.bundle_root is not None
        print(
            json.dumps(
                validation_summary(manifest, bundle_checked),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    except ManifestError as exc:
        print(f"invalid release evidence: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
