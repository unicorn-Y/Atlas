# PAR-10 · T6-2 任务书 · F09 版本事实面

## 选行与依据

- QUEUE 行:`F09-extensions`(09 扩展、权限与生命周期),能力 `B-F09-REGISTRY-01`。
- 已证实缺口:`evidence/exec06-f09-registry-20261119.txt` §C G4 / §D A-3——Atlas 缺 `newerVersions` 与 `{peerDependencies,deprecated,dsh}` 版本事实面;DSH 同包 `versions.ts` 提供该能力。
- T1 已交付 registryPlan/失败归因(链路待接);本包只做版本事实,不重复 T1。

## 实际入口

- 产品插件安装/查询入口:`core/atlas/api/plugins_router.py`、`core/atlas/plugins/runtime.py`(主树在途;候选树 HEAD 干净)。
- 若新增只读 HTTP 入口,走真实 `/api/plugins/...` 路由;若路由冲突,交付纯模块 + 最小接线 patch/说明并标链路待接。

## 工作树

- `D:\Atlas\.worktrees\zcode-par10-version-facts`
- 分支 `zcode/par10-version-facts`,基线 HEAD `060071ab`。
- 只写本树与 `evidence/par10-t6-2.md`;主工作区只读;不 commit/push/merge/stash。

## 交付

1. 新建纯函数模块(建议 `core/atlas/plugins/version_facts.py`):
   - `newer_versions(current, available)`:`available` 中严格大于 `current` 的版本,稳定排序;处理预发布/非法版本(返回空或明确错误,不抛未捕获异常)。
   - `version_facts(metadata)`:从 npm packument/版本对象提取 `{peerDependencies, deprecated, dsh}`;缺失字段归一(空对象/None/false),非法形状明确拒绝或归一;不联网、不落凭据。
   - 对照 DSH 源:`D:\ENGINE-V3-UPSTREAM-20261118\deepseek-harness\packages\boot\plugin-manager\src\versions.ts`(newerVersions/versionFacts 字段语义)。
2. 若可行,加只读真实入口:`GET /api/plugins/registry/versions?name=...&registry=...` 或扩展现有插件信息路由,用本地假 registry HTTP 服务返回 packument;测试真实 HTTP 200/错误面。若 plugins_router/runtime 在途冲突,交付补丁 + `git apply --check`,状态标链路待接。
3. 测试(`core/tests/test_plugin_version_facts.py`,@pytest.mark.unit):
   - newerVersions 升序/预发布/当前为最新/非法输入;
   - versionFacts:完整、缺 peerDependencies、deprecated=true/字符串、dsh 字段、非法形状;
   - 本地假 registry 端到端(若加 HTTP 入口);无真实网络/账号/凭据。
4. 命令:`--basetemp=<worktree>/.tmp/... -p no:cacheprovider`,记录解释器/版本、完整命令、退出码、通过数;ruff 新文件。

## 验收

- A-3 语义可判定:返回 newerVersions 与实际 `{peerDependencies, deprecated, dsh}`;不联网时纯函数测试全过。
- 若做了 HTTP 入口,用本地假 registry 证明真实路由;若未接,记录文件/行与可应用补丁。
- 回执末行:`PAR10_RECEIPT T6-2 READY|PARTIAL|BLOCKED`。