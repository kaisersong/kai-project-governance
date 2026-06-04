# Conflict Radar and Human Gate Redesign

Date: 2026-06-04
Project: kai-project-governance
Status: Design approved for planning

## Summary

`kai-project-governance` should shift from an approval-gate story to a
conflict-radar and risk-reduction story.

The system cannot reliably prevent all multi-agent conflicts. It cannot provide
hard locking across editors, shells, CI jobs, or agents that do not run the
skill. It also cannot delegate real approval decisions to a PM agent that lacks
task context. Its realistic value is to record workspace intent, detect likely
overlap, package useful context, notify the right participants, and pause only
for operations that need human judgment.

New product promise:

> A cooperative conflict radar for multi-agent workspaces. It records workspace
> intent, detects likely overlap, packages context for humans, and pauses only
> for high-risk operations that need human judgment. It is not a lock and not an
> autonomous approval authority.

## Problem

The current design treats `GATE` as a mode where an approval request can be sent
to a PM participant. That sounds useful, but the PM agent usually sees only:

- which files another agent claimed;
- which files the current agent wants to touch;
- a task id or short summary;
- a git head;
- a conflict list.

That is not enough information to decide whether work should proceed. A real
approval decision often depends on business priority, user intent, semantic code
impact, current conversation context, active incidents, release timing, and
whether overlapping file edits are actually conflicting.

An under-contextualized PM agent can summarize conflict data, but it should not
approve or reject work. Treating it as an authority creates fake safety: agents
appear governed while the actual decision was made by a participant with too
little context.

## Goals

- Reduce the chance of silent multi-agent workspace collisions.
- Make file and directory overlap visible before agents continue.
- Package conflict context in a form that a human can judge quickly.
- Notify related agents without turning every overlap into a blocking event.
- Pause only for high-risk operations that truly require human judgment.
- Keep the default workflow low-friction for ordinary source, test, and docs
  edits.
- Make broker failures and degraded decisions explicit in logs.

## Non-Goals

- Do not provide a hard lock.
- Do not guarantee that all conflicts are prevented.
- Do not block agents that do not run this skill.
- Do not capture arbitrary editor, shell, or CI mutations.
- Do not make semantic conflict decisions from path overlap alone.
- Do not let a PM agent approve or reject work by default.
- Do not gate every commit or normal push.

## Behavior Model

Replace the current `LINT / NOTIFY / GATE` framing with:

| Layer | Name | Purpose | Blocking |
| --- | --- | --- | --- |
| 1 | `RADAR` | Claim workspace intent, detect likely overlap, log actions. | No |
| 2 | `NUDGE` | Notify related agents and surface conflict packets. | Usually no |
| 3 | `HUMAN_GATE` | Pause for human confirmation on high-risk operations. | Yes |

`GATE` should mean only human gate. It must not mean autonomous PM-agent
approval.

## Decision Principles

1. Human-in-the-loop is the highest-priority decision source.
2. Agents may detect, explain, summarize, and recommend. They do not approve.
3. Ordinary source, test, and documentation edits should not block by default.
4. High-risk operations must require human judgment when no clear human context
   is available.
5. If human presence cannot be confirmed, the system should choose pause,
   nudge, degrade, or log based on severity. It must not claim an approval
   happened.
6. Delivery is not approval. A broker message with `deliveredCount > 0` only
   proves notification, not authorization.

## Operation Severity Matrix

| Operation | Severity | Default Behavior |
| --- | --- | --- |
| Read files, search, git diff, git log, local test run | low | No governance check needed. |
| Source, test, or docs edit | medium | `RADAR`; if overlap exists, `NUDGE`. |
| Shared types, API contract, config, dependency, lockfile, CI, env changes | high | `RADAR` and `NUDGE`; pause if autonomous with active conflict. |
| Normal git push | medium or high | Notify only by default; high if project config says push triggers deploy. |
| Release, publish, deploy, tag | critical | `HUMAN_GATE`. |
| Force push, hard reset, destructive delete, git rm, batch move | critical | `HUMAN_GATE`. |
| Autonomous active conflict | medium to critical | Medium may degrade; high and critical pause. |

Project config may refine these defaults, for example:

```json
{
  "pushTriggersDeploy": true,
  "publishOperations": ["git tag", "gh release", "clawhub publish"],
  "humanGateOn": ["critical", "high_autonomous_conflict"]
}
```

## Conflict Packet

The conflict packet is the central artifact. It replaces approval requests as
the primary output of conflict detection.

Example:

```json
{
  "type": "governance_conflict_packet",
  "project": "kai-project-governance",
  "operation": "edit source",
  "severity": "medium",
  "decisionRequired": false,
  "requestingAgent": {
    "id": "agent-b",
    "taskId": "task-123",
    "summary": "rename PM approval to human gate",
    "files": ["SKILL.md", "scripts/governance.py"],
    "gitHead": "abc123"
  },
  "conflicts": [
    {
      "agentId": "agent-a",
      "taskId": "task-122",
      "summary": "update governance CLI",
      "overlap": ["scripts/governance.py"],
      "expiresAt": "2026-06-04T12:30:00Z"
    }
  ],
  "recommendedAction": "warn_and_continue_with_human_present"
}
```

Required fields:

- `type`
- `project`
- `operation`
- `severity`
- `decisionRequired`
- `requestingAgent`
- `conflicts`
- `recommendedAction`

The CLI should support both concise human output and full JSON output. The
concise output should show who conflicts, which files overlap, and what action
is recommended. The JSON output is for tests, automation, and future tooling.

## CLI Contract Changes

Keep these commands:

- `claim`
- `check`
- `renew`
- `expand`
- `release`
- `log`
- `cleanup`
- `status`

Change these commands:

- `check` adds `--operation`, `--severity`, and optionally `--human-in-loop`.
- `check` outputs `decisionRequired`, `recommendedAction`, and
  `conflictPacket` when relevant.
- `notify` means notification only. It never implies approval.
- `request-approval` becomes a deprecated alias with a warning.
- Add `human-gate` or `request-human-confirmation` for high-risk operations.
- Rename `GOVERNANCE_PM_ID` semantics to `GOVERNANCE_NOTIFY_TARGET` or
  `GOVERNANCE_HUMAN_TARGET`, depending on use.
- Replace `GOVERNANCE_MODE=gate` with `GOVERNANCE_MODE=radar|nudge|human_gate`.

Status names should avoid approval language:

- Use `confirmed`, `declined`, `timed_out`, `degraded`, `notified`,
  `notify_failed`.
- Avoid `approved` and `rejected` except in deprecated compatibility output.

## Skill-Layer Contract

The CLI must not infer human-in-the-loop from conversation timing. It does not
have reliable access to that context. The skill or agent runtime decides whether
a human is currently driving the session and passes that as an explicit input.

Example:

```bash
python3 scripts/governance.py check \
  --files scripts/governance.py \
  --operation "edit source" \
  --human-in-loop
```

If a human is present:

- show the conflict packet;
- allow the human to continue directing the agent;
- log `skipped_human_in_loop_with_warning` or an equivalent renamed status.

If no human is present:

- low: ignore or log;
- medium: nudge, log, and continue only if the operation is reversible;
- high: pause when active conflict exists, otherwise notify/log;
- critical: human gate.

## PM Agent Role

The PM agent is not an approval authority by default.

Allowed PM-agent behavior:

- summarize overlap;
- route notifications;
- show task summaries and conflicting files;
- ask for human judgment;
- keep degraded-event review queues visible.

Disallowed PM-agent behavior:

- approve;
- reject;
- decide which agent wins;
- claim that a notification equals authorization.

If a future deployment gives a PM agent full task context and explicit authority,
that should be a separate, opt-in mode with its own documented guarantees.

## Broker Failure Policy

Broker failure must be explicit. The system should never fake success.

Default policy:

| Severity | Broker Down Behavior |
| --- | --- |
| low | Ignore or local log. |
| medium | Local log and continue if reversible. |
| high | Ask current user if present; otherwise degrade only if project policy allows it. |
| critical | Block unless the current human explicitly confirms. |

Every broker-down path should log:

- operation;
- severity;
- conflict status;
- intended notification target;
- reason for degradation or block;
- git head at action time.

## Nudge Deduplication

Nudges must avoid notification noise.

Deduplicate by:

- project;
- requesting task id;
- conflicting task id;
- overlap set;
- severity.

Send a new nudge only when:

- severity increases;
- overlap set changes materially;
- a new conflicting task appears;
- the previous nudge expired.

Low and medium conflict nudges should usually stay in the current agent context.
High and critical nudges may interrupt related agents or request human
confirmation.

## Scope Drift

Claims are often imperfect because agents discover additional files while
working. Scope drift should be treated as a first-class signal.

Before commit, push, publish, destructive operations, or human gate, compare:

- current claim files/directories/mayAffect;
- `git diff --name-only`;
- operation file arguments.

If touched files are outside the claim:

- warn;
- recommend `expand`;
- include drift in the conflict packet;
- log the drift.

Scope drift is not automatically a block for medium work. It can become a block
for high or critical operations.

## Pre-Push and Publish Behavior

Normal push:

- notify only by default;
- do not block by default;
- upgrade to high if project config says push triggers deploy.

Release, publish, deploy, tag:

- require human gate.

Force push and destructive git operations:

- require human gate.

The pre-push hook should be portable:

- resolve symlink targets correctly;
- handle filenames safely;
- not assume target repositories vendor `scripts/governance.py`;
- fail explicitly for critical operations if the governance script cannot be
  found.

## Documentation Changes

Update README, SKILL, and references to remove PM approval framing.

Remove or rewrite:

- "prevents agents from overwriting each other";
- "PM approves";
- "PM rejects";
- "gate mode asks PM";
- "governance-pm role" as default authority.

Use:

- "surfaces likely overlap";
- "packages context for human judgment";
- "notifies relevant participants";
- "human confirmation for high-risk operations";
- "risk reduction, not prevention".

## Test and Eval Plan

Add tests for:

- normal edit with no conflict -> no decision required;
- normal edit with overlap and human present -> warn only;
- normal edit with overlap and no human -> nudge and log;
- high-risk config/deps/CI change with overlap -> decision required;
- release/publish/tag -> human gate required;
- force push/destructive action -> human gate required;
- PM-agent "approved" reply is not treated as authorization;
- notify target missing -> local log remains valid and no fake success;
- broker down plus critical operation -> block or explicit human confirmation;
- repeated conflict -> nudge deduplication;
- scope drift -> expand warning;
- normal push -> notify only;
- push that triggers deploy -> high-risk behavior.

Add eval coverage for:

- conflict packet completeness;
- recommended action mapping;
- severity matrix;
- broker-down degradation policy;
- deprecated `request-approval` behavior;
- skill-layer scenarios where human presence changes behavior.

## Migration Plan

1. Rewrite docs and terminology first.
2. Extend `check` to produce conflict packets and decision metadata.
3. Split notification from human confirmation.
4. Deprecate approval commands and approval statuses.
5. Update pre-push and publish behavior.
6. Add tests and evals for the new contract.
7. Remove old PM approval examples after compatibility aliases exist.

## Adversarial Review Findings Incorporated

### Fake Safety

Risk: Users may still believe the system prevents conflicts.

Decision: Use advisory language everywhere. The product promise is risk
reduction and visibility, not prevention.

### Unreliable Human Detection

Risk: CLI cannot know whether a human is present.

Decision: CLI receives explicit `--human-in-loop`; skill/runtime owns that
judgment.

### Medium Conflict Degradation

Risk: Two autonomous agents may continue editing the same file.

Decision: Medium conflict may degrade only for reversible operations. High and
critical conflict pauses unless a project policy explicitly says otherwise.

### Approval Residue

Risk: Old command names and statuses keep the fake approval model alive.

Decision: Deprecate `request-approval`; rename statuses away from
approved/rejected.

### Notification Noise

Risk: Agents and humans ignore frequent overlap warnings.

Decision: Deduplicate nudges by task pair, overlap set, and severity.

### Claim Inaccuracy

Risk: Incomplete claims cause missed conflicts.

Decision: Add scope drift checks before commit, push, publish, destructive, and
human-gate operations.

### Broker Down

Risk: High-risk operations continue silently when notification fails.

Decision: Critical operations block unless current human confirms. Other
severity levels follow explicit degradation policy.

## Open Decisions Before Implementation

1. Command name: choose `human-gate` or `request-human-confirmation`.
2. Environment names: choose `GOVERNANCE_NOTIFY_TARGET`,
   `GOVERNANCE_HUMAN_TARGET`, or both.
3. Whether normal `git push` is medium by default or high by default.
4. Whether deprecated approval statuses remain accepted in logs for one
   compatibility window.
5. Where project configuration lives: `.governance.json` or CLI flags only.

Recommendation:

- Use `human-gate` for the command.
- Use both `GOVERNANCE_NOTIFY_TARGET` and `GOVERNANCE_HUMAN_TARGET`.
- Treat normal push as medium unless `pushTriggersDeploy` is configured.
- Accept deprecated statuses temporarily but never emit them in new flows.
- Store project policy in `.governance.json`.
