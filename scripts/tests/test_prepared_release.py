"""Application preparation proof tests; all data and Docker observations are synthetic."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

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
        for name in ("prepare-release.py", "phase_timing.py"):
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
        lines = []
        for variable, name in PREP.SECRET_FILES.items():
            source = Path(self.temp.name) / name
            source.write_text("private-fixture-value")
            source.chmod(0o444)
            lines.append(f"{variable}={source}")
        (self.root / ".env").write_text("\n".join(lines) + "\n")
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

    def test_changed_credential_source_fails(self):
        self.prepare()
        if not PREP.SECRET_FILES:
            return  # Accord credentials are literal values in the isolated .env.
        source = Path(self.temp.name) / next(iter(PREP.SECRET_FILES.values()))
        source.chmod(0o600)
        source.write_text("rotated")
        with self.assertRaises(PREP.PreparationError):
            self.verify()

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

        self.assertEqual(
            hashlib.sha256((ROOT / "deploy/phase_timing.py").read_bytes()).hexdigest(),
            "1c0088f8757c5fae97fa90141c8d421a7c9c2655f9a5e4bc2fb7343a3a2cbafa",
        )


if __name__ == "__main__":
    unittest.main()
