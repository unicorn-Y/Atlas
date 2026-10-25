# Self-hosted SSH tasks

Atlas does not provide a hosted cloud executor. The self-hosted task transport reuses the existing `SSHWorkspaceManager` and the user's OpenSSH configuration; no Atlas agent, SSH password, or private key is installed on the target machine.

## Host and credential setup

Add one exact host alias to the local user's `~/.ssh/config` (Windows: `%USERPROFILE%\.ssh\config`):

```sshconfig
Host atlas-gaming-pc
    HostName 100.88.12.34
    Port 22
    User atlas
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

`HostName` may be a ZeroTier IP or a LAN hostname/address. Keep the private key on the Atlas machine and use OpenSSH `known_hosts` verification. First connect with `ssh atlas-gaming-pc` from a terminal and accept/verify the target host key there. Atlas uses that alias and its configured `Port`, `User`, `IdentityFile`, agent, and known-hosts database. Atlas stores no key or password. Target account permissions are the effective execution permissions; use an OS account and workspace appropriate for the jobs you plan to submit.

In **Settings → Tasks and Integrations → Self-hosted remote tasks**, select the alias, set `ssh://atlas-gaming-pc/absolute/path/to/repository`, add optional environment tags, and save. `Test SSH` verifies connectivity and remote OS. The repository and Web Setup URL fields are local environment metadata; the repository link opens GitHub, while Web Setup opens the configured HTTP(S) page. `setup_command` is a shell command run through the same task queue.

## Execution protocol and records

The local HTTP interface is `/api/remote-tasks`: environment list/filter and save; task submit/list/status/cancel/retry; snapshot save/list; and attempt patch apply. A task carries its environment alias, absolute remote workspace, command, optional UTC run time/interval, and optional session snapshot ID. Atlas connects with the existing SSH manager, runs `cd <workspace> && <command>` on POSIX hosts (or the existing PowerShell SSH adapter on Windows), and records a distinct attempt ID, start/end time, exit code, bounded stdout/stderr, and `git diff --no-ext-diff --binary HEAD`. The JSON state is local at `data/remote-tasks.json`; it contains environment/task metadata, logs, diffs, and user-selected session snapshots, never SSH credentials.

Scheduled runs are dispatched by the local Atlas backend and survive closing the renderer. The backend must remain running and able to reach the target at run time. The scheduler is not installed on the remote host, so shutting down the local Atlas backend pauses due work until it starts again. This is the self-hosted counterpart to hosted offline scheduling, with that operational boundary made explicit.

A session snapshot records the latest 80 user/assistant messages, workspace URI, Git status, and a bounded binary patch relative to `HEAD`. It stays in the local Atlas data directory and excludes private keys, Atlas provider credentials, and machine settings. A task may link a snapshot ID as migration history. Commands execute as the selected SSH user in the configured workspace; the system does not add an approval gate or alter OS permissions. After an attempt, inspect its log and diff in the UI, then apply the patch to a chosen local Git repository; Atlas runs `git apply --check` before `git apply`.

## API example

```json
{
  "environment": "atlas-gaming-pc",
  "command": "git status --short && pytest -q",
  "scheduled_at": "2026-10-25T14:00:00Z",
  "interval_seconds": 0,
  "session_snapshot_id": ""
}
```

Task commands and setup commands run with the remote OS account's normal permissions. Keep secret values in the remote machine's own environment/configuration and reference variable names in commands; do not paste secret values into task commands or URLs.
