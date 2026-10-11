"""Model-facing Atlas tool catalog for the Hermes runtime.

H2.2 module split: the tool schema assembly used to live on
``AgentOrchestrator._model_facing_tools``; the orchestrator keeps a thin
delegating method so engine adapters (``engine.tool_registry`` /
``engine.hermes_policy``) and tests keep calling it through the agent
instance. Behavior is unchanged — the catalog is derived purely from the
orchestrator's runtimes.
"""

from __future__ import annotations

from typing import Any

from atlas.tools.web import WEB_TOOLS as _WEB_TOOLS

_WEB_EXTRACT_TOOL = {"type": "function", "function": {
    "name": "web_extract",
    "description": "提取网页正文或视频字幕，供阅读和总结链接使用。",
    "parameters": {"type": "object", "properties": {
        "url": {"type": "string"},
        "allow_local": {
            "type": "boolean",
            "description": "仅在用户明确要求读取本机 localhost 页面时为 true。",
        },
    }, "required": ["url"], "additionalProperties": False},
}}


def model_facing_tools(agent) -> list[dict[str, Any]]:
    """Assemble model-facing tool names for Atlas runtime telemetry."""
    """Assemble model-facing tool names for Atlas runtime telemetry."""
    tools = agent._mcp.get_tools_for_llm() if agent._mcp else []
    if agent._custom_tools is not None:
        tools.extend(agent._custom_tools.model_tools())
    if agent._local_execution:
        tools = [*tools, *agent._local_execution.get_tools_for_llm()]
    if agent._computer_use:
        tools = [*tools, *agent._computer_use.get_tools_for_llm()]
    if agent._web is not None:
        tools = [*tools, *_WEB_TOOLS, _WEB_EXTRACT_TOOL]
    if agent._memory is not None:
        tools = [*tools, {
            "type": "function",
            "function": {
                "name": "remember",
                "description": (
                    "Persist a durable memory about the user or project without "
                    "asking. Use for stable preferences, project conventions, and "
                    "corrective feedback (kind: preference|convention|feedback|fact)."
                ),
                "parameters": {"type": "object", "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "kind": {"type": "string", "enum": [
                        "preference", "convention", "feedback", "fact",
                    ]},
                }, "required": ["key", "value"], "additionalProperties": False},
            },
        }]
    tools.append({"type": "function", "function": {
        "name": "automation_manage",
        "description": (
            "Manage Atlas reminders/automations (E8). Actions: create | cancel | "
            "update | list. Use create when the user asks to be reminded at/near a "
            "time (\"明天上午9点提醒我交报告\"); cancel when they ask to drop a "
            "reminder (\"取消那个提醒\"); update when they move/reschedule it "
            "(\"改到下午\"); list before answering questions about pending reminders. "
            "This writes the real AutomationStore and syncs the existing "
            "AutomationEngine — never invent a second scheduler."
        ),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["create", "cancel", "update", "list"]},
            "message": {"type": "string", "description": "提醒正文（create/update）"},
            "due_at": {"type": "string", "description": "ISO 8601 绝对时间（优先）"},
            "due_text": {"type": "string", "description": "自然语言时间，如 明天上午9点 / 今天下午3点"},
            "query": {"type": "string", "description": "cancel/update 时用于匹配提醒的子串"},
            "automation_id": {"type": "string", "description": "精确 id（可选，优先于 query）"},
        }, "required": ["action"], "additionalProperties": False},
    }})
    tools.append({"type": "function", "function": {
        "name": "todo_list",
        "description": "Track a bounded task list for multi-step work. Replace or merge with todos; call with no todos to read. List every required item, keep one in_progress, and mark completed only after verification.",
        "parameters": {"type": "object", "properties": {
            "todos": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "content": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]},
                "parent": {"type": "string"},
            }, "required": ["id", "content", "status"]}},
            "merge": {"type": "boolean"},
        }, "required": [], "additionalProperties": False},
    }})
    tools.append({"type": "function", "function": {
        "name": "project_note",
        "description": "Append durable project guidance to .atlas/NOTES.md. Use for repeatable test/build commands, code conventions, user preferences, and known pitfalls. Do not store one-time task details.",
        "parameters": {"type": "object", "properties": {
            "section": {"type": "string"}, "text": {"type": "string"},
        }, "required": ["section", "text"], "additionalProperties": False},
    }})
    tools.extend([{
        "type": "function", "function": {
            "name": "kanban_create_board", "description": "Create a named Atlas coordination board.",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string"}, "board_id": {"type": "string"},
            }, "required": ["name"], "additionalProperties": False},
        },
    }, {
        "type": "function", "function": {
            "name": "kanban_list", "description": "List task cards on an Atlas coordination board.",
            "parameters": {"type": "object", "properties": {
                "board_id": {"type": "string"},
            }, "required": ["board_id"], "additionalProperties": False},
        },
    }, {
        "type": "function", "function": {
            "name": "kanban_create_task", "description": "Create a task card with assignee and dependency ids.",
            "parameters": {"type": "object", "properties": {
                "board_id": {"type": "string"}, "title": {"type": "string"},
                "description": {"type": "string"}, "assignee": {"type": "string"},
                "dependencies": {"type": "array", "items": {"type": "string"}},
                "run_id": {"type": "string"},
            }, "required": ["board_id", "title"], "additionalProperties": False},
        },
    }, {
        "type": "function", "function": {
            "name": "kanban_update_task", "description": "Claim or update a task card. Set status to running to claim, review for verification, or done after acceptance.",
            "parameters": {"type": "object", "properties": {
                "board_id": {"type": "string"}, "task_id": {"type": "string"},
                "status": {"type": "string", "enum": ["todo", "running", "blocked", "review", "done"]},
                "assignee": {"type": "string"}, "output": {"type": "string"},
                "run_id": {"type": "string"},
            }, "required": ["board_id", "task_id"], "additionalProperties": False},
        },
    }])
    if agent._projects is not None:
        tools.append({"type": "function", "function": {
            "name": "project_sources_search",
            "description": "Search the current project's attached files, links, and notes.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            }, "required": ["query"], "additionalProperties": False},
        }})
    if agent._skills is not None:
        tools = [*tools, {
            "type": "function",
            "function": {
                "name": "use_skill",
                "description": (
                    "Load an Atlas Skill's full instructions into this conversation. "
                    "Call this when the task matches one of the skills listed in the "
                    "skill index system message, then follow the returned instructions."
                ),
                "parameters": {"type": "object", "properties": {
                    "name": {"type": "string"},
                }, "required": ["name"], "additionalProperties": False},
            },
        }, {
            "type": "function",
            "function": {
                "name": "skill_search",
                "description": (
                    "Search the whole Atlas skill library (installed and fetch-on-use skills) "
                    "when the skill index does not list a fitting one. Returns names to pass to use_skill."
                ),
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string", "description": "Optional category name or id."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30},
                }, "required": ["query"], "additionalProperties": False},
            },
        }]
    if agent._memory is not None:
        tools = [*tools, {
            "type": "function",
            "function": {
                "name": "session_search",
                "description": (
                    "Search the user's past Atlas conversations (raw history, not "
                    "summarized memory). Returns matching messages with surrounding "
                    "context, conversation title, and timestamps."
                ),
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                    "context": {"type": "integer", "minimum": 0, "maximum": 6},
                }, "required": ["query"], "additionalProperties": False},
            },
        }]
    tools = [*tools, {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": (
                "Run a bounded Python workflow using atlas.call_tool(name, arguments)."
            ),
            "parameters": {"type": "object", "properties": {
                "code": {"type": "string"},
            }, "required": ["code"], "additionalProperties": False},
        },
    }]
    tools.extend([
        {"type": "function", "function": {"name": "create_checkpoint",
         "description": "Create an Atlas shadow Git snapshot for explicit workspace paths.",
         "parameters": {"type": "object", "properties": {
             "workspace": {"type": "string"}, "paths": {"type": "array",
             "items": {"type": "string"}},
         }, "required": ["workspace", "paths"], "additionalProperties": False}}},
        {"type": "function", "function": {"name": "list_checkpoints",
         "description": "List shadow checkpoints for an optional workspace.",
         "parameters": {"type": "object", "properties": {
             "workspace": {"type": "string"},
         }, "additionalProperties": False}}},
        {"type": "function", "function": {"name": "restore_checkpoint",
         "description": "Restore the scoped files from an Atlas shadow checkpoint.",
         "parameters": {"type": "object", "properties": {
             "checkpoint_id": {"type": "string"},
         }, "required": ["checkpoint_id"], "additionalProperties": False}}},
    ])
    tools.append({
        "type": "function", "function": {
            "name": "new_context_window",
            "description": (
                "Create a concise handoff summary of this task, then continue with a clean "
                "model context while preserving the conversation history."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    })
    tools.append({
        "type": "function", "function": {
            "name": "run_checks",
            "description": "Run project lint, typecheck, tests, or all available checks and return structured diagnostics.",
            "parameters": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["lint", "typecheck", "test", "all"]},
                "paths": {"type": "array", "items": {"type": "string"}},
            }, "required": ["kind"], "additionalProperties": False},
        },
    })
    tools.extend([
        {"type": "function", "function": {
            "name": "create_document",
            "description": "Create a .docx file in the current workspace.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"}, "title": {"type": "string"},
                "blocks": {"type": "array", "items": {
                    "type": "object", "properties": {
                        "type": {"type": "string", "enum": [
                            "heading", "paragraph", "bullets", "table", "image",
                        ]},
                        "text": {"type": "string"}, "level": {"type": "integer"},
                        "items": {"type": "array", "items": {"type": "string"}},
                        "rows": {"type": "array", "items": {
                            "type": "array", "items": {},
                        }},
                        "path": {"type": "string"}, "width": {"type": "number"},
                    }, "required": ["type"], "additionalProperties": False,
                }},
            }, "required": ["path", "blocks"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "create_spreadsheet",
            "description": "Create an .xlsx workbook in the current workspace.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
                "sheets": {"type": "array", "items": {
                    "type": "object", "properties": {
                        "name": {"type": "string"}, "rows": {"type": "array",
                            "items": {"type": "array", "items": {}}},
                        "header": {"type": "boolean"},
                        "column_widths": {"type": "array", "items": {"type": "number"}},
                    }, "required": ["name", "rows"], "additionalProperties": False,
                }},
            }, "required": ["path", "sheets"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "create_presentation",
            "description": "Create a .pptx presentation in the current workspace.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
                "slides": {"type": "array", "items": {
                    "type": "object", "properties": {
                        "title": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                        "notes": {"type": "string"}, "image": {"type": "string"},
                    }, "required": ["title"], "additionalProperties": False,
                }},
            }, "required": ["path", "slides"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "read_office",
            "description": "Read text, tables, formulas, and slide headings from an Office file.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
            }, "required": ["path"], "additionalProperties": False},
        }},
    ])
    if agent._delegation:
        tools.append({
            "type": "function",
            "function": {
                "name": "delegate_task",
                "description": (
                    "Delegate one bounded task. agent may be explore, researcher, plan, oracle, "
                    "verifier, general, or a trusted installed definition. Parallelize only "
                    "independent read-oriented work; keep dependent steps and shared-file edits serial."
                ),
                "parameters": {"type": "object", "properties": {
                    "goal": {"type": "string"}, "context": {"type": "string"},
                    "tool_profile": {"type": "array", "items": {"type": "string"}},
                    "executor": {"type": "string"},
                    "agent": {"type": "string"},
                    "background": {"type": "boolean"},
                    "permission_mode": {
                        "type": "string", "enum": ["full_access", "ask_writes", "read_only"],
                        "description": (
                            "Request a stricter permission mode for the child. Only stricter "
                            "requests are honored; the child never exceeds the parent."
                        ),
                    },
                    "output_schema": {"type": ["object", "string", "null"]},
                    "recipe": {"type": ["object", "null"], "properties": {
                        "id": {"type": "string"}, "params": {"type": "object"},
                    }, "required": ["id"], "additionalProperties": False},
                }, "required": [], "additionalProperties": False},
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "delegate_parallel",
                "description": (
                    "Delegate up to eight independent tasks to parallel workers. Each worker "
                    "returns findings and, when isolated, a patch for coordinator review."
                ),
                "parameters": {"type": "object", "properties": {
                    "tasks": {"type": "array", "minItems": 1, "maxItems": 8,
                              "items": {"type": "object", "properties": {
                                  "title": {"type": "string"},
                                  "goal": {"type": "string"},
                                  "context": {"type": ["string", "null"]},
                                  "output_schema": {"type": ["object", "string", "null"]},
                                  "agent": {"type": "string"},
                                  "recipe": {"type": ["object", "null"], "properties": {
                                      "id": {"type": "string"}, "params": {"type": "object"},
                                  }, "required": ["id"], "additionalProperties": False},
                              }, "required": ["title"],
                                  "additionalProperties": False}},
                    "max_concurrency": {"type": "integer", "minimum": 1, "maximum": 8},
                    "executor": {"type": "string"},
                    "verify": {"type": ["object", "null"], "properties": {
                        "criteria": {"type": "string"},
                    }, "required": ["criteria"], "additionalProperties": False},
                    "background": {"type": "boolean"},
                }, "required": ["tasks"], "additionalProperties": False},
            },
        })
        tools.extend([
            {"type": "function", "function": {
                "name": "subtask_status",
                "description": "查看一个子任务的状态、最近进度和完成结果。",
                "parameters": {"type": "object", "properties": {
                    "subtask_id": {"type": "string"},
                }, "required": ["subtask_id"], "additionalProperties": False},
            }},
            {"type": "function", "function": {
                "name": "subtask_message",
                "description": "向仍在运行的子任务补充要求；消息会在子 Agent 下一轮开始时送达。",
                "parameters": {"type": "object", "properties": {
                    "subtask_id": {"type": "string"}, "text": {"type": "string"},
                }, "required": ["subtask_id", "text"], "additionalProperties": False},
            }},
        ])
    tools.extend([
        {"type": "function", "function": {
            "name": "submit_findings",
            "description": (
                "Submit code-review findings and emit the review.findings event. Pass "
                "the reviewer's JSON findings array verbatim; an empty array is valid."
            ),
            "parameters": {"type": "object", "properties": {
                "findings_json": {"type": "string",
                                  "description": "JSON array of findings, verbatim from the reviewer."},
                "scope": {"type": "string", "description": "Review scope: working_tree, branch, or commit."},
                "scope_label": {"type": "string", "description": "Chinese display label of the review scope."},
            }, "required": ["findings_json"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "review_command",
            "description": (
                "Run a read-only verification command during a code review (tests, lint, "
                "typecheck, git read commands). Write-capable or mutating commands are refused."
            ),
            "parameters": {"type": "object", "properties": {
                "command": {"type": "string", "description": "The command line to run."},
                "cwd": {"type": "string", "description": "Working directory; defaults to the current workspace."},
            }, "required": ["command"], "additionalProperties": False},
        }},
    ])
    tools.append({
        "type": "function", "function": {
            "name": "ask_user",
            "description": "Ask the user a question and wait for their reply.",
            "parameters": {"type": "object", "properties": {
                "question": {"type": "string"},
                "options": {"type": ["array", "null"],
                            "items": {"type": "string"}},
            }, "required": ["question"], "additionalProperties": False},
        },
    })
    return tools
