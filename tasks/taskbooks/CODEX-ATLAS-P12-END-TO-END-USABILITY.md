# CODEX-ATLAS-P12-END-TO-END-USABILITY

STATUS: READY

Goal:
使 Atlas 成为可实际使用的全能个人助手——用户双击打开、发消息、收到格式化回复、工具正常工作、历史可查看。

Scope:
- 修复阻断真实对话的三个核心缺口（MCP 工具链、真流式、Markdown 渲染）
- 清理影响体验的 Mock 残留和硬编码
- 端到端验证：启动 → 发消息 → 工具调用 → 格式化输出 → 历史持久化

Deliverables:
- MCP 工具定义完整（filesystem/git/brave-search 三个 server 可用）
- Agent 事件真正流式返回（用户看到逐字输出而非等待后一批到达）
- 消息 Markdown 渲染（代码块、列表、链接、粗体/斜体）
- 去除硬编码：任务面板计划步骤、用户名/头像
- 端到端测试通过：新对话 → 发送 "列出当前目录文件" → 收到工具调用结果 → 重启后历史可见

Rules:
- 一个任务书，按优先级分 5 个 Task 顺序执行
- 每个 Task 完成后跑相关测试验证
- 最后一个 Task 是端到端集成验证
- 不改自主知识系统（P9-P11 成果）
- 不实现文件上传、语音输入、深色模式（留给后续）

---

## Task 1: 补全 MCP 工具链定义

### Context
`config/atlas.toml` 的 `tools.auto_start` 列了 filesystem/git/brave-search，但只有 filesystem 有 `[tools.servers.*]` 定义。后端启动时 MCPClient 找不到 git/brave-search 配置，Agent 只有文件系统工具。

### Actions
1. 从 `config/atlas.example.toml` 复制 `[tools.servers.git]` 和 `[tools.servers.brave-search]` 段到 `config/atlas.toml`
2. 取消注释 `tools.auto_start` 中的 git 和 brave-search 行
3. 确认 git server 的 `args` 指向正确的仓库路径（默认 `D:/Atlas`）
4. 确认 brave-search 的 env 占位（`BRAVE_API_KEY` 需用户自行配置，但定义要存在）

### Validation
```bash
cd D:/Atlas/core
uv run pytest tests/test_mcp_integration.py -v -k "filesystem or git"
```
预期：至少 2 个工具 server 启动成功（filesystem + git），brave-search 因缺 API key 可能失败但不影响其他

### Files
- `config/atlas.toml`

---

## Task 2: Agent 事件流改为真流式

### Context
`AgentOrchestrator.run()` 使用 `self._graph.ainvoke()` 执行完整图后一次性 yield 所有 `pending_events`。用户发消息后等待 5-20 秒才看到输出，体验像卡住。需要逐事件流式返回。

### Actions
1. 在 `core/atlas/agent/__init__.py` 的 `AgentOrchestrator` 类中：
   - 添加 `self._event_queue: asyncio.Queue` 在 `__init__` 初始化
   - 修改 `_think_node` 和 `_execute_tools_node`：产生事件时 `await self._event_queue.put(event)` 而非追加到 `pending_events`
   - 修改 `run()` 方法：
     ```python
     async def run(...):
         # 启动 LangGraph 执行（后台任务）
         graph_task = asyncio.create_task(self._graph.ainvoke(...))
         
         # 主循环：从 queue 取事件并 yield
         while True:
             try:
                 event = await asyncio.wait_for(self._event_queue.get(), timeout=0.5)
                 yield event
             except asyncio.TimeoutError:
                 if graph_task.done():
                     break
         
         # graph 执行完毕后，清空剩余 queue 事件
         while not self._event_queue.empty():
             yield self._event_queue.get_nowait()
         
         # 检查 graph_task 异常
         await graph_task
     ```
2. 确保所有 `message.delta` 事件在生成时立即入队（不等整个响应完成）
3. 保留现有错误处理和状态管理逻辑

### Validation
1. 启动后端：`cd D:/Atlas/core && uv run uvicorn atlas.server:app --port 8765`
2. 手动 WebSocket 测试：
   ```python
   import asyncio, websockets, json
   async def test():
       async with websockets.connect("ws://127.0.0.1:8765/ws/chat") as ws:
           await ws.send(json.dumps({"type": "message.create", "conversation_id": "test-conv", "content": "Hello"}))
           async for msg in ws:
               data = json.loads(msg)
               print(f"[{data['type']}] {data.get('content', '')[:50]}")
               if data['type'] == 'message.completed':
                   break
   asyncio.run(test())
   ```
   预期：`message.delta` 事件逐条到达（间隔 <1s），而非最后一批到达

### Files
- `core/atlas/agent/__init__.py`（或 `orchestrator.py`）

---

## Task 3: 前端 Markdown 渲染

### Context
`ConversationMessage` 组件当前直接显示纯文本。LLM 回复包含代码块、列表、链接时显示为原始 Markdown 语法，不可读。

### Actions
1. 安装依赖：
   ```bash
   cd D:/Atlas/frontend
   npm install react-markdown rehype-highlight remark-gfm
   ```
2. 在 `frontend/src/renderer/components/ConversationMessage.tsx` 中：
   - Import: `import ReactMarkdown from 'react-markdown'; import remarkGfm from 'remark-gfm'; import rehypeHighlight from 'rehype-highlight';`
   - 对 `message.role === 'assistant'` 的消息内容用 `<ReactMarkdown>` 包裹：
     ```tsx
     {message.role === 'assistant' ? (
       <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
         {message.content}
       </ReactMarkdown>
     ) : (
       <p>{message.content}</p>
     )}
     ```
3. 在 `frontend/src/renderer/App.module.css` 或新建 `ConversationMessage.module.css` 中添加代码高亮样式：
   ```css
   pre {
     background: #0f131c;
     border-radius: 8px;
     padding: 16px;
     overflow-x: auto;
   }
   code {
     font-family: 'Consolas', 'Monaco', monospace;
     font-size: 0.9em;
   }
   ```
4. 引入 highlight.js 主题 CSS（在 `index.html` 或 `App.tsx` 顶部）：
   ```tsx
   import 'highlight.js/styles/github-dark.css';
   ```

### Validation
1. 启动前端：`cd D:/Atlas/frontend && npm run dev`
2. 发送消息："用 Python 写一个 Hello World"
3. 检查回复：代码块有背景色、语法高亮，列表有缩进，链接可点击

### Files
- `frontend/src/renderer/components/ConversationMessage.tsx`
- `frontend/src/renderer/ConversationMessage.module.css`（新建）
- `frontend/package.json`

---

## Task 4: 清理硬编码和 Mock 残留

### Context
当前 UI 有多处写死数据：任务面板的 "5 步 · 3/5 完成"、用户名 "Lin"、空对话列表的三个假条目。影响真实使用时的可信度。

### Actions
1. **任务面板计划步骤**（`App.tsx` 的 planStrip 区域）：
   - 从 `activeRun?.events` 中提取 `plan.*` 事件（如 `plan.created`, `task.completed`）
   - 计算 `totalSteps` 和 `completedSteps`，动态显示 "X 步 · Y/X 完成"
   - 若无计划数据，隐藏该区域或显示 "无活动计划"

2. **用户名和头像**（`App.tsx` 的用户消息头像）：
   - 从 localStorage 读取 `atlas.preference.username`（默认 "User"）
   - 头像取用户名首字母大写
   - 在 `SettingsPage.tsx` 添加 "用户名" 输入框，保存到 localStorage

3. **空对话列表假数据**（确认已无 Mock 对话）：
   - 检查 `useAtlasStore.ts` 的 `initialize()` 是否仍有 Mock 对话注入
   - 确认侧边栏 "暂无对话" 提示正确显示（已有：App.tsx:56）

### Validation
1. 清空 localStorage，重启 Atlas
2. 检查侧边栏：显示 "暂无对话"
3. 进入设置 → 输入用户名 "测试用户" → 返回对话 → 发送消息
4. 检查消息头像：显示 "测" 字母
5. 若有活动计划，任务面板显示实际步骤数；否则隐藏

### Files
- `frontend/src/renderer/App.tsx`
- `frontend/src/renderer/pages/SettingsPage.tsx`
- `frontend/src/renderer/store/useAtlasStore.ts`（确认无 Mock 数据）

---

## Task 5: 端到端集成验证

### Context
前四个 Task 各自通过局部测试，但需要验证完整流程：启动 → 发消息 → 工具调用 → 格式化输出 → 历史持久化 → 重启后可见。

### Actions
1. **清理环境**：
   - 删除 `D:/Atlas/core/data/atlas.db`（若存在）
   - 清空浏览器 localStorage（或用隐身模式）

2. **启动 Atlas**（打包或开发模式）：
   ```bash
   cd D:/Atlas/frontend
   npm run dev
   ```

3. **测试用例 1：工具调用**
   - 创建新对话
   - 发送："列出 D:/Atlas 目录下的所有 .md 文件"
   - 预期：
     - 消息逐字显示（流式）
     - Agent 调用 `filesystem` 工具
     - 返回结果包含文件列表，Markdown 格式（列表渲染正确）

4. **测试用例 2：代码生成**
   - 发送："用 Python 写一个读取 JSON 文件的函数"
   - 预期：
     - 代码块有背景色和语法高亮
     - 函数定义、注释、示例清晰可读

5. **测试用例 3：历史持久化**
   - 关闭 Atlas
   - 重新启动
   - 检查侧边栏：之前的对话存在
   - 点开对话：历史消息完整显示（包括工具调用和代码）

6. **测试用例 4：错误恢复**
   - 发送："搜索最新的 AI 新闻"（brave-search，可能因缺 API key 失败）
   - 预期：
     - 返回友好错误提示（而非崩溃）
     - 对话仍可继续使用

### Validation Checklist
- [ ] 前端自动连接后端（显示 "后端已连接"）
- [ ] 新对话创建成功，标题自动生成
- [ ] 消息流式显示（delta 事件逐条到达）
- [ ] Markdown 渲染正确（代码高亮、列表缩进、链接）
- [ ] 工具调用成功（至少 filesystem 可用）
- [ ] 历史持久化：重启后对话和消息完整
- [ ] 任务面板无硬编码数据
- [ ] 用户名可配置且显示正确

### Acceptance Criteria
所有 7 项 checklist 通过 → P12 完成，Atlas 进入可用状态。

### Files
- 无需修改代码，纯测试验证
- 若发现 bug，修复后重新验证

---

## Definition of Done

1. 所有 5 个 Task 的 Validation 通过
2. Task 5 的 7 项 Checklist 全部勾选
3. 提交 commit：`feat(usability): end-to-end usability - MCP toolchain, streaming, markdown, E2E test (P12)`
4. 更新 `tasks/CURRENT.md` 状态为 COMPLETED
5. 生成结果文件：`tasks/results/CODEX-ATLAS-P12-END-TO-END-USABILITY.result.md`

---

## Notes

- MCP server 配置需要用户环境支持（Node.js、npx），若缺失应给出明确错误提示
- brave-search 的 `BRAVE_API_KEY` 由用户在环境变量或 `.env` 中配置，taskbook 不处理密钥管理
- Markdown 渲染的 CSS 样式应与现有暖白 UI 风格一致（深色代码块 + 暖白背景）
- 流式事件改造可能影响现有测试，需同步更新相关 mock 或测试用例
