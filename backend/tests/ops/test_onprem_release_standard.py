from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / "scripts/vendor/onprem_release.py"
ADAPTER = ROOT / "deploy/onprem-release-adapter.json"


def _module():
    spec = importlib.util.spec_from_file_location("accord_onprem_release", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vendored_validator_is_exact_reviewed_source() -> None:
    source = dict(
        line.split("=", 1)
        for line in (ROOT / "scripts/vendor/ONPREM_RELEASE_SOURCE").read_text().splitlines()
    )
    assert source["repository"] == "Ornament-AI/msidc-infra"
    assert source["commit"] == "4d479c594f4adc87ff31436465138a61b1108ada"
    assert hashlib.sha256(VALIDATOR.read_bytes()).hexdigest() == source["sha256"]


def test_signing_key_is_valid_ed25519_public_key() -> None:
    result = subprocess.run(
        [
            "openssl",
            "pkey",
            "-pubin",
            "-in",
            str(ROOT / "deploy/onprem-release-signing-public.pem"),
            "-text_pub",
            "-noout",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "ED25519 Public-Key" in result.stdout


def test_adapter_declares_every_service_and_required_proof() -> None:
    adapter = json.loads(ADAPTER.read_text())
    assert _module().validate_adapter(adapter) == adapter
    assert adapter["runtime_services"] == [
        "api",
        "migrations",
        "minio",
        "minio-init",
        "postgres",
        "web",
        "worker",
    ]
    assert adapter["singleton_services"] == ["api", "web", "worker"]
    assert adapter["migration"] == {
        "backup_required": True,
        "mode": "required",
        "service": "migrations",
    }
    assert {probe["kind"] for probe in adapter["probes"]} == {
        "auth",
        "health",
        "public",
        "readiness",
    }


def test_package_builds_self_contained_digest_release(tmp_path: Path) -> None:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    environment = os.environ | {
        "ACCORD_BACKEND_DIGEST": f"sha256:{'a' * 64}",
        "ACCORD_WEB_DIGEST": f"sha256:{'b' * 64}",
        "GITHUB_RUN_ID": "12345",
        "SOURCE_SHA": sha,
    }
    subprocess.run(
        ["bash", "deploy/package-release.sh", str(tmp_path)],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    manifest = json.loads((tmp_path / f"onprem-release-{sha}.json").read_text())
    assert {item["service"] for item in manifest["images"]} == {
        "api",
        "migrations",
        "minio",
        "minio-init",
        "postgres",
        "web",
        "worker",
    }
    assert all("@sha256:" in item["reference"] for item in manifest["images"])
    with tarfile.open(tmp_path / f"accord-deploy-sha-{sha}.tar.gz", "r:gz") as bundle:
        names = set(bundle.getnames())
        assert "deploy/.env" not in names
        assert "deploy/create_roles.sql" in names
        assert "deploy/release-source-sha" in names
        assert all(".." not in Path(name).parts for name in names)

        extracted = tmp_path / "extracted"
        bundle.extractall(extracted, filter="data")

    manifest_path = tmp_path / f"onprem-release-{sha}.json"
    (extracted / "deploy/setup.sh").write_text("tampered\n")
    tampered_file = subprocess.run(
        [
            "python3",
            str(VALIDATOR),
            "validate",
            str(manifest_path),
            "--bundle-root",
            str(extracted),
        ],
        capture_output=True,
        text=True,
    )
    assert tampered_file.returncode != 0
    assert any(word in tampered_file.stderr.lower() for word in ("checksum", "size mismatch"))

    with tarfile.open(tmp_path / f"accord-deploy-sha-{sha}.tar.gz", "r:gz") as bundle:
        bundle.extractall(extracted, filter="data")

    mutable = json.loads(manifest_path.read_text())
    mutable["images"][0]["reference"] = "postgres:latest"
    mutable_path = tmp_path / "mutable.json"
    mutable_path.write_text(json.dumps(mutable))
    rejected = subprocess.run(
        ["python3", str(VALIDATOR), "validate", str(mutable_path), "--bundle-root", str(extracted)],
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert any(word in rejected.stderr.lower() for word in ("digest", "invalid format"))


def test_release_workflow_is_exact_main_signed_and_durable() -> None:
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
    assert "workflow_run:" in workflow and "workflows: [CI]" in workflow
    assert "name: Prove exact reviewed main SHA" in workflow
    assert 'git merge-base --is-ancestor "$SOURCE_SHA" origin/main' in workflow
    assert "actions/workflows/ci.yml/runs?head_sha=${SOURCE_SHA}&status=success" in workflow
    assert "Manual publication must select the current main head" in workflow
    assert "No successful main CI run exists for exact SHA" in workflow
    assert "SOURCE_SHA: ${{ needs.release-gate.outputs.source_sha }}" in workflow
    assert "name: Rehearse deployed-schema upgrade" in workflow
    assert "PREVIOUS_DEPLOYED_SHA: ${{ secrets.ONPREM_DEPLOYED_SHA }}" in workflow
    assert "Protected ONPREM_DEPLOYED_SHA evidence is missing or invalid" in workflow
    assert 'git merge-base --is-ancestor "$PREVIOUS_DEPLOYED_SHA" "$SOURCE_SHA"' in workflow
    assert (
        'git worktree add --detach ../accord-previous "${{ steps.previous.outputs.sha }}"'
        in workflow
    )
    assert "candidate_sha=" not in workflow
    assert "rollback_fallback=" not in workflow
    assert "python -m alembic check" in workflow
    assert "migrations-release-upgrade" in workflow
    assert "group: onprem-release-main" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "/backend:latest" not in workflow
    assert "/web:latest" not in workflow
    assert "MOVE_TAG" not in workflow
    assert workflow.count("digest: ${{ steps.build.outputs.digest }}") == 2
    assert "environment: onprem-release" in workflow
    assert "secrets.ONPREM_RELEASE_SIGNING_KEY" in workflow
    assert "openssl pkeyutl -sign -rawin" in workflow
    assert 'release_tag="onprem-sha-${SOURCE_SHA}"' in workflow
    assert "gh release create" in workflow
    assert "deploy-accord" not in workflow


def test_fixed_live_rollback_is_backfilled_from_reviewed_main_tooling() -> None:
    workflow = (ROOT / ".github/workflows/backfill-onprem-rollback.yml").read_text()
    package = (ROOT / "deploy/package-release.sh").read_text()
    rollback_sha = "8cc2f95d00d35ab6eb9d4ace31b2f605af10d10d"
    assert "workflow_dispatch:" in workflow
    assert "if: github.ref == 'refs/heads/main'" in workflow
    assert "environment: onprem-release" in workflow
    assert f"ROLLBACK_SHA: {rollback_sha}" in workflow
    assert "ACCORD_RELEASE_SHA: ${{ env.ROLLBACK_SHA }}" in workflow
    assert "actions/workflows/ci.yml/runs?head_sha=${TOOLING_SHA}&status=success" in workflow
    assert "fetch-depth: 0" in workflow
    assert "group: onprem-release-main" in workflow
    assert "docker buildx imagetools inspect" not in workflow
    assert 'ROLLBACK_BUILD_RUN_ID: "32671105169"' in workflow
    assert 'ROLLBACK_BACKEND_ARTIFACT_ID: "9501399945"' in workflow
    assert 'ROLLBACK_WEB_ARTIFACT_ID: "9501403873"' in workflow
    assert "actions/runs/${ROLLBACK_BUILD_RUN_ID}" in workflow
    assert "actions/artifacts/${artifact_id}" in workflow
    assert ".workflow_run.id == $run_id" in workflow
    assert ".workflow_run.head_sha == $sha" in workflow
    assert ".expired == false" in workflow
    assert "actions/artifacts/${artifact_id}/zip" in workflow
    assert 'tar -tzf "$build_record"' in workflow
    assert (
        "ROLLBACK_BACKEND_DIGEST: sha256:51c9dd7315bdfa1b81821ecef83b8e435a5df6ab0ff232165a123d2d444fd2ef"
        in workflow
    )
    assert (
        "ROLLBACK_WEB_DIGEST: sha256:7c223d7c91cdad07ee9786c8212f555d8ed9d3b1165faf3b6696512254f3b2ac"
        in workflow
    )
    assert 'reference="ghcr.io/ornament-ai/accord/${component}@${digest}"' in workflow
    assert "docker pull --platform linux/amd64" in workflow
    assert "org.opencontainers.image.revision" in workflow
    assert ":sha-${ROLLBACK_SHA}" not in workflow
    assert 'gh release create "$release_tag"' in workflow
    assert rollback_sha in package
    assert "release-tooling-source-sha" in package


def test_operator_path_uses_only_fixed_nopasswd_wrapper() -> None:
    deploy = (ROOT / "scripts/deploy.sh").read_text()
    installer = (ROOT / "scripts/install-release-wrapper.sh").read_text()
    receipt = (ROOT / "scripts/run-release-with-receipt.py").read_text()
    wrapper = (ROOT / "deploy/deploy-accord-wrapper.sh").read_text()
    assert '"/usr/local/bin/deploy-accord"' in receipt
    assert "gh auth token" not in deploy
    assert "ACCORD_GHCR_READ_TOKEN" in deploy
    assert "ornament-ai-accord-ghcr-read" in deploy
    assert "manifest inspect" in (ROOT / "scripts/stage-accord-release.sh").read_text()
    assert 'RECEIPT_CLIENT="$ROOT/scripts/run-release-with-receipt.py"' in deploy
    assert 'python3 "$RECEIPT_CLIENT"' in deploy
    assert "ACCORD_RELEASE_GHCR_TOKEN" in wrapper
    assert "ephemeral GHCR credentials" in (ROOT / "deploy/setup.sh").read_text()
    assert "GHCR_TOKEN=" not in (ROOT / "deploy/.env.example").read_text()
    assert "NOPASSWD: /usr/local/bin/deploy-accord *" in installer
    assert "visudo -cf /etc/sudoers.d/.accord-release.new" in installer
    assert "mv -f /etc/sudoers.d/.accord-release.new /etc/sudoers.d/accord-release" in installer
    assert "$CANONICAL_MAIN_SHA:deploy/validate-deploy-env.py" in installer
    assert "repos/Ornament-AI/accord/git/ref/heads/main" in installer
    assert "actions/workflows/ci.yml/runs?head_sha=" in installer
    assert "git fetch" not in installer
    assert "$CANONICAL_MAIN_SHA:deploy/deploy-accord-wrapper.sh" in installer
    assert "accord-wrapper-trust" in installer
    assert "O_NOFOLLOW" in wrapper
    assert "os.O_NOFOLLOW" in wrapper
    assert "fcntl.LOCK_EX | fcntl.LOCK_NB" in wrapper
    assert "accord-release-install.lock" in wrapper
    assert "exec 8>/run/lock" not in wrapper
    assert 'os.mkdir("accord-release", 0o700, dir_fd=parent)' in wrapper
    assert "writable /run/lock must have the sticky bit" in wrapper
    assert "ACCORD_RELEASE_LIVE_PROOF=" in wrapper
    assert "ACCORD_RELEASE_RECEIPT=" in wrapper
    assert wrapper.index("ACCORD_RELEASE_LIVE_PROOF=") < wrapper.index("ACCORD_RELEASE_RECEIPT=")
    assert wrapper.index("release signature verification failed") < wrapper.index(
        'docker stop "${APP_CONTAINER_IDS[@]}"'
    )
    assert 'APP_CONTAINER_IDS=("$API_CID" "$WORKER_CID" "$WEB_CID" "$MINIO_CID")' in wrapper
    assert wrapper.index("docker stop") < wrapper.index("backup-before-migrate.sh")
    assert wrapper.index("backup-before-migrate.sh") < wrapper.index('mv "$LIVE_ROOT"')
    migration_failure = wrapper.index("rollout failed after migrations started")
    restore_previous = wrapper.rindex('mv "$BACKUP_ROOT" "$LIVE_ROOT"')
    assert migration_failure < restore_previous
    assert "the authenticated release files remain active" in wrapper


def test_wrapper_installer_ignores_substituted_origin(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    fake_bin = tmp_path / "bin"
    (root / "scripts").mkdir(parents=True)
    (root / "deploy").mkdir()
    fake_bin.mkdir()
    installer = root / "scripts/install-release-wrapper.sh"
    installer.write_text((ROOT / "scripts/install-release-wrapper.sh").read_text())
    installer.chmod(0o755)
    (root / "deploy/deploy-accord-wrapper.sh").write_text(
        (ROOT / "deploy/deploy-accord-wrapper.sh").read_text()
    )
    canonical = "a" * 40
    command_log = tmp_path / "commands.log"
    (fake_bin / "git").write_text(
        "#!/bin/sh\n"
        'printf "git %s\\n" "$*" >> "$COMMAND_LOG"\n'
        'case "$*" in\n'
        "  *fetch*|*origin*) exit 91 ;;\n"
        "  *status*) exit 0 ;;\n"
        f'  *"rev-parse HEAD"*) printf "%s\\n" "{canonical}"; exit 0 ;;\n'
        '  *"show "*) printf "#!/usr/bin/env bash\\nexit 0\\n"; exit 0 ;;\n'
        "esac\n"
        "exit 92\n"
    )
    (fake_bin / "gh").write_text(
        "#!/bin/sh\n"
        'printf "gh %s\\n" "$*" >> "$COMMAND_LOG"\n'
        'case "$*" in\n'
        f'  *"git/ref/heads/main"*) printf "%s\\n" "{canonical}" ;;\n'
        '  *"actions/workflows/ci.yml/runs"*) printf "1\\n" ;;\n'
        "  *) exit 93 ;;\n"
        "esac\n"
    )
    (fake_bin / "ssh").write_text('#!/bin/sh\nprintf "ssh %s\\n" "$*" >> "$COMMAND_LOG"\nexit 1\n')
    (fake_bin / "scp").write_text("#!/bin/sh\nexit 94\n")
    for command in ("git", "gh", "ssh", "scp"):
        (fake_bin / command).chmod(0o755)

    result = subprocess.run(
        ["bash", str(installer)],
        capture_output=True,
        check=False,
        env=os.environ
        | {"COMMAND_LOG": str(command_log), "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        text=True,
    )

    assert result.returncode == 1
    assert "SSH key access is not ready" in result.stderr
    calls = command_log.read_text()
    assert "repos/Ornament-AI/accord/git/ref/heads/main" in calls
    assert "actions/workflows/ci.yml/runs" in calls
    assert "git fetch" not in calls
    assert "git origin" not in calls


def test_deploy_environment_validator_rejects_control_keys_and_sanitizes_registry(
    tmp_path: Path,
) -> None:
    validator = ROOT / "deploy/validate-deploy-env.py"
    unsafe = tmp_path / "unsafe.env"
    unsafe.write_text("ENVIRONMENT=production\nPATH=/tmp/attacker\n")
    rejected = subprocess.run(
        ["python3", str(validator), str(unsafe)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert rejected.returncode != 0
    assert "unsupported variable PATH" in rejected.stderr

    legacy = tmp_path / "legacy.env"
    sanitized = tmp_path / "sanitized.env"
    legacy.write_text("ENVIRONMENT=production\nGHCR_USERNAME=old-user\nGHCR_TOKEN=old-token\n")
    result = subprocess.run(
        ["python3", str(validator), str(legacy), "--sanitize", str(sanitized)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert sanitized.read_text() == "ENVIRONMENT=production\n"


def test_fresh_host_bootstrap_is_separate_authenticated_and_empty_only() -> None:
    bootstrap = (ROOT / "scripts/bootstrap-release-host.sh").read_text()
    wrapper = (ROOT / "deploy/deploy-accord-wrapper.sh").read_text()
    assert "ACCORD_BOOTSTRAP_ENV_FILE" in bootstrap
    assert "stat.S_IMODE(before.st_mode) != 0o600" in bootstrap
    assert "stat -f" not in bootstrap
    assert "repos/Ornament-AI/accord/git/ref/heads/main" in bootstrap
    assert "actions/workflows/ci.yml/runs?head_sha=" in bootstrap
    assert "exact current Ornament-AI/accord main SHA" in bootstrap
    assert "git fetch" not in bootstrap
    assert "$MAIN_SHA:deploy/deploy-accord-wrapper.sh" in bootstrap
    assert "accord-bootstrap-trust" in bootstrap
    assert "ENV_SNAPSHOT" in bootstrap
    assert "os.O_NOFOLLOW" in bootstrap
    assert "key not in allowed" in bootstrap
    assert 'scp -q "$ENV_SNAPSHOT"' in bootstrap
    assert bootstrap.index('bash "$STAGER"') < bootstrap.index("Enter the VM sudo password")
    assert "docker ps -aq" in bootstrap
    assert "docker volume inspect accord_pgdata" in bootstrap
    assert "docker volume inspect accord_minio-data" in bootstrap
    assert "/usr/local/bin/.deploy-accord.new" in bootstrap
    assert "sha256sum --check --status" in bootstrap
    assert ".allow-first-release-$SHA" in bootstrap
    assert 'python3 "$RECEIPT_CLIENT"' in bootstrap
    assert "ACCORD_CONFIRMED_FRESH_INSTALL" not in bootstrap
    assert "scripts/run-release-with-receipt.py" in bootstrap
    assert "release-bootstrap-evidence" in wrapper
    assert ".first-release-attempted-$SHA" in wrapper
    assert "accord_pgdata accord_minio-data deploy_pgdata deploy_minio-data" in wrapper


def test_migration_marker_precedes_compose_mutation() -> None:
    setup = (ROOT / "deploy/setup.sh").read_text()
    assert setup.index(': >"$ACCORD_MIGRATION_STATE_FILE"') < setup.index(
        "docker compose --env-file .env up -d --no-build"
    )
    assert "ACCORD_SMOKE_REQUIRE_DOCKER=true" in setup
    assert "/api/auth/me" in setup
    assert "$PUBLIC_APP_URL/api/readyz" in setup
    backup = (ROOT / "deploy/backup-before-migrate.sh").read_text()
    deploy = (ROOT / "deploy/deploy-accord.sh").read_text()
    wrapper = (ROOT / "deploy/deploy-accord-wrapper.sh").read_text()
    assert 'MINIO_VOLUME="accord_minio-data"' in backup
    assert "POSTGRES_USER" in backup and "POSTGRES_DB" in backup
    assert 'pg_dump -U "$DB_USER" -d "$DB_NAME"' in backup
    assert "pg_dump -U accord -d accord" not in backup
    assert "tar --one-file-system --numeric-owner" in backup
    assert "FINAL_OBJECTS_CHECKSUM" in backup
    assert "release MinIO backup checksum verification failed" in deploy
    assert "Verified paired PostgreSQL and MinIO" in deploy
    operations = (ROOT / "docs/operations.md").read_text()
    assert "Never restore only one member of the pair" in operations
    assert "restore the PostgreSQL dump and its matching" in operations
    assert "`.minio.tar.gz` archive to `accord_minio-data`" in operations
    assert "stop api worker web minio" in wrapper
    assert 'WEB_BINDING="$(docker port "$WEB_CID" 80/tcp)"' in deploy
    assert '"http://127.0.0.1:$WEB_PORT/api/healthz"' in deploy
    assert '"http://127.0.0.1:$WEB_PORT/api/readyz"' in deploy
    assert "http://127.0.0.1:8085/api/healthz" not in deploy


def test_release_receipt_update_is_serialized_by_remote_lock(tmp_path: Path) -> None:
    helper = ROOT / "scripts/run-release-with-receipt.py"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    event_log = tmp_path / "events.log"
    lock_file = tmp_path / "remote.lock"
    barrier_dir = tmp_path / "barrier"
    barrier_dir.mkdir()
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import fcntl, os, pathlib, shlex, sys, time\n"
        "command = shlex.split(sys.argv[2])\n"
        "sha, nonce = command[-3], command[-1]\n"
        "barrier = pathlib.Path(os.environ['FAKE_BARRIER_DIR'])\n"
        "(barrier / str(os.getpid())).touch()\n"
        "deadline = time.monotonic() + 5\n"
        "while len(list(barrier.iterdir())) < 2:\n"
        "    assert time.monotonic() < deadline\n"
        "    time.sleep(0.01)\n"
        "with open(os.environ['FAKE_REMOTE_LOCK'], 'w') as lock:\n"
        "    try:\n"
        "        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "    except BlockingIOError:\n"
        "        raise SystemExit(75)\n"
        "    username = sys.stdin.readline().rstrip('\\n')\n"
        "    token = sys.stdin.readline().rstrip('\\n')\n"
        "    assert username == 'release-user' and token == 't' * 24\n"
        "    with open(os.environ['FAKE_EVENT_LOG'], 'a') as events:\n"
        "        events.write(f'acquired:{sha}\\n'); events.flush()\n"
        "    print(f'ACCORD_RELEASE_LIVE_PROOF={sha}:{nonce}', flush=True)\n"
        "    acknowledgement = sys.stdin.readline().rstrip('\\n')\n"
        "    assert acknowledgement == f'ACCORD_RELEASE_RECEIPT={sha}:{nonce}'\n"
        "    with open(os.environ['FAKE_EVENT_LOG'], 'a') as events:\n"
        "        events.write(f'ack:{sha}\\n'); events.flush()\n"
    )
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, time\n"
        "sha = sys.stdin.read()\n"
        "with open(os.environ['FAKE_EVENT_LOG'], 'a') as events:\n"
        "    events.write(f'gh-start:{sha}\\n'); events.flush()\n"
        "time.sleep(0.2)\n"
        "with open(os.environ['FAKE_EVENT_LOG'], 'a') as events:\n"
        "    events.write(f'gh-end:{sha}\\n'); events.flush()\n"
    )
    fake_ssh.chmod(0o755)
    fake_gh.chmod(0o755)
    first_sha = "a" * 40
    second_sha = "b" * 40
    environment = os.environ | {
        "ACCORD_GHCR_USERNAME": "release-user",
        "ACCORD_GHCR_READ_TOKEN": "t" * 24,
        "FAKE_EVENT_LOG": str(event_log),
        "FAKE_REMOTE_LOCK": str(lock_file),
        "FAKE_BARRIER_DIR": str(barrier_dir),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }
    processes = [
        subprocess.Popen(
            [
                str(helper),
                "accord-host",
                sha,
                f"/tmp/accord-release-{sha}-1-1",
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for sha in (first_sha, second_sha)
    ]
    results = [process.communicate(timeout=10) for process in processes]
    assert sorted(process.returncode for process in processes) == [0, 1], results

    events = event_log.read_text().splitlines()
    first_positions = [index for index, event in enumerate(events) if first_sha in event]
    second_positions = [index for index, event in enumerate(events) if second_sha in event]
    assert sorted((len(first_positions), len(second_positions))) == [0, 4]


def test_backup_uses_the_running_non_default_database_identity(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    minio_data = tmp_path / "minio-data"
    backup_root = tmp_path / "backups"
    docker_log = tmp_path / "docker.log"
    fake_bin.mkdir()
    minio_data.mkdir()
    (minio_data / "object.bin").write_bytes(b"stored-object")
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$FAKE_DOCKER_LOG"\n'
        'if [ "$1" = ps ]; then printf "database-cid\\n"; exit 0; fi\n'
        'if [ "$1" = inspect ]; then\n'
        '  printf "POSTGRES_USER=custom_backup_user\\nPOSTGRES_DB=custom_backup_db\\n"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1 $2" = "exec -i" ]; then\n'
        '  case "$*" in\n'
        '    *pg_dump*) printf "custom-format-dump\\n" ;;\n'
        '    *pg_restore*) printf "1; 0 1 TABLE DATA public example custom_backup_user\\n" ;;\n'
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1 $2" = "volume inspect" ]; then printf "%s\\n" "$FAKE_MINIO_DATA"; exit 0; fi\n'
        "exit 1\n"
    )
    docker.chmod(0o755)
    sha = "c" * 40

    result = subprocess.run(
        ["bash", str(ROOT / "deploy/backup-before-migrate.sh"), sha],
        capture_output=True,
        check=False,
        env=os.environ
        | {
            "ACCORD_LIVE_DEPLOY_DIR": str(tmp_path / "live-deploy"),
            "ACCORD_RELEASE_BACKUP_DIR": str(backup_root),
            "FAKE_DOCKER_LOG": str(docker_log),
            "FAKE_MINIO_DATA": str(minio_data),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
        text=True,
    )

    assert result.returncode == 0, result.stderr
    evidence = Path(result.stdout.strip())
    assert evidence.is_file()
    assert evidence.with_suffix(evidence.suffix + ".minio.tar.gz").is_file()
    calls = docker_log.read_text()
    assert "pg_dump -U custom_backup_user -d custom_backup_db --format=custom" in calls
