#!/usr/bin/env python3
"""Hold the remote release lock through the protected deployed-SHA receipt."""

from __future__ import annotations

import os
import re
import secrets
import shlex
import subprocess
import sys


def fail(message: str) -> int:
    print(f"run-release-with-receipt: {message}", file=sys.stderr)
    return 1


def main() -> int:
    if len(sys.argv) != 4:
        return fail("usage: run-release-with-receipt.py <ssh-target> <sha> <staged-root>")
    ssh_target, sha, staged_root = sys.argv[1:]
    if not re.fullmatch(r"(?:[A-Za-z0-9][A-Za-z0-9._-]*@)?[A-Za-z0-9][A-Za-z0-9._-]*", ssh_target):
        return fail("invalid SSH target")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return fail("invalid release SHA")
    if not re.fullmatch(rf"/tmp/accord-release-{sha}-[0-9]+-[0-9]+", staged_root):
        return fail("invalid staged release root")

    username = os.environ.get("ACCORD_GHCR_USERNAME", "")
    token = os.environ.get("ACCORD_GHCR_READ_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", username):
        return fail("invalid registry username")
    if not 20 <= len(token) <= 512 or "\n" in token or "\r" in token:
        return fail("invalid registry token")

    nonce = secrets.token_hex(32)
    remote_command = " ".join(
        shlex.quote(part)
        for part in (
            "sudo",
            "-n",
            "/usr/local/bin/deploy-accord",
            sha,
            staged_root,
            nonce,
        )
    )
    process = subprocess.Popen(
        ["ssh", ssh_target, remote_command],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdin is not None and process.stdout is not None
    marker = f"ACCORD_RELEASE_LIVE_PROOF={sha}:{nonce}"
    acknowledgement = f"ACCORD_RELEASE_RECEIPT={sha}:{nonce}"
    marker_seen = False
    try:
        process.stdin.write(f"{username}\n{token}\n")
        process.stdin.flush()
        for line in process.stdout:
            print(line, end="", flush=True)
            if line.rstrip("\n") != marker:
                continue
            if marker_seen:
                process.stdin.close()
                process.wait()
                return fail("remote wrapper emitted duplicate live-proof markers")
            marker_seen = True
            receipt_environment = os.environ.copy()
            receipt_environment.pop("ACCORD_GHCR_READ_TOKEN", None)
            receipt = subprocess.run(
                [
                    "gh",
                    "secret",
                    "set",
                    "ONPREM_DEPLOYED_SHA",
                    "--repo",
                    "Ornament-AI/accord",
                    "--env",
                    "onprem-release",
                ],
                input=sha,
                text=True,
                env=receipt_environment,
                check=False,
            )
            if receipt.returncode != 0:
                process.stdin.close()
                process.wait()
                return fail(
                    f"Accord is live at {sha}, but protected deployed-state evidence could not be updated"
                )
            process.stdin.write(f"{acknowledgement}\n")
            process.stdin.flush()
        process.stdin.close()
    except BrokenPipeError:
        pass

    return_code = process.wait()
    if return_code != 0:
        return fail(f"remote release wrapper exited with status {return_code}")
    if not marker_seen:
        return fail("remote release wrapper did not provide live-proof evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
