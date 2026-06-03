# PM Governance Workflow

## Your role as PM

You are the human decision-maker when autonomous agents detect conflicts. Agents
send you approval requests when they want to edit files that another agent has
already claimed.

## Checking approval requests

```bash
# Check your inbox for approval requests
intent-broker inbox
```

Look for messages with `request_approval` type. Each request contains:

- **Agent**: which agent is requesting
- **Project**: which project
- **Phase**: planning / implementing / destructive / committing / configuring / verifying
- **Files**: what they want to change
- **Conflicting agents**: who else is touching the same files
- **git HEAD**: the commit they're basing their work on
- **Action summary**: what they plan to do

## Approving or rejecting

```bash
# Approve
intent-broker reply <agent-id> "Approved. Proceed with <files>."

# Reject with reason
intent-broker reply <agent-id> "Rejected: <reason>. Please <alternative action>."
```

## Batch approval

When you have multiple requests and some don't actually conflict with each other:

1. Check the `git HEAD` of each request — they might be based on different states.
2. Group requests by project.
3. Within each project, check file overlap between requests.
4. Approve all non-overlapping requests at once.

```bash
# Approve multiple non-conflicting requests
intent-broker reply agent-a "Approved."
intent-broker reply agent-b "Approved."
```

## Reviewing degraded events

When agents proceeded without your approval (timeout or broker down), they log
these as `DEGRADED_CONFLICT` events. When you come back online:

1. Check your inbox for degradation notifications.
2. These are flagged differently from normal events — they represent decisions
   made without your input.
3. For each degraded event:
   - If no actual conflict occurred → acknowledge, no action needed.
   - If a conflict occurred → mark as incident, notify the involved agents.
4. You do not need to roll back or undo — just review and flag if needed.

## Sanity checks before approving

- **git HEAD changed?** If the agent's `git HEAD` is old, the approval might be
  stale. Ask the agent to rebase first.
- **Scope drift?** If the files listed don't match what you expect from the task,
  ask for clarification.
- **Actually conflicting?** Sometimes the overlap is in `mayAffect` (indirect)
  rather than `files` (direct). Indirect conflicts are lower risk.
