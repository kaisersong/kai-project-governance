# kai-project-governance

> When multiple AI agents edit the same codebase, they trample each other's work — silently. One agent refactors a module while another deletes it. A third pushes a commit that conflicts with two others. Nobody knows until something breaks. kai-project-governance is a **concurrency safety lint** that makes workspace claims visible and routes conflicts to a human decision-maker before damage happens.

A skill for [Claude Code](https://claude.ai/claude-code), [Codex CLI](https://github.com/openai/codex), [Antigravity](https://antigravity.dev), and multi-agent environments that prevents parallel agents from overwriting each other's changes.

English | [简体中文](README.zh-CN.md)

---

## How It Works

### Three-Tier Behavior Model

| Tier | Name | When | Behavior |
|------|------|------|----------|
| 1 (default) | **LINT** | Always active | Conflict detection + warning. Only blocks if conflict AND no human present. |
| 2 (always on) | **NOTIFY** | On every commit/push | Sends non-blocking notification to PM. Never blocks. |
| 3 (optional) | **GATE** | When `GOVERNANCE_MODE=gate` | Blocks on every commit/push, waits for PM approval. 120s timeout → degrade. |

### Three-Layer Check (Tier 1 Detail)

Before every controlled action (edit, commit, delete, deploy), the skill runs a three-layer check:

```
Action triggered → Human driving?
  → Yes → Show conflict info, proceed (human decides)
  → No  → Conflict with other agents?
    → No  → Proceed, log
    → Yes → Request PM approval (120s timeout → degrade)
```

**Layer 1 — Human in the loop.** If a human is actively driving the agent (last message < 5 min), show conflict warnings but don't block. The human is the governance.

**Layer 2 — Conflict detection.** Check `.governance-claims/` for active workspace claims from other agents. Compare files, directories, and `mayAffect` fields against the planned action.

**Layer 3 — PM approval.** If no human is present and a conflict exists, request approval from the PM via the intent broker. Timeout after 120 seconds degrades gracefully with logging.

### Workspace Claims

Each agent declares what it plans to work on:

```bash
python3 scripts/governance.py claim \
  --files src/main.py src/types.py \
  --dirs src/module/ \
  --may-affect src/shared/types.py
```

Other agents check before acting:

```bash
python3 scripts/governance.py check --files src/main.py
# → {"hasConflict": false, "activeClaims": 0}
```

Claims expire after 30 minutes (configurable). Agents renew every 10 minutes during long tasks.

### Publish-Release Rule

**Any external publish action** — `git push`, `gh release create`, `git tag`,
`clawhub publish` — must notify PM first (tier 2), and must request approval in
gate mode (tier 3). This applies even if no conflict is detected.

### What It Doesn't Do

This is a **cooperative lint, not a hard lock**. Agents that don't run the skill can still edit files. For hard enforcement, use git hooks, CI branch protection, or file permissions — those are different layers.

---

## Install

### Claude Code

```bash
ln -s /path/to/kai-project-governance ~/.claude/skills/kai-project-governance
```

### Codex CLI

```bash
ln -s /path/to/kai-project-governance ~/.codex/skills/kai-project-governance
```

### Antigravity (agy)

```bash
ln -s /path/to/kai-project-governance ~/.gemini/skills/kai-project-governance
```

### Other agents

```bash
ln -s /path/to/kai-project-governance ~/.agents/skills/kai-project-governance
```

Restart the agent after installation.

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `governance.py claim --files ...` | Claim workspace files/directories |
| `governance.py check --files ...` | Check for conflicts before acting |
| `governance.py renew [--ttl N]` | Renew your active claim |
| `governance.py expand --files ...` | Expand claim scope mid-task |
| `governance.py release` | Release your workspace claim |
| `governance.py notify --phase ...` | **Tier 2**: Non-blocking notification to PM |
| `governance.py request-approval --phase ...` | **Tier 3**: Blocking approval request (gate mode) |
| `governance.py log --phase ... --status ...` | Log a governance action |
| `governance.py cleanup` | Remove expired/malformed claims |
| `governance.py status` | Show current governance state |

All commands require being inside a git repository. Agent identity is set via `GOVERNANCE_AGENT_ID` env var. PM identity is set via `GOVERNANCE_PM_ID` (default: `qodercli-session-f782cff3`). Broker URL via `BROKER_URL` (default: `http://127.0.0.1:4318`).

### Gate Mode Pre-Push Hook

Install to automatically block `git push` in gate mode until PM approves:

```bash
ln -s /path/to/kai-project-governance/scripts/pre-push.sh .git/hooks/pre-push
```

The hook checks `GOVERNANCE_MODE` — if set to `gate`, it calls `request-approval`
before allowing the push to proceed.

---

## Controlled Nodes

| Node | When | Severity |
|------|------|----------|
| Planning | Before writing plan files | Medium |
| Implementing | Before editing source files | Medium |
| Destructive | Before deleting/renaming/moving files | Critical |
| Committing | Before `git commit` / `git push` | High |
| Configuring | Before changing config/deps/env files | High |
| Verifying | Before deploy/release operations | High |

Critical operations always show a warning, even when a human is driving.

---

## Architecture

```
kai-project-governance/
├── SKILL.md                    # Routing layer: trigger + governance flow
├── scripts/
│   ├── governance.py           # Deterministic CLI
│   └── run_evals.py            # Eval runner with rubric scoring
├── references/
│   ├── workspace-claims.md     # Claim protocol + race mitigation
│   ├── pm-governance.md        # PM workflow
│   ├── broker-commands.md      # Intent broker CLI reference
│   └── operation-severity.md   # Operation severity classification
├── evals/
│   ├── eval-cases.json         # 12 eval cases
│   ├── contract_checks.py      # Claim/log/path validation
│   ├── rubric.schema.json      # Scoring dimensions
│   ├── failure-map.md          # Where to fix when evals fail
│   └── baseline-report.json   # Baseline: 12/12 PASS, 100%
└── tests/
    ├── test_contract_checks.py # 43 unit tests
    ├── test_governance_cli.py  # 20 integration tests
    ├── test_reference_integrity.py # 5 integrity tests
    └── test_skill_size.py      # 1 budget test
```

---

## Eval Framework

```bash
python3 scripts/run_evals.py
```

Baseline: **12/12 PASS, 100%, all scores 5.0/5.0**

| Dimension | What it checks |
|-----------|---------------|
| claim_protocol | Claim created with correct fields, stored locally, broadcast via broker |
| conflict_detection | Conflicts identified across files, directories, and mayAffect |
| degradation_handling | Broker-down and PM-timeout handled with correct fallback |
| log_integrity | Log entries have correct schema, valid phases, valid statuses |

Unit tests: `pytest tests/ -v` — 71 tests, all passing.

---

## Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Three-tier model | LINT + NOTIFY + GATE | Default is non-blocking; gate is opt-in for strict enforcement |
| Publish-release rule | All push/release/tag must notify PM | Clean push is still a governance event |
| Cooperative, not enforced | Accepted | Hard enforcement belongs in git hooks / CI |
| File-level granularity | Accepted | Function-level is too expensive; false positives > false negatives |
| 120s PM timeout → degrade | Accepted | Never block the entire development flow |
| Human-in-loop shows warnings | Accepted | Human gets info but isn't blocked |
| Local claim files as truth | Chosen | Broker inbox is not a reliable state store |
| JSONL per-agent logs | Chosen | Avoids concurrent-write corruption |

### Known Limitations

1. **Non-atomic claims** — Two agents can claim the same files simultaneously. 5-second observation window mitigates.
2. **Scope drift** — Agent discovers it needs more files. Incremental expansion mitigates.
3. **PM single point** — Batch approval reduces fatigue.
4. **File-level conflicts only** — Same-file different-function edits trigger false warnings.
5. **Clock skew** — `expiresAt` uses agent local time. Impact is minimal.

---

## Compatibility

| Platform | Install path |
|----------|-------------|
| Claude Code | `~/.claude/skills/kai-project-governance/` |
| Codex CLI | `~/.codex/skills/kai-project-governance/` |
| Antigravity (agy) | `~/.gemini/skills/kai-project-governance/` |
| Generic agents | `~/.agents/skills/kai-project-governance/` |
