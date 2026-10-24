"""Offline source/packaging checks; no Docker, database, network or credentials."""

import ast
import copy
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
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
import release_classification as classification  # noqa: E402 - pinned local vendor
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


OPERATOR_AUTH_MUTATIONS = {
    "scripts/provision_member.py": ("seed",),
    "scripts/provision_organization.py": ("seed",),
    "backend/scripts/create_roles.sql": ("startup",),
}

AUTH_MUTATIONS = (
    *OPERATOR_AUTH_MUTATIONS,
    "backend/app/api/deps.py",
    "backend/app/tenancy.py",
    "backend/app/db.py",
    "backend/app/services/identity.py",
    "backend/app/services/members.py",
    "backend/app/services/bootstrap.py",
    "backend/app/models/identity.py",
    "backend/app/models/base.py",
    "backend/app/middleware/csrf.py",
    "backend/app/main.py",
    "backend/app/services/run_workflow.py",
    "backend/app/jobs/worker.py",
    "backend/app/services/artifacts.py",
    "backend/app/api/routes/payroll_runs.py",
)


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

    def assessment(self, candidate, *, frontend_review=False):
        # Protocol-only fixture. These numbers are not deployment policy choices.
        digest = classification.fingerprint
        images = {name: digest(name) for name in self.evidence["components"]}
        runtime = {
            "components": {
                name: {
                    "config": digest("config"),
                    "secret_versions": {"database": "version:fixture"},
                }
                for name in images
            }
        }
        baseline = inputs.bind_runtime_inputs(self.evidence, images, runtime)
        target = inputs.bind_runtime_inputs(candidate, images, runtime)
        receipt = {
            "manifest_digest": digest(baseline),
            "status": "committed",
            "inventory": baseline["inventory"],
            "identities": {name: digest(name + "-instance") for name in images},
            "effect_state": {name: digest(name) for name in classification.EFFECTS},
            "singleton_owners": {
                name: effect["owner"]
                for name, effect in self.evidence["effects"].items()
                if effect["owner"] is not None
            },
            "committed_at": 800,
        }
        observation = {
            key: copy.deepcopy(receipt[key])
            for key in ("inventory", "identities", "effect_state", "singleton_owners")
        }
        observation.update(
            receipt_digest=digest(receipt), healthy=True, journal="resolved", observed_at=990
        )
        policy = {
            "repository": baseline["repository"],
            "approval": digest("synthetic-policy"),
            "max_backup_age_s": 100,
            "max_restore_age_s": 500,
            "max_observation_age_s": 20,
            "old_client_window_s": 200,
        }
        backup = {
            "repository": baseline["repository"],
            "policy_digest": digest(policy),
            "recovery_set": digest("pair"),
            "completed_at": 950,
            "readable": True,
            "restore_set": digest("restored-pair"),
            "restored_at": 700,
            "restore_passed": True,
            "evidence": digest("restore-evidence"),
        }
        review = None
        if frontend_review:
            review = {
                "baseline": digest(baseline),
                "candidate": digest(target),
                "evidence": digest("synthetic-review"),
                "checks": dict.fromkeys(classification.FRONTEND_CHECKS, True),
                "retained": {
                    name: images[name]
                    for name, item in self.evidence["components"].items()
                    if item["role"] != "web"
                },
                "asset_window_s": 200,
            }
        return classification.assess(
            {
                "baseline": baseline,
                "candidate": target,
                "receipt": receipt,
                "observation": observation,
                "policy": policy,
                "backup": backup,
                "frontend_review": review,
                "backend_review": None,
                "now": 1000,
            }
        )

    def test_publisher_and_vendor_support_python312_syntax(self):
        publisher = ROOT / "scripts/recovery"
        for path in sorted(publisher.rglob("*.py")):
            with self.subTest(path=str(path.relative_to(ROOT))):
                ast.parse(path.read_text(), filename=str(path), feature_version=(3, 12))

    def test_real_replacement_ref_cannot_substitute_published_source_bytes(self):
        # Keep replacement refs entirely inside a disposable local clone. The
        # clone reads existing objects but writes no refs into the source repo.
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--shared",
                    "--no-checkout",
                    "--quiet",
                    str(ROOT),
                    str(repository),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            def git(*arguments):
                return subprocess.check_output(
                    ["git", "-C", str(repository), *arguments], text=True
                ).strip()

            git("checkout", "--quiet", "--detach", self.source)
            declaration = repository / "deploy/release-inputs.json"
            nginx = repository / "deploy/nginx/nginx.conf"
            original_declaration = declaration.read_bytes()
            original_nginx = nginx.read_bytes()
            replacement = json.loads(original_declaration)
            replacement["schema"] = 999
            declaration.write_text(json.dumps(replacement))
            nginx.write_bytes(original_nginx + b"\n# substituted release source\n")
            git("add", "deploy/release-inputs.json", "deploy/nginx/nginx.conf")
            git(
                "-c",
                "user.name=Source Evidence Test",
                "-c",
                "user.email=evidence@example.invalid",
                "commit",
                "-qm",
                "replacement fixture",
            )
            substituted = git("rev-parse", "HEAD")
            git("checkout", "--quiet", "--detach", self.source)
            git("replace", self.source, substituted)
            self.assertEqual(
                json.loads(git("show", f"{self.source}:deploy/release-inputs.json"))["schema"], 999
            )
            environment = {
                "PATH": os.environ["PATH"],
                "SOURCE_SHA": self.source,
                "GITHUB_SHA": self.source,
                "GITHUB_RUN_ID": "12345",
            }
            app = "accord"
            for role in ("BACKEND", "WEB"):
                environment[f"{app.upper()}_{role}_DIGEST"] = (
                    "sha256:" + ("a" if role == "BACKEND" else "b") * 64
                )
            for role in ("BACKEND", "WEB", "DB"):
                environment[f"{app.upper()}_{role}_IMAGE_BYTES"] = "1024"
                environment[f"{app.upper()}_{role}_IMAGE_INODES"] = "1024"
            if app == "accord":
                environment["ACCORD_PREVIOUS_DEPLOYED_SHA"] = self.source
            output = Path(temporary) / "output"
            result = subprocess.run(
                ["bash", "deploy/package-release.sh", str(output)],
                cwd=repository,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            archive = next(output.glob("*sha-*.tar.gz"))
            with tarfile.open(archive) as bundle:
                self.assertEqual(
                    bundle.extractfile("deploy/release-inputs.json").read(), original_declaration
                )
                self.assertEqual(
                    bundle.extractfile("deploy/nginx/nginx.conf").read(), original_nginx
                )
                evidence = json.loads(bundle.extractfile("deploy/release-build-inputs.json").read())
                self.assertEqual(evidence["source"], self.source)
                self.assertFalse(evidence["activation_allowed"])

    def test_canonical_vendor_pin(self):
        vendor = ROOT / "scripts/recovery/vendor"
        pin = json.loads((vendor / "SOURCE.json").read_text())
        self.assertEqual(pin["repository"], "Ornament-AI/msidc-infra")
        self.assertEqual(pin["commit"], "4fe908d73ff7a5cc3336c2f21812809260967c5c")
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
        self.assertEqual(changed["roots"], self.evidence["roots"])
        self.assertEqual(changed["effects"], self.evidence["effects"])
        result = self.assessment(changed, frontend_review=True)
        self.assertEqual(result["classification"], "frontend-only", result)
        self.assertFalse(result["activation_allowed"])

    def test_auth_helpers_require_dedicated_infrastructure_plan(self):
        for path in AUTH_MUTATIONS:
            with self.subTest(path=path):
                changed = self.changed(path)
                self.assertNotEqual(changed["roots"]["auth"], self.evidence["roots"]["auth"])
                result = self.assessment(changed)
                self.assertEqual(result["classification"], "infrastructure", result)
                self.assertIn("dedicated_infrastructure_plan", result["required_controls"])
                self.assertFalse(result["activation_allowed"])

    def test_auth_local_import_closure_is_declared(self):
        paths = self.declaration["roots"]["auth"]
        selected = {
            path
            for path in self.inventory
            if any(
                path == prefix or (prefix.endswith("/") and path.startswith(prefix))
                for prefix in paths
            )
        }
        for path in sorted(selected):
            if not path.endswith(".py"):
                continue
            content = subprocess.check_output(["git", "show", f"{self.source}:{path}"], cwd=ROOT)
            modules = []
            for node in ast.walk(ast.parse(content)):
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level:
                        parent = path.removeprefix("backend/").removesuffix(".py").split("/")[:-1]
                        module = ".".join(
                            parent[: len(parent) - node.level + 1] + ([module] if module else [])
                        )
                    modules.append(module)
                    modules.extend(module + "." + alias.name for alias in node.names)
            for module in modules:
                if not module.startswith("app."):
                    continue
                parts = module.split(".")
                candidates = ["backend/" + module.replace(".", "/") + ".py"]
                candidates.extend(
                    "backend/" + "/".join(parts[:length]) + "/__init__.py"
                    for length in range(1, len(parts) + 1)
                )
                for dependency in candidates:
                    if dependency in self.inventory:
                        with self.subTest(source=path, dependency=dependency):
                            self.assertIn(dependency, selected)

    def test_committed_auth_and_backend_mutations_change_evidence(self):
        # Change real committed blob bytes in a disposable Git object database.
        # No application source, test fixture database or worktree is modified.
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            objects = subprocess.check_output(
                ["git", "rev-parse", "--path-format=absolute", "--git-path", "objects"],
                cwd=ROOT,
                text=True,
            ).strip()
            (repository / ".git/objects/info/alternates").write_text(objects + "\n")
            for path in AUTH_MUTATIONS + (
                "backend/app/domain/payroll/engine.py",
                "backend/app/future/nested/helper.py",
            ):
                with self.subTest(path=path):
                    subprocess.run(["git", "read-tree", self.source], cwd=repository, check=True)
                    content = (
                        subprocess.check_output(
                            ["git", "show", f"{self.source}:{path}"],
                            cwd=repository,
                        )
                        if path in self.inventory
                        else b""
                    ) + (
                        b"\n-- source-evidence mutation fixture\n"
                        if path.endswith(".sql")
                        else b"\n# source-evidence mutation fixture\n"
                    )
                    blob = (
                        subprocess.check_output(
                            ["git", "hash-object", "-w", "--stdin"],
                            input=content,
                            cwd=repository,
                        )
                        .decode()
                        .strip()
                    )
                    subprocess.run(
                        [
                            "git",
                            "update-index",
                            "--add",
                            "--cacheinfo",
                            f"{self.inventory.get(path, {'mode': '100644'})['mode']},{blob},{path}",
                        ],
                        cwd=repository,
                        check=True,
                    )
                    tree = (
                        subprocess.check_output(["git", "write-tree"], cwd=repository)
                        .decode()
                        .strip()
                    )
                    source = (
                        subprocess.check_output(
                            [
                                "git",
                                "-c",
                                "user.name=Synthetic fixture",
                                "-c",
                                "user.email=fixture@example.invalid",
                                "commit-tree",
                                tree,
                                "-p",
                                self.source,
                                "-m",
                                "Synthetic helper mutation",
                            ],
                            cwd=repository,
                        )
                        .decode()
                        .strip()
                    )
                    changed = inputs.build_source_manifest(repository, source, self.declaration)
                    effects = OPERATOR_AUTH_MUTATIONS.get(
                        path, ("writes", "api", "jobs", "recovery", "startup")
                    )
                    for name in effects:
                        self.assertNotEqual(
                            changed["effects"][name]["version"],
                            self.evidence["effects"][name]["version"],
                        )
                    self.assertFalse(changed["activation_allowed"])
                    if path in AUTH_MUTATIONS:
                        self.assertNotEqual(
                            changed["roots"]["auth"], self.evidence["roots"]["auth"]
                        )
                        result = self.assessment(changed)
                        self.assertEqual(result["classification"], "infrastructure", result)
                        self.assertIn("dedicated_infrastructure_plan", result["required_controls"])
                        self.assertFalse(result["activation_allowed"])

    def test_new_nested_backend_helper_is_semantically_covered(self):
        path = "backend/app/future/nested/helper.py"
        inventory = dict(
            self.inventory,
            **{
                path: {
                    "mode": "100644",
                    "sha256": hashlib.sha256(b"new helper").hexdigest(),
                    "size": 10,
                }
            },
        )
        changed = self.build(inventory)
        for name in ("writes", "api", "jobs", "recovery", "startup"):
            self.assertNotEqual(
                changed["effects"][name]["version"], self.evidence["effects"][name]["version"]
            )
        result = self.assessment(changed)
        self.assertEqual(result["classification"], "data-changing", result)
        self.assertFalse(result["activation_allowed"])

    def test_each_evidence_path_runs_backend_checks_on_pull_request(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        # This workflow deliberately uses a literal list of simple positive
        # glob filters; reject a shape change rather than silently misparse it.
        block = re.search(
            r"^            backend:\n((?:              - .+\n)+)", workflow, re.MULTILINE
        )
        self.assertIsNotNone(block)
        filters = [ast.literal_eval(line.split("- ", 1)[1]) for line in block.group(1).splitlines()]
        self.assertTrue(all(not pattern.startswith("!") for pattern in filters))
        backend = workflow.split("\n  backend:\n", 1)[1].split("\n  migrations:\n", 1)[0]
        self.assertIn("needs.detect.outputs.backend_changed == 'true'", backend)
        self.assertIn("github.event_name != 'pull_request'", backend)
        self.assertIn(
            "- name: Source input evidence\n        run: python scripts/tests/test_release_input_evidence.py",
            backend,
        )
        for path in (
            "scripts/recovery/build_release_inputs.py",
            "scripts/recovery/vendor/release_inputs.py",
            "scripts/tests/test_release_input_evidence.py",
            "scripts/provision_member.py",
            "scripts/provision_organization.py",
            "deploy/release-inputs.json",
            "deploy/package-release.sh",
        ):
            with self.subTest(event="pull_request", changed_paths=[path]):
                self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in filters))
        self.assertFalse(
            any(fnmatch.fnmatchcase("frontend/src/main.tsx", pattern) for pattern in filters)
        )

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
