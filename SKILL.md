---
name: kai-project-governance
description: "Use when: (1) an agent is about to modify files, commit code, delete files, modify configs, or execute plans in a multi-agent environment, OR (2) the user asks about coordinating agents, preventing conflicts, or workspace governance. Triggers on: modifying source files, git operations, plan creation, deployment, file deletion, config changes, dependency changes, multi-agent coordination, conflict prevention. Even when the user is actively driving the session, this skill still checks for conflicts and displays warnings — it just doesn't block."
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

## Governance check flow

Run this flow before each controlled node (planning / implementing / destructive /
committing / configuring / verifying).

### Step 1 — Claim your workspace

Before starting a task, publish a workspace claim so other agents know what you
plan to touch. Read `references/workspace-claims.md` for the full protocol, then:

```bash
# Publish your claim
intent-broker note "{\"type\":\"workspace_claim\",\"action\":\"claim\",\"participantId\":\"$(hostname)-$$\",\"project\":\"$(basename $(git rev-parse --show-toplevel))\",\"files\":[\"path/to/file.py\"],\"directories\":[\"src/module/\"],\"mayAffect\":[\"src/shared/types.py\"],\"taskId\":\"task-$(date +%s)\",\"claimedAt\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"expiresAt\":\"$(date -u -v+30M +%Y-%m-%dT%H:%M:%SZ)\",\"gitHead\":\"$(git rev-parse HEAD)\"}"
```

Also write the same claim to `.governance-claims/<your-agent-id>.json` in the
project root. This is the authoritative source for claim queries — the broker
broadcast is just a notification.

Wait **5 seconds** after publishing. If another agent publishes an overlapping
claim during this window, compare `taskId` values — the lexicographically smaller
one wins. If you lose, wait for the other agent to finish or adjust your scope.

### Step 2 — Check broker availability

```bash
intent-broker who 2>/dev/null || echo "BROKER_DOWN"
```

If the broker is down, skip to Step 3 but note that PM approval is unavailable.
The local claim files still work for conflict detection.

### Step 3 — Check for conflicts

Read all files in `.governance-claims/` and find claims where `expiresAt` is still
in the future. Compare those claims' `files`, `directories`, and `mayAffect` fields
against the files you are about to touch. Use git-relative paths (resolved via
`git rev-parse --show-toplevel`).

- **No overlap** → proceed. Log to `.governance-log/<your-agent-id>.jsonl`.
- **Overlap found** → go to Step 4.

### Step 4 — Is a human actively driving this session?

Check whether the most recent user message in this conversation is less than
5 minutes old. This is a heuristic — it's not a cryptographic proof of human
attention, just a practical signal.

**If yes (human present):**

Display the conflict information in the conversation:

```
⚠️ Workspace conflict detected:
  - <agent-id> is editing <file-list>
  You may proceed, but be aware of potential merge conflicts.
```

Proceed. Log as `skipped_human_in_loop_with_warning`.

**If no (autonomous):**

Request PM approval via broker:

```bash
intent-broker task qoder "Approval request from <your-agent-id>: <project> / <phase>
Files: <file-list>
Conflicting agents: <agent-list>
git HEAD: <sha>
Action summary: <what you're about to do>"
```

Wait up to 120 seconds for a response.

- **Approved** → verify `git HEAD` hasn't changed since the request. Proceed.
- **Rejected** → stop. Adjust per PM feedback.
- **Timeout** → proceed (degraded). Log as `DEGRADED_CONFLICT`. This event
  will be flagged for PM review when they come back online.

### Step 5 — Log the action

Append one line to `.governance-log/<your-agent-id>.jsonl`:

```json
{"timestamp":"<ISO>","agentId":"<id>","project":"<name>","phase":"<phase>","action":"<action>","files":["<list>"],"humanInLoop":<bool>,"conflictDetected":<bool>,"activeConflicts":[<objects>],"approvalStatus":"<status>","gitHeadAtAction":"<sha>","details":"<text>"}
```

`approvalStatus` values: `approved`, `skipped_human_in_loop_with_warning`,
`no_conflict`, `DEGRADED_CONFLICT`, `BROKER_DOWN_DEGRADED`.

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

- **Create**: At task start, before any file edits.
- **Renew**: Every 10 minutes during long tasks (update `expiresAt`).
- **Expand**: When you discover the task affects more files than initially claimed,
  publish an updated claim with the expanded scope.
- **Release**: When the task completes or you abandon it.

```bash
# Release your claim
intent-broker note "{\"type\":\"workspace_claim\",\"action\":\"release\",\"participantId\":\"<your-agent-id>\",\"taskId\":\"<your-task-id>\"}"
rm .governance-claims/<your-agent-id>.json
```

## PM workflow

When you are the PM reviewing approvals, read `references/pm-governance.md` for
the full flow including batch approval and degraded-event review.

## Reference files

| File | When to read |
|------|-------------|
| `references/workspace-claims.md` | Before creating or reading claims — full protocol, race-condition mitigation, path normalization |
| `references/pm-governance.md` | When acting as PM — approval queue, batch operations, degraded event review |
| `references/broker-commands.md` | When you need the exact broker CLI syntax for claims, approvals, or queries |
| `references/operation-severity.md` | When deciding how cautious to be — classifies operations by blast radius |
