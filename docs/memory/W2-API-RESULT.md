# W2-A 后端结果

## 实现范围

完成 TASKBOOK-W2 第 3 节 W2-A，并按第 6 节添加 `/api/memlib/search`、`timeline`、`projects`、`project`、`open`、`stats`、`dream` 接口。变更仅限第 3 节列出的后端文件和本结果文件；未改前端，没有合并。

新增能力包括经历出处指针和五类经历列表、原始会话打开/搜索、可选 fastembed 向量检索与关键词回退、混合排序/时间衰减/MMR，以及按项目整理与检查点。对 20k 检索的实测还促成三项后端优化：缓存实体页标题、缓存向量矩阵并按类型保留候选、将 MMR 更新改为增量相似度计算；详细回忆可检索已在常驻区的近期经历，且按索引命中的页面读取条目。

## A8 主机实测

主机配置以只读方式加载自 `D:\Atlas\config\atlas.toml` 与主机现有用户设置，选中模型为 `gemini-3.8-flash`。未设置 `ATLAS_DATA_DIR`；A8 的记忆库、工作文件及会话数据库全部写入 `D:\atlas-mem-w2-api\.tmp\a8-real-20261016011115`。`ModelManager._persist_settings` 在实测进程中禁用；`open_ref` 明确指向临时 SessionDB。未向 `D:\Atlas\data` 写入测试数据。

### 1. 五轮任务与经历页

主机 Gemini 3.8 Flash 实际参与五轮任务，每轮均调用真实模型并将消息记入临时会话：读取 `sample.txt`；只把 `status=old` 改为 `status=verified`；运行 Python 命令确认输出 `status=verified`、退出码 0；选择先提交 status 单行修改；保留真实配置兼容性检查为未完成事项。临时文件最终内容：

```text
status=verified
owner=memory-library
```

五轮分别调用 `observe_turn`。首轮逐轮抽取虽保留了决定、文件和待办，但未提取命令、事实；因此又把五轮的真实记录和已验证步骤交给同一 Gemini 模型作一次完整经历抽取，并将结果写回临时经历页。最终五类列表均有内容，且对应真实文件、命令、决定、原文和未完成事项。经历页原文：

```markdown
# 2026-10-16

## 现在
- 五轮任务记录：修改 sample.txt 并验证：读取并编辑 sample.txt，将 status 改为 verified，运行命令验证 <!-- {"id":"m_d366583993","src":"经历","at":"2026-10-16T01:15:16+08:00","ref":"w2a-host-real-20261016011116@2026-10-16T01:15:16+08:00","session":"w2a-host-real-20261016011116","trigger":["sample.txt","status","owner"],"steps":["read_file ✓ 读取 sample.txt：status=old，owner=memory-library","edit_file ✓ 只将 status=old 改为 status=verified，owner 行不变","command ✓ python 命令输出 status=verified，退出码 0","decision ✓ 决定先提交 status 单行修改，再处理 owner 行","open_item ✓ 保留未完成：检查 status=verified 在真实 Atlas 配置中的兼容性"],"outcome":"status=verified 修改已完成并验证，兼容性检查未执行","verified":true,"decisions":["先提交 status 单行修改，再处理 owner 行"],"files":["sample.txt"],"commands":["python 命令（退出码 0，输出 status=verified）"],"facts":["sample.txt 原 status=old，owner=memory-library","owner 行保持不变"],"open_items":["检查 status=verified 在真实 Atlas 配置中的兼容性"]} -->
```

### 2. 详细召回、模型回答与 open

新问题：**“刚才那个任务改了哪个文件、为什么？”**。召回块命中经历记录，并带出决定、文件、命令、事实和待办：

```text
Atlas 记忆库里和这句话有关的记录：

## 以前做过的相关的事
- [2026-10-16] 五轮任务记录：修改 sample.txt 并验证：读取并编辑 sample.txt，将 status 改为 verified，运行命令验证 → status=verified 修改已完成并验证，兼容性检查未执行；决定：先提交 status 单行修改，再处理 owner 行；文件：sample.txt；命令：python 命令（退出码 0，输出 status=verified）；关键数字：sample.txt 原 status=old、owner=memory-library、owner 行保持不变；没做完：检查 status=verified 在真实 Atlas 配置中的兼容性；步骤：read_file ✓ 读取 sample.txt：status=old，owner=memory-library、edit_file ✓ 只将 status=old 改为 status=verified，owner 行不变、command ✓ python 命令输出 status=verified，退出码 0、decision ✓ 决定先提交 status 单行修改，再处理 owner 行、open_item ✓ 保留未完成：检查 status=verified 在真实 Atlas 配置中的兼容性；已验证

需要细节可用 memory_search(open="<ref>") 打开原对话：w2a-host-real-20261016011116@2026-10-16T01:15:16+08:00、w2a-host-real-20261016011116@2026-10-16T01:11:16+08:00
```

真实模型回答：

> 改的是 **sample.txt**。只把 `status=old` 改成 `status=verified`，`owner=memory-library` 没动；Python 验证命令输出 `status=verified`，退出码 0。记录中的决定是先提交已验证的 status 单行修改，再处理 owner 行。至于 status 为什么必须设为 verified，原对话没有说明，模型明确表示不确定，没有编造动机。兼容性检查仍是未完成项。

随后通过 `GET /api/memlib/open`（HTTP 200，`ok=true`，`window=2`）读取临时原会话。返回内容前 40 行（本次命中 2 轮，共 5 行）：

```text
user: 现在做一个决定：下一步先提交这个单行修改，还是先改 owner 行？请选择一个并说明原因。
assistant: 先提交当前这个单行修改（status=old → status=verified）。

原因：该修改已有验证命令输出 status=verified 作为直接证据，是完整、可提交的最小变更；owner 行尚未改动，没有待提交内容，也缺少需要先改它的依据。把已验证的单行修改单独提交，能保持提交原子性，之后再处理 owner 行。
user: 请把待办“检查 status=verified 在真实 Atlas 配置中的兼容性”留作未完成事项，本轮不要执行。
assistant: 已记录：待办事项「检查 status=verified 在真实 Atlas 配置中的兼容性」保留为未完成，本轮不执行。

确认：该兼容性检查尚未执行，必须保留为未完成事项。
```

### 3. 20,000 条检索基准

在临时库中生成 10,000 条假事实和 10,000 条假经历。主机未安装 fastembed，且包镜像下载失败，所以补向量时间使用确定性的 96 维合成向量函数测量；这不是 fastembed 模型推理时间。向量写入 20,000 条总计 **1,232.91 ms**。向量矩阵和实体缓存热起来后，`recall()` 连续 5 次平均 **64.44 ms**（范围 59.43–70.97 ms，目标 <80 ms）。首次冷召回 362.87 ms，包含矩阵载入和缓存建立。真实 ASGI `GET /api/memlib/search` 请求返回 HTTP 200、30 条结果，耗时 **19.66 ms**（向量已就绪，目标 <150 ms）。

将 embedding 函数模拟为不可用后再搜索，关键词回退无异常，返回 8 条结果，用时 **22.10 ms**。fastembed 的真实模型向量生成耗时尚未测得。

### 4. 三日期 dream

构造 2026-10-08、09、10 三条假经历，通过真实 `POST /api/memlib/dream` 与主机 Gemini 路由运行，HTTP **200**，返回 `ok=true`、`projects=["A8DreamConfirm"]`、`added=11`、`changed=4`，检查点已生成。Gemini 生成的 `事/A8DreamConfirm.md` 原文：

```markdown
# A8DreamConfirm

## 现在状态
- 项目：A8DreamConfirm。 <!-- {"id":"m_aecc9d254d","src":"整理","at":"2026-10-16T01:30:10+08:00","ref":"confirm-2026-10-08,confirm-2026-10-09,confirm-2026-10-10","verified":false} -->
- 存在 2026-10-08、2026-10-09、2026-10-10 三条跨天记录，文本均为“A8DreamConfirm：测试三日跨天项目整理”。 <!-- {"id":"m_a7cf9e3906","src":"整理","at":"2026-10-16T01:30:10+08:00","ref":"confirm-2026-10-08,confirm-2026-10-09,confirm-2026-10-10","verified":false} -->
- 涉及文件：sample.txt；命令：python verify status。 <!-- {"id":"m_c6b8aee63e","src":"整理","at":"2026-10-16T01:30:10+08:00","ref":"confirm-2026-10-08,confirm-2026-10-09,confirm-2026-10-10","verified":false} -->
- 三条记录 verified 均为 false，outcome 为空。 <!-- {"id":"m_55aca5d00b","src":"整理","at":"2026-10-16T01:30:10+08:00","ref":"confirm-2026-10-08,confirm-2026-10-09,confirm-2026-10-10","verified":false} -->
- 事实：三日记录用于确认 dream。 <!-- {"id":"m_089dcc16f8","src":"整理","at":"2026-10-16T01:30:10+08:00","ref":"confirm-2026-10-08,confirm-2026-10-09,confirm-2026-10-10","verified":false} -->

## 定下的决定
- 先验证单行修改。 <!-- {"id":"m_e4b6560102","src":"整理","at":"2026-10-16T01:30:10+08:00","ref":"confirm-2026-10-08,confirm-2026-10-09,confirm-2026-10-10","verified":false} -->

## 没做完
- 2026-10-30 前检查真实配置兼容性。 <!-- {"id":"m_d2d5175720","src":"整理","at":"2026-10-16T01:30:10+08:00","ref":"confirm-2026-10-08,confirm-2026-10-09,confirm-2026-10-10","verified":false} -->
- 三条记录均未验证（verified 为 false），outcome 为空。 <!-- {"id":"m_5bdbc7ec76","src":"整理","at":"2026-10-16T01:30:10+08:00","ref":"confirm-2026-10-08,confirm-2026-10-09,confirm-2026-10-10","verified":false} -->

## 来龙去脉
- 2026-10-08：A8DreamConfirm：测试三日跨天项目整理；决定：先验证单行修改；文件：sample.txt；命令：python verify status；事实：三日记录用于确认 dream；未完成项：2026-10-30 前检查真实配置兼容性；verified：false。 <!-- {"id":"m_1d613037f2","src":"整理","at":"2026-10-16T01:30:10+08:00","ref":"confirm-2026-10-08,confirm-2026-10-09,confirm-2026-10-10","verified":false} -->
- 2026-10-09：与 2026-10-08 记录内容、决定、文件、命令、事实、未完成项、verified 状态一致。 <!-- {"id":"m_72e3d09e57","src":"整理","at":"2026-10-16T01:30:10+08:00","ref":"confirm-2026-10-08,confirm-2026-10-09,confirm-2026-10-10","verified":false} -->
- 2026-10-10：与 2026-10-08 记录内容、决定、文件、命令、事实、未完成项、verified 状态一致。 <!-- {"id":"m_d930e2434c","src":"整理","at":"2026-10-16T01:30:10+08:00","ref":"confirm-2026-10-08,confirm-2026-10-09,confirm-2026-10-10","verified":false} -->
```

### 5. 真实模型和隔离范围

真实模型请求加载自 `D:\Atlas\config\atlas.toml` 和主机用户设置，模型选择为 `gemini-3.8-flash`，调用返回正常。主机配置/凭据只读使用，测试期间禁用了 ModelManager 设置持久化；五轮任务的文件、记忆页和 SessionDB 均在工作区 `.tmp`，dream 库也在 `.tmp`。向量搜索的 20k 合成数据同样仅在 `.tmp`。没有访问或写入 `D:\Atlas\data` 中的记忆库数据；`open_ref` 针对测试会话使用临时 SessionDB。

## 验证

- `python -m pytest core\tests\test_memory_library_w2.py -q --basetemp .tmp\pytest-w2-matrix -p no:cacheprovider --tb=short`：8 passed。
- W0/W1 测试单独运行：16 passed。
- `git diff --check`：通过。
- Ruff：新增模块与 W2 测试文件通过；既有模块有存量 lint 项，未做范围外格式化。

## 限制

- A8 向量生成基准是合成向量，不代表 fastembed 首次加载或真实推理速度；fastembed 包和模型下载未能从当前镜像安装。
- A8 真实模型使用主机已配置网关上的 Gemini 3.8 Flash；没有把原始主机凭据写进配置、结果或日志。
