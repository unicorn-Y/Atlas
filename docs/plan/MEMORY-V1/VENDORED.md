# MEMORY-V1 上游来源：F1 增量记录

本记录仅覆盖 F1 对已有提示词的增量，不替历史 S0–S6 搬运作完整验收。固定来源由 `02_上游搬运清单.md` 定义，不能用本记录自行写 ACCEPTED。

## Mastra（F1-B）

来源仓库 `mastra-ai/mastra`，commit `9c2e4c7cde40a4321112e24affd1750e9be827f9`。`packages/memory` 的许可为 Apache-2.0，本轮不涉及 `ee/`。保留原文件的 Copyright 2025 Kepler Software, Inc. 和 Apache-2.0 来源声明；既有 Apache NOTICE 不删除。

| 固定来源文件与行号 | 目标符号 | 本轮改动及理由 | 对照证据 |
|---|---|---|---|
| `packages/memory/src/processors/observational-memory/observer-agent.ts:48–296`；blob `37d963b6b7df63d1b44dea7e8a45ed6f3f1a23e6` | `core/atlas/memory/observer_prompt.py:OBSERVER_EXTRACTION_INSTRUCTIONS` | 保留全部原指令和英文示例，追加同语言硬规则及每类中文示例，减少中文观察翻成英文的波动 | 总控AST解析对比HEAD常量：移除F1追加文本后与原常量完全相等；原13931字符，新15412字符。test_f1_language.py及30次真模型证据 |
| 同文件 `317–395` 的输出及优先级构造规则 | `OBSERVER_OUTPUT_GUIDANCE`、`OBSERVER_GUIDELINES` | 追加中文优先级例子；guidelines不改；S2结构化JSON适配保留 | guidance原935字符，新1025；去除新增中文一行后相等。guidelines原1650字符逐字符相等 |
| `packages/memory/src/processors/observational-memory/reflector-agent.ts:41–135`；blob `bcf92d0c4b2f52aaf34daf5e4f7feed66af059db` | `core/atlas/memory/reflector.py:build_reflector_system_prompt` | 保留既有S4操作/禁区，追加各操作中文示例和同源语言规则；temperature由0.2降到0.1 | 总控读取diff，变化限定提示词和温度；定向测试验证memory_reflect调用及原有禁止删除规则 |
| 同文件 `160–232:COMPRESSION_GUIDANCE` | 既有反思提示词压缩规则 | 本轮不删除或缩减既有规则；本记录不声称重新搬运历史全部实现 | F1-B.md记录施工者已完整读固定源；完整源blob由总控git对象复核 |

语言校验与一次重试是本地F1修复，不是用规则代替Mastra模型提炼：产品仍通过 `ModelRouter.complete_for(..., purpose='memory_observe'/'memory_reflect')` 调真实模型。英文专名和技术名词保留原样；混合来源逐条跟随引用原文；失败仍保留有效观察并计数。

施工者真实语言证据：10段×3，61条中文/61条，input 153547、output 6977 token，模型 deepseek-v4.1-flash，费用未返回。总控最终源码抽检：1段×3，6条中文/6条，input 15360、output 700 token；证据 `progress/F1-B-language-smoke.*` 和 `C:/Users/25011/AppData/Local/Temp/atlas-f1-controller-b-real-smoke.log`。全集门禁仍待执行，本来源核对不能代替全集通过。

## F1-D 官方评测来源（运行尚待验收）

- 官方仓库 `https://github.com/xiaowu0162/LongMemEval`；固定 commit `9e0b455f4ef0e2ab8f2e582289761153549043fc`。总控亲验独立 checkout `D:/Temp/F1-D-official-longmemeval-9e0b455` 的 HEAD、origin 及 `src/evaluation/evaluate_qa.py` blob `4732f3772b04a2b9069121ade304e6320494abc2`；原有空 Git metadata 目录不作为来源证明。
- 完整 LongMemEval_S 来自固定 Hugging Face revision `2ec2a557f339b6c0369619b1ed5793734cc87533`，文件 `D:/Temp/F1-D-longmemeval-data-2ec2a55/longmemeval_s`。总控亲算字节数 `278025796`，SHA256 `08d8dad4be43ee2049a22ff5674eb86725d0ce5ff434cde2627e5e8e7e117894`。
- 固定120题按原 question_id 绑定完整 S 原文、日期和会话；oracle 的日期/历史不能代替完整 S。官方判分 prompt 的 gold 仅在生成答案之后进入 judge，不能进入 Observer、召回或回答输入。
- 本节只证明来源固定；12题冒烟、30场景三轮、120题效果和实际费用均未据此宣称通过。
