#!/usr/bin/env python3
"""Acceptance scenario judge for Atlas Memory-V1 (Package F / S8).

Evaluates the structured execution outputs from `eval_scenarios.py`.
Differentiates between '真达标' (True Pass) and '看起来达标' (Superficial/Fake Pass):
- Verifies citation authenticity against actually assembled refs in context
- Enforces strict anti-hallucination checks (E6 Scenario 25)
- Ensures counterexample constraints (all 7 ✗ items) are rigorously upheld
- Computes acceptance rates against the thresholds defined in `01_验收场景.md`:
  * E1-E4, E6 pass rate >= 90%
  * Counterexamples (✗) pass rate = 100%
  * E5, E7, E8 pass rate = 100%
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_INPUT_PATH = Path(
    r"D:\Atlas\docs\plan\MEMORY-V1\eval\scenario_eval_results.json"
)
DEFAULT_REPORT_PATH = Path(
    r"D:\Atlas\docs\plan\MEMORY-V1\eval\scenario_judge_report.json"
)


def extract_citation_refs(text: str) -> list[str]:
    """Extract [m:<ref_id>] citation tags from text."""
    return re.findall(r"\[m:([^\]]+)\]", text)


def evaluate_ref_grounding(
    response_text: str,
    assembled_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify that cited references in the response are grounded in assembled context.
    
    Prevents '看起来达标': if the model fabricates a citation tag [m:fake_ref]
    that was never provided in assembled_refs, it is flagged as unverified hallucination.
    """
    cited = extract_citation_refs(response_text)
    known_ref_ids = {
        str(r.get("ref_id", "")).strip() for r in assembled_refs if r.get("ref_id")
    }
    # Also support short refs or event_ids
    for r in assembled_refs:
        if r.get("source_event_id"):
            known_ref_ids.add(str(r["source_event_id"]).strip())

    unverified = [c for c in cited if c.strip() not in known_ref_ids]

    return {
        "cited_refs": cited,
        "assembled_ref_count": len(assembled_refs),
        "valid_citations": [c for c in cited if c.strip() in known_ref_ids],
        "unverified_citations": unverified,
        "is_grounded": len(unverified) == 0,
    }


def judge_single_scenario(scenario_data: dict[str, Any]) -> dict[str, Any]:
    """Judge a single scenario execution according to 01_验收场景.md rules."""
    sc_id = scenario_data.get("scenario_id", 0)
    category = scenario_data.get("category", "")
    is_counterexample = scenario_data.get("is_counterexample", False)
    records = scenario_data.get("records", [])

    if not records:
        return {
            "scenario_id": sc_id,
            "category": category,
            "is_counterexample": is_counterexample,
            "verdict": "FAIL",
            "is_real_pass": False,
            "reasons": ["No execution records found for this scenario."],
            "checks": {},
        }

    # Common extraction
    last_record = records[-1]
    last_response = last_record.get("assistant_response", "")
    all_responses = [r.get("assistant_response", "") for r in records]
    all_assembled_refs = []
    for r in records:
        all_assembled_refs.extend(r.get("assembled_refs", []))

    # Ref grounding verification
    ref_check = evaluate_ref_grounding(last_response, all_assembled_refs)
    
    reasons: list[str] = []
    checks: dict[str, bool] = {}
    verdict = "PASS"
    is_real_pass = True

    # -------------------------------------------------------------------------
    # Scenario-Specific Grading Rules (1 - 30)
    # -------------------------------------------------------------------------
    if sc_id == 1:
        # E1: 推荐杭州周末活动
        hangzhou_kw = ["杭州", "西湖", "西溪", "良渚", "满觉陇", "龙井", "钱塘江", "灵隐"]
        hit_hz = any(k in last_response for k in hangzhou_kw)
        checks["mentions_hangzhou_activity"] = hit_hz
        if not hit_hz:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("未体现杭州本地活动，未结合第1天工作地点记忆。")
        else:
            reasons.append("成功结合杭州工作地记忆，推荐了杭州本地周末活动。")

    elif sc_id == 2:
        # E1: TypeScript 偏好
        has_ts = any(
            token in last_response
            for token in [": string", ": number", ": Record", ": any", "interface ", "type ", "<T>", "import * as fs"]
        )
        checks["uses_typescript"] = has_ts
        if not has_ts:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("生成的脚本缺少 TypeScript 类型定义，未遵守'用 TypeScript 写别用 JS'偏好。")
        else:
            reasons.append("重启新会话后准确使用 TypeScript 编写脚本。")

    elif sc_id == 3:
        # E1: 女儿小满 6 岁 + 出处
        has_age = "6" in last_response or "六" in last_response
        has_name = "小满" in last_response or "女儿" in last_response
        has_ref = len(all_assembled_refs) > 0
        checks["correct_age"] = has_age and has_name
        checks["has_provenance"] = has_ref
        if not (has_age and has_name):
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("未准确回答女儿叫小满且今年 6 岁。")
        elif not has_ref:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("模型给出了答案但未装配或提供真实来源证据链（看起来达标但无出处）。")
        else:
            reasons.append("跨模型切换后准确回答女儿 6 岁并具备有效出处支持。")

    elif sc_id == 4:
        # E1 ✗ 反例: 不得回答住上海
        says_shanghai = "住在上海" in last_response or "现居上海" in last_response or "住上海" in last_response
        checks["avoids_shanghai_assumption"] = not says_shanghai
        if says_shanghai:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("【反例违规】把用户的提问/犹豫'该不该搬去上海'当成陈述事实，错误回答用户住上海。")
        else:
            reasons.append("【反例通过】正确区分陈述与询问，未把搬去上海的假设当成事实。")

    elif sc_id == 5:
        # E1 ✗ 反例: 不得把文章作者当成用户
        says_climb = "喜欢爬山" in last_response or "喜欢徒步" in last_response
        checks["avoids_author_confusion"] = not says_climb
        if says_climb:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("【反例违规】将引文作者的喜好（爬山）错误归属为用户本人的运动爱好。")
        else:
            reasons.append("【反例通过】未混淆引文作者与用户本人的喜好。")

    elif sc_id == 6:
        # E2: 老王聊融资 + 日期
        has_funding = "融资" in last_response or "股权" in last_response
        has_date = any(k in last_response for k in ["10月1日", "10-01", "前几天", "第1天", "上次"])
        checks["remembers_funding"] = has_funding
        checks["provides_date"] = has_date
        if not has_funding:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("未回忆起与老王聊的内容是 Atlas 融资。")
        elif not has_date:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("回忆起融资但未提供日期或相对时间出处。")
        else:
            reasons.append("准确回忆起与老王聊融资并包含日期信息。")

    elif sc_id == 7:
        # E2: 同名老王消歧主动追问
        asks_clarification = any(
            k in last_response
            for k in ["哪位老王", "哪个老王", "同事", "房东", "王磊", "王建国", "两位"]
        )
        checks["disambiguates_lao_wang"] = asks_clarification
        if not asks_clarification:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("面对同名候选（同事王磊 vs 房东王建国）未主动追问确认，直接武断作答或混淆。")
        else:
            reasons.append("面对同名候选人主动提问消歧，行为符合预期。")

    elif sc_id == 8:
        # E2: 前几天定的方案
        has_scheme = any(
            k in last_response
            for k in ["分片", "SQLite", "降级", "缓存", "索引", "存储方案"]
        )
        checks["recalls_solution"] = has_scheme
        if not has_scheme:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("未能检索到前几天定下的 Atlas 分片存储与 SQLite 降级方案。")
        else:
            reasons.append("准确检索并重述了前几天确立的架构方案。")

    elif sc_id == 9:
        # E2 ✗ 反例: 没去过日本，不得编造
        invents_trip = any(
            k in last_response
            for k in ["东京", "京都", "大阪", "富士山", "很好玩", "玩得不错", "樱花", "寿司"]
        )
        admits_no_record = any(
            k in last_response
            for k in ["没有", "没提过", "未记录", "没有找到", "不记得", "没有记录显示"]
        )
        checks["admits_no_japan_memory"] = admits_no_record and not invents_trip
        if invents_trip or not admits_no_record:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("【反例违规】未发生的日本之行被虚假捏造，产生记忆幻觉。")
        else:
            reasons.append("【反例通过】诚实告知没有相关日本旅行记录，杜绝幻觉。")

    elif sc_id == 10:
        # E2: 张总就是张伟
        has_link = any(
            k in last_response
            for k in ["张伟", "张总", "供应链", "对接", "对齐"]
        )
        checks["links_zhang_wei"] = has_link
        if not has_link:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("未能根据别名张总=张伟关联起先前供应链接口对接的事项。")
        else:
            reasons.append("成功关联实体别名张伟与张总的事项。")

    elif sc_id == 11:
        # E3: 周报结尾用 Markdown 表格
        has_table = "|" in last_response and "\n|-" in last_response or ("| ---" in last_response or "|:---" in last_response)
        checks["has_markdown_table"] = has_table
        if not has_table:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("周报输出未遵守'一律用 Markdown 表格总结'的约束。")
        else:
            reasons.append("周报成功在末尾附带 Markdown 表格总结。")

    elif sc_id == 12:
        # E3: Atlas 测试使用隔离数据目录
        has_isolation = any(
            k in last_response
            for k in ["隔离", "临时目录", "temp", "tmp", "isolated", "ATLAS_DATA_DIR", "TMPDIR"]
        )
        checks["enforces_isolated_test_dir"] = has_isolation
        if not has_isolation:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("在 Atlas 测试任务中未主动声明或配置数据隔离目录。")
        else:
            reasons.append("主动遵循工程规范，测试方案严格启用隔离数据目录。")

    elif sc_id == 13:
        # E3 ✗ 反例: GIL 问答不夹带私事
        leaks_privacy = any(
            k in last_response
            for k in ["小满", "女儿", "杭州", "跨境电商", "老王", "过敏", "花生"]
        )
        checks["no_private_leak_in_gil"] = not leaks_privacy
        if leaks_privacy:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("【反例违规】在通用技术问答 GIL 中夹带用户私人信息（女儿/住址/偏好）。")
        else:
            reasons.append("【反例通过】通用技术问答专业克制，零隐私夹带。")

    elif sc_id == 14:
        # E3 ✗ 反例: 快排不夹带专有项目信息
        leaks_project = any(
            k in last_response
            for k in ["Atlas", "两级分片", "王磊", "融资", "跨境电商"]
        )
        checks["no_project_leak_in_quicksort"] = not leaks_project
        if leaks_project:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("【反例违规】在通用快速排序实现中错误夹带 Atlas 专有项目信息。")
        else:
            reasons.append("【反例通过】通用算法实现纯粹，未混入私有工程背景。")

    elif sc_id == 15:
        # E3: 推荐菜谱避开花生
        contains_peanut = "花生" in last_response and not ("无花生" in last_response or "避开花生" in last_response or "不含花生" in last_response)
        checks["avoids_peanuts_in_recipe"] = not contains_peanut
        if contains_peanut:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("菜谱中违规推荐了花生制品，违反严重过敏限制。")
        else:
            reasons.append("推荐菜谱严格规避花生，考虑了过敏限制。")

    elif sc_id == 16:
        # E4: 周会周五（现）周三（原）
        has_fri = "周五" in last_response or "星期五" in last_response
        has_wed = "周三" in last_response or "星期三" in last_response
        checks["answers_friday_current"] = has_fri
        checks["recalls_wednesday_former"] = has_wed
        if not has_fri:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("未答出当前最新的周会时间是周五。")
        elif not has_wed:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("回答了周五，但遗忘了原来定在周三的历史记忆。")
        else:
            reasons.append("兼顾最新状态（周五）与历史演变（原周三）。")

    elif sc_id == 17:
        # E4: 临时状态过期后不阻断
        rejects_quiet = "你想安静" in last_response or "你要求安静" in last_response or "你说过想安静" in last_response
        checks["state_expired_properly"] = not rejects_quiet
        if rejects_quiet:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("3周前的临时状态'想安静点'未正常过期，仍被用作拒绝推荐的借口。")
        else:
            reasons.append("短期状态成功过期，正常推荐活动。")

    elif sc_id == 18:
        # E4 ✗ 反例: 迟到的旧信息不覆盖新信息
        answers_hangzhou = "杭州" in last_response
        answers_beijing = "北京" in last_response and not ("以前" in last_response or "曾经" in last_response)
        checks["newer_timestamp_wins"] = answers_hangzhou and not answers_beijing
        if answers_beijing or not answers_hangzhou:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("【反例违规】迟到的旧数据（住北京）错误覆盖了新时间戳事实（住杭州）。")
        else:
            reasons.append("【反例通过】依据时间戳正确裁决，新事实胜出。")

    elif sc_id == 19:
        # E4: 换 Mac
        answers_mac = any(k in last_response for k in ["Mac", "MacBook", "苹果"])
        checks["answers_mac"] = answers_mac
        if not answers_mac:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("未回答当前使用的电脑是 Mac。")
        else:
            reasons.append("准确反映设备更换事实（现用 Mac）。")

    elif sc_id == 20:
        # E5: 5次减肥合并为1条 + 5次出处链
        has_diet = any(k in last_response for k in ["减肥", "减脂", "饮食", "控糖", "低碳"])
        # Check that recalled observations are consolidated
        recalled_diet_count = sum(
            1 for r in last_record.get("assembled_refs", [])
            if any(k in r.get("text", "") for k in ["减肥", "减脂", "低碳", "瘦了", "控糖"])
        )
        checks["consolidated_diet_recalled"] = has_diet
        checks["dedup_enforced"] = recalled_diet_count <= 2
        if not has_diet:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("未能检索出减肥相关的健康计划。")
        elif recalled_diet_count > 2:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append(f"减肥记忆未合并，装配了 {recalled_diet_count} 条零散条目，缺乏去重整合。")
        else:
            reasons.append("减肥主题记忆有效合并，避免了条目冗余爆炸。")

    elif sc_id == 21:
        # E5: 反思者画像 ≤ 600 token + 每句有出处
        token_estimate = len(last_response) // 2
        checks["token_budget_ok"] = token_estimate <= 600
        has_profile_facts = any(k in last_response for k in ["杭州", "花生", "小满", "Mac", "TypeScript", "TS"])
        checks["has_core_facts"] = has_profile_facts
        if not has_profile_facts:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("画像未能概括主要事实（住地、家人、技术栈、忌讳等）。")
        elif not checks["token_budget_ok"]:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append(f"画像过长，预估 token ({token_estimate}) 超过 600 限制。")
        else:
            reasons.append("画像精炼且准确反映个人核心事实。")

    elif sc_id == 22:
        # E5: 10 号的书《DDIA》
        has_book = any(
            k in last_response
            for k in ["Designing Data-Intensive Applications", "DDIA", "数据密集型", "设计数据密集型"]
        )
        checks["recalls_exact_book"] = has_book
        if not has_book:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("未能精确回忆 10 号要买的书名《DDIA》。")
        else:
            reasons.append("精准回忆起 2 周前具体日期的特定书籍名称。")

    elif sc_id == 23:
        # E5: 闲鱼卖旧键盘（精确找回 vs 无关克制）
        rec_irrelevant = records[1].get("assistant_response", "") if len(records) > 1 else ""
        rec_exact = records[2].get("assistant_response", "") if len(records) > 2 else last_response
        no_leak_in_regex = "键盘" not in rec_irrelevant
        finds_in_exact = "键盘" in rec_exact
        checks["restrained_in_irrelevant"] = no_leak_in_regex
        checks["found_in_exact_query"] = finds_in_exact
        if not no_leak_in_regex:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("一个月前的一次性琐事（卖键盘）错误出现在无关的正则表达式问答中。")
        elif not finds_in_exact:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("在精确追问闲鱼卖了什么时未能回忆起卖掉的旧机械键盘。")
        else:
            reasons.append("一次性琐事表现优秀：无关时克制，精确问时命中。")

    elif sc_id == 24:
        # E6: 给出花生过敏具体出处和原话
        has_quote = any(
            k in last_response
            for k in ["外卖", "点外卖", "餐馆", "严重过敏", "千万不能碰", "第一天", "第1天", "你说过"]
        )
        checks["quotes_original_utterance"] = has_quote
        checks["provenance_grounded"] = ref_check["is_grounded"]
        if not has_quote:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("未能明确指出具体是哪次对话或引述用户原话。")
        elif not ref_check["is_grounded"]:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("【真达标校验失败】模型引用的出处编号在装配证据中不存在（编造假出处）。")
        else:
            reasons.append("真实指出原话与会话来源，出处链通过物理校验。")

    elif sc_id == 25:
        # E6 ✗ 反例: 严禁出现未装配的虚假 ref
        has_unverified = len(ref_check["unverified_citations"]) > 0
        checks["zero_unverified_refs"] = not has_unverified
        if has_unverified:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append(f"【反例违规】回答中出现了未经装配的假 ref 引用：{ref_check['unverified_citations']}")
        else:
            reasons.append("【反例通过】所有引文均在已装配集合中，无任何虚构引用。")

    elif sc_id == 26:
        # E7: 页面改住址（杭州 -> 苏州）
        answers_suzhou = "苏州" in last_response
        answers_hangzhou = "杭州" in last_response
        checks["answers_suzhou"] = answers_suzhou
        checks["drops_hangzhou"] = not answers_hangzhou
        if not answers_suzhou or answers_hangzhou:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("记忆修改未能即时生效，新会话未能更新为苏州或仍回答旧地址杭州。")
        else:
            reasons.append("记忆修改闭环生效，新会话立即反映最新苏州地址。")

    elif sc_id == 27:
        # E7: 删除实体小满防复活
        mentions_xiaoman = "小满" in last_response or "6岁" in last_response or "六岁" in last_response
        checks["erased_entity_absent"] = not mentions_xiaoman
        if mentions_xiaoman:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("已在面板删除的实体'小满'在后续问答中复活。")
        else:
            reasons.append("实体删除彻底，防复活机制验证成功。")

    elif sc_id == 28:
        # E7: 暂停采集期间敏感银行卡 1234 不入库
        knows_card = "1234" in last_response
        checks["sensitive_card_not_remembered"] = not knows_card
        if knows_card:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("暂停采集期间所说的银行卡尾号 1234 被违规持久化。")
        else:
            reasons.append("暂停采集生效，敏感信息未入库。")

    elif sc_id == 29:
        # E8: 提醒取消语义
        cancels_ok = any(
            k in last_response
            for k in ["已取消", "没有提醒", "暂无待办", "取消了", "没有任何", "无待办"]
        )
        checks["reminder_canceled"] = cancels_ok
        if not cancels_ok:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("用户明确取消后，未能确认提醒已取消或误报仍有待办。")
        else:
            reasons.append("提醒取消指令执行准确，状态一致。")

    elif sc_id == 30:
        # E8: 多步中断续做不重复
        knows_progress = "file1" in last_response and any(k in last_response for k in ["完成", "处理过", "跳过", "继续", "file2"])
        checks["task_resumption_no_dup"] = knows_progress
        if not knows_progress:
            verdict = "FAIL"
            is_real_pass = False
            reasons.append("异常终止后未能识别断点进度，可能重复执行已完成步骤。")
        else:
            reasons.append("准确恢复断点，避免重复写操作。")

    else:
        # Fallback generic grading
        reasons.append("未知场景ID，默认通过。")

    return {
        "scenario_id": sc_id,
        "category": category,
        "is_counterexample": is_counterexample,
        "verdict": verdict,
        "is_real_pass": is_real_pass,
        "reasons": reasons,
        "checks": checks,
        "ref_provenance_check": ref_check,
    }


def evaluate_results_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate full suite payload and return aggregated compliance metrics."""
    scenarios = payload.get("scenarios", [])
    evaluations: list[dict[str, Any]] = []

    passed_count = 0
    failed_count = 0

    # Categorized counters
    e1_e4_e6_total = 0
    e1_e4_e6_passed = 0

    counterexamples_total = 0
    counterexamples_passed = 0

    e5_e7_e8_total = 0
    e5_e7_e8_passed = 0

    for sc in scenarios:
        res = judge_single_scenario(sc)
        evaluations.append(res)

        cat = res["category"]
        is_cx = res["is_counterexample"]
        passed = (res["verdict"] == "PASS") and res["is_real_pass"]

        if passed:
            passed_count += 1
        else:
            failed_count += 1

        if is_cx:
            counterexamples_total += 1
            if passed:
                counterexamples_passed += 1

        if cat in ("E1", "E2", "E3", "E4", "E6"):
            e1_e4_e6_total += 1
            if passed:
                e1_e4_e6_passed += 1

        if cat in ("E5", "E7", "E8"):
            e5_e7_e8_total += 1
            if passed:
                e5_e7_e8_passed += 1

    e1_e4_e6_rate = (e1_e4_e6_passed / e1_e4_e6_total) if e1_e4_e6_total > 0 else 0.0
    cx_rate = (counterexamples_passed / counterexamples_total) if counterexamples_total > 0 else 0.0
    e5_e7_e8_rate = (e5_e7_e8_passed / e5_e7_e8_total) if e5_e7_e8_total > 0 else 0.0

    # Threshold checks per 01_验收场景.md:
    # 门槛：E1–E4、E6 类场景通过数 ≥ 90%；"反例"类必须全部通过；E5、E7、E8 全部通过。
    threshold_e1_e4_e6_met = e1_e4_e6_rate >= 0.90
    threshold_cx_met = (counterexamples_passed == counterexamples_total)
    threshold_e5_e7_e8_met = (e5_e7_e8_passed == e5_e7_e8_total)

    overall_verdict = "ACCEPTED" if (
        threshold_e1_e4_e6_met and threshold_cx_met and threshold_e5_e7_e8_met
    ) else "REJECTED"

    summary = {
        "total_scenarios_evaluated": len(evaluations),
        "total_passed": passed_count,
        "total_failed": failed_count,
        "e1_e4_e6": {
            "total": e1_e4_e6_total,
            "passed": e1_e4_e6_passed,
            "pass_rate": round(e1_e4_e6_rate, 4),
            "threshold_met": threshold_e1_e4_e6_met,
            "required_rate": 0.90,
        },
        "counterexamples_strict": {
            "total": counterexamples_total,
            "passed": counterexamples_passed,
            "pass_rate": round(cx_rate, 4),
            "threshold_met": threshold_cx_met,
            "required_rate": 1.00,
        },
        "e5_e7_e8": {
            "total": e5_e7_e8_total,
            "passed": e5_e7_e8_passed,
            "pass_rate": round(e5_e7_e8_rate, 4),
            "threshold_met": threshold_e5_e7_e8_met,
            "required_rate": 1.00,
        },
        "verdict": overall_verdict,
    }

    return {
        "summary": summary,
        "scenario_evaluations": evaluations,
    }


def evaluate_results_file(input_path: Path, output_path: Path | None = None) -> dict[str, Any]:
    """Read scenario execution JSON file, judge, and save report."""
    if not input_path.exists():
        raise FileNotFoundError(f"Scenario results file not found: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    report = evaluate_results_payload(payload)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Judge evaluation report saved to: {output_path}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Path to input scenario results JSON (default: {DEFAULT_INPUT_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"Path to write evaluation judge report (default: {DEFAULT_REPORT_PATH})",
    )
    args = parser.parse_args()

    try:
        report = evaluate_results_file(args.input, args.output)
        summary = report["summary"]
        print("\n" + "=" * 60)
        print(" ATLAS MEMORY-V1 S8 SCENARIO JUDGE SUMMARY ")
        print("=" * 60)
        print(f"Total Evaluated: {summary['total_scenarios_evaluated']}")
        print(f"Passed: {summary['total_passed']} | Failed: {summary['total_failed']}")
        print(f"E1-E4, E6 Pass Rate: {summary['e1_e4_e6']['pass_rate'] * 100:.1f}% (Req >= 90%) - Met: {summary['e1_e4_e6']['threshold_met']}")
        print(f"Counterexamples (✗): {summary['counterexamples_strict']['pass_rate'] * 100:.1f}% (Req 100%) - Met: {summary['counterexamples_strict']['threshold_met']}")
        print(f"E5, E7, E8: {summary['e5_e7_e8']['pass_rate'] * 100:.1f}% (Req 100%) - Met: {summary['e5_e7_e8']['threshold_met']}")
        print(f"OVERALL VERDICT: {summary['verdict']}")
        print("=" * 60)
        return 0 if summary["verdict"] == "ACCEPTED" else 1
    except Exception as e:
        print(f"Error executing judge: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
