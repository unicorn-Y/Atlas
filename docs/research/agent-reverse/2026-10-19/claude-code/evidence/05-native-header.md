# Native executable format and container evidence

Artifact: `package/claude.exe`, 290,211,488 bytes, SHA256 `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae` (version resource: 2.1.302.0, Anthropic PBC).

Independent PE parsing and resource-table inspection agree:

- DOS `e_lfanew=120`; signature `PE\0\0`; COFF machine `0x8664` (AMD64), 13 sections; PE32+ optional header `0x20b`; Windows subsystem `3` (console); image base `0x140000000`; entry RVA `0x054bb9cc`.
- Sections (name, RVA, virtual bytes, raw file offset, raw bytes): `.text` 0x1000 / 91,410,338 / 0x400 / 91,410,432; `.rdata` 0x0572c000 / 23,492,960 / 0x0572be00 / 23,493,120; `.data` 0x06d9d000 / 2,334,464 / 0x06d9ce00 / 121,344; `.pdata` 0x06fc9000 / 1,222,860 / 0x06fc8e00 / 1,223,168; `.bunblt` 0x070e0000 / 2,649,516 / 0x06fe4000 / 2,649,600; `.fptable` 0x07362000 / 256 / 0x07188000 / 512; `.tls` 0x07363000 / 23,401 / 0x07188200 / 23,552; `_RDATA` 0x07369000 / 500 / 0x0718e000 / 512; two `__DATA,_` sections each 16,384 bytes; `.rsrc` 200,748 bytes; `.reloc` 260,272 bytes; `.bun` raw file offset `0x071e2c00`, 170,783,232 raw bytes (the largest section; embedded Bun payload). The executable is a standalone Bun-compiled PE, not a JS launcher or Node-only package. Static `bun-v1.4`/`B:/~BUN/root/chunk-*.js` strings corroborate Bun and embedded JS chunk naming.
- Imports include `kernel32.dll` (338 entries, including `CreatePseudoConsole`, `CreateNamedPipe*`, `ConnectNamedPipe`, `CreateProcessW`, `CreateJobObject*`, `AssignProcessToJobObject`), `ntdll.dll` (34), `api-ms-win-core-synch-l1-2-0.dll` (3), `bcryptprimitives.dll` (1), `fwpuclnt.dll` (13 Windows Filtering Platform APIs), `netapi32.dll` (10 local user/group APIs), and `bcrypt.dll` (1). These are runtime import facts only: individual API imports do not prove a Claude feature uses them.
- Complete bounded PE resource inventory: 18 leaves. Type 3 numeric IDs 1-14 are icon payloads; type 14 includes named `IDI_MYICON`; type 16 is a 928-byte version resource; type 24 is a 1,474-byte manifest. All inspected leaves report language ID 1033. Resources other than the parsed version fields/icon grouping are not decoded here.

Coverage limit: no disassembly/decompilation or imported-call xrefs were recovered. Section presence, imports, strings and entry RVA are structural evidence, not an execution trace.

