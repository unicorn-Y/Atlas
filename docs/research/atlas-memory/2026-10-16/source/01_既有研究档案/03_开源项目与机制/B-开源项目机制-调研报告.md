# B｜开源项目机制调查（证据核对版）

> 核查时间：2026-10-14；定位：Atlas 的个人 Windows/中文/本地记忆底座。**本版是联网核实后的机制对比，不是已运行所有仓库的代码审计。** 未标实测的数字一概不能当本机性能。

## 检索说明
来源按可信度区分：仓库具体文件/技术文档 > 论文方法 > README 自述 > 第三方讨论；论文和 README 的 benchmark 宣传不等于相同硬件/模型/预算下可比。以下 13 项逐项目明确列出，“待验”表示尚无可靠代码证据。

## 项目逐项 13 维

### MemOS / MemTensor
- **核查入口（源码/论文）**：https://github.com/MemTensor/MemOS（源码或论文）
1. **记什么/谁写**：统一记忆 OS；支持对话/知识/工具等信息入口；确切提取提示词待逐文件复核。
2. **存储形态**：多记忆形式与管理层，具体数据库由部署配置决定。
3. **时间/冲突**：具有记忆演进设计，具体事实双时间戳与冲突策略未独立验证。
4. **认人认事**：未验证是否支持错误实体拆分。
5. **召回/排序**：混合检索、记忆路由；具体重排公式未验证。
6. **淡忘/删除**：不能把“记忆演进”宣传等同于确证的真删除。
7. **巩固/反思**：声称自演进与跨任务复用，需检查任务触发与失败恢复。
8. **出处/可信度**：来源级不变证据及投毒防线未确认。
9. **透明可修改**：有管理 API；逐条人类可编辑程度需实测。
10. **中文**：未找到严格独立中文检索质量测试。
11. **资源/本地**：可本地部署；实际常驻 RAM/CPU 和 P95 未测。
12. **效果证据/Issue**：[MemOS 论文](https://arxiv.org/abs/2507.03724)；项目成绩属于作者报告，比较需核对同条件。
13. **许可证/维护**：许可证、2026 年更新请检查仓库当期 LICENSE 和 release；版本未锁定。

### Hindsight / vectorize-io
- **核查入口（源码/论文）**：https://github.com/vectorize-io/hindsight（源码或论文）
1. **记什么/谁写**：通过 retain 显式提交，agent 集成可依据规则自动调用；提取事实/情绪/理由。
2. **存储形态**：Memory bank + 事实、观察、心智模型；内部存储需按版本确认。
3. **时间/冲突**：支持时间检索，但完整生效/失效数据模型未验证。
4. **认人认事**：实体归并机制请进一步追具体代码。
5. **召回/排序**：recall 结合语义/关键词/图/时间；reflect 进行高成本综合推理。
6. **淡忘/删除**：未证实真正级联删除的全部路径。
7. **巩固/反思**：retain / recall / reflect 是明确的阶段分工。
8. **出处/可信度**：文档建议返回记忆依据，绝不凭空补缺；原始来源逐条链未独立检查。
9. **透明可修改**：API 与 bank 范围可控制；普通用户逐条 UI 待验证。
10. **中文**：中文受嵌入/提炼模型影响，未见独立测试。
11. **资源/本地**：提供自托管与 Windows 指南；不能推断 GPU 必需。
12. **效果证据/Issue**：[Hindsight 论文](https://arxiv.org/abs/2512.12818)，自家 LongMemEval 排名不是统一第三方认证。
13. **许可证/维护**：仓库公开，许可证具体文件版本待核。

### Supermemory
- **核查入口（源码/论文）**：https://github.com/supermemoryai/supermemory（源码或论文）
1. **记什么/谁写**：自动从会话提炼事实、生成用户档案。
2. **存储形态**：记忆/API、用户画像、检索与连接器；存储实现与平台部署有关。
3. **时间/冲突**：自称处理临时事实到期和矛盾，需代码实证。
4. **认人认事**：未找到权威可拆分错误合并说明。
5. **召回/排序**：上下文检索与 profile；宣传 50ms 并非设备上基准。
6. **淡忘/删除**：宣传自动遗忘，不可视为物理删除保证。
7. **巩固/反思**：持续更新用户档案；反思过程需源码验证。
8. **出处/可信度**：逐条精确证据需复核。
9. **透明可修改**：自托管能力公开；用户编辑体验需验证。
10. **中文**：有中文 README，不等于中文召回质量。
11. **资源/本地**：自托管可用，存储栈/资源按部署而异。
12. **效果证据/Issue**：首页宣称多基准领先，未独立统一复测；[源码](https://github.com/supermemoryai/supermemory)。
13. **许可证/维护**：许可边界需核仓库 LICENSE。

### MemPalace
- **核查入口（源码/论文）**：https://github.com/mempalace/mempalace（源码或论文）
1. **记什么/谁写**：强调保留对话逐字原文，不主动摘要提炼。
2. **存储形态**：原文 + 检索索引；按 people/projects/wings/rooms/drawers 组织。
3. **时间/冲突**：缺结构化事实有效期这一设计维度。
4. **认人认事**：目录结构可作粗粒度人物项目分区；合并拆分需验证。
5. **召回/排序**：向量语义搜索 + 目录作用域缩小。
6. **淡忘/删除**：原文保存可抵御摘要遗失，但索引清理与真删除未验证。
7. **巩固/反思**：不以自动生成反思见长；相关能力未确认。
8. **出处/可信度**：原文可追溯是明显强项；检索命中不代表事实有效。
9. **透明可修改**：存在可观察性 Dashboard 需求，[Issue #1369](https://github.com/MemPalace/mempalace/issues/1369)。
10. **中文**：中文能力依赖 embedding，未见统一测试。
11. **资源/本地**：有本地使用案例；部署/性能差异大。
12. **效果证据/Issue**：[生产投诉讨论](https://github.com/MemPalace/mempalace/discussions/904) 与 [84 天实例](https://github.com/MemPalace/mempalace/discussions/2067)；不是可比 benchmark。
13. **许可证/维护**：许可证当期仓库核验。

### EverOS / EverMind-AI
- **核查入口（源码/论文）**：https://github.com/EverMind-AI/EverOS（源码或论文）
1. **记什么/谁写**：消息缓冲→切分/提取→落地 Markdown；明文是唯一真源。
2. **存储形态**：Markdown+YAML 真源；SQLite 协调/审计；LanceDB 向量/BM25/过滤派生索引。
3. **时间/冲突**：episode/atomic fact 的 deprecated_by 支持合并后退役。
4. **认人认事**：作用域有 app/project/owner；实体合并纠错机制需查。
5. **召回/排序**：LanceDB ANN+BM25+标量约束，索引可重建。
6. **淡忘/删除**：可编辑原文件，索引须 cascade rebuild；删除的全链保证要测。
7. **巩固/反思**：离线 OME、reflection_report 可审计归并。
8. **出处/可信度**：Markdown 原文+系统审计；每条 fact 精确出处仍待检查。
9. **透明可修改**：文件可人工阅读编辑，派生索引可重建。
10. **中文**：中文 BM25 和向量召回未评测。
11. **资源/本地**：无独立 DB 服务，SQLite+LanceDB；原生 Windows 仍需实际验证。
12. **效果证据/Issue**：[工作原理](https://github.com/EverMind-AI/EverOS/blob/main/docs/how-memory-works.md)；[存储布局](https://github.com/EverMind-AI/EverOS/blob/main/docs/storage_layout.md)。
13. **许可证/维护**：开源；具体许可证文件按版本核。

### claude-mem
- **核查入口（源码/论文）**：https://github.com/thedotmack/claude-mem（源码或论文）
1. **记什么/谁写**：生命周期 hooks 自动记录工具操作/会话，后台 SDK 生成观察与摘要。
2. **存储形态**：SQLite 会话/观察/摘要 + FTS5 + Chroma 向量索引。
3. **时间/冲突**：时效主要依赖会话时间与当前摘要，未验证双时间。
4. **认人认事**：项目/会话维度，跨人实体不强。
5. **召回/排序**：会话启动注入，MCP 按需搜；search→timeline→get_observations 分层披露。
6. **淡忘/删除**：没找到严格的跨 SQLite/Chroma 真删除保证。
7. **巩固/反思**：结束前总结+后台压缩，适合编码 agent。
8. **出处/可信度**：记录原工具痕迹优于只存模型结论，引用粒度需实测。
9. **透明可修改**：有 React viewer；编辑内存/索引行为仍需核实。
10. **中文**：FTS5 中文分词效果需测。
11. **资源/本地**：Bun+本地 worker；[Windows 路径与超时问题](https://github.com/thedotmack/claude-mem/blob/main/docs/public/troubleshooting.mdx)。
12. **效果证据/Issue**：[hooks 架构](https://github.com/thedotmack/claude-mem/blob/main/docs/public/architecture/hooks.mdx)；[worker 代码布局](https://github.com/thedotmack/claude-mem/blob/main/src/services/worker/README.md)。
13. **许可证/维护**：仓库 LICENSE 需按当前版本核。

### Graphiti / getzep
- **核查入口（源码/论文）**：https://github.com/getzep/graphiti（源码或论文）
1. **记什么/谁写**：episode 写入后抽取实体/关系，异步解析与维护。
2. **存储形态**：时间知识图谱，节点/edge/fact/episode；适配图数据库。
3. **时间/冲突**：valid_at / invalid_at 显式管理事实时效与矛盾失效。
4. **认人认事**：实体消歧涉及 LLM；错误合并问题属于高风险。
5. **召回/排序**：hybrid search（全文、向量、图等）与 reranking。
6. **淡忘/删除**：逻辑失效≠真删；需区分 purge 与 invalidation。
7. **巩固/反思**：持续 episode ingest 更新图，非人类式睡眠反思。
8. **出处/可信度**：可以保留 episode/fact 关联，但有不当失效风险。
9. **透明可修改**：有编程 API；完整普通用户编辑 UI 不属于核心。
10. **中文**：中文抽取和实体消歧需独立评测。
11. **资源/本地**：图数据库+LLM+embedding，总成本不能想当然很低。
12. **效果证据/Issue**：[错误失效 #1728](https://github.com/getzep/graphiti/issues/1728) [跨列表重复 #1672](https://github.com/getzep/graphiti/issues/1672)。
13. **许可证/维护**：开源项目，许可请锁定 commit 核查。

### mem0
- **核查入口（源码/论文）**：https://github.com/mem0ai/mem0（源码或论文）
1. **记什么/谁写**：add 自动抽取事实并执行 ADD/UPDATE/DELETE/NOOP；可显式写入。
2. **存储形态**：向量存储+SQLite 历史，另有 graph variant。
3. **时间/冲突**：新旧事实候选与 LLM 判断更新；双时间语义视具体版本。
4. **认人认事**：提供 user/agent/run scope，复杂别名拆分没有保证。
5. **召回/排序**：向量召回；可以追加过滤、阈值、reranker。
6. **淡忘/删除**：提供删接口；向量库/历史/缓存同步删除需实测。
7. **巩固/反思**：核心以持续提取/整合为主，独立反思不是默认主轴。
8. **出处/可信度**：保留历史 DB；原会话精确引用和推断标签需独立核验。
9. **透明可修改**：API CRUD；能否自然语言逐条纠正依赖应用层。
10. **中文**：中文模型与 embedding 可自选；未见独立对照。
11. **资源/本地**：支持本地和云模型多后端，压测应分开测。
12. **效果证据/Issue**：[真实主代码](https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py)；[论文](https://arxiv.org/abs/2504.19413) 宣称成绩勿跨设置比较。
13. **许可证/维护**：仓库许可按 LICENSE 核验。

### Letta / Letta Code
- **核查入口（源码/论文）**：https://github.com/letta-ai/letta-code（源码或论文）
1. **记什么/谁写**：agent 可主动调用工具更新 persona/user/core blocks。
2. **存储形态**：core context blocks + archival/store + git 版本化 context repositories。
3. **时间/冲突**：记忆文件可修改/版本回滚；事实时间线不是自动保证。
4. **认人认事**：persona/user 分区；复杂跨人 ID 归并未验证。
5. **召回/排序**：核心常驻 + 按需调档，取舍可由 agent 管理。
6. **淡忘/删除**：版本化利于回溯，不等于物理删除所有副本。
7. **巩固/反思**：可自编辑 prompt、技能和 agent 身份、长期项目历史。
8. **出处/可信度**：git diff 是可解释改动历史；外部证据链接仍需加。
9. **透明可修改**：自管理块/文件和用户检查能力较强。
10. **中文**：Markdown 内容自然支持中文，搜索质量需测。
11. **资源/本地**：开源本地 server，model/provider 可切换；资源依具体引擎。
12. **效果证据/Issue**：[Letta Code](https://github.com/letta-ai/letta-code) [Context Repositories](https://www.letta.com/blog/context-repositories/)。
13. **许可证/维护**：主仓库已指向新代码；旧 Letta v1 不能混为一谈。

### cognee
- **核查入口（源码/论文）**：https://github.com/topoteretes/cognee（源码或论文）
1. **记什么/谁写**：文本/文件/对话 ingest，GLiNER 本地抽实体替代大型 LLM 路线之一。
2. **存储形态**：图数据库/向量与关系存储组合，后端可变。
3. **时间/冲突**：知识图谱可演进，明确双时间能力需核代码。
4. **认人认事**：实体图抽取具归并基础，误合并撤销机制未验证。
5. **召回/排序**：图+向量混合检索。
6. **淡忘/删除**：缺乏完整真删验证。
7. **巩固/反思**：构建图谱/摘要，反思和经验技能需逐模块看。
8. **出处/可信度**：可保存来源节点但出处完整性不应先入为主。
9. **透明可修改**：面向开发者 API，个人编辑 UI 不确定。
10. **中文**：中文 GLiNER/小模型准确率需自测。
11. **资源/本地**：2026 支持无 API key 的本地 GLiNER 路线；CPU 延时未统一测。
12. **效果证据/Issue**：[仓库](https://github.com/topoteretes/cognee) [图谱论文](https://arxiv.org/abs/2505.24478)。
13. **许可证/维护**：Apache-2.0（仓库标识）。

### memU / NevaMind-AI
- **核查入口（源码/论文）**：https://github.com/NevaMind-AI/memU（源码或论文）
1. **记什么/谁写**：自动从 agent 历史抽取可复用技巧与用户信息。
2. **存储形态**：Wiki 化记忆文件+分层索引；版本快速演进。
3. **时间/冲突**：有 salience/强化等更新特性，完整时间范围需核。
4. **认人认事**：部分实体组织能力，但错误归并恢复待验。
5. **召回/排序**：层级摘要+语义/LLM 召回。
6. **淡忘/删除**：衰减/删除能力不能仅看发布说明。
7. **巩固/反思**：特别强调从历史过程提炼 skills 和主动性。
8. **出处/可信度**：引用与可信等级的实际实现要查。
9. **透明可修改**：个人 Wiki 可审阅，具体编辑/同步一致性待验。
10. **中文**：中文支持需实测。
11. **资源/本地**：Python 组件，按配置调用模型；显存和 P95 未验证。
12. **效果证据/Issue**：[1.4.0 更改记录](https://github.com/NevaMind-AI/memU/blob/main/CHANGELOG.md)。
13. **许可证/维护**：仓库 License 具体条件请检查。

### Memori / memorilabs
- **核查入口（源码/论文）**：https://github.com/memorilabs/memori（源码或论文）
1. **记什么/谁写**：面向 Agent 的会话/执行轨迹→结构化状态。
2. **存储形态**：支持标准 SQL 基础设施的 agent 原生记忆。
3. **时间/冲突**：具体 temporal schema 未验。
4. **认人认事**：复杂实体消歧待验。
5. **召回/排序**：SQL 结构化查询与记忆检索；排序细节待验。
6. **淡忘/删除**：删除链、快照和派生内容待验。
7. **巩固/反思**：自动结构化及 insight，反思需看代码。
8. **出处/可信度**：可解释性为产品主张，逐条出处待核。
9. **透明可修改**：API/企业级治理；个人 UI 未验。
10. **中文**：中文抽取需测。
11. **资源/本地**：本地/自部署形态因产品不同。
12. **效果证据/Issue**：[源码](https://github.com/memorilabs/memori) [官网](https://memorilabs.ai/)。
13. **许可证/维护**：Apache-2.0（仓库标识）。

### agentmemory / rohitg00
- **核查入口（源码/论文）**：https://github.com/rohitg00/agentmemory（源码或论文）
1. **记什么/谁写**：hooks 捕捉编码 agent 行为，压缩与复用。
2. **存储形态**：iii engine + 本地状态 DB，图和混合检索。
3. **时间/冲突**：superseded edge history 与图生命周期处理。
4. **认人认事**：图上的实体一致性，错误拆分待验。
5. **召回/排序**：混合检索，宣称 R@5 高分未复测。
6. **淡忘/删除**：含图溯源 ID 截断压缩，需警惕来源弱化。
7. **巩固/反思**：会话观察压缩和程序经验再利用。
8. **出处/可信度**：每条图节点最近 32 observations 引用是具体实现权衡。
9. **透明可修改**：Viewer 与 health 信息可看。
10. **中文**：宣传中文多语言文档；实际效果需测。
11. **资源/本地**：原生 Windows 固定 iii.exe 版本，部署限制见 README。
12. **效果证据/Issue**：[源码](https://github.com/rohitg00/agentmemory) [README 历史/压缩规则](https://github.com/rohitg00/agentmemory#readme)。
13. **许可证/维护**：Apache-2.0（仓库标识）。

### basic-memory
- **核查入口（源码/论文）**：https://github.com/basicmachines-co/basic-memory（源码或论文）
1. **记什么/谁写**：AI/人都直接读写 Markdown；不完全依赖自动提炼。
2. **存储形态**：Markdown 真源，SQLite 默认/可选 PostgreSQL，观察与 wikilinks。
3. **时间/冲突**：可以手动改旧事实，自动时间失效策略待查。
4. **认人认事**：链接及命名可手工管理实体。
5. **召回/排序**：语义与混合检索，可选 cross-encoder rerank。
6. **淡忘/删除**：删文件应同步索引，但需测同步和快照链。
7. **巩固/反思**：MCP/Claude Code pre-compact checkpoint 与交接。
8. **出处/可信度**：原文件很透明；每条声明的原始发言溯源需建模。
9. **透明可修改**：最值得研究的人机共同编辑文本和重建索引。
10. **中文**：中文支持取决于 embedding/FTS 配置。
11. **资源/本地**：SQLite 不需要 Docker；2026 Python 安装注明 prerelease。
12. **效果证据/Issue**：[源码/使用细节](https://github.com/basicmachines-co/basic-memory)。
13. **许可证/维护**：AGPL-3.0（本地 OSS，仓库说明）。

### SillyTavern World Info + 总结
- **核查入口（源码/论文）**：https://github.com/SillyTavern/SillyTavern（源码或论文）
1. **记什么/谁写**：Lorebook 人工编写为主；总结插件可定期提炼。
2. **存储形态**：World Info 词条、关键词和提示词片段。
3. **时间/冲突**：人为维护版本；无可靠时间有效期系统。
4. **认人认事**：角色/persona/chat 可绑定独立 lorebook。
5. **召回/排序**：关键字触发 + 可递归激活 + token budget。
6. **淡忘/删除**：编辑/删除 World Info 条目；聊天历史衍生仍需查。
7. **巩固/反思**：插件可压缩聊天长段落；不是严格推理式反思。
8. **出处/可信度**：原文出处与每条事实来源不自动保证。
9. **透明可修改**：人工编辑与关键词管理容易上手。
10. **中文**：中文关键词可用，分词同义词表现依配置。
11. **资源/本地**：前端运行负担低，真正模型推理取决于后端。
12. **效果证据/Issue**：[World Info 官方文档](https://github.com/SillyTavern/SillyTavern-Docs/blob/main/Usage/worldinfo.md)。
13. **许可证/维护**：仓库许可按对应主插件文件核验。

### A-MEM
- **核查入口（源码/论文）**：https://github.com/agiresearch/a-mem（源码或论文）
1. **记什么/谁写**：LLM 把交互制成带上下文/关键词/标签的原子 notes。
2. **存储形态**：卡片索引 + 相似联系的动态记忆网络。
3. **时间/冲突**：旧记忆可随新内容重写语境；严格时效待验。
4. **认人认事**：基于语义链接实体，错误拆分待验。
5. **召回/排序**：相似内容关联与语义召回。
6. **淡忘/删除**：没有证据证明删除的所有衍生指针清空。
7. **巩固/反思**：写入时联结历史、更新旧记忆表示。
8. **出处/可信度**：引用通常以 note 为单位，精确原始证据需外加。
9. **透明可修改**：卡片可读性较强。
10. **中文**：中文模型/embedding 可替换。
11. **资源/本地**：有额外生成/链接成本。
12. **效果证据/Issue**：[论文](https://arxiv.org/abs/2502.12110) [OpenReview](https://openreview.net/forum?id=FiM0M8gcct)。
13. **许可证/维护**：许可证按仓库核。

### LightMem
- **核查入口（源码/论文）**：https://github.com/zjunlp/LightMem（源码或论文）
1. **记什么/谁写**：在线快速过滤→短期按主题合并→离线慢巩固。
2. **存储形态**：感官/短期/长期三层，具体后端按仓库版本。
3. **时间/冲突**：由后台整理更新，事实冲突需要进一步对照代码。
4. **认人认事**：实体修正不是主要焦点。
5. **召回/排序**：分层检索以压缩成本。
6. **淡忘/删除**：有记忆更新但真删除链须验。
7. **巩固/反思**：sleep-time update 为核心机制。
8. **出处/可信度**：离线摘要可能丢证据，需绑定 raw 来源。
9. **透明可修改**：API 主导；UI 未证实。
10. **中文**：中国团队研究，可对照中文实验但不能直接视为保证。
11. **资源/本地**：论文作者报告 token/API/运行时大幅下降，未本地重测。
12. **效果证据/Issue**：[论文](https://arxiv.org/abs/2510.18866) [仓库](https://github.com/zjunlp/LightMem)。
13. **许可证/维护**：许可证按仓库核。

### EverMemOS（论文/项目需与 EverOS 分辨）
- **核查入口（源码/论文）**：https://arxiv.org/abs/2601.02163（源码或论文）
1. **记什么/谁写**：从长期互动自动构建可整合记忆。
2. **存储形态**：以 engram-inspired lifecycle 自组织。
3. **时间/冲突**：关注随时间更新、冲突。
4. **认人认事**：实体操作细节待核源码。
5. **召回/排序**：多层相关性路由。
6. **淡忘/删除**：淘汰政策需看代码。
7. **巩固/反思**：自组织巩固是论文重点。
8. **出处/可信度**：详细 provenance 结构需核。
9. **透明可修改**：用户级编辑 UI 未验证。
10. **中文**：中文效果未独立验证。
11. **资源/本地**：运行时和本地性需按代码核。
12. **效果证据/Issue**：[2026 论文](https://arxiv.org/abs/2601.02163)。
13. **许可证/维护**：论文不等于可复用 OSS；源码链接未完成验证。

## 13 维对比总表（简写；详见各项目 13 条）
| 项目 | 写入 | 存储 | 时间 | 实体 | 召回 | 删除 | 反思 | 溯源 | 可改 | 中文 | 本地 | 证据 | 许可 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MemOS / MemTensor | 混合 | 多态 | 待验 | 待验 | 混合 | 待验 | 演进 | 待验 | API | 待验 | 支持 | 论文 | 待核 |
| Hindsight / vectorize-io | retain | bank | 部分 | 待验 | 四路 | 待验 | reflect | 部分 | API | 待验 | 支持 | 论文 | 待核 |
| Supermemory | 自动 | 画像 | 过期 | 待验 | 语义 | 声称 | 增量 | 待验 | 部分 | 待验 | 支持 | 宣称 | 待核 |
| MemPalace | 原文 | 原文 | 弱 | 目录 | 向量 | 待验 | 弱 | 强 | 需UI | 待验 | 支持 | 讨论 | 待核 |
| EverOS / EverMind-AI | 缓冲 | MD真源 | 退役 | 分区 | 混合 | 重建 | OME | 日志 | 强 | 待验 | 强 | 源码文档 | 待核 |
| claude-mem | Hooks | SQLite | 会话 | 项目 | FTS+V | 待验 | 总结 | 轨迹 | Viewer | 待验 | 强 | 源码文档 | 待核 |
| Graphiti / getzep | 抽取 | 时序图 | 强 | LLM | 混合 | 失效≠删 | 图更新 | 部分 | API | 待验 | 需图DB | Issue | 待核 |
| mem0 | 抽取 | 向量+史 | 覆盖 | scope | 向量 | CRUD | 整合 | 部分 | API | 待验 | 强 | 源码+论文 | 待核 |
| Letta / Letta Code | 自编辑 | Blocks/Git | 版本 | 分区 | 调档 | 需实测 | 强 | Git | 强 | 待验 | 支持 | 源码 | 待核 |
| cognee | GLiNER | 图向量 | 待验 | 图 | 图+V | 待验 | 图谱 | 部分 | API | 待验 | 强 | 源码 | Apache |
| memU / NevaMind-AI | 自动 | Wiki | 部分 | 部分 | 分层 | 待验 | 技能 | 待验 | 可读 | 待验 | 支持 | 日志 | 待核 |
| Memori / memorilabs | 自动 | SQL | 待验 | 待验 | SQL | 待验 | 部分 | 待验 | API | 待验 | 支持 | 仓库 | Apache |
| agentmemory / rohitg00 | Hooks | iii DB | 历史 | 图 | 混合 | 待验 | 压缩 | 32引用 | Viewer | 待验 | Windows需设 | 仓库 | Apache |
| basic-memory | 人机共写 | MD+SQLite | 手改 | 链接 | 混合 | 需验 | checkpt | 原文 | 强 | 待验 | 强 | 仓库 | AGPL |
| SillyTavern World Info + 总结 | 人工 | 词条 | 人工 | 绑定 | 关键词 | 编辑 | 摘要 | 弱 | 强 | 可用 | 强 | 文档 | 待核 |
| A-MEM | 自动 | 卡片 | 演进 | 链接 | 相似 | 待验 | 链接 | 部分 | 卡片 | 待验 | 可用 | 论文 | 待核 |
| LightMem | 分层 | 三级 | 更新 | 弱 | 三级 | 待验 | 离线 | 待验 | API | 待验 | 可用 | 论文 | 待核 |
| EverMemOS（论文/项目需与 EverOS 分辨） | 自动 | 生命周期 | 演进 | 待验 | 分层 | 待验 | 自组织 | 待验 | 待验 | 待验 | 待验 | 论文 | 待核 |

## 补充源码定位：可以直接打开核对的关键文件

这一节区别于前面“按技术趋势推断”的描述，以下位置已从实际 GitHub 文件或官方文档页面定位；仍没有固定 commit，不能将今日 `main` 视为长期稳定 API。

| 项目 | 实际文件 | 在源码/文档中能明确看到什么 | Atlas 最该检查的边界 |
|---|---|---|---|
| Graphiti | [`graphiti_core/edges.py`](https://github.com/getzep/graphiti/blob/main/graphiti_core/edges.py) | `EntityEdge` 的 `valid_at`、`invalid_at`、`expired_at`、`reference_time`、引用 episode IDs 等字段 | “事实有效”与“系统已失效”的不同时间含义；不能因更近就消除旧历史 |
| Graphiti | [`graphiti_core/utils/maintenance/edge_operations.py`](https://github.com/getzep/graphiti/blob/main/graphiti_core/utils/maintenance/edge_operations.py) | 边抽取、节点匹配以及从事实和 episode 中提取时间戳的代码分支 | 误判同名实体、冲突范围、非日期格式、失效传播 |
| Graphiti | [Issue #1728](https://github.com/getzep/graphiti/issues/1728) | 有生产使用者报告跨全图无关关系意外失效；单例案例并非普遍事故率 | 必须使用同一实体/谓词的约束、可回滚的软失效 |
| mem0 | [`mem0/memory/main.py`](https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py) | 代码提供多种写入/检索/更新记忆函数与模型调用逻辑 | 确切 write-action 决策 prompt、重复抑制和删除级联需要逐函数验证 |
| Hindsight | [`agent-plugin/skills/hindsight-memory/SKILL.md`](https://github.com/vectorize-io/hindsight/blob/main/hindsight-integrations/agent-plugin/skills/hindsight-memory/SKILL.md) | 明确何时 `retain`、何时 `recall`、何时才调用昂贵的 `reflect`；recall 语义/关键词/图/时间四路 | agent 端策略显式编码，不应假设引擎自动知道合适触发时机 |
| Hindsight | [`best-practices.mdx`](https://github.com/vectorize-io/hindsight/blob/main/hindsight-docs/src/pages/best-practices.mdx) | 四路召回：semantic / BM25 / graph / temporal；`world`、`experience`、`observation` 三类，观察由引文支持 | 世界常识与个人经历分区；多条证据支持的推断须保留引用 |
| claude-mem | [`hooks.mdx`](https://github.com/thedotmack/claude-mem/blob/main/docs/public/architecture/hooks.mdx) | 工具完成后 Hook 将观察入队、worker 异步压缩、SQLite 保存并同步向量库；返回不阻塞编辑器 | 不可将 tool-output 作为用户本人事实；失败重试/去重 |
| claude-mem | [`hooks-architecture.mdx`](https://github.com/thedotmack/claude-mem/blob/main/docs/public/hooks-architecture.mdx) | `PostToolUse` → `observation_queue` 结构及会话关联，支持排查“为什么漏写” | raw 事件入库幂等、按会话关联、观察隐私标记 |
| EverOS | [`docs/how-memory-works.md`](https://github.com/EverMind-AI/EverOS/blob/main/docs/how-memory-works.md) | Markdown+YAML frontmatter 是 portable 真源；SQLite 审计状态和 LanceDB 索引可重建 | 文本编辑后异步同步、删除重建与审计日志保真 |
| EverOS | [`docs/storage_layout.md`](https://github.com/EverMind-AI/EverOS/blob/main/docs/storage_layout.md) | 存储目录约定、事件与索引布局 | 本地 Atlas 目录和用户可读导出方式 |

**实施含义**：先读项目对外接口，再读上表的数据模型和生命周期；不要只查 README 首页宣称的 benchmark。此处标“源码定位”不代表已审计全部函数或跑过回归。

## 逐维度目前最值得查的代码/方法（不是宣称“绝对最强”）
1. **写入与防漏**：claude-mem `plugin/hooks/hooks.json`、`src/services/worker/http/routes/`；Mem0 `mem0/memory/main.py`；更适合事件覆盖和显式更新的对照。
2. **人类可编辑真源**：EverOS `docs/how-memory-works.md` 与 `docs/storage_layout.md`；basic-memory Markdown；核心判断是索引坏了仍能从原文重建。
3. **有效期**：Graphiti `graphiti_core/utils/maintenance/edge_operations.py`；**特别看不当 invalid_at**。
4. **实体识别**：Graphiti 节点/边解析；先做消歧，再做冲突；必须具备撤销误合并。
5. **精确检索**：Hindsight `hindsight-integrations/agent-plugin/skills/hindsight-memory/SKILL.md` 的 semantic+keyword+graph+temporal；SillyTavern World Info 关键词触发；适合不同问题路由。
6. **去重与删除**：Mem0 `mem0/memory/main.py` 的事件类型；Graphiti #1728 证明“失效”也可能误删有效知识。
7. **后台巩固**：LightMem 论文 sleep-time；Hindsight reflect；EverOS OME。
8. **溯源**：MemPalace 逐字原文；GitHub Copilot 的代码引用有效性核查也值得学（闭源 A 详述）。
9. **用户透明**：basic-memory、EverOS 的 Markdown；不能依赖“问模型它记了什么”。
10. **中文**：目前没有同条件、同语料、同成本的可信全面横评；必须测中文别名、拼音、数字日期混排。
11. **本地资源**：EverOS SQLite/LanceDB、basic-memory SQLite；Graphiti 需要额外图存储与多个模型阶段。
12. **效果评价**：优先 LongMemEval（更新/拒答）、Memora/FAMA（过期）、MemoryAgentBench（遗忘/学会），不能只看 LoCoMo QA。
13. **许可证与活跃度**：AGPL-3.0 的 basic-memory 不能等同 Apache-2.0；每个组件锁 commit 后才谈复用范围。

## 从 Issues/Discussions 直接确认的设计陷阱
- **边失效的候选没有端点约束**：Graphiti #1728 报告近似文本的无关事实可能被判冲突；作者给出的某生产样本 3,950 条里有 1,616 条 invalid_at，这是单例投诉，不是总体发生率。https://github.com/getzep/graphiti/issues/1728 （源码讨论）
- **候选列表索引错位导致重复边**：Graphiti #1672，错误去重。https://github.com/getzep/graphiti/issues/1672 （Issue）
- **跨版本接口不能拿旧文档施工**：Letta 旧仓库的活跃代码已迁到 `letta-ai/letta-code`。https://github.com/letta-ai/letta （官方）
- **“永不摘要”的代价**：MemPalace 依赖全文搜索，精确性好但推理和形成稳定 belief 另需一层；讨论既有生产长期案例也有稳定性抱怨。https://github.com/MemPalace/mempalace/discussions/904 （社区）
- **索引重建的幽灵队列**：EverOS 文档明确说直接删 LanceDB 目录并不等于 reindex，要用 `cascade rebuild`，否则已完成队列会跳过。https://github.com/EverMind-AI/EverOS/blob/main/docs/how-memory-works.md （开发文档）
- **记录溯源越久越大**：agentmemory 对图节点/边留最近 32 个 observation ID 以避免极端堆积；容量和可追溯完整性必须权衡。https://github.com/rohitg00/agentmemory （源码说明）
- **Windows 运行时环境**：claude-mem 曾有 Bun PATH/Windows hook 故障指引；EverOS 的关联 Raven 曾报告原生 Windows 异常。https://github.com/thedotmack/claude-mem/blob/main/docs/public/troubleshooting.mdx ， https://github.com/EverMind-AI/Raven/issues/176 （开发者）
- **中文缺独立验证**：README 有简体翻译或 multilingual 参数不能等价于中文分词、实体歧义、日期推理通过。

## 对 Atlas 的先行排序（按个人本地复用价值）
**第一梯队**：EverOS（明文真源+索引重建）、Hindsight（retrieve/reflect 和类型思路）、Graphiti（时间事实及其教训）、LightMem（离线巩固）、claude-mem（自动捕捉与渐进查询）、Letta Code（身份/技能/版本化）。
**第二梯队**：mem0（简单易整合 CRUD）、basic-memory（编辑体验）、SillyTavern（精确触发）、memU（技能巩固）、MemPalace（全文证据）。
**第三梯队/备选**：Supermemory、Cognee、MemOS、Memori、agentmemory、A-MEM，具体取决于集成成本、Windows 兼容和当前 Atlas 已有实现的重叠率。**这不是“选赢家”，需要结合现存 Atlas 代码与质量门，再选可以直接摘取的部件。**

## 仍未核实的关键事项（不伪造）
- 各项目“提炼提示词原文”本轮没有完成逐文件摘抄；真正复用时应基于固定 commit 读取并保留 license notice。
- 全部 18 项实际磁盘、内存、CPU、写入/检索 P50/P95 和中文质量 **未实机跑**。
- 13 维中明确标“待验”的项目不可写成“没有功能”；无资料 ≠ 无实现。
- 没有逐一验证每个 repo 当日 LICENSE、commit 日期与 Issue 处理结局；参考时先锁版本。

## 未能访问或不完整的来源
- 需要登录的 Discord 私有频道、GitHub 私有 issue、部分 HF discussion 与中文 App 评论区；本轮仅收录能公开验证的链接。
- GitHub 部分 `tree/main` 路径被搜索抓取限制；已使用具体文件 URL/仓库页替代，不能声称读过全部源码。