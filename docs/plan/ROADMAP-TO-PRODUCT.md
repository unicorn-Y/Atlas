# Atlas 成品路线图（2026-10-02，用户自己派发版）

**这份文件是从现在到「成品」的完整计划。** 用户直接拿它和各波任务书去主机 Codex 派发执行，不需要 Claude 参与；遇到第八节列的情况再找 Claude。

配套文件：
- [00-MASTER-PLAN.md](00-MASTER-PLAN.md)：已定的决定（不要推翻）
- [CORE-PARITY.md](CORE-PARITY.md)：主体对标表，每一行写了谁最强、从哪个文件拿
- [EXECUTION-GUIDE.md](EXECUTION-GUIDE.md)：环境、搬代码的方法、fork 工作流、验收清单
- `tasks/taskbooks/ATLAS-*.md`：每一波的任务书（见第四节的表）

---

## 〇、当前顺序（用户 2026-10-03 调整，优先于第四节原表）

原则：**Atlas 所有已做能力和后续能力都以当前最新第一梯队实现重新核对；追求“最新情报 + 最强实现”，不是机械跟版本号。**

1. **U0 Hermes 最新上游同步**：`ATLAS-U0-HERMES-UPSTREAM-SYNC.md`
   - 先把 NousResearch/hermes-agent current main 合进 Atlas fork；
   - 保留 Atlas 自己的增强；
   - upstream 已经做得更强的重复实现删掉/改成薄 adapter。
2. **U1 全局 Latest-Best Refresh**：`ATLAS-U1-LATEST-BEST-REFRESH.md`
   - C1–C6 全部重新对标当前 Hermes / Claude Code / Codex / OpenCode / Pi / ZCode 等；
   - 已做好的也分 KEEP / UPGRADE / REPLACE；
   - 明显落后且影响日常强度的直接升级。
3. **X2 电脑与浏览器**：使用 X-PREP 产出的 2026-10 最新任务书；以最新 Hermes Browser/Computer 栈为底，再吸收 Browser Use / Stagehand / 当前最佳 browser-agent 实现。
4. **X4 技能市场**：使用最新 Hermes Skills Hub + 当前 skills.sh / ClawHub / GitHub / Claude plugins/skills 等。
5. **X5 自我进化**：先做 upstream/changelog watcher、capability diff、parity mapper、taskbook draft、skill learning/curator 等成熟闭环，让 Atlas 后面自己持续追新。
6. **K1 上线前检查**：`ATLAS-K1-PRELAUNCH-CHECK.md`。只检查有没有问题：Hermes/Atlas 能力是否接通、测试、假模型常用路径；发现问题就修。真实日常实测由用户自己做。
7. **日常使用 → 优化循环**：`docs/plan/USAGE-FEEDBACK.md`。
8. 其他 X1/X3/X6/X7、完整 T1、R1 由用户后续决定何时启动；但任务书和来源必须保持最新。

`ATLAS-O1-HERMES-PARITY.md` 已被 K1 取代，只作参考。笔记本是 Atlas 自己的电脑。

## 一、成品的标准

Atlas 做到下面全部，才算「成品」：

1. **主体比各家强**：CORE-PARITY 每一行都是 ✔；实测阶段（T1）的同一批真实任务里，Atlas 在成功率、改错率、token 花费、体验这几项上不输 Claude Code、Codex、OpenCode、Pi、Hermes、ZCode 中最强的那家。输了的项都补完。
2. **全能**：解冻的外部功能（X1–X7：连接外部世界、电脑和浏览器、跨设备和产出物、技能市场、自我进化、语音和统一入口、**常驻个人 Agent**，对标 OpenAI dots、Meta Muse、Grok Bot、Gemini Spark 等）都做完并验收。
2.5 **笔记本是 Atlas 自己的电脑**（用户 2026-10-02 决定）：Atlas 常驻在笔记本上，相当于各家的云端虚拟机；主机是用户自己工作的机器。
3. **能交付**：
   - 安装包在干净的 Windows 机器上一次装好就能用，不需要装 Python 或 Node；
   - 升级不丢数据；
   - 连续跑 24 小时不崩、不漏内存；
   - 有中文使用说明。
4. **能持续变强**：Atlas 自己能跟踪各家更新、生成任务书草稿（X5），合并 Hermes 上游的流程跑通过。
5. **最终审查通过**（R2）。

## 二、已定的决定（摘要，全文见 00-MASTER-PLAN 第三节）

- **内核**：内核是 fork 来的 Hermes（`unicorn-Y/hermes-agent` 的 `atlas` 分支），完全归 Atlas，随便改；零件逐项换成各家最强的。
- **默认权限**：完全访问，不弹窗。
- **用户亲自负责的**：安全审查。
- **不做**：沙箱、视频生成。
- **暂缓**：本地语音，放在 X6 做。
- **冻结**：记忆系统，不扩展。
- **主体优先**：外部功能等实测通过后再做。
- **测试方式**：每波只用假模型验收；真实模型的横向实测集中在 T1。
- **接口**：所有 HTTP / WS 都过 OriginGuard，不能放宽。
- **语言**：界面和回复用中文。

## 三、现在在哪（2026-10-02）

| 波 | 状态 |
| --- | --- |
| W06、W07 | 完成；W07B 作废，内容已分进 C1、C3、C5 |
| **C1 换内核** | 施工完成；独立验收收尾中，Codex 额度用完暂停。剩下的见任务书 `ATLAS-C1R-FINISH.md` |
| C2–C6 | 任务书已写好，按顺序做 |
| T1、X1–X6、R1、R2 | 任务书已写好 |

有一个分支 `wip/c3-frontend-from-laptop`，是旧会话按旧内核写的 C3 界面草稿。C3 时作为参考，**不要直接合并**。

## 四、全部波次和顺序

| 顺序 | 波 | 任务书 | 内容 | 规模 |
| --- | --- | --- | --- | --- |
| 1 | C1R | `ATLAS-C1R-FINISH.md` | C1 验收收尾 | 小 |
| 2 | C2 | `ATLAS-C2-TOOLS-CONTEXT.md` | 删除旧循环；防打转；读图片；编辑容错取并集；按模型写提示词；压缩打磨；换干净上下文 | 中 |
| 3 | C3 | `ATLAS-C3-SESSION-INTERACTION.md` | 中途转向、会话树、检查点合一、五档权限、计划模式、Goal、斜杠命令、状态栏、上下文构成、子 Agent 界面 | 大 |
| 4 | C4 | `ATLAS-C4-EXTENSIONS.md` | Hooks 全套并兼容 CC 格式、插件兼容 CC 格式、技能合一、自定义命令、从 CC / Codex 导入 | 中 |
| 5 | C5 | `ATLAS-C5-MODELS.md` | 国内服务商原生参数、多密钥轮换、分阶段思考量、缓存未命中原因、编辑模型 | 中 |
| 6 | C6 | `ATLAS-C6-CODING-POLISH.md` | LSP 诊断、/init、/review；长会话性能；主体界面打磨 | 中 |
| 7 | T1 | `ATLAS-T1-HEAD-TO-HEAD.md` | 真实模型横向实测，输了的项生成 T1F 补做任务书 | 中（**需要用户参与**） |
| 8 | T1F | T1 生成 | 补实测输掉的项 | 视结果 |
| 9 | X1–X7 | `ATLAS-X-EXTERNAL-PHASE.md` | 解冻外部功能，每一项先按 Hermes 内核重写原任务书，再做；X7 是常驻个人 Agent（dots、Muse、Grok Bot、Spark 那一类全部抄） | 大 |
| 10 | R1 | `ATLAS-R1-RELEASE.md` | 稳定性、安装包、升级迁移、文档、清理 | 中 |
| 11 | R2 | `FINAL-REVIEW.md` | 最终审查（独立的 Sol，或者找 Claude） | 小 |

C2 到 C6 之间有前后依赖，按顺序做，不要并行开两波。原因是它们都要改 `core/atlas/engine/` 和前端事件链，同时做一定会冲突。

## 五、每一波怎么派发（用户照做）

### 1. 开工：Sol 主控

1. 主机 Codex 点「新聊天」，确认底部项目是 **Atlas**。
2. 模型选 **GPT-6.1 Sol**，推理档位选 **中**（主控主要做分派和审查，「中」就够；子代理用 high）。
3. 把 `tasks/HANDOFF.md` 第 6 节的「Sol 主控提示词」复制进去，把 `<任务书名>` 换成这一波的任务书名，然后发送。
4. Sol 会把任务拆块，开多个 **GPT-6 Luna（high）** 子代理按文件分工并行干，每块审完再提交。

### 2. 验收：独立的 Sol

1. 主控写完结果文件 `tasks/results/<任务书名>.result.md` 并停下后，**另开一个新聊天**。
2. 模型选 **GPT-6.1 Sol / 中**。
3. 粘贴 HANDOFF 第 6 节的「独立验收提示词」，换掉任务书名，发送。
4. 验收者只负责找问题和审查，修复交给它开的 Luna 子代理。

### 3. 你自己判断能不能进下一波

打开 `tasks/reviews/<任务书名>.review.md`，看三样：

| 看什么 | 能进下一波 | 先别进 |
| --- | --- | --- |
| 结论 | 写着「通过」 | 写着「部分 / 未通过」 |
| 全量测试汇总行 | 0 失败；有失败的，每个都附了「C1 之前就失败」的证据 | 有新增失败 |
| CORE-PARITY 本波的行 | 都改成 ✔ 并写了提交号 | 还有 △ 或 ✘ |

不通过时，在**同一个验收对话**里发：「把没通过的项修完，再更新验收记录。」

### 4. 常见情况怎么处理

| 情况 | 怎么办 |
| --- | --- |
| Codex 额度用完 | 等重置后，在原对话里发「继续」 |
| 上下文太满，回复变慢、反复压缩 | 停掉原对话，开新对话：用同一个提示词，末尾加「这是续做：先 `git log` 和 `git status` 看已完成和未提交的改动，读懂后接着做，不要从头来，未提交的改动不要丢」 |
| Agent 想「先交一部分」 | 回复：「不要收窄范围。任务书要求的都做完；做不到的逐条写清原因和影响。」 |
| 一个多小时没有提交 | 回复：「审过、测试通过的修复现在就提交推送，再继续。」 |
| Agent 想用真实模型测试 | 回复：「本波不用真实模型，用假模型服务。真实模型只在 T1 用。」 |
| 子代理之间改冲突了 | 回复：「按文件重新分工，每个子代理只改分给它的文件、只 git add 自己的文件；冲突的部分交给同一个子代理串行做。」 |
| 测试读到了你真实的配置或数据目录 | 回复：「所有测试必须隔离 HERMES_HOME、ATLAS_DATA_DIR 和用户主目录，查清并修好。」 |

### 5. 省额度

- 主控和验收的 Sol 都开「中」；干活的 Luna 子代理开 high。
- 一波做完立刻开新对话，不要在一个对话里连做两波。
- 不在 Codex 里让它「解释」或「总结」长文档，要它直接干活。

## 六、各波的验收底线（通用）

1. 来源项目做到的细节都做到了，搬入的代码规模和来源对得上，不是自写的缩水版。
2. CORE-PARITY 里本波的每一行，代码能证明、测试能覆盖。
3. 已有功能不倒退（CORE-PARITY 第 11 节）。
4. 全量测试和前端四项检查都通过；端到端测试从 WebSocket 发起，只把模型换成假的。
5. 每个修复一个提交，提交信息写清为什么；推送前 `git pull --rebase`。

## 七、持续「抄」各家的新东西（成品之后也一直做）

在 X5（自我进化）做出来之前，手动做，每两周一次：

1. **合并 Hermes 上游**：按 EXECUTION-GUIDE 第三点六节，在 fork 里 `git merge upstream/main`，跑测试，更新 Atlas 里固定的提交号。派发提示词：「按 EXECUTION-GUIDE 第三点六节合并 Hermes 上游；冲突逐个处理并保留 Atlas 的改动；跑全量；写 `tasks/results/HERMES-MERGE-<日期>.result.md`。」
2. **看各家更新**：信息源在 `docs/research/2026-09-30-landscape/10-tracking-sources.md`。看到 Atlas 没有、或者别家做得更好的，就在 CORE-PARITY 里加一行（写清来源、谁做得最好、从哪个文件拿），攒够 5 到 10 行开一个「C7、C8……」波次，任务书照 C2 的格式写。
3. X5 做完以后，这两步由 Atlas 自己跑，人只负责看建议、点批准。

## 八、什么时候找 Claude

- 验收两轮都没通过，Agent 说不清问题出在哪；
- 需要拍板的设计决定，比如两家做法互相冲突、要删掉已有的功能；
- T1 实测的结果要分析，补做任务书要写；
- 任务书本身有错或者过时，比如来源仓库的文件改名了；
- 想调整路线，比如插队做某个外部功能。

找的时候带上：任务书名、结果文件和验收记录的路径、最近的提交号。

## 九、风险和已知问题

| 风险 | 应对 |
| --- | --- |
| Hermes 主要在 Linux 和 macOS 上开发，Windows 支持弱 | 每波验收都在 Windows 上跑相关的 Hermes 源码测试，影响 Atlas 的就在 fork 里修 |
| 每波只用假模型，真实效果要到 T1 才知道 | T1 必须认真做，输了的项一个个补，不能跳过 |
| Codex 额度经常用完 | 按第五节第 5 条省着用；大波次拆小 |
| fork 改得越多，合并上游越难 | Atlas 专属的东西放在 `core/atlas/engine/`，fork 只改非改不可的地方 |
| 笔记本还是 Python 3.12 | 笔记本的开发版要用 3.14 重建 venv（`py -3.14 -m venv core/.venv`，再 `pip install -e D:\hermes-agent` 的对应本地路径和 `-e core`），R1 统一处理 |
