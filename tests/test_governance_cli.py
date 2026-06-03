"""Integration tests for scripts/governance.py CLI."""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "governance.py"


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary git repo with governance initialized."""
    # Init git repo
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    # Set agent ID
    os.environ["GOVERNANCE_AGENT_ID"] = "test-agent-001"
    yield tmp_path
    os.environ.pop("GOVERNANCE_AGENT_ID", None)


def _gov(workspace, *args):
    """Run governance.py in a workspace."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        cwd=workspace,
        capture_output=True,
        text=True,
        env={**os.environ, "GOVERNANCE_AGENT_ID": "test-agent-001"},
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}\nstdout: {result.stdout}"
    return json.loads(result.stdout)


def _gov_agent(workspace, agent_id, *args):
    """Run governance.py as a specific agent."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        cwd=workspace,
        capture_output=True,
        text=True,
        env={**os.environ, "GOVERNANCE_AGENT_ID": agent_id},
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}\nstdout: {result.stdout}"
    return json.loads(result.stdout)


# --- Claim lifecycle ---

def test_claim_creates_file(workspace):
    r = _gov(workspace, "claim", "--files", "src/main.py")
    assert r["status"] == "claimed"
    claim = r["claim"]
    assert claim["participantId"] == "test-agent-001"
    assert "src/main.py" in claim["files"]
    assert (workspace / ".governance-claims" / "test-agent-001.json").exists()


def test_claim_normalizes_paths(workspace):
    r = _gov(workspace, "claim", "--files", "./src/main.py", "--dirs", "src/module/")
    claim = r["claim"]
    assert "./" not in str(claim["files"])
    assert "src/main.py" in claim["files"]


def test_release_removes_file(workspace):
    _gov(workspace, "claim", "--files", "src/main.py")
    assert (workspace / ".governance-claims" / "test-agent-001.json").exists()

    r = _gov(workspace, "release")
    assert r["status"] == "released"
    assert not (workspace / ".governance-claims" / "test-agent-001.json").exists()


def test_release_no_claim(workspace):
    r = _gov(workspace, "release")
    assert r["status"] == "no_claim"


def test_renew_updates_expiry(workspace):
    r1 = _gov(workspace, "claim", "--files", "src/main.py", "--ttl", "15")
    old_expires = r1["claim"]["expiresAt"]

    # Wait a moment so timestamps differ
    time.sleep(1)
    r2 = _gov(workspace, "renew", "--ttl", "30")
    assert r2["status"] == "renewed"
    assert r2["expiresAt"] >= old_expires


def test_expand_adds_files(workspace):
    _gov(workspace, "claim", "--files", "src/a.py")
    r = _gov(workspace, "expand", "--files", "src/b.py", "--may-affect", "src/types.py")
    assert r["status"] == "expanded"
    assert "src/a.py" in r["files"]
    assert "src/b.py" in r["files"]
    assert "src/types.py" in r["mayAffect"]


def test_cleanup_removes_expired(workspace):
    # Write an already-expired claim file directly
    claims_dir = workspace / ".governance-claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    claim = {
        "type": "workspace_claim", "action": "claim",
        "participantId": "test-agent-001", "project": "test",
        "files": ["src/main.py"], "directories": [], "mayAffect": [],
        "taskId": "task-expired", "claimedAt": expired,
        "expiresAt": expired, "gitHead": "abc",
    }
    (claims_dir / "test-agent-001.json").write_text(json.dumps(claim))

    r = _gov(workspace, "cleanup")
    assert r["status"] == "cleaned"
    assert r["removed"] >= 1


def test_cleanup_keeps_active(workspace):
    _gov(workspace, "claim", "--files", "src/main.py", "--ttl", "30")
    r = _gov(workspace, "cleanup")
    assert r["removed"] == 0


# --- Conflict detection ---

def test_check_no_conflict(workspace):
    _gov(workspace, "claim", "--files", "src/a.py")
    r = _gov(workspace, "check", "--files", "src/b.py")
    assert r["hasConflict"] is False
    assert r["conflicts"] == []


def test_check_file_conflict(workspace):
    _gov(workspace, "claim", "--files", "src/a.py")

    r = _gov_agent(workspace, "other-agent", "check", "--files", "src/a.py")
    assert r["hasConflict"] is True
    assert len(r["conflicts"]) == 1
    assert r["conflicts"][0]["participantId"] == "test-agent-001"


def test_check_directory_conflict(workspace):
    _gov(workspace, "claim", "--dirs", "src/module/")

    r = _gov_agent(workspace, "other-agent", "check", "--files", "src/module/foo.py")
    assert r["hasConflict"] is True


def test_check_may_affect_conflict(workspace):
    _gov(workspace, "claim", "--files", "src/a.py", "--may-affect", "src/shared.py")

    r = _gov_agent(workspace, "other-agent", "check", "--files", "src/shared.py")
    assert r["hasConflict"] is True


def test_check_no_self_conflict(workspace):
    _gov(workspace, "claim", "--files", "src/a.py")
    r = _gov(workspace, "check", "--files", "src/a.py")
    assert r["hasConflict"] is False


# --- Logging ---

def test_log_creates_entry(workspace):
    _gov(workspace, "log",
         "--phase", "implementing",
         "--action", "edit source",
         "--files", "src/main.py",
         "--status", "no_conflict")

    log_file = workspace / ".governance-log" / "test-agent-001.jsonl"
    assert log_file.exists()
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["phase"] == "implementing"
    assert entry["approvalStatus"] == "no_conflict"
    assert "src/main.py" in entry["files"]


def test_log_appends_multiple(workspace):
    _gov(workspace, "log", "--phase", "implementing", "--action", "a", "--status", "no_conflict")
    _gov(workspace, "log", "--phase", "committing", "--action", "b", "--status", "approved")

    log_file = workspace / ".governance-log" / "test-agent-001.jsonl"
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 2


# --- Status ---

def test_status_shows_claim(workspace):
    _gov(workspace, "claim", "--files", "src/main.py")
    r = _gov(workspace, "status")
    assert r["hasActiveClaim"] is True
    assert r["agentId"] == "test-agent-001"


def test_status_no_claim(workspace):
    r = _gov(workspace, "status")
    assert r["hasActiveClaim"] is False


# --- Agent ID stability ---

def test_agent_id_consistent_across_calls(workspace):
    os.environ["GOVERNANCE_AGENT_ID"] = "stable-agent-999"
    r1 = _gov_agent(workspace, "stable-agent-999", "status")
    r2 = _gov_agent(workspace, "stable-agent-999", "status")
    assert r1["agentId"] == r2["agentId"] == "stable-agent-999"


# --- Race condition scenario ---

def test_two_agents_claim_same_file(workspace):
    """Both agents claim the same file. Conflict detected on check."""
    _gov_agent(workspace, "agent-a", "claim", "--files", "src/main.py")
    _gov_agent(workspace, "agent-b", "claim", "--files", "src/main.py")

    r = _gov_agent(workspace, "agent-b", "check", "--files", "src/main.py")
    assert r["hasConflict"] is True
    assert any(c["participantId"] == "agent-a" for c in r["conflicts"])


def test_released_claim_no_conflict(workspace):
    """After agent-a releases, agent-b sees no conflict."""
    _gov_agent(workspace, "agent-a", "claim", "--files", "src/main.py")
    _gov_agent(workspace, "agent-a", "release")

    r = _gov_agent(workspace, "agent-b", "check", "--files", "src/main.py")
    assert r["hasConflict"] is False
