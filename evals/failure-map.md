# Governance Eval Failure Map

When a governance eval case fails, use this map to find the right fix.

## 1. Claim Protocol

- Typical failures:
  - Claim JSON missing required fields (participantId, taskId, etc.)
  - Path not normalized (absolute path, `./` prefix, backslashes)
  - Claim not written to `.governance-claims/` local file
  - Claim not broadcast via `intent-broker note`
  - TTL outside reasonable range (5-120 minutes)
- Fix here:
  - [SKILL.md](../SKILL.md) — Step 1
  - [references/workspace-claims.md](../references/workspace-claims.md)
  - [evals/contract_checks.py](contract_checks.py) — `validate_claim_json`, `validate_path_normalized`

## 2. Conflict Detection

- Typical failures:
  - File overlap not detected against `files` field
  - Directory overlap not detected (agent claims `src/foo/`, other touches `src/foo/bar.py`)
  - `mayAffect` field not included in overlap check
  - Expired claims still treated as active
  - Claim from same agent counted as self-conflict
- Fix here:
  - [SKILL.md](../SKILL.md) — Step 3
  - [evals/contract_checks.py](contract_checks.py) — `find_conflicts`
  - [references/workspace-claims.md](../references/workspace-claims.md)

## 3. Degradation Handling

- Typical failures:
  - PM timeout not logged as `DEGRADED_CONFLICT`
  - Broker-down path doesn't check local claim files
  - Broker-down with local conflicts doesn't pause
  - Human-in-loop completely skips conflict display (should show warning)
- Fix here:
  - [SKILL.md](../SKILL.md) — Step 4
  - [references/pm-governance.md](../references/pm-governance.md)
  - [references/operation-severity.md](../references/operation-severity.md)

## 4. Log Integrity

- Typical failures:
  - Log entry missing required fields
  - Invalid `phase` value (not one of the 6 controlled nodes)
  - Invalid `approvalStatus` value
  - Timestamp not ISO 8601
  - Log written to shared file instead of per-agent JSONL
- Fix here:
  - [SKILL.md](../SKILL.md) — Step 5
  - [evals/contract_checks.py](contract_checks.py) — `validate_log_entry`

## Operating Rule

Every real production failure (a conflict that wasn't caught, a log that was
corrupted, a claim that was ignored) should become one new case in
[evals/governance-cases.csv](governance-cases.csv).
