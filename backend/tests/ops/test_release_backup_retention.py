"""Retention and capacity contract of the fixed Accord release wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "deploy" / "deploy-accord-wrapper.sh"


def _run_retention(name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    wrapper = WRAPPER.read_text(encoding="utf-8")
    block = wrapper.split("# BEGIN TESTABLE RELEASE BACKUP RETENTION\n", 1)[1].split(
        "# END TESTABLE RELEASE BACKUP RETENTION", 1
    )[0]
    return subprocess.run(
        ["bash", "-c", f'{block}\n{name} "$@"', "retention-test", *arguments],
        capture_output=True,
        text=True,
    )


def _backup_set(root: Path, timestamp: str, *, completed: bool, archive_bytes: int = 1) -> Path:
    dump = root / f"accord-pre-migrate-{timestamp}-{'c' * 40}.dump"
    for path in (dump, Path(f"{dump}.list"), Path(f"{dump}.sha256")):
        path.write_bytes(b"evidence\n")
    with open(f"{dump}.minio.tar.gz", "wb") as archive:
        archive.truncate(archive_bytes)
    if completed:
        Path(f"{dump}.completed").write_text("completed\n", encoding="utf-8")
    return dump


def _set_files(root: Path, dump: Path) -> list[Path]:
    return [
        path
        for path in root.iterdir()
        if path.name == dump.name or path.name.startswith(f"{dump.name}.")
    ]


def test_successful_deploy_keeps_two_completed_backup_sets_and_failed_attempts_between(
    tmp_path: Path,
):
    root = tmp_path / "releases"
    root.mkdir()
    superseded = _backup_set(root, "20261001T000000Z", completed=True)
    legacy = _backup_set(root, "20260901T000000Z", completed=False)
    previous = _backup_set(root, "20261002T000000Z", completed=True)
    failed_attempt = _backup_set(root, "20261003T000000Z", completed=False)
    current = _backup_set(root, "20261004T000000Z", completed=False)
    unrelated = root / "routine-notes.txt"
    unrelated.write_text("keep\n", encoding="utf-8")
    outside = tmp_path / "outside.dump"
    outside.write_text("outside\n", encoding="utf-8")
    linked = root / f"accord-pre-migrate-20260801T000000Z-{'e' * 40}.dump"
    linked.symlink_to(outside)

    assert _run_retention("record_backup_completed", str(current)).returncode == 0
    result = _run_retention("prune_release_backups", str(root), str(current))

    assert result.returncode == 0, result.stderr
    assert not _set_files(root, superseded) and not _set_files(root, legacy)
    assert len(_set_files(root, previous)) == 5
    assert len(_set_files(root, failed_attempt)) == 4
    assert Path(f"{current}.completed").read_text(encoding="utf-8") == "completed 1\n"
    assert unrelated.is_file() and linked.is_symlink() and outside.is_file()


def test_backup_retention_keeps_everything_without_a_previous_completed_set(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    legacy = _backup_set(root, "20261001T000000Z", completed=False)
    current = _backup_set(root, "20261002T000000Z", completed=True)

    assert _run_retention("prune_release_backups", str(root), str(current)).returncode == 0
    assert len(_set_files(root, legacy)) == 4
    missing = root / f"accord-pre-migrate-20261009T000000Z-{'f' * 40}.dump"
    assert _run_retention("prune_release_backups", str(root), str(missing)).returncode != 0


def test_retention_removes_side_files_left_by_an_interrupted_prune(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    interrupted = _backup_set(root, "20261001T000000Z", completed=True)
    interrupted.unlink()
    previous = _backup_set(root, "20261002T000000Z", completed=True)
    current = _backup_set(root, "20261003T000000Z", completed=True)

    assert _run_retention("prune_release_backups", str(root), str(current)).returncode == 0
    assert not _set_files(root, interrupted)
    assert len(_set_files(root, previous)) == 5


def test_retention_orders_completed_sets_by_deployment_not_wall_clock(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    first = _backup_set(root, "20261001T100000Z", completed=False)
    after_clock_rollback = _backup_set(root, "20261001T090000Z", completed=False)
    current = _backup_set(root, "20261001T110000Z", completed=False)
    for dump in (first, after_clock_rollback, current):
        assert _run_retention("record_backup_completed", str(dump), ".minio.tar.gz").returncode == 0

    assert _run_retention("prune_release_backups", str(root), str(current)).returncode == 0

    assert not _set_files(root, first)
    assert Path(f"{after_clock_rollback}.completed").read_text(encoding="ascii") == "completed 2\n"
    assert Path(f"{current}.completed").read_text(encoding="ascii") == "completed 3\n"


def test_database_only_set_from_an_older_release_never_anchors_retention(tmp_path: Path):
    root = tmp_path / "releases"
    root.mkdir()
    with_files = _backup_set(root, "20261001T000000Z", completed=True)
    legacy_rollback = root / f"accord-pre-migrate-20261002T000000Z-{'d' * 40}.dump"
    legacy_rollback.write_bytes(b"database only\n")
    current = _backup_set(root, "20261003T000000Z", completed=False)

    refused = _run_retention("record_backup_completed", str(legacy_rollback), ".minio.tar.gz")
    assert refused.returncode != 0 and not Path(f"{legacy_rollback}.completed").exists()
    assert _run_retention("record_backup_completed", str(current), ".minio.tar.gz").returncode == 0
    assert _run_retention("prune_release_backups", str(root), str(current)).returncode == 0
    assert len(_set_files(root, with_files)) == 5 and legacy_rollback.is_file()


def test_backup_capacity_uses_live_files_and_newest_real_set(tmp_path: Path):
    uploads = tmp_path / "volumes/minio"
    restore_points = tmp_path / "volumes/minio-extra"
    (uploads / "bucket").mkdir(parents=True)
    restore_points.mkdir(parents=True)
    (uploads / "bucket/object").write_bytes(b"obj")
    root = tmp_path / "backups/releases"

    def capacity(*live: Path, database_bytes: int = 0) -> subprocess.CompletedProcess[str]:
        return _run_retention(
            "require_backup_capacity", str(root), str(database_bytes), *(str(path) for path in live)
        )

    assert capacity(uploads, restore_points).returncode == 0
    refused = capacity(uploads, restore_points, database_bytes=1 << 53)
    assert refused.returncode != 0 and "bytes free" in refused.stderr
    assert (
        _run_retention("require_backup_capacity", str(root), "unknown", str(uploads)).returncode
        != 0
    )
    assert capacity(uploads, tmp_path / "missing").returncode != 0
    with (restore_points / "large.bin").open("wb") as handle:
        handle.truncate(1 << 43)
    refused = capacity(uploads, restore_points)
    assert refused.returncode != 0 and "bytes free" in refused.stderr
    (restore_points / "large.bin").unlink()
    root.mkdir(parents=True)
    _backup_set(root, "20261001T000000Z", completed=True)
    (root / f"accord-pre-migrate-20261009T000000Z-{'e' * 40}.dump").symlink_to(tmp_path / "absent")
    assert capacity(uploads, restore_points).returncode == 0
    _backup_set(root, "20261002T000000Z", completed=True, archive_bytes=1 << 42)
    refused = capacity(uploads, restore_points)
    assert refused.returncode != 0 and "bytes free" in refused.stderr


def test_wrapper_checks_capacity_before_downtime_and_prunes_only_after_the_receipt():
    wrapper = WRAPPER.read_text(encoding="utf-8")
    capacity_call = wrapper.index(
        'require_backup_capacity /opt/accord/backups/releases "$DATABASE_BYTES" "$MINIO_DATA_ROOT"'
    )
    assert capacity_call < wrapper.index('docker stop "${APP_CONTAINER_IDS[@]}"')
    receipt = wrapper.index('|| die "protected deployed-state evidence acknowledgement is invalid"')
    failure = wrapper.index('if [[ -f "$MIGRATION_STATE_FILE" ]]; then\n    APP_QUIESCED=false')
    for call in (
        'record_backup_completed "$BACKUP_EVIDENCE" .minio.tar.gz',
        'prune_release_backups /opt/accord/backups/releases "$BACKUP_EVIDENCE"',
    ):
        assert wrapper.count(call) == 1
        assert receipt < wrapper.index(call) < failure
