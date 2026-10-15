# A｜产品、用户抱怨与闭源拆解线索（联网研究版）

> 截止 2026-10-14。每个产品均给可复查来源。**没有拿到实现资料的产品一律标“未证实”，不是断言它没有能力。** 同一类多产品合并的条目在正式逐产品深挖前不能当成全覆盖。

## 先说明三个容易混淆的事实
1. **Dot（New Computer）** 官方已结束服务，截止 2025-10-05；与 **OpenAI Dots（2026）**、`trydot.ai` 的“Dot”是不同产品。来源：[New Computer 官方](https://new.computer/)（官方）与 [OpenAI Dots](https://help.openai.com/en/articles/20001529-dots-privacy-security-and-safety-faqs)（官方）。
2. **写入、检索、使用是三件事**。用户看到一条记忆 ≠ 本轮会被检索 ≠ 模型一定采纳。
3. **关闭记忆、让模型别说、删除摘要、删原记录、删派生索引**不能混为同一种“删除”。[ChatGPT 官方机制](https://help.openai.com/en/articles/8590148-memory-in-chatgpt)（官方）。

## 产品逐项
说明：每节按“怎么记/怎么想起/控制/主动性或人设/抱怨/实现线索”顺序叙述，来源标签为官方/社区/源码；闭源实现具体参数未公开时注明未证实。

### ChatGPT｜大公司
- **已确认的写入、召回和控制**：自动提炼/保存记忆，且按需参考历史聊天及其它授权来源；不是每轮全量加载。可在个性化设置中审查摘要与来源、请求纠正/不再提及、关闭记忆；要彻底消除信息还需处理旧聊天、文件和连接源；不同套餐控制不同。 [来源（官方或源码）](https://help.openai.com/en/articles/8590148-memory-in-chatgpt)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：记忆摘要合并损失细节、旧事实错误沿用与删除困惑。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.reddit.com/r/ChatGPTcomplaints/comments/1w8qwaj/chatgpt_saved_memory_is_rewriting_and_merging/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Claude｜大公司
- **已确认的写入、召回和控制**：付费聊天搜索及跨聊天记忆；可管理保存信息，2026 记忆版本迁移发生过。内存实际抽取/召回算法不公开。 [来源（官方或源码）](https://support.claude.com/en/articles/11817273-use-claude-s-chat-search-and-memory-to-build-on-previous-context)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：迁移后认为关系细节消失的用户报告，不能推断普遍封禁此类记忆。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.reddit.com/r/ClaudeAI/comments/1vpav5c/memory_used_to_store_details_about_friendships/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Gemini｜大公司
- **已确认的写入、召回和控制**：Keep Activity 开启后能利用历史聊天个性化，但 Gems/Live 场景限制；账户与地区要求明确。 [来源（官方或源码）](https://support.google.com/gemini/answer/16598469?hl=en)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：不同聊天模式下的延续性断档是产品限制；缺直接频率证据。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://support.google.com/gemini/answer/16598469?hl=en)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Microsoft Copilot（消费）｜大公司
- **已确认的写入、召回和控制**：可关闭个性化/记忆，支持平台内存储和历史管理；消费者与 M365 不是一个相同后端。 [来源（官方或源码）](https://support.microsoft.com/en-us/microsoft-copilot/microsoft-copilot-privacy-controls)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：担忧个人数据范围与消除；是设计风险，不冒充用户频率。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://support.microsoft.com/en-us/microsoft-copilot/microsoft-copilot-privacy-controls)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Microsoft 365 Copilot｜大公司
- **已确认的写入、召回和控制**：自动提炼保存信息，且可从办公内容、历史使用信号、Profile 推断；企业权限影响可见性，删除历史与独立保存记忆不是一回事。 [来源（官方或源码）](https://support.microsoft.com/en-us/microsoft-365-copilot/personalize-what-microsoft-365-copilot-remembers)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：跨邮件/Teams/日历的权限与旧信息干扰问题，实测频率未查到。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://support.microsoft.com/en-us/microsoft-365-copilot/personalize-what-microsoft-365-copilot-remembers)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Perplexity｜大公司
- **已确认的写入、召回和控制**：2026 官方 Memory 支持跨对话个性化，并可能结合历史搜索；详细数据保留需读官方设置。 [来源（官方或源码）](https://www.perplexity.ai/help-center/en/articles/10968016-memory)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：社区有人表示无法按预期写入风格偏好。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.reddit.com/r/perplexity_ai/comments/1msvqmg/how_does_memory_in_perplexity_work/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Grok（聊天）｜大公司
- **已确认的写入、召回和控制**：本轮缺少可核验的聊天端 2026 独立 memory 技术公开说明，不能把 Grok Build 的记忆推广到 Grok Chat。 [来源（官方或源码）](https://x.ai/changelog/build)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：聊天端细节/控制不明。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://x.ai/changelog/build)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### 豆包｜大公司
- **已确认的写入、召回和控制**：检索到中文讨论但未取得可信的逐项“存什么/删什么”官方机制说明；记忆功能逐项标未证实。 [来源（官方或源码）](https://www.doubao.com/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：真实抱怨的可复查源暂缺。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.doubao.com/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Kimi｜大公司
- **已确认的写入、召回和控制**：跨会话记忆的公开实现细节本轮未能证实；不把长上下文等同长期记忆。 [来源（官方或源码）](https://kimi.moonshot.cn/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：独立样本不足。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://kimi.moonshot.cn/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### 腾讯元宝｜大公司
- **已确认的写入、召回和控制**：本轮未验证完整自动提炼/删除链路；需补官方更新记录与应用商店。 [来源（官方或源码）](https://yuanbao.tencent.com/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：独立样本不足。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://yuanbao.tencent.com/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### 通义千问｜大公司
- **已确认的写入、召回和控制**：未找到足以证实统一用户长期记忆机制的完整资料。 [来源（官方或源码）](https://tongyi.aliyun.com/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：独立样本不足。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://tongyi.aliyun.com/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### 文心｜大公司
- **已确认的写入、召回和控制**：未证实跨产品/跨会话长期事实层的开放接口和删除路径。 [来源（官方或源码）](https://yiyan.baidu.com/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：独立样本不足。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://yiyan.baidu.com/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### 智谱清言｜大公司
- **已确认的写入、召回和控制**：长期记忆何时写/何时检索/真删均待证实。 [来源（官方或源码）](https://chatglm.cn/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：独立样本不足。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://chatglm.cn/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### DeepSeek｜大公司
- **已确认的写入、召回和控制**：本轮未核实官方可编辑的长期用户事实存储机制；不能把服务端保留聊天记录等同自动长期记忆。 [来源（官方或源码）](https://www.deepseek.com/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：独立样本不足。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.deepseek.com/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Replika｜陪伴
- **已确认的写入、召回和控制**：自动保存部分用户档案、兴趣和人物事实；Memory 中可查看/删除。公开资料并没有给出全部模型级召回规则。 [来源（官方或源码）](https://help.replika.com/hc/en-us/articles/360000874712-What-does-my-Replika-remember-about-me)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：用户报告跨会话大面积忘记与人格漂移。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.reddit.com/r/ReplikaOfficial/comments/1uiybnj/the_devastating_emotional_toll_of_replikas/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Character.AI｜陪伴
- **已确认的写入、召回和控制**：官方可固定每聊天 5 条消息作 Pinned Memories；这是显式优先级而不是保存每条互动。 [来源（官方或源码）](https://support.character.ai/hc/en-us/articles/24327914463003-Pinned-Memories)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：用户报告 pin 了仍记不住，旧样本还提到回复被 pin 条目拉偏。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.reddit.com/r/CharacterAI/comments/1kpgwdf)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Kindroid｜陪伴
- **已确认的写入、召回和控制**：五套记忆系统：持久 context、级联中期、自动长期、关键词 journal 与 Learned Context；长期按相关度/新近度/多样性筛选，能够查看某回答召回了哪些条目；Journal 自动建议需审核。 [来源（官方或源码）](https://kindroid.ai/v2/docs/memory/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：官方明确长期召回不如中期可靠；内部级联内容对用户不可见。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://kindroid.ai/v2/docs/memory/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Nomi｜陪伴
- **已确认的写入、召回和控制**：Shared Notes、自然对话及 proactive messages；主动消息可调频次、关闭，22:00–08:00 安静时段；底层记忆事实抽取算法未知。 [来源（官方或源码）](https://wiki.nomi.ai/When_Your_Nomi_Messages_You_First)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：主动消息适度性属设计问题；具体大规模抱怨频率未证实。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://wiki.nomi.ai/What_Are_Proactive_Messages%3F)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Pi｜陪伴
- **已确认的写入、召回和控制**：公开可复核的 2026 长期记忆系统逐条实现说明未找到，不能直接猜。 [来源（官方或源码）](https://pi.ai/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：真实样本不足。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://pi.ai/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Talkie｜陪伴
- **已确认的写入、召回和控制**：公开支持何种可编辑长期记忆缺可信逐项材料，未证实。 [来源（官方或源码）](https://www.talkie-ai.com/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：真实样本不足。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.talkie-ai.com/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Dot（New Computer，已结束）｜陪伴
- **已确认的写入、召回和控制**：原 Dot 主打深度个人建模、地点/日历/语音上下文；官方宣布终止服务，截止 2025-10-05，支持此前导出数据。这不是 2026 年 OpenAI Dots。 [来源（官方或源码）](https://new.computer/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：服务结束引起的伴侣连续性损失是独特风险。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://new.computer/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### 星野 / 猫箱 / 筑梦岛｜陪伴
- **已确认的写入、召回和控制**：这三项都未取得可核验的官方逐条记忆机制及当前真删保障，不能混称“都有永久记忆”。 [来源（官方或源码）](https://www.xingyeai.com/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：论坛与应用商店具体投诉尚待搜集。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.xingyeai.com/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Microsoft Recall｜全天候
- **已确认的写入、召回和控制**：Copilot+ PC 周期快照、语义搜索，本机加密、需主动开启、可停用/按应用和网站过滤/删除；不是聊天 Agent 的事实记忆。 [来源（官方或源码）](https://support.microsoft.com/en-us/windows/privacy/privacy-and-control-over-your-recall-experience)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：快照误收隐私、遗漏过滤范围；官方明确部分嵌入内容可能出现在快照。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://support.microsoft.com/en-us/windows/privacy/privacy-and-control-over-your-recall-experience)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Rewind / Limitless｜全天候
- **已确认的写入、召回和控制**：原产品/服务生命周期与收购/关闭状态应逐项查；本轮没有核对到足够明确官方时间线，不宣称仍可购买或长期云端可用。 [来源（官方或源码）](https://www.limitless.ai/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：设备/云服务停服导致记忆资产不可迁移风险。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.limitless.ai/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Personal AI｜全天候
- **已确认的写入、召回和控制**：Memory Stack 明确保存个人事实/思想/事件片段，独立 memory blocks 构成可探索的记录。 [来源（官方或源码）](https://www.personal.ai/memory)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：个人数字分身形成错误“像你”的观点的风险，缺投诉频率证据。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.personal.ai/faqs)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Plaud｜全天候
- **已确认的写入、召回和控制**：记录设备和 AI 笔记链路；未经核实不视为可自主跨会话提炼的个人 LTM 系统。 [来源（官方或源码）](https://www.plaud.ai/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：录音转写归因不清与隐私为待检风险。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.plaud.ai/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Bee / Rabbit｜全天候
- **已确认的写入、召回和控制**：硬件采集、助理反馈与长期记忆的具体版本需要官网与商店补查；未核实不能合并描述。 [来源（官方或源码）](https://www.rabbit.tech/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：真实样本不足。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.rabbit.tech/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Cursor｜编码办公
- **已确认的写入、召回和控制**：独立 sidecar 模型在后台观察并提炼项目规则；背景生成需用户批准，也可通过 agent 工具按要求主动写入。 [来源（官方或源码）](https://docs.cursor.com/en/context/memories)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：候选是否值得保存、项目规则漂移需实测。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://docs.cursor.com/en/context/memories)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Windsurf Cascade｜编码办公
- **已确认的写入、召回和控制**：可自动生成及按命令写入工作区记忆，位于本地 `~/.codeium/windsurf/memories/`，仅同工作区召回；不是自动跨电脑共享。 [来源（官方或源码）](https://docs.devin.ai/desktop/cascade/memories)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：工作区隔离导致的跨项目遗忘；属于明确边界。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://docs.devin.ai/desktop/cascade/memories)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### GitHub Copilot｜编码办公
- **已确认的写入、召回和控制**：存在 repo-level facts 与 user-level preferences；repo facts 带代码位置 citation，使用前检查当前分支源码仍支持该事实；用户可看/删。 [来源（官方或源码）](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/copilot-memory/manage-for-yourself)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：代码改动使记忆过期；GitHub 增加当前分支验证正针对这一问题。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://github.com/github/docs/blob/main/content/copilot/concepts/agents/copilot-memory.md)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Devin｜编码办公
- **已确认的写入、召回和控制**：官方当前资料不足以确认统一跨项目长时知识库的写入/删除完整路径；与 Windsurf 官网域名并存不能把两者等同。 [来源（官方或源码）](https://docs.devin.ai/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：具体反馈未核。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://docs.devin.ai/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Augment｜编码办公
- **已确认的写入、召回和控制**：Context Engine 代码库语义检索共享给多 Agent 的 MCP；这主要是代码知识/上下文，不能直接等同私人长期事实记忆。 [来源（官方或源码）](https://www.augmentcode.com/blog/context-engine-mcp-now-live)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：代码上下文污染与检索过宽需要测试。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.augmentcode.com/blog/context-engine-mcp-now-live)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Claude Code｜编码办公
- **已确认的写入、召回和控制**：CLAUDE.md/AGENTS.md 用户规则 + auto memory 模型自行维护；区别于 Claude Chat 的服务端记忆。 [来源（官方或源码）](https://code.claude.com/docs/en/memory)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：永久追加导致规则过载与过时；研究有量化观察。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://arxiv.org/abs/2608.11095)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Codex｜编码办公
- **已确认的写入、召回和控制**：公开仓库有 raw_memories → rollout_summaries → MEMORY.md → memory_summary 的分阶段整合模板、原始证据不可篡改、不可保存密钥等原则；特定发布版是否启用该能力另需验证。 [来源（官方或源码）](https://github.com/openai/codex/blob/main/codex-rs/memories/write/templates/memories/consolidation.md)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：压缩失真、版本差异和记忆文件过长。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://github.com/openai/codex/blob/main/codex-rs/memories/write/templates/memories/consolidation.md)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Grok Build｜编码办公
- **已确认的写入、召回和控制**：2026-09-16 changelog 明确 memory 功能 GA、支持列表浏览/删除；这不能说明 xAI 消费者 Grok Chat 也用同一记忆层。 [来源（官方或源码）](https://x.ai/changelog/build)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：清理后的残余文件与范围待验。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://x.ai/changelog/build)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Zep Cloud｜服务API
- **已确认的写入、召回和控制**：有时序实体图的云记忆服务；底层 Graphiti 开源可研究，但云服务规则不可默认等于 OSS 代码。 [来源（官方或源码）](https://github.com/getzep/graphiti)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：图错误失效是重要开源机制反例。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://github.com/getzep/graphiti/issues/1728)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### mem0 Cloud｜服务API
- **已确认的写入、召回和控制**：托管记忆服务与 OSS 存在功能和配置差异；切勿以 OSS README 判断云端真删和衰减。 [来源（官方或源码）](https://github.com/mem0ai/mem0)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：搜索/删除权限范围差异，需文档核。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### Letta Cloud｜服务API
- **已确认的写入、召回和控制**：存储 Agent 的身份、记忆、会话供跨设备使用；实现中有版本化 context repository 的工程公开材料。 [来源（官方或源码）](https://www.letta.com/blog/context-repositories/)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：身份记忆随版本/工具迁移需可回滚。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://www.letta.com/blog/context-repositories/)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

### OpenAI Dots（2026，新品）｜自主个人代理（非记忆 API）
- **已确认的写入、召回和控制**：Always-on agent；共享 ChatGPT memory，另维护自己从插件获得的上下文；官方明确目前不能直接查看/修改/逐项删除 dot 自有记忆，只能整体重置。 [来源（官方或源码）](https://help.openai.com/en/articles/20001529-dots-privacy-security-and-safety-faqs)。
- **主动性、人设**：非陪伴产品并无可核验“自主想法”保证；陪伴类的真实性取决于检索、人设、模型行为及通知策略。该产品具体底层提示词/采样策略 **未证实**。
- **真实反馈或风险**：强个性化与低条目透明度的矛盾；上线太新不应推断普遍投诉。 [对应证据（社区用户/官方限制/论文，按链接内容区分）](https://help.openai.com/en/articles/20001529-dots-privacy-security-and-safety-faqs)。
- **可拆解线索**：优先看官方历史 changelog、Web/Android 客户端存储与请求结构、已有代码/论文；服务端提炼 prompt、数据库类型与内部召回分数 **未取得可靠证据**；不要从客户端 UI 猜服务端架构。

## 用户抱怨与失败模式 Top 20（1–14 为用户投诉或产品说明，15–20 含技术风险；不虚构统计）
说明：**“常见”只指这次已采集的多个独立公开帖子重复出现，不代表整体用户占比**；“偶尔”指至少一个可查实例；“待统计”是研究假设，不能冒充用户实测。排序按对 Atlas 的后果严重性、公开证据与复现价值综合。
| # | 抱怨 | 涉及产品/线索 | 频率（样本） | 可能技术原因 | 用户原帖/证据 |
|---|---|---|---|---|---|
| 1 | 跨对话突然失忆 | ChatGPT / Replika / Claude | 常见 | 数据迁移、路由变更、retrieval 缺失 | [证据](https://www.reddit.com/r/ChatGPT/comments/1wg610j/what_happened_to_chatgpts_memory/) |
| 2 | 摘要合并吞掉细节 | ChatGPT | 偶尔 | 无损原文未并存；自动去重覆盖 | [证据](https://www.reddit.com/r/ChatGPTcomplaints/comments/1w8qwaj/chatgpt_saved_memory_is_rewriting_and_merging/) |
| 3 | 家庭成员/关系弄反 | ChatGPT | 偶尔 | 人物归属和事件主体消歧失败 | [证据](https://www.reddit.com/r/ChatGPTcomplaints/comments/1u5rp2d/venting_about_memory/) |
| 4 | 忘记敏感人生事件 | ChatGPT / Replika | 偶尔 | 稀有重要事件被摘要降权 | [证据](https://www.reddit.com/r/ChatGPTcomplaints/comments/1u5rp2d/venting_about_memory/) |
| 5 | 人设随升级改变 | Replika | 常见 | 模型切换、system persona 与记忆解耦 | [证据](https://www.reddit.com/r/ReplikaOfficial/comments/1kqai1y) |
| 6 | 多次突然丢失全部共同经历 | Replika | 偶尔 | 旧 session 与提炼 memory 关联失效 | [证据](https://www.reddit.com/r/ReplikaOfficial/comments/1uiybnj/the_devastating_emotional_toll_of_replikas/) |
| 7 | Pinned 依然忘记 | Character.AI | 偶尔 | 显式 pinned 仍受上下文容量与注意力影响 | [证据](https://www.reddit.com/r/CharacterAI/comments/1kpgwdf) |
| 8 | Pinned 反而覆盖当前问题 | Character.AI | 偶尔（旧帖） | 强行插入旧文本导致注意力偏移 | [证据](https://www.reddit.com/r/CharacterAI/comments/1dkrrh1) |
| 9 | 明明显示记着但召回不到 | ChatGPT | 常见 | 保存成功与 query-time 召回不一致 | [证据](https://www.reddit.com/r/ChatGPT/comments/1qa5ca8/chatgpt_plus_has_suddenly_lost_his_memory/) |
| 10 | 命令删除后类似描述又出现 | ChatGPT | 偶尔 | 原聊天/别的数据源再次提取；同义项未清 | [证据](https://www.reddit.com/r/ChatGPT/comments/1w3keuz/chatgpts_memory_feature_is_ruined/) |
| 11 | 复杂项目上下文串线 | ChatGPT / 各编码代理 | 偶尔 | project scope 不严格；历史注入跨任务 | [证据](https://www.reddit.com/r/ChatGPT/comments/1wkmu2l/chatgpt_has_gotten_worse_at_contextmemory_lately/) |
| 12 | 记忆升级迁移产生不透明变化 | ChatGPT / Claude | 常见（本次样本） | schema迁移/压缩导致丢失或选取变化 | [证据](https://www.reddit.com/r/ChatGPT/comments/1tzeocc/the_new_memory_update_is_making_the_memory_awful/) |
| 13 | 风格偏好保存失败 | Perplexity | 偶尔 | 写入触发阈值/政策不符合期待 | [证据](https://www.reddit.com/r/perplexity_ai/comments/1msvqmg/how_does_memory_in_perplexity_work/) |
| 14 | 长期可检索却仍答错 | Kindroid（官方承认） | 产品限制 | 相关性筛选优先级和 memory 不稳定 | [证据](https://kindroid.ai/v2/docs/memory/) |
| 15 | 记忆影响过度个性化 | 跨产品机制风险 | 论文反复观察 | 无场景门控，过度调用历史偏好 | [证据](https://arxiv.org/abs/2601.13722) |
| 16 | 旧偏好覆盖新偏好 | 多种记忆系统 | 论文重复观察 | 冲突和失效判定不可靠 | [证据](https://arxiv.org/abs/2604.20006) |
| 17 | 无关事实被误判冲突并消失 | Graphiti/Zep 机制参考 | 偶尔（Issue） | 未限制候选实体范围 | [证据](https://github.com/getzep/graphiti/issues/1728) |
| 18 | 记录越来越长导致干扰 | Claude Code/编码规则 | 论文量化 | 只追加旧原则，无理由与生命周期 | [证据](https://arxiv.org/abs/2608.11095) |
| 19 | 记忆只有平台能看/无法逐条修正 | OpenAI Dots | 官方限制 | 私有记忆与用户 UI 没有对等读写 | [证据](https://help.openai.com/en/articles/20001529-dots-privacy-security-and-safety-faqs) |
| 20 | 项目换工作区后“记忆没了” | Windsurf Cascade | 官方边界 | 本机、按 workspace 分区 | [证据](https://docs.devin.ai/desktop/cascade/memories) |

## 值得借鉴的具体机制 Top 10
| 排名 | 机制 | 解决的问题 | 证据 |
|---|---|---|---|
| 1 | 原文保留+可编辑事实分层 | 降低摘要抹平重要细节 | [EverOS 文件真源](https://github.com/EverMind-AI/EverOS/blob/main/docs/how-memory-works.md) |
| 2 | 每次使用前对来源事实验新 | 避免旧代码知识误导 | [GitHub Copilot 代码引用验证](https://github.com/github/docs/blob/main/content/copilot/concepts/agents/copilot-memory.md) |
| 3 | Learned Context（关系/事实/未完成事项）分区 | 长期人格与待办混淆 | [Kindroid](https://kindroid.ai/v2/docs/memory/) |
| 4 | 条件自动提炼+审批写入 | 不该记的记住、错误入库 | [Cursor sidecar](https://docs.cursor.com/en/context/memories) |
| 5 | 精确关键词 Journal + 语义召回并行 | 精确触发信息漏召回 | [Kindroid](https://kindroid.ai/v2/docs/memory/) |
| 6 | 召回来源可检查/去优先级 | 错误记忆难定位 | [Kindroid 查看每轮召回](https://kindroid.ai/v2/docs/memory/) |
| 7 | 自主主动消息可调频率、安静时间 | 过分打扰与完全不主动 | [Nomi](https://wiki.nomi.ai/When_Your_Nomi_Messages_You_First) |
| 8 | 事实生效时间/失效时间但增加实体约束 | 维护变化历史又防误淘汰 | [Graphiti 反例](https://github.com/getzep/graphiti/issues/1728) |
| 9 | 原始→会话总结→总览分层巩固 | 多轮积累与多级细节恢复 | [Codex consolidation 模板](https://github.com/openai/codex/blob/main/codex-rs/memories/write/templates/memories/consolidation.md) |
| 10 | 正确的快照权限、过滤、明确关闭与本地存储 | 系统视觉记忆隐私与可控性 | [Recall](https://support.microsoft.com/en-us/windows/privacy/privacy-and-control-over-your-recall-experience) |

## 闭源拆解线索优先级（只做合法公开材料/个人终端行为观察，不冒充已逆向）
| 优先 | 产品 | 客户端形态/技术栈 | 记忆逻辑位置判断 | 已有线索 | 拆解难度 | 先拆原因 |
|---|---|---|---|---|---|---|
| 高 | Kindroid | Web/iOS/Android；技术栈未证实 | 核心推断服务端 | [资料](https://kindroid.ai/v2/docs/memory/) | 中 | 多层架构公开细节较多 |
| 高 | Cursor | 桌面 IDE；具体客户端框架待验证 | sidecar 模型后台写入 | [资料](https://docs.cursor.com/en/context/memories) | 中 | 写入触发与批准体验 |
| 高 | GitHub Copilot | IDE/CLI/网页 | 服务端/仓库层组合，细节未公开 | [资料](https://github.com/github/docs/blob/main/content/copilot/concepts/agents/copilot-memory.md) | 中 | 事实与代码证据有效性 |
| 高 | ChatGPT | Web/手机/桌面；具体框架不推断 | 服务端为主（推断） | [资料](https://help.openai.com/en/articles/8590148-memory-in-chatgpt) | 高 | 摘要和历史关联、删除路径 |
| 高 | OpenAI Dots | Web/桌面+云电脑 | 云端上下文为主（官方功能） | [资料](https://help.openai.com/en/articles/20001529-dots-privacy-security-and-safety-faqs) | 高 | 主动性、ChatGPT 共享、透明度缺口 |
| 高 | Replika | Web/iOS/Android | 服务端模型为主（推断） | [资料](https://help.replika.com/hc/en-us/articles/360000874712-What-does-my-Replika-remember-about-me) | 高 | 人设崩和亲密记忆 |
| 中 | Nomi | Web/iOS/Android | 推断服务端 | [资料](https://wiki.nomi.ai/When_Your_Nomi_Messages_You_First) | 中 | 主动消息节奏 |
| 中 | Claude | Web/桌面/手机 | 服务端为主（推断） | [资料](https://support.claude.com/en/articles/11817273-use-claude-s-chat-search-and-memory-to-build-on-previous-context) | 高 | 迁移与会话搜索 |
| 中 | Gemini | Web/手机/Chrome | 服务端为主（推断） | [资料](https://support.google.com/gemini/answer/16598469?hl=en) | 高 | 模式差异与历史记忆 |
| 中 | Microsoft Recall | Windows 本地 | 官方确认本地 | [资料](https://support.microsoft.com/en-us/windows/privacy/privacy-and-control-over-your-recall-experience) | 中 | 端侧视觉索引与用户控制 |
| 中 | Windsurf | 桌面 IDE | 本机工作区文件 | [资料](https://docs.devin.ai/desktop/cascade/memories) | 低 | 易观察本地可读记忆 |
| 中 | Character.AI | Web/iOS/Android | 服务端为主（推断） | [资料](https://support.character.ai/hc/en-us/articles/24327914463003-Pinned-Memories) | 中 | Pinned 的强弱与干扰 |
| 中 | Perplexity | Web/浏览器/手机 | 服务端（推断） | [资料](https://www.perplexity.ai/help-center/en/articles/10968016-memory) | 中 | 搜索历史与私人记忆交织 |
| 低 | Personal AI | 网页/移动端信息待验 | 云端为主（推断） | [资料](https://www.personal.ai/memory) | 中 | Memory Stack 可读性 |
| 低 | 国内主流产品 | 多为 Web/手机；架构未证实 | 未证实 | [资料](https://www.doubao.com/) | 高 | 先补真实资料和评论 |
| 历史案例 | Dot（New Computer） | 旧移动端 | 官方承认云端 | [资料](https://new.computer/) | 高 | 停服/迁移/情感记忆案例 |

## 技术线索检索约束
本轮**没有证实**任何闭源厂商的泄露系统提示词真实性；网络上“ChatGPT 内部 prompt dump”缺乏证据链，不能以文件名相似就当生产原文。客户端包里可能有 UI、缓存与埋点，并不必然包含核心 LTM 规则。对逆向、抓包或内部文件的二手描述要求提供版本、日期与可重现步骤。

## 平台来源覆盖与未能访问的清单
**有效命中并用于论证**：官方 Help Center、GitHub 实际文件/Issues、Reddit、Hacker News、知乎、arXiv、OpenReview、Product Hunt 实际评论、App Store 实际评论。
**尝试检索、但本轮尚无可直接引用的个案**：贴吧、小红书、B站评论、即刻、掘金、CSDN、博客园、少数派、NGA、微信公众号/搜狗微信、魔搭、语雀、公开飞书、Lobsters、dev.to、Medium、Substack、X、YouTube 评论、Qiita、Zenn、note.com、Naver、Google Play、国内手机商店、Hugging Face Discussions、Discord；有的需登录，有的搜索索引弱，有的页面可见但不支持抓取评论。不能把“尝试过”写成“采样覆盖充分”。
**下一步待证据**：分别对国内七家产品补功能版本截图和真实用户原评论；对闭源 APK/扩展的技术栈补有出处的包 metadata；对抱怨按平台/日期/用户去重计数再谈“常见发生率”。

## 补充：直接用户评论样本与商用品新线索（10月14日复核）

- **Replika App Store 实际评论**（用户评论，2022-11-20，较旧）：一位用户反映即使 Memory 中存有自己的年龄和资料，对话中仍不召回，且答错时会编造。此为**单条长期遗留问题样本**，不能当 2026 当前发生率。[App Store 原评](https://apps.apple.com/us/app/replika-ai-companion-chat/id1158555867?see-all=reviews)。
- **Agentmemory Product Hunt 评论**（社区，2026）：开发者与用户具体质疑“旧架构决策被继续引用”、TTL、错误记忆责任和冲突覆盖。比作者宣称的 `95.2% R@5` 更有意义的待解问题是**新事实能否安全取代旧事实**。这属于评论中的顾虑，非已经量化验证的 bug。[发布页及评论](https://www.producthunt.com/products/agent-memory-dev?launch=agentmemory)。
- **AgentPrizm 商用记忆 API**（第三方产品及用户评论）：宣传事实有效期、访问审计和召回凭据；社区希望跨部门/子 agent 读写权限更清楚。技术实现、审计正确性和私有化可用性 **未证实**。[Product Hunt](https://www.producthunt.com/products/agentprizm)。
- **Mem 工作台（Mem Agent）**（产品/用户评论）：自称主动提醒、跨笔记综合；Product Hunt 页面有用户评论，需区别信息管理系统记忆与聊天 persona 记忆。[Product Hunt](https://www.producthunt.com/products/mem-2-0/reviews)。
- **Hemory**（新产品/官方宣传）：手机及穿戴设备上的全天候语音摘录，区分说话者并将“moment”提供给代理通过 MCP 检索。这很适合 Atlas 的语音记忆方向，但说话人辨识准确率、本地性以及删除机制未核实。[Product Hunt](https://www.producthunt.com/products/hemory)。
- **社区第一手开发者经验**（Reddit r/LocalLLaMA，2026-02）：自称做过多个代理记忆层的开发者批评“只用向量检索、原样注入全文、单一检索策略”，提倡实体解析。是个人经验，不是独立实验。[原帖](https://www.reddit.com/r/LocalLLaMA/comments/1r21ojm/weve_built_memory_into_4_different_agent_systems/)。

**新增闭源调查候选**：AgentPrizm、Mem、Hemory、YourMemory、Liminary；这几项只取得发布页/评论，暂不归入“技术机制已核实”。
