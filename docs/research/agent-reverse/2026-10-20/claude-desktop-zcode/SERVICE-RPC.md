# SERVICE-RPC.md — cowork-svc.exe RPC protocol analysis

Target: `cowork-svc.exe` (13,761,360 bytes, Go 1.25.14, PE x64 CUI)
Image base `0x140000000`; all `entry_hex` are VAs. File offsets are given where relevant.
All evidence below comes from the extracted binary's own pclntab symbols, `.rdata`
string constants, and x86-64 disassembly. No claim in this document is based on
strings alone where code evidence was obtainable.

Reproduce with: `PARSERS\gopcln.py`, `PARSERS\analyze_go.py`, `PARSERS\inlinestr.py`,
`PARSERS\dispatchtab.py`, `PARSERS\leautil.py`, `PARSERS\gopcln.py`.

---

## 0. Identity

| Property | Value | Evidence |
|---|---|---|
| Main module | `github.com/anthropics/cowork-win32-service` | buildinfo at file 0x83b910: `path\tgithub.com/anthropics/cowork-win32-service/cmd/cowork-svc` |
| Binary | `cmd/cowork-svc` | same |
| Go version | go1.25.14 | buildinfo `Go buildinf:` at file 0xc62400, version string at 0x8168f0 |
| Build flags | `-ldflags="-s -w"`, `CGO_ENABLED=1`, `GOOS=windows`, `GOARCH=amd64`, `GOAMD64=v1` | buildinfo `build` lines |
| Service name | `CoworkVMService`, `StartAccount=localSystem`, `StartupType=auto` | AppxManifest.xml `<desktop6:Service Name="CoworkVMService" ...>` |
| Package capability | `localSystemServices`, `packagedServices`, `runFullTrust` | AppxManifest.xml `<Capabilities>` |
| pclntab | file 0x87e200, magic `0xfffffff1`, 15181 funcs, 1265 files | `gopcln.py` |

---

## 1. Claim-by-claim verdicts

Summary: for the six headline protocol claims, **4 VERIFIED, 2 PARTIALLY
VERIFIED, 0 REFUTED**. Two sub-claims inside the method/event lists are
individually **REFUTED** (`spawn`/`kill` are not pipe methods; `startupStep` is
not an event name).

| # | Claim | Verdict |
|---|---|---|
| 1 | Pipe path `\\.\pipe\cowork-vm-service` | **VERIFIED** |
| 2 | 4-byte big-endian JSON framing | **VERIFIED** (pipe channel and vsock channel) |
| 3 | 10 MiB limit | **VERIFIED for the pipe channel**; the vsock guest channel uses a different 100 MiB limit |
| 4 | Methods `configure/startVM/stopVM/isRunning/isGuestConnected/spawn/kill/writeStdin` | **PARTIALLY VERIFIED** — `configure, startVM, stopVM, isRunning, isGuestConnected, writeStdin` present; **`spawn` and `kill` are NOT pipe RPC methods** (they are guest-RPC method names in a passthrough allowlist) |
| 5 | Events `stdout/stderr/exit/error/networkStatus/apiReachability/startupStep` | **PARTIALLY VERIFIED** — `stdout, stderr, exit, error, networkStatus, apiReachability` are guest-channel events; **`startupStep` is not an event name**, it is an internal callback (`emitStartupStep`) that emits `(step, status)` progress records |
| 6 | 10 MiB max message size constant | **VERIFIED** as `0xa00000` at instruction `0x14050fb40` (`cmp ecx, 0xa00000`) |

---

### Claim 1 — pipe path `\\.\pipe\cowork-vm-service` — VERIFIED

Evidence (three independent sources):

1. **Exact `go:string` constant.** The string header at file offset **0xcae7c0**
   is `{ptr = 0x14072fc03, len = 26}` and resolves to exactly
   `\\.\pipe\cowork-vm-service` (26 bytes). The neighbouring header at
   **0xcae7e0** is `{ptr = 0x140734df2, len = 30}` →
   `\\.\pipe\cowork-daemon-console`.
   Two further literals are stored as raw pooled tokens:
   * `\\.\pipe\cowork-vm-service-store` at file 0x735fcd
   * `\\.\pipe\cowork-daemon-console-store` at file 0x73ab55
2. **Manifest.** `AppxManifest.xml` declares the service trigger with
   `<desktop6:DataItem Value="\pipe\cowork-vm-service" />`.
3. **Code.** `pipe.(*Server).Start` @ `0x1405140c0` (size 672) calls
   `github.com/Microsoft/go-winio.ListenPipe` and, on failure, produces
   `failed to create named pipe: %w`
   (LEA at `0x14051404c` → VA `0x1407362f8`, len 31).

The `-store` variants are the debug/`-store` mode pipes (a second service
instance variant); `cowork-daemon-console*` is the guest serial-console
channel described in VM-LIFECYCLE.md §6.

### Claim 2 — 4-byte big-endian JSON framing — VERIFIED

`pipe.ReadMessage` @ `0x14050faa0` (size 576):

```
0x14050faf4  call  encoding/binary.Read          ; decode 4-byte length
0x14050fb14  lea   rax, "failed to read length: %w"  (len 25, .rdata 0x14072e5ef)
0x14050fb38  mov   ecx, [rsp+0x34]               ; decoded uint32
0x14050fb40  cmp   ecx, 0xa00000                 ; 10 MiB guard
0x14050fb46  ja    0x14050fc36                   ; -> "message too large" error
0x14050fb55  call  runtime.makeslice
0x14050fb82  call  io.ReadAtLeast                ; read exactly N bytes
0x14050fba2  lea   rax, "failed to read payload: %w" (len 26, .rdata 0x14072fc37)
0x14050fbe8  call  encoding/json.Unmarshal
0x14050fc08  lea   rax, "failed to unmarshal message: %w" (len 31, .rdata 0x1407362d9)
```

Big-endian is proven by the itab passed to `encoding/binary.Read`. The LEA at
`0x14050fada` targets `0x140829fb0`, whose vtable slots resolve (via pclntab
symbols) to:

```
0x140829fb0 +0x18 fun[0] = 0x140118d40  encoding/binary.(*bigEndian).PutUint16
0x140829fb0 +0x20 fun[1] = 0x140118da0  encoding/binary.(*bigEndian).PutUint32
0x140829fb0 +0x28 fun[2] = 0x140118e00  encoding/binary.(*bigEndian).PutUint64
0x140829fb0 +0x30 fun[3] = 0x140118e60  encoding/binary.(*bigEndian).String
0x140829fb0 +0x38 fun[4] = 0x140118ea0  encoding/binary.(*bigEndian).Uint16
0x140829fb0 +0x40 fun[5] = 0x140118f00  encoding/binary.(*bigEndian).Uint32
0x140829fb0 +0x48 fun[6] = 0x140118f60  encoding/binary.(*bigEndian).Uint64
```

This is an `*encoding/binary.bigEndian` itab, not `littleEndian`. The decoded
value therefore comes from `bigEndian.Uint32`.

`pipe.WriteMessage` @ `0x14050f920` (size 384) mirrors this:

```
0x14050f94f  call  encoding/json.Marshal
0x14050f99e  lea   rcx, [rbx+4]        ; header is len(payload)+4
0x14050f9a7  call  runtime.makeslice
0x14050f9ce  bswap esi                ; <-- byte swap of the uint32 length
0x14050f9d0  mov   [rax], esi         ; store big-endian prefix
0x14050fa25  lea   rax, "failed to write message: %w"
```

The `bswap esi` at `0x14050f9ce` is the byte-order conversion; `WriteMessage`
uses a hand-rolled big-endian store rather than the `binary` package.

The guest-side channels (`vm.ReadMessage` @ `0x1404f0dc0`, `vm.WriteMessage` @
`0x1404f0c60`) use the **same** framing, also hand-rolled big-endian:

```
vm.WriteMessage:
0x1404f0c7f  lea   rdi, [rcx + 4]     ; payload len + 4-byte header
0x1404f0cc0  call  runtime.makeslice
0x1404f0d00  bswap r8d                ; big-endian store of the length
vm.ReadMessage:
0x1404f0e00  cmp   rcx, 4             ; need 4 bytes for the header
0x1404f0e31  call  vm.(*HVSocketConn).Read
0x1404f0eb8  mov   edx, [rsp+0x28]
0x1404f0ebc  bswap edx                ; <-- big-endian load
0x1404f0ec0  cmp   edx, 0x6400000     ; 100 MiB guard
```

### Claim 3 — 10 MiB limit — VERIFIED for pipe, different for vsock

* Pipe channel: `0x14050fb40  cmp ecx, 0xa00000` → **10,485,760 bytes = 10 MiB**.
  Overflow path emits `.rdata 0x1407525a5` (len 82):
  `message too large: %d bytes (header=0x%08x) — framing desync, closing connection`.
  The `%08x` in that format string is itself consistent with a 4-byte header.
* Guest vsock channel: `vm.ReadMessage` @ `0x1404f0ec0  cmp edx, 0x6400000`
  → **104,857,600 bytes = 100 MiB**. This is a *separate, larger* limit.

So "10 MiB limit" is correct for the app↔service named pipe. It is wrong if
applied to the service↔guest vsock channel.

### Claim 4 — method list — PARTIALLY VERIFIED

The pipe dispatch is `pipe.(*Server).dispatchWithSession` @ `0x140519840`
(size 3168), reached from `dispatch` @ `0x140518fc0` (736 bytes) via
`dispatchVerified` @ `0x1405192a0` (1440 bytes). Recovered string-switch table
(immediates + `memequal` calls, with handler attribution from the direct `call`
that follows each case):

| Method literal | cmp site | Handler (pclntab symbol) | Handler entry |
|---|---|---|---|
| `isRunning` (9) | 0x1405198a0 | `pipe.(*Server).handleIsRunning` | 0x14051da20 |
| `runEdrExtension` (15) | 0x140519944 | `pipe.(*Server).handleRunEdrExtension` | 0x14050d100 |
| `subscribeEvents` (15) | 0x140519a14 | inline in `dispatchWithSession` (calls `fmt.Errorf` on bad params; the real body is `handleSubscription`) | 0x140517a00 |
| `isGuestConnected` (16) | 0x140519ab4 | `vm.(*WindowsVMManager).IsGuestConnected` | 0x1404fd580 |
| `VM`-suffix group → `stopVM` (6) | 0x140519bd4 | `pipe.(*Server).handleStopVM` | 0x14051d7e0 |
| `startVM` (7) | 0x140519c8a | `pipe.(*Server).handleStartVM` | 0x14051d3c0 |
| `writeStdin` (10) | 0x140519d65 | `pipe.(*Server).handleWriteStdin` | 0x14051e0e0 |
| `setDebugLogging` (15) | 0x140519e40 | `pipe.(*Server).handleSetDebugLogging` | 0x14051e4c0 |
| `getNetworkDrives` (16) | 0x140519f20 | `pipe.(*Server).handleGetNetworkDrives` | 0x14051dce0 |
| `isProcessRunning` (16) | 0x140519fd0 | `pipe.(*Server).handleIsProcessRunning` | 0x14051e2c0 |
| `isDebugLoggingEnabled` (21) | memequal @ 0x14051a0aa | `pipe.(*Server).handleIsDebugLoggingEnabled` | 0x14051e660 |
| `refreshGuestProxy` (17) | memequal @ 0x14051a14e | `pipe.(*Server).handleRefreshGuestProxy` | 0x14051d940 |
| `sendGuestResponse` (17) | memequal @ 0x14051a16d | `pipe.(*Server).handleSendGuestResponse` | 0x14051dec0 |
| `configure` (9) | `dispatchVerified` 0x140519330 | `pipe.(*Server).handleConfigure` | 0x14051a5e0 |

No-match path: `0x14051a1bd` builds `unknown method: %s` (.rdata 0x140724d20).
`dispatchVerified` also enforces ordering: before `configure`, the method returns
`not configured: call 'configure' first` (.rdata 0x14073e1dc/.rdata 0x14073e1ee,
error string emitted at cmp-guard `0x1405196a8`).

**`spawn` and `kill` are REFUTED as pipe methods.** They appear only in
`pipe.map.init.0` @ `0x140509100` (a Go map literal), whose LEA-referenced keys are:

```
0x14050912d  spawn
0x140509154  kill
0x140509174  mountPath
0x140509194  readFile
0x1405091b4  getMemoryInfo
0x1405091d4  getSessionsDiskInfo
0x1405091f4  deleteSessionDirs
0x140509214  pruneSessionCaches
0x140509234  installSdk
0x140509254  addApprovedOauthToken
```

This is the **passthrough allowlist** used by `handlePassthrough` @
`0x14051e740` (288 bytes), which forwards an allowed method to the guest over
vsock. So `spawn`/`kill` are guest-agent method names reachable *through*
`handlePassthrough`, not direct pipe methods.

### Claim 5 — event names — PARTIALLY VERIFIED

Guest-channel event dispatch is `vm.(*RPCServer).handleEvent` @ `0x140501420`
(reached from `vm.(*RPCServer).handleMessage` @ `0x140500a20`, which switches on
`event`/`request`/`response` at cmp sites `0x140500a47`, `0x140500a74`,
`0x140500c64`). Recovered event literals:

| Event literal | cmp site | Length guard |
|---|---|---|
| `exit` | 0x14050149b | 4 |
| `error` | 0x14050184a | 5 |
| `ready` | 0x140501c97 | 5 |
| `stderr` | 0x140501efd | 6 |
| `stdout` | 0x140502045 | 6 |
| `networkStatus` | 0x1405021a0 | 13 |
| `apiReachability` | 0x140502425 (memequal 0x140502440..) | 15 |

Note the `apiReachability` case reads `0x14050242f movabs r8, 0x6863616552697061`
= `"apiReach"` + `0x140502449 cmp dword [rdx+8], 0x6c696261` = `"abil"` +
`0x140502456 cmp word [rdx+0xc], 0x7469` = `"it"` +
`0x140502466 cmp byte [rdx+0xe], 0x79` = `"y"`.

There is also `ready` (not in the prior claim set) — a guest boot-readiness event.

**`startupStep` is REFUTED as an event name.** It is a *struct field* tag
(`json:"step,omitempty"`, name blob at `.rdata` 0x5b762f) and an internal
callback `vm.(*EventCallbacks).emitStartupStep` (thunk `-fm` @ `0x140506e60`,
160 bytes). The emit sites are inside `vm.(*WindowsVMManager).StartVM`:
`0x1404f7278` and `0x1404f72d1` (LEA of the closure). The actual step literals
used with it are the StartVM progress markers:

```
0x1404f7401  create_network     status 0x1404f740d  completed
0x1404f7521  create_vm_config   status 0x1404f752d  started
0x1404f76c6  create_vm_config   status 0x1404f76d2  completed
0x1404f8870  vm_boot           status 0x1404f8964  completed
0x1404f89dc  add_plan9_shares   status 0x1404f89e8  started
0x1404f8ace  failed
0x1404f9xxx  guest_ready (in StartVM.func2, 0x1404fa3ac)
```

So the wire representation is a `step` field (JSON tag `step,omitempty`) with
values like `create_network`, not an event named `startupStep`.

### Claim 6 — max message size constant — VERIFIED

`0xa00000` (10 MiB) appears at `0x14050fb40` (`cmp ecx, 0xa00000`) in
`pipe.ReadMessage`. The write side has no explicit cap in `pipe.WriteMessage`
beyond the marshalled payload size; the only cap on the channel is the read
guard. File offset of the immediate is 0x50f142, inside `pipe.ReadMessage`'s
file range 0x50f0a0–0x50f2e0 (confirmed).

---

## 2. Message envelope

From the type metadata (`.rdata` name blob; struct type names recovered at
0x5af832, 0x599051, 0x59d8cf, 0x5a01c2, 0x5ab866, 0x5b88ea, 0x5b1841) and the
`json:"..."` field records (91 distinct field+tag pairs, see `SVC-STRINGS.tsv`):

Type names present in the binary:
`*pipe.Request`, `*pipe.Response`, `*pipe.ConfigureParams`,
`*pipe.StartVMParams`, `*pipe.WriteStdinParams`, `*pipe.SubscribeEventsParams`,
`*pipe.SetDebugLoggingParams`, `*pipe.IsProcessRunningParams`, `*pipe.Event`.

Field/tag records (address = .rdata file offset of the name record):

```
0x5ad6b4  Method       json:"method"           (len 6)
0x5bbece  Method       json:"method,omitempty" (len 6)
0x5bbe2e  Params       json:"params,omitempty"
0x5bbe4e  Result       json:"result,omitempty"
0x5b9cdc  Error        json:"error,omitempty"
0x5b7613  Data         json:"data,omitempty"
0x5b9dcc  Event        json:"event,omitempty"
0x5b17ef  ID           json:"id"  /  0x5b180f json:"id,omitempty"
0x5b75f7  Connected    json:"connected"
0x5b17df  Running      json:"running"
0x5b17c7  Enabled      json:"enabled"
0x5b762f  Step         json:"step,omitempty"
0x5b9e08  Stage        json:"stage,omitempty"
```

Reconstructed pipe envelope:

```jsonc
// request
{ "id": "...", "method": "configure", "params": { ... } }
// response
{ "id": "...", "result": { ... } }   or   { "id": "...", "error": "..." }
// event (server -> client)
{ "event": "stdout", "data": ... }
```

The `RequestType` field (`json:"RequestType"`, tag at 0x5bbeee) is used by the
**guest** message type (`vm.Message`), not the pipe envelope.

## 3. Guest message types (vsock)

`vm.(*RPCServer).handleMessage` @ `0x140500a20` switches on the message type
string:

```
0x140500a41 cmp rdx,5 ; 0x140500a47 cmp dword [r8],0x6e657665 ("even") ; 0x140500a54 cmp byte [r8+4],0x74 ("t")  -> "event"
0x140500a6a cmp rdx,7 ; 0x140500a74 cmp dword [r8],0x75716572 ("requ") ; 0x140500a86 cmp word [r8+4],0x7365 ("es") ; 0x140500a93 cmp byte [r8+6],0x74 -> "request"
0x140500c64 -> "response"
```

Guest request parameters observed as JSON tags include
`installCACertificates`, `mountPlan9Shares`, `plan9Shares`, `isRunning`,
`stdin`, `ipv6Assignment`, `hostProxyConfig`, `runEdrExtension`,
`apiReachability`. These are RPC method names carried in `RequestType` /
`method` on the guest channel (visible as LEA literals in
`vm.(*RPCServer).SendInstallCACertificates` 0x140503ac5 and
`vm.mountSharesInGuest` 0x1404fb64b).

## 4. Transport topology

```
Claude Desktop (app, MSIX full-trust)
        |  named pipe \\.\pipe\cowork-vm-service
        |  [u32 BE length][JSON]  max 10 MiB
        v
cowork-svc.exe (LocalSystem Windows service, CoworkVMService)
        |  AF_HYPERV / HVSocket, service GUID 90db8b89-0d35-4f79-8ce9-49ea0ac8b7cd
        |  [u32 BE length][JSON]  max 100 MiB
        v
Linux guest (rootfs.vhdx + smol-bin.vhdx)
```

HVSocket listener evidence: `vm.NewHVSocketListener` @ `0x1404ef520` (2080 bytes)
creates the socket and binds the literal GUID
`90db8b89-0d35-4f79-8ce9-49ea0ac8b7cd` (.rdata 0x1404efca3) and the all-zeros
GUID (.rdata 0x1404efc6b). `vm.(*HVSocketListener).Accept` @ `0x1404eff20` logs
`accept failed: %v` (0x1404f03b2).

## 5. Access control on the pipe

The pipe is not merely opened to whoever connects:

* `pipe.(*Server).dispatch` @ `0x140518fc0` calls `pipe.GetClientInfoFromConn`
  (`0x140509cc0`) then `pipe.(*Server).verifyClientSignature` (`0x140511920`,
  3008 bytes) before `dispatchVerified`.
* Signature check errors: `client executable is not signed: %s` (0x1405121bc),
  `client certificate does not match service (...)` (0x140511c4d),
  `client signature is invalid for %s: %s` (0x140512049),
  `client certificate thumbprint could not be determined for %s` (0x140511ead).
* Service self-check on startup: `pipe.(*Server).InitSignatureVerification` @
  `0x1405103a0` (3552 bytes) emits `service is not properly signed: %s`
  (0x14051100c) and `service certificate thumbprint could not be determined`
  (0x140510749).
* Package containment: `pipe.(*ClientInfo).InServicePackage` @ `0x14050b720`
  emits `client %s is not part of package %s (client package: %q)`
  (0x14050ba02) and `client %s was not started from the package directory ...`
  (0x14050b948).
* User data directory containment: `pipe.(*ClientInfo).UserDataDirFor` @
  `0x14050bc80` (2976 bytes), `invalid userData basename %q` (0x14050bd94).
* Per-connection impersonation: `vm.PipeClientUser` @ `0x1404f1240` calls
  `ImpersonateNamedPipeClient` (`vm.PipeClientUser.func1` 0x1404f15a7).

## 6. UNRESOLVED

* Exact JSON field ordering / optionality of `pipe.ConfigureParams` members.
  The type metadata is present (`*pipe.ConfigureParams` at .rdata 0x5af832) and
  91 field+tag records were recovered, but the mapping from each tag to its
  owning struct was not completed: the `structtype` field-array layout in
  Go 1.25 differed from the layout assumed by my parser (16-byte
  `structfield{name int32, typ int32, offset uintptr}` produced inconsistent
  offsets). The tags themselves are all in `SVC-STRINGS.tsv` and are real.
* Whether `subscribeEvents` has a dedicated handler symbol: the case in
  `dispatchWithSession` jumps straight to param validation and then to
  `pipe.(*Server).handleSubscription` @ `0x140517a00` indirectly; the direct
  call in the case body is `fmt.Errorf`. The 3392-byte `handleSubscription`
  function exists and references `invalid subscribeEvents params: %w`
  (0x140517c68), so the behaviour is certain; the exact dispatch edge is not.
* The precise `emitStartupStep` argument pair for `guest_ready`: it is emitted
  from `StartVM.func2` @ 0x1404fa3ac, but the `(step, status)` pair could not be
  read out of the closure without full register-flow analysis.
