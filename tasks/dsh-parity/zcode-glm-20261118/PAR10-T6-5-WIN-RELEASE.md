# PAR-10 · T6-5 任务书 · Windows 完整发行链复验

## 选行与依据

- QUEUE 行:`F01-distribution` / `B-F01-CORE-PKG-VERIFY-01`;T2 已验真实 packaged/NSIS payload,但 backend 用现有副本、未跑完整 `npm run dist:win`/安装卸载,本包补全链。
- 依据:`PAR10-READY-NEXT.md` §Windows 完整发行链;`evidence/par10-t2.md`;T2 源树 `D:\Atlas\.worktrees\zcode-par10-release-startup`。

## 工作树

- `D:\Atlas\.worktrees\zcode-par10-win-release-repro`
- 分支 `zcode/par10-win-release-repro`,HEAD `060071ab`。
- 先确认 T2 写者已停,移入明确的七个发行文件(`releaseIntegrity.ts/.test.ts`、`after-pack-release-manifest.cjs`、`after-pack.cjs`、`write-release-manifest.mjs`、`package.json`、`electron.ts`),记录源 sha256。

## 任务

1. 用同一源码生成 backend、应用、内嵌清单、Node、NSIS,目标 `npm run dist:win` 派生;优先复用现有依赖/缓存;全部输出到本树/临时目录。
2. 记录实际命令、产物版本、清单来源、受检文件 SHA-256、Node 版本及真实 Electron 启动。
3. 保留 T2 的真实缺清单/不匹配拒绝;核实旧清单迁移到新产物。
4. 升级验证用隔离安装路径和临时配置/数据库;先核实安装器选项无副作用;可先验证 NSIS payload,再做支持的隔离安装。不可安全分离的本机安装路径记为阻塞。
5. 缺依赖时写具体阶段/实际错误;已完成部分继续接受复核。命令/退出码/日志完整记录。

## 验收

- 全链产物可复现或给出具体阻塞阶段;真实启动与拒绝证据保留;清单/哈希/Node 版本可核对。
- 回执 `evidence/par10-t6-5.md`,末行 `PAR10_RECEIPT T6-5 READY|PARTIAL|BLOCKED`。