#!/usr/bin/env python3
"""Application-local proof for one locked, same-boot preparation attempt.

The wrapper authenticates the v2 bundle before this adapter runs. This record
is neither a shared release contract nor evidence for a no-op. Secret contents
and their hashes are never stored; isolated file identity binds runtime inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
APPLICATION = "accord"
TAG_VARIABLE = "ACCORD_TAG"
SERVICES = {"web", "role-sync", "worker", "api", "migrations", "minio", "postgres", "minio-init"}
SECRET_FILES = {}
PROOF = ".release-prepared.json"
SOURCES = ".prepared-credential-sources.json"
ATTEMPT_VARIABLE = "RELEASE_PREPARATION_ATTEMPT"
RUNTIME_FILES = {
    ".env",
    "release-manifest.json",
    "release-checksums.txt",
    "release-signature.sig",
    "release-backup-evidence",
    "release-bootstrap-evidence",
    PROOF,
    SOURCES,
}


class PreparationError(RuntimeError):
    pass


def phase(root: Path, directory: str, name: str):
    spec = importlib.util.spec_from_file_location("phase_timing", root / "phase_timing.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.measure_phase(
        Path(os.environ["RELEASE_PREPARATION_EVIDENCE"]) / directory,
        os.environ[ATTEMPT_VARIABLE],
        name,
    )


def require(condition, message):
    if not condition:
        raise PreparationError(message)


def metadata(path: Path):
    item = path.lstat()
    require(stat.S_ISREG(item.st_mode), "input must be a regular non-symlink file")
    return {
        name: getattr(item, name)
        for name in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    }


def read_input(path: Path):
    before = metadata(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(os.fstat(fd).st_size <= 128 * 1024 * 1024, "input is too large")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read()
    finally:
        os.close(fd)
    require(before == metadata(path), "input changed during inspection")
    return data, before


def environment_file(root: Path):
    data, _ = read_input(root / ".env")
    values = {}
    compose_source = (root / "docker-compose.yml").read_text()
    example = (root / ".env.example").read_text()
    allowed = set(re.findall(r"(?<!\$)\$(?:\{)?([A-Za-z_][A-Za-z0-9_]*)", compose_source))
    allowed.update(re.findall(r"(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", example))
    # Existing retired registry/bootstrap settings remain ignored by setup.
    allowed.update(
        {
            "GHCR_TOKEN",
            "GHCR_TOKEN_FILE",
            "GHCR_USERNAME",
            "ACCORD_RELEASE_GHCR_USERNAME",
            "ACCORD_RELEASE_GHCR_TOKEN",
            "ACCORD_CONFIRMED_FRESH_INSTALL",
        }
    )
    for line in data.decode().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = (part.strip() for part in line.split("=", 1))
        require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is not None, "invalid environment key")
        require(key not in values, "duplicate environment key")
        require(key in allowed, "untracked environment key")
        require(
            not key.startswith(("COMPOSE_", "DOCKER_", "RELEASE_PREPARATION_", "PYTHON", "LD_"))
            and key
            not in {
                "PATH",
                "HOME",
                "BASH_ENV",
                "ENV",
                "SHELLOPTS",
                "BASHOPTS",
                "CDPATH",
                "MODE",
                "SCRIPT_DIR",
            },
            "untracked process/Compose input",
        )
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def validator(root: Path):
    spec = importlib.util.spec_from_file_location("onprem_release", root / "onprem_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest(root: Path):
    module = validator(root)
    data = module.load_manifest(root / "release-manifest.json")
    require(data["application"] == APPLICATION, "wrong application")
    require(
        data["artifact"]["deploy_root"] == "deploy"
        and data["deployment"]["compose_file"] == "deploy/docker-compose.yml",
        "unsupported deployment layout",
    )
    require({item["service"] for item in data["images"]} == SERVICES, "unknown service inventory")
    return module, data


def docker_environment(root: Path):
    # Environment values are interpreted literally, matching safe_source_env.
    # Only variables referenced by the signed Compose file enter interpolation;
    # shell/Compose/registry overrides in an ambient environment cannot win.
    transport = {
        name: os.environ[name]
        for name in (
            "PATH",
            "HOME",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
            "XDG_RUNTIME_DIR",
            "SSH_AUTH_SOCK",
        )
        if name in os.environ
    }
    source = (root / "docker-compose.yml").read_text()
    names = set(re.findall(r"(?<!\$)\$(?:\{)?([A-Za-z_][A-Za-z0-9_]*)", source))
    require(
        not names.intersection(transport)
        and not any(name.startswith("COMPOSE_") for name in names),
        "reserved interpolation input",
    )
    transport.update({key: value for key, value in environment_file(root).items() if key in names})
    return transport


def compose_command(root: Path, arguments):
    return [
        "docker",
        "compose",
        "--project-directory",
        str(root),
        "--env-file",
        str(root / ".env"),
        "-f",
        str(root / "docker-compose.yml"),
        *arguments,
    ]


def docker_output(root: Path, command):
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=docker_environment(root),
        check=False,
    )
    require(result.returncode == 0, "Docker preparation command failed")
    return result.stdout


def configuration(root: Path, module, release):
    result = json.loads(
        docker_output(
            root, compose_command(root, ["config", "--format", "json", "--no-env-resolution"])
        )
    )
    expected = {item["service"]: item["reference"] for item in release["images"]}
    require(set(result["services"]) == SERVICES, "resolved service inventory changed")
    for name, service in result["services"].items():
        require(
            not any(key in service for key in ("build", "profiles", "env_file", "develop")),
            "untracked Compose service input",
        )
        require(
            module.canonicalize_digest_reference(service["image"], name) == expected[name],
            "resolved image differs from signed manifest",
        )
        for volume in service.get("volumes", []):
            if volume["type"] == "bind":
                require(volume.get("read_only") is True, "untracked writable bind mount")
                require(
                    Path(volume["source"]).resolve().is_relative_to(root.resolve()),
                    "external configuration bind mount",
                )
    for section in ("secrets", "configs"):
        for value in result.get(section, {}).values():
            require(
                "file" in value and Path(value["file"]).resolve().is_relative_to(root.resolve()),
                "external configuration/credential input",
            )
    return result, expected


def image_identity(root: Path, module, reference):
    records = json.loads(docker_output(root, ["docker", "image", "inspect", reference]))
    require(isinstance(records, list) and len(records) == 1, "ambiguous local image")
    image = records[0]
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", image["Id"]) is not None, "invalid local image ID")
    aliases = {
        module.canonicalize_digest_reference(value, "cached image")
        for value in image.get("RepoDigests", [])
    }
    require(reference in aliases, "signed digest is not in the local image store")
    return image["Id"]


def inputs(root: Path, release):
    paths = {}
    for entry in release["artifact"]["files"]:
        path = Path(entry["path"])
        require(path.parts[0] == "deploy", "unexpected deploy file")
        relative = Path(*path.parts[1:])
        data, identity = read_input(root / relative)
        require(
            len(data) == entry["size"] and hashlib.sha256(data).hexdigest() == entry["sha256"],
            "signed deployment input changed",
        )
        paths[str(relative)] = identity
    allowed_directories = {".prepared-secrets"} if SECRET_FILES else set()
    for path in paths:
        allowed_directories.update(
            str(parent) for parent in Path(path).parents if str(parent) != "."
        )
    for current, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            require(
                str((Path(current) / name).relative_to(root)) in allowed_directories,
                "untracked deployment directory",
            )
            require(not (Path(current) / name).is_symlink(), "symlinked input directory")
        for name in files:
            relative = (Path(current) / name).relative_to(root)
            if str(relative) in paths:
                continue
            require(
                str(relative) in RUNTIME_FILES
                or (
                    relative.parts[0] == ".prepared-secrets"
                    and len(relative.parts) == 2
                    and relative.name in SECRET_FILES.values()
                ),
                "untracked deployment file",
            )
            if str(relative) in {PROOF, "release-backup-evidence", "release-bootstrap-evidence"}:
                continue
            paths[str(relative)] = metadata(root / relative)
    require(".env" in paths, "missing candidate environment")
    return paths


def write_private(path: Path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def stage(root: Path):
    _, release = manifest(root)
    values = environment_file(root)
    sources = {}
    replacements = {TAG_VARIABLE: "sha-" + release["source"]["commit_sha"]}
    for key in ("PUBLIC_APP_URL", "BASE_URL"):
        if key in values:
            replacements[key] = values[key].removesuffix("/")
    if SECRET_FILES:
        target = root / ".prepared-secrets"
        target.mkdir(mode=0o700)
        for variable, filename in SECRET_FILES.items():
            source = Path(values.get(variable, ""))
            require(
                source.is_absolute()
                and not source.is_relative_to(root)
                and not source.is_relative_to(Path("/opt") / APPLICATION / "deploy"),
                "credential source must be an explicit absolute file outside deployment trees",
            )
            data, identity = read_input(source)
            require(data, "empty credential input")
            # Private directory and root-owned copies with existing modes; live sources are
            # never chmod/chown'ed. Compose mounts each isolated file read-only.
            fd = os.open(
                target / filename,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                stat.S_IMODE(identity["st_mode"]),
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            sources[str(source)] = identity
            replacements[variable] = f"./.prepared-secrets/{filename}"
    original = (root / ".env").read_text()
    lines = [
        line
        for line in original.splitlines()
        if not re.match(r"^(?:export\s+)?(?:" + "|".join(replacements) + r")\s*=", line.strip())
    ]
    lines.extend(f"{key}={value}" for key, value in replacements.items())
    temporary = root / ".prepared-environment"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(lines) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, root / ".env")
    write_private(root / SOURCES, sources)


def prove_credential_readability(root: Path, config):
    for service in config["services"].values():
        secrets = service.get("secrets", [])
        if not secrets:
            continue
        command = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--entrypoint=/bin/sh",
        ]
        if service.get("user"):
            command.extend(["--user", service["user"]])
        targets = []
        for item in secrets:
            source = config["secrets"][item["source"]]["file"]
            target = "/run/secrets/" + item.get("target", item["source"])
            require("," not in source and "," not in target, "unsupported credential path")
            command.extend(["--mount", f"type=bind,src={source},dst={target},readonly"])
            targets.append(target)
        command.extend(
            [
                service["image"],
                "-ec",
                'for path do test -r "$path" && test -s "$path" || exit 1; done',
                "credential-probe",
                *targets,
            ]
        )
        docker_output(root, command)


def proof_context(root: Path):
    attempt = os.environ.get(ATTEMPT_VARIABLE, "")
    require(str(uuid.UUID(attempt)) == attempt, "missing canonical preparation attempt")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    require(str(uuid.UUID(boot)) == boot, "missing boot identity")
    return attempt, boot


def prepare_or_verify(root: Path, prepare: bool):
    module, release = manifest(root)
    if prepare:
        with phase(root, "configuration", "configuration-validation"):
            config, bindings = configuration(root, module, release)
    else:
        config, bindings = configuration(root, module, release)
    before = inputs(root, release)
    sources = json.loads((root / SOURCES).read_text())
    require(
        all(metadata(Path(path)) == identity for path, identity in sources.items()),
        "source credentials changed",
    )

    def inspect_images():
        images = {}
        for reference in sorted(set(bindings.values())):
            if prepare:
                try:
                    image_identity(root, module, reference)
                except PreparationError:
                    docker_output(root, ["docker", "pull", reference])
            images[reference] = image_identity(root, module, reference)
        return images

    if prepare:
        with phase(root, "images", "image-preparation"):
            images = inspect_images()
        with phase(root, "credentials", "credential-preparation"):
            prove_credential_readability(root, config)
    else:
        images = inspect_images()
    require(inputs(root, release) == before, "candidate inputs changed during preparation")
    require(
        all(metadata(Path(path)) == identity for path, identity in sources.items()),
        "source credentials changed during preparation",
    )
    attempt, boot = proof_context(root)
    proof = {
        "application": APPLICATION,
        "attempt": attempt,
        "boot_id": boot,
        "manifest_sha256": hashlib.sha256(
            (root / "release-manifest.json").read_bytes()
        ).hexdigest(),
        "inputs": before,
        "images": images,
        "credential_sources": sources,
    }
    if prepare:
        write_private(root / PROOF, proof)
    else:
        data, identity = read_input(root / PROOF)
        require(
            identity["st_uid"] == os.geteuid() and stat.S_IMODE(identity["st_mode"]) == 0o600,
            "unsafe preparation proof",
        )
        require(json.loads(data) == proof, "prepared attempt, inputs or cached images changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "prepare", "verify", "compose"))
    parser.add_argument("root", type=Path)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        root = args.root.absolute()
        require(root.is_dir() and not root.is_symlink(), "invalid candidate directory")
        if args.mode == "stage":
            with phase(root, "credential-copy", "credential-preparation"):
                stage(root)
        elif args.mode == "compose":
            # Thin environment adapter; lifecycle decisions stay in setup.sh.
            command = compose_command(root, args.arguments)
            os.execvpe(command[0], command, docker_environment(root))
        else:
            prepare_or_verify(root, args.mode == "prepare")
    except (PreparationError, OSError, ValueError, KeyError, TypeError):
        sys.exit("prepare-release: input, image or preparation proof failed validation")


if __name__ == "__main__":
    main()
