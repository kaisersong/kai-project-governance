#!/usr/bin/env python3
"""Eval runner for kai-project-governance. Executes eval cases and produces baseline report."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "governance.py"
EVAL_CASES = ROOT / "evals" / "eval-cases.json"


def _run_gov(workspace: Path, agent_id: str, cmd: str, args: dict) -> dict:
    """Run a governance CLI command and return parsed JSON output."""
    argv = [sys.executable, str(SCRIPT), cmd]

    if cmd == "claim":
        for f in args.get("files", []):
            argv.extend(["--files", f])
        for d in args.get("dirs", []):
            argv.extend(["--dirs", d])
        for m in args.get("may_affect", []):
            argv.extend(["--may-affect", m])
        if "ttl" in args:
            argv.extend(["--ttl", str(args["ttl"])])
    elif cmd == "check":
        for f in args.get("files", []):
            argv.extend(["--files", f])
        for d in args.get("dirs", []):
            argv.extend(["--dirs", d])
    elif cmd == "renew":
        if "ttl" in args:
            argv.extend(["--ttl", str(args["ttl"])])
    elif cmd == "expand":
        for f in args.get("files", []):
            argv.extend(["--files", f])
        for d in args.get("dirs", []):
            argv.extend(["--dirs", d])
        for m in args.get("may_affect", []):
            argv.extend(["--may-affect", m])
    elif cmd == "log":
        argv.extend(["--phase", args.get("phase", "implementing")])
        argv.extend(["--action", args.get("action", "test")])
        argv.extend(["--status", args.get("status", "no_conflict")])
        for f in args.get("files", []):
            argv.extend(["--files", f])
        if args.get("human_in_loop"):
            argv.append("--human-in-loop")
        if args.get("conflict"):
            argv.append("--conflict")

    result = subprocess.run(
        argv,
        cwd=workspace,
        capture_output=True,
        text=True,
        env={**os.environ, "GOVERNANCE_AGENT_ID": agent_id},
    )

    if result.returncode != 0:
        return {"_error": True, "_stderr": result.stderr, "_returncode": result.returncode}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"_raw": result.stdout}


def _init_workspace() -> Path:
    """Create a temp git repo for testing."""
    tmp = Path(tempfile.mkdtemp(prefix="gov-eval-"))
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "eval@test.com"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Eval"], cwd=tmp, capture_output=True, check=True)
    (tmp / "README.md").write_text("# eval")
    subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True)
    return tmp


def _write_expired_claim(workspace: Path, agent_id: str, claim_data: dict) -> None:
    """Write a synthetic claim file directly."""
    claims_dir = workspace / ".governance-claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    claim = {
        "type": "workspace_claim",
        "action": "claim",
        "participantId": agent_id,
        "project": workspace.name,
        "files": claim_data.get("files", []),
        "directories": claim_data.get("directories", []),
        "mayAffect": claim_data.get("mayAffect", []),
        "taskId": f"task-synthetic-{agent_id}",
        "claimedAt": "2020-01-01T00:00:00Z",
        "expiresAt": claim_data.get("expiresAt", "2020-01-01T00:00:00Z"),
        "gitHead": "0000000000000000000000000000000000000000",
    }
    (claims_dir / f"{agent_id}.json").write_text(json.dumps(claim) + "\n")


def _check_assert(output: dict, assertion: dict) -> tuple[bool, str]:
    """Check an assertion against CLI output. Returns (passed, message)."""
    for key, expected in assertion.items():
        if key == "conflict_count":
            actual = len(output.get("conflicts", []))
            if actual != expected:
                return False, f"conflict_count: expected {expected}, got {actual}"
        else:
            actual = output.get(key)
            if actual != expected:
                return False, f"{key}: expected {expected}, got {actual}"
    return True, "ok"


def run_eval(eval_case: dict) -> dict:
    """Run a single eval case and return results."""
    case_id = eval_case["id"]
    name = eval_case["name"]
    workspace = _init_workspace()
    default_agent = f"eval-agent-{case_id}"

    steps_run = 0
    steps_passed = 0
    findings = []
    start = time.time()

    # Setup: create claims for other agents
    for setup in eval_case.get("setup", []):
        if "write_claim" in setup:
            agent = setup["write_claim"].get("agent", "synthetic")
            _write_expired_claim(workspace, agent, setup["write_claim"])
        else:
            agent = setup.get("agent", default_agent)
            cmd = setup["cmd"]
            args = setup.get("args", {})
            _run_gov(workspace, agent, cmd, args)

    # Main steps
    agent_ids_seen = []
    for step in eval_case.get("steps", []):
        agent = step.get("agent", default_agent)
        cmd = step["cmd"]
        args = step.get("args", {})

        output = _run_gov(workspace, agent, cmd, args)
        steps_run += 1

        if output.get("_error"):
            findings.append({
                "step": cmd,
                "severity": "high",
                "message": f"CLI error: {output.get('_stderr', '')[:200]}",
            })
            continue

        # Check assertions
        if "assert" in step:
            passed, msg = _check_assert(output, step["assert"])
            if passed:
                steps_passed += 1
            else:
                findings.append({
                    "step": cmd,
                    "severity": "medium",
                    "message": f"Assertion failed: {msg}",
                })
        else:
            steps_passed += 1

        # Track agent ID consistency
        if "agentId" in output:
            agent_ids_seen.append(output["agentId"])

    # Teardown
    for teardown in eval_case.get("teardown", []):
        agent = teardown.get("agent", default_agent)
        _run_gov(workspace, agent, teardown.get("cmd", "release"), teardown.get("args", {}))

    # Check agent ID consistency
    agent_id_consistent = len(set(agent_ids_seen)) <= 1 if agent_ids_seen else True

    # Score
    elapsed = time.time() - start
    score = steps_passed / steps_run if steps_run > 0 else 0

    # Rubric scoring
    rubric = {
        "claim_protocol": 5,
        "conflict_detection": 5,
        "degradation_handling": 5,
        "log_integrity": 5,
    }

    for f in findings:
        sev = f["severity"]
        penalty = 1 if sev == "medium" else 2
        step = f.get("step", "")
        if step in ("claim", "release", "renew", "expand"):
            rubric["claim_protocol"] = max(1, rubric["claim_protocol"] - penalty)
        elif step == "check":
            rubric["conflict_detection"] = max(1, rubric["conflict_detection"] - penalty)
        elif step == "log":
            rubric["log_integrity"] = max(1, rubric["log_integrity"] - penalty)
        else:
            rubric["degradation_handling"] = max(1, rubric["degradation_handling"] - penalty)

    verdict = "pass" if score == 1.0 and not findings else ("needs_work" if score >= 0.5 else "fail")

    # Cleanup
    import shutil
    shutil.rmtree(workspace, ignore_errors=True)

    return {
        "case_id": case_id,
        "name": name,
        "verdict": verdict,
        "score": round(score, 2),
        "steps_run": steps_run,
        "steps_passed": steps_passed,
        "scores": rubric,
        "findings": findings,
        "agent_id_consistent": agent_id_consistent,
        "elapsed_seconds": round(elapsed, 2),
        "summary": f"{steps_passed}/{steps_run} steps passed" + (f", {len(findings)} findings" if findings else ""),
    }


def main():
    cases = json.loads(EVAL_CASES.read_text(encoding="utf-8"))
    results = []
    total_start = time.time()

    print(f"Running {len(cases['evals'])} eval cases for {cases['skill_name']}...")
    print("=" * 60)

    for case in cases["evals"]:
        result = run_eval(case)
        results.append(result)
        status = "PASS" if result["verdict"] == "pass" else ("WARN" if result["verdict"] == "needs_work" else "FAIL")
        print(f"  [{status}] #{result['case_id']:2d} {result['name']:<35s} {result['summary']}")

    total_elapsed = time.time() - total_start

    # Aggregate
    total = len(results)
    passed = sum(1 for r in results if r["verdict"] == "pass")
    needs_work = sum(1 for r in results if r["verdict"] == "needs_work")
    failed = sum(1 for r in results if r["verdict"] == "fail")

    avg_scores = {}
    for dim in ["claim_protocol", "conflict_detection", "degradation_handling", "log_integrity"]:
        vals = [r["scores"][dim] for r in results]
        avg_scores[dim] = round(sum(vals) / len(vals), 2) if vals else 0

    all_findings = [f for r in results for f in r["findings"]]
    agent_id_ok = all(r["agent_id_consistent"] for r in results)

    report = {
        "skill_name": cases["skill_name"],
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline_version": 1,
        "summary": {
            "total": total,
            "passed": passed,
            "needs_work": needs_work,
            "failed": failed,
            "pass_rate": round(passed / total, 2) if total else 0,
        },
        "average_scores": avg_scores,
        "agent_id_consistency": agent_id_ok,
        "total_findings": len(all_findings),
        "total_elapsed_seconds": round(total_elapsed, 2),
        "results": results,
    }

    print()
    print("=" * 60)
    print(f"BASELINE REPORT")
    print(f"  Total: {total} | Passed: {passed} | Needs Work: {needs_work} | Failed: {failed}")
    print(f"  Pass rate: {report['summary']['pass_rate']:.0%}")
    print(f"  Avg scores: claim={avg_scores['claim_protocol']} conflict={avg_scores['conflict_detection']} "
          f"degrade={avg_scores['degradation_handling']} log={avg_scores['log_integrity']}")
    print(f"  Agent ID consistency: {'OK' if agent_id_ok else 'FAIL'}")
    print(f"  Findings: {len(all_findings)}")
    print(f"  Elapsed: {total_elapsed:.1f}s")

    # Save report
    report_path = ROOT / "evals" / "baseline-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n  Report saved to: {report_path}")


if __name__ == "__main__":
    main()
