# F1-D 派工包

2026-10-09 用户新指令与正式分工优先于下文初始派工：模型统一为 `gemini-3.8-flash`，通过 custom / Antigravity `http://127.0.0.1:8045/v1`；密钥仅从 Windows 凭据库读取。隔离设置复制 `providers.custom`、`custom_models`、`memory_model`，观察、反思、回答、判分均需验证实际路由。20 美元预算询问已解除，12 题通过后直接跑固定 120 题；未知代理价格仍如实记录，不能写为零。

已验收 A/B/C 基线于 2026-10-09 推送：Atlas `2df2e13744b6ccb8ea4714ee82cb6f4693efea2d`，MemoryOS `cc01907ae774b2bee4b5796626b72a9d4c4fdfd0`；两仓 SSH 远端核验一致，ahead/behind 均为 0/0。源码冻结已解除。A 独占 `eval_scenarios.py`、新增对应测试与 30 场景专项报告；B 独占 LongMemEval 运行器/成本与来源校验器、`real_memory.py`、共享 Gemini 隔离 helper、对应测试及 LongMemEval 专项报告；C 独占 `scripts/f1_language_smoke.py` 与 F1-B Gemini 证据/报告。各写者不得覆盖其他所有权或历史脏文件。总控亲自验收后提交推送。

所有权：Atlas `scripts/memory_v1/` 和 `docs/plan/MEMORY-V1/eval/`；报告 `progress/F1-D.md`。既有脏改动 `eval/scenario_judge_report.json` 不覆盖，输出新 F1 专属报告。总控不写产品或评测代码，施工者 GPT-6 Luna xhigh。你不是唯一写者，不能回退其他包的更改；不提交推送，不改 CURRENT，不写 ACCEPTED。

先完整读 F1-D、任务书 §6、30 场景、搬运清单及固定官方 LongMemEval 脚本。只在隔离根使用数据和服务，不碰生产数据/配置，不进入 S7。

## 第一阶段（可以先施工）

1. 实现 LongMemEval 完整运行器：原始会话 → Atlas 真实 Observer → MemoryOS HTTP → 真实召回装配 → Atlas 真实聊天入口/run_phases → 回答；用固定官方脚本判分。数据集答案仅给独立 judge，不得进入形成/召回/回答。
2. 校验已有固定120题清单及六类各20题；不删题不换题。已有清单 metadata.source_file_used 是 `longmemeval_oracle.json`，与 canonical LongMemEval_S sha 不同，须验证实际使用完整S会话而非oracle缩短历史；下载完整S放隔离artifact，不提交数据集，记录sha256。如果清单题号与完整S不兼容，向总控报真实缺失，不自行重抽。
3. 12题分层冒烟（每类2题），保存真实Observer产物/出处、召回refs、回答、官方judge输出、model/token/费用；估算120题包含观察、回答、判分的总费用。超过20美元等值则停下全量，向总控报告精确估算和依据。不能假设未知价格为0。必要时官方供应商价格来源核实，保留链接。
4. 修现有30场景脚本实际入口：当前 `run_scenario_step` 直接 `router.complete_for(..., 'chat', ...)`，只是拼装相似上下文，未真经过 run_phases；S8必须走真实API/WS或真实run_phases。动作如重启/切换模型/删除/提醒/中断不能仅改内存标志冒充。原文不能改写；不得预插形成好的记忆来提高分数。

## 第二阶段（等A/B总控验收整合后）

- 30场景×3，逐条3次判定和中位数；E1–E4/E6中位数≥90%，反例及E5/E7/E8三次全过。
- 120题真正跑完，官方脚本判分；总分≥80%，六类分数/model/token/费用/hash、失败根因；对照任务书给定公开成绩，说明来源及可比性。
- 装配≤1500 token；不得降低阈值、增top-k、全历史塞模型、按题号写答案或作弊。未达门槛如实记录并向总控提产品缺口。

## 验收材料

给总控精确命令、隔离目录、输出报告和原始log路径、两仓hash、费用估算。总控亲自读diff、跑双仓全集、抽一条真实冒烟后才整合推送。HTTP/GPU启动时间、端口先报总控；避免多服务默认开启语义后抢本地模型内存。
