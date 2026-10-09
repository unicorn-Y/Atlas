# F4-E 演练运行器准备检查点

状态：`PREP_ONLY`。本检查点只改进正式演练运行器及其静态回归；未启动 Atlas、MemoryOS、真实模型或正式演练，也未读取或计算生产配置、数据库、WAL 的内容或哈希。没有把测试结果标记为真实产品效果或 `ACCEPTED`。

## 发现与修正

- 旧提醒断言会把无时区的 `trigger.at` 直接附加用户时区，因此可能把缺失时区的错误值当作本地 9 点。现在必须是有时区的存储值，并按 UTC instant 与预期时间比较。
- 旧去重断言只看 `request_run_id` 和非空 `intent_id`。现在等待隔离 MemoryOS 副本中出现同一 intent，并只读检查它的 `user_source_ref`、`source_state`、生命周期、版本、动作与 `due_at`；来源引用必须解析为本轮真实 `ATLAS_USER_MESSAGE` / `USER` 观察事件，且 `metadata.request_run_id` 等于创建聊天的 run id。创建后等待 `ACTIVE`，取消后等待 `CANCELLED`，同时检查同一个 Automation id、唯一性和启用状态。只写来源引用和校验结果，不读写或输出来源消息正文。
- `明天上午 9 点` 的预期时间现在从该用户消息的真实 `occurred_at` 和用户 IANA 时区推导，消除服务启动、旧数据导入耗时造成的跨日误差；后续重启、取消和 rollback 继续比较同一 UTC instant。
- Automation TOML 路径按 Atlas DB 的配置落点确定：`isolated_atlas_db.parent / "automations.toml"`。隔离配置的 `db_path=./data/atlas.db` 对应 `atlas_data/data/atlas.db`，所以 store 位于其同级目录。
- 创建与取消聊天保留真实 WebSocket 聊天，只授权 `automation_manage` 工具并使用 `full_access`，以通过现有权限门；没有直接构造或写入提醒来代替聊天产物。

## 验证

- 原 E runner 专项基线（第一次修改前）：12 passed / 0.10s。
- 当前专项：
  `D:\Atlas\core\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q scripts/memory_v1/test_f2_enable_rehearsal.py --basetemp C:\Users\25011\AppData\Local\Temp\atlas-f4e-prep-review-20261009a`
  结果：29 passed / 0.26s。
- Ruff：`ruff check scripts/memory_v1/f2_enable_rehearsal.py scripts/memory_v1/test_f2_enable_rehearsal.py --select F401,F821,E9` 通过。
- `git diff --check` 对 runner 和测试文件通过；Git 仅提示工作区 LF 将在后续 Git 写入时转换为 CRLF。
- 回归包含无时区 trigger 拒绝、isolated clone 中 USER/source/run 关联校验、Observer 的 ACTIVE→CANCELLED 结算、Automation 同 id 状态和 DB 同级 store 路径。先前错误路径由审查发现；本检查点未声称单独运行了修改前失败测试。

## 边界与待执行

本检查点未执行真实模型/服务，也未触碰 `D:\Atlas\data`、`D:\MemoryOSData` 或生产配置。以上 SQLite 验证只在正式演练创建的隔离副本上以只读连接运行。正式 F4-E 仍待 F4-A/B/C 合入且总控明确授权；实际产物必须单独记录 clone 的前后哈希、真实聊天与 Observer/intent settle、重启、取消、disable rollback 和清理结果。
