# SSH-HELPERS.md — claude-ssh-broker / claude-ssh-proxy / claude-ssh-askpass

All three are Go 1.25.14, PE x64 CUI, module
`github.com/anthropics/ssh-askpass`, built with `-trimpath=true`, `CGO_ENABLED=0`.
None statically imports anything beyond `kernel32.dll` (46 functions, the standard
Go runtime set). All Windows-specific behaviour goes through `golang.org/x/sys/windows`
and `github.com/Microsoft/go-winio`.

| Binary | Size | pclntab | funcs | Module path (buildinfo) |
|---|---|---|---|---|
| `claude-ssh-broker.exe` | 2,599,248 | file 0x189b60 | 2786 | `.../cmd/claude-ssh-broker` |
| `claude-ssh-proxy.exe` | 1,976,144 | file 0x127d80 | 2186 | `.../cmd/claude-ssh-proxy` |
| `claude-ssh-askpass.exe` | 2,648,912 | file 0x191880 | 2865 | `.../cmd/claude-ssh-askpass` |

Only `claude-ssh-broker` and `claude-ssh-askpass` depend on `go-winio` v0.6.2
(they use named pipes); `claude-ssh-proxy` depends only on `golang.org/x/sys`.

---

## 1. `claude-ssh-broker.exe` — the credential custodian

Manifest role: no `Application` entry for the broker; it is launched by the app
(or by `claude-ssh-proxy`) and holds the SSH passphrase / key-ask flow.

Entry point chain: `main.main` @ `0x1400fc920` (64 bytes) → `main.run`
@ `0x1400fc960` (1664 bytes) → `main.serve` @ `0x1400fd320` (1376 bytes).

Key functions (all pclntab-confirmed):

| Function | Entry | Size | Purpose |
|---|---|---|---|
| `main.listenOwnerOnly` | 0x1400fbb20 | 320 | create the pipe with an owner-only DACL |
| `main.selfCreated` | 0x1400fbc60 | 160 | did we create it (vs. attach) |
| `main.currentUserSid` | 0x1400fbd00 | 160 | caller SID for the ACL |
| `main.clientIdentity` | 0x1400fbda0 | 1440 | identify the connecting process |
| `main.parentTable` | 0x1400fc380 | 544 | snapshot the process table to walk parents |
| `main.imageAndCreation` | 0x1400fc600 | 704 | image path + creation time of a pid |
| `main.run` | 0x1400fc960 | 1664 | main loop |
| `main.serve` | 0x1400fd320 | 1376 | per-connection handler |
| `main.(*connTable).put/drop/answer/closeAll` | 0x1400fd8e0… | | in-flight askpass requests |
| `main.(*lineWriter).write` | 0x1400fddc0 | 416 | line-oriented framing |

Security-relevant literals:

```
0x1400fbbe1  "cannot create the pipe: %v"
0x1400fbd50  "cannot read the process token: %v"
0x1400fbe30  "cannot identify the pipe client: %v"
0x1400fbea9  "cannot open the pipe client: %v"
0x1400fc484  "cannot snapshot processes: %v"
0x1400fcc71  "listening"
0x1400fcd3e  "created"
```

The `listening`/`created` pair at 0x1400fcc71 / 0x1400fcd3e is the stdout
handshake the app parses to learn the broker is ready and whether it created the
pipe or attached to an existing one.

## 2. `claude-ssh-proxy.exe` — ProxyCommand runner

Manifest role: registered as `claude-ssh-proxy.exe` execution alias, no AppListEntry.
Purpose: run an SSH `ProxyCommand` in a kill-on-close Job Object so the child
dies with the proxy.

Entry: `main.main` @ `0x1400c1e00` → `main.run` @ `0x1400c1e60` (576 bytes).

| Function | Entry | Size | Purpose |
|---|---|---|---|
| `main.readCommandFile` | 0x1400c20a0 | 512 | read the ProxyCommand text from a file |
| `main.scrubEnvironment` | 0x1400c22a0 | 1280 | strip askpass vars before exec |
| `main.runProxyCommand` | 0x1400c27a0 | 2400 | spawn + wait |
| `main.killOnCloseJob` | 0x1400c31c0 | 352 | create/configure the Job Object |
| `main.createEnvBlock` | 0x1400c3320 | 800 | build CREATE_UNICODE_ENVIRONMENT block |
| `main.envName` | 0x1400c3720 | 192 | case-insensitive env-name compare |

Literals:

```
0x1400c1e81  "CLAUDE_SSH_ASKPASS_RELAY"
0x1400c20e0  "cannot read the command file: %v"
0x1400c21db  "command file holds a NUL byte"
0x1400c2217  "command file is empty"
0x1400c223f  "command file too large"
0x1400c2351  "SSH_ASKPASS"
0x1400c2377  "SSH_ASKPASS_PROMPT"
0x1400c239a  "SSH_ASKPASS_REQUIRE"
0x1400c23e0  "CLAUDE_SSH_ASKPASS_BROKER"
0x1400c2603  "none:ccd-ssh-askpass"
0x1400c2829  "command is not valid text: %v"
0x1400c2913  "; running the command outside a job"
0x1400c2bc8  "cannot start the ProxyCommand: %v"
0x1400c2ea8  "waiting for the ProxyCommand: %v"
0x1400c2f88  "reading the ProxyCommand's exit code: %v"
```

The `none:ccd-ssh-askpass` literal at 0x1400c2603 is the `SSH_ASKPASS_REQUIRE`
value written into the child environment (`none` disables askpass in the child;
`ccd-ssh-askpass` names the helper). `scrubEnvironment` removes
`SSH_ASKPASS*` and `CLAUDE_SSH_ASKPASS_*` from the inherited block so the child
cannot reach the broker directly.

## 3. `claude-ssh-askpass.exe` — the askpass shim

Manifest role: its own `Application` (`Id="SshAskpass"`) with alias
`claude-ssh-askpass.exe`, `AppListEntry="none"`. This is the program OpenSSH
invokes via `SSH_ASKPASS`.

Entry: `main.main` @ `0x140102d80` → `main.run` @ `0x140102dc0` (2720 bytes).

| Function | Entry | Size | Purpose |
|---|---|---|---|
| `main.promptText` | 0x140101780 | 160 | derive the prompt from argv |
| `main.skipProgramToken` | 0x140101820 | 320 | skip argv[0]-style token |
| `main.dialRelay` | 0x140101960 | 256 | connect to the relay pipe |
| `main.verifyServer` | 0x140101a60 | 2112 | verify the pipe **server** identity |
| `main.imagePath` | 0x140102300 | 224 | image path for a pid |
| `main.ancestry` | 0x1401023e0 | 1568 | walk parent chain |
| `main.terminateParent` | 0x140102a60 | 160 | |
| `main.readRelayFile` | 0x140102b60 | 544 | |
| `main.run` | 0x140102dc0 | 2720 | main flow |
| `main.fail` | 0x1401038c0 | 256 | print `claude-ssh-askpass: ` + msg |

Literals:

```
0x140102df8  "CLAUDE_SSH_ASKPASS_RELAY"
0x140102e12  "SSH_ASKPASS_PROMPT"
0x140102f17  "CLAUDE_SSH_ASKPASS_BROKER"
0x14010324e  "cannot encode the request"
0x140103764  "unreadable answer from the relay"
0x1401037b1  "no answer from the relay"
0x1401038e9  "claude-ssh-askpass: "
0x140101c8d  "cannot identify the pipe server: %v"
0x140101d09  "cannot open the pipe server: %v"
0x140101dd8  "cannot read the pipe server's times: %v"
0x140101e7c  "cannot read the pipe server's image: %v"
0x140101f4a  "cannot read this helper's image: %v"
0x140102030  "the pipe is served by process %d, not the connection's broker"
0x140102116  "claude-ssh-broker"
```

`verifyServer` is the anti-spoofing core: it compares the pipe server's process
image name against `claude-ssh-broker` and checks the server's creation time
against what the caller expects, so a rogue process cannot squat the relay pipe
and harvest passphrases. `main.ancestry` then walks the parent chain to confirm
the askpass was invoked by an expected SSH process.

## 4. Trust chain, condensed

```
ssh (user's OpenSSH)
  -> executes claude-ssh-askpass.exe (SSH_ASKPASS)
       -> verifies the relay pipe's server is claude-ssh-broker   (verifyServer)
       -> verifies its own ancestry                                (ancestry)
       -> sends the askpass request over the relay pipe
            -> claude-ssh-broker  (holds the credential, owner-only pipe DACL)
                 -> answers over the same line-oriented channel
  <- passphrase returned to ssh
```

and separately:

```
ssh -o ProxyCommand="claude-ssh-proxy <file>"
  -> claude-ssh-proxy reads the command file
       -> scrubs SSH_ASKPASS* from the child env
       -> spawns the ProxyCommand in a kill-on-close Job Object
       -> waits, propagates the exit code
```

## 5. UNRESOLVED

* The relay pipe **name** was not recovered as a literal. `dialRelay` and
  `listenOwnerOnly` both take the pipe path as a parameter and no `\\.\pipe\...`
  string exists in any of the three binaries (verified by regex over the whole
  file). The path is supplied by the parent (the broker is launched with it, or
  it is passed via `CLAUDE_SSH_ASKPASS_RELAY`).
* The exact JSON schema of the askpass request/response was not extracted; only
  the `cannot encode the request` / `unreadable answer from the relay` error
  paths prove the payload is encoded (likely JSON given the module's use of
  `encoding/json`, but not verified).

---

## 补充：broker 的进程结构与身份校验（pclntab 级）

`claude-ssh-broker.exe` 的 `main` 包共 **31 个函数**，全部可命名：

| 函数 | 入口 | 大小 | 职责 |
|---|---|---:|---|
| `main.listenOwnerOnly` | `0x1400fbb20` | 320 | **只允许属主连接**的监听 |
| `main.currentUserSid` | `0x1400fbd00` | 160 | 取当前用户 SID |
| `main.clientIdentity` | `0x1400fbda0` | **1,440** | **校验客户端身份**（最大函数之一） |
| `main.parentTable` | `0x1400fc380` | 544 | **父进程表**（判断调用者父进程合法性） |
| `main.imageAndCreation` | `0x1400fc600` | 704 | 取进程映像路径与创建时间 |
| `main.selfCreated` | `0x1400fbc60` | 160 | 判断是否为自身创建 |
| `main.run` | `0x1400fc960` | 1,664 | 主循环 |
| `main.serve` | `0x1400fd320` | 1,376 | 服务循环 |
| `main.(*connTable).put/drop/answer/closeAll` | — | 256/224/**480**/288 | **连接表**：登记、移除、**应答**、全关 |
| `main.(*lineWriter).write` | `0x1400fddc0` | 416 | 行写出 |
| `main.heldConn.*` | — | 96–160 | 被挂起的连接（带 deadline） |

### 三条可确认的安全设计

1. **`listenOwnerOnly` + `currentUserSid`** —— 管道只允许**同属主**连接（不是任意同机用户）。
2. **`clientIdentity` + `parentTable` + `imageAndCreation`** —— 不仅校验客户端进程，还检查**父进程链**与映像创建时间，用于识别伪造。
3. **`connTable.answer`** —— 连接被"挂起等待应答"是有状态的（`heldConn` + deadline），说明交互是**请求-应答**而非纯转发。

### 帧上限的诚实结论

对 `main.serve`（1,376 B）与 `main.run`（1,664 B）做了 `cmp reg, imm32` 全扫描，只得到若干**非整数常量**（`0x15a068`、`0x1b1a36`、`0x1b223f` 等），它们是偏移/类型指针而非尺寸上限。

因此 **`helper frame over cap` 的上限值不在代码里内联**，而是存放在数据段的可变参数（很可能来自配置或 `bufio.Scanner` 的 max token size 默认值）。

**`U-035` 保持 PARTIAL**，不做编造。要得到具体数值需对该比较点做动态调试或更深的数据流分析。
