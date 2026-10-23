"""Reviewed source profiles for offline experiments; no runtime discovery."""
import hashlib
import json
import re
from pathlib import Path


class EvidenceError(ValueError):
    """Static code only; never echo untrusted evidence."""


def require(condition, code):
    if not condition:
        raise EvidenceError(code)


def fingerprint(value):
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def application_profile(repository):
    require(type(repository) is str and re.fullmatch(r"Ornament-AI/[a-z][a-z0-9-]*", repository), "unsupported_repository")
    path = Path(__file__).with_name("profiles") / (repository.split("/")[1] + ".json")
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "invalid_profile")
            value[key] = item
        return value
    try:
        require(path.stat().st_size <= 100_000, "invalid_profile")
        profile = json.loads(path.read_text(), object_pairs_hook=pairs)
    except (OSError, ValueError):
        raise EvidenceError("unsupported_repository") from None
    require(type(profile) is dict and set(profile) == {"schema", "repository", "source_commit", "source_path", "delivery", "assessment", "components", "writers", "recovery_format", "constraints"}, "invalid_profile")
    require(type(profile["schema"]) is int and profile["schema"] == 1 and profile["repository"] == repository, "invalid_profile")
    require(type(profile["source_commit"]) is str and re.fullmatch(r"[0-9a-f]{40}", profile["source_commit"]), "invalid_profile")
    components = profile["components"]
    require(type(components) is dict, "invalid_profile")
    for name, role in components.items():
        require(type(name) is str and re.fullmatch(r"[a-z][a-z0-9_-]*", name), "invalid_profile")
        require(role in ("web", "backend", "worker", "migration", "database", "infrastructure"), "invalid_profile")
    writers = profile["writers"]
    require(type(writers) is list and all(type(name) is str for name in writers)
            and len(writers) == len(set(writers)), "invalid_profile")
    require(profile["assessment"] in ("offline", "adapter-pending", "not-configured"), "invalid_profile")
    if profile["assessment"] == "offline":
        require(bool(components) and "external" in writers and type(profile["recovery_format"]) is dict
                and set(profile["recovery_format"]) == {"database", "files"}, "invalid_profile")
    return profile
