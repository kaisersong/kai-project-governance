# Broker CLI Command Reference

## Basic operations

```bash
# Check who's online
intent-broker who

# Check your inbox
intent-broker inbox

# Send a non-interrupting note
intent-broker note <message>

# Send an interrupting task
intent-broker task <participant-alias> <message>

# Reply to a specific agent
intent-broker reply <participant-alias> <message>
```

## Claim-related commands

### Publish a claim

```bash
intent-broker note "$(python3 -c "
import json
from datetime import datetime, timedelta, timezone
claim = {
    'type': 'workspace_claim',
    'action': 'claim',
    'participantId': '$(hostname)-$$',
    'project': '$(basename $(git rev-parse --show-toplevel))',
    'files': ['src/main.py'],
    'directories': ['src/module/'],
    'mayAffect': ['src/types.py'],
    'taskId': 'task-$(date +%s)',
    'claimedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'expiresAt': (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'gitHead': '$(git rev-parse HEAD)'
}
print(json.dumps(claim))
")"
```

### Release a claim

```bash
intent-broker note "$(python3 -c "
import json
print(json.dumps({
    'type': 'workspace_claim',
    'action': 'release',
    'participantId': '$(hostname)-$$',
    'taskId': 'task-XXXXX'
}))
")"
```

## Approval commands

### Request PM approval

```bash
intent-broker task qoder "APPROVAL REQUEST
Agent: $(hostname)-$$
Project: $(basename $(git rev-parse --show-toplevel))
Phase: implementing
Files: $(git diff --name-only 2>/dev/null || echo 'N/A')
Conflicting agents: <agent-list>
git HEAD: $(git rev-parse HEAD)
Summary: <what you're about to do>"
```

### Respond to approval (PM side)

```bash
# Approve
intent-broker reply <agent-alias> "APPROVED: proceed with <summary>"

# Reject
intent-broker reply <agent-alias> "REJECTED: <reason>"
```

## Reading claims from local files

```bash
# List all active claims (not expired)
python3 -c "
import json, glob, os
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
for f in glob.glob('.governance-claims/*.json'):
    try:
        c = json.load(open(f))
        exp = datetime.fromisoformat(c['expiresAt'].replace('Z','+00:00'))
        if exp > now:
            print(f'{c[\"participantId\"]}: {c.get(\"files\",[])} + {c.get(\"directories\",[])}')
    except Exception as e:
        print(f'Error reading {f}: {e}', file=os.sys.stderr)
"
```

## Broker API reference

- Base URL: `http://127.0.0.1:4318`
- Send intent: `POST /intents`
- Fields: `kind`, `fromParticipantId`, `taskId`, `threadId`, `to`, `payload`
- Pull inbox: `GET /inbox/:participantId?after=0&limit=50`
- Ack messages: `POST /inbox/:participantId/ack`
- Approval respond: `POST /approvals/:approvalId/respond`
- Valid `kind` values: `request_approval`, `respond_approval`, `reply_message`
