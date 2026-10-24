"""Ultraplan research, structured plan persistence, and reviewed execution."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid
from typing import Any

_JOBS: dict[str, dict[str, Any]] = {}


def validate_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("plan must be a JSON object")
    if not isinstance(value.get("goal"), str) or not value["goal"].strip():
        raise ValueError("goal must be non-empty text")
    if not isinstance(value.get("background"), str):
        raise ValueError("background must be text")
    steps = value.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty array")
    identifiers: set[str] = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"steps[{index}] must be an object")
        for field in ("id", "title", "detail", "verify"):
            if not isinstance(step.get(field), str) or not step[field].strip():
                raise ValueError(f"steps[{index}].{field} must be non-empty text")
        if not isinstance(step.get("files"), list) or any(not isinstance(path, str) for path in step["files"]):
            raise ValueError(f"steps[{index}].files must be an array of strings")
        if step["id"] in identifiers:
            raise ValueError(f"steps[{index}].id must be unique")
        identifiers.add(step["id"])
        step.setdefault("annotation", "")
        step.setdefault("status", "pending")
    for field in ("risks", "open_questions"):
        if not isinstance(value.get(field), list) or any(not isinstance(item, str) for item in value[field]):
            raise ValueError(f"{field} must be an array of strings")
    return value


def render_markdown(plan: dict[str, Any]) -> str:
    rows = [f"# {plan['goal']}", "", "## 背景", "", plan["background"], "", "## 步骤", ""]
    for index, step in enumerate(plan["steps"], 1):
        rows += [f"### {index}. {step['title']}", "", step["detail"], "",
                 f"- 文件：{', '.join(step['files']) or '待确认'}",
                 f"- 验证：{step['verify']}"]
        if step.get("annotation"):
            rows.append(f"- 批注：{step['annotation']}")
        rows.append("")
    rows += ["## 风险", ""] + ([f"- {item}" for item in plan["risks"]] or ["- 无"])
    rows += ["", "## 待确认问题", ""] + ([f"- {item}" for item in plan["open_questions"]] or ["- 无"])
    return "\n".join(rows).rstrip() + "\n"


async def _complete_resilient(orchestrator: Any, model: str, messages: list[dict[str, Any]], *, max_tokens: int) -> Any:
    """The plan synthesis call is the one step whose failure throws away all research.

    Retry transient upstream errors (e.g. relay 503) with backoff and then walk the user's
    fallback chain, instead of failing the whole ultraplan on one bad response.
    """
    from atlas.config import load_user_settings

    chain = [str(item) for item in (load_user_settings().get("fallback_chain") or []) if item]
    candidates = [item for index, item in enumerate([model, *chain]) if item and item not in [model, *chain][:index]]
    last_error: Exception | None = None
    for candidate in candidates:
        for attempt, delay in enumerate((0, 3, 8)):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await orchestrator._model_router.complete_for(candidate, "planning", messages, max_tokens=max_tokens)
            except Exception as exc:  # noqa: BLE001 - provider errors vary by transport
                last_error = exc
    assert last_error is not None
    raise last_error


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    for marker in (" for url ", " For more information"):
        text = text.split(marker)[0]
    if "503" in text or "502" in text or "504" in text:
        return f"模型服务暂时不可用（{text.strip()}），已重试并尝试备用模型仍失败；调研结果已保留，可稍后点“重新生成计划”。"
    if "429" in text:
        return f"模型服务限流（{text.strip()}），已重试仍失败；调研结果已保留，可稍后重新生成计划。"
    return f"{type(exc).__name__}: {text.strip()}"


def _parse_plan(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    return validate_plan(json.loads(raw))


async def start(orchestrator: Any, *, goal: str, workspace: str, model: str,
                conversation_id: str) -> dict[str, Any]:
    if not goal.strip() or not Path(workspace).is_dir():
        raise ValueError("goal and an existing workspace are required")
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "status": "researching", "goal": goal.strip(), "workspace": workspace,
           "conversation_id": conversation_id, "progress": [], "plan": None, "error": None,
           "path": None, "steps": []}
    _JOBS[job_id] = job
    asyncio.create_task(_research_and_plan(orchestrator, job, model), name=f"ultraplan-{job_id}")
    return public_job(job)


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {**{key: job[key] for key in ("id", "status", "goal", "progress", "plan", "error", "path", "steps")},
            "can_replan": bool(job.get("evidence")) and job.get("status") == "failed"}


async def _research_and_plan(orchestrator: Any, job: dict[str, Any], model: str) -> None:
    try:
        if orchestrator._delegation is None:
            raise RuntimeError("Atlas 子 Agent 委派服务不可用")
        async def progress(sid: str, text: str, *_: Any) -> None:
            row = next((item for item in job["progress"] if item.get("id") == sid), None)
            if row is not None:
                row["detail"] = str(text)[-500:]
        async def completed(sid: str, status: str, summary: str, *_: Any) -> None:
            row = next((item for item in job["progress"] if item.get("id") == sid), None)
            if row is not None:
                row.update({"status": status, "detail": summary[:3000]})
        # Child start callbacks pass a task id; add it after each callback's metadata arrives.
        async def on_started(sid: str, title: str, backend: str, metadata: Any = None) -> None:
            job["progress"].append({"id": sid, "title": title, "status": "running",
                                    "detail": f"并行调研 Agent 已启动（{backend}）"})
        results = await orchestrator._delegation.delegate_parallel(
            [
                {"title": "代码结构与相关文件", "goal": f"只读调研目标：{job['goal']}。定位代码结构、关键文件与调用链，提供路径和行号证据。禁止修改文件。", "agent": "general", "agent_model": model, "agent_permission": "read_only", "agent_tools": ["read_file", "local_file", "search_files", "glob", "grep", "coding.repo_map"]},
                {"title": "依赖、风险与边界", "goal": f"只读调研目标：{job['goal']}。分析相关依赖、兼容性、风险和边界情况，给出依据。禁止修改文件。", "agent": "general", "agent_model": model, "agent_permission": "read_only", "agent_tools": ["read_file", "local_file", "search_files", "glob", "grep", "coding.repo_map"]},
                {"title": "验证与测试方法", "goal": f"只读调研目标：{job['goal']}。找出适用验证命令、现有测试、验收方法及潜在限制。禁止修改文件。", "agent": "general", "agent_model": model, "agent_permission": "read_only", "agent_tools": ["read_file", "local_file", "search_files", "glob", "grep", "coding.repo_map"]},
            ], max_concurrency=3, cwd=job["workspace"], on_started=on_started,
            on_progress=progress, on_completed=completed, executor="atlas",
            atlas_options={"model": model, "workspace": job["workspace"], "permission_mode": "read_only",
                           "tool_allow": ["read_file", "local_file", "search_files", "glob", "grep", "coding.repo_map"]},
        )
        job["evidence"] = json.dumps(results, ensure_ascii=False, default=str)
        job["model"] = model
        await _synthesize(orchestrator, job, model)
    except Exception as exc:
        job.update({"status": "failed", "error": _friendly_error(exc)})


async def replan(job_id: str, orchestrator: Any) -> dict[str, Any]:
    """Re-run only the synthesis step from the research already collected for this job."""
    job = _JOBS.get(job_id)
    if job is None:
        raise KeyError(job_id)
    if not job.get("evidence"):
        raise ValueError("这个计划还没有可用的调研结果，请重新发起 /ultraplan")
    if job.get("status") in {"researching", "planning", "executing"}:
        raise ValueError("计划正在生成或执行中")
    job.update({"status": "planning", "error": None})

    async def run() -> None:
        try:
            await _synthesize(orchestrator, job, str(job.get("model") or ""))
        except Exception as exc:
            job.update({"status": "failed", "error": _friendly_error(exc)})

    asyncio.create_task(run(), name=f"ultraplan-replan-{job_id}")
    return public_job(job)


async def _synthesize(orchestrator: Any, job: dict[str, Any], model: str) -> None:
    job["status"] = "planning"
    evidence = str(job["evidence"])
    schema = {"goal": "string", "background": "string", "steps": [{"id": "string", "title": "string", "detail": "string", "files": ["string"], "verify": "string"}], "risks": ["string"], "open_questions": ["string"]}
    prompt = "根据调研证据，仅返回符合指定字段的 JSON 计划，不要执行任务。证据：\n" + evidence + "\n字段结构：\n" + json.dumps(schema, ensure_ascii=False)
    response = await _complete_resilient(orchestrator, model, [{"role": "user", "content": prompt}], max_tokens=6000)
    try:
        plan = _parse_plan(response.text)
    except (ValueError, TypeError, json.JSONDecodeError) as first_error:
        rewrite = await _complete_resilient(orchestrator, model, [
            {"role": "system", "content": "修复无效计划，只输出符合 JSON schema 的 JSON 对象。"},
            {"role": "user", "content": f"schema={json.dumps(schema, ensure_ascii=False)}\n原输出={response.text}\n校验错误={first_error}"},
        ], max_tokens=6000)
        plan = _parse_plan(rewrite.text)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", plan["goal"].lower()).strip("-")[:32] or "plan"
    path = Path(job["workspace"]) / ".atlas" / "plans" / f"{stamp}-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(plan), encoding="utf-8")
    job.update({"status": "awaiting_approval", "plan": plan, "path": str(path), "steps": [
        {"id": step["id"], "status": "pending"} for step in plan["steps"]
    ]})


def get(job_id: str) -> dict[str, Any]:
    if job_id not in _JOBS:
        raise KeyError(job_id)
    return public_job(_JOBS[job_id])


def save_edit(job_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        raise KeyError(job_id)
    if job["status"] not in {"awaiting_approval", "failed_step"}:
        raise ValueError("plan is not awaiting approval")
    prior = {item["id"]: item["status"] for item in job["steps"]}
    job["plan"] = validate_plan(plan)
    Path(job["path"]).write_text(render_markdown(job["plan"]), encoding="utf-8")
    job["steps"] = [{"id": step["id"],
                     "status": "completed" if prior.get(step["id"]) == "completed" else "pending"}
                    for step in job["plan"]["steps"]]
    return public_job(job)


async def execute(job_id: str, orchestrator: Any) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        raise KeyError(job_id)
    if job["status"] != "executing":
        raise ValueError("plan execution has not been claimed")
    plan = validate_plan(job["plan"])
    for index, step in enumerate(plan["steps"]):
        if job["steps"][index]["status"] == "completed":
            continue
        job["steps"][index]["status"] = "running"
        prompt = f"按已批准的高级计划执行步骤：{step['title']}\n{step['detail']}\n文件：{', '.join(step['files'])}\n验证：{step['verify']}\n用户批注：{step.get('annotation', '')}"
        failed = False
        try:
            async for event in orchestrator.run(prompt, job["conversation_id"], workspace=job["workspace"],
                                                 workspace_trusted=True, permission_mode="full_access", mode="act"):
                if event.get("type") == "error":
                    job["steps"][index].update({"status": "failed", "error": str(event.get("detail") or "执行失败")})
                    failed = True
                    break
        except Exception as exc:
            job["steps"][index].update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            failed = True
        if failed:
            job["status"] = "failed_step"
            return public_job(job)
        job["steps"][index]["status"] = "completed"
        plan["steps"][index]["status"] = "completed"
        Path(job["path"]).write_text(render_markdown(plan), encoding="utf-8")
    job["status"] = "completed"
    job["plan"] = plan
    return public_job(job)


def discard(job_id: str) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        raise KeyError(job_id)
    if job["status"] in {"researching", "planning", "executing"}:
        raise ValueError("cannot discard an active workflow")
    job["status"] = "discarded"
    return public_job(job)


def claim_execution(job_id: str) -> dict[str, Any]:
    """Atomically claim one approved job before scheduling its execution task."""
    job = _JOBS.get(job_id)
    if job is None:
        raise KeyError(job_id)
    if job["status"] not in {"awaiting_approval", "failed_step"}:
        raise ValueError("plan cannot be executed in its current state")
    job["status"] = "executing"
    return public_job(job)
