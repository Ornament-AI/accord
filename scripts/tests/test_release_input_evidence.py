"""Offline source/packaging checks; no Docker, database, network or credentials."""

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/recovery/vendor"))

import release_inputs as inputs  # noqa: E402 - load the pinned local vendor directory
from release_profiles import EvidenceError  # noqa: E402 - load the pinned local vendor directory

APP = "accord"
CONFIG = {
    "components": [
        "api",
        "migrations",
        "minio",
        "minio-init",
        "postgres",
        "role-sync",
        "web",
        "worker",
    ],
    "backend": ["api", "migrations", "worker"],
    "key": "backend/app/jobs/worker.py",
    "effect": ["jobs", "recovery"],
    "shared": "pnpm-workspace.yaml",
    "declaration": "deploy/release-inputs.json",
    "package": "deploy/package-release.sh",
}


class ReleaseInputEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = subprocess.check_output(
            [shutil.which("git"), "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        cls.declaration = json.loads((ROOT / CONFIG["declaration"]).read_text())
        cls.inventory = inputs.committed_inventory(ROOT, cls.source)
        cls.evidence = cls.build(cls.inventory)

    @classmethod
    def build(cls, inventory, declaration=None):
        with mock.patch.object(inputs, "committed_inventory", return_value=inventory):
            return inputs.build_source_manifest(ROOT, cls.source, declaration or cls.declaration)

    def changed(self, path):
        inventory = copy.deepcopy(self.inventory)
        inventory[path]["sha256"] = "f" * 64
        return self.build(inventory)

    def test_canonical_vendor_pin(self):
        vendor = ROOT / "scripts/recovery/vendor"
        pin = json.loads((vendor / "SOURCE.json").read_text())
        self.assertEqual(pin["repository"], "Ornament-AI/msidc-infra")
        self.assertEqual(pin["commit"], "9e2f12bfa3f602d352ee9af9ac2d65db93a47c16")
        for name, digest in pin["files"].items():
            self.assertEqual(hashlib.sha256((vendor / name).read_bytes()).hexdigest(), digest)

    def test_complete_topology_and_no_runtime_permission(self):
        self.assertEqual(set(self.evidence["components"]), set(CONFIG["components"]))
        self.assertFalse(self.evidence["activation_allowed"])
        self.assertNotIn("inventory", self.evidence)
        for component in self.evidence["components"].values():
            self.assertNotIn("config", component)
            self.assertNotIn("secret_versions", component)
            self.assertNotIn("image", component)
        images = dict.fromkeys(CONFIG["components"], "sha256:" + "a" * 64)
        with self.assertRaises(EvidenceError):
            inputs.bind_runtime_inputs(self.evidence, images, {})

    def test_docker_copy_dependencies_and_startup_effects(self):
        for name in CONFIG["backend"]:
            self.assertIn("backend/", self.declaration["components"][name]["inputs"])
        self.assertIn(CONFIG["shared"], self.declaration["components"]["web"]["inputs"])
        changed = self.changed(CONFIG["key"])
        for name in CONFIG["backend"]:
            self.assertNotEqual(changed["components"][name], self.evidence["components"][name])
        for name in CONFIG["effect"]:
            self.assertNotEqual(
                changed["effects"][name]["version"], self.evidence["effects"][name]["version"]
            )

    def test_frontend_change_does_not_hide_backend_dependencies(self):
        path = next(path for path in self.inventory if path.startswith("frontend/src/"))
        changed = self.changed(path)
        self.assertNotEqual(changed["components"]["web"], self.evidence["components"]["web"])
        for name in CONFIG["backend"]:
            self.assertEqual(changed["components"][name], self.evidence["components"][name])

    def test_unmapped_source_is_conservative_and_missing_input_rejected(self):
        inventory = dict(
            self.inventory,
            **{"new-runtime-entrypoint.py": {"mode": "100644", "sha256": "a" * 64, "size": 1}},
        )
        changed = self.build(inventory)
        self.assertIn("new-runtime-entrypoint.py", changed["unassigned"])
        self.assertNotEqual(
            changed["roots"]["shared_runtime"], self.evidence["roots"]["shared_runtime"]
        )
        declaration = copy.deepcopy(self.declaration)
        declaration["components"]["web"]["inputs"].append("missing-docker-copy-input")
        with self.assertRaises(EvidenceError):
            self.build(self.inventory, declaration)

    def test_cli_uses_committed_source_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "source.json"
            command = [
                sys.executable,
                str(ROOT / "scripts/recovery/build_release_inputs.py"),
                "--repository",
                str(ROOT),
                "--source",
                self.source,
                "--output",
                str(output),
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertFalse(json.loads(result.stdout)["activation_allowed"])
            self.assertEqual(json.loads(output.read_text()), self.evidence)
            before = output.read_bytes()
            self.assertEqual(
                subprocess.run(command, check=False, capture_output=True).returncode, 2
            )
            self.assertEqual(output.read_bytes(), before)

    def test_publisher_preserves_existing_contract(self):
        if APP == "plinth":
            spec = importlib.util.spec_from_file_location(
                "source_evidence_plinth_contract", ROOT / "scripts/release/contract.py"
            )
            sys.path.insert(0, str(ROOT / "scripts/release"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "bundle"
                module.package(
                    self.source,
                    "ghcr.io/ornament-ai/plinth-backend@sha256:" + "a" * 64,
                    "ghcr.io/ornament-ai/plinth-web@sha256:" + "b" * 64,
                    12345,
                    output,
                )
                manifest = json.loads((output / f"onprem-release-{self.source}.json").read_text())
                self.assertEqual(
                    {item["path"] for item in manifest["artifact"]["files"]}, {"deploy/compose.yml"}
                )
                self.assertFalse((output / "release-build-inputs.json").exists())
            return
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            environment = {
                "PATH": os.environ["PATH"],
                "SOURCE_SHA": self.source,
                "GITHUB_RUN_ID": "12345",
            }
            for role in ("BACKEND", "WEB"):
                environment[f"{APP.upper()}_{role}_DIGEST"] = (
                    "sha256:" + ("a" if role == "BACKEND" else "b") * 64
                )
            for role in ("BACKEND", "WEB", "DB"):
                environment[f"{APP.upper()}_{role}_IMAGE_BYTES"] = "1024"
                environment[f"{APP.upper()}_{role}_IMAGE_INODES"] = "1024"
            if APP == "accord":
                environment["ACCORD_PREVIOUS_DEPLOYED_SHA"] = self.source
            command = ["bash", CONFIG["package"], str(output)]
            if APP == "delta":
                environment.update(
                    {
                        "GHCR_OWNER": "ornament-ai",
                        "GITHUB_REPOSITORY": "Ornament-AI/delta",
                        "GITHUB_SHA": self.source,
                    }
                )
                for role in ("BACKEND", "WEB"):
                    record = output / f"{role.lower()}-provenance.json"
                    record.write_text(json.dumps(self.delta_record(role.lower())))
                    environment[f"DELTA_{role}_PROVENANCE"] = str(record)
                command = ["bash", CONFIG["package"], "sha-" + self.source, str(output)]
            subprocess.run(
                command, cwd=ROOT, env=environment, check=True, capture_output=True, text=True
            )
            manifest = json.loads((output / f"onprem-release-{self.source}.json").read_text())
            prefix = "" if APP == "delta" else "deploy/"
            names = {item["path"] for item in manifest["artifact"]["files"]}
            self.assertIn(prefix + "release-build-inputs.json", names)
            self.assertIn(prefix + "release-inputs.json", names)
            self.assertNotIn(prefix + "release-components.json", names)
            self.assertFalse(any("scripts/recovery" in name for name in names))
            archive = next(output.glob("*sha-*.tar.gz"))
            with tarfile.open(archive) as handle:
                member = next(
                    item
                    for item in handle.getmembers()
                    if item.name.removeprefix("./") == prefix + "release-build-inputs.json"
                )
                content = handle.extractfile(member).read()
                self.assertEqual(json.loads(content), self.evidence)
                entry = next(
                    item
                    for item in manifest["artifact"]["files"]
                    if item["path"] == prefix + "release-build-inputs.json"
                )
                self.assertEqual(entry["sha256"], hashlib.sha256(content).hexdigest())

    def delta_record(self, role):
        # Protocol fixture only, validated by the real existing packager. This
        # does not represent hosted CI or real BuildKit provenance evidence.
        digest = ("a" if role == "backend" else "b") * 64
        return {
            "workflow_ref": "Ornament-AI/delta/.github/workflows/deploy.yml@refs/heads/main",
            "statement": {
                "_type": "https://in-toto.io/Statement/v1",
                "subject": [
                    {"name": f"ghcr.io/ornament-ai/delta-{role}", "digest": {"sha256": digest}}
                ],
                "predicateType": "https://slsa.dev/provenance/v1",
                "predicate": {
                    "buildDefinition": {
                        "buildType": "https://github.com/moby/buildkit/blob/master/docs/attestations/slsa-definitions.md",
                        "externalParameters": {
                            "configSource": {
                                "uri": "https://github.com/Ornament-AI/delta.git#refs/heads/main",
                                "digest": {"sha1": self.source},
                                "path": "backend/Dockerfile"
                                if role == "backend"
                                else "deploy/onprem/Dockerfile.web",
                            }
                        },
                    },
                    "runDetails": {
                        "builder": {
                            "id": "https://github.com/Ornament-AI/delta/actions/runs/12345/attempts/1"
                        },
                        "metadata": {"buildkit_completeness": {"resolvedDependencies": True}},
                    },
                },
            },
        }


if __name__ == "__main__":
    unittest.main()
