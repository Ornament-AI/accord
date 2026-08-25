#!/usr/bin/env python3
"""Fail closed unless a release was rehearsed from the live Accord revision."""

from __future__ import annotations

import re
import sys

SHA_RE = re.compile(r"[0-9a-f]{40}")


def fail(message: str) -> int:
    print(f"verify-release-baseline: {message}", file=sys.stderr)
    return 1


def main() -> int:
    if len(sys.argv) != 4:
        return fail(
            "usage: verify-release-baseline.py "
            "<rehearsed-sha> <live-app-version> <live-release-sha-or-dash>"
        )
    rehearsed_sha, live_app_version, live_release_sha = sys.argv[1:]
    if SHA_RE.fullmatch(rehearsed_sha) is None:
        return fail("rehearsed SHA is invalid")
    if not live_app_version.startswith("sha-"):
        return fail("live APP_VERSION is not an immutable sha tag")
    app_sha = live_app_version.removeprefix("sha-")
    if SHA_RE.fullmatch(app_sha) is None:
        return fail("live APP_VERSION is not an immutable sha tag")
    if live_release_sha != "-" and SHA_RE.fullmatch(live_release_sha) is None:
        return fail("live release identity is invalid")
    if live_release_sha != "-" and live_release_sha != app_sha:
        return fail("live APP_VERSION and release identity disagree")
    if app_sha != rehearsed_sha:
        return fail(
            "release was rehearsed from a different deployed SHA; "
            "publish a new release from the current live baseline"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
