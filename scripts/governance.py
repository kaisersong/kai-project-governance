#!/usr/bin/env python3
"""kai-project-governance CLI — deterministic workspace claim and conflict management."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLAIMS_DIR = ".governance-claims"
LOG_DIR = ".governance-log"
DEFAULT_TTL_MINUTES = 30
RENEWAL_INTERVAL_MINUTES = 10
OBSERVATION_WINDOW_SECONDS = 5


def _repo_root() -> Path:
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(root)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: not inside a git repository", file=sys.stderr)
        sys.exit(1)


def _agent_id() -> str:
    """Stable agent identity for this session. Priority:
    1. GOVERNANCE_AGENT_ID env var (explicit override)
    2. INTENT_BROKER_PARTICIPANT_ID env var (broker-assigned)
    3. hostname + session file fallback
    """
    explicit = os.environ.get("GOVERNANCE_AGENT_ID")
    if explicit:
        return explicit

    broker_id = os.environ.get("INTENT_BROKER_PARTICIPANT_ID")
    if broker_id:
        return broker_id

    import socket
    session_file = Path.home() / ".governance-session-id"
    if session_file.exists():
        return session_file.read_text().strip()

    session_id = f"{socket.gethostname()}-{int(time.time())}"
    session_file.write_text(session_id)
    return session_id


def _normalize_path(path: str, repo_root: Path) -> str:
    """Normalize a path to be relative to repo root."""
    p = Path(path)
    if p.is_absolute():
        try:
            return str(p.relative_to(repo_root))
        except ValueError:
            print(f"WARNING: path {path} is outside repo root", file=sys.stderr)
            return str(p)
    return str(p).lstrip("./")


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def _send_to_pm(summary: str, task_id: str | None = None, thread_id: str | None = None) -> dict:
    """Send a message to PM via broker HTTP API. Returns delivery result dict."""
    BROKER_URL = os.environ.get("BROKER_URL", "http://127.0.0.1:4318")
    PM_PARTICIPANT_ID = os.environ.get(
        "GOVERNANCE_PM_ID", "qodercli-session-f782cff3"
    )

    payload = {
        "kind": "reply_message",
        "fromParticipantId": _agent_id(),
        "taskId": task_id,
        "threadId": thread_id,
        "to": {"mode": "participant", "participants": [PM_PARTICIPANT_ID]},
        "payload": {"body": {"summary": summary}},
    }

    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{BROKER_URL}/intents",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=10,
        )
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return {"deliveredCount": 0, "error": "broker_unreachable"}


def _project_name(repo_root: Path) -> str:
    return repo_root.name


def _claims_path(repo_root: Path) -> Path:
    return repo_root / CLAIMS_DIR


def _log_path(repo_root: Path) -> Path:
    return repo_root / LOG_DIR


def _read_active_claims(claims_dir: Path) -> list[dict]:
    """Read all non-expired claims from the claims directory."""
    now = datetime.now(timezone.utc)
    claims = []
    if not claims_dir.exists():
        return claims
    for f in claims_dir.glob("*.json"):
        try:
            claim = json.loads(f.read_text(encoding="utf-8"))
            expires = datetime.fromisoformat(claim["expiresAt"].replace("Z", "+00:00"))
            if expires > now:
                claims.append(claim)
        except (json.JSONDecodeError, KeyError, ValueError):
            # Skip malformed claims but warn
            print(f"WARNING: malformed claim file {f.name}", file=sys.stderr)
    return claims


def _find_conflicts(my_files: list[str], my_dirs: list[str], active_claims: list[dict], my_agent_id: str) -> list[dict]:
    """Find conflicts between my scope and active claims from other agents."""
    conflicts = []
    my_set = set(my_files)
    for d in my_dirs:
        my_set.add(d.rstrip("/") + "/")

    for claim in active_claims:
        if claim.get("participantId") == my_agent_id:
            continue  # skip self

        their_files = set(claim.get("files", []))
        their_dirs = set(claim.get("directories", []))
        their_may = set(claim.get("mayAffect", []))

        overlap = set()
        for f in my_files:
            if f in their_files or f in their_may:
                overlap.add(f)
            for td in their_dirs:
                if f.startswith(td.rstrip("/") + "/"):
                    overlap.add(f)

        for d in my_dirs:
            norm_d = d.rstrip("/") + "/"
            for tf in their_files | their_may:
                if tf.startswith(norm_d):
                    overlap.add(tf)
            for td in their_dirs:
                norm_td = td.rstrip("/") + "/"
                if norm_d.startswith(norm_td) or norm_td.startswith(norm_d):
                    overlap.add(d)

        if overlap:
            conflicts.append({
                "participantId": claim["participantId"],
                "taskId": claim.get("taskId", "unknown"),
                "overlapping_files": sorted(overlap),
            })

    return conflicts


def _is_broker_available() -> bool:
    """Check broker availability by parsing `intent-broker who` output."""
    try:
        result = subprocess.run(
            ["intent-broker", "who"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return False
        # Check that output contains actual participant lines, not just warnings
        lines = [l for l in result.stdout.strip().splitlines() if l.strip() and not l.startswith("(")]
        return len(lines) > 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _human_in_loop() -> bool:
    """Best-effort check: was the last user message within 5 minutes?"""
    # In Claude Code, this is a heuristic. The skill itself has better context.
    # This CLI provides the raw timestamp check; the skill layer adds semantic judgment.
    return False  # CLI default: no human. Skill overrides this.


def _append_log(repo_root: Path, agent_id: str, entry: dict) -> None:
    log_dir = _log_path(repo_root)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{agent_id}.jsonl"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---- Subcommands ----

def cmd_claim(args: argparse.Namespace) -> None:
    repo_root = _repo_root()
    agent_id = _agent_id()
    claims_dir = _claims_path(repo_root)
    claims_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    ttl = args.ttl or DEFAULT_TTL_MINUTES
    expires = now + timedelta(minutes=ttl)

    # Normalize paths
    files = [_normalize_path(f, repo_root) for f in (args.files or [])]
    dirs = [_normalize_path(d, repo_root) for d in (args.dirs or [])]
    may_affect = [_normalize_path(f, repo_root) for f in (args.may_affect or [])]

    claim = {
        "type": "workspace_claim",
        "action": "claim",
        "participantId": agent_id,
        "project": _project_name(repo_root),
        "files": sorted(set(files)),
        "directories": sorted(set(dirs)),
        "mayAffect": sorted(set(may_affect)),
        "priority": args.priority,
        "taskId": args.task_id or f"task-{int(now.timestamp())}",
        "claimedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresAt": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gitHead": _git_head(),
    }

    # Write local claim file
    claim_file = claims_dir / f"{agent_id}.json"
    claim_file.write_text(json.dumps(claim, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Broadcast via broker if available
    if _is_broker_available():
        try:
            file_list = ",".join(files + dirs) if files or dirs else "workspace"
            subprocess.run(
                ["intent-broker", "group", "notify", "file-changed", _project_name(repo_root),
                 "--reason", f"claim: {file_list}"],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    print(json.dumps({"status": "claimed", "claim": claim}, ensure_ascii=False))


def cmd_notify(args: argparse.Namespace) -> None:
    """Tier 2: Send non-blocking notification to PM about a commit/push."""
    repo_root = _repo_root()
    agent_id = _agent_id()
    project = _project_name(repo_root)
    phase = args.phase
    git_head = args.git_head or _git_head()
    files = args.files or []
    summary = args.summary or f"{phase}: {', '.join(files) if files else 'changes'}"

    msg = (f"[governance] {agent_id} → {phase} in {project}\n"
           f"Files: {', '.join(files) if files else '(none listed)'}\n"
           f"HEAD: {git_head}\n"
           f"Summary: {summary}")

    delivery = _send_to_pm(msg, task_id="governance-three-tier",
                           thread_id="governance-push-review")
    delivered = delivery.get("deliveredCount", 0) > 0

    # Always log
    _append_log(repo_root, agent_id, {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agentId": agent_id,
        "project": project,
        "phase": phase,
        "action": summary,
        "files": files,
        "humanInLoop": False,
        "conflictDetected": False,
        "approvalStatus": "notified_pm" if delivered else "notify_failed",
        "gitHeadAtAction": git_head,
        "deliveryResult": delivery,
    })

    print(json.dumps({
        "status": "notified" if delivered else "notify_failed",
        "recipient": "qoder",
        "delivered": delivered,
        "phase": phase,
    }))


def cmd_request_approval(args: argparse.Namespace) -> None:
    """Tier 3 (gate mode): Request PM approval and wait for response."""
    repo_root = _repo_root()
    agent_id = _agent_id()
    project = _project_name(repo_root)
    phase = args.phase
    git_head = args.git_head or _git_head()
    files = args.files or []
    summary = args.summary or f"{phase}: {', '.join(files) if files else 'changes'}"
    timeout = args.timeout or 120

    if not _is_broker_available():
        _append_log(repo_root, agent_id, {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "agentId": agent_id, "project": project, "phase": phase,
            "action": summary, "files": files,
            "humanInLoop": False, "conflictDetected": True,
            "approvalStatus": "BROKER_DOWN_DEGRADED", "gitHeadAtAction": git_head,
        })
        print(json.dumps({"status": "degraded", "reason": "broker_down", "proceed": True}))
        return

    # Send approval request via HTTP API
    task_id = f"governance-approval-{agent_id}-{int(time.time())}"
    msg = (f"APPROVAL REQUEST (gate mode) from {agent_id}\n"
           f"Project: {project} / Phase: {phase}\n"
           f"Files: {', '.join(files)}\n"
           f"HEAD: {git_head}\n"
           f"Summary: {summary}")

    delivery = _send_to_pm(msg, task_id=task_id)

    # Wait for PM response (poll inbox)
    PM_PARTICIPANT_ID = os.environ.get(
        "GOVERNANCE_PM_ID", "qodercli-session-f782cff3"
    )
    BROKER_URL = os.environ.get("BROKER_URL", "http://127.0.0.1:4318")
    start = time.time()
    while time.time() - start < timeout:
        try:
            result = subprocess.run(
                ["curl", "-s", f"{BROKER_URL}/inbox/{PM_PARTICIPANT_ID}?after=0&limit=5"],
                capture_output=True, text=True, timeout=5,
            )
            inbox_data = json.loads(result.stdout)
            items = inbox_data.get("items", [])
            for item in items:
                body = item.get("payload", {}).get("body", {}).get("summary", "").lower()
                if task_id.lower() in body or "approved" in body or "rejected" in body:
                    if "approved" in body:
                        _append_log(repo_root, agent_id, {
                            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "agentId": agent_id, "project": project, "phase": phase,
                            "action": summary, "files": files,
                            "humanInLoop": False, "conflictDetected": True,
                            "approvalStatus": "approved", "approvalId": task_id,
                            "gitHeadAtAction": git_head,
                        })
                        print(json.dumps({"status": "approved", "approvalId": task_id}))
                        return
                    elif "rejected" in body:
                        _append_log(repo_root, agent_id, {
                            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "agentId": agent_id, "project": project, "phase": phase,
                            "action": summary, "files": files,
                            "humanInLoop": False, "conflictDetected": True,
                            "approvalStatus": "rejected", "approvalId": task_id,
                            "gitHeadAtAction": git_head,
                        })
                        print(json.dumps({"status": "rejected", "approvalId": task_id}))
                        sys.exit(1)
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(5)

    # Timeout → degrade
    _append_log(repo_root, agent_id, {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agentId": agent_id, "project": project, "phase": phase,
        "action": summary, "files": files,
        "humanInLoop": False, "conflictDetected": True,
        "approvalStatus": "DEGRADED_CONFLICT", "approvalId": task_id,
        "gitHeadAtAction": git_head,
    })
    print(json.dumps({"status": "degraded", "reason": "timeout", "proceed": True,
                       "waited_seconds": int(time.time() - start), "approvalId": task_id}))


def cmd_check(args: argparse.Namespace) -> None:
    repo_root = _repo_root()
    agent_id = _agent_id()
    claims_dir = _claims_path(repo_root)

    files = [_normalize_path(f, repo_root) for f in (args.files or [])]
    dirs = [_normalize_path(d, repo_root) for d in (args.dirs or [])]

    active_claims = _read_active_claims(claims_dir)
    conflicts = _find_conflicts(files, dirs, active_claims, agent_id)
    broker_up = _is_broker_available()

    gate_mode = os.environ.get("GOVERNANCE_MODE", "lint")

    result = {
        "brokerAvailable": broker_up,
        "activeClaims": len(active_claims),
        "conflicts": conflicts,
        "hasConflict": len(conflicts) > 0,
        "governanceMode": gate_mode,
    }

    print(json.dumps(result, ensure_ascii=False))


def cmd_renew(args: argparse.Namespace) -> None:
    repo_root = _repo_root()
    agent_id = _agent_id()
    claim_file = _claims_path(repo_root) / f"{agent_id}.json"

    if not claim_file.exists():
        print(json.dumps({"status": "no_claim", "error": "No active claim found for this agent"}))
        sys.exit(1)

    claim = json.loads(claim_file.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    ttl = args.ttl or DEFAULT_TTL_MINUTES
    claim["expiresAt"] = (now + timedelta(minutes=ttl)).strftime("%Y-%m-%dT%H:%M:%SZ")
    claim_file.write_text(json.dumps(claim, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if _is_broker_available():
        try:
            subprocess.run(
                ["intent-broker", "note", json.dumps(claim, ensure_ascii=False)],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    print(json.dumps({"status": "renewed", "expiresAt": claim["expiresAt"]}))


def cmd_expand(args: argparse.Namespace) -> None:
    repo_root = _repo_root()
    agent_id = _agent_id()
    claim_file = _claims_path(repo_root) / f"{agent_id}.json"

    if not claim_file.exists():
        print(json.dumps({"status": "no_claim", "error": "No active claim found for this agent"}))
        sys.exit(1)

    claim = json.loads(claim_file.read_text(encoding="utf-8"))

    new_files = [_normalize_path(f, repo_root) for f in (args.files or [])]
    new_dirs = [_normalize_path(d, repo_root) for d in (args.dirs or [])]
    new_may = [_normalize_path(f, repo_root) for f in (args.may_affect or [])]

    claim["files"] = sorted(set(claim.get("files", []) + new_files))
    claim["directories"] = sorted(set(claim.get("directories", []) + new_dirs))
    claim["mayAffect"] = sorted(set(claim.get("mayAffect", []) + new_may))

    claim_file.write_text(json.dumps(claim, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({"status": "expanded", "files": claim["files"], "directories": claim["directories"], "mayAffect": claim["mayAffect"]}))


def cmd_release(args: argparse.Namespace) -> None:
    repo_root = _repo_root()
    agent_id = _agent_id()
    claim_file = _claims_path(repo_root) / f"{agent_id}.json"

    if not claim_file.exists():
        print(json.dumps({"status": "no_claim", "warning": "No active claim to release"}))
        return

    claim = json.loads(claim_file.read_text(encoding="utf-8"))
    claim_file.unlink()

    release_msg = {
        "type": "workspace_claim",
        "action": "release",
        "participantId": agent_id,
        "taskId": claim.get("taskId", "unknown"),
    }

    if _is_broker_available():
        try:
            task_id = claim.get("taskId", "unknown")
            subprocess.run(
                ["intent-broker", "group", "notify", "file-changed", _project_name(repo_root),
                 "--reason", f"release: {task_id}"],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    print(json.dumps({"status": "released", "taskId": claim.get("taskId")}))


def cmd_log(args: argparse.Namespace) -> None:
    repo_root = _repo_root()
    agent_id = _agent_id()

    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agentId": agent_id,
        "project": _project_name(repo_root),
        "phase": args.phase,
        "action": args.action,
        "files": [_normalize_path(f, repo_root) for f in (args.files or [])],
        "humanInLoop": args.human_in_loop,
        "conflictDetected": args.conflict,
        "approvalStatus": args.status,
    }
    if args.conflicts:
        entry["activeConflicts"] = json.loads(args.conflicts)
    if args.git_head:
        entry["gitHeadAtAction"] = args.git_head

    _append_log(repo_root, agent_id, entry)
    print(json.dumps({"status": "logged"}))


def cmd_cleanup(args: argparse.Namespace) -> None:
    repo_root = _repo_root()
    claims_dir = _claims_path(repo_root)
    now = datetime.now(timezone.utc)
    removed = 0

    if not claims_dir.exists():
        print(json.dumps({"status": "nothing_to_clean", "removed": 0}))
        return

    for f in list(claims_dir.glob("*.json")):
        try:
            claim = json.loads(f.read_text(encoding="utf-8"))
            expires = datetime.fromisoformat(claim["expiresAt"].replace("Z", "+00:00"))
            if expires <= now:
                f.unlink()
                removed += 1
        except (json.JSONDecodeError, KeyError, ValueError):
            # Remove malformed claim files
            f.unlink()
            removed += 1

    print(json.dumps({"status": "cleaned", "removed": removed}))


def cmd_status(args: argparse.Namespace) -> None:
    repo_root = _repo_root()
    agent_id = _agent_id()
    claims_dir = _claims_path(repo_root)

    claim_file = claims_dir / f"{agent_id}.json"
    has_claim = claim_file.exists()

    active_claims = _read_active_claims(claims_dir)
    broker_up = _is_broker_available()

    result = {
        "agentId": agent_id,
        "project": _project_name(repo_root),
        "hasActiveClaim": has_claim,
        "brokerAvailable": broker_up,
        "activeClaimsCount": len(active_claims),
        "activeClaimAgents": [c["participantId"] for c in active_claims],
    }

    if has_claim:
        claim = json.loads(claim_file.read_text(encoding="utf-8"))
        expires = datetime.fromisoformat(claim["expiresAt"].replace("Z", "+00:00"))
        result["claimExpiresIn"] = f"{(expires - datetime.now(timezone.utc)).total_seconds():.0f}s"

    print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="governance",
        description="Multi-agent workspace governance CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # claim
    p_claim = sub.add_parser("claim", help="Claim workspace files/directories")
    p_claim.add_argument("--files", nargs="*", default=[], help="Files to claim")
    p_claim.add_argument("--dirs", nargs="*", default=[], help="Directories to claim")
    p_claim.add_argument("--may-affect", nargs="*", default=[], help="Files you may indirectly affect")
    p_claim.add_argument("--task-id", default=None, help="Explicit task ID")
    p_claim.add_argument("--ttl", type=int, default=None, help="TTL in minutes (default 30)")
    p_claim.add_argument("--priority", default="normal", help="Claim priority: low/normal/high (default normal)")

    # check
    p_check = sub.add_parser("check", help="Check for conflicts before acting")
    p_check.add_argument("--files", nargs="*", default=[], help="Files you plan to touch")
    p_check.add_argument("--dirs", nargs="*", default=[], help="Directories you plan to touch")

    # renew
    p_renew = sub.add_parser("renew", help="Renew your active claim")
    p_renew.add_argument("--ttl", type=int, default=None, help="TTL in minutes (default 30)")

    # expand
    p_expand = sub.add_parser("expand", help="Expand your claim scope")
    p_expand.add_argument("--files", nargs="*", default=[], help="Additional files to claim")
    p_expand.add_argument("--dirs", nargs="*", default=[], help="Additional directories to claim")
    p_expand.add_argument("--may-affect", nargs="*", default=[], help="Additional may-affect files")

    # release
    p_release = sub.add_parser("release", help="Release your workspace claim")

    # log
    p_log = sub.add_parser("log", help="Log a governance action")
    p_log.add_argument("--phase", required=True, help="planning/implementing/destructive/committing/configuring/verifying")
    p_log.add_argument("--action", required=True, help="What you did")
    p_log.add_argument("--files", nargs="*", default=[], help="Files involved")
    p_log.add_argument("--human-in-loop", action="store_true", help="Human was actively driving")
    p_log.add_argument("--conflict", action="store_true", help="Conflict was detected")
    p_log.add_argument("--status", required=True, help="Approval status")
    p_log.add_argument("--conflicts", default=None, help="JSON array of active conflicts")
    p_log.add_argument("--git-head", default=None, help="Git HEAD at action time")

    # cleanup
    p_cleanup = sub.add_parser("cleanup", help="Remove expired and malformed claims")

    # status
    p_status = sub.add_parser("status", help="Show current governance state")

    # notify (tier 2: non-blocking PM notification)
    p_notify = sub.add_parser("notify", help="Send non-blocking notification to PM about commit/push")
    p_notify.add_argument("--phase", required=True, help="committing/verifying")
    p_notify.add_argument("--files", nargs="*", default=[], help="Files involved")
    p_notify.add_argument("--git-head", default=None, help="Git HEAD at time of notification")
    p_notify.add_argument("--summary", default=None, help="One-line summary of the change")

    # request-approval (tier 3: gate mode blocking approval)
    p_req = sub.add_parser("request-approval", help="Request PM approval and wait (gate mode)")
    p_req.add_argument("--phase", required=True, help="committing/verifying")
    p_req.add_argument("--files", nargs="*", default=[], help="Files involved")
    p_req.add_argument("--git-head", default=None, help="Git HEAD at time of request")
    p_req.add_argument("--summary", default=None, help="One-line summary of the change")
    p_req.add_argument("--timeout", type=int, default=120, help="Timeout in seconds (default 120)")

    args = parser.parse_args()

    commands = {
        "claim": cmd_claim,
        "check": cmd_check,
        "renew": cmd_renew,
        "expand": cmd_expand,
        "release": cmd_release,
        "notify": cmd_notify,
        "request-approval": cmd_request_approval,
        "log": cmd_log,
        "cleanup": cmd_cleanup,
        "status": cmd_status,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
