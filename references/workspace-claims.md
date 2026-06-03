# Workspace Claims Protocol

## Overview

Workspace claims are how agents declare what files they plan to work on. Other
agents check these claims before starting their own work to detect conflicts.

Claims are stored in **two places**:
1. **Local file** (authoritative): `.governance-claims/<agent-id>.json` in the project root
2. **Broker broadcast** (notification): sent via `intent-broker note` so other agents see it immediately

The local file is the source of truth for queries. The broker broadcast is just
a faster notification channel — if an agent misses the broadcast, it can still
read the local file.

## Claim JSON schema

```json
{
  "type": "workspace_claim",
  "action": "claim",
  "participantId": "xiaok-session-abc123",
  "project": "mojing",
  "files": [
    "Sources/UI/MenuBar/MenuBarController.swift"
  ],
  "directories": [
    "Sources/Gesture/"
  ],
  "mayAffect": [
    "Sources/Shared/HandTypes.swift",
    "Tests/GestureTests/GestureDetectorTests.swift"
  ],
  "taskId": "task-1748960000",
  "claimedAt": "2026-06-03T10:00:00Z",
  "expiresAt": "2026-06-03T10:30:00Z",
  "gitHead": "abc123def456"
}
```

### Field definitions

| Field | Required | Description |
|-------|----------|-------------|
| `type` | yes | Always `workspace_claim` |
| `action` | yes | `claim`, `release`, or `renew` |
| `participantId` | yes | Your agent's unique session ID |
| `project` | yes | `basename` of the git repo root |
| `files` | no | Specific files you will edit |
| `directories` | no | Directories you will work within |
| `mayAffect` | no | Files you might indirectly touch (imports, shared types, tests) |
| `taskId` | yes | Unique ID for this task (used for race-condition priority) |
| `claimedAt` | yes | ISO 8601 timestamp when claim was created |
| `expiresAt` | yes | ISO 8601 timestamp when claim becomes stale |
| `gitHead` | yes | Current git HEAD at claim time |

## Path normalization

All file paths must be **relative to the git repo root**, with no leading `./`,
no trailing slashes on directories, and resolved through realpath for symlinks.

```bash
# Get the repo root
REPO_ROOT=$(git rev-parse --show-toplevel)

# Normalize a path
normalize_path() {
  local p="$1"
  # Resolve to absolute, then strip repo root prefix
  local abs=$(cd "$(dirname "$p")" && pwd)/$(basename "$p")
  echo "${abs#$REPO_ROOT/}"
}
```

## Race-condition mitigation

Claims are not atomic — two agents can simultaneously read "no active claims"
and both publish. The mitigation is a **5-second observation window**:

1. Publish your claim.
2. Wait 5 seconds.
3. Re-read all claims in `.governance-claims/`.
4. If another agent claimed overlapping files during the window:
   - Compare `taskId` values — the lexicographically smaller one gets priority.
   - If you lose: wait for the other agent to release, or adjust your scope.
5. If no overlap detected → proceed.

This doesn't eliminate races entirely, but in practice the 5-second window
covers the vast majority of cases since agents don't start editing instantly.

## Claim renewal

Long-running tasks must renew their claims every 10 minutes to prevent stale
claims from blocking others.

```bash
# Update expiresAt to 30 minutes from now
CURRENT=$(cat .governance-claims/<your-agent-id>.json)
UPDATED=$(echo "$CURRENT" | python3 -c "
import sys, json
from datetime import datetime, timedelta, timezone
c = json.load(sys.stdin)
c['expiresAt'] = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
json.dump(c, sys.stdout)
")
echo "$UPDATED" > .governance-claims/<your-agent-id>.json
intent-broker note "$UPDATED"
```

If renewal fails (broker down, disk full), the claim will expire after its
original TTL. Other agents will then be free to claim the workspace. This is
acceptable — the claim is advisory, not a lock.

## Claim scope expansion

When you discover your task needs to touch more files than initially claimed:

```bash
# Read current claim
CURRENT=$(cat .governance-claims/<your-agent-id>.json)

# Add new files to the arrays
UPDATED=$(echo "$CURRENT" | python3 -c "
import sys, json
c = json.load(sys.stdin)
new_files = sys.argv[1:]
c['files'] = sorted(set(c.get('files', []) + new_files))
json.dump(c, sys.stdout)
" "path/to/new/file.py")

echo "$UPDATED" > .governance-claims/<your-agent-id>.json
intent-broker note "$UPDATED"
```

Always expand proactively — don't wait for a conflict to update your claim.

## Claim release

When your task completes or you abandon it:

```bash
# Remove local claim file
rm .governance-claims/<your-agent-id>.json

# Broadcast release
intent-broker note "{\"type\":\"workspace_claim\",\"action\":\"release\",\"participantId\":\"<your-agent-id>\",\"taskId\":\"<your-task-id>\"}"
```

Only the agent that created a claim can release it (verified by `participantId`).
If you see a release message with a different `participantId` than the claim
owner, ignore it.

## Claim expiry

Claims with `expiresAt` in the past are considered stale. When reading claims:

```bash
# Filter to only active claims
python3 -c "
import json, glob, os
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
for f in glob.glob('.governance-claims/*.json'):
    try:
        c = json.load(open(f))
        expires = datetime.fromisoformat(c['expiresAt'].replace('Z', '+00:00'))
        if expires > now:
            print(json.dumps(c))
    except:
        pass
"
```

Suggested TTL: 30 minutes. Adjust based on your project's typical task duration.
