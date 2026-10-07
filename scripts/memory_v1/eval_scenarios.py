#!/usr/bin/env python3
"""Acceptance scenario runner for Atlas Memory-V1 (Package F / S8).

Runs all 30 acceptance scenarios defined in `01_验收场景.md`.
Enforces strict isolation from production data roots (D:\\Atlas\\data, D:\\MemoryOSData).
Saves structured execution results including:
- Natural Chinese user input
- Simulated / occurred_at timestamps
- Observer outputs (formed observations)
- Assembled context refs (provenance tokens)
- Model responses
- Scenario action traces (model switches, erasures, edits, pause capture)

Output JSON can be evaluated directly by `eval_judge.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Ensure Atlas core is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = REPO_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

# Production roots that must NEVER be touched during evaluation
PRODUCTION_ROOTS = (
    Path(r"D:\Atlas\data"),
    Path(r"D:\MemoryOSData"),
    Path(os.environ.get("LOCALAPPDATA", r"C:\Users\25011\AppData\Local")) / "hermes",
)

DEFAULT_RESULTS_PATH = Path(
    r"D:\Atlas\docs\plan\MEMORY-V1\eval\scenario_eval_results.json"
)


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
        ),
    ]


# =============================================================================
# Execution Engine with Strict Root Isolation
# =============================================================================

def enforce_isolation(isolated_dir: Path) -> dict[str, str]:
    """Ensure environment paths do not collide with production roots."""
    for prod_root in PRODUCTION_ROOTS:
        try:
            if isolated_dir.resolve().is_relative_to(prod_root.resolve()):
                raise RuntimeError(
                    f"Refusing to run: isolated_dir {isolated_dir} is inside production root {prod_root}"
                )
        except (AttributeError, ValueError):
            pass

    isolated_dir.mkdir(parents=True, exist_ok=True)
    atlas_data = isolated_dir / "atlas_data"
    memoryos_data = isolated_dir / "memoryos_data"
    hermes_home = isolated_dir / "hermes_home"

    for d in (atlas_data, memoryos_data, hermes_home):
        d.mkdir(parents=True, exist_ok=True)

    env_overrides = {
        "ATLAS_DATA_DIR": str(atlas_data),
        "MEMORYOS_DATA_ROOT": str(memoryos_data),
        "MEMORYOS_DB_PATH": str(memoryos_data / "unified_memory.db"),
        "HERMES_HOME": str(hermes_home),
        "ATLAS_TEST_MODE": "1",
    }
    os.environ.update(env_overrides)
    return env_overrides


async def run_scenario_step(
    scenario: ScenarioSpec,
    step: ScenarioStep,
    state: dict[str, Any],
    dry_run: bool = False,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Execute a single step of a scenario."""
    action_info: dict[str, Any] = {}
    
    # Handle state mutations before step execution
    if step.action == "pause_capture":
        state["capture_paused"] = True
        action_info = {"action": "pause_capture", "status": "ok"}
    elif step.action == "resume_capture":
        state["capture_paused"] = False
        action_info = {"action": "resume_capture", "status": "ok"}
    elif step.action == "switch_model":
        state["current_model"] = step.action_payload.get("model", "gpt-4o")
        action_info = {"action": "switch_model", "target": state["current_model"]}
    elif step.action == "edit_memory":
        state["edits"].append(step.action_payload)
        action_info = {"action": "edit_memory", "payload": step.action_payload}
    elif step.action == "delete_memory":
        state["deletions"].append(step.action_payload)
        action_info = {"action": "delete_memory", "payload": step.action_payload}
    elif step.action == "kill_process":
        state["interrupted_state"] = step.action_payload
        action_info = {"action": "kill_process", "saved_state": step.action_payload}

    if dry_run:
        # Return structured dry-run simulation payload
        return {
            "turn_index": step.turn_index,
            "session_id": step.session_id,
            "occurred_at": step.occurred_at,
            "user_input": step.user_input,
            "action": step.action,
            "action_info": action_info,
            "observer_output": [
                {
                    "text": f"Observed facts for {step.user_input[:20]}...",
                    "priority": "HIGH" if "过敏" in step.user_input else "MEDIUM",
                    "occurred_at": step.occurred_at,
                    "event_id": f"evt_{scenario.id}_{step.turn_index}",
                }
            ] if not state.get("capture_paused") else [],
            "assembled_refs": [
                {
                    "ref_id": f"ref_{scenario.id}_{step.turn_index}",
                    "text": step.user_input,
                    "source_event_id": f"evt_{scenario.id}_{step.turn_index}",
                    "occurred_at": step.occurred_at,
                }
            ],
            "assistant_response": f"[DRY-RUN RESPONSE to '{step.user_input}']",
            "model_used": state.get("current_model", model_name or "claude-sonnet-4"),
            "dry_run": True,
        }

    # Live execution with real models and isolated pipeline
    # We dynamically load ModelManager and MemoryObserver
    from atlas.models import ModelManager
    from atlas.memory.observer import MemoryObserver

    mm = ModelManager()
    active_model = state.get("current_model") or model_name or mm.get_default_model().get("id", "claude-sonnet-4")
    
    # 1. Memory Observer processing (if capture not paused)
    formed_observations: list[dict[str, Any]] = []
    if not state.get("capture_paused") and not step.user_input.startswith("[系统模拟操作"):
        obs = MemoryObserver(model_manager=mm)
        try:
            # Run observer extraction
            extracted = await obs.extract_observations([{"role": "user", "content": step.user_input}])
            for o in extracted:
                formed_observations.append({
                    "text": getattr(o, "text", str(o)),
                    "priority": getattr(o, "priority", "MEDIUM"),
                    "occurred_at": step.occurred_at,
                    "event_id": f"obs_{scenario.id}_{step.turn_index}",
                })
        except Exception as e:
            formed_observations.append({"text": f"observer_error: {e}", "priority": "LOW"})

    # 2. Context assembly simulation / recall
    # Assemble relevant context from prior turns in this scenario state
    assembled_refs: list[dict[str, Any]] = []
    recalled_context_texts: list[str] = []
    
    for prev_obs in state.get("history_observations", []):
        # Exclude deleted entities
        text = prev_obs.get("text", "")
        if any(d.get("entity") in text for d in state.get("deletions", [])):
            continue
        ref_id = prev_obs.get("event_id", f"ref_{len(assembled_refs)}")
        assembled_refs.append({
            "ref_id": ref_id,
            "text": text,
            "occurred_at": prev_obs.get("occurred_at"),
        })
        recalled_context_texts.append(f"[m:{ref_id}] {text}")

    # Record current observations into scenario history
    state.setdefault("history_observations", []).extend(formed_observations)

    # 3. Model generation via ModelManager
    messages = [
        {"role": "system", "content": "你是 Atlas 个人智能助理。"},
    ]
    if recalled_context_texts:
        messages.append({
            "role": "system",
            "content": "【用户记忆与事实】\n" + "\n".join(recalled_context_texts),
        })
    messages.append({"role": "user", "content": step.user_input})

    resp = await mm.chat(model=active_model, messages=messages, temperature=0.2)
    response_text = resp.get("content", "") if isinstance(resp, dict) else str(resp)

    return {
        "turn_index": step.turn_index,
        "session_id": step.session_id,
        "occurred_at": step.occurred_at,
        "user_input": step.user_input,
        "action": step.action,
        "action_info": action_info,
        "observer_output": formed_observations,
        "assembled_refs": assembled_refs,
        "assistant_response": response_text,
        "model_used": active_model,
        "dry_run": False,
    }


async def run_scenario(
    scenario: ScenarioSpec,
    isolated_dir: Path,
    dry_run: bool = False,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Execute all steps of a single scenario."""
    print(f"Running Scenario #{scenario.id:02d} [{scenario.category}] {scenario.title} ...")
    state: dict[str, Any] = {
        "capture_paused": False,
        "current_model": model_name,
        "edits": [],
        "deletions": [],
        "interrupted_state": None,
        "history_observations": [],
    }

    step_records: list[dict[str, Any]] = []
    for step in scenario.steps:
        rec = await run_scenario_step(
            scenario=scenario,
            step=step,
            state=state,
            dry_run=dry_run,
            model_name=model_name,
        )
        step_records.append(rec)

    return {
        "scenario_id": scenario.id,
        "category": scenario.category,
        "title": scenario.title,
        "description": scenario.description,
        "is_counterexample": scenario.is_counterexample,
        "acceptance_criteria": scenario.acceptance_criteria,
        "steps_count": len(scenario.steps),
        "records": step_records,
        "final_state": {
            "edits": state["edits"],
            "deletions": state["deletions"],
            "capture_paused": state["capture_paused"],
        },
    }


async def run_evaluation_suite(
    scenarios: list[ScenarioSpec],
    isolated_dir: Path,
    output_path: Path,
    dry_run: bool = False,
    model_name: str | None = None,
) -> Path:
    """Run specified scenarios and save execution results."""
    enforce_isolation(isolated_dir)
    results: list[dict[str, Any]] = []

    for sc in scenarios:
        res = await run_scenario(
            scenario=sc,
            isolated_dir=isolated_dir,
            dry_run=dry_run,
            model_name=model_name,
        )
        results.append(res)

    suite_payload = {
        "metadata": {
            "generated_at": datetime.datetime.now().isoformat(),
            "total_scenarios": len(results),
            "dry_run": dry_run,
            "isolated_dir": str(isolated_dir),
            "model_configured": model_name or "default",
        },
        "scenarios": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(suite_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nCompleted {len(results)} scenarios. Results saved to: {output_path}")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        type=int,
        default=None,
        help="Run specific scenario by ID (1..30)",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Run scenarios under category (E1..E8)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all 30 scenarios",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without invoking external LLM APIs",
    )
    parser.add_argument(
        "--isolated-dir",
        type=Path,
        default=None,
        help="Directory for isolated test data (default: tempdir)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESULTS_PATH,
        help=f"Output path for results JSON (default: {DEFAULT_RESULTS_PATH})",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model ID to evaluate against (e.g. claude-sonnet-4, gpt-4o)",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Automatically run eval_judge.py on the output",
    )

    args = parser.parse_args()

    all_specs = get_all_scenarios()
    targets = all_specs
    if args.scenario:
        targets = [s for s in all_specs if s.id == args.scenario]
        if not targets:
            print(f"Error: Unknown scenario id {args.scenario}")
            return 1
    elif args.category:
        targets = [s for s in all_specs if s.category.upper() == args.category.upper()]
        if not targets:
            print(f"Error: Unknown category {args.category}")
            return 1

    default_isolated = Path(r"D:\tmp\atlas_eval_isolated")
    isolated_dir = args.isolated_dir or default_isolated
    
    out_file = asyncio.run(
        run_evaluation_suite(
            scenarios=targets,
            isolated_dir=isolated_dir,
            output_path=args.output,
            dry_run=args.dry_run,
            model_name=args.model,
        )
    )

    if args.judge:
        try:
            from scripts.memory_v1.eval_judge import evaluate_results_file, DEFAULT_REPORT_PATH
        except ModuleNotFoundError:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
            from scripts.memory_v1.eval_judge import evaluate_results_file, DEFAULT_REPORT_PATH
        report = evaluate_results_file(out_file, output_path=DEFAULT_REPORT_PATH)
        print(f"Evaluation Verdict: {report.get('summary', {}).get('verdict')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
