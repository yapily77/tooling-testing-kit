## Issue Tracking

This project uses **bd (beads)** for issue tracking.
Run \`bd prime\` for workflow context, or install hooks (\`bd hooks install\`) for auto-injection.

**Quick reference:**
- \`bd ready\` - Find unblocked work
- \`bd create "Title" --type task --priority 2\` - Create issue
- \`bd close <id>\` - Complete work
- \`bd dolt push\` - Push beads to remote

For full workflow details: `bd prime`

## Code Quality

**Hygiene & linting:** `ruff` is the configured linter/formatter (see `README.md` badge + `[tool.ruff]` in `pyproject.toml`). Static analysis lives under `hygiene/` — see `hygiene/README.md` and `hygiene/GUIDE.md`. Daily scans are driven by `hygiene/daily/`.

**Tests:** pytest 9.1.1, configured via `[tool.pytest.ini_options]` in `pyproject.toml`.
```bash
.venv/bin/python -m pytest                 # run everything
.venv/bin/python -m pytest tests/08_static_gates   # single suite
.venv/bin/python -m pytest -x -q           # fail fast, concise
.venv/bin/python -m pytest --lf            # re-run last failures only
```
Test discovery spans `tests/examples` and `tools/test` (see `pyproject.toml` `testpaths`). The `tests/` tree is bucketed by purpose (01-gold snapshots, 02-unit, 05-e2e, 08-static gates, etc.).

**Tools:** Most dev tooling is its own package under `tools/` (AST refactorings, RAG pipeline `tools/rag/` using Pydantic-AI, symbol queries, knowledge graph). Each sub-tool has its own entry module; run `.venv/bin/python tools/<tool>.py --help`. A shared harness lives in `tools/_codebase_common.py`. OpenCode plugin wrappers live in `plugins/opencode/` — `clean_python.ts` and `clean_ts.ts` for Python/TS quality gates.

## Modules

| Area        | Path           | Notes                                                       |
|-------------|----------------|-------------------------------------------------------------|
| Core src    | `src/`         | `interfaces/` — public module surface                       |
| Dev tools   | `tools/`       | AST refactorings, RAG pipeline (`tools/rag/`), symbol queries; `tools/pyproject.toml` may declare own deps |
| Hygiene     | `hygiene/`     | Hybrid static AST + LLM (Pydantic-AI) technical debt scanners + daily automation |
| Plugins     | `plugins/`     | OpenCode tool wrappers (`clean_python.ts`, `clean_ts.ts`) for Python/TS quality gates |
| Demo        | `demo/`        | Case studies: `opencode/python/` + `opencode/typescript/` + `scripts/` |
| Tests       | `tests/`       | Bucketed suites; `tests/08_static_gates` for quality gates  |
| Examples    | `examples/`    | Sample targets + scanner output samples                     |
| Issues      | `.beads/`      | Local Dolt DB + JSONL export; run `bd prime` / `bd ready`   |

## Issue Tracking

Always use `bd` — do **not** write markdown TODO lists.

```bash
bd ready                       # work available now
bd show <id>                   # inspect an issue
bd create "Title" --type task  # new work item
bd update <id> --claim         # claim it
bd close <id>                  # finish + archive
bd remember "key — note"       # persist project memory
bd dolt push                   # sync beads to remote
```

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
