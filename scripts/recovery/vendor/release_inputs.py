"""Canonical source inputs for signed release evidence; never authorizes execution.

The app supplies a reviewed declaration. Read committed Git blobs, never the
working tree or environment. Unassigned tracked files enter the conservative
shared-runtime root rather than disappearing behind a frontend label.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from release_profiles import application_profile, fingerprint, require
from release_classification import EFFECTS, ROOTS, fields, manifest


def _git(repository, *arguments):
    result = subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, check=False)
    require(result.returncode == 0, "source_git_unavailable")
    return result.stdout


def _paths(value):
    require(type(value) is list and bool(value) and all(type(item) is str for item in value)
            and len(value) == len(set(value)), "invalid_input_paths")
    for name in value:
        require(type(name) is str and name and not name.startswith("/")
                and "\\" not in name and "\x00" not in name
                and all(part not in ("", ".", "..") for part in name.rstrip("/").split("/")), "invalid_input_path")
    return value


def committed_inventory(repository, source):
    require(type(source) is str and re.fullmatch(r"[0-9a-f]{40}", source), "invalid_source")
    require(_git(repository, "rev-parse", source + "^{commit}").decode().strip() == source, "source_commit_mismatch")
    inventory = {}
    for row in _git(repository, "ls-tree", "-rz", "--full-tree", source).split(b"\x00"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8", errors="strict")
        _paths([path])
        require(mode in {"100644", "100755"} and kind == "blob", "unsupported_source_entry")
        # Never read uncommitted files, symlink targets, environment or credentials.
        blob = _git(repository, "cat-file", "blob", oid)
        inventory[path] = {"mode": mode, "sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob)}
    require(bool(inventory), "empty_source_inventory")
    return inventory


def _select(inventory, paths):
    selected = {}
    for prefix in _paths(paths):
        matches = {name: item for name, item in inventory.items()
                   if name == prefix or (prefix.endswith("/") and name.startswith(prefix))}
        require(bool(matches), "declared_input_missing")
        selected.update(matches)
    return selected


def build_source_manifest(repository, source, declaration):
    fields(declaration, {"schema", "repository", "components", "roots", "effects"})
    require(type(declaration["schema"]) is int and declaration["schema"] == 1, "unsupported_input_schema")
    profile = application_profile(declaration["repository"])
    require(profile["assessment"] == "offline", "application_adapter_pending")
    fields(declaration["components"], profile["components"])
    fields(declaration["roots"], ROOTS)
    fields(declaration["effects"], EFFECTS)
    inventory = committed_inventory(repository, source)
    semantic_coverage = set()
    web_inputs, non_web_inputs, shared_inputs = set(), set(), set()
    components, roots, effects = {}, {}, {}
    for name, spec in declaration["components"].items():
        fields(spec, {"inputs", "shared_inputs"})
        inputs, shared = _select(inventory, spec["inputs"]), _select(inventory, spec["shared_inputs"])
        role = profile["components"][name]
        (web_inputs if role == "web" else non_web_inputs).update(inputs)
        shared_inputs.update(shared)
        components[name] = {"role": role, "build_inputs": fingerprint(inputs),
                            "shared_dependencies": fingerprint(shared)}
    for name, paths in declaration["roots"].items():
        selected = _select(inventory, paths)
        semantic_coverage.update(selected)
        roots[name] = selected
    for name, spec in declaration["effects"].items():
        fields(spec, {"inputs", "behavior", "runs_on_start", "owner"})
        require(spec["behavior"] in {"none", "read-only", "mutating"}
                and type(spec["runs_on_start"]) is bool, "unknown_effect")
        require((spec["behavior"] == "none" and spec["owner"] is None and not spec["runs_on_start"])
                or (spec["behavior"] != "none" and spec["owner"] in profile["components"]), "unknown_effect_owner")
        selected = _select(inventory, spec["inputs"])
        semantic_coverage.update(selected)
        effects[name] = {key: spec[key] for key in ("behavior", "runs_on_start", "owner")}
        effects[name]["version"] = fingerprint(selected)
    # A broad component build directory proves packaging coverage, not which
    # runtime roots/effects its helpers can change. Only root/effect declarations
    # provide semantic coverage. The sole exemption is declared web input that
    # no non-web component or shared dependency consumes; this preserves an
    # isolated frontend change without a filename heuristic. Any new backend or
    # shared helper omitted from semantic declarations changes shared_runtime.
    web_only = web_inputs - non_web_inputs - shared_inputs
    unassigned = {name: value for name, value in inventory.items()
                  if name not in semantic_coverage and name not in web_only}
    roots["shared_runtime"] = {"declared": roots["shared_runtime"], "unassigned": unassigned}
    return {"schema": 1, "repository": declaration["repository"], "source": source,
            "profile_digest": fingerprint(profile), "declaration_digest": fingerprint(declaration),
            "source_tree": fingerprint(inventory), "unassigned": sorted(unassigned),
            "components": components, "roots": {name: fingerprint(value) for name, value in roots.items()},
            "effects": effects, "activation_allowed": False}


def bind_runtime_inputs(source, images, runtime):
    """Complete a component manifest only with explicit runtime version bindings.

    Publishing callers must obtain runtime bindings from an approved source;
    this function validates structure, it does not manufacture that approval.
    """
    fields(runtime, {"components"})
    fields(images, source["components"])
    fields(runtime["components"], source["components"])
    components = {}
    for name, build in source["components"].items():
        binding = runtime["components"][name]
        fields(binding, {"config", "secret_versions"})
        components[name] = dict(build, image=images[name], **binding)
    document = {"schema": 1, "repository": source["repository"], "source": source["source"],
                "profile_digest": source["profile_digest"],
                "inventory": dict(source["roots"], components=components, effects=source["effects"])}
    manifest(document, application_profile(document["repository"]))
    return document
