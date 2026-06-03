"""Contract checks for kai-project-governance eval system."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


def result(status: str, detail: str = "") -> dict[str, str]:
    return {"status": status, "detail": detail}


def validate_claim_json(claim: dict) -> dict[str, str]:
    """Validate a workspace claim has all required fields and correct types."""
    required_fields = {
        "type": str,
        "action": str,
        "participantId": str,
        "project": str,
        "taskId": str,
        "claimedAt": str,
        "expiresAt": str,
        "gitHead": str,
    }

    for field, expected_type in required_fields.items():
        if field not in claim:
            return result("missing_field", f"Missing required field: {field}")
        if not isinstance(claim[field], expected_type):
            return result("wrong_type", f"Field {field} must be {expected_type.__name__}")

    if claim["type"] != "workspace_claim":
        return result("invalid_type", f"type must be 'workspace_claim', got '{claim['type']}'")

    if claim["action"] not in ("claim", "release", "renew"):
        return result("invalid_action", f"action must be claim/release/renew, got '{claim['action']}'")

    if claim["action"] == "claim":
        has_scope = (
            claim.get("files")
            or claim.get("directories")
            or claim.get("mayAffect")
        )
        if not has_scope:
            return result("no_scope", "Claim must have files, directories, or mayAffect")

    return result("valid")


def validate_claim_timestamps(claim: dict) -> dict[str, str]:
    """Validate claimedAt is before expiresAt and both parse as ISO 8601."""
    try:
        claimed = _parse_iso(claim["claimedAt"])
        expires = _parse_iso(claim["expiresAt"])
    except (ValueError, KeyError) as e:
        return result("invalid_timestamp", str(e))

    if claimed >= expires:
        return result("invalid_timestamp", "claimedAt must be before expiresAt")

    ttl_minutes = (expires - claimed).total_seconds() / 60
    if ttl_minutes < 5 or ttl_minutes > 120:
        return result("suspicious_ttl", f"TTL is {ttl_minutes:.0f} minutes (expected 5-120)")

    return result("valid")


def validate_path_normalized(path: str) -> dict[str, str]:
    """Validate a path is git-root-relative and normalized."""
    if path.startswith("/"):
        return result("absolute_path", f"Path must be relative, got: {path}")
    if path.startswith("./"):
        return result("dot_slash", f"Path must not start with './', got: {path}")
    if "\\" in path:
        return result("backslash", f"Path must use forward slashes, got: {path}")
    if path.endswith("/") and "/" in path[:-1]:
        # Directory paths should not have double slashes
        if "//" in path:
            return result("double_slash", f"Path has double slashes: {path}")
    return result("valid")


def validate_log_entry(entry: dict) -> dict[str, str]:
    """Validate a governance log entry."""
    required_fields = [
        "timestamp", "agentId", "project", "phase", "action",
        "files", "humanInLoop", "conflictDetected", "approvalStatus",
    ]

    for field in required_fields:
        if field not in entry:
            return result("missing_field", f"Log entry missing field: {field}")

    valid_phases = {"planning", "implementing", "destructive", "committing", "configuring", "verifying"}
    if entry["phase"] not in valid_phases:
        return result("invalid_phase", f"phase must be one of {valid_phases}, got '{entry['phase']}'")

    valid_statuses = {
        "approved", "skipped_human_in_loop_with_warning", "no_conflict",
        "DEGRADED_CONFLICT", "BROKER_DOWN_DEGRADED", "rejected",
    }
    if entry["approvalStatus"] not in valid_statuses:
        return result("invalid_status", f"approvalStatus must be one of {valid_statuses}, got '{entry['approvalStatus']}'")

    try:
        _parse_iso(entry["timestamp"])
    except ValueError as e:
        return result("invalid_timestamp", str(e))

    return result("valid")


def validate_severity_class(operation: str) -> dict[str, str]:
    """Validate an operation maps to a known severity class."""
    severity_map = {
        "critical": [
            "git push --force", "git reset --hard", "rm", "git rm",
            "git mv", "database migration", "lockfile change",
            "CI/CD change", ".env change", "branch delete",
        ],
        "high": [
            "git push", "git merge", "git rebase", "config edit",
            "dependency install", "dependency remove", "shared type change",
            "API contract change",
        ],
        "medium": [
            "edit source", "add file", "edit test", "edit docs",
        ],
        "low": [
            "read file", "run tests", "git log", "git diff",
            "search codebase", "build local",
        ],
    }

    for severity, operations in severity_map.items():
        for op in operations:
            if operation.lower() == op.lower() or operation.lower().startswith(op.lower()):
                return result("valid", severity)

    return result("unknown_operation", f"Operation '{operation}' not classified")


def find_conflicts(my_files: list[str], active_claims: list[dict]) -> list[dict]:
    """Find conflicts between my files and active claims."""
    conflicts = []
    for claim in active_claims:
        their_files = set(claim.get("files", []))
        their_dirs = set(claim.get("directories", []))
        their_may_affect = set(claim.get("mayAffect", []))

        all_theirs = their_files | their_may_affect

        # Check directory overlap
        for my_file in my_files:
            for their_dir in their_dirs:
                if my_file.startswith(their_dir.rstrip("/") + "/"):
                    all_theirs.add(my_file)

        overlap = set(my_files) & all_theirs
        if overlap:
            conflicts.append({
                "participantId": claim["participantId"],
                "overlapping_files": sorted(overlap),
                "taskId": claim["taskId"],
            })

    return conflicts


def _parse_iso(ts: str) -> datetime:
    """Parse ISO 8601 timestamp, handling various formats."""
    ts = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        # Try without timezone
        return datetime.fromisoformat(ts.replace("+00:00", "")).replace(tzinfo=timezone.utc)
