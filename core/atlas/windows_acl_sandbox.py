"""Windows write-restricted sandbox: a real filesystem boundary per tool call.

`windows_job_sandbox` states its own limit: a Job Object contains the process
tree and enforces resource limits, but it is not a filesystem ACL, so a command
that already knows an absolute path can still write there. DSH closes that hole
with a write-restricted token plus a capability SID that is the only identity
allowed to write the workspace.

This module is that layer:

1. mint a random capability SID (``S-1-5-21-...``) for one call,
2. derive the caller's own primary token into a restricted token with
   ``WRITE_RESTRICTED`` and a restricting list of Everyone + the caller's logon
   SID + the capability SID,
3. append the boundary ACEs to exactly the roots that call may write, keeping the
   previous DACL so it can be put back byte for byte afterwards:
   the capability SID gets read/write/execute, the caller's logon SID gets
   read/execute (a protected DACL that names neither the user nor Everyone would
   otherwise leave the child unable to list the workspace), and the user SID gets
   full control only when the caller can already write there — measured by a real
   create+delete, so it can never widen access,
4. launch the child through ``CreateProcessAsUserW`` with that token and with
   TMP/TEMP pointed at a private scratch directory, so the shared real ``%TEMP%``
   never has to be opened for write,
5. remove the temporary ACEs when the call ends, whether it succeeded or not.

A restricted token intersects the restricting SIDs with the normal ones, so a
write needs both lists to agree: opening the real ``%TEMP%`` or another program's
directory stays denied even though the caller owns it, which is exactly the
boundary a container would give.

The result carries ``enforced`` so no caller can mistake this for the Job Object
path or for a Docker boundary.
"""

from __future__ import annotations

import ctypes
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes as wt
from dataclasses import dataclass, field

__all__ = [
    "AclSandboxUnavailable",
    "AclSandboxResult",
    "acl_available",
    "run_in_acl_sandbox",
]

IS_WINDOWS = sys.platform == "win32"

# --- Win32 constants -------------------------------------------------------

TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_ADJUST_SESSIONID = 0x0100
TOKEN_ALL_ACCESS_FOR_DERIVE = (
    TOKEN_ASSIGN_PRIMARY
    | TOKEN_DUPLICATE
    | TOKEN_QUERY
    | TOKEN_ADJUST_DEFAULT
    | TOKEN_ADJUST_SESSIONID
)

DISABLE_MAX_PRIVILEGE = 0x0001
WRITE_RESTRICTED = 0x0008

TokenUser = 1
TokenGroups = 2
SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x00000004
UNPROTECTED_DACL_SECURITY_INFORMATION = 0x20000000
PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
SE_DACL_PROTECTED = 0x1000

# Own the entry and read/write/execute it, but never WRITE_DAC or WRITE_OWNER:
# a sandboxed child must not be able to widen its own boundary.
FILE_SANDBOX_ALL = 0x001301FF
FILE_READ_EXECUTE = 0x001200A9
GRANT_ACCESS = 1
TRUSTEE_IS_SID = 0
TRUSTEE_IS_UNKNOWN = 0
SUB_CONTAINERS_AND_OBJECTS_INHERIT = 0x03

STARTF_USESTDHANDLES = 0x00000100
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0
CREATE_NO_WINDOW = 0x08000000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
INFINITE = 0xFFFFFFFF
HANDLE_FLAG_INHERIT = 0x00000001
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
WAIT_TIMEOUT_CODE = 0x102
STILL_ACTIVE = 259


#: One lock per manipulated root. Two concurrent calls must not interleave
#: "add my ACE" with "put the old DACL back", or one silently erases the other's
#: write grant mid-run.
_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(root: str) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(root))
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PATH_LOCKS[key] = lock
        return lock


class AclSandboxUnavailable(RuntimeError):
    """This host cannot provide the write-restricted boundary."""


@dataclass(frozen=True)
class AclSandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    enforced: bool
    mode: str
    capability_sid: str
    writable_roots: tuple[str, ...]
    acl_roots_restored: bool
    detail: str = ""

    def as_payload(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "enforced": self.enforced,
            "mode": self.mode,
            "capability_sid": self.capability_sid,
            "writable_roots": list(self.writable_roots),
            "acl_roots_restored": self.acl_roots_restored,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "detail": self.detail,
        }


# --- ctypes plumbing -------------------------------------------------------

if IS_WINDOWS:  # pragma: no cover - import-time platform guard
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    class _SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]

    class _GENERIC_MAPPING(ctypes.Structure):
        _fields_ = [
            ("GenericRead", wt.DWORD),
            ("GenericWrite", wt.DWORD),
            ("GenericExecute", wt.DWORD),
            ("GenericAll", wt.DWORD),
        ]

    class _PRIVILEGE_SET(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wt.DWORD), ("Control", wt.DWORD),
                    ("Privilege", ctypes.c_void_p * 1)]

    class _TRUSTEE_W(ctypes.Structure):
        _fields_ = [
            ("pMultipleTrustee", ctypes.c_void_p),
            ("MultipleTrusteeOperation", ctypes.c_int),
            ("TrusteeForm", ctypes.c_int),
            ("TrusteeType", ctypes.c_int),
            ("ptstrName", ctypes.c_void_p),
        ]

    class _EXPLICIT_ACCESS_W(ctypes.Structure):
        _fields_ = [
            ("grfAccessPermissions", wt.DWORD),
            ("grfAccessMode", ctypes.c_int),
            ("grfInheritance", wt.DWORD),
            ("Trustee", _TRUSTEE_W),
        ]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wt.DWORD),
            ("lpReserved", wt.LPWSTR),
            ("lpDesktop", wt.LPWSTR),
            ("lpTitle", wt.LPWSTR),
            ("dwX", wt.DWORD),
            ("dwY", wt.DWORD),
            ("dwXSize", wt.DWORD),
            ("dwYSize", wt.DWORD),
            ("dwXCountChars", wt.DWORD),
            ("dwYCountChars", wt.DWORD),
            ("dwFillAttribute", wt.DWORD),
            ("dwFlags", wt.DWORD),
            ("wShowWindow", wt.WORD),
            ("cbReserved2", wt.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wt.HANDLE),
            ("hStdOutput", wt.HANDLE),
            ("hStdError", wt.HANDLE),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wt.HANDLE),
            ("hThread", wt.HANDLE),
            ("dwProcessId", wt.DWORD),
            ("dwThreadId", wt.DWORD),
        ]

    _kernel32.GetCurrentProcess.restype = wt.HANDLE
    _kernel32.CloseHandle.argtypes = [wt.HANDLE]
    _kernel32.CloseHandle.restype = wt.BOOL
    _kernel32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    _kernel32.OpenProcessToken.restype = wt.BOOL
    _advapi32.CreateRestrictedToken.argtypes = [
        wt.HANDLE,
        wt.DWORD,
        wt.DWORD,
        ctypes.POINTER(_SID_AND_ATTRIBUTES),
        wt.DWORD,
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.POINTER(_SID_AND_ATTRIBUTES),
        ctypes.POINTER(wt.HANDLE),
    ]
    _advapi32.CreateRestrictedToken.restype = wt.BOOL
    _advapi32.CreateProcessAsUserW.argtypes = [
        wt.HANDLE,
        wt.LPWSTR,
        wt.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wt.BOOL,
        wt.DWORD,
        ctypes.c_void_p,
        wt.LPWSTR,
        ctypes.POINTER(_STARTUPINFOW),
        ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    _advapi32.CreateProcessAsUserW.restype = wt.BOOL
    _kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    _kernel32.WaitForSingleObject.restype = wt.DWORD
    _kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    _kernel32.GetExitCodeProcess.restype = wt.BOOL
    _kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    _kernel32.TerminateProcess.restype = wt.BOOL
    _kernel32.SetHandleInformation.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD]
    _kernel32.SetHandleInformation.restype = wt.BOOL
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wt.HANDLE
    _kernel32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wt.BOOL
    _kernel32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
    _kernel32.TerminateJobObject.restype = wt.BOOL

    _advapi32.ConvertStringSidToSidW.argtypes = [wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.ConvertStringSidToSidW.restype = wt.BOOL
    _advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.LPWSTR)]
    _advapi32.ConvertSidToStringSidW.restype = wt.BOOL
    _advapi32.GetTokenInformation.argtypes = [
        wt.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.POINTER(wt.DWORD),
    ]
    _advapi32.GetTokenInformation.restype = wt.BOOL
    _advapi32.AccessCheck.argtypes = [
        ctypes.c_void_p,
        wt.HANDLE,
        wt.DWORD,
        ctypes.POINTER(_GENERIC_MAPPING),
        ctypes.c_void_p,
        ctypes.POINTER(wt.DWORD),
        ctypes.POINTER(wt.DWORD),
        ctypes.POINTER(wt.BOOL),
    ]
    _advapi32.AccessCheck.restype = wt.BOOL
    _advapi32.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wt.WORD),
        ctypes.POINTER(wt.DWORD),
    ]
    _advapi32.GetSecurityDescriptorControl.restype = wt.BOOL
    _advapi32.GetNamedSecurityInfoW.argtypes = [
        wt.LPWSTR,
        ctypes.c_int,
        wt.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _advapi32.GetNamedSecurityInfoW.restype = wt.DWORD
    _advapi32.SetNamedSecurityInfoW.argtypes = [
        wt.LPWSTR,
        ctypes.c_int,
        wt.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    _advapi32.SetNamedSecurityInfoW.restype = wt.DWORD
    _advapi32.SetEntriesInAclW.argtypes = [
        ctypes.c_ulong,
        ctypes.POINTER(_EXPLICIT_ACCESS_W),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _advapi32.SetEntriesInAclW.restype = wt.DWORD

    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p


def acl_available() -> bool:
    """True when this host can build a write-restricted token."""
    if not IS_WINDOWS:
        return False
    try:
        token = _open_self_token()
    except AclSandboxUnavailable:
        return False
    _kernel32.CloseHandle(token)
    return True


def _open_self_token() -> int:
    handle = wt.HANDLE()
    if not _kernel32.OpenProcessToken(
        _kernel32.GetCurrentProcess(), TOKEN_ALL_ACCESS_FOR_DERIVE, ctypes.byref(handle)
    ):
        raise AclSandboxUnavailable(
            f"OpenProcessToken failed (WinError {ctypes.get_last_error()})"
        )
    return handle


def _mint_capability_sid() -> tuple[str, ctypes.c_void_p]:
    # A syntactically valid SID with no backing account. Windows accepts one in
    # a token's restricting list, which is exactly the capability-SID idea.
    parts = [secrets.randbelow(0x7FFFFFFF) + 1 for _ in range(4)]
    sid_text = "S-1-5-21-" + "-".join(str(p) for p in parts)
    psid = ctypes.c_void_p()
    if not _advapi32.ConvertStringSidToSidW(sid_text, ctypes.byref(psid)):
        raise AclSandboxUnavailable(
            f"ConvertStringSidToSidW failed for {sid_text} (WinError {ctypes.get_last_error()})"
        )
    return sid_text, psid


def _logon_sid_text(token: int) -> str | None:
    """The logon-session SID carried by the caller's token.

    A write-restricted token still needs this SID in its restricting list or the
    child cannot attach to the window station and dies with
    STATUS_DLL_INIT_FAILED (0xC0000142).
    """
    class _SID_AND_ATTRIBUTES(ctypes.Structure):  # local: not part of the public API
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]

    size = wt.DWORD(0)
    _advapi32.GetTokenInformation(token, TokenGroups, None, 0, ctypes.byref(size))
    if not size.value:
        return None
    buf = ctypes.create_string_buffer(size.value)
    if not _advapi32.GetTokenInformation(token, TokenGroups, buf, size.value, ctypes.byref(size)):
        return None
    count = ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0]
    array = ctypes.cast(
        ctypes.addressof(buf) + 8, ctypes.POINTER(_SID_AND_ATTRIBUTES * count)
    ).contents
    for i in range(count):
        text = _sid_to_string(array[i].Sid)
        if text and text.startswith("S-1-5-5-"):
            return text
    return None


def _sid_to_string(psid: ctypes.c_void_p) -> str | None:
    out = wt.LPWSTR()
    if not _advapi32.ConvertSidToStringSidW(psid, ctypes.byref(out)):
        return None
    try:
        return out.value
    finally:
        _kernel32.LocalFree(ctypes.cast(out, ctypes.c_void_p))


def _make_write_restricted_token(cap_sid: ctypes.c_void_p) -> int:
    base = _open_self_token()
    logon = _logon_sid_text(base)
    sids: list[ctypes.c_void_p] = []
    for text in ("S-1-1-0", logon):
        if not text:
            continue
        psid = ctypes.c_void_p()
        if _advapi32.ConvertStringSidToSidW(text, ctypes.byref(psid)):
            sids.append(psid)
    sids.append(cap_sid)
    restricted = (_SID_AND_ATTRIBUTES * len(sids))()
    for i, psid in enumerate(sids):
        restricted[i].Sid = psid
        restricted[i].Attributes = 0
    new_token = wt.HANDLE()
    ok = _advapi32.CreateRestrictedToken(
        base,
        DISABLE_MAX_PRIVILEGE | WRITE_RESTRICTED,
        0,
        None,
        0,
        None,
        len(sids),
        restricted,
        ctypes.byref(new_token),
    )
    err = ctypes.get_last_error()
    _kernel32.CloseHandle(base)
    for psid in sids[:-1]:
        _kernel32.LocalFree(psid)
    if not ok:
        raise AclSandboxUnavailable(f"CreateRestrictedToken failed (WinError {err})")
    return new_token


def _dacl_inherit_flag(sd: ctypes.c_void_p) -> int:
    """PROTECTED vs UNPROTECTED for the DACL, matching the object's own bit.

    Re-applying a DACL without this bit silently *unprotects* the object, which
    makes it inherit its parent's ACEs — a restore that changes the ACL instead
    of putting it back.
    """
    control = wt.WORD(0)
    revision = wt.DWORD(0)
    if not _advapi32.GetSecurityDescriptorControl(sd, ctypes.byref(control), ctypes.byref(revision)):
        return UNPROTECTED_DACL_SECURITY_INFORMATION
    if control.value & SE_DACL_PROTECTED:
        return PROTECTED_DACL_SECURITY_INFORMATION
    return UNPROTECTED_DACL_SECURITY_INFORMATION


def _caller_user_sid() -> ctypes.c_void_p:
    """A copy of the caller's own user SID, freed by the caller."""
    token = _open_self_token()
    try:
        size = wt.DWORD(0)
        _advapi32.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(max(size.value, 64))
        if not _advapi32.GetTokenInformation(token, TokenUser, buf, len(buf), ctypes.byref(size)):
            return ctypes.c_void_p()
        source = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        copy = ctypes.c_void_p()
        if not _advapi32.ConvertStringSidToSidW(_sid_to_string(source) or "", ctypes.byref(copy)):
            return ctypes.c_void_p()
        return copy
    finally:
        _kernel32.CloseHandle(token)


def _caller_can_write(path: str) -> bool:
    """Can the caller's *normal* token write here? Answered by trying.

    A write-restricted token intersects its restricting SIDs with the normal
    ones, so a root whose DACL only relies on OWNER RIGHTS is unwritable inside
    the sandbox even though the owner can write normally. Measuring it with a
    real create+delete (instead of an access check) keeps this honest and makes
    the extra ACE below a re-statement of an existing right, never an escalation.
    """
    probe = os.path.join(str(path), f".atlas-acl-probe-{secrets.token_hex(4)}")
    try:
        with open(probe, "wb") as fh:
            fh.write(b"x")
    except OSError:
        return False
    try:
        os.unlink(probe)
    except OSError:
        pass
    return True


def _grant_write(
    root: str,
    cap_sid: ctypes.c_void_p,
    read_sid: ctypes.c_void_p | None = None,
    user_sid: ctypes.c_void_p | None = None,
) -> tuple[bool, ctypes.c_void_p, ctypes.c_void_p]:
    """Append the boundary ACEs to root and return the previous DACL.

    Two ACEs go on: the capability SID gets read/write/execute (the only identity
    the write-restricted token will accept a write from), and the caller's logon
    SID gets read/execute. The second one is what keeps reads working on a root
    whose DACL is protected and names neither the user nor Everyone — without it
    the child would be unable to even list the workspace. Read-only rights cannot
    widen what the caller could write.
    """
    old_sd = ctypes.c_void_p()
    old_dacl = ctypes.c_void_p()
    rc = _advapi32.GetNamedSecurityInfoW(
        str(root),
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(old_dacl),
        None,
        ctypes.byref(old_sd),
    )
    if rc != 0:
        return False, None, None

    entries: list[tuple[ctypes.c_void_p, int]] = [(cap_sid, FILE_SANDBOX_ALL)]
    if read_sid is not None:
        entries.append((read_sid, FILE_READ_EXECUTE))
    if user_sid is not None and _caller_can_write(root):
        # Materialise the write right the caller already holds: a restricted
        # token checks the normal SID list as well, so OWNER RIGHTS alone leaves
        # the root unwritable inside the sandbox.
        entries.append((user_sid, FILE_SANDBOX_ALL))

    array = (_EXPLICIT_ACCESS_W * len(entries))()
    for i, (psid, perms) in enumerate(entries):
        array[i].grfAccessPermissions = perms
        array[i].grfAccessMode = GRANT_ACCESS
        array[i].grfInheritance = SUB_CONTAINERS_AND_OBJECTS_INHERIT
        array[i].Trustee.TrusteeForm = TRUSTEE_IS_SID
        array[i].Trustee.TrusteeType = TRUSTEE_IS_UNKNOWN
        array[i].Trustee.ptstrName = psid

    new_dacl = ctypes.c_void_p()
    rc = _advapi32.SetEntriesInAclW(len(entries), array, old_dacl, ctypes.byref(new_dacl))
    if rc != 0:
        _kernel32.LocalFree(old_sd)
        return False, None, None

    rc = _advapi32.SetNamedSecurityInfoW(
        str(root),
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION | _dacl_inherit_flag(old_sd),
        None,
        None,
        new_dacl,
        None,
    )
    _kernel32.LocalFree(new_dacl)
    if rc != 0:
        _kernel32.LocalFree(old_sd)
        return False, None, None
    return True, old_dacl, old_sd


def _restore_dacl(root: str, old_dacl: ctypes.c_void_p, old_sd: ctypes.c_void_p) -> bool:
    rc = _advapi32.SetNamedSecurityInfoW(
        str(root),
        SE_FILE_OBJECT,
        DACL_SECURITY_INFORMATION | _dacl_inherit_flag(old_sd),
        None,
        None,
        old_dacl,
        None,
    )
    if old_sd:
        _kernel32.LocalFree(old_sd)
    return rc == 0


def _unicode_env_block(overrides: dict[str, str]) -> ctypes.Array:
    env = dict(os.environ)
    env.update(overrides)
    body = "".join(f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper()))
    return ctypes.create_unicode_buffer(body + "\0")


def _open_stdio(path: str) -> int:
    # Inheritable handle without going through CreateFileW's SECURITY_ATTRIBUTES.
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_TRUNC)
    handle = _msvcrt_handle(fd)
    _kernel32.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT)
    return fd


def _msvcrt_handle(fd: int) -> int:
    import msvcrt

    return msvcrt.get_osfhandle(fd)


def run_in_acl_sandbox(
    argv: list[str],
    *,
    mode: str = "workspace-write",
    workspace_roots: list[str] | None = None,
    cwd: str | None = None,
    timeout: float = 120.0,
    command: str | None = None,
) -> AclSandboxResult:
    """Run argv under a write-restricted token.

    ``read-only`` grants write only to a private scratch directory; every other
    path — including the workspace — fails a write access check while reads keep
    working. ``workspace-write`` adds the caller's workspace roots.

    Pass ``command`` for a shell line: it is handed to ``cmd.exe /d /s /c`` as
    one unit, which is the only way a quoted redirect inside it survives. ``argv``
    is quoted with ``list2cmdline`` and cannot carry shell metacharacters safely.
    """
    if not IS_WINDOWS:
        raise AclSandboxUnavailable("write-restricted sandbox is Windows-only")
    if mode not in ("read-only", "workspace-write"):
        raise ValueError(f"unsupported mode for the ACL layer: {mode!r}")

    started = time.monotonic()
    cap_text, cap_sid = _mint_capability_sid()
    token = _make_write_restricted_token(cap_sid)
    base = _open_self_token()
    logon_text = _logon_sid_text(base)
    _kernel32.CloseHandle(base)
    logon_sid = ctypes.c_void_p()
    if logon_text:
        _advapi32.ConvertStringSidToSidW(logon_text, ctypes.byref(logon_sid))
    user_sid = _caller_user_sid()

    scratch = tempfile.mkdtemp(prefix="atlas-acl-")
    granted: list[tuple[str, ctypes.c_void_p, ctypes.c_void_p]] = []
    roots = [scratch]
    if mode == "workspace-write":
        for root in workspace_roots or []:
            resolved = os.path.abspath(root)
            if os.path.exists(resolved):
                roots.append(resolved)
    # The real %TEMP% is never granted: it is shared with every other program on
    # the machine, so allowing it would make `read-only` writable in practice.
    # The child's TMP/TEMP point at this call's scratch directory instead.

    # Sorted acquisition order so two calls with overlapping roots cannot
    # deadlock, and the locks stay held until the ACLs are back: a concurrent
    # call must never restore a DACL that already carries another call's grant.
    locks = [
        _path_lock(norm)
        for norm in sorted({os.path.normcase(r) for r in roots})
    ]
    for lock in locks:
        lock.acquire()
    try:
        for root in roots:
            ok, old_dacl, old_sd = _grant_write(root, cap_sid, logon_sid or None, user_sid)
            if ok:
                granted.append((root, old_dacl, old_sd))

        out_path = os.path.join(scratch, "stdout.bin")
        err_path = os.path.join(scratch, "stderr.bin")
        out_fd = _open_stdio(out_path)
        err_fd = _open_stdio(err_path)
        nul_fd = _open_stdio(os.devnull)

        job = _kernel32.CreateJobObjectW(None, None)
        pi = _PROCESS_INFORMATION()
        si = _STARTUPINFOW()
        si.cb = ctypes.sizeof(_STARTUPINFOW)
        # No CREATE_NO_WINDOW: a write-restricted token cannot attach a console, so
        # that flag kills the child with STATUS_DLL_INIT_FAILED before main(). The
        # hidden console from STARTF_USESHOWWINDOW/SW_HIDE is what suppresses the
        # window instead.
        si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW
        si.wShowWindow = SW_HIDE
        si.hStdInput = _msvcrt_handle(nul_fd)
        si.hStdOutput = _msvcrt_handle(out_fd)
        si.hStdError = _msvcrt_handle(err_fd)

        if command is not None:
            # /s strips the outer quote pair and hands the rest to cmd verbatim, so
            # `echo x> "path with space"` keeps its own quotes.
            line = f'cmd.exe /d /s /c "{command}"'
        else:
            line = subprocess.list2cmdline(argv)
        command_line = ctypes.create_unicode_buffer(line)
        env_block = _unicode_env_block({"TMP": scratch, "TEMP": scratch})
        work_dir = os.path.abspath(cwd) if cwd else None
        created = _advapi32.CreateProcessAsUserW(
            token,
            None,
            command_line,
            None,
            None,
            True,
            CREATE_UNICODE_ENVIRONMENT,
            ctypes.cast(env_block, ctypes.c_void_p),
            work_dir,
            ctypes.byref(si),
            ctypes.byref(pi),
        )
        create_error = ctypes.get_last_error()

        exit_code: int | None = None
        timed_out = False
        if created:
            if job:
                _kernel32.AssignProcessToJobObject(job, pi.hProcess)
            waited = _kernel32.WaitForSingleObject(pi.hProcess, int(timeout * 1000))
            if waited == WAIT_TIMEOUT_CODE:
                timed_out = True
                if job:
                    _kernel32.TerminateJobObject(job, 1)
                _kernel32.TerminateProcess(pi.hProcess, 1)
                _kernel32.WaitForSingleObject(pi.hProcess, 5000)
            code = wt.DWORD(0)
            _kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
            exit_code = int(code.value)
            _kernel32.CloseHandle(pi.hProcess)
            _kernel32.CloseHandle(pi.hThread)
        if job:
            _kernel32.CloseHandle(job)

    finally:
        restored = True
        for root, old_dacl, old_sd in granted:
            restored = _restore_dacl(root, old_dacl, old_sd) and restored
        for lock in locks:
            lock.release()

    if cap_sid:
        _kernel32.LocalFree(cap_sid)
    if logon_sid:
        _kernel32.LocalFree(logon_sid)
    if user_sid:
        _kernel32.LocalFree(user_sid)

    def _read(path: str) -> str:
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            return ""
        # Native tools on a Chinese Windows emit GBK; Python-side tools emit
        # UTF-8. Prefer UTF-8, fall back when the bytes are not valid UTF-8.
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("gbk", errors="replace")

    detail = ""
    if not created:
        detail = f"CreateProcessAsUserW failed (WinError {create_error})"

    result = AclSandboxResult(
        exit_code=exit_code,
        stdout=_read(out_path),
        stderr=_read(err_path),
        timed_out=timed_out,
        enforced=bool(created and granted),
        mode=mode,
        capability_sid=cap_text,
        writable_roots=tuple(granted_roots := [r for r, _, _ in granted]),
        acl_roots_restored=restored,
        detail=detail,
    )
    try:
        import shutil

        shutil.rmtree(scratch, ignore_errors=True)
    except Exception:
        pass
    return result