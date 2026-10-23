"""Offline release assessment. This module cannot authorize or execute a deploy.

Version 1 is a separate experimental contract, not a change to release.json v2.
Inputs describe evidence; authenticating/collecting that evidence is deliberately
not implemented here. Even a successful assessment always denies activation.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


from release_profiles import EvidenceError, application_profile, fingerprint, require


DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
VERSION = re.compile(r"version:[A-Za-z0-9_.-]{1,128}\Z")
ROLES = {"web", "backend", "worker", "migration", "database", "infrastructure"}
EFFECTS = {"migration", "seed", "recovery", "startup", "jobs", "file_layout", "writes", "api"}
ROOTS = {"deployment", "proxy", "shared_runtime", "storage", "auth", "shared_dependencies"}
FRONTEND_CHECKS = {"api", "proxy", "config", "auth", "old_assets", "lazy_chunks", "long_requests"}
BACKEND_CHECKS = {"old_reads_new_writes", "new_reads_old_writes", "exclusive_startup", "single_job_owner"}
PRODUCTION_GATES = [
    "authenticated_signed_manifests_and_exact_publication_ci",
    "durable_successful_receipt_and_fresh_locked_runtime_observation",
    "approved_policy_and_authenticated_backup_restore_evidence",
    "reviewed_application_adapter_and_failure_rehearsals",
    "separate_production_activation_authorization",
]


def fields(value, expected):
    require(type(value) is dict and set(value) == set(expected), "unknown_or_missing_fields")


def digest(value):
    require(type(value) is str and DIGEST.fullmatch(value), "invalid_digest")


def identifier(value):
    require(type(value) is str and NAME.fullmatch(value), "invalid_identifier")


def positive(value):
    require(type(value) is int and value > 0, "invalid_positive_integer")


def reference_map(value, pattern, *, empty=False):
    require(type(value) is dict and (empty or bool(value)), "incomplete_inventory")
    for key, item in value.items():
        identifier(key)
        require(type(item) is str and pattern.fullmatch(item), "invalid_inventory_reference")


def manifest(value, profile):
    fields(value, {"schema", "repository", "source", "profile_digest", "inventory"})
    require(type(value["schema"]) is int and value["schema"] == 1, "unsupported_schema")
    require(type(value["repository"]) is str and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"]), "invalid_repository")
    require(type(value["source"]) is str and re.fullmatch(r"[0-9a-f]{40}", value["source"]), "invalid_source")
    require(value["profile_digest"] == fingerprint(profile), "profile_binding_mismatch")
    inv = value["inventory"]
    fields(inv, ROOTS | {"components", "effects"})
    for root in ROOTS:
        digest(inv[root])
    components = inv["components"]
    require(type(components) is dict and bool(components), "incomplete_components")
    require(set(components) == set(profile["components"]), "profile_component_inventory_mismatch")
    for name, component in components.items():
        identifier(name)
        fields(component, {"role", "image", "build_inputs", "shared_dependencies", "config", "secret_versions"})
        require(component["role"] in ROLES, "unknown_component_role")
        require(component["role"] == profile["components"][name], "profile_role_mismatch")
        for key in ("image", "build_inputs", "shared_dependencies", "config"):
            digest(component[key])
        reference_map(component["secret_versions"], VERSION, empty=True)
    fields(inv["effects"], EFFECTS)
    for effect in inv["effects"].values():
        fields(effect, {"version", "behavior", "runs_on_start", "owner"})
        digest(effect["version"])
        require(effect["behavior"] in ("none", "read-only", "mutating"), "unknown_effect")
        require(type(effect["runs_on_start"]) is bool, "unknown_startup_behavior")
        if effect["behavior"] == "none":
            require(effect["owner"] is None and not effect["runs_on_start"], "inconsistent_absent_effect")
        else:
            require(type(effect["owner"]) is str and effect["owner"] in components, "unknown_effect_owner")
    return inv


def age(now, timestamp, maximum, code):
    require(type(timestamp) is int and 0 <= timestamp <= now and now - timestamp <= maximum, code)


def policy_and_backup(policy, backup, now, repository):
    fields(policy, {"repository", "approval", "max_backup_age_s", "max_restore_age_s", "max_observation_age_s", "old_client_window_s"})
    require(policy["repository"] == repository, "policy_repository_mismatch")
    digest(policy["approval"])
    for key in ("max_backup_age_s", "max_restore_age_s", "max_observation_age_s", "old_client_window_s"):
        positive(policy[key])
    fields(backup, {"repository", "policy_digest", "recovery_set", "completed_at", "readable", "restore_set", "restored_at", "restore_passed", "evidence"})
    require(backup["repository"] == repository and backup["policy_digest"] == fingerprint(policy), "backup_policy_mismatch")
    for key in ("recovery_set", "restore_set", "evidence"):
        digest(backup[key])
    require(backup["readable"] is True and backup["restore_passed"] is True, "unhealthy_backup")
    age(now, backup["completed_at"], policy["max_backup_age_s"], "stale_backup")
    age(now, backup["restored_at"], policy["max_restore_age_s"], "stale_restore")


def review(value, baseline, candidate, checks):
    fields(value, {"baseline", "candidate", "evidence", "checks", "retained", "asset_window_s"})
    require(value["baseline"] == fingerprint(baseline) and value["candidate"] == fingerprint(candidate), "review_binding_mismatch")
    digest(value["evidence"])
    fields(value["checks"], checks)
    require(all(item is True for item in value["checks"].values()), "compatibility_unproved")
    reference_map(value["retained"], DIGEST, empty=True)
    require(type(value["asset_window_s"]) is int and value["asset_window_s"] >= 0, "invalid_asset_window")


def assess(evidence):
    """Return a deterministic, inert assessment; unknown evidence always aborts.

    Time is an explicit input for replay. A future authenticated caller must supply
    its own clock and observations, never a timestamp from an untrusted manifest.
    """
    result = {"mode": "offline-assessment", "activation_allowed": False,
              "classification": "abort", "required_controls": [], "changes": [],
              "prerequisites": PRODUCTION_GATES.copy()}
    try:
        fields(evidence, {"baseline", "candidate", "receipt", "observation", "policy", "backup", "frontend_review", "backend_review", "now"})
        positive(evidence["now"])
        base, candidate = evidence["baseline"], evidence["candidate"]
        require(type(base) is dict and "repository" in base, "missing_successful_baseline")
        profile = application_profile(base["repository"])
        require(profile["assessment"] == "offline", "application_adapter_pending")
        old, new = manifest(base, profile), manifest(candidate, profile)
        require(base["repository"] == candidate["repository"], "repository_mismatch")
        receipt, observed = evidence["receipt"], evidence["observation"]
        fields(receipt, {"manifest_digest", "status", "inventory", "identities", "effect_state", "singleton_owners", "committed_at"})
        require(receipt["status"] == "committed" and receipt["manifest_digest"] == fingerprint(base), "missing_successful_baseline")
        require(receipt["inventory"] == old, "baseline_runtime_mismatch")
        reference_map(receipt["identities"], DIGEST)
        require(set(receipt["identities"]) == set(old["components"]), "incomplete_runtime_identities")
        reference_map(receipt["effect_state"], DIGEST)
        require(set(receipt["effect_state"]) == EFFECTS, "incomplete_effect_state")
        expected_owners = {key: val["owner"] for key, val in old["effects"].items() if val["owner"] is not None}
        require(receipt["singleton_owners"] == expected_owners, "singleton_owner_mismatch")
        fields(observed, {"receipt_digest", "inventory", "identities", "effect_state", "singleton_owners", "healthy", "journal", "observed_at"})
        require(observed["receipt_digest"] == fingerprint(receipt), "observation_receipt_mismatch")
        require(all(observed[key] == receipt[key] for key in ("inventory", "identities", "effect_state", "singleton_owners")), "runtime_drift")
        require(observed["healthy"] is True and observed["journal"] == "resolved", "unhealthy_or_unresolved_runtime")
        policy_and_backup(evidence["policy"], evidence["backup"], evidence["now"], base["repository"])
        age(evidence["now"], observed["observed_at"], evidence["policy"]["max_observation_age_s"], "stale_observation")
        age(observed["observed_at"], receipt["committed_at"], evidence["now"], "invalid_commit_time")
        # Reviews are optional only when irrelevant; malformed supplied evidence
        # is never silently ignored, including on the no-op path.
        for key, checks in (("frontend_review", FRONTEND_CHECKS), ("backend_review", BACKEND_CHECKS)):
            if evidence[key] is not None:
                review(evidence[key], base, candidate, checks)
        if old == new:
            result.update(classification="no-op", required_controls=["zero_stop_create_or_job_calls"])
            return result

        changed_roots = {key for key in ROOTS if old[key] != new[key]}
        changed_effects = {key for key in EFFECTS if old["effects"][key] != new["effects"][key]}
        names = set(old["components"]) | set(new["components"])
        changed_components = {name for name in names if old["components"].get(name) != new["components"].get(name)}
        result["changes"] = sorted(changed_roots | {"effect:" + x for x in changed_effects} | {"component:" + x for x in changed_components})
        infrastructure = bool(changed_roots - {"shared_dependencies"})
        backend = False
        for name in changed_components:
            before, after = old["components"].get(name), new["components"].get(name)
            if before is None or after is None or before["role"] != after["role"]:
                infrastructure = True
                backend = True
                continue
            infrastructure |= any(before[key] != after[key] for key in ("config", "secret_versions"))
            infrastructure |= after["role"] in {"database", "infrastructure"}
            backend |= after["role"] != "web"

        # No changed shared input/effect/config may disappear behind a web label.
        frontend = not infrastructure and not backend and not changed_roots and not changed_effects
        if frontend:
            # An unchanged effect still runs when its owning web component is
            # replaced. Compatibility review cannot waive data/startup work.
            require(not any(
                effect["runs_on_start"] and effect["owner"] in changed_components
                and (effect["behavior"] == "mutating" or name in {"migration", "seed", "recovery", "jobs"})
                for name, effect in new["effects"].items()
            ), "frontend_startup_not_separated")
            proof = evidence["frontend_review"]
            require(proof is not None, "frontend_review_required")
            retained = {name: value["image"] for name, value in old["components"].items() if value["role"] != "web"}
            require(proof["retained"] == retained, "retained_components_not_explicit")
            require(proof["asset_window_s"] >= evidence["policy"]["old_client_window_s"], "insufficient_asset_window")
            result.update(classification="frontend-only", required_controls=[
                "replace_web_only", "retain_backend_database_and_storage_identities",
                "skip_migration_seed_recovery_and_jobs", "preserve_old_assets_and_drain_requests",
                "require_scheduled_backup_and_restore_health",
            ])
            return result

        data_change = bool(changed_effects or "shared_dependencies" in changed_roots)
        mutating_start = any(x["runs_on_start"] and x["behavior"] == "mutating" for x in new["effects"].values())
        data_change |= backend and (mutating_start or evidence["backend_review"] is None)
        controls = {"exclusive_startup", "fresh_matched_db_and_files", "fence_all_writers", "durable_journal"}
        if data_change:
            controls.update({"single_migration_owner", "uncertain_migration_lockout", "never_restore_after_new_writes"})
        if infrastructure:
            controls.add("dedicated_infrastructure_plan")
        result.update(classification="infrastructure" if infrastructure else "data-changing" if data_change else "backend-runtime-compatible", required_controls=sorted(controls))
        return result
    except (EvidenceError, TypeError, KeyError, ValueError) as exc:
        result["reason"] = str(exc) if isinstance(exc, EvidenceError) else "malformed_evidence"
        return result


def load(path):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate_json_key")
            value[key] = item
        return value
    require(path.stat().st_size <= 2_000_000, "oversized_evidence")
    return json.loads(path.read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(EvidenceError("invalid_json_number")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        result = assess(load(args.evidence))
    except (OSError, ValueError, RecursionError):
        result = {"mode": "offline-assessment", "activation_allowed": False, "classification": "abort", "reason": "unreadable_evidence"}
    print(json.dumps(result, sort_keys=True))
    return 2 if result["classification"] == "abort" else 0


if __name__ == "__main__":
    raise SystemExit(main())
