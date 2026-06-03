"""Tests for claim protocol, conflict detection, and log validation."""

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))
from contract_checks import (
    validate_claim_json,
    validate_claim_timestamps,
    validate_path_normalized,
    validate_log_entry,
    validate_severity_class,
    find_conflicts,
)


# --- Claim JSON validation ---

def test_valid_claim_passes():
    claim = _make_claim()
    assert validate_claim_json(claim)["status"] == "valid"


def test_missing_required_field_fails():
    claim = _make_claim()
    del claim["participantId"]
    r = validate_claim_json(claim)
    assert r["status"] == "missing_field"
    assert "participantId" in r["detail"]


def test_wrong_type_fails():
    claim = _make_claim()
    claim["taskId"] = 12345  # should be string
    r = validate_claim_json(claim)
    assert r["status"] == "wrong_type"


def test_invalid_action_fails():
    claim = _make_claim()
    claim["action"] = "steal"
    r = validate_claim_json(claim)
    assert r["status"] == "invalid_action"


def test_claim_without_scope_fails():
    claim = _make_claim()
    claim.pop("files", None)
    claim.pop("directories", None)
    claim.pop("mayAffect", None)
    r = validate_claim_json(claim)
    assert r["status"] == "no_scope"


def test_release_action_does_not_need_scope():
    claim = _make_claim(action="release")
    claim.pop("files", None)
    claim.pop("directories", None)
    claim.pop("mayAffect", None)
    r = validate_claim_json(claim)
    assert r["status"] == "valid"


# --- Timestamp validation ---

def test_valid_timestamps_pass():
    claim = _make_claim()
    assert validate_claim_timestamps(claim)["status"] == "valid"


def test_expires_before_claimed_fails():
    claim = _make_claim()
    claim["claimedAt"] = "2026-06-03T10:30:00Z"
    claim["expiresAt"] = "2026-06-03T10:00:00Z"
    r = validate_claim_timestamps(claim)
    assert r["status"] == "invalid_timestamp"


def test_ttl_too_short_fails():
    claim = _make_claim()
    claim["claimedAt"] = "2026-06-03T10:00:00Z"
    claim["expiresAt"] = "2026-06-03T10:01:00Z"  # 1 minute TTL
    r = validate_claim_timestamps(claim)
    assert r["status"] == "suspicious_ttl"


def test_ttl_too_long_fails():
    claim = _make_claim()
    claim["claimedAt"] = "2026-06-03T10:00:00Z"
    claim["expiresAt"] = "2026-06-03T14:00:00Z"  # 4 hours
    r = validate_claim_timestamps(claim)
    assert r["status"] == "suspicious_ttl"


# --- Path normalization ---

def test_relative_path_passes():
    assert validate_path_normalized("src/main.py")["status"] == "valid"


def test_absolute_path_fails():
    assert validate_path_normalized("/Users/song/project/main.py")["status"] == "absolute_path"


def test_dot_slash_fails():
    assert validate_path_normalized("./src/main.py")["status"] == "dot_slash"


def test_backslash_fails():
    assert validate_path_normalized("src\\main.py")["status"] == "backslash"


def test_directory_with_trailing_slash_passes():
    assert validate_path_normalized("src/module/")["status"] == "valid"


# --- Log entry validation ---

def test_valid_log_entry_passes():
    entry = _make_log_entry()
    assert validate_log_entry(entry)["status"] == "valid"


def test_missing_log_field_fails():
    entry = _make_log_entry()
    del entry["phase"]
    r = validate_log_entry(entry)
    assert r["status"] == "missing_field"


def test_invalid_phase_fails():
    entry = _make_log_entry()
    entry["phase"] = "dancing"
    r = validate_log_entry(entry)
    assert r["status"] == "invalid_phase"


def test_invalid_approval_status_fails():
    entry = _make_log_entry()
    entry["approvalStatus"] = "whatever"
    r = validate_log_entry(entry)
    assert r["status"] == "invalid_status"


@pytest.mark.parametrize("status", [
    "approved",
    "skipped_human_in_loop_with_warning",
    "no_conflict",
    "DEGRADED_CONFLICT",
    "BROKER_DOWN_DEGRADED",
    "rejected",
])
def test_all_valid_approval_statuses(status):
    entry = _make_log_entry()
    entry["approvalStatus"] = status
    assert validate_log_entry(entry)["status"] == "valid"


@pytest.mark.parametrize("phase", [
    "planning", "implementing", "destructive",
    "committing", "configuring", "verifying",
])
def test_all_valid_phases(phase):
    entry = _make_log_entry()
    entry["phase"] = phase
    assert validate_log_entry(entry)["status"] == "valid"


# --- Severity classification ---

def test_critical_operations():
    for op in ["git push --force", "rm", "git rm", "database migration"]:
        r = validate_severity_class(op)
        assert r["status"] == "valid"
        assert r["detail"] == "critical"


def test_high_operations():
    for op in ["git push", "git merge", "dependency install"]:
        r = validate_severity_class(op)
        assert r["status"] == "valid"
        assert r["detail"] == "high"


def test_medium_operations():
    for op in ["edit source", "add file", "edit test"]:
        r = validate_severity_class(op)
        assert r["status"] == "valid"
        assert r["detail"] == "medium"


def test_low_operations():
    for op in ["read file", "run tests", "git log", "git diff"]:
        r = validate_severity_class(op)
        assert r["status"] == "valid"
        assert r["detail"] == "low"


def test_unknown_operation():
    r = validate_severity_class("deploy to mars")
    assert r["status"] == "unknown_operation"


# --- Conflict detection ---

def test_no_overlap_no_conflict():
    claims = [_make_claim(files=["src/a.py"])]
    conflicts = find_conflicts(["src/b.py"], claims)
    assert conflicts == []


def test_exact_file_overlap():
    claims = [_make_claim(participantId="other-agent", files=["src/a.py"])]
    conflicts = find_conflicts(["src/a.py"], claims)
    assert len(conflicts) == 1
    assert conflicts[0]["participantId"] == "other-agent"
    assert "src/a.py" in conflicts[0]["overlapping_files"]


def test_directory_overlap():
    claims = [_make_claim(participantId="other-agent", directories=["src/module/"])]
    conflicts = find_conflicts(["src/module/foo.py"], claims)
    assert len(conflicts) == 1


def test_may_affect_overlap():
    claims = [_make_claim(
        participantId="other-agent",
        files=["src/a.py"],
        may_affect=["src/shared/types.py"],
    )]
    conflicts = find_conflicts(["src/shared/types.py"], claims)
    assert len(conflicts) == 1


def test_no_self_conflict():
    """An agent's own claim should still show up — filtering is the caller's job."""
    claims = [_make_claim(participantId="me", files=["src/a.py"])]
    conflicts = find_conflicts(["src/a.py"], claims)
    assert len(conflicts) == 1  # detection finds it, caller filters


def test_multiple_conflicts():
    claims = [
        _make_claim(participantId="agent-a", files=["src/a.py"]),
        _make_claim(participantId="agent-b", files=["src/b.py", "src/c.py"]),
    ]
    conflicts = find_conflicts(["src/a.py", "src/c.py"], claims)
    assert len(conflicts) == 2


# --- Eval cases CSV integrity ---

def test_eval_cases_csv_loads():
    csv_path = ROOT / "evals" / "governance-cases.csv"
    with csv_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 3, "Should have at least 3 eval cases"
    for row in rows:
        assert row["case_id"], "Each case needs an ID"
        assert row["expected_behavior"], "Each case needs expected behavior"


# --- Helpers ---

def _make_claim(
    action="claim",
    participantId="test-agent",
    files=None,
    directories=None,
    may_affect=None,
):
    now = datetime.now(timezone.utc)
    return {
        "type": "workspace_claim",
        "action": action,
        "participantId": participantId,
        "project": "test-project",
        "files": files or ["src/main.py"],
        "directories": directories or [],
        "mayAffect": may_affect or [],
        "taskId": "task-1748960000",
        "claimedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresAt": (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gitHead": "abc123def456",
    }


def _make_log_entry(**overrides):
    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agentId": "test-agent",
        "project": "test-project",
        "phase": "implementing",
        "action": "edit",
        "files": ["src/main.py"],
        "humanInLoop": False,
        "conflictDetected": False,
        "approvalStatus": "no_conflict",
    }
    entry.update(overrides)
    return entry
