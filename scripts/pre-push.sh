#!/bin/bash
# Pre-push hook — automatically notifies PM on every push (Tier 2),
# and optionally blocks for PM approval in gate mode (Tier 3).
#
# Install: ln -s <project>/scripts/pre-push.sh .git/hooks/pre-push

GOVERNANCE_MODE="${GOVERNANCE_MODE:-lint}"

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

# ===== Tier 2 (always on): notify PM =====
echo "[governance] notifying PM before push..."
python3 "$GOV_SCRIPT" notify \
    --phase committing \
    --files $FILES \
    --git-head "$HEAD" \
    --summary "git push: $FILES" 2>&1

# ===== Tier 3 (opt-in): block until PM approves =====
if [ "$GOVERNANCE_MODE" = "gate" ]; then
    echo "[governance] GATE MODE: requesting PM approval..."
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
fi

# Allow push to proceed
exit 0
