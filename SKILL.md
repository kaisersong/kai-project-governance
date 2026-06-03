---
name: kai-project-governance
description: "Use before modifying, deleting, committing, pushing, changing config/dependencies, deploying, or writing plans in a shared repo or multi-agent workspace; use for coordinating agents, workspace claims, conflict prevention, PM approval. Chinese: 并发协作/冲突/多代理治理. Do not use for read-only questions, code search, git diff/log, or running tests."
---

# kai-project-governance

Multi-agent conflict prevention for AI coding environments.

This skill is a **concurrency safety lint** — not a lock, not a gate. It reduces
the probability of agents trampling each other's work by making workspace claims
visible and routing conflicts to a human decision-maker (PM) when no human is
actively driving the agent.

## Known scope

This skill cannot prevent conflicts from agents that don't run it, from shell
commands, from CI jobs, or from editors. For hard enforcement, use git hooks,
CI branch protection, or file permissions — those are different layers.

## Setup

Set your stable agent identity before using this skill. Pick one:

```bash
# Option A: Explicit (recommended for CI/scripts)
export GOVERNANCE_AGENT_ID="my-agent-session-123"

# Option B: Auto-detected from broker or hostname-based session file
# No action needed — `governance status` will show your ID
```

All commands use `scripts/governance.py` which handles path normalization,
claim storage, conflict detection, and logging deterministically.

## Governance check flow

Run this flow before each controlled node (planning / implementing / destructive /
committing / configuring / verifying).

### Step 1 — Claim your workspace

```bash
python3 scripts/governance.py claim \
  --files src/module/main.py src/module/types.py \
  --dirs src/module/ \
  --may-affect src/shared/types.py tests/test_module.py
```

This writes `.governance-claims/<agent-id>.json` and broadcasts via broker
if available. The script handles timestamps, TTL, path normalization, and git HEAD.

Wait **5 seconds** after claiming. Re-check for competing claims:

```bash
sleep 5 && python3 scripts/governance.py check --files src/module/main.py
```

If another agent published an overlapping claim during the window, compare
`taskId` values — the lexicographically smaller one wins. If you lose, wait
for the other agent to finish or adjust your scope.

### Step 2 — Check for conflicts

```bash
python3 scripts/governance.py check \
  --files src/module/main.py \
  --dirs src/module/
```

Output:
```json
{
  "brokerAvailable": true,
  "activeClaims": 2,
  "conflicts": [{"participantId": "agent-b", "overlapping_files": ["src/module/main.py"]}],
  "hasConflict": true
}
```

- `hasConflict: false` → proceed. Log the action (Step 5).
- `hasConflict: true` → go to Step 3.

### Step 3 — Human in the loop?

Check whether the most recent user message in this conversation is less than
5 minutes old.

**If yes (human present):**

Display the conflict info in conversation:
```
⚠️ Workspace conflict detected:
  - agent-b is editing src/module/main.py
  You may proceed, but be aware of potential merge conflicts.
```

Proceed. Log as `skipped_human_in_loop_with_warning`.

**If no (autonomous):**

Request PM approval via broker:

```bash
intent-broker task qoder "APPROVAL REQUEST from $(python3 scripts/governance.py status | python3 -c 'import sys,json; print(json.load(sys.stdin)["agentId"])')
Project: <project> / Phase: <phase>
Files: <file-list>
Conflicts: <conflict-list>
git HEAD: $(git rev-parse HEAD)
Summary: <what you're about to do>"
```

Wait up to 120 seconds.

- **Approved** → verify `git HEAD` unchanged. Proceed.
- **Rejected** → stop. Adjust per PM feedback. Log as `rejected`.
- **Timeout** → proceed (degraded). Log as `DEGRADED_CONFLICT`.

### Step 4 — Log the action

```bash
python3 scripts/governance.py log \
  --phase implementing \
  --action "edit source" \
  --files src/module/main.py \
  --status no_conflict
```

For conflicts, add flags:
```bash
python3 scripts/governance.py log \
  --phase committing \
  --action "git push" \
  --files src/module/main.py src/module/types.py \
  --human-in-loop \
  --conflict \
  --status skipped_human_in_loop_with_warning \
  --git-head "$(git rev-parse HEAD)"
```

Valid `--status` values: `approved`, `skipped_human_in_loop_with_warning`,
`no_conflict`, `DEGRADED_CONFLICT`, `BROKER_DOWN_DEGRADED`, `rejected`.

Valid `--phase` values: `planning`, `implementing`, `destructive`,
`committing`, `configuring`, `verifying`.

### Step 5 — Release when done

```bash
python3 scripts/governance.py release
```

This removes your claim file and broadcasts a release message.

## Controlled nodes

| Node | When to check | What to check |
|------|---------------|---------------|
| Planning | Before writing a plan file | Planned scope |
| Implementing | Before writing/editing source files | Exact file paths |
| Destructive | Before deleting, renaming, or moving files | Impact + dependents |
| Committing | Before `git commit` or `git push` | `git diff --name-only` |
| Configuring | Before changing config/deps/env files | Global impact |
| Verifying | Before deploy/release operations | Blast radius |

## Claim lifecycle

- **Create**: `governance claim` at task start.
- **Renew**: `governance renew --ttl 30` every 10 minutes during long tasks.
- **Expand**: `governance expand --files new_file.py` when scope grows.
- **Release**: `governance release` when done.
- **Cleanup**: `governance cleanup` removes expired/malformed claims.

## Status check

```bash
python3 scripts/governance.py status
```

Shows your agent ID, active claim, broker availability, and other active claims.

## PM workflow

When you are the PM reviewing approvals, read `references/pm-governance.md`.

## Reference files

| File | When to read |
|------|-------------|
| `references/workspace-claims.md` | Before creating or reading claims — full protocol, race-condition mitigation, path normalization |
| `references/pm-governance.md` | When acting as PM — approval queue, batch operations, degraded event review |
| `references/broker-commands.md` | When you need the exact broker CLI syntax for claims, approvals, or queries |
| `references/operation-severity.md` | When deciding how cautious to be — classifies operations by blast radius |
