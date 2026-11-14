"""SSH execution-world evidence (X30): a real asyncssh loopback server proves
that ``SSHWorkspaceManager``'s exec and fs channels travel the SSH wire —
run/exec, SFTP read/write/list, and remote edit — without an external host.

This exercises exactly the tool-level execution world Atlas has today
(``ssh.py``): local_file/local_edit/local_exec/local_git proxy to the remote
host while the workspace URI stays ``ssh://<alias>/<abs-path>``. It does not
claim the DSH "move fs/subprocess/sandbox wholesale" target, which is absent.
"""

import asyncio
import time

import asyncssh
import pytest

from atlas.ssh import SSHWorkspaceManager, _Connection

pytestmark = pytest.mark.unit


async def _serve_remote_command(process: asyncssh.SSHServerProcess) -> None:
    """Exec handler: run the requested command on this host (loopback stand-in
    for the remote machine) and return its streams over the SSH channel."""
    proc = await asyncio.create_subprocess_shell(
        process.command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    process.stdout.write(out.decode("utf-8", "replace"))
    process.stderr.write(err.decode("utf-8", "replace"))
    process.exit(proc.returncode or 0)


class _LoopbackServer(asyncssh.SSHServer):
    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == "z6" and password == "z6"


class _ServerHarness:
    def __init__(self, tmp_path):
        self.root = tmp_path / "remote-root"
        self.root.mkdir(parents=True, exist_ok=True)
        self._key = asyncssh.generate_private_key("ssh-ed25519")
        self._acceptor = None
        self.client = None

    async def start(self):
        self._acceptor = await asyncssh.listen(
            "127.0.0.1", 0, server_host_keys=[self._key],
            server_factory=_LoopbackServer, process_factory=_serve_remote_command,
            sftp_factory=True, allow_scp=True,
        )
        listener = self._acceptor.sockets[0].getsockname()[1]
        self.client = await asyncssh.connect(
            "127.0.0.1", port=listener, known_hosts=None,
            username="z6", password="z6",
        )
        # Atlas keeps Windows SSH roots POSIX-style ("/C:/...", "/D:/...").
        self.workspace = f"ssh://z6looper/{self.root.as_posix()}"
        return self

    async def stop(self):
        if self.client is not None:
            self.client.close()
        if self._acceptor is not None:
            self._acceptor.close()
            await self._acceptor.wait_closed()


@pytest.fixture
async def ssh_world(tmp_path):
    harness = await _ServerHarness(tmp_path).start()
    try:
        yield harness
    finally:
        await harness.stop()


def _wired_manager(harness: _ServerHarness) -> SSHWorkspaceManager:
    """A manager whose connection pool is pre-wired to the loopback server."""
    mgr = SSHWorkspaceManager()

    async def _connect(_host: str) -> _Connection:
        return _Connection(client=harness.client, last_used=time.monotonic())

    mgr._connect = _connect  # noqa: SLF001 - test wiring of the private pool seam
    return mgr


async def test_ssh_exec_channel_and_os_probe(ssh_world):
    mgr = _wired_manager(ssh_world)
    host, root = mgr.parse_workspace(ssh_world.workspace)
    assert root.startswith("/") and root[2] == ":"

    result = await mgr.run_result(host, "echo %OS%")
    assert result["exit_code"] == 0
    assert "windows_nt" in result["stdout"].lower()

    probe = await mgr.test(host)
    assert probe["ok"] is True
    assert probe["os"] == "windows"


async def test_ssh_file_round_trip_over_sftp(ssh_world):
    mgr = _wired_manager(ssh_world)
    target = ssh_world.root / "notes" / "z6.txt"

    written = await mgr.call_tool("local_file", {
        "action": "write", "path": str(target), "content": "z6-ssh-evidence",
    }, ssh_world.workspace)
    assert written["is_error"] is False
    assert target.read_text(encoding="utf-8") == "z6-ssh-evidence"

    read = await mgr.call_tool("local_file", {
        "action": "read", "path": str(target),
    }, ssh_world.workspace)
    assert read["data"]["content"] == "z6-ssh-evidence"
    assert read["data"]["size"] == len("z6-ssh-evidence")

    listing = await mgr.call_tool("local_file", {
        "action": "list", "path": ssh_world.root,
    }, ssh_world.workspace)
    names = {entry["name"] for entry in listing["data"]["entries"]}
    assert "notes" in names


async def test_ssh_remote_exec_runs_in_workspace_root(ssh_world):
    mgr = _wired_manager(ssh_world)
    marker = ssh_world.root / "cwd-marker.txt"
    marker.write_text("", encoding="utf-8")

    outcome = await mgr.call_tool("local_exec", {
        "executable": "powershell",
        "args": ["-NoProfile", "-NonInteractive", "-Command",
                 "Get-ChildItem -Name | Set-Content cwd-listing.txt"],
        "cwd": str(ssh_world.root),
    }, ssh_world.workspace)
    assert outcome["is_error"] is False
    assert (ssh_world.root / "cwd-listing.txt").exists()


async def test_ssh_remote_edit_replaces_one_match_on_disk(ssh_world):
    mgr = _wired_manager(ssh_world)
    target = ssh_world.root / "editable.txt"
    target.write_text("before: z6-old\n", encoding="utf-8")

    edited = await mgr.call_tool("local_edit", {
        "path": str(target), "old_string": "z6-old", "new_string": "z6-new",
    }, ssh_world.workspace)
    assert edited["is_error"] is False
    assert target.read_text(encoding="utf-8") == "before: z6-new\n"

    # An ambiguous old_string must fail closed without touching the file.
    target.write_text("dup dup\n", encoding="utf-8")
    with pytest.raises(ValueError):
        await mgr.call_tool("local_edit", {
            "path": str(target), "old_string": "dup", "new_string": "x",
        }, ssh_world.workspace)
    assert target.read_text(encoding="utf-8") == "dup dup\n"
