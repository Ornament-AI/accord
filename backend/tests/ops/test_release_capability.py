"""The fixed release wrapper refuses bundles that predate prepared activation."""

from __future__ import annotations

import json
import re
import sys
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "deploy" / "deploy-accord-wrapper.sh"
CALL = 'require_release_capability "$EXTRACTED/deploy" \\\n'


def _wrapper() -> str:
    return WRAPPER.read_text(encoding="utf-8")


def _activate_candidate(extracted: Path) -> subprocess.CompletedProcess[str]:
    """Run the wrapper's own die(), capability block and refusal, then start the
    candidate's preparation exactly as prepare_candidate does."""
    wrapper = _wrapper()
    die = next(line for line in wrapper.splitlines() if line.startswith("die() "))
    block = wrapper.split("# BEGIN TESTABLE RELEASE CAPABILITY CHECK\n", 1)[1].split(
        "# END TESTABLE RELEASE CAPABILITY CHECK", 1
    )[0]
    start = wrapper.index("MANIFEST_SHA=")
    refusal = wrapper[start : wrapper.index("# Preserve the live environment only after")]
    refusal = refusal.replace("/usr/bin/python3", sys.executable)
    script = (
        f'set -euo pipefail\n{die}\n{block}\nEXTRACTED="$1"\n'
        f'SHA={"d" * 40}\nMANIFEST="$1/../manifest.json"\n{refusal}'
        'bash "$EXTRACTED/deploy/setup.sh" --prepare\n'
    )
    return subprocess.run(
        ["bash", "-c", script, "capability-test", str(extracted)],
        capture_output=True,
        text=True,
    )


def _bundle(tmp_path: Path) -> tuple[Path, Path]:
    extracted = tmp_path / "extracted"
    (extracted / "deploy").mkdir(parents=True)
    invocations = tmp_path / "setup-invocations"
    (tmp_path / "manifest.json").write_text(json.dumps({"source": {"commit_sha": "d" * 40}}))
    for name in ("release-source-sha", "release-tooling-source-sha", "release-rehearsed-from-sha"):
        (extracted / "deploy" / name).write_text("d" * 40 + "\n")
    baseline = extracted / "deploy/verify-release-baseline.py"
    baseline.write_text("raise SystemExit(99)\n")
    baseline.chmod(0o755)
    (extracted / "deploy/onprem_release.py").write_text(
        f"with open({str(invocations)!r}, 'a') as out: out.write('validator\\n')\n"
    )
    # Stands in for a pre-PR setup.sh, which ignores its arguments and runs
    # login, pull and `docker compose up -d` against the live project.
    (extracted / "deploy/setup.sh").write_text(f'printf "%s\\n" "$*" >> "{invocations}"\n')
    return extracted, invocations


def test_bundle_without_capability_marker_is_refused_before_setup_runs(tmp_path: Path):
    extracted, invocations = _bundle(tmp_path)

    result = _activate_candidate(extracted)

    assert result.returncode != 0
    assert "does not declare prepared-activation-v1" in result.stderr
    assert "was not run" in result.stderr
    assert not invocations.exists()


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"prepared-activation-v1",
        b"prepared-activation-v1\n\n",
        b"prepared-activation-v1\nextra\n",
        b" prepared-activation-v1\n",
        b"prepared-activation-v2\n",
    ],
)
def test_marker_must_have_exact_content(tmp_path: Path, content: bytes):
    extracted, invocations = _bundle(tmp_path)
    (extracted / "deploy/release-capabilities").write_bytes(content)

    result = _activate_candidate(extracted)

    assert result.returncode != 0
    assert "does not declare prepared-activation-v1" in result.stderr
    assert not invocations.exists()


def test_symlinked_or_directory_marker_is_refused(tmp_path: Path):
    for kind in ("symlink", "directory"):
        extracted, invocations = _bundle(tmp_path / kind)
        marker = extracted / "deploy/release-capabilities"
        if kind == "symlink":
            target = tmp_path / kind / "capabilities"
            target.write_bytes((ROOT / "deploy/release-capabilities").read_bytes())
            marker.symlink_to(target)
        else:
            marker.mkdir()

        result = _activate_candidate(extracted)

        assert result.returncode != 0, kind
        assert "does not declare prepared-activation-v1" in result.stderr, kind
        assert not invocations.exists(), kind


def test_bundle_with_the_committed_marker_reaches_preparation(tmp_path: Path):
    extracted, invocations = _bundle(tmp_path)
    (extracted / "deploy/release-capabilities").write_bytes(
        (ROOT / "deploy/release-capabilities").read_bytes()
    )

    result = _activate_candidate(extracted)

    assert result.returncode == 0, result.stderr
    assert invocations.read_text() == "validator\n--prepare\n"


def test_capability_check_precedes_every_bundle_script_and_both_paths():
    wrapper = _wrapper()
    check = wrapper.index(CALL)
    assert wrapper.count(CALL) == 1
    for checked in (
        "release signature verification failed",
        "checksum mismatch for {name}",
        "release validator does not match the reviewed source",
    ):
        assert wrapper.index(checked) < check
    assert check < wrapper.index('onprem_release.py" validate')
    executed = list(re.finditer(r'(?:bash|python3)\s+"\$EXTRACTED/deploy/([^"]+)"', wrapper))
    assert {match.group(1) for match in executed} >= {
        "onprem_release.py",
        "setup.sh",
        "verify-release-baseline.py",
        "backup-before-migrate.sh",
    }
    for match in executed:
        assert check < match.start(), match.group(1)
    for later in (
        'if [[ -f "$BOOTSTRAP_MARKER"',
        "    prepare_candidate\n",
        'docker stop "${APP_CONTAINER_IDS[@]}"',
        'bash "$LIVE_ROOT/deploy-accord.sh"',
    ):
        assert check < wrapper.index(later), later
