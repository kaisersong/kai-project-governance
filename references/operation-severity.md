# Operation Severity Classification

Not all operations carry the same risk. Use this classification to decide how
cautious to be during governance checks.

## Severity levels

### Critical — Always check, never skip

Operations that can destroy data or affect the entire project:

- `git push --force` / `git reset --hard`
- Deleting files or directories (`rm`, `git rm`)
- Renaming files (`git mv`)
- Database migrations (forward and rollback)
- Modifying `package-lock.json`, `poetry.lock`, or similar lockfiles
- Changing CI/CD pipeline configuration
- Modifying `.env` or secrets files
- Branch deletion

### High — Check when other agents are active

Operations that affect shared state but are usually recoverable:

- `git push` (normal)
- `git merge` / `git rebase`
- Editing shared configuration files (`tsconfig.json`, `pyproject.toml`, etc.)
- Installing or removing dependencies
- Modifying shared type definitions or interfaces
- Changing API contracts

### Medium — Check only if file overlap detected

Normal development work that usually only affects the specific files being edited:

- Editing source code files
- Adding new files
- Modifying tests
- Updating documentation

### Low — No governance check needed

Read-only or local-only operations:

- Reading files
- Running tests locally
- Viewing git log / diff
- Searching codebase
- Building locally (no output artifacts committed)

## How severity affects the flow

| Severity | Human present | Autonomous, no conflict | Autonomous, conflict |
|----------|--------------|------------------------|---------------------|
| Critical | Show warning, proceed | PM approval required | PM approval required |
| High | Show info, proceed | Log and proceed | PM approval required |
| Medium | Proceed | Log and proceed | PM approval required |
| Low | Proceed | Proceed | Log and proceed |

Critical operations always get a warning, even when a human is present, because
their blast radius extends beyond the current agent's awareness.
