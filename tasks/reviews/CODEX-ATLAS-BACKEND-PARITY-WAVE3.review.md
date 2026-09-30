# CODEX-ATLAS-BACKEND-PARITY-WAVE3 Review

REVIEW_RESULT: ACCEPTED（SSH 在真实主机上不可用的问题由审阅方直接修复）
REVIEWED_HEAD: `f6a2c7f`
BASE_HEAD: `c6e48a3`

## Verdict

结果文件如实说明了全量测试没跑完，没有虚报。笔记本补跑全量 `core/tests`（跳过 `test_computer_use.py`）：**598 passed, 5 skipped**，包括 Hub 进程启动测试。`origin_guard` 未改动；Hub 上审阅方加的 `OriginGuard` 保留；`/api/workspace/raw` 的 SSH 分支也带了沙箱头。

## 审阅方修复：SSH 对真实主机完全不可用

Codex 的 SSH 测试全部使用模拟传输，而模拟和真实 asyncssh 行为不一致。用笔记本连主机（`zhuji`，Windows，OpenSSH 默认 shell 为 cmd.exe）实测：

1. `asyncssh.connect(..., client_keys=None)` 关闭了密钥登录 → `Permission denied`。去掉该参数，按 ssh config 的 IdentityFile 加载密钥。
2. 系统识别靠 `$PSVersionTable`，在 cmd.exe 里原样输出 → 误判为 linux，之后所有命令按 POSIX 拼接。改为先 `echo %OS%`（cmd 下为 `Windows_NT`），再 PowerShell 探测，最后 `uname`。
3. PowerShell 不认 SFTP 风格的 `/D:/Atlas`，`Set-Location` 静默失败，命令在用户目录执行。`_powershell_quote` 去掉盘符前的 `/`。
4. `-EncodedCommand` 不传回原生命令的退出码 → git 失败也报 0。脚本末尾加 `exit $LASTEXITCODE`；同时关掉进度输出（stderr 的 `#< CLIXML`）。
5. `await sftp.scandir(...)`：scandir 是异步迭代器 → 列目录报错。改为 `readdir`。测试里的假 SFTP 同步改名，并加了「cmd 默认 shell 识别为 Windows」的测试。

修复后在主机 `ssh://zhuji/D:/Atlas` 上实测：shell、git status、exec、列目录、glob、读文件都正确，失败命令返回非零。

## 留给下一波（非阻塞）

1. 内置角色 `default / architect / reviewer` 的名称、说明、指令是英文，改为中文。
2. `rules.trust` 用 `f"{run_id}:{run.sequence}"` 校验 event_id，依赖回复前没有新事件；改为保存发出时的 event_id 比对。
3. SSH 测试至少保留一条可选的真实连接测试（环境变量 `ATLAS_SSH_TEST_HOST` 设置时运行），避免模拟与真实库再次脱节。
