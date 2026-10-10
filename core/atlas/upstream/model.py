"""追新清单的数据模型：组件、分类、状态与更新方式。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: 分类（顺序即界面顺序）：id → (名称, 一句话说明)。
CATEGORIES: dict[str, tuple[str, str]] = {
    "kernel": ("Agent 内核", "Hermes fork：对话循环、工具、上下文压缩"),
    "memory": ("记忆", "MemOS fork：记忆、事实、技能学习"),
    "agents": ("外部 Agent 与协议", "Claude Code / Codex / Pi 等外部 Agent 与 ACP"),
    "automation": ("浏览器与电脑操作", "browser-use、cua、Playwright、Chrome DevTools"),
    "mcp": ("MCP 服务", "配置里启动的 MCP 服务器"),
    "models": ("模型接入", "模型调用库与模型目录"),
    "channels": ("外部渠道", "Slack、飞书、钉钉等渠道 SDK"),
    "learning": ("学习与进化", "技能训练等直接引用的仓库"),
    "backend": ("后端依赖", "其余 Python 运行依赖"),
    "desktop": ("桌面与界面", "Electron 界面用到的前端库"),
    "runtime": ("运行时", "Electron、Node、Python 本身"),
    "skills": ("技能", "从技能市场装的技能"),
    "borrowed": ("借鉴代码", "从别的项目移植进来的源码文件"),
    "transitive": ("间接依赖", "上面这些包自己依赖的包"),
    "dev": ("开发与测试工具", "测试、打包、类型检查"),
}

#: 状态。
LATEST = "latest"          # 已是最新
OUTDATED = "outdated"      # 有新版本
UNKNOWN = "unknown"        # 查不到最新版本（离线、来源不明）
ERROR = "error"            # 扫描或查询出错
HELD = "held"              # 用户锁定，不参与一键追新

#: 更新方式。
AUTO = "auto"        # 预演副本里直接改版本号、装包、跑测试
MERGE = "merge"      # fork 合并上游；冲突时需要人（或 Agent）处理
REVIEW = "review"    # 借鉴代码：三方合并上游改动，冲突时生成待办
HOT = "hot"          # 不用重启，直接在运行中的 Atlas 里更新（技能、MCP 版本号）
MANUAL = "manual"    # 只提示，不自动做（如 Python 大版本）

STRATEGY_LABELS = {
    AUTO: "自动更新", MERGE: "合并上游", REVIEW: "合并改动", HOT: "即时更新", MANUAL: "需手动",
}


@dataclass
class Component:
    """清单里的一项。``id`` 在一次扫描内唯一，形如 ``pip:browser-use``、``npm:react``。"""

    id: str
    name: str
    category: str
    kind: str
    current: str = ""
    latest: str = ""
    status: str = UNKNOWN
    strategy: str = AUTO
    spec: str = ""
    source: str = ""
    url: str = ""
    locations: list[str] = field(default_factory=list)
    note: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def resolve_status(self) -> None:
        """有 current 与 latest 时按是否相同定状态（已设为 error/held 的不动）。"""
        if self.status in {ERROR, HELD}:
            return
        if not self.latest or not self.current:
            self.status = UNKNOWN
        else:
            self.status = LATEST if self.current == self.latest else OUTDATED

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["category_label"] = CATEGORIES.get(self.category, (self.category, ""))[0]
        data["strategy_label"] = STRATEGY_LABELS.get(self.strategy, self.strategy)
        return data


def is_actionable(component: dict[str, Any]) -> bool:
    """一键追新会处理的项：有新版本、不是手动项。"""
    return component.get("status") == OUTDATED and component.get("strategy") != MANUAL
