# VM-LIFECYCLE.md — what cowork-svc.exe actually does to create/start/stop the Cowork VM

Target: `cowork-svc.exe`, Go 1.25.14, image base `0x140000000`.
Every step cites a pclntab symbol (with entry VA) and, where useful, the exact
instruction or string constant. Compiled with `-ldflags="-s -w"`, so no DWARF:
all evidence is pclntab + disassembly + `.rdata` literals.

Reproduce with `PARSERS\analyze_go.py`, `PARSERS\inlinestr.py`, `PARSERS\leautil.py`.

---

## 1. Host-side HCS/HDV access is fully dynamic

`Get-ChildItem` on the PE import table of `cowork-svc.exe` returns **one DLL**:
`kernel32.dll` with 46 functions (`LoadLibraryW`, `LoadLibraryExW`,
`GetProcAddress`, `VirtualAlloc`, `CreateThread`, …). There is **no** static
import of `vmcompute.dll`, `computecore.dll`, `virtdisk.dll`, or `hcsapi`.
Consequently every Hyper-V/HCS/HCN/VHD entry point is resolved at runtime.

`vm.InitHCS` @ `0x1404e4120` (2464 bytes) is the resolver:

```
0x1404e41d2  lea  rax, "vmcompute.dll"       (.rdata, part of pooled literals)
0x1404e4305  ...  log "[HCS] vmcompute.dll loaded successfully"
0x1404e4343  lea  rax, "computecore.dll"
0x1404e447a  ...  log "[HCS] computecore.dll loaded successfully"
0x1404e4504  "HcsCreateComputeSystem"
0x1404e456e  "HcsOpenComputeSystem"
0x1404e45d8  "HcsCloseComputeSystem", "HcsStartComputeSystem"
0x1404e4641  "HcsStartComputeSystem", "HcsGetOperationResult"
0x1404e46a2  "HcsShutDownComputeSystem"
0x1404e4703  "HcsTerminateComputeSystem", "HcsWaitForOperationResult"
0x1404e4764  "HcsGetComputeSystemProperties"
0x1404e47c5  "HcsGetServiceProperties"
0x1404e4826  "HcsEnumerateComputeSystems"
0x1404e4887  "HcsCreateOperation"
0x1404e48ea  "HcsCloseOperation"
0x1404e494b  "HcsGetOperationResult"
0x1404e49ac  "HcsWaitForOperationResult", "HcsCreateOperation"
0x1404e4a0d  "HcsModifyComputeSystem"
```

Calls made: `golang.org/x/sys/windows.(*LazyDLL).Load` (twice — vmcompute and
computecore) plus `vm.InitHCS.func1` (the `GetProcAddress` wrapper) about a
dozen times. Failure to load is non-fatal: `[HCS] Warning: Failed to load
vmcompute.dll: %v` (literal at file 0x7444c2).

`vm.InitHCN` @ `0x1404e29c0` (672 bytes) does the same for the network API:

```
0x1404e29e6  "computenetwork.dll"
0x1404e2a61  "HcnEnumerateNetworks"
0x1404e2ac2  "HcnOpenNetwork"
0x1404e2b23  "HcnCloseNetwork", "computecore.dll"
0x1404e2b84  "HcnDeleteNetwork"
0x1404e2be5  "HcnQueryNetworkProperties"
```

VHD creation is equally dynamic: `vm.CreateDynamicVHDX` @ `0x140504120` (1504 bytes)
calls `CreateVirtualDisk` from `virtdisk.dll` and reports
`CreateVirtualDisk failed: 0x%x (err: %v)` (0x1405044e9). The
`[VHDX] Warning: failed to load virtdisk.dll: %v` message exists at file 0x7445ae.

---

## 2. `configure` — declare the VM, do not start it

Handler: `pipe.(*Server).handleConfigure` @ `0x14051a5e0` (**10112 bytes** — the
largest first-party function in the binary).

It takes `pipe.ConfigureParams` (type metadata at `.rdata` 0x5af832) and resolves
the VM bundle under the *calling user's* profile:

```
0x14051aefc  "%s\\vm_bundles\\claudevm.bundle"   ; bundle root
0x14051af52  "%s\\rootfs.vhdx"                   ; root filesystem disk
0x14051afb5  "%s\\vmlinuz"                       ; kernel
0x14051b01c  "%s\\initrd"                        ; initramfs
0x14051b082  "%s\\smol-bin.vhdx"                 ; userland/agent disk
0x14051b0e7  "%s\\sessiondata.vhdx"              ; writable session disk
```

Then it applies each piece to the `WindowsVMManager`, each with its own error
literal:

| Step | Setter | Error literal | Site |
|---|---|---|---|
| VHDX (rootfs) | `vm.(*WindowsVMManager).SetVHDXPath` | `failed to set VHDX path: %w` | 0x14051b613 |
| kernel | `SetKernelPath` | `failed to set kernel path: %w` | 0x14051b6ed |
| initrd | `SetInitrdPath` | `failed to set initrd path: %w` | 0x14051b7c8 |
| smol-bin | `SetSmolBinPath` | `failed to set smol-bin path: %w` | 0x14051b8a8 |
| session disk | `SetSessionDiskPath` | `failed to set session disk path: %w` | 0x14051bdb2 |
| memory | (memory setter) | `failed to set memory: %w` | 0x14051ca13 |
| CPUs | (CPU setter) | `failed to set CPU count: %w` | 0x14051caf0 |

Each setter re-validates the path with `vm.finalPath` @ `0x1404f2000` and
`vm.ValidateWritePath` @ `0x1404f2360`; failures read
`kernel not found: %s` (0x1404f45bc), `initrd not found: %s` (0x1404f495c),
`smol-bin not found: %s` (0x1404f4cfc), `session disk not found: %s`
(0x1404f509c), `%w: %s` (0x1404f388d).

Drive shares come next on the host side:

```
0x14051bea6  "no fixed drives found"                     ; vm.EnumerateFixedDrives returned nothing
0x14051c2d6  "failed to add drive share %s: %w"
0x14051c89d  "failed to add network-drive share %s: %w"
```

`vm.EnumerateFixedDrives` @ `0x1404e9160` walks drives; `vm.SystemDriveLetter`
@ `0x1404e90e0` reads the `SystemDrive` env var (literal at 0x1404e90ee).

`handleConfigure` also runs `CreateDynamicVHDXAsUser` (closure at
`0x14051cf40`) and `ValidateWritePathAsUser` (closure at 0x14051cf80), i.e. disk
creation and path validation happen **impersonating the calling user**, not as
LocalSystem. Clients that are not yet configured get
`not configured: call 'configure' first` from `dispatchVerified`
(cmp-guard at 0x1405196a8; literals 0x14073e1dc / 0x14073e1ee).

`configure` does **not** create the compute system.

---

## 3. `startVM` — create, start, share, wait for guest

Pipe handler `pipe.(*Server).handleStartVM` @ `0x14051d3c0` (960 bytes) takes
`pipe.StartVMParams` (type metadata 0x5ab866) and calls
`vm.(*WindowsVMManager).StartVM` @ `0x1404f6f20` (**10240 bytes**).

Emission markers prove the ordering (each is a `(step, status)` pair fed to
`vm.(*EventCallbacks).emitStartupStep`, thunk `-fm` @ 0x140506e60):

| Order | step | status | Site |
|---|---|---|---|
| 1 | `create_network` | `started` | 0x1404f7401 / 0x1404f740d |
| 1 | `create_network` | `completed` | 0x1404f740d |
| 2 | `create_vm_config` | `started` | 0x1404f7521 |
| 2 | `create_vm_config` | `completed` | 0x1404f76c6 / 0x1404f76d2 |
| 3 | `vm_boot` | `started` | 0x1404f8870 |
| 3 | `vm_boot` | `completed` | 0x1404f8958 / 0x1404f8964 |
| 4 | `add_plan9_shares` | `started` | 0x1404f89dc / 0x1404f89e8 |
| 4 | `add_plan9_shares` | `failed` | 0x1404f8ace |
| 5 | `guest_ready` | (in `StartVM.func2`) | 0x1404fa3ac |

Call sequence inside `StartVM` (direct calls, in order):

```
1.  vm.NewVirtualNetworkProvider            -> "failed to create virtual network: %w" (0x1404f7378)
2.  vm.(*VMConfig).BuildHCSDocument         (5760 bytes, @ 0x1404de6a0)
    encoding/json.MarshalIndent
3.  vm.CreateComputeSystem                  (@ 0x1404e4d00, 3488 bytes)
      -> "%w: failed to create compute system: %v" (0x1404f765f)
      on error: vm.(*WindowsVMManager).cleanupStartResources
4.  vm.(*HCSSystem).GetProperties           (poll for State)
      runtime.mapaccess1_faststr            ; reads the "State" property
5.  vm.ParseGUID                            (RuntimeId -> GUID)
6.  makechan / makemap_small ...            ; start the event fan-out
```

### 3a. The HCS document

`vm.(*VMConfig).BuildHCSDocument` @ `0x1404de6a0` (5760 bytes) is a pure JSON
builder. Its LEA-referenced keys, in emission order, are the HCS schema:

```
KernelFilePath, InitRdPath, KernelCmdLine, LinuxKernelDirect   (0x1404de8e3..)
Uefi, Type, Path, ReadOnly, SupportCompressedVolumes           (0x1404dea74..)
Attachments, "Primary SCSI Controller", Scsi                   (0x1404defb5..)
NamedPipe, Name, Ports, VirtioSerial                           (0x1404df12b..)
Plan9, BindSecurityDescriptor, ConnectSecurityDescriptor,
       AllowWildcardBinds, "0000c822-facb-11e6-bd58-64006a7986d3",
       DefaultBindSecurityDescriptor,
       DefaultConnectSecurityDescriptor, ServiceTable,
       HvSocketConfig, HvSocket                                 (0x1404df2e9..0x1404df74c)
Chipset, SizeInMB, AllowOvercommit, Memory                     (0x1404df7a8..)
Count, Processor, ComputeTopology, Devices                     (0x1404df963..)
Owner, Major, Minor, SchemaVersion,
       ShouldTerminateOnLastHandleClosed, VirtualMachine        (0x1404dfaf3..0x1404dfc91)
```

Notes that matter:

* `LinuxKernelDirect` means the guest boots a raw `vmlinuz` + `initrd`
  (no UEFI firmware), consistent with `vmlinuz` / `initrd` in the bundle.
* The GUID `0000c822-facb-11e6-bd58-64006a7986d3` is the Hyper-V **Virtio
  Serial / hvsock service GUID** used for the `ServiceTable`.
* `ShouldTerminateOnLastHandleClosed` is set, so the VM dies if the service's
  handle closes — the service is the VM's lifetime owner.
* `Owner` is emitted last; `BuildHCSDocument` therefore also encodes 9p/Plan9
  share definitions (`Plan9` → `Shares`).

### 3b. Creating the compute system

`vm.CreateComputeSystem` @ `0x1404e4d00`:

```
0x1404e4d9a  "failed to marshal config: %w"
0x1404e4e37  "invalid id: %w"
0x1404e4ed6  "invalid config: %w"
0x1404e59ec  "HCS not initialized - call InitHCS() first"
0x1404e599e  "HcsCreateOperation failed to create operation handle"
0x1404e5685  "HcsCreateComputeSystem failed with HRESULT 0x%x: %s"
0x1404e5805  "HcsWaitForOperationResult failed with HRESULT 0x%x: %s"
```

So: `HcsCreateOperation` → `HcsCreateComputeSystem(id, configJson, operation)` →
`HcsWaitForOperationResult(operation)`. The VM id is logged before the call as
`[HCS] Calling HcsCreateComputeSystem with id=%s` (file 0x7444e1).

### 3c. Starting it

`vm.(*HCSSystem).Start` @ `0x1404e5dc0` (1824 bytes):

```
0x1404e644c  "HcsCreateOperation failed"
0x1404e61cc  "HcsStartComputeSystem failed with HRESULT 0x%x: %s"
0x1404e6326  "HcsWaitForOperationResult failed with HRESULT 0x%x: %s"
```

`StartVM` wraps failure as `%w: failed to start VM: %v` (0x1404f8dbd) and
`%w: failed to start VM: %v [%s]` (0x1404f9009).

A specific HRESULT is singled out: `0xc03a001a` at 0x1404f8d27
(`ERROR_VHD_SHARED` / disk-in-use style failure). It is compared as the retry
signal after `HcsStartComputeSystem`.

### 3d. Plan9 shares (the host<->guest filesystem bridge)

`vm.(*HCSSystem).AddPlan9Share` @ `0x1404e8520` (512 bytes) marshals a Plan9
share config (`failed to marshal Plan9 share config: %w`, 0x1404e863e) and
applies it with `HcsModifyComputeSystem` (see 3e).

`vm.(*WindowsVMManager).AddPlan9Share` @ `0x1404f5240` (3616 bytes) decides whether to add,
update, or skip:

```
0x1404f54a2  "share path not found: %s"
0x1404f579f  "same"        ; already configured identically
0x1404f589a  "updated"
0x1404f5a01  "added"
```

Shares are only added when the service holds a user token:
`cannot add Plan9 shares without a user token` (0x1404f8b44). The log line is
`[VM] Adding Plan9 share via HcsModifyComputeSystem: name=%s path=%s port=%d flags=0x%x hasToken=%v`
(closure `StartVM.(*HCSSystem).shareAdder.func30` @ 0x1404f99d3).

After the shares are configured the service verifies the guest actually mounted
them: `vm.(*WindowsVMManager).settleGuestShares` @ `0x1404fb0c0` (1344 bytes) emits
`guest did not report the shares mounted` (0x1404fb1f1) and
`host drive share %q not mounted: %s` (0x1404fb4bc).

### 3e. Runtime modification

`vm.(*HCSSystem).ModifyComputeSystem` @ `0x1404e7b20` (2048 bytes) is the single
`HcsModifyComputeSystem` wrapper:

```
0x1404e7c39  "invalid configuration: %w"
0x1404e81d6  "HcsModifyComputeSystem failed with HRESULT 0x%x (result len=%d)"
0x1404e8281  "HCS not initialized - HcsModifyComputeSystem not available"
```

### 3f. What `startVM` waits for

`vm.(*WindowsVMManager).IsRunning` @ `0x1404fd040` (768 bytes) reads the `State` property
(literal at 0x1404fd187) and compares it to the running state. `IsGuestConnected`
@ `0x1404fd580` is what the pipe's `isGuestConnected` method calls. `guest_ready`
(0x1404fa3ac) is emitted from `StartVM.func2` — i.e. StartVM does not return until
the guest has connected back over vsock or the wait fails.

---

## 4. `stopVM` — terminate, release, stop console

Pipe handler `pipe.(*Server).handleStopVM` @ `0x14051d7e0` (352 bytes) wraps the
call in `context.WithTimeout` and calls `vm.(*WindowsVMManager).StopVM`
@ `0x1404fc560` (1728 bytes).

`StopVM` call order (direct calls):

```
sync.(*RWMutex).Lock
log
runtime.makechan / runtime.newproc        ; async terminate
time.NewTimer / runtime.selectgo          ; bounded wait
vm.(*HCSSystem).Terminate                 ; up to three call sites (retry path)
vm.(*WindowsVMManager).releaseResources
vm.(*WindowsVMManager).stopConsoleReader
```

`vm.(*HCSSystem).Terminate` @ `0x1404e6be0` (1152 bytes):

```
0x1404e6fdc  "HcsCreateOperation failed"
0x1404e6e82  "HcsTerminateComputeSystem failed with HRESULT 0x%x/0x%x: %s"
```

The `0x%x/0x%x` pair is `(hr, win32err)` — the code resolves both.

A *graceful* sibling exists: `vm.(*HCSSystem).Shutdown` @ `0x1404e6680`
(1152 bytes) calls `HcsShutdownComputeSystem`
(`HcsShutdownComputeSystem failed with HRESULT 0x%x/0x%x`, 0x1404e6922).
`StopVM` uses **Terminate**, not Shutdown — the VM is killed, not asked to
power off.

`vm.(*WindowsVMManager).cleanupStartResources` @ `0x1404fc340` (224 bytes) is the
error-path cleanup and calls exactly two things:

```
vm.(*VirtualNetworkProvider).Stop
vm.(*RPCServer).Stop
```

so a failed `startVM` leaves no HCN network and no vsock listener behind.

---

## 5. Idle teardown

`pipe.(*Server).checkIdleSessions` @ `0x140514560` (2816 bytes) runs from
`pipe.(*Server).idleSessionChecker` @ 0x140514340 (started by `Server.Start`).
It iterates sessions, and for each computes
`time.Now().Sub(lastUse)` and consults:

```
pipe.(*vmSession).subscriberCount      ; how many event subscribers are attached
vm.(*WindowsVMManager).IsRunning       ; is the VM actually up
vm.(*WindowsVMManager).HasUnreleasedResources
time.Duration.Round
```

Sessions with zero subscribers, a running VM, and no unreleased resources are
torn down (`stopAllSessions` @ 0x140515420, `Server.Stop` @ 0x1405151e0).

---

## 6. Console / log channel

`vm.(*ConsoleReader)` is a second channel into the VM, used for the serial
console (COM1 → `\\.\pipe\cowork-daemon-console`):

* `vm.(*ConsoleReader).Start` @ 0x1404dfde0 (224 bytes) spawns
  `readLoop` @ 0x1404dff20 (1504 bytes).
* `readLoop` calls `vm.(*ConsoleReader).connectPipe` @ 0x1404e0680 which calls
  `github.com/Microsoft/go-winio.DialPipeContext` in a `context.WithTimeout`.
* Log records are buffered by `pipe.(*guestLog).append` @ 0x14050f480 and drained
  by `pipe.(*guestLog).take` @ 0x14050f6a0. Backpressure produces
  `"[Console] %d bytes dropped here: the app was not taking the VM's log and the buffer was full"`
  (0x14050f53a) and `[logsink] dropped %d message(s): log destination not keeping up`
  (0x14050f233 from `logsink.(*Writer).reportDrops`).

---

## 7. Full lifecycle, condensed

```
configure   -> resolve %s\vm_bundles\claudevm.bundle
            -> validate rootfs.vhdx / vmlinuz / initrd / smol-bin.vhdx / sessiondata.vhdx
            -> CreateDynamicVHDXAsUser(sessiondata.vhdx, impersonating caller)
            -> set memory/CPU
            -> AddPlan9Share per fixed drive + network drive
            -> (no HCS call yet)

startVM     -> NewVirtualNetworkProvider          (create_network / started)
            -> BuildHCSDocument -> MarshalIndent  (create_vm_config / started)
            -> CreateComputeSystem (HcsCreateComputeSystem)
            -> CreateComputeSystem returns         (create_vm_config / completed)
            -> HCSSystem.Start (HcsStartComputeSystem)  (vm_boot / started)
            -> HCSSystem.GetProperties (poll State)     (vm_boot / completed)
            -> AddPlan9Share via HcsModifyComputeSystem (add_plan9_shares / started)
            -> NewHVSocketListener + RPCServer.Start
            -> wait for guest_ready
            -> returns; isRunning -> true, isGuestConnected -> true

stopVM      -> context.WithTimeout
            -> HCSSystem.Terminate (HcsTerminateComputeSystem)   [not Shutdown]
            -> releaseResources
            -> stopConsoleReader
```

---

## 8. UNRESOLVED

* `vm.(*WindowsVMManager).releaseResources` body was not disassembled in this
  pass; the name is from pclntab only.
* The `0xc03a001a` comparison at 0x1404f8d27 is a 4-byte immediate compared
  against the HRESULT; the surrounding branch structure was read but the exact
  retry count for the disk-in-use path was not recovered.
* `guest_ready`'s `(step, status)` argument pair lives in a closure built at
  0x1404fa3ac; the values were not extracted without full register flow.
