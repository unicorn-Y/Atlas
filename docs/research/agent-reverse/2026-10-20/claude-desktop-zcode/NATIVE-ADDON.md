# NATIVE-ADDON.md — `claude-native-binding.node`

Target: `app.asar.unpacked/node_modules/%40ant/claude-native/claude-native-binding.node`
(3,778,896 bytes, PE32+ x64 DLL, image base `0x180000000`).

The addon is a **Rust cdylib** built with `napi-rs` (not a C++ N-API addon).
Evidence: embedded crate path
`registry/src/index.crates.io-1949cf8c6b5b557f/napi-2.16.17/src/bindgen_runtime/module_register.rs`
at file 0x2bb600, plus Rust panic strings (`called Result::unwrap() on an Err value`,
`PoisonError`) and Rust source basenames in `.rdata`.

---

## 1. PE exports

The export table has exactly **one** entry:

| Name | Ordinal | RVA | VA |
|---|---|---|---|
| `napi_register_module_v1` | 0 | 0x1e10c0 | 0x1801e10c0 |

This is the N-API module-registration entry point. `node` calls it once with an
`napi_env` and an exports object; the addon then calls `napi_create_function` /
`napi_set_named_property` for every registered binding.

Disassembly of `0x1801e10c0` shows the standard napi-rs bootstrap: a call to
`0x1801ec920` (module-init helper), a `cmp qword [rbp+0x170], -1` guard, and
`gs:[0x58]`-relative TLS access — i.e. the napi-rs `Env`/`ModuleRegister`
machinery, not a hand-written `napi_define_properties` table.

## 2. How the export names were recovered

napi-rs emits, for every `#[napi]` function, the pair:

```
<jsCamelCaseName>\0Failed to register function `<rust_snake_case_name>`\0
```

in `.rdata`. Example at file 0x2a2507:

```
... cuIsRemoteSession\0Failed to register function `cu_is_remote_session`cuListOpenWindows\0Failed to register function `cu_list_open_windows` ...
```

Regexing `Failed to register function \x60([a-z0-9_]+)\x60` and converting
snake_case → lowerCamelCase recovers the JS-visible name for each binding.
**109 registrations** were recovered this way; the full list is in
`NATIVE-ADDON-EXPORTS.tsv`.

This mapping was independently confirmed against the packed asar: the shipped JS
calls `native.cuListOpenWindows()`, `native.cuGetOwnBundleId()` and
`native.getActiveWindowHandle()` (asar file offsets 0x116bd7a and 0x2ea499).

## 3. JS-visible function surface (109 exports)

Grouped by area, all names verbatim from the registration strings:

### Window / app enumeration (`cu*` = "computer use")
```
cuListOpenWindows, cuListRunningApps, cuListInstalledApps, cuGetAppIcon,
cuListDisplays, cuAppUnderPoint, cuDisplayForPid, cuFocusedControl,
cuControlAtPoint, cuGetOwnBundleId, cuIsRemoteSession, cuWindowsDirectory,
cuMaskedWindowRects, cuExcludedWindowRects, cuHideApps, cuUnhideApps
```

### Window manipulation
```
getActiveWindowHandle, getWindowAbove, moveWindowBehind, focusWindow,
getFrontmostAppInfo, isOtherAppFullscreen, getWindowsElevationType,
enumerateNetworkDrives
```

### Process inspection
```
getProcessLineage, readProcessTree, readProcessFootprints,
readProcessCreationTime, isProcessRunning, isProcessInAppJob, joinAppJob,
readConsoleClients, readOwnMemoryComposition, prefetchProcessPrivateMemory
```

### Sandboxed filesystem (`*Beneath` = relative to an opened root dir handle)
```
openRootDir, openBeneath, statBeneath, mkdirBeneath, rmdirBeneath,
renameBeneath, unlinkBeneath, cloneAt, materializeDatalessFile,
readFreshUserPath, readUserPathValueRaw, writeUserPathValueRaw
```

### Registry
```
readRegistryValues, enumRegistryValues, enumRegistrySubkeys,
writeRegistryValue, writeRegistryDword, deleteRegistryKey
```

### Services / packages / elevation
```
queryWindowsServiceState, startWindowsService, getCurrentPackageFamilyName,
isCurrentPackageBeingServiced, enableWindowsOptionalFeature
```

### Windows Hello / hardware keys
```
promptWindowsHello, cancelWindowsHello, windowsHelloAvailability,
hardwareKeySign, hardwareKeyGetOrCreate
```

### Input synthesis / screen
```
typeText, typeTextPaced, moveMouse, mouseButton, mouseScroll, mouseLocation,
validateKeys, key, keys, encodeFrameJpeg
```

### Accessibility / "sable otter" (screen reader bridge)
```
sableOtterStart, sableOtterStop, sableOtterProbe, sableOtterSwallow,
sableOtterSwallowOff, sableOtterSetKeys, sableOtterReadWindow,
sableOtterLastResultBeforeCaret
```

### Voiceover / audio capture
```
watchVoiceoverStart, watchVoiceoverStop, watchVoiceoverStartPreview,
watchVoiceoverStopPreview, watchVoiceoverSubscribePcm,
watchVoiceoverSubscribeMicState, watchVoiceoverListInputDevices,
watchVoiceoverSubscribeDiagnostics
```

### Recorder / timers
```
watchRecorderStart, watchRecorderStop, watchRecorderSubscribe,
watchRecorderNowT, wakeTimerSchedule, wakeTimerCancel, wakeTimerSupported
```

### Named pipes / IPC / DPAPI
```
connectNamedPipeSystemOwned, connectNamedPipeSameUserOwned,
userDpapiProtect, userDpapiUnprotect
```

### Office integration
```
closeOfficeDocument, focusOfficeDocument
```

### Misc / platform stubs
```
getHcsStatus, readPlistValue, parsePlistValue, readMacSessionState,
listTcpListeners, attestedMachRequest, applyVmImageDelta
```

Note the macOS-named entries (`readMacSessionState`, `readPlistValue`,
`parsePlistValue`, `attestedMachRequest`) are present in the **Windows** binary;
the string `Web authentication is not available on this platform` (file 0x29e000-ish)
shows they are cross-platform API stubs.

## 4. Import surface (the real Windows capability set)

22 DLLs, 228 imports. The interesting ones for capability analysis:

| DLL | Imports | What it enables |
|---|---|---|
| `user32.dll` (51) | `SendInput`, `EnumChildWindows`, `GetGUIThreadInfo`, `EnumDisplayMonitors`, `GetWindowTextW`, `MonitorFromWindow`, `GetIconInfo` | synthetic input, window enumeration, screen capture |
| `advapi32.dll` (19) | `OpenSCManagerW`, `OpenServiceW`, `StartServiceW`, `QueryServiceStatus`, `RegOpenKeyExW`, `RegDeleteKeyW`, `GetTokenInformation`, `ConvertSidToStringSidW`, `GetSecurityInfo` | service control, registry write, token inspection |
| `ntdll.dll` (7) | `NtCreateFile`, `NtReadFile`, `NtWriteFile`, `NtQueryInformationFile`, `NtSetInformationFile`, `NtQueryInformationProcess` | relative-handle filesystem ops (`*Beneath`), process lineage |
| `ncrypt.dll` (7) | `NCryptOpenStorageProvider`, `NCryptCreatePersistedKey`, `NCryptSignHash`, `NCryptExportKey` | Windows Hello key material, TPM-backed signing |
| `crypt32.dll` (2) | `CryptProtectData`, `CryptUnprotectData` | DPAPI (`userDpapiProtect`) |
| `shell32.dll` (4) | `SHGetKnownFolderPath`, `SHGetKnownFolderItem`, `ShellExecuteExW`, `SHGetFileInfoW` | app info, file associations |
| `dwmapi.dll` (3) | `DwmSetWindowAttribute`, `DwmGetWindowAttribute`, `DwmFlush` | window z-order / composition |
| `iphlpapi.dll` (1) | `GetExtendedTcpTable` | `listTcpListeners` |
| `mpr.dll` (3) | `WNetOpenEnumW`, `WNetEnumResourceW`, `WNetCloseEnum` | `enumerateNetworkDrives` |
| `powrprof.dll` (4) | `PowerGetActiveScheme`, `PowerReadACValueIndex`, `GetPwrCapabilities` | power/timer behaviour |
| `userenv.dll` (2) | `CreateEnvironmentBlock`, `DestroyEnvironmentBlock` | launching helpers in user context |
| `bcryptprimitives.dll` (1) | `ProcessPrng` | CSPRNG (Rust `getrandom`) |
| `api-ms-win-core-winrt-l1-1-0.dll` (1) | `RoGetActivationFactory` | WinRT (Windows Hello UI) |

## 5. Not resolved

* The exact `napi_value` each export receives (arity and argument structs) was
  not recovered: napi-rs builds per-function argument extraction inline and the
  `.rdata` carries the JS/Rust name pairs but not parameter schemas. The
  snake_case names strongly imply the argument shape for each (`cu_hide_apps`
  takes a list of `hwnd`; `type_text` takes a string; etc.) but this is
  inference, not extracted fact.
* `napi_register_module_v1`'s call graph was only partially walked; the exact
  order of the 109 `napi_create_function` calls was not reconstructed.
