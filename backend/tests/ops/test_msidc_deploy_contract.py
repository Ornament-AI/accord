"""Regression checks for the shared-host MSIDC deployment contract."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _write_fake_docker(fake_bin: Path, docker_log: Path) -> None:
    (fake_bin / "docker").write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$FAKE_DOCKER_LOG"\n'
        'if [ "$1 $2" = "compose version" ]; then exit 0; fi\n'
        'if [ "$1 $2" = "volume inspect" ]; then\n'
        '  case "$3" in\n'
        "    deploy_pgdata|deploy_minio-data)\n"
        '      if [ "${FAKE_LEGACY_VOLUMES:-true}" = true ]; then exit 0; fi\n'
        "      ;;\n"
        "  esac\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )
    (fake_bin / "docker").chmod(0o755)


def _valid_env_lines() -> list[str]:
    return [
        f"ACCORD_TAG=sha-{'a' * 40}",
        "ACCORD_WEB_PORT=8085",
        "ENVIRONMENT=production",
        "DEV_AUTH_BYPASS=false",
        "ACCORD_DB_PASSWORD=strong-db-password",
        "WORKOS_CLIENT_ID=client_test",
        "WORKOS_API_KEY=sk_test",
        "WORKOS_WEBHOOK_SECRET=whsec_test",
        "SESSION_SECRET_KEY=session-secret-$with-(safe)-metacharacters;",
        "OBJECT_STORAGE_ACCESS_KEY=accord-storage",
        "OBJECT_STORAGE_SECRET_KEY=strong-storage-secret",
        "PUBLIC_APP_URL=https://accord.innovastra.app",
        "BASE_URL=https://accord.innovastra.app",
        "CORS_ORIGINS=https://accord.innovastra.app",
        "WORKOS_REDIRECT_URI=https://accord.innovastra.app/api/auth/callback",
    ]


def _setup_environment(fake_bin: Path, docker_log: Path) -> dict[str, str]:
    return {
        "ACCORD_RELEASE_GHCR_USERNAME": "accord-release-operator",
        "ACCORD_RELEASE_GHCR_TOKEN": "x" * 40,
        "FAKE_DOCKER_LOG": str(docker_log),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }


def test_compose_is_isolated_and_does_not_publish_minio() -> None:
    compose = (ROOT / "deploy/docker-compose.yml").read_text()

    assert "name: accord" in compose
    assert "127.0.0.1:${ACCORD_WEB_PORT:-8085}:80" in compose
    assert '"9000:9000"' not in compose
    assert '"9001:9001"' not in compose
    minio_service = compose.split("  minio:\n", 1)[1].split("\n  minio-init:\n", 1)[0]
    assert "mem_limit: 512m" in minio_service


def test_setup_requires_immutable_images_and_production_auth() -> None:
    setup = (ROOT / "deploy/setup.sh").read_text()

    assert "^sha-[0-9a-f]{40}$" in setup
    assert '[[ "${ENVIRONMENT:-}" == "production" ]]' in setup
    assert '[[ "${DEV_AUTH_BYPASS:-}" == "false" ]]' in setup
    assert "up -d --no-build" in setup
    assert "WORKOS_REDIRECT_URI" in setup
    assert "org.opencontainers.image.revision" in setup
    assert "trap diagnose_failure EXIT" in setup
    assert "guard_persistent_volume_ownership" in setup
    assert "contains unsafe shell metacharacters" not in setup
    assert "for _ in $(seq 1 15)" in setup
    assert '$WORKER_READY || die "Worker startup proof is missing"' in setup
    assert "unsupported variable $key" in setup
    for dangerous in ("PATH", "LD_PRELOAD", "BASH_ENV", "DOCKER_HOST", "DOCKER_CONFIG"):
        assert f"|{dangerous}|" not in setup


def test_deploy_bundle_never_uploads_the_host_env() -> None:
    deploy = (ROOT / "scripts/deploy.sh").read_text()
    stage = (ROOT / "scripts/stage-accord-release.sh").read_text()
    receipt = (ROOT / "scripts/run-release-with-receipt.py").read_text()

    assert 'gh release download "onprem-sha-$SHA"' in stage
    assert "onprem-signature-$SHA.sig" in stage
    assert "release signature verification failed" in stage
    assert "deploy/.env" not in stage
    assert 'python3 "$RECEIPT_CLIENT"' in deploy
    assert '"/usr/local/bin/deploy-accord"' in receipt
    assert "ls-remote --exit-code origin refs/heads/main" in deploy


def test_provisioning_scripts_can_import_the_container_app() -> None:
    provision = (ROOT / "deploy/provision.sh").read_text()

    assert provision.count("-e PYTHONPATH=/app") == 2
    assert provision.count('-v "$ROOT/scripts:/provision/scripts:ro"') == 2


def test_setup_reports_missing_public_url_before_docker_mutation(tmp_path: Path) -> None:
    deploy_dir = tmp_path / "deploy"
    fake_bin = tmp_path / "bin"
    deploy_dir.mkdir()
    fake_bin.mkdir()
    (deploy_dir / "setup.sh").write_text((ROOT / "deploy/setup.sh").read_text())
    docker_log = tmp_path / "docker.log"
    _write_fake_docker(fake_bin, docker_log)
    (deploy_dir / ".env").write_text(
        "\n".join(line for line in _valid_env_lines() if not line.startswith("PUBLIC_APP_URL="))
    )

    result = subprocess.run(
        ["bash", str(deploy_dir / "setup.sh")],
        capture_output=True,
        check=False,
        env=_setup_environment(fake_bin, docker_log)
        | {
            "FAKE_LEGACY_VOLUMES": "false",
        },
        text=True,
    )

    assert result.returncode == 1
    assert "Missing required variables: PUBLIC_APP_URL" in result.stderr
    docker_calls = docker_log.read_text()
    assert "compose pull" not in docker_calls
    assert "compose up" not in docker_calls


def test_setup_accepts_default_web_port_when_env_omits_it(tmp_path: Path) -> None:
    deploy_dir = tmp_path / "deploy"
    fake_bin = tmp_path / "bin"
    docker_log = tmp_path / "docker.log"
    deploy_dir.mkdir()
    fake_bin.mkdir()
    (deploy_dir / "setup.sh").write_text((ROOT / "deploy/setup.sh").read_text())
    _write_fake_docker(fake_bin, docker_log)
    (deploy_dir / ".env").write_text(
        "\n".join(line for line in _valid_env_lines() if not line.startswith("ACCORD_WEB_PORT="))
    )

    result = subprocess.run(
        ["bash", str(deploy_dir / "setup.sh")],
        capture_output=True,
        check=False,
        env=_setup_environment(fake_bin, docker_log)
        | {
            "FAKE_LEGACY_VOLUMES": "false",
        },
        text=True,
    )

    assert "ACCORD_WEB_PORT" not in result.stderr
    assert "compose --env-file .env pull --quiet" in docker_log.read_text()


def test_fresh_install_without_legacy_volumes_reaches_image_pull(tmp_path: Path) -> None:
    deploy_dir = tmp_path / "deploy"
    fake_bin = tmp_path / "bin"
    docker_log = tmp_path / "docker.log"
    deploy_dir.mkdir()
    fake_bin.mkdir()
    (deploy_dir / "setup.sh").write_text((ROOT / "deploy/setup.sh").read_text())
    _write_fake_docker(fake_bin, docker_log)
    (deploy_dir / ".env").write_text("\n".join(_valid_env_lines()))

    result = subprocess.run(
        ["bash", str(deploy_dir / "setup.sh")],
        capture_output=True,
        check=False,
        env=_setup_environment(fake_bin, docker_log)
        | {
            "FAKE_LEGACY_VOLUMES": "false",
        },
        text=True,
    )

    assert result.returncode == 1
    assert "compose --env-file .env pull --quiet" in docker_log.read_text()


@pytest.mark.parametrize(
    ("persisted_value", "invocation_value"), [("false", "true"), ("true", "false")]
)
def test_legacy_volume_bypass_is_obsolete(
    tmp_path: Path,
    persisted_value: str,
    invocation_value: str,
) -> None:
    deploy_dir = tmp_path / "deploy"
    fake_bin = tmp_path / "bin"
    docker_log = tmp_path / "docker.log"
    deploy_dir.mkdir()
    fake_bin.mkdir()
    (deploy_dir / "setup.sh").write_text((ROOT / "deploy/setup.sh").read_text())
    _write_fake_docker(fake_bin, docker_log)
    (deploy_dir / ".env").write_text(
        "\n".join([*_valid_env_lines(), f"ACCORD_CONFIRMED_FRESH_INSTALL={persisted_value}"])
    )

    result = subprocess.run(
        ["bash", str(deploy_dir / "setup.sh")],
        capture_output=True,
        check=False,
        env=_setup_environment(fake_bin, docker_log)
        | {
            "ACCORD_CONFIRMED_FRESH_INSTALL": invocation_value,
        },
        text=True,
    )

    assert result.returncode == 1
    docker_calls = docker_log.read_text()
    assert "compose --env-file .env pull --quiet" not in docker_calls
    assert "Legacy deploy_* volumes exist" in result.stderr


def test_persisted_registry_credentials_are_ignored(tmp_path: Path) -> None:
    deploy_dir = tmp_path / "deploy"
    fake_bin = tmp_path / "bin"
    docker_log = tmp_path / "docker.log"
    deploy_dir.mkdir()
    fake_bin.mkdir()
    (deploy_dir / "setup.sh").write_text((ROOT / "deploy/setup.sh").read_text())
    _write_fake_docker(fake_bin, docker_log)
    (deploy_dir / ".env").write_text(
        "\n".join(
            [
                *_valid_env_lines(),
                "GHCR_TOKEN=persisted-legacy-token",
                "ACCORD_RELEASE_GHCR_TOKEN=persisted-release-token",
            ]
        )
    )

    result = subprocess.run(
        ["bash", str(deploy_dir / "setup.sh")],
        capture_output=True,
        check=False,
        env=_setup_environment(fake_bin, docker_log) | {"FAKE_LEGACY_VOLUMES": "false"},
        text=True,
    )

    assert result.returncode == 1
    assert "Ignoring registry credential GHCR_TOKEN" in result.stdout
    assert "Ignoring registry credential ACCORD_RELEASE_GHCR_TOKEN" in result.stdout
    assert "compose --env-file .env pull --quiet" in docker_log.read_text()


def test_process_control_environment_is_rejected_before_docker_mutation(tmp_path: Path) -> None:
    deploy_dir = tmp_path / "deploy"
    fake_bin = tmp_path / "bin"
    docker_log = tmp_path / "docker.log"
    deploy_dir.mkdir()
    fake_bin.mkdir()
    (deploy_dir / "setup.sh").write_text((ROOT / "deploy/setup.sh").read_text())
    _write_fake_docker(fake_bin, docker_log)
    (deploy_dir / ".env").write_text(
        "\n".join([*_valid_env_lines(), "DOCKER_HOST=tcp://attacker:2375"])
    )

    result = subprocess.run(
        ["bash", str(deploy_dir / "setup.sh")],
        capture_output=True,
        check=False,
        env=_setup_environment(fake_bin, docker_log),
        text=True,
    )

    assert result.returncode == 1
    assert "unsupported variable DOCKER_HOST" in result.stderr
    calls = docker_log.read_text()
    assert "login ghcr.io" not in calls
    assert "compose --env-file" not in calls
