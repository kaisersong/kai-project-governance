#!/bin/bash
# Pre-push hook for GOVERNANCE_MODE=gate
# Install: ln -s <project>/scripts/pre-push.sh .git/hooks/pre-push
#
# In gate mode, blocks git push until PM approval is obtained.
# Uses governance.py request-approval under the hood.
# If GOVERNANCE_MODE != gate, this hook does nothing.

set -e

GOVERNANCE_MODE="${GOVERNANCE_MODE:-lint}"

if [ "$GOVERNANCE_MODE" != "gate" ]; then
    echo "[governance] gate mode not active, allowing push"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")/../scripts" && pwd)"
GOV_SCRIPT="$SCRIPT_DIR/governance.py"

if [ ! -f "$GOV_SCRIPT" ]; then
    # Try project root
    GOV_SCRIPT="$(git rev-parse --show-toplevel)/scripts/governance.py"
fi

if [ ! -f "$GOV_SCRIPT" ]; then
    echo "[governance] WARNING: governance.py not found, allowing push"
    exit 0
fi

FILES=$(git diff --name-only HEAD @{upstream} 2>/dev/null || git diff --name-only HEAD HEAD~1 2>/dev/null || echo "")
HEAD=$(git rev-parse HEAD)

echo "[governance] GATE MODE: requesting PM approval before push..."
echo "[governance] Files: $FILES"
echo "[governance] HEAD: $HEAD"

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
exit 0
