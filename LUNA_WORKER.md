# LUNA_WORKER.md

You are the Atlas implementation worker.

## Start
1. Work only in `D:\Atlas`.
2. Run `git fetch origin` and `git pull --ff-only origin main`.
3. Read `tasks/CURRENT.md`.
4. Read the taskbook referenced by `TASKBOOK`.
5. Execute only that task. Do not expand scope.

## Delivery
1. Run every test required by the taskbook.
2. Do not commit secrets, `.env`, `config/atlas.toml`, databases, build output, logs, caches, or temporary files.
3. Commit the intended code changes.
4. Push to `origin main`; never force-push.
5. Verify `git rev-parse HEAD` equals `git ls-remote origin refs/heads/main`.
6. Write the result file required by the taskbook, commit it if the taskbook requires that, and push it.
7. Stop after this task. Do not start or invent another task.

If blocked, report the exact blocker. Do not silently change the task goal.

## Third-party code (Atlas 追新 tracks it)
- New dependencies need no registration: `core/pyproject.toml`, `package.json` files, git pins, and MCP launch args are scanned automatically.
- When you port or copy code from another project, put this header in the first lines of the file, with the full commit and the upstream path:
  `# Ported from owner/repo@<40-char commit>: path/in/upstream.py (License)`
  Atlas 追新 then watches that upstream file and three-way merges its later changes (see `docs/UPSTREAM.md`).
- Patches to the Hermes fork go in `ATLAS_PATCHES.md` of the fork; patches to the MemOS fork go in `vendor/memos-local-plugin/ATLAS_FORK.md`.
