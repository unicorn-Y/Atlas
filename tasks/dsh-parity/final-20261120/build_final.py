# -*- coding: utf-8 -*-
"""Build the consolidated Atlas x DSH parity table (2026-11-20).

Inputs: Codex session tables (read-only) + DSH package inventory.
Outputs: final TSV, coverage ledger, action list, stats.
"""
import csv, io, os, re, glob, collections

BASE = r"C:\Users\25011\Documents\codex\2026-11-19\kan"
OUT = r"D:\Atlas\tasks\dsh-parity\final-20261120"
DSH_REF = "2e39e704"
ATLAS_REF = "060071ab"
V = "DSH 2e39e704（master）/ rc.5 9c2670d3；Atlas 060071ab（wave3 HEAD）+ 未提交工作区"


def read_rows(path):
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        return [dict(x) for x in csv.DictReader(f, delimiter="\t")]


def pick(rows, keys):
    for k in keys:
        if k in rows and (rows[k] or "").strip():
            return rows[k].strip()
    return ""


# ---------------- existing tables ----------------
STATUS_MAP = {
    "对齐已验": "已对齐", "部分": "部分", "缺失": "缺失",
    "已见设计取向差异": "设计差异", "资源差异": "设计差异",
    "两侧均可配置，角色粒度不同": "设计差异", "显示档位与作用域不同": "设计差异",
    "持久化入口与应用时机不同": "设计差异", "字重、字族与模板不同": "设计差异",
    "渲染与换肤机制不同": "设计差异", "某些表面各有实现": "设计差异",
    "均使用浏览器色系能力，所读入口不同": "设计差异", "反馈结构有所不同": "设计差异",
    "阈值及可配置语义不同": "设计差异",
}
src_files = [
    BASE + r"\outputs\Atlas-DSH-完整范围对照总表.tsv",
    BASE + r"\outputs\Atlas-DSH-行为逐项对照.tsv",
    BASE + r"\outputs\Atlas-DSH-Luna双轮详细复核.tsv",
    BASE + r"\outputs\Atlas-DSH-Luna逐项源码复核.tsv",
    BASE + r"\outputs\Atlas-DSH-续查行为对照.tsv",
    BASE + r"\outputs\Atlas-DSH-最新实质行为补核.tsv",
    BASE + r"\outputs\Atlas-DSH-界面资源与压缩细节.tsv",
    BASE + r"\outputs\Atlas-DSH-总对照表.tsv",
] + sorted(glob.glob(BASE + r"\work\dsh-*.tsv"))

ALL = collections.defaultdict(list)
for path in src_files:
    for r in read_rows(path):
        i = pick(r, ["ID", "能力ID"])
        if not i:
            continue
        ALL[i].append((os.path.basename(path), r))


def classify_sentence(s):
    s = (s or "").strip()
    if not s:
        return "未核"
    if s.startswith("部分") or s.startswith("部分对应") or s.startswith("部分重叠"):
        return "部分"
    if s.startswith("缺失") or ("明确" in s[:12] and "缺口" in s):
        return "缺失"
    if s.startswith("对齐") or s.startswith("已对齐") or "对齐已验" in s[:12]:
        return "已对齐"
    # Directional claims: an Atlas-side absence or non-equivalence is a gap, not "unverified".
    if re.search(r"(?:Atlas|atlas)[^。；]{0,50}(?:未发现|未见|未跟踪|无对应|不等同|不提供|不覆盖|没有对应)", s):
        return "缺失"
    if re.search(r"(?:Atlas|atlas)[^。；]{0,30}(?:更多|多于|比 DSH|比DSH)", s):
        return "设计差异"
    if (s.startswith("待核") or s.startswith("需对照") or "待核" in s[:15]
            or "不能判" in s or "未证" in s or "不足以" in s or "尚未" in s):
        return "未核"
    if ("不同" in s or "差异" in s or "不是同一" in s or "不等价" in s
            or "机制分离" in s or "架构不同" in s):
        return "设计差异"
    if ("DSH" in s or "dsh" in s) and ("Atlas" in s or "atlas" in s):
        return "设计差异"
    if s.startswith("两边") or s.startswith("都") or s.startswith("功能面"):
        return "设计差异"
    return "未核"


EXACT = {"部分", "缺失", "对齐已验", "已对齐"}
SRC_RANK = {"Atlas-DSH-完整范围对照总表.tsv": 0, "Atlas-DSH-行为逐项对照.tsv": 1,
            "Atlas-DSH-Luna双轮详细复核.tsv": 2, "Atlas-DSH-Luna逐项源码复核.tsv": 3,
            "Atlas-DSH-续查行为对照.tsv": 4, "Atlas-DSH-最新实质行为补核.tsv": 5,
            "Atlas-DSH-界面资源与压缩细节.tsv": 6, "Atlas-DSH-总对照表.tsv": 7}


def row_rank(item):
    src, r = item
    return (SRC_RANK.get(src, 5), -len(r))


DOMAIN_CODE = [
    ("F01", ("发行", "构建", "安装", "打包", "发布")),
    ("F02", ("Desktop", "桌面", "窗口", "Electron", "IPC", "托盘", "菜单", "快捷键", "更新", "宿主")),
    ("F03", ("Web", "渲染", "界面", "字体", "图标", "CSS", "样式", "页面", "组件", "UI")),
    ("F04", ("CLI", "SDK", "协议", "接口", "API", "路由", "AppServer", "IPC 协议", "远程")),
    ("F05", ("Host", "agent", "Agent", "内核", "循环", "生命周期", "取消", "计划", "goal", "Goal", "todo", "Todo", "子代理", "subagent")),
    ("F06", ("模型", "账户", "上下文", "压缩", "prompt", "推理", "凭据", "认证")),
    ("F07", ("会话", "存储", "历史", "持久化", "投影", "spill", "遥测", "反馈")),
    ("F08", ("工具", "工作区", "执行", "沙箱", "终端", "SSH", "ssh", "文件", "shell", "Office", "浏览器", "web")),
    ("F09", ("扩展", "插件", "权限", "技能", "市场", "审批", "授权", "连接器")),
    ("F10", ("协作", "云", "配置", "遥测", "团队", "身份", "数据")),
]


def domain_code(domain, detail=""):
    s = (domain or "") + " " + (detail or "")
    m = re.search(r"F(0\d|10)\b", s)
    if m:
        return "F" + m.group(1)
    m = re.search(r"\b(0\d|10)\s", s)
    if m:
        return "F" + m.group(1)
    for code, kws in DOMAIN_CODE:
        if any(k in s for k in kws):
            return code
    return "X"


def priority_for(verdict, rid, detail, note, domain):
    if verdict in ("已对齐", "设计差异", "Atlas独有"):
        return ""
    text = (detail or "") + (note or "")
    if verdict == "非产品面":
        return "P3"
    if re.search(r"族级映射|无独立 dsh 型 CLI|DSH 专有|DSH专有|不同抽象|架构差异|不适用", text):
        return "P3"
    if rid.startswith("B-F04-CLI") or rid.startswith("B-F04-SDK"):
        return "P3"
    if rid.startswith("SH-C4") or rid.startswith("SH-F01"):
        return "P2"
    if rid.startswith("B-F02-IPC"):
        return "P2"
    if verdict == "未核":
        return "P3"
    safety = bool(re.search(r"安全|权限|认证|凭据|沙箱|加密|审计", text))
    core = domain in ("F02", "F05", "F06", "F08", "F09")
    if verdict == "缺失":
        return "P0" if (safety and core) else "P1"
    if verdict == "部分":
        return "P1" if safety else "P2"
    if verdict == "候选对应":
        return "P2"
    return "P3"


canon = []
for i, items in ALL.items():
    items.sort(key=row_rank)
    r = items[0][1]
    verdict = ""
    for _, rr in items:
        raw = pick(rr, ["状态", "结论", "Atlas历史映射状态", "对比结论"])
        v = STATUS_MAP.get(raw) or (classify_sentence(raw) if raw not in EXACT else "已对齐")
        if v in ("缺失", "部分", "已对齐"):
            verdict = v
            break
        if v == "设计差异" and not verdict:
            verdict = "设计差异"
    if not verdict:
        verdict = "未核"
    domain = " ".join(dict.fromkeys(x for x in (pick(rr, ["领域"]) for _, rr in items) if x))
    detail = next((x for x in (pick(rr, ["细节", "细节或对应行为", "行为"]) for _, rr in items) if x), "")
    dsh = next((x for x in (pick(rr, ["DSH行为与可观察结果", "DSH行为", "DSH可观察结果", "DSH实现"]) for _, rr in items) if x), "")
    dsh_ev = next((x for x in (pick(rr, ["DSH证据", "DSH入口", "DSH源码ID"]) for _, rr in items) if x), "")
    atlas = next((x for x in (pick(rr, ["Atlas行为", "Atlas主树行为", "Atlas旧表实现", "Atlas历史映射状态"]) for _, rr in items) if x), "")
    atlas_ev = next((x for x in (pick(rr, ["Atlas证据", "Atlas旧表定位", "Atlas既有证据"]) for _, rr in items) if x), "")
    note = next((x for x in (pick(rr, ["差异或验证边界", "候选或验证边界", "既有缺口"]) for _, rr in items) if x), "")
    raw_status = pick(r, ["状态", "结论", "Atlas历史映射状态"])
    if len(raw_status) > 24 and raw_status not in EXACT:
        verdict_note = f"原结论：{raw_status}"
        if note and note != "—":
            note = verdict_note + "；" + note
        else:
            note = verdict_note
    action = ""
    if verdict == "缺失":
        action = f"新增/对齐：{detail}" + (f"；缺口：{note[:240]}" if note else "")
    elif verdict == "部分":
        action = f"补齐：{detail}" + (f"；缺口：{note[:240]}" if note else "")
    elif verdict == "未核":
        action = f"先核验：{detail}" + (f"；边界：{note[:200]}" if note else "")
    else:
        action = "无需动作（已对齐/设计差异/独有）"
    canon.append({
        "ID": i,
        "域编码": domain_code(domain, detail),
        "领域": domain or "未分类",
        "细节": detail or "—",
        "DSH版本": "rc.5" if not pick(r, ["rc.5增量检查"]) else "master/rc.5差异",
        "DSH行为": dsh or "—",
        "DSH证据": dsh_ev or "—",
        "Atlas行为": atlas or "—",
        "Atlas证据": atlas_ev or "—",
        "结论": verdict,
        "差异或边界": note or "—",
        "Atlas行动": action,
        "优先级": priority_for(verdict, i, detail, note, domain_code(domain, detail)),
        "证据等级": "历史台账（含源码锚点）" if "历史" in items[0][0] else "源码静态",
        "来源": items[0][0],
    })

def norm_status(raw):
    raw = (raw or "").strip()
    if raw in STATUS_MAP:
        return STATUS_MAP[raw]
    if raw.startswith("DSH module explicitly inventoried"):
        return "未核"
    for key, val in STATUS_MAP.items():
        if raw.startswith(key):
            return val
    return "未核"


# ---------------- inventories ----------------
INV = read_rows(r"D:\Atlas\tasks\dsh-parity\_dsh_pkg_inventory.tsv")
INV_BY_MANIFEST = {r["manifest"]: r for r in INV}
PICK_BY_MANIFEST = {}
for r in read_rows(os.path.join(OUT, "_pkg_entry_picks.tsv")):
    PICK_BY_MANIFEST[r["manifest"]] = r.get("entry_pick", "")
VER_BY_MANIFEST = {}
for r in read_rows(BASE + r"\outputs\Atlas-DSH-最新版全部包与插件声明.tsv"):
    if r.get("产品") == "DSH":
        VER_BY_MANIFEST[r.get("清单路径", "")] = r.get("差异状态", "")
for r in read_rows(os.path.join(OUT, "_uncovered_entry_exports.tsv")):
    VER_BY_MANIFEST.setdefault(r["manifest"], r.get("in_versions", ""))
for r in INV:
    st = VER_BY_MANIFEST.get(r["manifest"], "")
    r["in_versions"] = "master 新增" if "新增" in st else ("master 删除" if "删除" in st else "rc.5")

DOMAIN_CN = {
    "F01": "F01 发行、构建与安装", "F02": "F02 桌面与系统集成", "F03": "F03 Web 与渲染层",
    "F04": "F04 CLI、SDK 与协议", "F05": "F05 Host/Agent 循环", "F06": "F06 模型、账户与上下文",
    "F07": "F07 会话、存储与历史", "F08": "F08 工具、工作区与执行环境",
    "F09": "F09 扩展、权限与生命周期", "F10": "F10 协作、云契约与配置",
    "X": "X 内部原语", "T": "T 测试基座",
}

# ---------------- complement: 151 uncovered DSH workspaces ----------------
# (manifest, code, detail, dsh_behavior, atlas_behavior, atlas_evidence, verdict, action, prio, note)
M = []
def add(*row): M.append(row)

add("apps/plugin-market-generator/package.json","F09","插件市场索引生成器","从 npm 包与 Git 仓库清单生成市场索引（图标、安装参数、校验）","Atlas 有技能市场索引与插件市场工具；未定位按 npm/Git 清单离线生成索引的参考实现","core/atlas/skills/market.py; core/atlas/tools/plugin_marketplace.py","部分","在 skills/market.py 增离线索引生成入口，复用现有校验","P2","清单+入口静态")
add("packages/account/deepseek-account/package.json","F06","DeepSeek 账户登录与凭据","浏览器审批登录；账户凭据与通知管理；审批不绕过本地取消","Atlas 有模型凭据库与通知适配，未见 DeepSeek 账户登录流程","core/atlas/models/credentials.py; core/atlas/notifications/","部分","在凭据库之上增加账户登录/刷新入口并明确取消语义","P1","master 新增；静态")
add("packages/account/deepseek-auth/package.json","F06","请求鉴权选择（API key / 账户签名）","按连接类型选择 API key 或账户签名，错误码分类","Atlas 模型通道走 API key；账户签名路径未定位","core/atlas/models/credentials.py; core/atlas/models/router.py","部分","在模型凭据解析处增加 account 连接类型与错误分类","P1","master 新增；静态")
add("packages/api/remotes/package.json","F04","远程 BFF 能力装配","按应用选择 Host 能力并组装 Remote BFF","Atlas 有 remote_access、remote_router 与能力探针","core/atlas/remote_access.py; core/atlas/api/remote_router.py","部分","对齐能力选择与方法级暴露","P2","静态")
add("packages/boot/hmr/package.json","F09","模块与 profile 配置热重载","串行化模块/配置重载并协调待挂载模块","Atlas 未见热重载；插件补丁层为静态应用","core/atlas/plugins/patch_layer.py","缺失","新增 HMR 控制器；若不做需在文档明确不支持","P2","静态检索无热重载实现")
add("packages/computer-use/computer-use/package.json","F02","计算机使用能力注册","独占命名注册 computer-use provider","Atlas 有 computer_use 工具与 CUA 后端","core/atlas/tools/computer_use.py; core/atlas/capabilities/computer/cua_backend.py","候选对应","核对 provider 独占注册与冲突错误","P1","静态")
add("packages/connector/cli-account/package.json","F09","第三方 CLI 账户","插件注册第三方 CLI 与其账户，Host 集中管理","Atlas 有插件运行时与 MCP 客户端，未见 CLI 账户注册契约","core/atlas/plugins/runtime.py; core/atlas/tools/mcp_client.py","部分","在 plugins/runtime 增加 CLI 账户注册表","P2","master 新增；静态")
add("packages/connector/linear/package.json","F09","Linear hosted MCP 集成","固定 Linear MCP 端点，经共享 MCP manager 授权","Atlas 有 Linear 集成路由与 MCP 管理器","core/atlas/api/linear_integration_router.py; core/atlas/tools/mcp_client.py","部分","核对 hosted MCP 授权/工具加载与 Atlas 直连实现的差异","P2","master 新增；静态")
add("packages/connector/notion/package.json","F09","Notion MCP 集成","固定 Notion MCP 端点，经共享 MCP manager 授权","Atlas 有通用 MCP 客户端，未见 Notion 专用注册","core/atlas/tools/mcp_client.py","部分","用通用 MCP 配置注册 Notion，或补专用连接器","P3","master 新增；静态")
add("packages/connector/upstream-skills/package.json","F09","上游技能目录注册","CLI 插件注册入口技能并固定上游目录","Atlas 有技能获取与生命周期管理","core/atlas/skills/acquisition.py; core/atlas/skills/lifecycle.py","候选对应","核对固定目录与版本锁定语义","P2","master 新增；静态")
add("packages/context/file-reference-local/package.json","F06","本地文件引用索引","有界模糊索引，支持 @file 发现","Atlas 有 @file 语法与文件拖放，独立索引服务未定位","core/atlas/engine/kernel/context.py; frontend/src/renderer/services/fileDrop.ts","部分","补有界模糊索引与检索预算","P2","静态")
add("packages/context/file-reference/package.json","F06","文件引用契约与 @file 语法","共享 @file 语法与发现契约","Atlas 内核上下文已解析 @file","core/atlas/engine/kernel/context.py","候选对应","核对语法边界与解析失败行为","P2","静态")
add("packages/context/harness-dev-context/package.json","F06","开发环境上下文注入","注入 checkout 路径与 Web GUI URL，不随环境变化","Atlas 有项目上下文与指令注入，未见同类开发上下文","core/atlas/project_context.py; core/atlas/agent/project_instructions.py","部分","如需，增加稳定的开发上下文段","P3","静态")
add("packages/core/agent-tool-presentation/package.json","F05","工具呈现选择器（已弃用）","按挂载范围为 agent 选择内置工具执行呈现","Atlas 有 presentation.py 与 tool_node 呈现逻辑","core/atlas/agent/presentation.py; core/atlas/agent/tool_node.py","部分","无需新增；核对呈现选择覆盖度","P3","DSH 包已标记 deprecated")
add("packages/core/scope/package.json","F05","作用域注册原语","scope 标签与按 scope 过滤的事件分发","Atlas 有 secret/terminal scope 与 capability bus，无统一 scope 原语","core/atlas/engine/agent/secret_scope.py; core/atlas/tools/terminal_scope.py; core/atlas/runtime/capability_bus.py","部分","若插件隔离需要，抽统一 scope 原语","P2","静态")
add("packages/credentials/authorization/package.json","F09","插件授权流","插件拥有凭据获取流程，统一会话与错误分类","Atlas 有 MCP OAuth 与渠道凭据桥","core/atlas/tools/mcp_oauth.py; core/atlas/channels/credentials.py","部分","对齐统一授权会话与拒绝错误","P2","静态")
add("packages/document/tool-office/package.json","F08","模型侧 Office 工具","文档渲染、转换、重算","Atlas 有 office.py、libreoffice.py 与 office 路由","core/atlas/office.py; core/atlas/libreoffice.py; core/atlas/api/office_router.py","候选对应","逐项核对 docx/pptx/xlsx 渲染、转换、重算","P1","静态")
add("packages/experimental/action-cards/package.json","F03","答案下方动作卡","卡片状态、用户动作、状态提示","Atlas 有结构化组件与消息动作，未见统一 action-card 框架","core/atlas/tools/structured_components.py; frontend/src/renderer/components/","部分","评估用结构化组件承载动作卡","P2","静态")
add("packages/experimental/badge-skill-bundle/package.json","F09","dsh 徽章技能","让 agent 在文档/PR 加 powered by dsh 徽章","Atlas 无对应，属品牌营销","","缺失","不实现；记录为非产品需求","P3","DSH 品牌运营")
add("packages/experimental/browser-use-chrome-devtools-mcp/package.json","F08","Chrome DevTools MCP 浏览器工具","每会话 Chromium 检查/自动化，固定 MCP 服务器","Atlas 有 browser_use 兼容层与 CLI 后端","core/atlas/engine/tools/browser_use_cli.py; core/atlas/tools/browser_use_compat.py","部分","核对 CDP 能力面与固定版本","P2","experimental；静态")
add("packages/experimental/browser-use-playwright-mcp/package.json","F08","Playwright MCP 浏览器工具","固定 Playwright MCP 的 Chromium 工具","Atlas 有 browser_use 兼容层，执行后端不同","core/atlas/tools/browser_use_compat.py; core/atlas/capabilities/browser/browser_use.py","部分","核对 Playwright 专有能力（网络/多页/追踪）","P2","experimental；静态")
add("packages/experimental/browser-use-stagehand-native/package.json","F08","Stagehand 原生浏览器工具","独立原生模型驱动的 Stagehand 工具","Atlas 未定位 Stagehand 集成","core/atlas/tools/browser_use_compat.py","缺失","评估 Stagehand 集成价值后再做","P3","experimental；静态检索无命中")
add("packages/experimental/client-ui-action-cards/package.json","F03","动作卡 UI 框架","答案下方共享卡框、种类主体、隐藏层","Atlas 有消息动作与结构化组件，无同款卡框","frontend/src/renderer/components/; core/atlas/tools/structured_components.py","部分","若采用动作卡，统一卡框与状态层","P2","experimental；静态")
add("packages/experimental/client-ui-claude-code-mods/package.json","F03","Claude Code mods 条","prompt 上方显示每会话 mod 树并发送按钮事件","Atlas 有 Claude 后端，未见该 UI 条","core/atlas/agents/backends/claude.py","缺失","新增 mods 树 UI 与事件桥","P2","experimental；静态")
add("packages/experimental/client-ui-cot-translation/package.json","F03","推理内容翻译","展开推理的机器翻译，保留原文","Atlas 有 ReasoningBlock，无翻译层","frontend/src/renderer/components/ReasoningBlock.tsx; core/atlas/models/reasoning_stages.py","缺失","新增翻译开关与缓存层","P2","experimental；静态")
add("packages/experimental/client-ui-creation-recommendations/package.json","F03","个性化页面创建卡","位置选择、创建进度、撤销与恢复","Atlas 有 CreatePage，无创建推荐卡","frontend/src/renderer/pages/CreatePage.tsx","部分","如产品需要，在 CreatePage 增加推荐卡","P3","experimental；静态")
add("packages/experimental/client-ui-plugin-recommendations/package.json","F03","官方插件推荐卡","目录文案与一键启用","Atlas 有扩展目录面板","frontend/src/renderer/components/settings/ExtensionCatalogPanel.tsx","部分","在扩展目录增加推荐位","P2","experimental；静态")
add("packages/experimental/client-ui-stats/package.json","F03","每轮/步成本统计表","上下文、耗时、缓存、工具成本表","Atlas 有 usage、ConversationActivity、context_breakdown","core/atlas/usage.py; frontend/src/renderer/components/ConversationActivity.tsx; core/atlas/engine/agent/context_breakdown.py","部分","补齐缓存/工具成本列","P2","experimental；静态")
add("packages/experimental/computer-use-cua-driver-mcp/package.json","F02","Cua Driver MCP 计算机使用","经已安装 Cua Driver MCP 可执行文件独占计算机使用","Atlas 有 CUA 后端","core/atlas/capabilities/computer/cua_backend.py; core/atlas/tools/computer_use.py","候选对应","核对 MCP 载体与独占注册","P2","experimental；静态")
add("packages/experimental/computer-use-cua-driver-native/package.json","F02","Cua Driver 原生计算机使用","进程内 Cua Driver 原生 SDK","Atlas 有 CUA 后端","core/atlas/capabilities/computer/cua_backend.py","候选对应","核对原生 SDK 与工具集","P2","experimental；静态")
add("packages/experimental/cot-translation-bundle/package.json","F06","推理翻译组合","可选推理翻译的组合层","Atlas 未见翻译能力","","缺失","随 client-ui-cot-translation 一起实现","P2","experimental；静态")
add("packages/experimental/creation-recommendations/package.json","F09","从需求创建持久插件","明确会话需求转化为可独立安装/移除的插件","Atlas 有插件运行时与创建页，未见自动生成插件","core/atlas/plugins/runtime.py; frontend/src/renderer/pages/CreatePage.tsx","部分","补生成→安装→撤销闭环","P2","experimental；静态")
add("packages/experimental/cua-bundle/package.json","F02","可选 Computer Use 组合","macOS/Windows Computer Use 组合层","Atlas 有 computer_use 与 CUA 后端","core/atlas/tools/computer_use.py","部分","核对平台覆盖","P2","experimental；静态")
add("packages/experimental/cua-windows/package.json","F02","Windows C# computer use","共享应用/窗口对象的 Windows C# provider","Atlas cua_backend 的平台实现待核","core/atlas/capabilities/computer/cua_backend.py; core/atlas/tools/x2/computer.py","部分","核对 Windows 原生 provider 是否等价","P2","master 新增；静态")
add("packages/experimental/forge-bundle/package.json","F10","变更请求面板与 worktree","会话内变更请求面板、worktree 选项","Atlas 有 ChangesPanel、review、worktree 支持","frontend/src/renderer/shell/panels/ChangesPanel.tsx; core/atlas/review/","部分","核对变更请求→worktree 闭环","P2","experimental；静态")
add("packages/experimental/forge-session/package.json","F10","变更请求绑定会话","把变更请求绑定到创建/推送/跟踪它的会话","Atlas 有 PR 自动化与工作流","core/atlas/pr_automation.py; core/atlas/github_workflows.py","部分","补会话 ↔ 变更请求关联","P2","experimental；静态")
add("packages/experimental/inspector-profile/package.json","F03","原始会话日志与节点检查","原始日志/聊天节点检查的 Web bundle","Atlas 有 run_replay 与 Inspector","core/atlas/run_replay/; frontend/src/renderer/shell/Inspector.tsx","部分","核对节点级检查深度","P2","experimental；静态")
add("packages/experimental/personalized-recommendations/package.json","F03","个性化推荐组合","个性化页面与内置插件推荐卡","Atlas 有建议安全模块，无推荐卡组合","core/atlas/suggestions_safety.py","部分","如产品需要再做","P3","experimental；静态")
add("packages/experimental/plugin-market-bundle/package.json","F09","自定义插件索引 Discover","浏览并安装自定义插件索引中的 bundle","Atlas 有技能市场与扩展目录","core/atlas/skills/market.py; frontend/src/renderer/components/settings/ExtensionCatalogPanel.tsx","部分","补自定义索引来源","P2","experimental；静态")
add("packages/experimental/plugin-recommendations/package.json","F09","官方插件建议","显式需求触发推荐，用户显式启用，决策持久化","Atlas 有扩展目录，无推荐决策模型","frontend/src/renderer/components/settings/ExtensionCatalogPanel.tsx","部分","补推荐决策与持久化","P2","experimental；静态")
add("packages/experimental/ralph-bundle/package.json","F05","Ralph 重复任务循环","按显式请求用全新 agent 重复执行","Atlas 有 ralph_loop.py","core/atlas/agent/ralph_loop.py","候选对应","核对全新 agent 隔离与停止条件","P1","experimental；静态")
add("packages/experimental/skill-badge/package.json","F09","dsh 徽章技能提供者","内置 dsh-badge 技能","Atlas 无对应","","缺失","不实现","P3","品牌运营")
add("packages/experimental/speech-to-text-sensevoice/package.json","F06","本地 SenseVoice 转写","本地 ONNX 转写，托管 sherpa-onnx 进程","Atlas 有 asr.py，异步/本地引擎待核","core/atlas/asr.py","部分","核对本地模型与进程托管","P1","experimental；静态")
add("packages/experimental/subagent-oar/package.json","F05","OAR 一次性子代理","经 OAR 默认运行时注册一次性子代理","Atlas 有子代理与多后端","core/atlas/engine/kernel/subagents.py; core/atlas/agents/backends/","部分","补 OAR 适配或明确不支持","P2","experimental；静态")
add("packages/experimental/terminal-bundle/package.json","F08","持久终端组合","侧栏可观察的长驻终端","Atlas 有 TerminalPanel 与 persistent_agents","frontend/src/renderer/shell/panels/TerminalPanel.tsx; core/atlas/persistent_agents/store.py","候选对应","核对长驻/重启恢复","P1","experimental；静态")
add("packages/experimental/terminal-panel/package.json","F08","侧栏持久终端面板","Agent 持久终端与用户终端只读访问","Atlas 有 TerminalPanel 与 terminal_env_registry","frontend/src/renderer/shell/panels/TerminalPanel.tsx; core/atlas/engine/agent/terminal_env_registry.py","候选对应","核对用户终端只读接入","P1","experimental；静态")
add("packages/experimental/translator/package.json","F06","匿名文本翻译","机器翻译，可选持久化的与会话无关结果","Atlas 未定位翻译能力","","缺失","新增翻译服务与结果缓存","P2","experimental；静态检索无命中")
add("packages/experimental/voice-input-bundle/package.json","F06","本地语音输入","本地 SenseVoice 语音输入，首次使用下载运行时","Atlas 有 asr.py 与语音相关模块，UI 接入待核","core/atlas/asr.py","部分","核对首次下载与语音输入入口","P2","experimental；静态")
add("packages/experimental/webworker-packer/package.json","F01","浏览器运行时 VFS 打包器","构建期打包 base VFS 与有序数据覆盖层","Atlas 未见 WebWorker/VFS 打包","","缺失","若引入浏览器运行时再实现","P3","experimental；构建工具")
add("packages/extensions/ui-cordis/package.json","F09","Cordis 动态插件定义卡","cordis_define 工具行与运行/停止开关","Atlas 有工作流定义与插件 UI，无 Cordis 卡","core/atlas/workflow/definition.py","部分","如支持动态插件，补定义卡","P2","静态")
add("packages/feedback/message-feedback/package.json","F07","消息评分与备注","最终 assistant 消息的评分/备注写入会话日志","Atlas 有消息元数据与消息组件，未见评分存储","core/atlas/engine/agent/message_metadata.py; frontend/src/renderer/components/ConversationMessage.tsx","部分","补评分事件与持久化","P2","静态")
add("packages/fs/fs-local/package.json","F08","本地文件系统实现","真实路径身份、原子变更的文件系统实现","Atlas 有工作区文件工具与查询","core/atlas/tools/workspace_queries.py; core/atlas/engine/tools/","部分","按需抽文件系统缝","P2","静态")
add("packages/fs/fs-observation-policy/package.json","F08","读前观测与版本守卫","按上下文的已观测状态、读前编辑、版本守卫","Atlas 工具策略中可能有等价守卫，未逐条核","core/atlas/agent/tool_node.py; core/atlas/engine/state/","部分","核对读前编辑与并发版本冲突处理","P1","静态")
add("packages/fs/fs-patch/package.json","F08","Codex 风格补丁解析","纯补丁解析与 LF 文本应用，结构化失配","Atlas 有补丁层与 Codex 后端","core/atlas/plugins/patch_layer.py; core/atlas/agents/backends/codex.py","候选对应","核对失配错误结构","P1","静态")
add("packages/fs/fs-sandbox/package.json","F08","沙箱文件系统","按沙箱策略限制写/编辑","Atlas 有 sandbox 与 windows_job_sandbox","core/atlas/sandbox.py; core/atlas/windows_job_sandbox.py","部分","补齐文件系统层强制（当前 Job Object 不控 ACL）","P0","静态；安全相关")
add("packages/fs/fs/package.json","F08","文件系统抽象缝","ctx.fs 词汇类型与实现契约","Atlas 直接使用工作区工具，无统一 fs 缝","core/atlas/tools/workspace_queries.py","设计差异","不强制抽象；按需保留","P3","架构差异")
add("packages/goal/command-goal/package.json","F05","/goal 命令","同会话持久目标的斜杠命令","Atlas 有 goal_command.py","core/atlas/engine/goal_command.py","候选对应","核对命令语法与恢复","P1","静态")
add("packages/goal/goal-round-driver/package.json","F05","同会话 goal 轮次驱动","竞争防护的 goal-round 驱动","Atlas 有 goal_loop.py","core/atlas/engine/goal_loop.py","候选对应","核对轮次竞争与停止","P1","静态")
add("packages/goal/goal/package.json","F05","事件溯源 goal 状态","事件溯源状态、CAS 变更、投影","Atlas 有 engine/goals.py 与 introspect 投影","core/atlas/engine/goals.py; core/atlas/introspect/providers/goals.py","候选对应","核对事件模型与 CAS","P1","静态")
add("packages/guard/timeout-policy/package.json","F05","工具调用超时策略","per-tool 截止时间装入 exec.signal","Atlas 有 deadline.py","core/atlas/engine/agent/deadline.py","候选对应","核对按工具覆写","P1","静态")
add("packages/host/authentication-desktop/package.json","F02","桌面私有凭据校验","桌面私有连接凭据校验器","Atlas 有桌面入口与网关服务，私有通道鉴权待核","core/atlas/desktop_entry.py; core/atlas/gateway_service.py","部分","核对桌面私有通道鉴权","P1","master 新增；静态")
add("packages/host/directory-picker-auto/package.json","F02","目录选择器自适应","按宿主情况选择原生或浏览后端","Electron 已有 showOpenDialog 路径","frontend/src/main/electron.ts","部分","核对原生/浏览自动选择","P2","静态")
add("packages/host/directory-picker-browse/package.json","F02","应用内目录浏览","应用内浏览/创建原语","Atlas 有工作区路由与选择对话框","core/atlas/api/workspace_router.py; frontend/src/renderer/components/ResumePickerDialog.tsx","部分","核对应用内浏览能力","P2","静态")
add("packages/host/directory-picker-native/package.json","F02","原生目录选择","宿主原生目录选择实现","Electron showOpenDialog","frontend/src/main/electron.ts","候选对应","核对返回值契约","P2","静态")
add("packages/host/directory-picker/package.json","F02","目录选择抽象缝","workspace 目录选择 seam","Atlas 直接调用 Electron，无 seam","frontend/src/main/electron.ts","设计差异","不强制抽象","P3","架构差异")
add("packages/host/frontend-static/package.json","F02","SPA dist 静态服务","Web shell 的静态入口回退","Atlas 由 Electron 直接加载 dist","frontend/src/main/electron.ts","设计差异","无需补齐","P3","架构差异")
add("packages/host/open-in-app/package.json","F02","应用目录/图标/启动端点","解析应用目录、图标与启动端点","Atlas 有 openExternal 与 shell_aliases","frontend/src/main/electron.ts; core/atlas/shell_aliases.py","部分","核对应用目录与图标","P2","静态")
add("packages/host/plugin-inventory/package.json","F09","插件状态只读投影","当前 Loader 插件状态投影","Atlas 有插件运行时与投影，无同款只读 Remote 投影","core/atlas/plugins/runtime.py; core/atlas/engine/state/projections.py","部分","补插件状态投影接口","P2","静态")
add("packages/host/product-telemetry-otel/package.json","F10","产品遥测 OTel 导出","显式产品事件经 OTel HTTP 日志导出","Atlas 有 telemetry.py，导出协议待核","core/atlas/telemetry.py","部分","核对 OTel 导出与事件白名单","P2","静态")
add("packages/host/webserver/package.json","F04","HTTP/upgrade 路由注册","Web 路由注册、索引变换、静态目录","Atlas 用 FastAPI + ws_protocol","core/atlas/server.py; core/atlas/api/ws_protocol.py","设计差异","无需补齐","P3","架构差异")
add("packages/identity/anonymous-user-id/package.json","F10","匿名用户 ID","home 级随机 UUID，用于遥测/反馈关联","Atlas 未见匿名 ID","","缺失","新增匿名 ID 与遥测关联","P2","静态检索无命中")
add("packages/interaction/commands/package.json","F05","人类命令注册表","插件拥有的命令注册表，供 UI 适配器共享","Atlas 有 runtime/commands.py 与 slashCommands","core/atlas/runtime/commands.py; frontend/src/renderer/services/slashCommands.ts","候选对应","核对命令来源与冲突","P1","静态")
add("packages/interaction/user-approval/package.json","F09","用户审批缝","一次性权限决策，策略覆盖","Atlas 有 approval_policy 与 approval_outcome","core/atlas/approval_policy.py; core/atlas/approval_outcome.py","候选对应","核对策略继承与子代理覆盖","P1","静态")
add("packages/interaction/user-questions/package.json","F05","运行时向用户提问","agent 运行中向人类提问，带超时","Atlas 有 ask_user 工具","core/atlas/agent/tool_catalog.py; core/atlas/agent/tool_node.py","候选对应","核对超时与取消","P1","静态")
add("packages/mcp/mcp-account/package.json","F09","MCP 连接器账户","Plugins 页的连接器 OAuth 账户","Atlas 有 mcp_oauth 与 MCP 面板","core/atlas/tools/mcp_oauth.py; frontend/src/renderer/components/settings/McpServersPanel.tsx","候选对应","核对外部账户与刷新","P1","master 新增；静态")
add("packages/plan/plan-mode/package.json","F05","计划模式","日志化的 per-agent 计划模式、直接命令、审查后退出","Atlas 有 planning.py 与 plan_prompt","core/atlas/agent/planning.py; core/atlas/engine/kernel/toolkit/plan_prompt.py","候选对应","核对退出条件与写文件限制","P1","静态")
add("packages/preset/persona/package.json","F06","部署人设段","组合式部署人设注入","Atlas 有系统提示组装，人设配置待核","core/atlas/engine/kernel/prompt.py; core/atlas/agent/presentation.py","部分","核对人设注入点","P2","静态")
add("packages/sandbox/sandbox-local/package.json","F08","本地进程沙箱","bwrap/landlock 等本地沙箱后端","Atlas 有 sandbox.py","core/atlas/sandbox.py","部分","核对 Linux 后端覆盖","P1","静态")
add("packages/sandbox/sandbox-windows-acl/package.json","F08","Windows ACL 写限制沙箱","受限令牌 + capability SID 写允许","Atlas 明确使用 Job Object，注释承认无法强制 ACL","core/atlas/windows_job_sandbox.py; core/atlas/sandbox.py","缺失","实现受限令牌/ACL 写限制后端","P0","安全缺口；源码注释为证")
add("packages/session-query/session-query-sqlite/package.json","F07","SQLite FTS5 会话检索","基于 SQLite FTS5 的会话查询后端","Atlas 有 atlas_state_search.py","core/atlas/engine/state/atlas_state_search.py","候选对应","核对 FTS5 与分页","P1","静态")
add("packages/session/message-quotes/package.json","F03","选中文本引用","选中文本引用为 Markdown 引用块","Atlas 前端已有选中→引用到输入框","frontend/src/renderer/App.tsx","部分","核对多段/取消/纯文本边界","P2","静态")
add("packages/session/session-projection-cache/package.json","F07","持久投影缓存","每会话检查点记录持久化","Atlas 有 session_projections 与 run_checkpoints","core/atlas/session_projections.py; core/atlas/run_checkpoints.py","候选对应","核对外置持久化与失效","P1","静态")
add("packages/session/session-telemetry-otel/package.json","F10","会话日志遥测","反馈授权的会话日志，字节有界 OTel","Atlas 有 session_telemetry.py","core/atlas/session_telemetry.py","部分","核对授权门与大小边界","P2","静态")
add("packages/session/session-turn-outline/package.json","F07","轮次大纲投影","整日志的轮次大纲","Atlas 有 projections 与 timelineProjection","core/atlas/engine/state/projections.py; frontend/src/renderer/components/timelineProjection.ts","部分","补齐大纲投影","P2","静态")
add("packages/settings/settings/package.json","F10","设置 schema 投影与表单编辑","对 Cordis profile patch 的设置描述/表单编辑","Atlas 有 config.py 与多设置路由","core/atlas/config.py; core/atlas/api/","部分","核对 schema 驱动的表单编辑","P1","静态")
add("packages/shell/bash-local/package.json","F08","本地 bash 执行器","本地子进程 bash 执行","Atlas 有 local_execution 与 exec","core/atlas/tools/local_execution.py; core/atlas/engine/kernel/exec.py","候选对应","核对超时/信号/编码","P1","静态")
add("packages/shell/pwsh-local/package.json","F08","本地 PowerShell 执行器","本地 PowerShell 执行","Atlas local_execution 含 PowerShell 分支，待逐项核","core/atlas/tools/local_execution.py","部分","核对编码前导/参数","P1","静态")
add("packages/shell/pwsh-sandbox/package.json","F08","沙箱 PowerShell 执行器","沙箱模式下执行 pwsh","Atlas 有 sandbox 与 PowerShell 分支","core/atlas/sandbox.py; core/atlas/tools/local_execution.py","部分","核对沙箱覆盖","P1","静态")
add("packages/shell/shell-env/package.json","F08","托管 shell 环境注册表","工具无关的 DSH_* 环境注册","Atlas 有环境策略与执行环境","core/atlas/engine/tools/environments/local_env_policy.py","部分","按需抽注册表","P2","静态")
add("packages/shell/shell/package.json","F08","shell 执行 abstract 缝","ctx.shell 执行契约","Atlas 直接调用本地执行","core/atlas/tools/local_execution.py","设计差异","不强制抽象","P3","架构差异")
add("packages/shell/tool-bash-persistent/package.json","F08","持久 bash 工具","owner 作用域的持久 bash over PTY","Atlas 有终端工具与 persistent_agents","core/atlas/engine/agent/terminal_env_registry.py; core/atlas/persistent_agents/store.py","部分","核对 owner 隔离与恢复","P1","静态")
add("packages/shell/tool-pwsh-persistent/package.json","F08","持久 PowerShell 工具","owner 作用域的持久 pwsh over PTY","Atlas 的 pwsh 持久路径待核","core/atlas/persistent_agents/store.py; core/atlas/tools/local_execution.py","部分","补持久 pwsh 或明确不支持","P1","静态")
add("packages/shell/tool-pwsh/package.json","F08","pwsh 工具","模型侧 pwsh 工具","Atlas local_execution 的 PowerShell 分支","core/atlas/tools/local_execution.py","部分","核对工具暴露名与参数","P1","静态")
add("packages/skill/skill-office/package.json","F09","Office 工作流技能","内置 Word/PPT/Excel 工作流与操作指引","Atlas 有 office 与技能系统","core/atlas/office.py; core/atlas/skills/","候选对应","核对技能内容与文件操作","P1","静态")
add("packages/skill/tool-workspace-dependencies/package.json","F08","工作区依赖查询工具","内置 Python/Node/pnpm payload 的绝对路径查询","Atlas 有 node_runtime 与执行环境","core/atlas/tools/node_runtime.py; core/atlas/engine/tools/environments/","部分","核对 payload 与路径解析","P2","静态")
add("packages/spill/spill-local/package.json","F07","本地 spill 存储","私有会话作用域文件存储","Atlas 有 spill_store.py","core/atlas/spill_store.py","候选对应","核对清理周期与权限","P1","静态")
add("packages/spill/spill-policy/package.json","F07","令牌预算结果保留","超限工具结果保留与可恢复文本/图片路径","Atlas 有 spill_store 与 token_meter","core/atlas/spill_store.py; core/atlas/engine/agent/token_meter.py","候选对应","核对预算与图片卸载","P1","静态")
add("packages/spill/spill/package.json","F07","spill 存储抽象缝","超大工具文本/图片保存契约","Atlas 有 spill_store","core/atlas/spill_store.py","候选对应","核对接口边界","P1","静态")
add("packages/ssh/fs-ssh/package.json","F08","SSH 文件系统","经共享 POSIX SSH helper 的文件系统","Atlas 有 ssh.py 与 SSH 执行环境","core/atlas/ssh.py; core/atlas/engine/tools/environments/ssh.py","部分","核对远程原子变更","P1","静态")
add("packages/ssh/sandbox-ssh/package.json","F08","远程沙箱 argv","在 SSH 主机上选择并应用沙箱","Atlas SSH 环境与 sandbox 分离","core/atlas/ssh.py; core/atlas/sandbox.py","部分","核对远程沙箱参数","P1","静态")
add("packages/ssh/ssh-helper-runtime/package.json","F08","SSH helper 运行时载体","私有 SEA 调度器与托管 worker","Atlas 无同款 SEA 载体","core/atlas/ssh.py","部分","若需版本匹配 helper，再实现","P2","静态")
add("packages/ssh/ssh/package.json","F08","OpenSSH 连接与 POSIX helper","单连接所有权、版本匹配 helper、独立流","Atlas 有 ssh.py","core/atlas/ssh.py","候选对应","核对连接复用与版本协商","P1","静态")
add("packages/ssh/subprocess-ssh/package.json","F08","远程子进程/PTY","独立 SSH 流的远程子进程与 PTY","Atlas 有 SSH 执行环境","core/atlas/engine/tools/environments/ssh.py","部分","核对 PTY 与取消","P1","静态")
add("packages/storage/storage-domain/package.json","F07","事件化 schema KV 域","schema 校验、事件发射的 KV 域","Atlas 有状态 schema/registry","core/atlas/engine/state/atlas_state_schema.py; core/atlas/engine/state/atlas_state_registry.py","部分","核对事件发射与迁移","P2","静态")
add("packages/subagent/subagent-claude-code/package.json","F05","Claude Code 子代理","官方 Agent SDK 的一次性子代理","Atlas 有 Claude 后端与子代理内核","core/atlas/agents/backends/claude.py; core/atlas/engine/kernel/subagents.py","候选对应","核对一次性语义与权限","P1","静态")
add("packages/subagent/subagent-codex/package.json","F05","Codex 子代理","官方 app-server 协议的一次性子代理","Atlas 有 Codex 后端与 app_server","core/atlas/agents/backends/codex.py; core/atlas/tools/app_server.py","候选对应","核对协议版本与进程释放","P1","静态")
add("packages/subagent/subagent-dsh-sdk/package.json","F05","子进程 SDK 子代理","stdio JSON 驱动子 DSH 运行时","Atlas 有外部进程与后端宿主","core/atlas/runtime/external_process.py; core/atlas/runtime/backends.py","部分","核对 stdio 协议","P2","静态")
add("packages/subagent/subagent-fork-in-process/package.json","F05","进程内 fork 子代理","以父日志前缀播种的子 agent","Atlas 有子代理工作树/容量控制","core/atlas/agent/subagent_worktree.py; core/atlas/agent/subagent_capacity.py","部分","核对前缀播种语义","P1","静态")
add("packages/subagent/subagent-spawn-in-process/package.json","F05","进程内 spawn 子代理","在 ctx.agents 上新建子 agent","Atlas 有 kernel/subagents","core/atlas/engine/kernel/subagents.py","候选对应","核对隔离与回收","P1","静态")
add("packages/subagent/tool-subagent-control/package.json","F05","子代理控制工具","消息、中断、子发现工具","Atlas 有子代理内核与 mailbox","core/atlas/engine/kernel/subagents.py; core/atlas/agent/mailbox.py","部分","补齐消息/中断/发现工具面","P1","静态")
add("packages/subprocess/win32-process/package.json","F08","Win32 进程/Job Object 原语","共享 Win32 进程、stdio、Job Object","Atlas 有 windows_job_sandbox","core/atlas/windows_job_sandbox.py","候选对应","核对原语覆盖","P2","静态")
add("packages/team/tool-agent-team/package.json","F10","Agent Teams 任务板工具","条件可用的任务板工具与指引","Atlas 有 Teams roster（注释即 DSH listMembers parity）、kanban、groups","core/atlas/agent/enrichment.py; core/atlas/kanban.py; core/atlas/groups/","部分","补齐 Teams 工具面并核对 roster 契约","P1","静态")
add("packages/terminal/terminal-bash/package.json","F08","持久 bash PTY 后端","基于子进程终端原语的持久 shell","Atlas 有终端注册表与面板","core/atlas/engine/agent/terminal_env_registry.py; frontend/src/renderer/shell/panels/TerminalPanel.tsx","部分","核对 PTY 复用/清理","P1","静态")
add("packages/terminal/terminal/package.json","F08","持久 PTY 注册表","owner 作用域 PTY 注册与后端注册","Atlas 有 terminal_env_registry","core/atlas/engine/agent/terminal_env_registry.py","候选对应","核对 owner 作用域","P1","静态")
add("packages/test-support/agent-loop-testkit/package.json","T","Agent 循环测试基座","生产 AgentLoop 驱动与 Inbox stub","Atlas 有测试夹具但无同款产品级 driver","core/tests/","非产品面","不实现；测试基建可借鉴","P3","test-support")
add("packages/test-support/client-runtime/package.json","T","客户端测试运行时","jsdom slot bench 与会话/工作区替身","Atlas 前端测试自有运行时","frontend/src/renderer/*.test.tsx","非产品面","不实现","P3","test-support")
add("packages/test-support/llm-mock-server/package.json","T","LLM 故障 mock 服务器","可脚本化的 HTTP/SSE 故障注入","Atlas fake_llm_provider 已覆盖部分","core/tests/fakes/fake_llm_provider.py","非产品面","可按需补 SSE 故障注入","P3","test-support")
add("packages/test-support/llm-replay/package.json","T","LLM 回放插件","从录制会话重建模型分块","Atlas 有 run_replay","core/atlas/run_replay/","非产品面","已另有实现；核对回放精度","P3","test-support")
add("packages/test-support/loader-smoke/package.json","T","Loader 冒烟测试","无密钥真实 Loader 示例冒烟","Atlas 无同名基座","core/tests/","非产品面","不实现","P3","test-support")
add("packages/test-support/remote-mock/package.json","T","Remote 流量 mock","按端点命名的 unary/stream mock","Atlas 有远程 mock 能力待核","core/tests/","非产品面","不实现","P3","test-support")
add("packages/test-support/session-snapshot/package.json","T","会话快照核心","ACP 适配与期望输出归一化","Atlas 无同名基座","core/tests/","非产品面","不实现","P3","test-support")
add("packages/test-support/tool-testkit/package.json","T","工具测试夹具","工具定义/执行夹具","Atlas 有工具测试","core/tests/","非产品面","不实现","P3","test-support")
add("packages/todo/tool-todo/package.json","F05","todo_write 工具","模型侧 todo 写入，落事件溯源会话日志","Atlas 有 todo_tool 与 todo_state","core/atlas/engine/tools/todo_tool.py; core/atlas/agent/todo_state.py","候选对应","核对状态迁移与恢复","P1","静态")
add("packages/typert/generator/package.json","F04","Typert 代码生成器","TypeScript 项目分析 + 模型驱动产物生成","Atlas 的 ws_protocol 为手写描述，无代码生成","core/atlas/api/ws_protocol.py","缺失","评估生成式协议描述的必要性","P2","静态检索无 typert")
add("packages/typert/loader/package.json","F04","Typert 加载集成","Loader 集成生成的 Typert 贡献","Atlas 无对应","","缺失","随 generator 一起评估","P2","静态")
add("packages/typert/protocol/package.json","F04","Typert Remote 协议","编译无关的 Remote 元数据与提供者协议","Atlas 有 ws_protocol 描述","core/atlas/api/ws_protocol.py","部分","核对帧描述与版本化","P2","静态")
add("packages/typert/registry/package.json","F04","Typert 运行时注册表","生成包反射与 Zod schema 注册","Atlas 无对应","","缺失","随 generator 一起评估","P2","静态")
add("packages/util/atomic-write/package.json","X","原子写原语","独占临时文件 + 重命名，保留权限","Atlas 状态库有原子写，未抽公共原语","core/atlas/engine/state/atlas_state_dbfile.py","部分","抽 atomic_write 适配器供插件使用","P3","内部原语")
add("packages/util/brand/package.json","X","品牌类型原语","编译期品牌类型","Atlas 用 Python，无对应","","缺失","不实现","P3","类型层")
add("packages/util/chunked-list/package.json","X","分块持久列表","有界复制的追加式分块列表","Atlas 有检查点/持久代","core/atlas/run_checkpoints.py; core/atlas/agent/checkpoints.py","部分","按需借鉴","P3","内部原语")
add("packages/util/code-language/package.json","X","扩展名→语言映射","代码高亮语言表","Atlas CodeBlock 自有映射","frontend/src/renderer/components/message-actions/CodeBlock.tsx","部分","核对扩展名覆盖","P3","内部原语")
add("packages/util/crypto/package.json","X","UUID/字节编码","浏览器安全 UUID 与编码","Atlas 用标准库","","缺失","不实现","P3","内部原语")
add("packages/util/deque/package.json","X","环形双端队列","摊销常数端操作","Atlas 用标准库","","缺失","不实现","P3","内部原语")
add("packages/util/error/package.json","X","HarnessError 基类","稳定机器码与 cause 链","Atlas 有错误分类器","core/atlas/agent/error_classifier.py","部分","按需统一错误码","P3","内部原语")
add("packages/util/file-drag/package.json","F02","文件拖放契约","拖放名称、原生传输请求","Atlas 有 fileDrop 与设备文件传输","frontend/src/renderer/services/fileDrop.ts; core/atlas/devices/file_transfers.py","候选对应","核对 token 类型","P2","静态")
add("packages/util/home-paths/package.json","X","home 路径助手","用户数据路径helper","Atlas 有路径助手","core/atlas/engine/tools/tool_backend_helpers.py","部分","按需统一","P3","内部原语")
add("packages/util/http-proxy/package.json","X","出站代理策略","进程级 HTTP 代理解析","Atlas 有代理源与环境策略","core/atlas/engine/agent/proxy_sources/; core/atlas/engine/tools/environments/local_env_policy.py","候选对应","核对分层优先级","P2","静态")
add("packages/util/launch-environment/package.json","X","启动环境快照","记录每层来源的不可变环境","Atlas 有分层环境","core/atlas/engine/tools/environments/local.py","部分","核对来源标注","P3","内部原语")
add("packages/util/lazy-require/package.json","X","惰性 require","调用方相对的缓存加载","Atlas 无对应","","缺失","不实现","P3","内部原语")
add("packages/util/native-command/package.json","F08","原生命令与路径打开","无 shell 执行、取消、桌面探测","Atlas 有本地执行与 shell 别名","core/atlas/tools/local_execution.py; core/atlas/shell_aliases.py","部分","核对无 shell 路径","P2","静态")
add("packages/util/output-retention/package.json","F08","有界输出保留","ItemRetainer/TextRetainer 与提示","Atlas 有输出上限与截断","core/atlas/engine/tools/tool_output_limits.py; core/atlas/engine/tools/environments/base_output.py","部分","核对保留策略","P2","内部原语")
add("packages/util/package-manifest/package.json","F09","清单 dsh 字段类型","package.json.dsh 配置类型","Atlas 有插件清单类型","core/atlas/plugins/runtime.py","部分","核对字段","P2","内部原语")
add("packages/util/plugin-detail/package.json","F09","插件详情文档","meta.detail/README、图片路径、CDN","Atlas 有文档与 MCP 资源路径","core/atlas/api/cloud_documents_router.py; core/atlas/tools/local_image.py","部分","按需补插件详情","P3","内部原语")
add("packages/util/plugin-market-index/package.json","F09","插件市场索引格式","格式 1 校验、图标解析、安装参数","Atlas 有技能市场","core/atlas/skills/market.py","候选对应","核对索引格式","P2","内部原语")
add("packages/util/time/package.json","X","时间/时区原语","严格 instant、IANA 时区、cron 计算","Atlas 用标准库与调度器","core/atlas/scheduler/","设计差异","不实现","P3","内部原语")
add("packages/util/timeout/package.json","X","超时/截止原语","clampTimeout、deadline、watchdog","Atlas 有 deadline.py","core/atlas/engine/agent/deadline.py","候选对应","核对边界值","P3","内部原语")
add("packages/util/values/package.json","X","JSON 值原语","深比较/快照/JSON 守卫","Atlas 无对应","","缺失","不实现","P3","内部原语")
add("packages/util/workspace-path/package.json","X","工作区路径助手","浏览器安全路径与显示","Atlas 前端自有路径处理","frontend/src/renderer/services/","部分","核对相对/绝对显示","P3","内部原语")
add("packages/web/web-deepseek-api/package.json","F08","DeepSeek 搜索/抓取 provider","DeepSeek Search 与 Fetch API provider","Atlas 有 websearch provider 体系","core/atlas/websearch/providers/","部分","核对 provider 能力","P1","静态")
add("packages/web/web-search-deepseek/package.json","F08","DeepSeek 搜索 provider","经 Anthropic 兼容 API 的原生 web_search","Atlas 有 keyed provider","core/atlas/websearch/providers/keyed.py","部分","核对搜索参数与计费","P1","静态")
add("packages/workflow/tool-workflow/package.json","F05","workflow 编排工具","模型侧 JS 编排脚本 over workflowEngine","Atlas 有 workflow/script.py 与 workflow_tool","core/atlas/workflow/script.py; core/atlas/engine/kernel/workflow_tool.py","候选对应","核对控制流与拒绝规则","P1","静态")

add("packages/attachment/attachment-local/package.json","F07","本地附件存储","会话作用域的本地附件保存与读取","Atlas 有附件/媒体入口与后台任务，未见统一附件存储缝","core/atlas/background_tasks.py; core/atlas/channels/ingress.py","部分","按需抽附件存储层","P2","静态")
add("packages/attachment/attachment/package.json","F07","附件抽象缝","附件保存/读取契约","Atlas 直接使用渠道与消息附件","core/atlas/channels/ingress.py","设计差异","不强制抽象","P3","架构差异")
add("packages/bundle/base/package.json","F01","基础 bundle 组合","基础运行时组合层","Atlas 用服务注册与启动装配","core/atlas/api/app_services.py; core/atlas/server.py","设计差异","无需补齐","P3","架构差异")
add("packages/experimental/session-titles-bundle/package.json","F07","自动会话标题","会话标题生成的组合层","Atlas 有会话标题生成","core/atlas/agent/run_phases.py; core/atlas/engine/atlas_runtime.py","候选对应","核对标题生成时机与去重","P1","experimental；静态")
add("packages/experimental/timeline/package.json","F07","会话时间线投影","实验性时间线视图","Atlas 有前端 timelineProjection 与投影","frontend/src/renderer/components/timelineProjection.ts; core/atlas/engine/state/projections.py","部分","核对时间线粒度","P2","experimental；静态")
add("packages/guard/repeat-tool-reminder/package.json","F05","重复工具调用提醒","重复调用检测与提醒","Atlas 有 stuck 检测","core/atlas/engine/kernel/stuck.py","候选对应","核对重复判定阈值","P1","静态")
add("packages/jobs/jobs-local/package.json","F08","本地后台任务","本地后台任务执行与状态","Atlas 有 background_tasks.py","core/atlas/background_tasks.py","候选对应","核对持久化与取消","P1","静态")
add("packages/jobs/jobs/package.json","F08","后台任务抽象","后台任务 seam","Atlas 直接使用 background_tasks","core/atlas/background_tasks.py","设计差异","不强制抽象","P2","架构差异")
add("packages/llm/deepseek-llm-api-extensions/package.json","F06","DeepSeek API 扩展","DeepSeek 兼容 API 的扩展字段/能力","Atlas 有模型路由与 provider 参数","core/atlas/models/router.py","部分","核对扩展字段","P2","静态")
add("packages/llm/llm-deepseek-api-key/package.json","F06","DeepSeek API key provider","API key 提供者与连接选择","Atlas 有模型凭据与路由","core/atlas/models/credentials.py; core/atlas/models/router.py","候选对应","核对 provider 选择与错误","P1","静态")
add("packages/mcp/mcp-manager/package.json","F09","MCP 管理器","共享 MCP 服务器管理与授权","Atlas 有 mcp_client 与 mcp_oauth","core/atlas/tools/mcp_client.py; core/atlas/tools/mcp_oauth.py","候选对应","核对服务器生命周期","P1","静态")
add("packages/session-query/tool-session-list/package.json","F07","会话列表工具","模型侧只读会话列举，offset/limit 1–100","Atlas 有 session_queries","core/atlas/agent/session_queries.py","候选对应","核对分页与默认值","P1","静态")
add("packages/session/session-format-v0-to-v1/package.json","F07","会话格式迁移 v0→v1","旧格式到 v1 的迁移","Atlas 有会话迁移闸门","core/atlas/session_migration_gate.py","候选对应","核对迁移幂等与拒绝边界","P2","静态")
add("packages/session/session-format-v1-to-v2/package.json","F07","会话格式迁移 v1→v2","v1 到 v2 的迁移","Atlas 有会话迁移闸门","core/atlas/session_migration_gate.py","候选对应","核对迁移幂等与拒绝边界","P2","静态")
add("packages/session/session-format-v2-to-v3/package.json","F07","会话格式迁移 v2→v3","v2 到 v3 的迁移","Atlas 有会话迁移闸门","core/atlas/session_migration_gate.py","候选对应","核对迁移幂等与拒绝边界","P2","静态")
add("packages/util/text-search/package.json","F07","文本搜索","多语言分词/文本搜索基础","Atlas 有状态库搜索","core/atlas/engine/state/atlas_state_search.py","候选对应","核对分词与排序","P2","静态")

# Atlas-only surfaces
ATL = [
 ("ATL-REWIND","F07","会话回卷与检查点","DSH 无同名模块；Atlas 有 rewind 与 run_checkpoints","Atlas 独有：会话回卷/恢复","core/atlas/rewind/; core/atlas/run_checkpoints.py","Atlas独有","保留；可反向输出给 DSH 对照","P2","Atlas 独有"),
 ("ATL-PROJECTS","F10","项目注册与项目设置","DSH 无同名模块；Atlas 有 projects 与 project_settings","Atlas 独有：项目维度注册/设置","core/atlas/projects/; core/atlas/project_settings.py","Atlas独有","保留；可反向输出","P2","Atlas 独有"),
]
for row in ATL:
    i,code,detail,dsh,atlas,ev,verdict,action,prio,note=row
    canon.append({"ID":i,"域编码":code,"领域":"Atlas 独有","细节":detail,"DSH版本":"rc.5",
        "DSH行为":dsh,"DSH证据":"无对应模块","Atlas行为":atlas,"Atlas证据":ev,"结论":verdict,
        "差异或边界":note,"Atlas行动":action,"优先级":prio,"证据等级":"源码静态","来源":"本轮补核"})

ATOMC = [
 ("ATOM-TERMINAL-BASH","F08","持久 bash 原子能力（历史台账 112 项）","DSH terminal-bash 的 112 条原子义务：PTY 生命周期、取消、清理、owner 作用域","Atlas 有终端环境注册表与面板，未按原子项逐条核","core/atlas/engine/agent/terminal_env_registry.py; frontend/src/renderer/shell/panels/TerminalPanel.tsx","未核","按 atomic-capabilities.jsonl 的 terminal-bash 112 项逐条核对","P2","历史台账；Atlas parity atomic"),
 ("ATOM-UI-SCHEDULE","F03","计划页 UI 原子能力（历史台账 109 项）","DSH client-ui-schedule 及其 tests 的 109 条原子义务","Atlas 有 scheduler/automation 与计划页，未逐原子项核","core/atlas/scheduler/; frontend/src/renderer/pages/AutomationPage.tsx","未核","按原子台账核对计划页状态、编辑与测试面","P2","历史台账"),
 ("ATOM-TOOL-TERMINAL","F08","终端工具原子能力（历史台账 117 项）","dsh-tool-terminal / dsh-terminal / client-ui-tool 组合的 117 条原子义务","Atlas 有终端工具与 UI，未逐原子项核","core/atlas/engine/tools/terminal_tool_config.py; core/atlas/tools/terminal_scope.py","未核","按原子台账核对终端工具的触发、错误与 UI 投影","P2","历史台账"),
 ("ATOM-SESSION-CONTROLLER","F07","会话控制器原子能力（历史台账 24 项）","dsh-api-session-controller 的 24 条 Session 协议义务","Atlas 有 atlas_runtime/session_queries，未逐项核","core/atlas/engine/atlas_runtime.py; core/atlas/agent/session_queries.py","部分","按原子台账核对首发送达、queue/steer、取消与历史分页","P1","历史台账"),
 ("ATOM-MISC","F04","SDK/工作目录原子能力（历史台账 4 项）","dsh-sdk、dsh-working-directory、dsh-tool-working-directory 的 4 条原子义务","Atlas 有 app-server/ACP 与工作区工具，逐项映射待核","core/atlas/tools/app_server.py; core/atlas/tools/workspace_queries.py","未核","逐条核对 SDK 与工作目录契约","P3","历史台账"),
]
for (i,code,detail,dsh,atlas,ev,verdict,action,prio,note) in ATOMC:
    canon.append({"ID":i,"域编码":code,"领域":"历史原子台账","细节":detail,"DSH版本":"rc.5",
        "DSH行为":dsh,"DSH证据":"tasks/dsh-parity/atomic/atomic-capabilities.jsonl（Atlas 历史台账）",
        "Atlas行为":atlas,"Atlas证据":ev,"结论":verdict,"差异或边界":note,"Atlas行动":action,
        "优先级":prio,"证据等级":"历史台账","证据校验":"无 DSH 路径；Atlas 路径存在","来源":"Atlas 原子台账（历史）"})

# ---------------- complement rows ----------------
DEFAULT_VERDICT_PRIO = {"缺失":"P1","部分":"P2","候选对应":"P2","设计差异":"P3","非产品面":"P3"}
for (mf,code,detail,dsh,atlas,ev,verdict,action,prio,note) in M:
    short = mf.replace("packages/","").replace("apps/","app-").replace("/package.json","").replace("/","-").upper()
    rid = "PKG-" + re.sub(r"[^A-Z0-9]+","-",short).strip("-")
    inv = INV_BY_MANIFEST.get(mf, {})
    entry = PICK_BY_MANIFEST.get(mf, "")
    evd = mf + "@" + DSH_REF + (f"；入口 {entry}" if entry else "")
    canon.append({"ID":rid,"域编码":code,"领域":DOMAIN_CN.get(code,"未分类"),"细节":detail,
        "DSH版本":inv.get("in_versions","rc.5"),"DSH行为":dsh,"DSH证据":evd,
        "Atlas行为":atlas,"Atlas证据":ev or "未定位到 Atlas 等价实现",
        "结论":verdict,"差异或边界":note,"Atlas行动":action,"优先级":prio,
        "证据等级":"清单级" if verdict=="非产品面" else "源码静态","来源":"本轮补核（2026-11-20）"})

# ---------------- evidence validation ----------------
import subprocess
EVPAT = re.compile(r"[A-Za-z0-9_@./-]+\.(?:tsx|ts|jsx|js|mjs|cjs|json|py|css|toml|yaml|yml|md)(?![A-Za-z0-9])")
def _rel(p):
    return re.match(r"^(?:packages|apps|docs|scripts|tooling|website|frontend|core|backend-adapter|\.github|config|tests|tasks)/", p)
_dsh = set()
for r in canon:
    _dsh.update(x for x in EVPAT.findall(r["DSH证据"] or "") if _rel(x))
_bare = r"D:\Atlas\.worktrees\_codex-dsh-rc5-source.git"
_out = subprocess.run(["git","-C",_bare,"cat-file","--batch-check"],
    input="".join("2e39e704:%s\n" % p for p in sorted(_dsh)),
    capture_output=True,text=True,encoding="utf-8",errors="replace").stdout.splitlines()
_valid_dsh = {p for p,line in zip(sorted(_dsh), _out) if not line.endswith(" missing")}
for r in canon:
    dp=[x for x in EVPAT.findall(r["DSH证据"] or "") if _rel(x)]
    ap=[x for x in EVPAT.findall(r["Atlas证据"] or "") if _rel(x)]
    if not dp:
        dv="无 DSH 路径"
    elif any(x in _valid_dsh for x in dp):
        dv="DSH 路径存在"
    else:
        dv="DSH 路径失配"
    if not ap:
        av="无 Atlas 路径"
    elif any(os.path.exists(os.path.join(r"D:\Atlas", x.replace("/", os.sep))) for x in ap):
        av="Atlas 路径存在"
    else:
        av="Atlas 路径失配"
    r["证据校验"]=dv+"；"+av

# ---------------- write ----------------
COLS = ["ID","域编码","领域","细节","DSH版本","DSH行为","DSH证据","Atlas行为","Atlas证据","结论","差异或边界","Atlas行动","优先级","证据等级","证据校验","来源"]
VERDICT_ORDER = {"缺失":0,"部分":1,"候选对应":2,"未核":3,"设计差异":4,"Atlas独有":5,"已对齐":6}
def sort_key(r):
    return (r["域编码"], VERDICT_ORDER.get(r["结论"],9), r["优先级"] or "P9", r["ID"])
canon.sort(key=sort_key)
with io.open(os.path.join(OUT,"Atlas-DSH-完整对照表-20261120.tsv"),"w",encoding="utf-8",newline="") as f:
    w=csv.DictWriter(f,delimiter="\t",fieldnames=COLS); w.writeheader(); w.writerows(canon)

# coverage ledger
pkg_rows = collections.defaultdict(list)
for r in canon:
    for inv in INV:
        d=os.path.dirname(inv["manifest"])
        if d in (r["DSH证据"] or "") or (inv["name"] and inv["name"] in (r["DSH证据"] or "")) or (inv["name"] and inv["name"] in (r["DSH行为"] or "")):
            pkg_rows[inv["manifest"]].append(r)
ledger=[]
for inv in INV:
    ids=pkg_rows.get(inv["manifest"],[])
    verdicts=collections.Counter(x["结论"] for x in ids)
    ledger.append({"包清单":inv["manifest"],"包名":inv["name"],"版本":inv.get("in_versions",""),
        "说明":inv["description"][:100],"行数":len(ids),"行ID":";".join(x["ID"] for x in ids[:8]),
        "结论分布":";".join(f"{k}={v}" for k,v in verdicts.items()) or "无行",
        "覆盖级别":"有专项行" if any(x["来源"].startswith("本轮补核") for x in ids) else ("有引用行" if ids else "无行")})
with io.open(os.path.join(OUT,"Atlas-DSH-覆盖台账.tsv"),"w",encoding="utf-8",newline="") as f:
    w=csv.DictWriter(f,delimiter="\t",fieldnames=list(ledger[0].keys())); w.writeheader(); w.writerows(ledger)

# action list
acts=[r for r in canon if r["结论"] in ("缺失","部分","候选对应","未核")]
acts.sort(key=sort_key)
with io.open(os.path.join(OUT,"Atlas-DSH-施工单-20261120.tsv"),"w",encoding="utf-8",newline="") as f:
    w=csv.DictWriter(f,delimiter="\t",fieldnames=["ID","域编码","领域","细节","结论","优先级","Atlas行动","Atlas证据","差异或边界"]); w.writeheader()
    for r in acts:
        w.writerow({k:r.get(k,"") for k in ["ID","域编码","领域","细节","结论","优先级","Atlas行动","Atlas证据","差异或边界"]})

# stats
st=collections.Counter(r["结论"] for r in canon)
print("FINAL rows:",len(canon))
for k,v in st.most_common(): print(f"  {k}: {v}")
print("packages covered:",sum(1 for x in ledger if x["行数"]>0),"/",len(ledger))
print("packages with dedicated rows:",sum(1 for x in ledger if x["覆盖级别"]=="有专项行"))
missing_map=set(x[0] for x in M)
print("mapping entries:",len(M),"unique:",len(missing_map))
not_mapped=set(i["manifest"] for i in INV)-missing_map
print("not in mapping:",len(not_mapped))
no_row=[i["manifest"] for i in INV if not pkg_rows.get(i["manifest"])]
print("packages with zero ledger rows:",len(no_row))
for m in no_row: print("  ZERO:",m)