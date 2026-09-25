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
