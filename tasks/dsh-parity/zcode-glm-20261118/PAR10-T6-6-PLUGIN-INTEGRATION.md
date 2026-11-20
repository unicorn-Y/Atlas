# PAR-10 · T6-6 任务书 · 插件注册表与版本信息合验

## 选行与依据

- QUEUE 行:`F09-extensions` / `B-F09-REGISTRY-01`;T1 已验 registry plan + 安装执行器(链路待接),T6-2 已验版本事实(46 passed/8 skipped,主树补丁 apply-check 失败)。
- 依据:`PAR10-PLUGIN-INTEGRATION-NEXT.md`;`evidence/par10-t1.md` + `par10-t1-wiring.patch`;`evidence/par10-t6-2.md` + `par10-t6-2-wiring.patch`。

## 工作树

- `D:\Atlas\.worktrees\zcode-par10-plugin-integration-candidate`
- 分支 `zcode/par10-plugin-integration-candidate`,HEAD `060071ab`。
- T1/T6-2 源树与主工作区只读;本树独占;不 commit/push/merge/stash。

## 任务

1. 移入 T1 的 `registry_plan.py`、`registry_install.py` 及测试;移入 T6-2 的 `version_facts.py` 及测试;逐文件记录源路径/sha256。
2. 从主树复制**必要的最小当前接口副本**(至少 `core/atlas/api/plugins_router.py`、`core/atlas/plugins/runtime.py`;若 import 需要再加未跟踪 `compatibility.py`/相关测试),记录源路径+sha256+基线 diff。主树只读。
3. 重新适配 T1/T6-2 两处调用点(不要盲打旧补丁):保持主树在途调用契约、审批/幂等/取消/状态快照、错误归因与脱敏;版本读取沿用现有受信源与权限判断,检查来源、重定向、超时边界。路由变更按需刷新本树 `routes.json` 并记录归因。
4. 用受配置授权的临时回环 registry 走真实插件 HTTP 安装入口与版本信息入口,验证:
   - 两者 registry 选择一致;公共源失败允许回退;私有/显式源失败不回落;未知源拒绝;spec host 不回落;
   - 版本/依赖字段(peerDependencies/deprecated/dsh)与预发布结果;
   - 错误与日志无凭据/私有路径;来源/重定向/超时边界;
   - 成功安装 + 已有插件生命周期回归(既有套件)。
5. 记录命令/退出码/通过数;明确主树可能冲突的文件与行、安静基线可复跑补丁、未完成项。禁止真实 npm/账号/凭据。
6. 回执 `evidence/par10-t6-6.md`:工作树、源/接口哈希、改动文件/diff、入口矩阵、命令/退出码、冲突与未覆盖项。**最后一行 `PAR10_RECEIPT T6-6 READY|PARTIAL|BLOCKED`**,完成汇报给出同一标记与路径。