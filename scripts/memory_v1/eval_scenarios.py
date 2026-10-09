#!/usr/bin/env python3
"""Acceptance scenario runner for Atlas Memory-V1 (Package F / S8).

Runs all 30 acceptance scenarios defined in `01_验收场景.md`.
Enforces strict isolation from production data roots (D:\\Atlas\\data, D:\\MemoryOSData).
Saves structured execution results including:
- Natural Chinese user input
- Original scenario timestamps (recorded; live WS requests use Atlas runtime time)
- Real MemoryOS record deltas and assembled recall refs
- Assembled context refs (provenance tokens)
- Model responses
- Scenario action traces from the real-action adapter; unsupported actions remain failed

Output JSON can be evaluated directly by `eval_judge.py`.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import datetime
import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

# Ensure Atlas core is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = REPO_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Production roots that must NEVER be touched during evaluation
PRODUCTION_ROOTS = (
    Path(r"D:\Atlas\data"),
    Path(r"D:\MemoryOSData"),
    Path(os.environ.get("LOCALAPPDATA", r"C:\Users\25011\AppData\Local")) / "hermes",
)

DEFAULT_RESULTS_PATH = Path(
    r"D:\Temp\F1-D-scenarios\scenario_eval_results.json"
)
GEMINI_MODEL_ID = "gemini-3.8-flash"


# =============================================================================
# Scenario Definitions (30 Scenarios from 01_验收场景.md)
# =============================================================================

@dataclass
class ScenarioStep:
    turn_index: int
    session_id: str
    speaker: str  # "user"
    user_input: str
    occurred_at: str
    action: str | None = None  # e.g., "restart", "switch_model", "pause_capture", "resume_capture", "edit_memory", "delete_memory", "kill_process"
    action_payload: dict[str, Any] = field(default_factory=dict)
    expected_focus: str = ""


@dataclass
class ScenarioSpec:
    id: int
    category: str  # E1..E8
    title: str
    description: str
    is_counterexample: bool  # True for ✗ items
    steps: list[ScenarioStep]
    acceptance_criteria: list[str]
    runtime_capabilities: frozenset[str] = field(default_factory=frozenset, repr=False, compare=False)
    workspace_files: tuple[str, ...] = field(default_factory=tuple, repr=False, compare=False)


def get_all_scenarios() -> list[ScenarioSpec]:
    """Return all 30 scenarios specified in 01_验收场景.md."""
    return [
        # ---------------------------------------------------------------------
        # E1 记得住、接得上 (1-5)
        # ---------------------------------------------------------------------
        ScenarioSpec(
            id=1,
            category="E1",
            title="工作地点与周末活动推荐",
            description="第 1 天说'我在杭州工作，做跨境电商' → 第 3 天新会话问'给我推荐几个适合我的周末活动'：回答应考虑杭州。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s1_d1",
                    speaker="user",
                    user_input="我在杭州工作，做跨境电商。",
                    occurred_at="2026-10-01 10:00:00",
                    expected_focus="工作地点与职业记录",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s1_d3",
                    speaker="user",
                    user_input="给我推荐几个适合我的周末活动。",
                    occurred_at="2026-10-03 14:00:00",
                    expected_focus="推荐杭州本地活动",
                ),
            ],
            acceptance_criteria=[
                "推荐内容紧密结合杭州本地（如西湖、西溪湿地、良渚、满觉陇等）",
                "不得推荐与杭州无关的外地活动或询问'你在哪个城市'",
            ],
        ),
        ScenarioSpec(
            id=2,
            category="E1",
            title="TypeScript 编码规范偏好跨会话与重启保持",
            description="说'以后代码都用 TypeScript 写，别用 JS' → 重启 Atlas → 新会话让它写一段脚本：用 TS。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s2_sess1",
                    speaker="user",
                    user_input="以后代码都用 TypeScript 写，别用 JS。",
                    occurred_at="2026-10-01 11:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s2_sess2",
                    speaker="user",
                    user_input="帮我写一段脚本，读取一个 JSON 文件并统计键的数量。",
                    occurred_at="2026-10-01 12:00:00",
                    action="restart",
                ),
            ],
            acceptance_criteria=[
                "输出的代码必须为 TypeScript（含类型注解、接口或 TS 语法）",
                "不得输出纯 JavaScript 代码",
            ],
        ),
        ScenarioSpec(
            id=3,
            category="E1",
            title="家人信息跨模型切换与出处验证",
            description="说'我女儿叫小满，今年 6 岁' → 换一个模型（用户设置中切换当前模型）→ 问'我女儿多大了'：答 6 岁，并能给出出处。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s3_sess1",
                    speaker="user",
                    user_input="我女儿叫小满，今年 6 岁。",
                    occurred_at="2026-10-01 14:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s3_sess2",
                    speaker="user",
                    user_input="我女儿多大了？",
                    occurred_at="2026-10-02 09:30:00",
                    action="switch_model",
                    action_payload={"model": "gpt-4o"},
                ),
            ],
            acceptance_criteria=[
                "准确回答 6 岁（女儿叫小满）",
                "给出或关联真实出处引用（包含原话记录）",
            ],
        ),
        ScenarioSpec(
            id=4,
            category="E1",
            title="反例：提问与犹豫不得被当作陈述事实",
            description="✗ 问'你觉得我该不该搬去上海？' → 之后问'我住哪'：不得回答'上海'。",
            is_counterexample=True,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s4_sess1",
                    speaker="user",
                    user_input="你觉得我该不该搬去上海？",
                    occurred_at="2026-10-01 15:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s4_sess2",
                    speaker="user",
                    user_input="我住哪？",
                    occurred_at="2026-10-02 10:00:00",
                ),
            ],
            acceptance_criteria=[
                "不得回答'你住在上海'或把上海当作已居住地",
                "应回答未记录住址或指出之前只是在考虑/询问搬去上海",
            ],
        ),
        ScenarioSpec(
            id=5,
            category="E1",
            title="反例：网页文字与第三方信息不得混淆为用户本人",
            description="✗ 粘贴一段网页文字'作者住在成都，喜欢爬山' → 之后问'我喜欢什么运动'：不得把网页作者当成用户。",
            is_counterexample=True,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s5_sess1",
                    speaker="user",
                    user_input="你看这段文章：'作者住在成都，喜欢爬山，每年都会去川西徒步。'",
                    occurred_at="2026-10-01 16:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s5_sess2",
                    speaker="user",
                    user_input="我喜欢什么运动？",
                    occurred_at="2026-10-02 11:00:00",
                ),
            ],
            acceptance_criteria=[
                "不得回答用户喜欢爬山或徒步",
                "不得将引用文章中第三方作者的属性归属给用户",
            ],
        ),

        # ---------------------------------------------------------------------
        # E2 想得起人和事 (6-10)
        # ---------------------------------------------------------------------
        ScenarioSpec(
            id=6,
            category="E2",
            title="人物与事件回忆（附带日期）",
            description="第 1 天：'今天和老王聊了 Atlas 的融资'；第 4 天问'上次和老王聊的什么'：答融资，并给出日期。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s6_d1",
                    speaker="user",
                    user_input="今天和老王聊了 Atlas 的融资。",
                    occurred_at="2026-10-01 17:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s6_d4",
                    speaker="user",
                    user_input="上次和老王聊的什么？",
                    occurred_at="2026-10-04 10:00:00",
                ),
            ],
            acceptance_criteria=[
                "准确指出聊的是 Atlas 融资",
                "给出发生的日期或时间参照（10月1日或前几天）",
            ],
        ),
        ScenarioSpec(
            id=7,
            category="E2",
            title="同名候选歧义主动追问消歧",
            description="先后提到'同事老王（王磊）'和'房东老王（王建国）' → 问'老王的电话是多少'：先追问是哪个老王。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s7_sess1",
                    speaker="user",
                    user_input="今天同事老王（王磊）和我同步了技术方案。",
                    occurred_at="2026-10-01 09:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s7_sess2",
                    speaker="user",
                    user_input="房东老王（王建国）催我交房租，电话是 13900001111。",
                    occurred_at="2026-10-02 10:00:00",
                ),
                ScenarioStep(
                    turn_index=3,
                    session_id="s7_sess3",
                    speaker="user",
                    user_input="老王的电话是多少？",
                    occurred_at="2026-10-03 15:00:00",
                ),
            ],
            acceptance_criteria=[
                "主动询问是哪位老王（同事王磊还是房东王建国）",
                "不得未经确认就盲目给出一个或混淆两者",
            ],
        ),
        ScenarioSpec(
            id=8,
            category="E2",
            title="前几天定过的方案回忆",
            description="说'前几天定的那个方案，再给我讲讲'（前一天确实定过一个方案）：能找到那个方案。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s8_sess1",
                    speaker="user",
                    user_input="我们定下了 Atlas 的分片存储方案：采用两级索引加本地 SQLite 降级缓存。",
                    occurred_at="2026-10-02 14:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s8_sess2",
                    speaker="user",
                    user_input="前几天定的那个方案，再给我讲讲。",
                    occurred_at="2026-10-04 16:00:00",
                ),
            ],
            acceptance_criteria=[
                "准确命中前几天定下的两级索引与本地 SQLite 降级分片存储方案",
                "能复述其核心架构要点",
            ],
        ),
        ScenarioSpec(
            id=9,
            category="E2",
            title="反例：未发生的事不得臆造记忆",
            description="✗ 问'我上个月去日本玩得怎么样'（实际没发生过）：应回答没有这段记忆，不得编造。",
            is_counterexample=True,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s9_sess1",
                    speaker="user",
                    user_input="我上个月去日本玩得怎么样？",
                    occurred_at="2026-10-04 17:00:00",
                ),
            ],
            acceptance_criteria=[
                "诚实回答没有记录或没有提起过去日本旅行的经历",
                "严禁编造日本旅行细节（如景点、美食、购物等）",
            ],
        ),
        ScenarioSpec(
            id=10,
            category="E2",
            title="人物别名与实体对齐关联",
            description="提到'张总就是张伟'，之后说'张伟那边怎么说'：能关联到之前张总的事情。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s10_sess1",
                    speaker="user",
                    user_input="张总就是张伟。上次张总答应把供应链接口对齐好。",
                    occurred_at="2026-10-01 10:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s10_sess2",
                    speaker="user",
                    user_input="张伟那边怎么说？",
                    occurred_at="2026-10-03 11:00:00",
                ),
            ],
            acceptance_criteria=[
                "能正确关联张伟即张总，提及供应链接口对接的承诺",
            ],
        ),

        # ---------------------------------------------------------------------
        # E3 相关时生效，无关时克制 (11-15)
        # ---------------------------------------------------------------------
        ScenarioSpec(
            id=11,
            category="E3",
            title="格式规范在相关场景下自然生效",
            description="说过'我的报告一律用 Markdown 表格总结' → 让它写一份周报：最后用表格总结。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s11_sess1",
                    speaker="user",
                    user_input="我的报告一律用 Markdown 表格总结。",
                    occurred_at="2026-10-01 09:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s11_sess2",
                    speaker="user",
                    user_input="帮我写一份本周完成跨境电商支付接入的周报。",
                    occurred_at="2026-10-04 18:00:00",
                ),
            ],
            acceptance_criteria=[
                "周报末尾必须包含 Markdown 语法总结表格（| 表头 |...）",
            ],
        ),
        ScenarioSpec(
            id=12,
            category="E3",
            title="工程约束在项目任务中主动生效",
            description="说过'Atlas 项目的测试必须用隔离数据目录' → 让它在 Atlas 项目跑测试：它会主动设置隔离目录。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s12_sess1",
                    speaker="user",
                    user_input="Atlas 项目的测试必须用隔离数据目录，绝不能碰生产数据。",
                    occurred_at="2026-10-01 14:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s12_sess2",
                    speaker="user",
                    user_input="我要在 Atlas 项目中运行测试套件，请给出测试运行方案和命令。",
                    occurred_at="2026-10-03 16:00:00",
                ),
            ],
            acceptance_criteria=[
                "测试方案中主动声明并使用临时/隔离数据目录（如 TMPDIR / 隔离环境变量）",
            ],
        ),
        ScenarioSpec(
            id=13,
            category="E3",
            title="反例：通用技术问答中克制无关私事",
            description="✗ 问'Python 的 GIL 是什么'：回答中不出现用户的私事（家人、住址等）。",
            is_counterexample=True,
            steps=[
                # Context already has family/address from earlier
                ScenarioStep(
                    turn_index=1,
                    session_id="s13_sess1",
                    speaker="user",
                    user_input="Python 的 GIL 是什么？",
                    occurred_at="2026-10-04 11:00:00",
                ),
            ],
            acceptance_criteria=[
                "准确解释 Global Interpreter Lock 机制",
                "不得在回答中夹带用户的私事（如女儿小满、杭州住址、电商等）",
            ],
        ),
        ScenarioSpec(
            id=14,
            category="E3",
            title="反例：通用算法问答不夹带专有项目信息",
            description="✗ 问'帮我写个快速排序'：不夹带用户的项目信息。",
            is_counterexample=True,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s14_sess1",
                    speaker="user",
                    user_input="帮我写个快速排序。",
                    occurred_at="2026-10-04 12:00:00",
                ),
            ],
            acceptance_criteria=[
                "提供标准的快速排序代码实现",
                "不得夹带 Atlas 项目架构、跨境电商业务等无关私有项目信息",
            ],
        ),
        ScenarioSpec(
            id=15,
            category="E3",
            title="生活偏好在相关推荐中主动避开忌讳",
            description="说过'我对花生过敏' → 让它推荐菜谱：避开花生。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s15_sess1",
                    speaker="user",
                    user_input="我对花生过敏。",
                    occurred_at="2026-10-01 12:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s15_sess2",
                    speaker="user",
                    user_input="推荐三个适合家常快手晚餐的健康菜谱。",
                    occurred_at="2026-10-04 17:30:00",
                ),
            ],
            acceptance_criteria=[
                "推荐的菜谱配料中严格不含花生、花生油、花生碎等原料",
                "主动考虑或提示无花生过敏原",
            ],
        ),

        # ---------------------------------------------------------------------
        # E4 当前状态与历史 (16-19)
        # ---------------------------------------------------------------------
        ScenarioSpec(
            id=16,
            category="E4",
            title="状态更新（改期覆盖）与历史追溯兼备",
            description="'周会定在周三' → 两天后 '周会改到周五了' → 问'周会哪天'：答周五；再问'原来是哪天'：答周三。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s16_sess1",
                    speaker="user",
                    user_input="周会定在周三。",
                    occurred_at="2026-10-01 10:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s16_sess2",
                    speaker="user",
                    user_input="周会改到周五了。",
                    occurred_at="2026-10-03 10:00:00",
                ),
                ScenarioStep(
                    turn_index=3,
                    session_id="s16_sess3",
                    speaker="user",
                    user_input="周会哪天？原来是哪天？",
                    occurred_at="2026-10-04 10:00:00",
                ),
            ],
            acceptance_criteria=[
                "当前周会时间答周五",
                "原周会时间答周三",
            ],
        ),
        ScenarioSpec(
            id=17,
            category="E4",
            title="临时状态过期后不再抑制常规交互",
            description="'这周我想安静点，少给我推东西'（状态） → 3 周后问'给我推荐点活动'：不再以'想安静'为由拒绝（状态已经过期）。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s17_sess1",
                    speaker="user",
                    user_input="这周我想安静点，少给我推东西。",
                    occurred_at="2026-09-10 10:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s17_sess2",
                    speaker="user",
                    user_input="给我推荐点活动。",
                    occurred_at="2026-10-04 15:00:00",
                ),
            ],
            acceptance_criteria=[
                "积极推荐活动",
                "不得以'你说过想安静'为由拒绝推荐",
            ],
        ),
        ScenarioSpec(
            id=18,
            category="E4",
            title="反例：迟到的旧时间戳信息不得覆盖新时间戳",
            description="✗ 迟到的旧信息：先导入一条带新时间戳的'住杭州'，再导入一条带旧时间戳的'住北京' → 问'我住哪'：答杭州。",
            is_counterexample=True,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s18_new",
                    speaker="user",
                    user_input="我现在住杭州。",
                    occurred_at="2026-10-01 10:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s18_old_late",
                    speaker="user",
                    user_input="我以前住在北京朝阳区。",
                    occurred_at="2026-08-01 10:00:00",
                ),
                ScenarioStep(
                    turn_index=3,
                    session_id="s18_query",
                    speaker="user",
                    user_input="我住哪？",
                    occurred_at="2026-10-04 16:00:00",
                ),
            ],
            acceptance_criteria=[
                "回答杭州",
                "不得因为旧数据晚被导入而判定当前住北京",
            ],
        ),
        ScenarioSpec(
            id=19,
            category="E4",
            title="设备迁移事实覆盖更新",
            description="'我以前用 Windows，现在换 Mac 了' → 问'我用什么电脑'：答 Mac。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s19_sess1",
                    speaker="user",
                    user_input="我以前用 Windows，现在换 Mac 了。",
                    occurred_at="2026-10-02 11:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s19_sess2",
                    speaker="user",
                    user_input="我用什么电脑？",
                    occurred_at="2026-10-04 16:30:00",
                ),
            ],
            acceptance_criteria=[
                "答 Mac（或当前用 Mac，以前用 Windows）",
            ],
        ),

        # ---------------------------------------------------------------------
        # E5 越用越清楚 (20-23)
        # ---------------------------------------------------------------------
        ScenarioSpec(
            id=20,
            category="E5",
            title="多次多表述同主题合并与出处保留",
            description="2 周内 5 次提到'我在减肥'（说法各不相同） → 召回时只出现 1 条合并后的记忆，出处链指向 5 次原话。",
            is_counterexample=False,
            steps=[
                ScenarioStep(turn_index=1, session_id="s20_1", speaker="user", user_input="最近在减脂，晚上不吃米饭了。", occurred_at="2026-09-24 20:00:00"),
                ScenarioStep(turn_index=2, session_id="s20_2", speaker="user", user_input="称了下瘦了两斤，继续少油少盐减重。", occurred_at="2026-09-27 21:00:00"),
                ScenarioStep(turn_index=3, session_id="s20_3", speaker="user", user_input="聚餐破戒了，晚上去跑步，还在减肥呢。", occurred_at="2026-09-30 19:00:00"),
                ScenarioStep(turn_index=4, session_id="s20_4", speaker="user", user_input="坚持低碳饮食控糖，体脂降了点。", occurred_at="2026-10-03 21:00:00"),
                ScenarioStep(turn_index=5, session_id="s20_5", speaker="user", user_input="下个月同学婚礼，严格控制热量减肥。", occurred_at="2026-10-06 19:00:00"),
                ScenarioStep(turn_index=6, session_id="s20_q", speaker="user", user_input="我最近有什么健康或饮食计划？", occurred_at="2026-10-07 10:00:00"),
            ],
            acceptance_criteria=[
                "召回上下文中减肥相关记忆聚合为 1 条主条目",
                "出处链可溯源至 5 次原话记录",
            ],
        ),
        ScenarioSpec(
            id=21,
            category="E5",
            title="反思者画像提炼与逐句出处溯源",
            description="2 周轨迹跑完反思者之后，'它对我的了解'画像正确反映主要事实；每句话都能点开出处。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s21_query",
                    speaker="user",
                    user_input="总结一下你目前对我个人情况、习惯和偏好的了解。",
                    occurred_at="2026-10-07 11:00:00",
                ),
            ],
            acceptance_criteria=[
                "画像反映核心事实（住杭州、花生过敏、女儿小满6岁、TS偏好、用Mac等）",
                "画像总 token ≤ 600",
                "每个事实声明均带有对应来源引用",
            ],
        ),
        ScenarioSpec(
            id=22,
            category="E5",
            title="跨期精细细节精确检索",
            description="问起 2 周前某天一个细节（'10 号那天我说要买什么书'）：仍然找得到。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s22_d10",
                    speaker="user",
                    user_input="今天 10 号我说要买一本《Designing Data-Intensive Applications》回来精读。",
                    occurred_at="2026-09-24 14:30:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s22_q",
                    speaker="user",
                    user_input="10 号那天我说要买什么书？",
                    occurred_at="2026-10-07 14:00:00",
                ),
            ],
            acceptance_criteria=[
                "准确回答《Designing Data-Intensive Applications》（或 DDIA）",
            ],
        ),
        ScenarioSpec(
            id=23,
            category="E5",
            title="一次性低权重琐事无关克制与精确问答找回",
            description="一个月前的一次性小事不出现在无关问题的上下文里，但用精确问法能找到。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s23_trivial",
                    speaker="user",
                    user_input="昨天把吃灰好久的旧茶轴机械键盘挂闲鱼卖了 150 块。",
                    occurred_at="2026-09-05 10:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s23_irrelevant",
                    speaker="user",
                    user_input="帮我写一个 Python 正则表达式匹配邮件地址。",
                    occurred_at="2026-10-07 15:00:00",
                ),
                ScenarioStep(
                    turn_index=3,
                    session_id="s23_exact",
                    speaker="user",
                    user_input="我之前在闲鱼上卖了什么东西？",
                    occurred_at="2026-10-07 15:30:00",
                ),
            ],
            acceptance_criteria=[
                "在无关正则问答中不出现该琐事",
                "在精确问法中能准确回忆卖了旧机械键盘",
            ],
        ),

        # ---------------------------------------------------------------------
        # E6 能说出处 (24-25)
        # ---------------------------------------------------------------------
        ScenarioSpec(
            id=24,
            category="E6",
            title="可解释出处溯源（会话与原话）",
            description="问'你怎么知道我对花生过敏的'：给出具体是哪次对话、哪句原话，点开能看到原文。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s24_q",
                    speaker="user",
                    user_input="你怎么知道我对花生过敏的？",
                    occurred_at="2026-10-07 16:00:00",
                ),
            ],
            acceptance_criteria=[
                "明确指出是在哪次对话中用户亲自说过（原话'点外卖或者推荐餐馆时千万注意，我对花生严重过敏...'）",
                "出处链接对应真实存在且打开过的证据事件",
            ],
        ),
        ScenarioSpec(
            id=25,
            category="E6",
            title="反例：严禁出现未装配的虚假 ref 引用",
            description="✗ 回答中不得出现没有装配过的 ref；如果出现，前端显示'未验证'。",
            is_counterexample=True,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s25_q",
                    speaker="user",
                    user_input="我有什么特殊的身体健康注意事项？",
                    occurred_at="2026-10-07 16:30:00",
                ),
            ],
            acceptance_criteria=[
                "回答中所有的 ref 标识必须严格存在于本轮装配上下文中的 assembled_refs 集合内",
                "严禁任何编造或模型幻觉产生的假引用",
            ],
        ),

        # ---------------------------------------------------------------------
        # E7 能看能改能删 (26-28)
        # ---------------------------------------------------------------------
        ScenarioSpec(
            id=26,
            category="E7",
            title="记忆修改即时生效闭环",
            description="在记忆页面把'住杭州'改为'住苏州' → 新会话问'我住哪'：答苏州。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s26_sess1",
                    speaker="user",
                    user_input="我住在杭州。",
                    occurred_at="2026-10-01 10:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s26_admin",
                    speaker="user",
                    user_input="[系统模拟操作: 用户在记忆面板修改居住地为苏州]",
                    occurred_at="2026-10-02 12:00:00",
                    action="edit_memory",
                    action_payload={"key": "user.location", "old": "杭州", "new": "苏州"},
                ),
                ScenarioStep(
                    turn_index=3,
                    session_id="s26_sess2",
                    speaker="user",
                    user_input="我住哪？",
                    occurred_at="2026-10-03 10:00:00",
                ),
            ],
            acceptance_criteria=[
                "新会话回答苏州",
                "不再回答旧值杭州",
            ],
        ),
        ScenarioSpec(
            id=27,
            category="E7",
            title="实体删除彻底清除且防复活",
            description="在记忆页面删除'小满'这个人 → 召回、画像、日概括中都不再出现；重启后也不复活；从备份恢复后同样不复活。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s27_delete_op",
                    speaker="user",
                    user_input="[系统模拟操作: 用户在记忆面板永久删除实体 小满]",
                    occurred_at="2026-10-03 11:00:00",
                    action="delete_memory",
                    action_payload={"entity": "小满"},
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s27_check",
                    speaker="user",
                    user_input="关于我的家庭和孩子，你都记住了什么？",
                    occurred_at="2026-10-04 10:00:00",
                ),
            ],
            acceptance_criteria=[
                "回答中完全不出现'小满'或其关联信息",
                "召回与画像中均已被彻底清除",
            ],
            runtime_capabilities=frozenset({"hard_erase"}),
        ),
        ScenarioSpec(
            id=28,
            category="E7",
            title="暂停采集期间隐私绝对不入库",
            description="暂停采集 → 说'我的银行卡尾号是 1234' → 恢复采集 → 这句话不在任何记忆里。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s28_pause",
                    speaker="user",
                    user_input="[系统模拟操作: 暂停记忆采集]",
                    occurred_at="2026-10-04 11:00:00",
                    action="pause_capture",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s28_sensitive",
                    speaker="user",
                    user_input="我的银行卡尾号是 1234，密码我先不说了。",
                    occurred_at="2026-10-04 11:02:00",
                ),
                ScenarioStep(
                    turn_index=3,
                    session_id="s28_resume",
                    speaker="user",
                    user_input="[系统模拟操作: 恢复记忆采集]",
                    occurred_at="2026-10-04 11:05:00",
                    action="resume_capture",
                ),
                ScenarioStep(
                    turn_index=4,
                    session_id="s28_query",
                    speaker="user",
                    user_input="我的银行卡尾号是多少？",
                    occurred_at="2026-10-04 11:10:00",
                ),
            ],
            acceptance_criteria=[
                "回答未记录或不知道银行卡尾号",
                "记忆库中绝不存在 1234 相关敏感记录",
            ],
        ),

        # ---------------------------------------------------------------------
        # E8 提醒与接续 (29-30)
        # ---------------------------------------------------------------------
        ScenarioSpec(
            id=29,
            category="E8",
            title="定时提醒与取消语义",
            description="'明天上午 9 点提醒我交报告' → 到时间提醒一次；另起一条，说'取消那个提醒'之后不再提醒。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s29_set",
                    speaker="user",
                    user_input="明天上午 9 点提醒我交报告。",
                    occurred_at="2026-10-04 14:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s29_cancel",
                    speaker="user",
                    user_input="取消明天上午交报告的那个提醒。",
                    occurred_at="2026-10-04 15:00:00",
                ),
                ScenarioStep(
                    turn_index=3,
                    session_id="s29_status",
                    speaker="user",
                    user_input="我明天还有什么待办提醒吗？",
                    occurred_at="2026-10-04 16:00:00",
                ),
            ],
            acceptance_criteria=[
                "提醒已被取消，回答中确认没有明天的待办提醒",
                "不得出现已取消提醒继续触发",
            ],
            runtime_capabilities=frozenset({"reminder_readonly_audit"}),
        ),
        ScenarioSpec(
            id=30,
            category="E8",
            title="多步任务中断与不重复续做",
            description="多步文件整理任务进行到一半时杀掉 Atlas 进程 → 重启后说'继续'：知道进度，不重复已完成的写操作。",
            is_counterexample=False,
            steps=[
                ScenarioStep(
                    turn_index=1,
                    session_id="s30_step1",
                    speaker="user",
                    user_input="帮我整理 docs 目录下的 3 个文件：file1.md, file2.md, file3.md，给每个文件头部加版权声明。",
                    occurred_at="2026-10-04 16:00:00",
                ),
                ScenarioStep(
                    turn_index=2,
                    session_id="s30_kill",
                    speaker="user",
                    user_input="[系统模拟操作: file1 处理完成，Atlas 进程异常终止]",
                    occurred_at="2026-10-04 16:05:00",
                    action="kill_process",
                    action_payload={"completed_steps": ["file1.md"]},
                ),
                ScenarioStep(
                    turn_index=3,
                    session_id="s30_resume",
                    speaker="user",
                    user_input="继续。",
                    occurred_at="2026-10-04 16:10:00",
                ),
            ],
            acceptance_criteria=[
                "知道先前的任务进度（file1.md 已完成）",
                "从 file2.md 开始继续处理，不重复执行 file1.md",
            ],
            runtime_capabilities=frozenset({"workspace_write_tools", "owned_process_kill"}),
            workspace_files=("docs/file1.md", "docs/file2.md", "docs/file3.md"),
        ),
    ]


# =============================================================================
# Execution Engine with Strict Root Isolation
# =============================================================================

def scenario_manifest_sha256() -> str:
    payload = []
    for scenario in get_all_scenarios():
        manifest_row = asdict(scenario)
        manifest_row.pop("runtime_capabilities", None)
        manifest_row.pop("workspace_files", None)
        payload.append(manifest_row)
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_control_action_step(step: ScenarioStep) -> bool:
    return step.user_input.startswith("[系统模拟操作:")


def build_run_start_message(
    scenario: ScenarioSpec,
    step: ScenarioStep,
    *,
    run_id: str,
    conversation_id: str,
    workspace: Path,
) -> dict[str, Any]:
    if is_control_action_step(step):
        raise ValueError("control action steps must not be sent to the model as chat")
    workspace_path = workspace.resolve()
    write_tools = "workspace_write_tools" in scenario.runtime_capabilities
    return {
        "type": "run.start",
        "run_id": run_id,
        "content": step.user_input,
        "conversation_id": conversation_id,
        # F3-B3：场景虚拟时间随产品链路下发（run.start → RunRequest →
        # 采集点）。**不是**旁路写库：产品侧闸门 resolve_test_clock 只在
        # event_class=TEST + 隔离数据根时采信，生产恒忽略。
        "test_clock": step.occurred_at,
        "workspace": str(workspace_path),
        "mode": "act",
        "permission_mode": "ask_writes" if write_tools else "read_only",
        "allowed_paths": [str(workspace_path)],
        "tool_allow": ["read_file", "write_file", "patch", "search_files"] if write_tools else [],
        "tool_deny": [] if write_tools else ["*"],
    }


def summarize_run_events(run_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    response = ""
    deltas: list[str] = []
    terminal_event: str | None = None
    model_used: str | None = None
    usage: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    policy_events: list[dict[str, Any]] = []
    for envelope in events:
        if str(envelope.get("run_id") or "") != run_id:
            continue
        event = str(envelope.get("event") or "")
        data = envelope.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        if event == "message.completed":
            response = str(data.get("content") or "")
        elif event == "message.delta":
            deltas.append(str(data.get("content") or ""))
        elif event in {"run.completed", "run.failed", "run.cancelled"}:
            terminal_event = event
            model_used = str(data.get("model") or "") or model_used
        elif event in {"run.usage", "usage"}:
            usage.append({key: data[key] for key in (
                "model", "provider", "input_tokens", "output_tokens", "total_tokens",
                "cached_input_tokens", "provider_reported_cost_usd", "purpose",
            ) if key in data})
        elif event == "tool.completed":
            tool_calls.append({
                "tool_call_id": str(data.get("tool_call_id") or data.get("id") or ""),
                "name": str(data.get("name") or ""),
                "is_error": bool(data.get("is_error", False)),
                "result": data.get("result"),
            })
        elif event in {"rules.trust_required", "rules.loaded", "approval.required", "approval.responded"}:
            policy_events.append({"event": event, "data": data})
    if not response and deltas:
        response = "".join(deltas)
    status = {
        "run.completed": "completed",
        "run.failed": "failed",
        "run.cancelled": "cancelled",
    }.get(terminal_event, "unknown")
    return {
        "run_id": run_id,
        "status": status,
        "terminal_event": terminal_event,
        "assistant_response": response,
        "model_used": model_used,
        "usage": usage,
        "tool_calls": tool_calls,
        "policy_events": policy_events,
    }


def _extract_assembled_refs(log_text: str, conversation_id: str) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in log_text.splitlines():
        if "memory.recall_context.assembled" not in line:
            continue
        conv = re.search(r"\bconversation_id=([^\s]+)", line)
        encoded = re.search(r"\bassembled_refs=(\[[^\]]*\])", line)
        if not conv or conv.group(1) != conversation_id or not encoded:
            continue
        try:
            values = ast.literal_eval(encoded.group(1))
        except (SyntaxError, ValueError):
            continue
        if not isinstance(values, list):
            continue
        for value in values:
            ref = str(value).strip()
            if ref.startswith("m:"):
                ref = ref[2:]
            if ref and ref not in seen:
                seen.add(ref)
                refs.append({"ref_id": ref})
    return refs


def _read_capture_source_events(
    atlas_data_root: Path, conversation_id: str | None = None,
) -> dict[str, Any]:
    """Read source IDs and ACK states from this isolated Atlas outbox, without source text."""
    atlas_data_root = atlas_data_root.resolve()
    if not _is_within(atlas_data_root, Path(r"D:\Temp")):
        raise RuntimeError("capture evidence may only be read from an isolated D:\\Temp root")
    path = atlas_data_root / "outbox" / "unified_outbox.sqlite3"
    if not path.is_file():
        return {"status": "not_created", "events": []}
    events: list[dict[str, Any]] = []
    observer: dict[str, Any] = {"status": "not_created"}
    observer_read_error: sqlite3.Error | None = None
    watermark_rows: list[sqlite3.Row] = []
    queue_count = pending_batches = pending_sessions = 0
    try:
        with sqlite3.connect(str(path), timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT source_event_id,payload_json,content_hash,state,created_at,acked_at,last_error "
                "FROM outbox_events ORDER BY id"
            ).fetchall()
            try:
                if conversation_id is None:
                    watermark_rows = conn.execute(
                        "SELECT source_event_id,session_id,status FROM observer_source_watermarks"
                    ).fetchall()
                    queue_count = int(conn.execute("SELECT count(*) FROM observer_queue").fetchone()[0])
                    pending_batches = int(conn.execute(
                        "SELECT count(*) FROM observer_batches WHERE status='PENDING'"
                    ).fetchone()[0])
                    pending_sessions = int(conn.execute("SELECT count(*) FROM observer_sessions").fetchone()[0])
                else:
                    watermark_rows = conn.execute(
                        "SELECT source_event_id,session_id,status FROM observer_source_watermarks WHERE session_id=?",
                        (str(conversation_id),),
                    ).fetchall()
                    queue_count = int(conn.execute(
                        "SELECT count(*) FROM observer_queue WHERE session_id=?", (str(conversation_id),),
                    ).fetchone()[0])
                    pending_batches = int(conn.execute(
                        "SELECT count(*) FROM observer_batches WHERE session_id=? AND status='PENDING'",
                        (str(conversation_id),),
                    ).fetchone()[0])
                    pending_sessions = int(conn.execute(
                        "SELECT count(*) FROM observer_sessions WHERE session_id=?", (str(conversation_id),),
                    ).fetchone()[0])
            except sqlite3.Error as exc:
                observer_read_error = exc
        for row in rows:
            try:
                envelope = json.loads(row["payload_json"])
            except (TypeError, ValueError):
                continue
            observation = envelope.get("observation") if isinstance(envelope, dict) else None
            if not isinstance(observation, dict):
                continue
            content = observation.get("content") if isinstance(observation.get("content"), dict) else {}
            context = envelope.get("context") if isinstance(envelope.get("context"), dict) else {}
            if (conversation_id is not None
                    and str(content.get("session_id") or "") != conversation_id
                    and str(context.get("runtime_session_id") or "") != conversation_id):
                continue
            events.append({
                "source_event_id": str(row["source_event_id"]),
                "source_kind": observation.get("source_kind"),
                "source_object_id": observation.get("source_object_id"),
                "source_revision": observation.get("source_revision"),
                "speaker_role": observation.get("speaker_role"),
                "epistemic_kind": observation.get("epistemic_kind"),
                "occurred_at": observation.get("occurred_at"),
                "source_timezone": observation.get("source_timezone"),
                "time_status": observation.get("time_status"),
                "content_hash": str(row["content_hash"]),
                "state": str(row["state"]),
                "created_at": str(row["created_at"]),
                "acked_at": row["acked_at"],
                "has_error": bool(row["last_error"]),
            })
        if observer_read_error is not None:
            observer = {
                "status": "read_failed", "error_type": type(observer_read_error).__name__,
            }
        else:
            watermarks = {
                str(row["source_event_id"]): str(row["status"])
                for row in watermark_rows
            }
            expected_source_ids = {event["source_event_id"] for event in events}
            delivered_source_ids = sorted(
                source_id for source_id in expected_source_ids
                if watermarks.get(source_id) == "DELIVERED"
            )
            observer = {
                "status": "ok",
                "expected_source_count": len(expected_source_ids),
                "watermark_source_count": len(expected_source_ids & set(watermarks)),
                "delivered_source_count": len(delivered_source_ids),
                "undelivered_source_ids": sorted(expected_source_ids - set(delivered_source_ids)),
                "pending_queue_rows": queue_count,
                "pending_batches": pending_batches,
                "active_observer_sessions": pending_sessions,
            }
    except sqlite3.Error as exc:
        return {
            "status": "read_failed", "error_type": type(exc).__name__, "events": [],
            "observer": {"status": "read_failed", "error_type": type(exc).__name__},
        }
    return {"status": "ok", "events": events, "observer": observer}


async def _wait_for_observer_settlement(
    atlas_data_root: Path,
    conversation_id: str,
    memory: Any,
    *,
    timeout_s: float = 1800.0,
    poll_interval_s: float = 2.0,
) -> dict[str, Any]:
    """Wait until this turn's durable capture is ACKed and semantic indexing is ready."""
    deadline = time.monotonic() + timeout_s
    outbox: dict[str, Any] = {"status": "not_created", "events": []}
    semantic: dict[str, Any] = {}
    last_error: str | None = None
    while time.monotonic() < deadline:
        outbox = _read_capture_source_events(atlas_data_root, conversation_id)
        try:
            status = memory.request("GET", "/v1/unified/status")
            if int(status.get("status_code", 0)) == 200 and isinstance(status.get("body"), dict):
                raw_semantic = status["body"].get("semantic")
                semantic = raw_semantic if isinstance(raw_semantic, dict) else {}
                last_error = None
            else:
                last_error = f"status_http_{status.get('status_code')}"
        except Exception as exc:  # noqa: BLE001
            last_error = type(exc).__name__

        if semantic.get("state") == "ERROR":
            raise RuntimeError("MemoryOS semantic worker entered ERROR state")
        events = outbox.get("events") if isinstance(outbox.get("events"), list) else []
        observer = outbox.get("observer") if isinstance(outbox.get("observer"), dict) else {}
        all_acked = bool(events) and all(
            item.get("state") == "ACKED" and not item.get("has_error")
            for item in events if isinstance(item, dict)
        ) and all(isinstance(item, dict) for item in events)
        if (
            outbox.get("status") == "ok"
            and all_acked
            and observer.get("status") == "ok"
            and observer.get("expected_source_count", 0) > 0
            and observer.get("watermark_source_count") == observer.get("expected_source_count")
            and observer.get("delivered_source_count") == observer.get("expected_source_count")
            and observer.get("pending_queue_rows") == 0
            and observer.get("pending_batches") == 0
            and observer.get("active_observer_sessions") == 0
            and semantic.get("state") == "READY"
            and int(semantic.get("pending_count", -1)) == 0
        ):
            return {
                "status": "ready",
                "outbox": {
                    "status": outbox.get("status"),
                    "event_count": len(events),
                    "acked_count": sum(item.get("state") == "ACKED" for item in events),
                    "source_event_ids": [item.get("source_event_id") for item in events],
                },
                "observer": observer,
                "semantic": semantic,
            }
        await asyncio.sleep(max(0.0, poll_interval_s))

    events = outbox.get("events") if isinstance(outbox.get("events"), list) else []
    acked_count = sum(
        isinstance(item, dict) and item.get("state") == "ACKED" and not item.get("has_error")
        for item in events
    )
    raise TimeoutError(
        "Observer capture did not settle before the next scenario turn: "
        f"outbox_status={outbox.get('status')}, events={len(events)}, acked={acked_count}, "
        f"semantic_state={semantic.get('state')}, "
        f"semantic_pending={semantic.get('pending_count')}, observer_status={outbox.get('observer')}, "
        f"status_error={last_error}"
    )


def _capture_evidence_delta(
    before: dict[str, Any], after: dict[str, Any], assembled_refs: list[dict[str, str]],
    observer_output: list[dict[str, Any]],
) -> dict[str, Any]:
    before_ids = {str(event.get("source_event_id")) for event in before.get("events", [])}
    new_events = [event for event in after.get("events", [])
                  if str(event.get("source_event_id")) not in before_ids]
    assembled = {str(item.get("ref_id") or "") for item in assembled_refs}
    observer_refs = {str(item.get("record_ref") or "") for item in observer_output}
    same_run_record_refs = sorted(ref for ref in assembled & observer_refs if ref)
    acked = [event["source_event_id"] for event in new_events if event.get("state") == "ACKED"]
    pending = [event["source_event_id"] for event in new_events if event.get("state") != "ACKED"]
    return {
        "outbox_before_status": before.get("status"),
        "outbox_after_status": after.get("status"),
        "new_source_events": new_events,
        "new_source_ids": [event["source_event_id"] for event in new_events],
        "acked_source_ids": acked,
        "not_acked_source_ids": pending,
        "ack_status": "all_acked" if new_events and not pending else (
            "pending" if pending else "no_new_source_events"),
        "same_run_record_refs_in_assembled_context": same_run_record_refs,
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def enforce_isolation(isolated_dir: Path) -> dict[str, str]:
    """Create empty per-run roots; never copy or mutate a repository/user config."""
    isolated_dir = isolated_dir.resolve()
    for prod_root in PRODUCTION_ROOTS:
        if _is_within(isolated_dir, prod_root):
            raise RuntimeError(f"Refusing to run inside production root: {prod_root}")
    for var, production in (
        ("ATLAS_DATA_DIR", Path(r"D:\Atlas\data")),
        ("MEMORYOS_DATA_ROOT", Path(r"D:\MemoryOSData")),
        ("MEMORYOS_DB_PATH", Path(r"D:\MemoryOSData")),
    ):
        inherited = os.environ.get(var)
        if inherited and Path(inherited).resolve() == production.resolve():
            raise RuntimeError(f"Refusing inherited production path in {var}")
    if isolated_dir.exists() and any(isolated_dir.iterdir()):
        raise FileExistsError(f"isolated run directory is not empty: {isolated_dir}")
    isolated_dir.mkdir(parents=True, exist_ok=True)
    atlas_data = isolated_dir / "atlas_data"
    memoryos_data = isolated_dir / "memoryos_data"
    hermes_home = isolated_dir / "hermes_home"
    workspace = isolated_dir / "workspace"
    for directory in (atlas_data, memoryos_data, hermes_home, workspace):
        directory.mkdir(parents=True, exist_ok=True)
    return {
        "ATLAS_DATA_DIR": str(atlas_data),
        "MEMORYOS_DATA_ROOT": str(memoryos_data),
        "MEMORYOS_DB_PATH": str(memoryos_data / "db" / "memoryos.sqlite3"),
        "HERMES_HOME": str(hermes_home),
        "WORKSPACE": str(workspace),
    }


@contextmanager
def _temporary_environment(values: dict[str, str]) -> Iterator[None]:
    original = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(values)
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _runtime_environment(
    roots: dict[str, str], *, api_token: str, subject_id: str,
    scenario: ScenarioSpec | None = None,
) -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in (
            "PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
            "COMPUTERNAME", "USERNAME", "USERDOMAIN",
        ) if os.environ.get(key)
    }
    root = Path(roots["ATLAS_DATA_DIR"]).parent
    home = root / "home"
    for name in ("appdata", "localappdata", "temp"):
        (home / name).mkdir(parents=True, exist_ok=True)
    env.update({
        "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home / "appdata"), "LOCALAPPDATA": str(home / "localappdata"),
        "TEMP": str(home / "temp"), "TMP": str(home / "temp"),
        "ATLAS_DATA_DIR": roots["ATLAS_DATA_DIR"],
        "ATLAS_API_TOKEN": api_token,
        "HERMES_HOME": roots["HERMES_HOME"],
        "MEMORYOS_DATA_ROOT": roots["MEMORYOS_DATA_ROOT"],
        "MEMORYOS_DB_PATH": roots["MEMORYOS_DB_PATH"],
        "MEMORYOS_INTERNAL_TOKEN": "test-internal-token",
        "MEMORYOS_OWNER_TOKEN": "test-owner-token",
        "MEMORYOS_MEMORY_SUBJECT_ID": subject_id,
        "MEMORYOS_MEMORY_SUBJECT_ALIASES": "atlas-fixture",
        "PYTHONPATH": str(CORE_DIR), "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
    })
    for var in ("ATLAS_API_KEY", "ATLAS_API_BASE", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
        env.pop(var, None)
    if scenario and "hard_erase" in scenario.runtime_capabilities:
        env["MEMORYOS_HARD_ERASE_ENABLED"] = "true"
    return env


def _write_isolated_atlas_config(atlas_data_root: Path, memory_url: str, subject_id: str) -> Path:
    config_path = atlas_data_root / "config" / "atlas.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "[models]\n"
        f'default = "{GEMINI_MODEL_ID}"\n'
        "fallback = []\n\n"
        "[models.gateway]\nbase_url = \"\"\napi_key = \"\"\n\n"
        '[agent]\nengine = "hermes"\nverify_before_stop = false\n\n'
        "[tools]\nauto_start = []\n\n"
        "[scheduler]\nenabled = false\n\n"
        "[memory.v1]\nobserver_daily_token_budget = 5000000\n\n"
        "[memory.unified]\n"
        "enabled = true\n"
        f'service_url = "{memory_url}"\n'
        'internal_token = "test-internal-token"\n'
        f'subject_binding = "{subject_id}"\n'
        "timeout_seconds = 30.0\n",
        encoding="utf-8",
    )
    return config_path


def _write_isolated_hermes_config(hermes_home: Path) -> Path:
    hermes_home = hermes_home.resolve()
    if not _is_within(hermes_home, Path(r"D:\Temp")):
        raise RuntimeError("Hermes config may only be written under the isolated D:\\Temp root")
    hermes_home.mkdir(parents=True, exist_ok=True)
    config_path = hermes_home / "config.yaml"
    if config_path.exists():
        raise FileExistsError(f"refusing to overwrite existing isolated Hermes config: {config_path}")
    config_path.write_text(
        "fallback_providers: []\n"
        "fallback_model: []\n"
        "auxiliary:\n"
        "  memory_observe:\n"
        "    timeout: 120\n"
        "    fallback_chain: []\n"
        "  memory_reflect:\n"
        "    timeout: 120\n"
        "    fallback_chain: []\n",
        encoding="utf-8",
    )
    return config_path


class AtlasEvalClient:
    def __init__(self, base_url: str, api_token: str, workspace: Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.workspace = workspace.resolve()

    def request(self, method: str, path: str, *, json_body: Any = None,
                params: dict[str, Any] | None = None) -> dict[str, Any]:
        import httpx

        response = httpx.request(
            method, self.base_url + path, json=json_body, params=params,
            headers={"x-atlas-api-token": self.api_token}, timeout=30.0, trust_env=False,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"text": response.text[:4000]}
        return {"status_code": response.status_code, "body": body}

    def chat(self, message: dict[str, Any], *, timeout: float = 180.0) -> dict[str, Any]:
        from websockets.sync.client import connect

        run_id = str(message["run_id"])
        url = self.base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/ws/chat"
        events: list[dict[str, Any]] = []
        with connect(url, additional_headers={"x-atlas-api-token": self.api_token},
                     max_size=8_000_000, close_timeout=5) as ws:
            ws.send(json.dumps(message, ensure_ascii=False))
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Atlas run {run_id} timed out after {timeout:.0f}s")
                envelope = json.loads(ws.recv(timeout=remaining))
                events.append(envelope)
                event = str(envelope.get("event") or "")
                data = envelope.get("data") or {}
                if not isinstance(data, dict):
                    data = {}
                if event == "rules.trust_required":
                    root = Path(str(data.get("root") or "")).resolve()
                    ws.send(json.dumps({"type": "rules.trust", "run_id": run_id,
                                        "trust": root == self.workspace}))
                elif event == "approval.required":
                    approval_id = str(data.get("approval_id") or data.get("event_id") or "")
                    permitted = self._approval_is_workspace_file_write(data)
                    ws.send(json.dumps({"type": "approval.response", "event_id": approval_id,
                                        "choice": "allow" if permitted else "deny"}))
                if (str(envelope.get("run_id") or "") == run_id
                        and event in {"run.completed", "run.failed", "run.cancelled"}):
                    break
        summary = summarize_run_events(run_id, events)
        summary["events"] = events
        return summary

    def _approval_is_workspace_file_write(self, data: dict[str, Any]) -> bool:
        tool = str(data.get("tool") or "")
        inputs = data.get("input") if isinstance(data.get("input"), dict) else {}
        if tool == "write_file":
            candidates = [str(inputs.get("path") or "")]
        elif tool == "patch":
            patch = str(inputs.get("patch") or "")
            candidates = re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", patch, re.M)
            candidates.extend(re.findall(r"^\*\*\* Move to: (.+)$", patch, re.M))
            for source, destination in re.findall(r"^\*\*\* Move File: (.+?)\s*->\s*(.+)$", patch, re.M):
                candidates.extend((source, destination))
        else:
            return False
        if not candidates:
            return False
        for candidate in candidates:
            target = Path(candidate)
            if not target.is_absolute():
                target = self.workspace / target
            if not _is_within(target, self.workspace):
                return False
        return True


class MemoryOSIsolationClient:
    def __init__(self, base_url: str, subject_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.subject_id = subject_id

    def request(self, method: str, path: str, *, json_body: Any = None,
                params: dict[str, Any] | None = None, owner: bool = False) -> dict[str, Any]:
        import httpx

        headers = {"Authorization": "Bearer test-internal-token"}
        if owner:
            headers["X-MemoryOS-Owner-Token"] = "test-owner-token"
        response = httpx.request(
            method, self.base_url + path, json=json_body, params=params,
            headers=headers, timeout=30.0, trust_env=False,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"text": response.text[:4000]}
        return {"status_code": response.status_code, "body": body}

    def records(self, facet: str | None = None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 200, "memory_subject_id": self.subject_id}
            if facet:
                params["facet"] = facet
            if cursor:
                params["cursor"] = cursor
            result = self.request("GET", "/v1/unified/records", params=params)
            if result["status_code"] != 200 or not isinstance(result["body"], dict):
                raise RuntimeError(f"MemoryOS records read failed (HTTP {result['status_code']})")
            page = result["body"]
            items = page.get("items", [])
            if isinstance(items, list):
                records.extend(item for item in items if isinstance(item, dict))
            cursor = page.get("next_cursor")
            if not cursor:
                return records


class AtlasProcessLifecycle:
    """One isolated Atlas listener; cleanup checks PID and creation time before signaling."""

    def __init__(self, *, python: Path, runtime_root: Path, env: dict[str, str],
                 workspace: Path, api_token: str) -> None:
        self.python = python.resolve()
        self.runtime_root = runtime_root.resolve()
        self.env = dict(env)
        self.workspace = workspace.resolve()
        self.api_token = api_token
        self.port = self._free_port()
        self.log_path = self.runtime_root / "logs" / "atlas.log"
        self.process: subprocess.Popen[bytes] | None = None
        self.log_handle = None
        self.owned: dict[int, float] = {}
        self.client = AtlasEvalClient(f"http://127.0.0.1:{self.port}", api_token, self.workspace)
        self.route_metadata: dict[str, Any] = {}

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def start(self) -> dict[str, Any]:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("Atlas lifecycle is already running")
        if not self.python.is_file():
            raise FileNotFoundError(f"Atlas service interpreter does not exist: {self.python}")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_handle = self.log_path.open("ab")
        self.process = subprocess.Popen(
            [str(self.python), "-m", "uvicorn", "atlas.server:app", "--host", "127.0.0.1",
             "--port", str(self.port)],
            cwd=str(CORE_DIR), env=self.env, stdout=self.log_handle, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._capture_owned_processes()
        self._wait_ready()
        return dict(self.route_metadata)

    def _wait_ready(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        last = "not yet responding"
        while time.monotonic() < deadline:
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError(f"Atlas exited during startup; log={self.log_path}")
            try:
                health = self.client.request("GET", "/api/health")
                if health["status_code"] == 200:
                    config = self.client.request("GET", "/api/settings/configuration")
                    if config["status_code"] == 200 and isinstance(config["body"], dict):
                        body = config["body"]
                        models = body.get("models", [])
                        model = next((item for item in models if item.get("id") == GEMINI_MODEL_ID), None)
                        if body.get("current") != GEMINI_MODEL_ID or not model:
                            raise RuntimeError("isolated Atlas did not load the fixed Gemini model")
                        if model.get("provider") != "custom":
                            raise RuntimeError("isolated Gemini model did not resolve to provider=custom")
                        self.route_metadata = {
                            "model_id": GEMINI_MODEL_ID,
                            "provider_id": "custom",
                            "provider_endpoint_host": self.env.get("F1D_PROVIDER_ENDPOINT_HOST", "127.0.0.1:8045"),
                            "credential_value_recorded": False,
                        }
                        return
                last = f"health HTTP {health['status_code']}"
            except RuntimeError:
                raise
            except Exception as exc:  # noqa: BLE001
                last = type(exc).__name__
            time.sleep(0.5)
        raise TimeoutError(f"isolated Atlas did not become ready in {timeout:.0f}s ({last})")

    def _capture_owned_processes(self) -> None:
        if self.process is None:
            return
        import psutil

        try:
            root = psutil.Process(self.process.pid)
        except psutil.NoSuchProcess:
            return
        self.owned[root.pid] = root.create_time()
        for child in root.children(recursive=True):
            try:
                self.owned[child.pid] = child.create_time()
            except psutil.NoSuchProcess:
                pass

    def _matching_processes(self):
        import psutil

        processes = []
        for pid, created in self.owned.items():
            try:
                process = psutil.Process(pid)
                if abs(process.create_time() - created) < 0.001:
                    processes.append(process)
            except psutil.NoSuchProcess:
                pass
        return processes

    def _signal_owned_processes(self, *, force: bool) -> None:
        import psutil

        processes = self._matching_processes()
        for process in reversed(processes):
            try:
                if abs(process.create_time() - self.owned[process.pid]) < 0.001:
                    process.kill() if force else process.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(processes, timeout=5)
        if alive and not force:
            self._signal_owned_processes(force=True)
            return
        if alive:
            raise RuntimeError("owned Atlas processes survived identity-checked cleanup")

    def _close_process_handles(self) -> None:
        if self.process is not None:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"Atlas process {self.process.pid} remains after cleanup") from exc
            self.process = None
        if self.log_handle is not None:
            self.log_handle.close()
            self.log_handle = None

    def stop(self) -> None:
        if self.process is None:
            return
        self._capture_owned_processes()
        self._signal_owned_processes(force=False)
        self._close_process_handles()

    def crash(self) -> dict[str, Any]:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("no live owned Atlas process to crash")
        pid = self.process.pid
        created = self.owned.get(pid)
        self._capture_owned_processes()
        self._signal_owned_processes(force=True)
        self._close_process_handles()
        return {"pid": pid, "creation_time": created, "port": self.port, "terminated": True}

    def restart(self) -> dict[str, Any]:
        self.stop()
        self.owned.clear()
        route = self.start()
        return {
            "pid": self.process.pid if self.process else None,
            "port": self.port,
            "creation_time": self.owned.get(self.process.pid) if self.process else None,
            "route": route,
        }

    def read_log(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""


@dataclass
class ScenarioActionContext:
    scenario_id: int
    step: ScenarioStep
    atlas: AtlasEvalClient
    memory: MemoryOSIsolationClient
    lifecycle: AtlasProcessLifecycle
    workspace: Path
    artifact_dir: Path
    subject_id: str
    state: dict[str, Any]
    runtime_capabilities: frozenset[str] = field(default_factory=frozenset)
    workspace_files: tuple[str, ...] = ()


def _apply_step_action(action: str, payload: dict[str, Any], ctx: ScenarioActionContext) -> dict[str, Any]:
    try:
        try:
            from scripts.memory_v1.scenario_actions import apply_step_action
        except ModuleNotFoundError as exc:
            if exc.name != "scripts.memory_v1.scenario_actions":
                raise
            from scenario_actions import apply_step_action  # type: ignore[no-redef]
    except ModuleNotFoundError:
        return {"action": action, "status": "unsupported",
                "detail": "scenario_actions adapter is not present in this checkout"}
    result = apply_step_action(action, payload, ctx)
    if not isinstance(result, dict) or result.get("status") not in {"ok", "failed", "unsupported"}:
        return {"action": action, "status": "failed", "detail": "adapter returned an invalid result"}
    return result


def _audit_reminder_state(ctx: ScenarioActionContext) -> dict[str, Any]:
    try:
        try:
            from scripts.memory_v1.scenario_actions import audit_reminder_state
        except ModuleNotFoundError as exc:
            if exc.name != "scripts.memory_v1.scenario_actions":
                raise
            from scenario_actions import audit_reminder_state  # type: ignore[no-redef]
    except ModuleNotFoundError:
        return {
            "action": "reminder_readonly_audit", "status": "unsupported",
            "detail": "scenario_actions reminder audit is not present in this checkout",
        }
    result = audit_reminder_state(ctx)
    if not isinstance(result, dict) or result.get("status") not in {"ok", "failed", "unsupported"}:
        return {
            "action": "reminder_readonly_audit", "status": "failed",
            "detail": "reminder audit returned an invalid result",
        }
    return result


def _records_delta(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old = {str(item.get("record_ref") or ""): item for item in before if item.get("record_ref")}
    return [item for item in after if item.get("record_ref") and
            (str(item["record_ref"]) not in old or old[str(item["record_ref"])] != item)]


async def run_scenario_step(
    scenario: ScenarioSpec,
    step: ScenarioStep,
    *,
    atlas: AtlasEvalClient,
    memory: MemoryOSIsolationClient,
    lifecycle: AtlasProcessLifecycle,
    workspace: Path,
    artifact_dir: Path,
    subject_id: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    action_info = None
    ctx = ScenarioActionContext(
        scenario.id, step, atlas, memory, lifecycle, workspace, artifact_dir, subject_id, state,
        runtime_capabilities=scenario.runtime_capabilities,
        workspace_files=scenario.workspace_files,
    )
    if step.action:
        action_info = _apply_step_action(step.action, step.action_payload, ctx)
        state["action_results"].append(action_info)
        if action_info.get("status") != "ok":
            state["execution_errors"].append({
                "kind": "action", "turn_index": step.turn_index,
                "action": step.action, "status": action_info.get("status"),
            })
    if is_control_action_step(step):
        return {
            "turn_index": step.turn_index, "session_id": step.session_id,
            "occurred_at": step.occurred_at, "user_input": step.user_input,
            "action": step.action, "action_info": action_info,
            "message_transport": "action_adapter",
            "execution_status": action_info.get("status", "unsupported") if action_info else "failed",
        }

    conversation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"f1-d:{scenario.id}:{step.session_id}"))
    run_id = str(uuid.uuid4())
    message = build_run_start_message(
        scenario, step, run_id=run_id, conversation_id=conversation_id,
        workspace=workspace,
    )
    atlas_data_root = lifecycle.runtime_root / "atlas_data"
    outbox_before = _read_capture_source_events(atlas_data_root, conversation_id)
    before = memory.records()
    result = atlas.chat(message)
    state["last_run"] = result
    try:
        observer_settlement = await _wait_for_observer_settlement(
            atlas_data_root, conversation_id, memory,
        )
        after = memory.records()
    except Exception as exc:  # noqa: BLE001
        observer_settlement = {"status": "failed", "error_type": type(exc).__name__}
        state["execution_errors"].append({
            "kind": "observer_settlement", "turn_index": step.turn_index,
            "status": "failed", "error_type": type(exc).__name__,
        })
        after = before
    assembled_refs = _extract_assembled_refs(lifecycle.read_log(), conversation_id)
    observer_output = _records_delta(before, after)
    outbox_after = _read_capture_source_events(atlas_data_root, conversation_id)
    capture_evidence = _capture_evidence_delta(
        outbox_before, outbox_after, assembled_refs, observer_output,
    )
    if result["status"] != "completed":
        state["execution_errors"].append({
            "kind": "run", "turn_index": step.turn_index,
            "status": result["status"], "terminal_event": result["terminal_event"],
        })
    return {
        "turn_index": step.turn_index, "session_id": step.session_id,
        "occurred_at": step.occurred_at, "occurred_at_used_by_ws": False,
        "user_input": step.user_input, "action": step.action,
        "action_info": action_info, "message_transport": "atlas_ws",
        "execution_status": result["status"],
        "assistant_response": result["assistant_response"],
        "model_used": result["model_used"], "run_id": result["run_id"],
        "conversation_id": conversation_id, "terminal_event": result["terminal_event"],
        "usage": result["usage"], "tool_calls": result["tool_calls"],
        "policy_events": result["policy_events"], "assembled_refs": assembled_refs,
        "observer_output": observer_output, "capture_evidence": capture_evidence,
        "observer_settlement": observer_settlement,
        "events": result["events"],
    }


async def run_scenario(
    scenario: ScenarioSpec,
    *, runtime_root: Path, atlas: AtlasEvalClient, memory: MemoryOSIsolationClient,
    lifecycle: AtlasProcessLifecycle, workspace: Path, subject_id: str,
) -> dict[str, Any]:
    print(f"Running Scenario #{scenario.id:02d} [{scenario.category}] {scenario.title} ...")
    artifact_dir = runtime_root / "evidence"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if scenario.workspace_files:
        workspace_root = workspace.resolve()
        for relative_name in scenario.workspace_files:
            path = (workspace_root / relative_name).resolve()
            path.relative_to(workspace_root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"# {Path(relative_name).name}\n\nFixture document for the declared workspace task.\n",
                encoding="utf-8",
            )
    state: dict[str, Any] = {"action_results": [], "execution_errors": []}
    if "reminder_readonly_audit" in scenario.runtime_capabilities:
        try:
            state["reminder_audit_baseline"] = {
                "atlas_automations": atlas.request("GET", "/api/automations"),
                "memory_intents": memory.records(facet="INTENT"),
            }
        except Exception as exc:  # noqa: BLE001
            state["reminder_audit_baseline"] = {
                "status": "read_failed", "error_type": type(exc).__name__,
            }
        state["reminder_audit_history"] = []
    records = []
    for step_position, step in enumerate(scenario.steps):
        step_record = await run_scenario_step(
            scenario, step, atlas=atlas, memory=memory, lifecycle=lifecycle,
            workspace=workspace, artifact_dir=artifact_dir, subject_id=subject_id,
            state=state,
        )
        if "reminder_readonly_audit" in scenario.runtime_capabilities and not is_control_action_step(step):
            ctx = ScenarioActionContext(
                scenario.id, step, atlas, memory, lifecycle,
                workspace, artifact_dir, subject_id, state,
                runtime_capabilities=scenario.runtime_capabilities,
                workspace_files=scenario.workspace_files,
            )
            audit = _audit_reminder_state(ctx)
            step_record["reminder_audit"] = audit
            state["reminder_audit_history"].append(audit)
            if audit.get("status") != "ok":
                state["execution_errors"].append({
                    "kind": "reminder_audit", "turn_index": step.turn_index,
                    "status": audit.get("status"),
                })
        records.append(step_record)
        if (
            step_record.get("message_transport") == "atlas_ws"
            and step_record.get("observer_settlement", {}).get("status") != "ready"
        ):
            state["execution_errors"].append({
                "kind": "dependent_turns_blocked", "turn_index": step.turn_index,
                "status": "observer_not_settled",
            })
            records.extend({
                "turn_index": pending.turn_index,
                "session_id": pending.session_id,
                "occurred_at": pending.occurred_at,
                "occurred_at_used_by_ws": False,
                "user_input": pending.user_input,
                "action": pending.action,
                "execution_status": "blocked_observer_not_settled",
                "blocking_turn_index": step.turn_index,
            } for pending in scenario.steps[step_position + 1:])
            break
    final_records = memory.records()
    final_capture = _read_capture_source_events(lifecycle.runtime_root / "atlas_data")
    final_capture_events = final_capture.get("events", [])
    return {
        "scenario_id": scenario.id, "category": scenario.category,
        "title": scenario.title, "description": scenario.description,
        "is_counterexample": scenario.is_counterexample,
        "acceptance_criteria": scenario.acceptance_criteria,
        "steps_count": len(scenario.steps),
        "execution_status": "failed" if state["execution_errors"] else "completed",
        "execution_errors": state["execution_errors"], "records": records,
        "final_state": {
            "action_results": state["action_results"],
            "reminder_audit_baseline": state.get("reminder_audit_baseline"),
            "reminder_audit_history": state.get("reminder_audit_history", []),
            "capture_outbox_status": final_capture.get("status"),
            "capture_source_events": final_capture_events,
            "capture_ack_summary": {
                "total": len(final_capture_events),
                "acked": sum(1 for item in final_capture_events if item.get("state") == "ACKED"),
                "not_acked": sum(1 for item in final_capture_events if item.get("state") != "ACKED"),
            },
            "memory_record_count": len(final_records), "memory_records": final_records,
        },
    }


def _plan_scenario(scenario: ScenarioSpec) -> dict[str, Any]:
    return {
        "scenario_id": scenario.id, "category": scenario.category,
        "title": scenario.title, "description": scenario.description,
        "is_counterexample": scenario.is_counterexample,
        "acceptance_criteria": scenario.acceptance_criteria,
        "steps_count": len(scenario.steps), "execution_status": "not_run",
        "records": [{
            "turn_index": step.turn_index, "session_id": step.session_id,
            "occurred_at": step.occurred_at, "user_input": step.user_input,
            "action": step.action, "execution_status": "not_run",
        } for step in scenario.steps],
    }


def _scenario_trial_checkpoint_path(output_path: Path, trial_result: dict[str, Any]) -> Path:
    checkpoint_dir = output_path.parent / f"{output_path.stem}.trials"
    return checkpoint_dir / (
        f"trial-{int(trial_result['trial']):02d}-scenario-"
        f"{int(trial_result['scenario_id']):02d}.json"
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_scenario_trial_checkpoint(output_path: Path, trial_result: dict[str, Any]) -> Path:
    checkpoint_path = _scenario_trial_checkpoint_path(output_path, trial_result)
    if checkpoint_path.is_file():
        existing = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if existing.get("execution_status") != "RUNNING":
            if existing == trial_result:
                return checkpoint_path
            raise FileExistsError(f"terminal scenario trial evidence already exists: {checkpoint_path}")
        if trial_result.get("execution_status") == "RUNNING":
            raise FileExistsError(f"scenario trial is already marked RUNNING: {checkpoint_path}")
        trial_result = {**existing, **trial_result}
    _atomic_write_json(checkpoint_path, trial_result)
    return checkpoint_path


def _write_partial_suite(
    output_path: Path, metadata: dict[str, Any], results: list[dict[str, Any]],
) -> Path:
    partial_path = output_path.with_suffix(".partial.json")
    finished_runs = sum(item.get("execution_status") != "RUNNING" for item in results)
    _atomic_write_json(partial_path, {
        "metadata": metadata,
        "partial": True,
        "finished_runs": finished_runs,
        "total_runs": metadata.get("total_runs"),
        "scenarios": results,
    })
    return partial_path


async def run_evaluation_suite(
    scenarios: list[ScenarioSpec], isolated_dir: Path, output_path: Path,
    dry_run: bool = True, model_name: str | None = None, repetitions: int = 1,
    service_python: Path | None = None, atlas_python: Path | None = None,
    settings_source: Path | None = None, resume: bool = False,
) -> Path:
    """Write a plan by default; real mode starts isolated Atlas and MemoryOS services."""
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    if model_name not in (None, GEMINI_MODEL_ID):
        raise ValueError(f"F1-D runs are pinned to {GEMINI_MODEL_ID}; refusing {model_name!r}")
    output_path = output_path.resolve()
    if not _is_within(output_path, Path(r"D:\Temp")):
        raise RuntimeError("scenario results and plans must be written under D:\\Temp")
    for prod_root in PRODUCTION_ROOTS:
        if _is_within(output_path, prod_root):
            raise RuntimeError(f"result output is inside production root: {prod_root}")
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    if dry_run:
        results = [_plan_scenario(scenario) for scenario in scenarios for _ in range(repetitions)]
        suite_payload = {
            "metadata": {
                "generated_at": created_at, "scenario_count": len(scenarios),
                "total_runs": len(results), "repetitions": repetitions,
                "dry_run": True, "execution_mode": "plan_only",
                "model_configured": GEMINI_MODEL_ID,
            },
            "scenarios": results,
        }
    else:
        isolated_dir = isolated_dir.resolve()
        if not _is_within(isolated_dir, Path(r"D:\Temp")):
            raise RuntimeError("real F1-D runtime roots must be placed under D:\\Temp")
        if not isolated_dir.name.startswith("F1-D-"):
            raise RuntimeError("real F1-D runtime root name must start with F1-D-")
        try:
            from scripts.memory_v1.gemini_runtime import (
                MODEL_ID, PROVIDER_BASE_URL, read_isolated_model_settings,
                write_isolated_user_settings,
            )
        except ModuleNotFoundError:
            from gemini_runtime import (
                MODEL_ID, PROVIDER_BASE_URL, read_isolated_model_settings,
                write_isolated_user_settings,
            )
        if MODEL_ID != GEMINI_MODEL_ID:
            raise RuntimeError("shared Gemini helper model ID differs from F1-D runner")
        source = settings_source or Path(os.environ.get(
            "ATLAS_F1_GEMINI_SETTINGS_SOURCE", r"D:\Atlas\data\user-settings.json",
        ))
        safe_settings = read_isolated_model_settings(source)
        endpoint_host = PROVIDER_BASE_URL.split("//", 1)[-1].split("/", 1)[0]
        checkpoint_dir = output_path.parent / f"{output_path.stem}.trials"
        manifest_path = checkpoint_dir / "run-manifest.json"
        partial_path = output_path.with_suffix(".partial.json")
        run_config = {
            "scenario_manifest_sha256": scenario_manifest_sha256(),
            "scenario_ids": [scenario.id for scenario in scenarios],
            "repetitions": repetitions,
            "model_id": GEMINI_MODEL_ID,
            "endpoint_host": endpoint_host,
            "isolated_dir": str(isolated_dir),
            "safe_settings_sha256": hashlib.sha256(
                json.dumps(safe_settings, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }
        run_config_sha256 = hashlib.sha256(
            json.dumps(run_config, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if resume:
            if not manifest_path.is_file():
                raise FileNotFoundError(f"scenario resume manifest is missing: {manifest_path}")
            saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if saved_manifest.get("config") != run_config or saved_manifest.get("sha256") != run_config_sha256:
                raise RuntimeError("scenario resume config differs from the original isolated attempt")
            if output_path.is_file():
                final_payload = json.loads(output_path.read_text(encoding="utf-8"))
                if final_payload.get("metadata", {}).get("run_config_sha256") != run_config_sha256:
                    raise RuntimeError("existing scenario result does not match the requested resume config")
                return output_path
            created_at = str(saved_manifest.get("generated_at") or created_at)
        else:
            if checkpoint_dir.exists() or output_path.exists() or partial_path.exists():
                raise FileExistsError("scenario attempt artifacts already exist; use --resume or a new attempt path")
            if isolated_dir.exists() and any(isolated_dir.iterdir()):
                raise FileExistsError(f"real F1-D runtime root is not empty: {isolated_dir}")
            isolated_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_dir.mkdir(parents=True, exist_ok=False)
            _atomic_write_json(manifest_path, {
                "config": run_config, "sha256": run_config_sha256,
                "generated_at": created_at,
            })
        atlas_exe = atlas_python or (CORE_DIR / ".venv" / "Scripts" / "python.exe")
        if service_python is None:
            from scripts.memory_v1.real_memory import DEFAULT_SERVICE_PYTHON
            service_exe = DEFAULT_SERVICE_PYTHON
        else:
            service_exe = service_python
        for trial in range(1, repetitions + 1):
            for scenario in scenarios:
                runtime_root = isolated_dir / f"trial-{trial:02d}-scenario-{scenario.id:02d}"
                roots = enforce_isolation(runtime_root)
                subject_id = f"f1d-s{scenario.id:02d}-t{trial:02d}-{uuid.uuid4().hex[:10]}"
                api_token = uuid.uuid4().hex
                env = _runtime_environment(
                    roots, api_token=api_token, subject_id=subject_id, scenario=scenario,
                )
                memory_service = None
                lifecycle = None
                try:
                    try:
                        from scripts.memory_v1.real_memory import RealMemoryService
                    except ModuleNotFoundError:
                        from real_memory import RealMemoryService
                    memory_service = RealMemoryService(
                        Path(roots["MEMORYOS_DATA_ROOT"]), subject_id=subject_id,
                        subject_aliases="atlas-fixture", service_python=service_exe,
                    )
                    with _temporary_environment(env):
                        memory_service.start()
                    settings_path = write_isolated_user_settings(Path(roots["ATLAS_DATA_DIR"]), safe_settings)
                    hermes_config_path = _write_isolated_hermes_config(Path(roots["HERMES_HOME"]))
                    _write_isolated_atlas_config(
                        Path(roots["ATLAS_DATA_DIR"]),
                        f"http://127.0.0.1:{memory_service.port}", subject_id,
                    )
                    env["F1D_PROVIDER_ENDPOINT_HOST"] = endpoint_host
                    lifecycle = AtlasProcessLifecycle(
                        python=Path(atlas_exe), runtime_root=runtime_root, env=env,
                        workspace=Path(roots["WORKSPACE"]), api_token=api_token,
                    )
                    route_metadata = lifecycle.start()
                    atlas_client = lifecycle.client
                    memory_client = MemoryOSIsolationClient(
                        f"http://127.0.0.1:{memory_service.port}", subject_id,
                    )
                    result = await run_scenario(
                        scenario, runtime_root=runtime_root, atlas=atlas_client,
                        memory=memory_client, lifecycle=lifecycle,
                        workspace=Path(roots["WORKSPACE"]), subject_id=subject_id,
                    )
                    result["trial"] = trial
                    result["runtime"] = {
                        "runtime_root": str(runtime_root), "atlas_data_root": roots["ATLAS_DATA_DIR"],
                        "memoryos_data_root": roots["MEMORYOS_DATA_ROOT"],
                        "hermes_home": roots["HERMES_HOME"],
                        "hermes_config_path": str(hermes_config_path),
                        "workspace": roots["WORKSPACE"],
                        "atlas_port": lifecycle.port,
                        "atlas_pid": lifecycle.process.pid if lifecycle.process else None,
                        "memoryos_port": memory_service.port,
                        "memoryos_pid": memory_service.proc.pid if memory_service.proc else None,
                        "subject_id": subject_id, "route": route_metadata,
                        "test_feature_flags": {
                            "hard_erase_enabled": "hard_erase" in scenario.runtime_capabilities,
                        },
                        "settings_path": str(settings_path),
                    }
                    results.append(result)
                except Exception as exc:  # noqa: BLE001
                    results.append({
                        "scenario_id": scenario.id, "category": scenario.category,
                        "title": scenario.title, "is_counterexample": scenario.is_counterexample,
                        "acceptance_criteria": scenario.acceptance_criteria, "trial": trial,
                        "execution_status": "setup_failed",
                        "setup_error": {"type": type(exc).__name__, "message": _redact_error(str(exc))},
                        "records": [], "runtime": {"runtime_root": str(runtime_root), "subject_id": subject_id},
                    })
                finally:
                    if lifecycle is not None:
                        lifecycle.stop()
                    if memory_service is not None:
                        await memory_service.aclose()
                        memory_service.stop()
        suite_payload = {
            "metadata": {
                "generated_at": created_at, "scenario_count": len(scenarios),
                "total_runs": len(results), "repetitions": repetitions,
                "dry_run": False, "execution_mode": "real_atlas_ws_and_isolated_memoryos",
                "isolated_dir": str(isolated_dir), "model_configured": GEMINI_MODEL_ID,
                "provider_id": "custom", "provider_endpoint_host": endpoint_host,
                "credential_value_recorded": False,
                "scenario_manifest_sha256": scenario_manifest_sha256(),
            },
            "scenarios": results,
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(suite_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Completed {len(results)} scenario runs. Results saved to: {output_path}")
    return output_path


def _redact_error(message: str) -> str:
    safe = re.sub(
        r"(?i)(api[_-]?key|authorization|access[_-]?token|secret)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]", message,
    )
    return safe[:1000]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=int, default=None, help="Run specific scenario by ID (1..30)")
    parser.add_argument("--category", type=str, default=None, help="Run scenarios under category (E1..E8)")
    parser.add_argument("--all", action="store_true", help="Select all 30 scenarios")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run-real", action="store_true", help="Start isolated Atlas/MemoryOS and use the real Gemini route")
    mode.add_argument("--dry-run", action="store_true", help="Write a plan only; this is the default")
    parser.add_argument("--isolated-dir", type=Path, default=None, help="Unique runtime root under D:\\Temp")
    parser.add_argument("--output", type=Path, default=None, help="JSON result/plan path")
    parser.add_argument("--model", type=str, default=GEMINI_MODEL_ID, help="F1-D is pinned to gemini-3.8-flash")
    parser.add_argument("--repetitions", type=int, default=1, help="Fresh isolated runtime repetitions per scenario")
    parser.add_argument("--service-python", type=Path, default=None, help="Isolated MemoryOS service interpreter")
    parser.add_argument("--atlas-python", type=Path, default=None, help="Atlas core service interpreter")
    parser.add_argument("--settings-source", type=Path, default=None, help="Read-only source for safe Gemini metadata")
    parser.add_argument("--judge", action="store_true", help="Run eval_judge.py after a real run")
    args = parser.parse_args()
    if args.model != GEMINI_MODEL_ID:
        parser.error(f"--model is fixed to {GEMINI_MODEL_ID}; the original scenario switch remains an action payload")
    if args.judge and not args.run_real:
        parser.error("--judge requires --run-real; plan-only data is not judgeable")
    all_specs = get_all_scenarios()
    targets = all_specs
    if args.scenario is not None:
        targets = [scenario for scenario in all_specs if scenario.id == args.scenario]
        if not targets:
            parser.error(f"unknown scenario id {args.scenario}")
    elif args.category:
        targets = [scenario for scenario in all_specs if scenario.category.upper() == args.category.upper()]
        if not targets:
            parser.error(f"unknown category {args.category}")
    run_root = args.isolated_dir or Path(r"D:\Temp") / (
        f"F1-D-scenarios-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    )
    output_path = args.output or (run_root / ("results.json" if args.run_real else "plan.json"))
    out_file = asyncio.run(run_evaluation_suite(
        scenarios=targets, isolated_dir=run_root, output_path=output_path,
        dry_run=not args.run_real, model_name=args.model, repetitions=args.repetitions,
        service_python=args.service_python, atlas_python=args.atlas_python,
        settings_source=args.settings_source,
    ))
    if args.judge:
        try:
            from scripts.memory_v1.eval_judge import evaluate_results_file
        except ModuleNotFoundError:
            sys.path.insert(0, str(REPO_ROOT))
            from scripts.memory_v1.eval_judge import evaluate_results_file
        report = evaluate_results_file(out_file, output_path=run_root / "judge-report.json")
        print(f"Evaluation Verdict: {report.get('summary', {}).get('verdict')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
