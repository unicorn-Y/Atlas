# 专题 3：产出物——文档、表格、演示、网页和应用（2026-09-30）

## 一、当前最强做法

1. **生成的是能继续编辑的「活文档」，不是一次性文件。**
   - **Claude Docs / Slides（9-16 beta）**：对话里生成可以编辑的文档和幻灯片，可以接着让 Claude 改，也可以自己改；文档能导出 Word、PDF、Markdown、Google Docs，幻灯片能直接在 Claude 里放映，或者下载成 PowerPoint、PDF；可以用链接分享、多人协作。
   - **Microsoft 365 Copilot**：Word、Excel、PowerPoint 各有专门的 Agent。
2. **产出能发布成网页，而且能自己更新。**
   - **ChatGPT Sites（公测）**：一句话生成仪表盘、项目跟踪、上线日历、原型、内部门户、报告；先私下预览，再发布成可分享的网址（OpenAI 负责托管）；**底层数据变了，仪表盘会自动更新**。
   - **千问办公（9-07）**：一句话生成最多百人同时在线协作的网页应用。
3. **直接改用户电脑上的 Office 文件。**
   - **豆包工作（9-09）**：同步编辑本地的 PPT、Excel，Word 随后支持。
4. **更多媒体类型。**
   - **Manus Studio（9-28）**：时间线式视频剪辑、桌面游戏开发（多人游戏发链接就能玩）。
   - **Genspark**：AI Slides / Sheets / Docs 一整套，并用多个模型交叉核对事实，减少幻觉。
5. **质量评测**：演示文稿在 2026 年的评测里，设计质量和 PPTX 导出保真度是两个独立维度——很多工具网页里好看，导出成 PPTX 就走样。Manus 的演示 Agent 在「导出」和「自主程度」上满分，内容准确度只有 3/5。
6. **交互式产出嵌在对话里**：ChatGPT 的应用（MCP Apps）在对话里内嵌、画中画或全屏显示交互界面（专题 2）；Hermes 桌面端用沙箱实时预览产物。

## 二、Atlas 现状

| 能力 | Atlas | 差距 |
| --- | --- | --- |
| 生成 Word / Excel / PPT | ✅ `create_document / create_spreadsheet / create_presentation`，文件面板可以预览 | 一次性生成；没有「接着改某一页、某一段」的编辑体验；设计质量没有评测过 |
| 读取 Office | ✅ `read_office` | |
| HTML / 应用预览 | ✅ 沙箱预览 | |
| 版本历史 | ✅ 文件面板历史版本 | |
| 发布成网页、自动更新 | ❌ | ChatGPT Sites |
| 分享链接 | ❌（第六波第 4 节做「导出成 HTML」） | Claude Docs、OpenClaw 可撤销只读链接 |
| 对话里的交互界面 | ❌ | MCP Apps |
| 编辑用户已经打开的本地 Office | ❌ 只能生成新文件或覆盖 | 豆包 |
| 视频、图像 | 🟡 有图像生成工具 | Manus Studio |

## 三、Atlas 要超过它们该做的

1. **活文档编辑器**：在 Atlas 里打开生成的文档或幻灯片，直接改，也可以选中某一段或某一页让 Atlas 改；保存回原来的 docx / pptx。重点保证**导出保真**，这是现在大部分产品的短板。
2. **幻灯片质量**：做设计模板和版式规则（参考 Claude Slides 和专业 PPT 工具的评测维度），生成后自动截图检查排版有没有溢出、重叠。
3. **本地发布 + 自动刷新的仪表盘**：生成的网页应用可以「发布」到本机或主机上的一个地址（局域网或 Tailscale 能访问），配合专题 2 的触发器定时刷新数据。不依赖云，是 Atlas 的差异点。
4. **分享**：导出单文件 HTML（第六波）之后，再做可撤销的只读分享链接（主机托管）。
5. **事实核对**：写报告时可选让另一个模型交叉核对关键事实和数字（Genspark 做法，对应专题 5 的多模型）。
6. **MCP Apps 渲染**（见专题 2）。

## 资料

- [Claude Docs 与 Slides beta](https://tbreak.com/claude-docs-slides-one-claude/)、[Claude Slides 详解](https://www.eesel.ai/blog/claude-slides)
- [ChatGPT Sites 功能与限制](https://playcode.io/blog/chatgpt-sites-explained)、[ChatGPT 发布说明](https://help.openai.com/en/articles/6825453-chatgpt-release-notes)
- [Microsoft 365 Copilot 的 Word、Excel、PowerPoint Agent](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/introducing-word-excel-and-powerpoint-agents-in-microsoft-365-copilot/4470604)
- [2026 AI 做 PPT 12 款排名（设计质量与导出保真度）](https://www.pi.inc/blog/ai-ppt-generation-in-2026-12-tools-ranked-by-agentic-intelligence-design-quality-and-export-fidelity)、[Excel Agent 评测](https://gptforwork.com/blog/ai-agents-for-excel-benchmark)
- [豆包工作本地 Office 编辑（2026-09-09）](https://news.qq.com/rain/a/20260909A09O4W00)、[AI 办公三强实测（36 氪）](https://www.36kr.com/p/3989030731700105)
- [Manus 2.0 Studio](https://www.explainx.ai/blog/manus-2-0-studio-cue-cascade-cloud-computer-2026)
- [Genspark 2026 功能实测](https://www.lindy.ai/blog/genspark-ai-features)
