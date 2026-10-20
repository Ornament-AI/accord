"""Application preparation proof tests; all data and Docker observations are synthetic."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("preparation", ROOT / "deploy/prepare-release.py")
PREP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREP)
REFERENCE = "docker.io/library/python@sha256:" + "b" * 64
IMAGE = "sha256:" + "c" * 64


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "deploy"
        self.root.mkdir()
        self.calls = []
        self.present = True
        self.image = IMAGE
        self.env = patch.dict(
            os.environ,
            {
                "RELEASE_PREPARATION_ATTEMPT": str(uuid.uuid4()),
                "RELEASE_PREPARATION_EVIDENCE": str(Path(self.temp.name) / "evidence"),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        Path(os.environ["RELEASE_PREPARATION_EVIDENCE"]).mkdir(mode=0o700)
        self.boot = patch.object(
            PREP,
            "proof_context",
            side_effect=lambda _: (os.environ["RELEASE_PREPARATION_ATTEMPT"], "test-boot"),
        )
        self.boot.start()
        self.addCleanup(self.boot.stop)
        for name in ("prepare-release.py", "phase_timing.py", ".env.example"):
            shutil.copyfile(ROOT / "deploy" / name, self.root / name)
        shutil.copyfile(ROOT / "scripts/vendor/onprem_release.py", self.root / "onprem_release.py")
        (self.root / "docker-compose.yml").write_text(
            "services:\n"
            + "".join(f"  {name}:\n    image: {REFERENCE}\n" for name in sorted(PREP.SERVICES))
        )
        validator = PREP.validator(self.root)
        path = Path(self.temp.name) / "manifest.json"
        validator.build_manifest(
            SimpleNamespace(
                adapter=ROOT / "deploy/onprem-release-adapter.json",
                bundle_root=Path(self.temp.name),
                commit_sha="a" * 40,
                workflow_run_id=1,
                output=path,
            )
        )
        shutil.copyfile(path, self.root / "release-manifest.json")
        (self.root / ".env").write_text("SESSION_SECRET_KEY=private-fixture-value\n")
        PREP.stage(self.root)
        self.config = {"services": {name: {"image": REFERENCE} for name in PREP.SERVICES}}
        self.docker = patch.object(PREP, "docker_output", side_effect=self.output)
        self.docker.start()
        self.addCleanup(self.docker.stop)

    def output(self, root, command):
        self.calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            PREP.require(self.present, "missing image")
            return json.dumps(
                [{"Id": self.image, "RepoDigests": [REFERENCE.replace("docker.io/library/", "")]}]
            )
        if command[:2] == ["docker", "pull"]:
            self.present = True
            return ""
        if command[:2] == ["docker", "compose"]:
            return json.dumps(self.config)
        raise AssertionError(command)

    def prepare(self):
        PREP.prepare_or_verify(self.root, True)

    def verify(self):
        PREP.prepare_or_verify(self.root, False)

    def test_cache_hit_never_pulls_and_proof_contains_no_secret_material(self):
        self.prepare()
        self.verify()
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in self.calls))
        evidence = (self.root / PREP.PROOF).read_text()
        self.assertNotIn("private-fixture-value", evidence)
        self.assertIn(IMAGE, evidence)

    def test_prepare_pulls_missing_digest_but_verification_cannot(self):
        self.present = False
        self.prepare()
        self.assertEqual(
            [c for c in self.calls if c[:2] == ["docker", "pull"]], [["docker", "pull", REFERENCE]]
        )
        self.calls.clear()
        self.present = False
        with self.assertRaises(PREP.PreparationError):
            self.verify()
        self.assertFalse(any(c[:2] == ["docker", "pull"] for c in self.calls))

    def test_missing_image_and_registry_failure_cannot_write_proof(self):
        self.present = False
        with patch.object(PREP, "docker_output", side_effect=PREP.PreparationError("offline")):
            with self.assertRaises(PREP.PreparationError):
                self.prepare()
        self.assertFalse((self.root / PREP.PROOF).exists())

    def test_changed_environment_fails(self):
        self.prepare()
        with (self.root / ".env").open("a") as stream:
            stream.write("UNTRACKED=changed\n")
        with self.assertRaises(PREP.PreparationError):
            self.verify()

    def test_changed_signed_file_fails(self):
        self.prepare()
        with (self.root / "docker-compose.yml").open("a") as stream:
            stream.write("# changed\n")
        with self.assertRaises(PREP.PreparationError):
            self.verify()

    def test_untracked_compose_override_fails(self):
        (self.root / "compose.override.yaml").write_text("services: {}\n")
        with self.assertRaises(PREP.PreparationError):
            self.prepare()

    def test_changed_attempt_and_image_identity_fail(self):
        self.prepare()
        self.image = "sha256:" + "d" * 64
        with self.assertRaises(PREP.PreparationError):
            self.verify()
        self.image = IMAGE
        with patch.dict(os.environ, {"RELEASE_PREPARATION_ATTEMPT": str(uuid.uuid4())}):
            with self.assertRaises(PREP.PreparationError):
                self.verify()

    def test_changed_boot_identity_fails(self):
        self.prepare()
        with patch.object(
            PREP,
            "proof_context",
            return_value=(os.environ["RELEASE_PREPARATION_ATTEMPT"], "different-boot"),
        ):
            with self.assertRaises(PREP.PreparationError):
                self.verify()

    def test_untracked_empty_directory_fails(self):
        (self.root / "untracked-config").mkdir()
        with self.assertRaises(PREP.PreparationError):
            self.prepare()

    def test_directory_promotion_keeps_file_identity_proof_valid(self):
        self.prepare()
        promoted = self.root.parent / "promoted"
        self.root.rename(promoted)
        self.root = promoted
        self.verify()

    def test_external_bind_and_extra_service_are_rejected(self):
        name = sorted(PREP.SERVICES)[0]
        self.config["services"][name]["volumes"] = [
            {"type": "bind", "source": str(self.root / "../outside"), "read_only": True}
        ]
        with self.assertRaises(PREP.PreparationError):
            self.prepare()

    def test_rotated_environment_credential_invalidates_proof(self):
        self.prepare()
        (self.root / ".env").write_text("SESSION_SECRET_KEY=rotated\n")
        with self.assertRaises(PREP.PreparationError):
            self.verify()

    def test_all_installer_keys_are_accepted(self):
        spec = importlib.util.spec_from_file_location(
            "env_validator", ROOT / "deploy/validate-deploy-env.py"
        )
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        shutil.copyfile(ROOT / "deploy/docker-compose.yml", self.root / "docker-compose.yml")
        (self.root / ".env").write_text("\n".join(f"{key}=fixture" for key in validator.ALLOWED))
        self.assertEqual(set(PREP.environment_file(self.root)), validator.ALLOWED)

    def test_external_secrets_and_configs_are_rejected(self):
        for section in ("secrets", "configs"):
            with self.subTest(section=section):
                self.config[section] = {"unknown": {"file": "/outside/secret"}}
                with self.assertRaises(PREP.PreparationError):
                    self.prepare()
                del self.config[section]
                shutil.rmtree(Path(os.environ["RELEASE_PREPARATION_EVIDENCE"]) / "configuration")

    def test_credential_copy_artifacts_are_not_accepted(self):
        (self.root / ".prepared-secrets").mkdir()
        with self.assertRaises(PREP.PreparationError):
            self.prepare()

    def test_timing_failure_before_start_cannot_write_proof_or_pull(self):
        Path(os.environ["RELEASE_PREPARATION_EVIDENCE"], "configuration").mkdir()
        with self.assertRaises((OSError, ValueError)):
            self.prepare()
        self.assertFalse(self.calls)
        self.assertFalse((self.root / PREP.PROOF).exists())

    def test_timing_failure_after_image_preparation_cannot_write_proof(self):
        from contextlib import contextmanager

        real_phase = PREP.phase

        @contextmanager
        def fail_finish(root, directory, name):
            with real_phase(root, directory, name):
                yield
            if directory == "images":
                raise OSError("test completion evidence failure")

        with patch.object(PREP, "phase", side_effect=fail_finish):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertFalse((self.root / PREP.PROOF).exists())
        self.assertTrue(any(c[:3] == ["docker", "image", "inspect"] for c in self.calls))

    def test_process_overrides_are_rejected(self):
        for key in ("DOCKER_HOST", "COMPOSE_FILE", "BASH_ENV", "RELEASE_PREPARATION_ATTEMPT"):
            with self.subTest(key=key):
                (self.root / ".env").write_text(f"{key}=untracked\n")
                with self.assertRaises(PREP.PreparationError):
                    PREP.docker_environment(self.root)

    def test_timing_vendor_provenance(self):
        import hashlib

        pin = "dd113b9e1448b504e709daa55f8a1db63fc80f9d4b0391c13c4c97a874e67fc9"
        self.assertEqual(
            hashlib.sha256((ROOT / "deploy/phase_timing.py").read_bytes()).hexdigest(), pin
        )
        source = dict(
            line.split("=", 1)
            for line in (ROOT / "deploy/PHASE_TIMING_SOURCE").read_text().splitlines()
        )
        self.assertEqual(source["sha256"], pin)
        self.assertEqual(source["commit"], "86fb618d9687f604b780234ae6f02254a65edbff")


if __name__ == "__main__":
    unittest.main()
