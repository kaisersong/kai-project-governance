#!/bin/bash
# Pre-push hook — always requests PM approval when PM is online,
# leaves a directed progress note when PM is offline.
# No lint fallback.
#
# Install: ln -s <project>/scripts/pre-push.sh .git/hooks/pre-push

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Try sibling scripts/ first, then project root
GOV_SCRIPT="$SCRIPT_DIR/governance.py"
if [ ! -f "$GOV_SCRIPT" ]; then
    GOV_SCRIPT="$(git rev-parse --show-toplevel 2>/dev/null)/scripts/governance.py"
fi
if [ ! -f "$GOV_SCRIPT" ]; then
    echo "[governance] governance.py not found, allowing push"
    exit 0
fi

FILES=$(git diff --name-only HEAD @{upstream} 2>/dev/null || git diff --name-only HEAD HEAD~1 2>/dev/null || echo "")
HEAD=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

# Check if PM is online via broker presence
BROKER_URL="${BROKER_URL:-http://127.0.0.1:4318}"
PM_ONLINE=false
PM_ID=""

# Try to find governance-pm participant and check presence
PM_QUERY=$(curl -s --max-time 3 "$BROKER_URL/participants?role=governance-pm" 2>/dev/null || echo "")
if [ -n "$PM_QUERY" ]; then
    PM_ID=$(echo "$PM_QUERY" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for p in data.get('participants', []):
        pid = p.get('participantId', '')
        if pid:
            print(pid)
            break
except: pass
" 2>/dev/null)

    if [ -n "$PM_ID" ]; then
        PM_STATUS=$(curl -s --max-time 3 "$BROKER_URL/presence/$PM_ID" 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('status', 'offline'))
except: print('offline')
" 2>/dev/null)
        if [ "$PM_STATUS" = "online" ]; then
            PM_ONLINE=true
        fi
    fi
fi

if [ "$PM_ONLINE" = true ]; then
    # PM is online — must get approval
    echo "[governance] PM is online, requesting approval..."
    python3 "$GOV_SCRIPT" request-approval \
        --phase committing \
        --files $FILES \
        --git-head "$HEAD" \
        --summary "git push: $FILES"
    RESULT=$?
    if [ $RESULT -ne 0 ]; then
        echo "[governance] BLOCKED: PM rejected or request failed"
        exit 1
    fi
    echo "[governance] APPROVED: proceeding with push"
else
    # PM is offline — directed progress note, then allow
    echo "[governance] PM is offline, leaving progress note..."
    python3 "$GOV_SCRIPT" notify \
        --phase committing \
        --files $FILES \
        --git-head "$HEAD" \
        --summary "git push (PM offline): $FILES" 2>&1
fi

exit 0
