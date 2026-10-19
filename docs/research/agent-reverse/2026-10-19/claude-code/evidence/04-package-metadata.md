# Package metadata and wrapper behavior

## Core package: `@anthropic-ai/claude-code@2.1.302`

`package/package.json` identifies `bin.claude = bin/claude.exe`, `postinstall = node install.cjs`, `prepare` gated by `AUTHORIZED`, Node `>=22`, `type=module`, no direct dependencies, and platform optional dependencies at the exact same version for Darwin/Linux/Windows x64 and arm64 (plus Linux musl variants). Its `files` list publishes the 500-byte Windows shim, `install.cjs`, `cli-wrapper.cjs`, and `sdk-tools.d.ts`. License: `SEE LICENSE IN README.md`; the shipped license text says all rights reserved and refers to Anthropic's legal agreements.

## Win32 package: `@anthropic-ai/claude-code-win32-x64@2.1.302`

`package/package.json` pins `os: win32`, `cpu: x64`, and publishes only `claude.exe`, README, and LICENSE. The native binary's Windows version resource reports FileVersion/ProductVersion `2.1.302.0`, Company `Anthropic PBC`, Description `Claude Code`.

## Verified execution path

- `package/install.cjs:1-6,69-103,105-150,152-163,165-239`: postinstall detects OS/arch, resolves the matching optional dependency, selects `claude.exe`, and first attempts `linkSync` into `bin/claude.exe`, falling back to a copy on cross-device/no-link-permission. Thus the ordinary installed command invokes the native binary directly, without retaining Node as the supervisor.
- `package/install.cjs:152-163,169-228`: missing native package prints install guidance; `FAIL_ON_MISSING_NATIVE` is substituted at build time (the archived template literal is `false`), and can fail the install except when optional dependencies are explicitly omitted.
- `package/cli-wrapper.cjs:1-7,50-78,83-125,131-155`: the manual fallback detects platform, resolves the package executable through `require.resolve`, launches it with inherited stdio and `CLAUDE_CODE_INSTALLED_VIA_NPM_WRAPPER=1`, maps signal exits to `128 + signal`, and propagates native exit status.
- The archived `package/bin/claude.exe` is a 500-byte placeholder/shim; it is not the actual product executable. The platform package's 290,211,488-byte PE is the real executable analyzed here.

## SDK declarations are not proof of CLI call sites

The core package also ships a 4,223-line `sdk-tools.d.ts`. Its public type surface includes `AgentInput` (lines 772-812: background by default, named addressable agent via `SendMessage`, optional worktree/remote isolation), `TaskCreate/Get/Update/ListInput` (2802-2868), `WorkflowInput` (2869-2900: persisted script path and same-session resumable run ID), and typed task status/result shapes (4005-4038). These declarations are strong evidence that the published SDK surface defines those contracts; they do not by themselves establish which functions the standalone CLI calls at runtime.

