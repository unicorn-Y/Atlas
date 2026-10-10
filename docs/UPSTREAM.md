# 组件追新（Atlas 追新）

把 Atlas 里所有「别人的东西」追到最新：入口在侧栏「自动追新」页最上面的「组件追新」卡片。
代码在 `core/atlas/upstream/`，接口 `/api/upstream`。

## 跟踪什么（自动发现，不用登记）

| 分类 | 来源 | 怎么更新 |
|---|---|---|
| Agent 内核 | Hermes fork（`core/pyproject.toml` `[tool.atlas.hermes]`） | 把上游 `upstream_ref` 合进 fork，跑 Atlas 补丁测试，推送 fork，改锁定提交 |
| 记忆 | MemOS fork（`vendor/memos-local-plugin/.atlas-upstream.json`） | 下载基准版与新版 npm 包，逐文件三方合并，重建 |
| Python 依赖 / 外部 Agent / 浏览器与电脑操作 / 渠道 / 模型接入 | `core/pyproject.toml` | 改 `==` 锁定版本，装新版，重写 `core/requirements.lock` |
| 学习与进化 | pyproject 里的 `git+https://github.com/...@提交号` | 换成上游最新提交 |
| 桌面与界面 / 开发工具 / 运行时（Electron） | 各 `package.json` | `npm install 包@最新`，保持 `^`/精确写法；同步 MCP 启动参数里的版本 |
| 间接依赖 | `pip list --outdated` / `npm outdated --all` | 逐个升级，引入依赖冲突的保持原样；npm 按版本范围更新 |
| MCP 服务 | `config/atlas.example.toml` 与本机 `config/atlas.toml` 的 `npx 包@版本` | 示例配置随提交更新；本机配置在重启时由 `post-merge` 对齐 |
| 运行时 | `frontend/node-runtime.json`（安装包内置 Node）、Python | Node 跟到最新 LTS（含校验值）；Python 只提示 |
| 技能 | 技能市场装的技能 | 直接在运行中的 Atlas 里更新（不用重启） |
| 借鉴代码 | 源码文件头的来源标注 | 三方合并上游该文件的改动；重叠时生成 `data/upstream/reviews/*.diff` 待人工 |

借鉴代码的标注写法（以后新移植的文件照这个写）：

```
# Ported from owner/repo@<完整提交号>: path/in/upstream.py (License)
```

## 怎么保证不把 Atlas 弄坏

1. 所有改动都在仓库旁的 `atlas-upstream-staging/` 里做（git 工作树 + 复制的 venv 与 node_modules），
   正在用的 Atlas 照常运行。
2. 先跑一遍后端单元测试和前端构建/测试当基线；每组更新后再跑，**只要出现基线以外的新失败**
   （或依赖冲突、构建失败、导入失败）就整组回退。
3. 整组不过时，先把不跨大版本的一起重试，再逐个试跨大版本的，找出有问题的那项单独回退，
   原因写进 `data/upstream/failed.json`；自动追新不再重试这个版本，上游出了新版本再试。
4. 通过的每组提交一次（提交者「Atlas 追新」），然后推送到远端当前分支（设置里可关）。
   推送不了时结果留在 `data/upstream/pending-merge.json`，更新器重启时在本机合并。
5. 重启（界面上的「立即重启更新」或更新横幅）走 `scripts/atlas-update.mjs`：合并 → 按需
   `pip install -r core/requirements.lock`、`npm ci`、重建前端 → `python -m atlas.upstream post-merge`。

## 自动

设置（`data/upstream/settings.json`，界面上可切）：

- `auto`（默认）：每 24 小时检查一次，有新版本就在预演副本里更新并验证，完成后 Windows 通知、
  界面提示重启。
- `check`：只检查和提示。
- `off`：什么都不做。
- 「锁定」某一项：一键追新和自动追新都跳过它（比如等 React 19 适配完再放开）。

## 命令行

```
python -m atlas.upstream check          # 检查并打印汇总
python -m atlas.upstream run --all      # 全部追到最新（前台跑，日志进 data/upstream/run.json）
python -m atlas.upstream run --ids npm:react pip:fastapi
```
