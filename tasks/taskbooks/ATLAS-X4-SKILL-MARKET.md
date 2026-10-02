# ATLAS-X4：技能市场

> 前提：X2 验收通过（X2 录制出来的技能要能进市场体系）。
> 先读：ROADMAP-TO-PRODUCT、EXECUTION-GUIDE、C4 的结果文件和验收记录（技能目录合一后的现状）。

## 本波目标

在 Atlas 里能搜索、预览、安装、更新、卸载各个来源的技能，体验不输 Hermes 的技能市场，也不输 Claude Code 的插件市场。装好的技能立刻能用，渐进加载，不白占上下文。

## 1. 来源和后端（主路径：接通 Hermes 的技能市场客户端）

- **Hermes 侧代码**：
  - `tools/skills_hub.py`：总入口、缓存、锁文件、技能源管理（taps）、审计日志；
  - `skills_hub_sources.py`：各个技能源；
  - `skills_hub_search.py`：搜索；
  - `skills_hub_install.py`：安装；
  - `skills_hub_models.py`：数据结构；
  - `skills_hub_official.py`、`skills_hub_github.py`、`skills_hub_skillssh.py`、`skills_hub_clawhub.py`：四种技能源；
  - `skills_sync*.py`：同步内置技能和可选技能。
- **做法**：在 fork 里启用这些模块，安装位置指到 Atlas 的技能目录（C4 合并后的那套），然后接到 Atlas 的技能注册、版本和信任管理（`core/atlas/skills/`）上。**不要两套并存**：已装清单、锁文件、更新检查都只用一份。
- **技能源**：
  - 默认：Hermes 官方、skills.sh、ClawHub、GitHub（任意仓库）；
  - Claude Code 插件市场里带的技能：通过 C4 的插件体系导入；
  - 用户可以添加自定义技能源，比如自己的 GitHub 仓库。
- **国内网络**：每个技能源都要能走代理；连不上时给出白话提示，不卡住界面。
- **不做**：安装前的安全扫描（Hermes 的 `skills_guard`、`skills_ast_audit` 等），按约定由用户亲自负责，保持关闭。只做来源显示，以及安装前预览 SKILL.md 和文件清单。

## 2. 接口

- `GET /api/skills/market/search?q=&source=`：搜索。
- `GET /api/skills/market/{source}/{id}`：详情，包括说明、版本、作者、文件清单、SKILL.md 预览。
- `POST /api/skills/market/install`、`POST /api/skills/{name}/update`、`DELETE /api/skills/{name}`。
- `GET /api/skills/updates`：检查更新。
- 技能源管理：`GET` 和 `POST` `/api/skills/market/sources`。

所有接口都过 OriginGuard。

## 3. 前端（技能市场页）

- 入口：侧栏「技能」→ 三个标签页：「市场」「已安装」「更新」。
- **市场**：搜索框、按来源筛选、卡片（名字、一句话说明、来源、星数或下载量、是否已安装）；点开看详情和 SKILL.md 预览；一键安装。
- **已安装**：启用和停用、看版本和来源、卸载、「在对话里试用」（新开一个对话，自动激活这个技能）。
- **更新**：可以更新的列表，一键全部更新；更新前能看到改了什么。
- X2 录制生成的技能、技能自学生成的技能（X5，以后才有），也显示在「已安装」里，标记「本机生成」。
- 要美观，放不下的做成可折叠的；四项前端检查；截图。

## 4. 测试和验收

- **假技能源测试**：搜索、安装、更新、卸载、锁文件一致、同名冲突、断网提示、渐进加载（装了 50 个技能，提示词里只增加索引）。
- **真实验收**（先问用户）：从 skills.sh 或 GitHub 各装一个真实技能，在对话里用一次，再卸载。
- 更新 CORE-PARITY 的「外部功能」一节，加 X4 各行；同步 PARITY（F175、F181）。

## 5. 交付

结果文件 `tasks/results/ATLAS-X4-SKILL-MARKET.result.md`，写清：Hermes 模块和 Atlas 技能系统的对接方式、技能源清单、真实验收记录、全量测试汇总行。
