#!/usr/bin/env python3
"""Two-week conversation trace generator for Atlas Memory-V1 (Package F / S8).

Generates a realistic 14-day user interaction trace featuring:
- Repeated mentions across 14 days (e.g., 5 varied expressions of "I'm on a diet" for E5 Scenario 20 MERGE)
- Outdated / expired states (e.g., "want peace this week" with short half-life for E4 Scenario 17)
- Superseding / corrections (e.g., meeting Wed -> Fri for Scenario 16, Windows -> Mac for Scenario 19)
- Homonyms / multiple candidates (e.g., Coworker Lao Wang vs Landlord Lao Wang for E2 Scenario 7, Zhang Zong = Zhang Wei for Scenario 10)
- Core durable facts (e.g., peanut allergy for E3/E6, daughter Xiaoman age 6 for E1/E7)
- Behavioral constraints (e.g., TypeScript only for E1, Markdown tables for E3, isolated test dir for E3)
- Retrievable exact date detail (e.g., Day 10 book purchase for E5 Scenario 22)
- One-off trivial events (e.g., morning latte, keyboard sale for E5 Scenario 23 low-importance decay)

Used by:
- S4 Reflector offline / batch testing (MERGE, SUPERSEDE, ROLLUP_DAY, PROFILE_UPDATE, IMPORTANCE)
- E5 acceptance evaluation and recency/importance ranking validation
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT_PATH = Path(r"D:\Atlas\docs\plan\MEMORY-V1\eval\two_week_trace.json")
DEFAULT_BASE_DATE = "2026-09-24"


def build_two_week_events(base_date_str: str) -> list[dict[str, Any]]:
    """Build day-by-day conversational events spanning 14 days."""
    base_date = datetime.date.fromisoformat(base_date_str)

    def day_ts(day_offset: int, hour: int, minute: int) -> str:
        d = base_date + datetime.timedelta(days=day_offset)
        dt = datetime.datetime(d.year, d.month, d.day, hour, minute, 0)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def day_date(day_offset: int) -> str:
        return (base_date + datetime.timedelta(days=day_offset)).isoformat()

    sessions: list[dict[str, Any]] = [
        # =========================================================================
        # Day 1: Base facts (Location, Work, Allergy, Initial Tech Stack)
        # =========================================================================
        {
            "session_id": "session_day01_morning",
            "day_index": 1,
            "date": day_date(0),
            "topic": "自我介绍与基础事实",
            "test_markers": ["e1_location_work", "e3_peanut_allergy", "e4_pc_windows_initial"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "你好！我刚来杭州余杭这边工作，在做跨境电商相关的业务。",
                    "timestamp": day_ts(0, 9, 30),
                },
                {
                    "speaker": "assistant",
                    "text": "你好！欢迎来到杭州！余杭区是跨境电商和互联网技术聚集地，有什么我可以帮你的？",
                    "timestamp": day_ts(0, 9, 30),
                },
                {
                    "speaker": "user",
                    "text": "点外卖或者推荐餐馆时千万注意，我对花生严重过敏，千万不能碰任何花生制品。",
                    "timestamp": day_ts(0, 9, 32),
                },
                {
                    "speaker": "assistant",
                    "text": "已郑重记下：对花生严重过敏，绝不能食用含花生及花生油的花生制品。",
                    "timestamp": day_ts(0, 9, 32),
                },
                {
                    "speaker": "user",
                    "text": "另外我现在主要用 Windows 笔记本做开发，装了 WSL2。",
                    "timestamp": day_ts(0, 9, 35),
                },
                {
                    "speaker": "assistant",
                    "text": "收到，当前主力开发设备是 Windows + WSL2 环境。",
                    "timestamp": day_ts(0, 9, 35),
                },
            ],
        },
        # =========================================================================
        # Day 2: Family, Coding Constraints, Diet mention #1, Trivial event #1
        # =========================================================================
        {
            "session_id": "session_day02_general",
            "day_index": 2,
            "date": day_date(1),
            "topic": "家庭信息、编码规范、减肥第1次、琐事1",
            "test_markers": ["e1_family_xiaoman", "e1_ts_preference", "e5_diet_mention_1", "e5_trivial_latte"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "我女儿叫小满，今年 6 岁，准备要读小学了，平时挺调皮的。",
                    "timestamp": day_ts(1, 10, 15),
                },
                {
                    "speaker": "assistant",
                    "text": "6 岁的小满正是充满好奇心的年纪，幼小衔接阶段需要多陪伴引导。",
                    "timestamp": day_ts(1, 10, 15),
                },
                {
                    "speaker": "user",
                    "text": "对了我平时写前端和后端脚本，以后代码都用 TypeScript 写，别用 JS。",
                    "timestamp": day_ts(1, 10, 18),
                },
                {
                    "speaker": "assistant",
                    "text": "好的，以后的代码方案默认统一使用 TypeScript，不使用纯 JavaScript。",
                    "timestamp": day_ts(1, 10, 18),
                },
                {
                    "speaker": "user",
                    "text": "今天早上在楼下星巴克买了一杯燕麦拿铁，感觉味道偏淡。",
                    "timestamp": day_ts(1, 10, 22),
                },
                {
                    "speaker": "assistant",
                    "text": "燕麦奶自带谷物甜味，有时确实会觉得咖啡浓缩味稍淡，可以尝试多加一份浓缩。",
                    "timestamp": day_ts(1, 10, 22),
                },
                {
                    "speaker": "user",
                    "text": "最近在减脂，体脂有点高，晚上开始不吃米饭了。",
                    "timestamp": day_ts(1, 20, 0),
                },
                {
                    "speaker": "assistant",
                    "text": "控制晚间精制碳水对减脂确实见效快，注意补充优质蛋白质和绿叶蔬菜。",
                    "timestamp": day_ts(1, 20, 0),
                },
            ],
        },
        # =========================================================================
        # Day 3: Short-term state (want peace), Alias (Zhang Zong = Zhang Wei)
        # =========================================================================
        {
            "session_id": "session_day03_work",
            "day_index": 3,
            "date": day_date(2),
            "topic": "短期疲劳状态、别名关联",
            "test_markers": ["e4_temporary_state_quiet", "e2_alias_zhang_wei"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "这周连续通宵加班太累了，这周我想安静点，少给我推东西和活动。",
                    "timestamp": day_ts(2, 14, 0),
                },
                {
                    "speaker": "assistant",
                    "text": "明白，本周尽量保持安静克制，不主动打扰或推荐额外事项，多休息恢复精力。",
                    "timestamp": day_ts(2, 14, 0),
                },
                {
                    "speaker": "user",
                    "text": "对了，我们商务合作的张总就是张伟，以后提到张伟或者张总都是同一个人。",
                    "timestamp": day_ts(2, 14, 10),
                },
                {
                    "speaker": "assistant",
                    "text": "记下了：业务合作中的张总即张伟，两者是同一实体。",
                    "timestamp": day_ts(2, 14, 10),
                },
            ],
        },
        # =========================================================================
        # Day 4: Homonym #1 (Coworker Lao Wang / Wang Lei), Diet mention #2
        # =========================================================================
        {
            "session_id": "session_day04_colleague",
            "day_index": 4,
            "date": day_date(3),
            "topic": "同事老王聊融资、减肥第2次",
            "test_markers": ["e2_lao_wang_colleague_funding", "e5_diet_mention_2"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "今天下午和同事老王（王磊）在咖啡厅聊了 Atlas 的融资和股权结构，谈得挺深入。",
                    "timestamp": day_ts(3, 16, 30),
                },
                {
                    "speaker": "assistant",
                    "text": "和同事王磊聊 Atlas 融资与股权结构是关键里程碑，需要做好后续纪要跟进。",
                    "timestamp": day_ts(3, 16, 30),
                },
                {
                    "speaker": "user",
                    "text": "今天早上称了一下体重瘦了两斤，减重小有成效，继续少油少盐低卡饮食。",
                    "timestamp": day_ts(3, 21, 15),
                },
                {
                    "speaker": "assistant",
                    "text": "两斤是好的开始！健康减脂坚持少油少盐，循序渐进效果最稳固。",
                    "timestamp": day_ts(3, 21, 15),
                },
            ],
        },
        # =========================================================================
        # Day 5: Meeting initial (Wed), Reporting format (Markdown table)
        # =========================================================================
        {
            "session_id": "session_day05_project_rules",
            "day_index": 5,
            "date": day_date(4),
            "topic": "周会时间初始定在周三、周报表格格式",
            "test_markers": ["e4_meeting_wednesday_initial", "e3_markdown_table_rule"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "我们跨境电商技术小组的周会定在周三下午两点开，不要记错了。",
                    "timestamp": day_ts(4, 11, 0),
                },
                {
                    "speaker": "assistant",
                    "text": "记录完成：技术小组周会定在每周三下午 14:00。",
                    "timestamp": day_ts(4, 11, 0),
                },
                {
                    "speaker": "user",
                    "text": "另外有一个格式习惯：我的报告一律用 Markdown 表格总结，结构更清晰。",
                    "timestamp": day_ts(4, 11, 10),
                },
                {
                    "speaker": "assistant",
                    "text": "收到：生成总结报告时，末尾一律必须使用 Markdown 表格进行归纳呈现。",
                    "timestamp": day_ts(4, 11, 10),
                },
            ],
        },
        # =========================================================================
        # Day 6: Project test constraint (Isolated dir)
        # =========================================================================
        {
            "session_id": "session_day06_atlas_testing",
            "day_index": 6,
            "date": day_date(5),
            "topic": "测试必须用隔离数据目录",
            "test_markers": ["e3_isolated_test_dir_rule"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "在写自动化测试或者脚本时记住：Atlas 项目的测试必须用隔离数据目录，绝不能碰真实数据。",
                    "timestamp": day_ts(5, 15, 20),
                },
                {
                    "speaker": "assistant",
                    "text": "已牢记严苛约束：Atlas 项目测试必须使用隔离临时目录，严禁写入或修改生产生产路径。",
                    "timestamp": day_ts(5, 15, 20),
                },
            ],
        },
        # =========================================================================
        # Day 7: Diet mention #3 (Cheat meal & gym)
        # =========================================================================
        {
            "session_id": "session_day07_fitness",
            "day_index": 7,
            "date": day_date(6),
            "topic": "减肥第3次（聚餐破戒与补救）",
            "test_markers": ["e5_diet_mention_3"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "中午跟同事聚餐火锅有点破戒了，晚上得去健身房慢跑 5 公里，还在减肥呢不能松懈。",
                    "timestamp": day_ts(6, 18, 45),
                },
                {
                    "speaker": "assistant",
                    "text": "偶尔一餐放纵不影响大局，适度慢跑消耗多余糖原就好，注意跑步前后拉伸。",
                    "timestamp": day_ts(6, 18, 45),
                },
            ],
        },
        # =========================================================================
        # Day 8: Meeting changed (SUPERSEDE: Wed -> Fri)
        # =========================================================================
        {
            "session_id": "session_day08_meeting_change",
            "day_index": 8,
            "date": day_date(7),
            "topic": "周会时间变更到周五（覆盖旧时间）",
            "test_markers": ["e4_meeting_change_to_friday_supersede"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "因为周三要跟海外供应商同步进度，周会改到周五了，依然是下午两点。",
                    "timestamp": day_ts(7, 10, 0),
                },
                {
                    "speaker": "assistant",
                    "text": "更新记录：周会已从周三改到周五下午 14:00，原周三安排已作废更新。",
                    "timestamp": day_ts(7, 10, 0),
                },
            ],
        },
        # =========================================================================
        # Day 9: Homonym #2 (Landlord Lao Wang / Wang Jianguo), Device switch (Windows -> Mac)
        # =========================================================================
        {
            "session_id": "session_day09_landlord_and_mac",
            "day_index": 9,
            "date": day_date(8),
            "topic": "房东老王催租、电脑换成 Mac",
            "test_markers": ["e2_lao_wang_landlord_rent", "e4_device_change_mac_supersede"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "今天房东老王（王建国）打电话催我交下季度房租了，电话是 13800138000。",
                    "timestamp": day_ts(8, 11, 30),
                },
                {
                    "speaker": "assistant",
                    "text": "已记录：房东老王（王建国），催缴下季度房租，联系电话 13800138000。",
                    "timestamp": day_ts(8, 11, 30),
                },
                {
                    "speaker": "user",
                    "text": "我以前用 Windows，公司刚配了 M3 MacBook Pro，我现在换 Mac 了，体验真顺畅。",
                    "timestamp": day_ts(8, 15, 0),
                },
                {
                    "speaker": "assistant",
                    "text": "恭喜换新机！主力开发环境已从 Windows 切换为 Apple Silicon (M3) Mac OS。",
                    "timestamp": day_ts(8, 15, 0),
                },
            ],
        },
        # =========================================================================
        # Day 10: Retrievable date detail (DDIA book purchase), Diet mention #4
        # =========================================================================
        {
            "session_id": "session_day10_book_and_diet",
            "day_index": 10,
            "date": day_date(9),
            "topic": "想买的书籍精确细节、减肥第4次",
            "test_markers": ["e5_exact_book_detail", "e5_diet_mention_4"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "今天 10 号下午我和团队聊完分布式，我说我想买一本《Designing Data-Intensive Applications》回来细读。",
                    "timestamp": day_ts(9, 14, 30),
                },
                {
                    "speaker": "assistant",
                    "text": "DDIA 是分布式与数据系统的经典神书，非常值得研读。",
                    "timestamp": day_ts(9, 14, 30),
                },
                {
                    "speaker": "user",
                    "text": "这周控糖很严格，低碳饮食控制热量，体重稳步下降，减脂成果喜人。",
                    "timestamp": day_ts(9, 21, 0),
                },
                {
                    "speaker": "assistant",
                    "text": "科学控糖配合低碳饮食确实能持续稳住体脂，为你坚持的毅力点赞！",
                    "timestamp": day_ts(9, 21, 0),
                },
            ],
        },
        # =========================================================================
        # Day 11: Solution discussion (Atlas distributed storage schema)
        # =========================================================================
        {
            "session_id": "session_day11_solution",
            "day_index": 11,
            "date": day_date(10),
            "topic": "之前定过的方案细节",
            "test_markers": ["e2_solution_defined"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "前几天定的那个 Atlas 分布式存储方案，采用两层分片 + 本地 SQLite 缓存做降级，这个思路很对。",
                    "timestamp": day_ts(10, 16, 0),
                },
                {
                    "speaker": "assistant",
                    "text": "两层分片保证水平扩展，本地 SQLite 提供零依赖降级容灾，整体架构兼具弹性和可用性。",
                    "timestamp": day_ts(10, 16, 0),
                },
            ],
        },
        # =========================================================================
        # Day 12: Trivial event #2 (Idle keyboard sale)
        # =========================================================================
        {
            "session_id": "session_day12_trivial_keyboard",
            "day_index": 12,
            "date": day_date(11),
            "topic": "琐事2：闲鱼卖旧键盘",
            "test_markers": ["e5_trivial_keyboard_sale"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "昨天把书房吃灰好久的那把旧茶轴机械键盘挂闲鱼 150 块卖掉了，腾了点桌面空间。",
                    "timestamp": day_ts(11, 17, 30),
                },
                {
                    "speaker": "assistant",
                    "text": "断舍离既能回血又能让工作台更清爽，给新设备腾出舒适空间。",
                    "timestamp": day_ts(11, 17, 30),
                },
            ],
        },
        # =========================================================================
        # Day 13: Diet mention #5 (Final diet mention in 2-week cycle)
        # =========================================================================
        {
            "session_id": "session_day13_diet_final",
            "day_index": 13,
            "date": day_date(12),
            "topic": "减肥第5次（2周收尾）",
            "test_markers": ["e5_diet_mention_5"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "下个月老同学婚礼要当伴郎，这半个月我一直在严格减肥控制体型，已经减了五斤了！",
                    "timestamp": day_ts(12, 19, 0),
                },
                {
                    "speaker": "assistant",
                    "text": "半个月减五斤成效斐然！伴郎状态一定能非常精神，继续保持目前的健康节奏！",
                    "timestamp": day_ts(12, 19, 0),
                },
            ],
        },
        # =========================================================================
        # Day 14: Verification queries across all test vectors
        # =========================================================================
        {
            "session_id": "session_day14_verification_queries",
            "day_index": 14,
            "date": day_date(13),
            "topic": "第14天综合回顾与跨期问答",
            "test_markers": ["e4_expired_state_query", "e5_trace_complete"],
            "turns": [
                {
                    "speaker": "user",
                    "text": "今天周末了，天气也不错，给我推荐几个杭州适合我的周末活动吧！",
                    "timestamp": day_ts(13, 10, 0),
                },
                {
                    "speaker": "assistant",
                    "text": "杭州周末推荐：1. 西溪湿地绿道骑行；2. 余杭良渚文化村大屋顶看展与咖啡漫步；3. 灵隐青芝坞品茗散步。轻松舒适且适合放松身心。",
                    "timestamp": day_ts(13, 10, 0),
                },
                {
                    "speaker": "user",
                    "text": "对了，我们组的周会是哪天来着？",
                    "timestamp": day_ts(13, 10, 5),
                },
                {
                    "speaker": "assistant",
                    "text": "技术小组现在的周会定在周五下午两点（原先定在周三，后来变更到了周五）。",
                    "timestamp": day_ts(13, 10, 5),
                },
            ],
        },
    ]

    return sessions


def validate_trace(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate that the trace satisfies all S4 and E5 design constraints."""
    total_turns = sum(len(s["turns"]) for s in sessions)
    all_markers: set[str] = set()
    timestamps: list[datetime.datetime] = []

    for s in sessions:
        for m in s.get("test_markers", []):
            all_markers.add(m)
        for t in s.get("turns", []):
            ts = datetime.datetime.fromisoformat(t["timestamp"])
            timestamps.append(ts)

    # Check chronological ordering
    for i in range(1, len(timestamps)):
        if timestamps[i] < timestamps[i - 1]:
            raise ValueError(
                f"Timestamp out of order at turn {i}: {timestamps[i]} < {timestamps[i-1]}"
            )

    # Check required markers
    required_markers = [
        "e5_diet_mention_1",
        "e5_diet_mention_2",
        "e5_diet_mention_3",
        "e5_diet_mention_4",
        "e5_diet_mention_5",
        "e4_temporary_state_quiet",
        "e4_meeting_wednesday_initial",
        "e4_meeting_change_to_friday_supersede",
        "e4_device_change_mac_supersede",
        "e2_lao_wang_colleague_funding",
        "e2_lao_wang_landlord_rent",
        "e2_alias_zhang_wei",
        "e3_peanut_allergy",
        "e5_exact_book_detail",
        "e5_trivial_latte",
        "e5_trivial_keyboard_sale",
    ]

    missing = [rm for rm in required_markers if rm not in all_markers]
    if missing:
        raise ValueError(f"Trace is missing required test markers: {missing}")

    day_span = (timestamps[-1].date() - timestamps[0].date()).days + 1

    return {
        "status": "VALID",
        "total_sessions": len(sessions),
        "total_turns": total_turns,
        "day_span": day_span,
        "first_timestamp": timestamps[0].isoformat(),
        "last_timestamp": timestamps[-1].isoformat(),
        "markers_verified": sorted(list(all_markers)),
    }


def generate_trace_file(
    output_path: Path,
    base_date: str = DEFAULT_BASE_DATE,
) -> Path:
    """Generate and serialize the two-week conversation trace."""
    sessions = build_two_week_events(base_date)
    validation = validate_trace(sessions)

    payload = {
        "metadata": {
            "title": "Two-Week Real Memory Interaction Trace (14 Days)",
            "purpose": "Evaluates S4 Reflector (MERGE, SUPERSEDE, ROLLUP, PROFILE, IMPORTANCE) and E5 / S8 acceptance",
            "base_date": base_date,
            "generated_at": datetime.datetime.now().isoformat(),
            "validation": validation,
        },
        "sessions": sessions,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Generated 2-week trace with {len(sessions)} sessions ({validation['total_turns']} turns) over {validation['day_span']} days.")
    print(f"Saved to: {output_path}")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output path for JSON trace (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--base-date",
        type=str,
        default=DEFAULT_BASE_DATE,
        help=f"Base starting date YYYY-MM-DD (default: {DEFAULT_BASE_DATE})",
    )
    args = parser.parse_args()

    generate_trace_file(output_path=args.output, base_date=args.base_date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
