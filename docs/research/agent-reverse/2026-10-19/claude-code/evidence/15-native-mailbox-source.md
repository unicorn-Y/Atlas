# Exact embedded mailbox source: write, read, acknowledge

- Package: `@anthropic-ai/claude-code-win32-x64@2.1.302`, member `package/claude.exe`.
- SHA-256: `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae` (290,211,488 bytes).
- Source: readable embedded Bun application-JS in the PE `.bun` payload. The excerpts were obtained by seeking the exact local executable to these file offsets; they are not native disassembly.
- Method: bounded direct byte extraction from the exact SHA-pinned artifact, after the REA full-PE function inventory timeout and a stalled REA literal search. Decimal offsets permit mechanical rechecking.

## Path derivation and read

At byte offset **248,019,409** (`0x0ec879d1`), `vj(e,n)` derives an inbox path under the application data root, team-scoped (or current session/default), ending in `inboxes/<sanitized-agent>.json`. `S8e(e,n,r,s)` begins at byte offset **248,020,900** (`0x0ec87fa4`). Its visible source reads through the v5 storage adapter when available, otherwise filesystem `read`; it parses and validates with `Re`, reports and drops invalid entries, supplies legacy `type="message"` when absent, maps absent file or syntax error to `[]`, and only rethrows other read errors when `throwOnUnknownReadError` is set. `w8e` filters to unread messages.

## Writer

`async function Zw(e,n,r,s)` starts at byte offset **248,022,054** (`0x0ec88426`). Exact source fragments:

```js
async function Zw(e,n,r,s){let c=Ve().safeParse(n);if(!c.success){...;return}let y=W()&&s!==void 0?ee(e,r):void 0;if(W()&&s!==void 0&&y!==void 0){let w={...n,...s3(),type:"message",read:!1},S=$t(y,e,r);try{return await te(s,y,S,(E)=>(z().record(S,w),{messages:[...E.messages,w],result:!0})),...,w.msg_id}catch(E){...;return}}
```

The file path branch visible at that offset ensures the inbox directory, computes path and `.lock`, attempts exclusive create of `[]` (tolerating only `EEXIST`), acquires `dl(path,{lockfilePath,...V})`, reads/validates prior entries via `S8e`, appends `{...message,...s3(),type:"message",read:false}`, records it in the in-memory index, and writes JSON via `atomicWrite`. If the write fails it retires the just-added index record. A `finally` releases the lock via `zm`. Only after the write does it return `msg_id`. The storage-v5 path performs the append through the `updateText` transaction callback.

## Acknowledgement and clear

- Single-message removal: `async function RRr(e,n,r,s)` begins at byte offset **248,024,280** (`0x0ec88d38`). Under lock it reloads the inbox, matches an unread record by `from`, `timestamp`, and `text`, removes it if found, atomically writes remaining unread entries, updates cache retention and releases the lock. The storage route uses an equivalent `te` transform.
- Bulk prune: `async function gOe(e,n,r,s)` begins at byte offset **248,025,672** (`0x0ec892a8`). It reloads under lock, computes delivered unread records and atomically persists survivors; optional message keys preserve selected records. Missing file clears cache and returns success. A storage-adapter equivalent exists.
- Clear: `async function WWn(e,n,r)` begins at byte offset **248,027,467** (`0x0ec8994b`). It writes `[]` under lock or atomically replaces via the storage adapter.
- Helper `te` serializes storage-adapter read-modify-write with `updateText`; helper `j` updates the in-memory message-ID retention index after file changes.

These excerpts establish static client operations; they do not prove exactly-once delivery, crash durability of the underlying filesystem/store, interprocess lock correctness, parent notification, or observed next-turn handling. No live team mailbox was accessed or modified.
