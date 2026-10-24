"""Emit committed source evidence only; this command never authorizes activation."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).with_name("vendor")))

from release_inputs import build_source_manifest  # noqa: E402 - load the pinned local vendor directory
from release_profiles import EvidenceError, require  # noqa: E402 - load the pinned local vendor directory

DECLARATION = "deploy/release-inputs.json"
REPOSITORY = "Ornament-AI/accord"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        require(re.fullmatch(r"[0-9a-f]{40}", args.source), "invalid_source")
        # The declaration and every input come from the same immutable commit.
        result = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-C",
                str(args.repository),
                "show",
                f"{args.source}:{DECLARATION}",
            ],
            capture_output=True,
            check=False,
        )
        require(result.returncode == 0, "committed_declaration_unavailable")
        require(len(result.stdout) <= 2_000_000, "oversized_evidence")

        def pairs(items):
            value = {}
            for key, item in items:
                require(key not in value, "duplicate_json_key")
                value[key] = item
            return value

        declaration = json.loads(result.stdout.decode("utf-8"), object_pairs_hook=pairs)
        require(declaration["repository"] == REPOSITORY, "repository_mismatch")
        evidence = build_source_manifest(args.repository, args.source, declaration)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(evidence, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        print(
            json.dumps(
                {
                    "source": args.source,
                    "component_manifest_complete": False,
                    "activation_allowed": False,
                }
            )
        )
        return 0
    except (EvidenceError, OSError, ValueError, KeyError, TypeError, UnicodeError):
        print("release source evidence could not be completed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
