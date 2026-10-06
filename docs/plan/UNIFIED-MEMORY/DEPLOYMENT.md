# Unified Memory: Windows 一致启动、健康性能与正式切换运行手册 (DEPLOYMENT.md)

本文档面向 Atlas 统一记忆架构（Unified Memory）在 Windows 环境下的部署、运维与发布切换，覆盖 **T12.2 Windows 一致启动、健康与性能** 及 **T12.3 正式切换 dry-run、恢复与用户交付** 的全流程工程规范。

---

## 1. 架构定位与发布背景

统一记忆（Unified Memory）为 Atlas 桌面端与 MemoryOS 提供全局单一记忆事实权威。在 UM12 发布阶段，必须保证：
1. **启动一致性**：开发环境（Dev）与打包发布版（Packaged）使用完全相同的 MemoryOS 服务地址、数据根与契约版本（`contract_version="UM-WIN-1.0"`），具备完全一致的 `authority_id` 权威标识；
2. **生命周期可控**：启动、重启、退出 Atlas 均能安全管理内部托管服务，不遗留孤儿进程，不误杀无关系统进程，重复启动不累加后台队列；
3. **性能预算严控**：真实规模下满足 p50/p95 延迟、上下文 Token 预算与存储增长约束，通过分页和预算截断而非删除必要记忆来保障性能；
4. **切换与回滚屏障**：切换操作基于受控副本进行只读差异预览并生成一致备份清单；在切换窗口内保证零双写（`dual_memory_writers == False`）；回滚恢复**必须前置执行擦除/撤回屏障**，杜绝盲目恢复旧库导致已删除数据死灰复燃。

---

## 2. Windows 启动与权威绑定 (T12.2)

### 2.1 统一绑定契约

无论是在开发调试启动（`uvicorn atlas.server:app`），还是在 Electron 打包运行时（Windows Packaged Release），Atlas 必须严格加载相同的核心配置：

| 参数 | 配置项 | 默认/规范值 | 说明 |
| --- | --- | --- | --- |
| 契约版本 | `contract_version` | `UM-WIN-1.0` | 统一契约版本标准 |
| 服务地址 | `service_url` | `http://127.0.0.1:{port}` | 绑定的 MemoryOS 服务地址 |
| 内部令牌 | `internal_token` | 配置于 `atlas.toml` 或环境变量 | 内部跨进程 Bearer 鉴权 |
| 主体绑定 | `subject_binding` | 默认 `atlas-fixture` 或用户主体 | 防止跨主体数据污染 |
| 权威标识 | `authority_id` | 稳定 UUID / 实例唯一权威 | 保证多进程与重启后权威不变 |
| 数据根路径 | `ATLAS_DATA_DIR` / `MEMORYOS_DATA_ROOT` | 显式路径 | 隔离环境，严禁指向生产未授权路径 |

### 2.2 启动接线与配置优先级

1. **配置文件加载**：
   - 优先读取 `ATLAS_DATA_DIR/config/atlas.toml` 中的 `[memory.unified]` 小节；
   - 环境变量覆盖：`ATLAS_UNIFIED_MEMORY_SERVICE_URL`、`ATLAS_UNIFIED_INTERNAL_TOKEN`；
   - 严禁“仅在开发环境注入 Mock，打包后使用失效配置”的行为。
2. **生产路径护栏**：
   - 测试与沙箱启动时，强制拦截 `D:\Atlas\data` 与 `D:\MemoryOSData` 生产路径；
   - 一旦检测到生产数据根绑定，立即触发致命断言并拒绝启动。

---

## 3. 服务与 Worker 生命周期可观测性 (T12.2)

### 3.1 健康探针与状态流转

- **Atlas 后端探针**：`GET /api/health`
  - 返回各组件状态（`scheduler`, `memory`, `orchestrator`）；
  - 启动阶段上报 `"status": "starting"`，全部就绪后返回 `"status": "ok"`；
  - 超时保护：桌面端依据状态显示进度，不因瞬时慢启动误杀服务。
- **统一记忆代理探针**：`GET /api/unified-memory/status`
  - 透传至 MemoryOS `GET /v1/unified/status`；
  - 响应包含：`contract_version`、`authority_id`、各组件接线状态、`watermarks`、`outbox` 状态以及 `formation.worker` 详情；
  - 降级保护：服务不可达时返回 `503 ServiceUnavailable`，严格禁止静默回落到废弃旧库伪造成功。

### 3.2 进程治理与优雅退出

- **启停隔离原则**：
  - Atlas 停止时，仅通过记录的 PID 与进程树针对性终止受管的 MemoryOS 子进程与 worker；
  - 严禁执行全局 `taskkill /IM python.exe /F` 等误杀其它用户进程的操作；
  - 退出后通过端口监听检测确认释放，Manifest 中记录 `stop_leftovers: []`。
- **Worker 幂等与去重**：
  - 重复启动 Atlas 或重启 backend 时，后台形成 Worker 检查运行锁或队列唯一性；
  - 严禁多次启动累加多个并发消费进程造成数据写竞争。

---

## 4. 资源限制与性能预算 (T12.2)

### 4.1 延迟与吞吐预算指标

在单机本地 Windows 环境下，核心链路执行严格的 P50/P95 延迟控制：
- **`POST /api/unified-memory/observe`**：
  - P50 延迟 ≤ 50ms；P95 延迟 ≤ 200ms；
- **`POST /api/unified-memory/recall`**：
  - P50 延迟 ≤ 100ms；P95 延迟 ≤ 350ms；
- **服务启动时间**：
  - 端到端双服务启动就绪 ≤ 5.0s。

### 4.2 上下文预算与无损装配纪律

在执行记忆检索与对话装配时：
- **Token 预算上限**：`max_tokens = 2400`；
- **记录条数上限**：`max_records = 12`；
- **证据节选上限**：`max_source_snippets = 8`；
- **核心纪律（无损控制）**：
  - **严禁为了凑性能而物理删除必要的用户记忆**；
  - 超出预算时，装配层通过相关性排序与截断、以及客户端分页 Cursor（`next_cursor`）进行无损控制；
  - 数据库内原始记忆完整留存，全量查询多次分页后召回率必须保持 100%。

---

## 5. 正式切换 Dry-Run 运行手册 (T12.3)

切换脚本：`scripts/unified_memory/cutover.py`

### 5.1 切换准备与副本演练

1. **副本隔离**：
   - 切换操作首先在源数据目录的受控副本（`staging_cutover/`）上运行；
   - 严禁直接在生产数据库上执行未经 dry-run 的破坏性迁移。
2. **只读差异预览**：
   - 读取旧 MemoryStore 中的记录数（`memories`, `episodes` 等）；
   - 计算待迁移与已存在记录的差异分布，输出 `preview` 报告。
3. **一致备份清单（Backup Manifest）**：
   - 生成完整备份至 `backup_cutover/`；
   - 写入 `backup_manifest.json`，记录每个文件的 `size_bytes`、`sha256` 校验和、SQLite 数据表行数以及当前观察水位（`OBSERVATION_ACKED`, `FORMED_THROUGH`）。

### 5.2 原子切换与零双写控制 (Zero Dual-Memory Writers)

在执行正式切换窗口期：
- **写暂停控制器（WritePauseController）**：
  - 获取写暂停锁 `cutover_write_pause.lock`；
  - 在切换窗口内，来自 UI/聊天的新增写入被暂挂，或自动暂存进 Atlas 侧的运行 Outbox 队列；
  - 保证系统在任一瞬间仅存在单一记忆权威：`dual_memory_writers == False`；
- **新写/删除/撤回对账**：
  - 切换完成后核对 Outbox 暂存条数、删除标记与撤回记录，全部补齐对账后释放写暂停锁。

### 5.3 启动失败自动回滚演练

如果在切换后执行服务启动健康检测时发生故障（如注入 `cutover_startup_failure` 故障）：
- 切换脚本捕获异常，自动触发回滚；
- 释放写锁，保持原有数据与旧库不变；
- 输出 `{"rolled_back": True, "dual_memory_writers": False}`；
- 恢复到切换前的一致备份版本。

---

## 6. 回滚与屏障恢复运行手册 (T12.3)

恢复脚本：`scripts/unified_memory/rollback.py`

### 6.1 核心恢复铁律：先屏障，后恢复

> **严禁盲目直接覆盖恢复旧备份数据库！**
> 如果用户在备份创建之后执行了合规擦除（`HARD_ERASE`）或撤回了敏感偏好，直接覆盖旧数据库会导致被擦除的隐私记录“被复活”，构成严重数据泄露风险。

### 6.2 恢复执行步骤

1. **校验备份清单完整性**：
   - 读取 `backup_manifest.json`；
   - 重新计算各备份文件的 SHA-256，与清单逐一核对。
2. **装载擦除与撤回屏障**：
   - 读取擦除台账（`erasure_ledger`）与撤回事件；
   - 提取所有被屏障阻断的 `record_ref`、`source_object_id` 与资产 ID 集合。
3. **应用屏障并执行数据恢复**：
   - 将备份文件解压/复制回目标数据目录；
   - **在数据库开放服务之前**，针对目标 SQLite 库执行屏障清洗：将屏障清单内的记录执行原子物理删除或打上 `ERASED`/`TOMBSTONE` 标记；
   - 重建索引，确保向量与全文索引中不存在被擦除记录的残留。
4. **后置 Outbox 暂存队列接续**：
   - 如果切换后有合法的新写入（暂存在 outbox 中），恢复流程将其保留至对账队列，避免用户在切换演练期间输入的文本无故丢失。

---

## 7. 生产切换发布交付核对表 (Sign-off Checklist)

- [ ] **Windows 启动一致性**：开发模式与打包模式启动统一读取 `[memory.unified]` 配置，`authority_id` 与契约版本完全一致；
- [ ] **服务生命周期**：停止 Atlas 时子进程退出干净，`stop_leftovers` 为空，无系统孤儿进程；
- [ ] **性能预算合规**：P50/P95 响应符合毫秒级预算，Token 预算限制生效，分页逻辑无损；
- [ ] **切换演练通过**：Dry-run 成功产出只读 diff 与 `backup_manifest.json`；
- [ ] **零双写保证**：切换期间写暂停生效，`dual_memory_writers == False`；
- [ ] **故障自动回滚**：启动失败演练中自动回滚并保持之前一致版本；
- [ ] **屏障恢复守卫**：验证带有 `HARD_ERASE` 记录的库在回滚后，被擦除记录绝不复活；
- [ ] **用户授权门禁**：实际生产环境的数据切换仅在用户交互确认后触发。
