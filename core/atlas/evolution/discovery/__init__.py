"""全网发现：从各家更新日志、GitHub、HN、Reddit、MCP 注册表、技能市场、论坛和网页搜索
里找新出的 agent / 功能 / MCP / 技能 / 工具，判断值不值得吸收，产出报告和移植任务书草稿。"""

from atlas.evolution.discovery.service import read_report, run_discovery, start_run, start_scheduler, status

__all__ = ["read_report", "run_discovery", "start_run", "start_scheduler", "status"]
