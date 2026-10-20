#!/usr/bin/env python3
"""Run one deployment phase with private, durable, secret-free timing metadata.

These records measure commands, not availability, and are not a recovery journal.
The caller owns the deployment lock, signature checks and operation ordering.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path

PHASES = (
    "artifact-verification", "image-preparation", "configuration-validation",
    "credential-preparation", "drain", "database-backup", "file-backup",
    "backup-verification", "migration", "application-readiness", "observation",
)
RECORD_FAILURE = 125


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_record(directory: Path, name: str, record: dict) -> None:
    # Exclusive creation also refuses symlinks and preserves previous evidence.
    fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.fchmod(fd, 0o600)  # Exact private mode, independent of the caller's umask.
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(record, output, sort_keys=True, separators=(",", ":"))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    sync_directory(directory)


def execute_command(command: list[str]) -> tuple[int, int | None]:
    """Forward cancellation to the command group and retain control until exit.

    No timeout/escalation: a child ignoring cancellation keeps the runner (and
    inherited lock descriptors) alive. The caller must wait for the runner too.
    SIGKILL cannot be handled and requires external journal/recovery fencing.
    """
    process = None
    cancellation = None

    def forward(signum, _frame):
        nonlocal cancellation
        if cancellation is None:
            cancellation = signum
        if process is not None and process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signum)

    previous = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[signum] = signal.signal(signum, forward)
        # Isolate the command group so a terminal signal is forwarded once and
        # descendants in that group receive cancellation as well.
        process = subprocess.Popen(command, start_new_session=True)
        if cancellation is not None:
            forward(cancellation, None)
        result = process.wait()
        return result, cancellation
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _begin_phase(directory: Path, attempt: str, phase: str) -> tuple[dict, int]:
    if str(uuid.UUID(attempt)) != attempt or phase not in PHASES:
        raise ValueError("invalid phase invocation")
    directory.mkdir(mode=0o700)  # Parent must exist; every invocation gets a new directory.
    directory.chmod(0o700)  # mkdir permissions otherwise depend on umask.
    sync_directory(directory.parent)
    started = time.monotonic_ns()
    identity = {"contract_version": 1, "attempt_id": attempt,
                "phase_id": str(uuid.uuid4()), "phase": phase}
    write_record(directory, "started.json", {
        **identity, "event": "started", "utc": utc_now(),
    })
    return identity, started


def _finish_phase(directory: Path, identity: dict, started: int, *, outcome: str,
                  exit_code: int | None = None, child_signal: int | None = None,
                  cancellation_signal: int | None = None, error_code: str | None = None) -> None:
    write_record(directory, "finished.json", {
        **identity, "event": "finished", "utc": utc_now(),
        "elapsed_ns": time.monotonic_ns() - started, "outcome": outcome,
        "cancellation_signal": cancellation_signal, "exit_code": exit_code,
        "signal": child_signal, "error_code": error_code,
    })


@contextmanager
def measure_phase(directory: Path, attempt: str, phase: str):
    """Time one in-process block; callers retain locks, signals and transaction control.

    The block starts only after durable start evidence. Normal exit means success;
    callers must raise for an unsuccessful or unknown operation result. Exceptions
    are re-raised; no messages, locals or values are serialized. Persistence errors
    propagate too, including after the block's operation already happened.
    """
    identity, started = _begin_phase(directory, attempt, phase)
    try:
        yield
    except BaseException as exc:
        interrupted = not isinstance(exc, Exception)
        _finish_phase(directory, identity, started,
                      outcome="cancelled" if interrupted else "failed",
                      error_code="phase_interrupted" if interrupted else "phase_exception")
        raise
    else:
        _finish_phase(directory, identity, started, outcome="success")


def run_phase(directory: Path, attempt: str, phase: str, command: list[str]) -> int:
    """Start only after the start record is synced; never turn a failed phase green."""
    if not command:
        raise ValueError("invalid phase invocation")
    identity, started = _begin_phase(directory, attempt, phase)
    error_code = None
    cancellation = None
    try:
        result, cancellation = execute_command(command)
    except OSError:
        # No argv, environment, stderr, exceptions or credential values in evidence.
        result, error_code = 126, "command_unavailable"
    _finish_phase(directory, identity, started,
                  outcome="cancelled" if cancellation is not None else ("success" if result == 0 else "failed"),
                  cancellation_signal=cancellation, exit_code=result if result >= 0 else None,
                  child_signal=-result if result < 0 else None, error_code=error_code)
    if cancellation is not None:
        return 128 + cancellation
    return result if result >= 0 else 128 - result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path,
                        help="new private phase directory under an existing trusted parent")
    parser.add_argument("--attempt", required=True, help="canonical UUID for this release attempt")
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        return run_phase(args.directory, args.attempt, args.phase, command)
    except (OSError, ValueError):
        print("phase-timing: evidence could not be persisted or invocation is invalid", file=sys.stderr)
        return RECORD_FAILURE
    except KeyboardInterrupt:
        # No fabricated completion: an interrupted wrapper leaves incomplete evidence.
        return 130


if __name__ == "__main__":
    sys.exit(main())
