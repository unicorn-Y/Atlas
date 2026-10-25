import { lazy, startTransition, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import {
  AudioLines, Bell, BookMarked, Brain, Copy, Cpu, Keyboard, Monitor, Radio, Smartphone, Wrench, Sparkles, Laptop, Webhook, Server, ShieldCheck, ShieldAlert as ShieldAsk, Lock, Download, FolderOpen, GitBranch, GitBranchPlus, MessagesSquare, UserCog, Image as ImageIcon, ListChecks, MessageCircle, MessageSquareX, Undo2, Minus, Moon, PanelRight, Pause, Pencil, Play, Plus, Puzzle, RotateCcw, Settings,
  SlidersHorizontal, Square, Sun, Zap, FileCog, Volume2, X, Gauge, Search, Pin, HardDrive, File as FileIcon,
} from 'lucide-react';
import { backend, useAtlasStore } from './store/useAtlasStore';
import type { ConversationMessage as HistoryMessage, RunFile } from '@atlas/backend-adapter';
import type { BackendStartupProgress, RecentScreenshot } from '../shared/ipc';
import type { Artifact } from '../types/artifact';
import type { AgentEvent } from '../types/runtime';
import { latestTodos, usageSummary } from './components/runInsights';
import Composer, { type ComposerMode, type MentionItem, type SlashCommand } from './components/Composer';
import KeymapDialog from './components/KeymapDialog';
import { resolveMessageSkillReferences } from './components/skillMentions';
import { cancelRoutedSpeech, speakRouted } from './services/speechPlayback';
import { getSelectedInputStream } from './services/audioDevices';
const MessageThread = lazy(() => import('./components/MessageThread'));
const TodoPanel = lazy(() => import('./components/TodoPanel'));
const ProgressCapsule = lazy(() => import('./components/ProgressCapsule'));
const ConversationQueuePanel = lazy(() => import('./components/ConversationQueuePanel'));
const RecipesDialog = lazy(() => import('./components/RecipesDialog'));
const WorkflowManagerDialog = lazy(() => import('./components/WorkflowManagerDialog'));
const SideChat = lazy(() => import('./components/SideChat'));
const PaneWorkspace = lazy(() => import('./components/PaneWorkspace'));
const UltraplanPanel = lazy(() => import('./components/UltraplanPanel'));
const RemoteFolderDialog = lazy(() => import('./components/RemoteFolderDialog'));
const InitDialog = lazy(() => import('./components/InitDialog'));
const LspStatusSection = lazy(() => import('./components/LspStatusSection'));
const TimelineNav = lazy(() => import('./components/TimelineNav'));
const ChaptersNav = lazy(() => import('./components/ChaptersNav'));
const ForkTree = lazy(() => import('./components/ForkTree'));
const RunSetupMenu = lazy(() => import('./components/RunSetupMenu'));
const TabStrip = lazy(() => import('./components/TabStrip'));
const OnboardingDialog = lazy(() => import('./components/OnboardingDialog'));
const FeatureLessons = lazy(() => import('./components/FeatureLessons'));
const ResumePickerDialog = lazy(() => import('./components/ResumePickerDialog'));
const FallbackModelsDialog = lazy(() => import('./components/FallbackModelsDialog'));
const IDEManagerDialog = lazy(() => import('./components/IDEManagerDialog'));
import { applyFileBindings, loadBindings, matchShortcut } from './services/shortcuts';
import type { CustomCommandInfo, PermissionMode } from '@atlas/backend-adapter';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from './ui/Menu';
import Mark, { MarkDefs } from './components/Mark';
import type { PaletteItem } from './components/Palette';
import PersonalTodos from './components/PersonalTodos';
import type { StatusBarPreferences } from './pages/SettingsPage';
import type { RecipeLaunchRequest } from './components/settings/RecipeManagerPanel';
// Each navigation destination is its own renderer chunk. The initial conversation
// surface therefore does not parse the settings, automation, and workbench pages.
const ShortcutsPanel = lazy(() => import('./pages/ShortcutsPanel'));
const ScriptToolsPanel = lazy(() => import('./pages/ScriptToolsPanel'));
const TelegramPanel = lazy(() => import('./pages/TelegramPanel'));
const UsagePanel = lazy(() => import('./pages/UsagePanel'));
const SkillsMarketPage = lazy(() => import('./pages/SkillsMarketPage'));
const LibraryPage = lazy(() => import('./pages/LibraryPage'));
const EvolutionPage = lazy(() => import('./pages/EvolutionPage'));
const MemoryPage = lazy(() => import('./pages/MemoryPage'));
const AutomationPage = lazy(() => import('./pages/AutomationPage'));
const CodePage = lazy(() => import('./pages/CodePage'));
const CreatePage = lazy(() => import('./pages/CreatePage'));
const BoardPage = lazy(() => import('./pages/BoardPage'));
const ProfilesPanel = lazy(() => import('./pages/ProfilesPanel'));
const HooksPanel = lazy(() => import('./pages/HooksPanel'));
const AgentsPage = lazy(() => import('./pages/agents/AgentsPage'));
const AgentsOverview = lazy(() => import('./pages/agents/AgentsOverview'));
const DevicesPage = lazy(() => import('./pages/DevicesPage'));
const WorkbenchPage = lazy(() => import('./pages/WorkbenchPage'));
const GroupsView = lazy(() => import('./pages/GroupsView'));
const ChannelsSettings = lazy(() => import('./pages/settings/ChannelsSettings'));
const LocalModelsSettings = lazy(() => import('./pages/settings/LocalModelsSettings'));
const NotificationsPanel = lazy(() => import('./pages/ConsolePage').then((module) => ({ default: module.NotificationsPanel })));
const PluginsPanel = lazy(() => import('./pages/ConsolePage').then((module) => ({ default: module.PluginsPanel })));
const Palette = lazy(() => import('./components/Palette'));
const Inspector = lazy(() => import('./shell/Inspector'));
const VoiceOverlay = lazy(() => import('./components/VoiceOverlay'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const ImportPanel = lazy(() => import('./components/ImportPanel'));
const McpServersPanel = lazy(() => import('./components/settings/McpServersPanel'));
const ConfigTransferPanel = lazy(() => import('./components/settings/ConfigTransferPanel'));
const DiagnosticsPanel = lazy(() => import('./components/settings/DiagnosticsPanel'));
const RecipeManagerPanel = lazy(() => import('./components/settings/RecipeManagerPanel'));
const ExtensionPackagesPanel = lazy(() => import('./components/settings/ExtensionPackagesPanel'));
const ExtensionCatalogPanel = lazy(() => import('./components/settings/ExtensionCatalogPanel'));
const AppearanceNotificationsPanel = lazy(() => import('./components/settings/AppearanceNotificationsPanel'));
const AudioDevicesPanel = lazy(() => import('./components/settings/AudioDevicesPanel'));
const StorageRetentionPanel = lazy(() => import('./components/settings/StorageRetentionPanel'));
const WorkspaceSecurityPanel = lazy(() => import('./components/settings/WorkspaceSecurityPanel'));
const ConversationModelSettings = lazy(() => import('./components/settings/ConversationModelSettings'));
const ConversationMemoryPanel = lazy(() => import('./components/ConversationMemoryPanel'));
const U4SettingsPanel = lazy(() => import('./components/settings/U4SettingsPanel'));
const SettingsProposalCards = lazy(() => import('./components/SettingsProposalCards'));
const CustomCommandsPanel = lazy(() => import('./components/settings/CustomCommandsPanel'));
const RunLimitsPanel = lazy(() => import('./components/settings/RunLimitsPanel'));
const PlatformSettingsPanel = lazy(() => import('./components/settings/PlatformSettingsPanel'));
const BackgroundTasksPanel = lazy(() => import('./components/settings/BackgroundTasksPanel'));
const SettingsIntegrationsPanel = lazy(() => import('./components/settings/SettingsIntegrationsPanel'));
const NetworkSettingsPanel = lazy(() => import('./components/settings/NetworkSettingsPanel'));
const MainConfigPanel = lazy(() => import('./components/settings/MainConfigPanel'));
const ExpertModePanel = lazy(() => import('./components/settings/ExpertModePanel'));
const ExpertModeBadge = lazy(() => import('./components/settings/ExpertModePanel').then((module) => ({ default: module.ExpertModeBadge })));
const OutputStyleSettingsPanel = lazy(() => import('./components/settings/OutputStyleSettingsPanel'));
const McpResourcesPanel = lazy(() => import('./components/settings/McpResourcesPanel'));
const LocalModelsPanel = lazy(() => import('./components/settings/LocalModelsPanel'));
const DesktopTeachPanel = lazy(() => import('./components/settings/DesktopTeachPanel'));
const DesktopTeachOverlay = lazy(() => import('./components/settings/DesktopTeachPanel').then((module) => ({ default: module.DesktopTeachOverlay })));
const SecretsPanel = lazy(() => import('./components/settings/SecretsPanel'));
const LinearIntegrationPanel = lazy(() => import('./components/settings/LinearIntegrationPanel'));
const OPEN_EXPERT_SETTINGS = 'atlas:open-expert-settings';
import Sidebar, { MORE_NAV, NAV, type View } from './shell/Sidebar';
import HomeView, { type Suggestion } from './shell/HomeView';
import type { InspectorTab } from './shell/Inspector';
import type { PickedElement } from './shell/panels/BrowserPanel';
import { THEMES, applyStoredTheme, clearCustomTheme, initialTheme, nextTheme, themeInfo, type Theme } from './shell/themes';
import { observeLocalizedCopy, readLocale, saveLocale, t } from './services/i18n';
import { api, relativeTime } from './services/api';
import { extractMemoryMarkers } from './services/memoryMarkers';
import { buildTimeline } from './components/timeline';
const ComputerEdgeBar = lazy(() => import('./components/x2').then((module) => ({ default: module.ComputerEdgeBar })));
import UpdateBanner from './components/UpdateBanner';
import DiagnosticsFloatingOverlay from './components/DiagnosticsFloatingOverlay';
import { Button } from './ui/Button';
import { Dialog } from './ui/Dialog';
import { Tip, TooltipProvider } from './ui/Tooltip';
import { cn } from './ui/cn';
import { cleanSearchSnippet, rankSearchHits, searchHitRoleLabel } from './services/searchHits';
import ComputerLivePreview from './components/x2/ComputerLivePreview';
const ScreenRecorderDialog = lazy(() => import('./components/ScreenRecorderDialog'));

type SheetPane = 'models' | 'advanced' | 'usage' | 'limits' | 'profiles' | 'hooks' | 'tools' | 'telegram' | 'channels' | 'devices' | 'localModels' | 'shortcuts' | 'appearance' | 'u4' | 'plugins' | 'mcp' | 'skills' | 'recipes' | 'extensions' | 'transfer' | 'diagnostics' | 'security' | 'commands' | 'platform' | 'integrations' | 'network' | 'expert' | 'mainConfig' | 'storage' | 'memories' | 'teach' | 'secrets';
type MemoryMarkerDraft = { text: string; path: string; session?: string; ref?: string };

const SETTINGS_NAV: Array<[SheetPane, string, typeof Bell, string]> = [
  ['models', '模型与服务', SlidersHorizontal, 'provider 模型 model 默认模型 主模型备用链 fallback API key 密钥 reasoning 推理 连接 base URL endpoint 服务商提供商 API 地址 用户名 顾问子代理模型 subagent status bar 状态栏'],
  ['secrets', '密钥库', Lock, 'secrets 密钥 keyring credential handle token'],
  ['teach', '桌面教学', Monitor, 'teach 录制 桌面 操作 教学 技能 skill'],
  ['mainConfig', '主体配置', FileCog, 'atlas.toml config 配置 文件 user-settings 界面设置 当前生效 备份 恢复 编辑'],
  ['expert', '专家模式', Zap, 'expert 专家 模式 切换 覆盖 overlay 额外配置 附加说明 提示词 技能 插件 工具 MCP 同步 仓库 安装 卸载'],
  ['network', '模型网络', Server, 'proxy 代理 CA certificate certificate authority 网络 HTTPS TLS'],
  ['security', '工作区安全', ShieldCheck, 'workspace trust 信任 sandbox 沙箱 network permission 权限 rules AGENTS CLAUDE 执行权限 文件写入 网络访问 命令 Docker 容器 隔离会话 当前会话模型 凭据'],
  ['channels', 'Gateway 与渠道账号', Radio, 'gateway channel 渠道 账号 bot token access policy dm group pairing allowlist 发送者 策略 配对 私聊 群聊 允许名单'],
  ['localModels', '本地模型', Cpu, 'local 本地模型'],
  ['advanced', '高级', Settings, 'compression 压缩 高级'],
  ['u4', '会话与顾问', UserCog, '顾问 advisor 顾问模型 默认顾问模型 会话预设 preset 预设 工作目录 模型 推理强度 技能 环境变量 ChatGPT 导入 历史 手机推送 mobile push channel chat id completion approval failure'],
  ['usage', '用量', Gauge, 'usage token cost 费用 预算 个人资料 profile'],
  ['limits', '运行限制', Gauge, 'run limits max turns 轮数 token budget cost limit 费用上限'],
  ['profiles', '角色', UserCog, 'profile 角色 agent'],
  ['hooks', 'Hooks', Webhook, 'hook 事件'],
  ['commands', '自定义命令', BookMarked, 'slash command 命令 prompt 参数'],
  ['tools', '脚本工具', Wrench, 'script tool 工具'],
  ['telegram', '手机远程', Smartphone, 'telegram remote 手机 远程'],
  ['devices', '设备', Monitor, 'device remote pairing 设备 配对 二维码 扫码 注册 可信 在线 凭据 token 轮换 撤销 DM 私信 审批 指令 结果'],
  ['shortcuts', '快捷键', Keyboard, 'shortcut keybinding 快捷键 按键 全局快捷键 语音快捷键 截图 按住说话'],
  ['appearance', '外观、字号、语音与通知', Sun, 'appearance theme font font size typography notification desktop toast quiet hours sound voice language UI language interface size font family monospace Vim theme color dark light system screenshot notifications sound focus mode quiet hours quiet start quiet end notification permission pinned summary sidebar read aloud voice rate microphone wake word auto send 外观 主题 字体 字号 界面语言 界面字号 界面字体 等宽字体 Vim 配色 深色 浅色 跟随系统 通知 桌面通知 系统提示音 专注模式 静默时段 静默开始时间 静默结束时间 权限 置顶任务摘要 侧边栏 自动朗读 语速 麦克风 唤醒词 自动发送'],
  ['plugins', '插件与导入', Puzzle, 'plugin import 插件 导入 Claude Codex'],
  ['skills', 'Skills', BookMarked, 'skill 技能 安全发现'],
  ['mcp', 'MCP 服务', Server, 'mcp server tool 服务'],
  ['recipes', '配方', BookMarked, 'recipe template 参数化 配方'],
  ['extensions', '扩展目录与来源', Puzzle, 'extension package registry catalog 扩展 包 目录 来源'],
  ['transfer', '配置导入导出', Download, 'settings config export import backup 配置 导入 导出 备份'],
  ['diagnostics', '诊断', ShieldCheck, 'diagnostics health config errors 诊断 健康 配置 错误'],
  ['storage', '存储与保留', HardDrive, 'storage disk cache retention data clear 存储 占用 保留期限 清理'],
  ['platform', '平台集成', Laptop, 'desktop platform global shortcut hotkey always on top VS Code JetBrains deep link'],
  ['integrations', '任务与集成', GitBranchPlus, 'github pull request Slack Linear cloud tasks automation'],
];

const TERMINAL = ['completed', 'failed', 'cancelled'];
const RUN_LABEL: Record<string, string> = { running: '正在处理', planning: '正在规划', queued: '排队中', paused: '已暂停', waiting: '等你确认', waiting_approval: '等你确认', completed: '已完成', failed: '出错了', cancelled: '已中断' };
const HOME_MODES: ComposerMode[] = [
  { id: 'chat', label: '对话', icon: MessageCircle },
  { id: 'image', label: '图像', icon: ImageIcon },
  { id: 'voice', label: '语音通话', icon: AudioLines },
];
const PERMISSION: Record<PermissionMode, { label: string; hint: string }> = {
  full_access: { label: '完全访问', hint: 'Atlas 直接读写文件、运行命令（默认）' },
  ask_each: { label: '每步确认', hint: '每次调用工具前都先问你' },
  ask_writes: { label: '改前问我', hint: '改文件、运行命令前先问你' },
  auto_file: { label: '自动改文件', hint: '文件编辑自动进行，命令和 MCP 写操作前先问你' },
  plan: { label: '计划模式', hint: '只读探索并先提交计划，批准后再执行' },
  read_only: { label: '只读', hint: '只能查看，不能改任何东西' },
};
const EFFORT_LABEL: Record<string, string> = { minimal: '最低', low: '低', medium: '中', high: '高' };
const PROVIDER_USAGE_URL: Record<string, { label: string; url: string }> = {
  anthropic: { label: 'Anthropic 用量与账单', url: 'https://platform.claude.com/usage' },
  openai: { label: 'OpenAI 用量与账单', url: 'https://platform.openai.com/usage' },
  deepseek: { label: 'DeepSeek 账户用量', url: 'https://platform.deepseek.com/usage' },
  google: { label: 'Google AI Studio 账户', url: 'https://aistudio.google.com/' },
  gemini: { label: 'Google AI Studio 账户', url: 'https://aistudio.google.com/' },
  mistral: { label: 'Mistral 用量与账单', url: 'https://console.mistral.ai/usage/' },
};
/** Shift+Tab 和 /permissions 共用的切换顺序；read_only 不在循环里，只能从菜单选。 */
const PERMISSION_CYCLE: PermissionMode[] = ['ask_each', 'ask_writes', 'auto_file', 'plan', 'full_access'];
const draftKey = (conversationId: string) => `atlas.draft.${conversationId || 'home'}`;
function parseRecentScreenshotCache(value: unknown): { capturedAt: number; items: string[] } | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as { capturedAt?: unknown; items?: unknown };
  if (typeof row.capturedAt !== 'number' || !Array.isArray(row.items)) return null;
  return { capturedAt: row.capturedAt, items: row.items.filter((item): item is string => typeof item === 'string') };
}
const readDraft = (conversationId: string) => { try { return localStorage.getItem(draftKey(conversationId)) ?? ''; } catch { return ''; } };
const writeDraft = (conversationId: string, text: string) => {
  try { if (text) localStorage.setItem(draftKey(conversationId), text); else localStorage.removeItem(draftKey(conversationId)); } catch { /* storage unavailable */ }
};
const pref = (key: string) => { try { return localStorage.getItem(`atlas.preference.${key}`); } catch { return null; } };
const setPref = (key: string, value: string) => { try { localStorage.setItem(`atlas.preference.${key}`, value); } catch { /* storage unavailable */ } };
const STATUS_BAR_KEYS: Array<keyof StatusBarPreferences> = ['model', 'reasoning', 'context', 'tokens', 'cost', 'git', 'permission', 'processes'];
const readStatusBarPreferences = (): StatusBarPreferences => {
  let saved: Partial<StatusBarPreferences> = {};
  try { saved = JSON.parse(pref('statusbar') ?? '{}') as Partial<StatusBarPreferences>; } catch { /* use defaults */ }
  return Object.fromEntries(STATUS_BAR_KEYS.map((key) => [key, typeof saved[key] === 'boolean' ? saved[key] : true])) as StatusBarPreferences;
};

export default function App() {
  // 窄选择器：只订阅这个界面真正要读的数据字段；动作函数恒定，从 getState 合入。
  // conversationMessages 仍在列（朗读/撤回/复制要用），但重列表的渲染已交给 MessageThread 自己的窄订阅。
  const storeData = useAtlasStore(useShallow((state) => ({
    apiBaseUrl: state.apiBaseUrl, providerBaseUrl: state.providerBaseUrl, apiKeyConfigured: state.apiKeyConfigured,
    initOpen: state.initOpen,
    compressionModel: state.compressionModel, configLoaded: state.configLoaded, settingsBusy: state.settingsBusy,
    connectionTest: state.connectionTest, mode: state.mode, connected: state.connected, busy: state.busy, paused: state.paused,
    backendStarting: state.backendStarting, startupDetail: state.startupDetail,
    error: state.error, model: state.model, models: state.models, providers: state.providers, reasoningStages: state.reasoningStages,
    tools: state.tools, skills: state.skills, activeSkills: state.activeSkills, capabilities: state.capabilities,
    conversations: state.conversations, conversationsLoading: state.conversationsLoading,
    loadingMessagesConversationId: state.loadingMessagesConversationId, creatingConversation: state.creatingConversation,
    conversationMessages: state.conversationMessages, activeConversationId: state.activeConversationId,
    runs: state.runs, activeRunId: state.activeRunId, artifacts: state.artifacts, queue: state.queue, queuePaused: state.queuePaused,
    followUpMode: state.followUpMode, nextRunMode: state.nextRunMode, unread: state.unread, pinned: state.pinned,
    archived: state.archived, runPrompts: state.runPrompts, profiles: state.profiles, recipes: state.recipes,
    customCommands: state.customCommands, profileId: state.profileId, reasoningEffort: state.reasoningEffort,
    worktreeRequests: state.worktreeRequests, fileOpenRequest: state.fileOpenRequest,
  })));
  const store = useMemo(() => ({ ...useAtlasStore.getState(), ...storeData }), [storeData]);
  const storeRef = useRef(store);
  storeRef.current = store;
  const [startupProgress, setStartupProgress] = useState<BackendStartupProgress | null>(null);
  const [pendingComponents, setPendingComponents] = useState<string[]>([]);
  const [view, setView] = useState<View>('home');
  const [inspectorOpen, setInspectorOpen] = useState(() => pref('canvas') === 'true');
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('artifacts');
  const [previewFile, setPreviewFile] = useState('');
  const [fullScreenDiff, setFullScreenDiff] = useState(false);
  const [theme, setTheme] = useState<Theme>(() => initialTheme());
  useEffect(() => {
    saveLocale(readLocale());
    const root = document.getElementById('root');
    if (!root) return;
    let stop = observeLocalizedCopy(root, readLocale());
    const onLocaleChange = (event: Event) => {
      stop();
      const locale = (event as CustomEvent<'zh-CN' | 'en-US'>).detail;
      stop = observeLocalizedCopy(root, locale);
    };
    window.addEventListener('atlas:locale-change', onLocaleChange);
    return () => { stop(); window.removeEventListener('atlas:locale-change', onLocaleChange); };
  }, []);
  useEffect(() => {
    const saved = (() => { try { return localStorage.getItem('atlas.code-theme') || 'auto'; } catch { return 'auto'; } })();
    document.documentElement.dataset.codeTheme = saved === 'auto' ? (theme === 'dark' ? 'dark-vivid' : 'light-soft') : saved;
  }, [theme]);
  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => { if (pref('theme-mode') === 'system') setTheme(query.matches ? 'dark' : 'light'); };
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  const [sideMini, setSideMini] = useState(() => pref('sidebar-mini') === 'true');
  // Narrow windows collapse the sidebar to icons without touching the saved preference.
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 900px)').matches);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 900px)');
    const update = () => setNarrow(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  const [sheet, setSheet] = useState<SheetPane | null>(null);
  const [settingsQuery, setSettingsQuery] = useState('');
  const [settingControlMatches, setSettingControlMatches] = useState<Array<{ id: string; label: string; pane: SheetPane }>>([]);
  const settingsContentRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const query = settingsQuery.trim().toLocaleLowerCase();
    if (!query || !sheet) { setSettingControlMatches([]); return; }
    setSettingControlMatches([]);
    let timer = 0;
    const scan = () => {
      const root = settingsContentRef.current;
      if (!root) return;
      const controls = Array.from(root.querySelectorAll<HTMLElement>('input:not([type="hidden"]), select, textarea, button, [role="switch"], [role="checkbox"]'));
      const matches: Array<{ id: string; label: string; pane: SheetPane }> = [];
      controls.forEach((control, index) => {
        const row = control.closest<HTMLElement>('[data-setting-row]');
        const label = (control.getAttribute('aria-label') || row?.dataset.settingLabel || control.closest('label')?.textContent || control.getAttribute('placeholder') || control.getAttribute('title') || control.textContent || control.getAttribute('name') || control.id || '').replace(/\s+/g, ' ').trim();
        const terms = `${label} ${row?.dataset.settingTerms ?? ''} ${control.getAttribute('data-search-terms') ?? ''}`.toLocaleLowerCase();
        if (!label || !terms.includes(query)) return;
        const id = `${sheet}-${index}`;
        control.dataset.settingSearchId = id;
        control.dataset.settingSearchLabel = label;
        matches.push({ id, label: label.slice(0, 140), pane: sheet });
      });
      setSettingControlMatches(matches.slice(0, 20));
      const target = matches.length ? root.querySelector<HTMLElement>(`[data-setting-search-id="${CSS.escape(matches[0].id)}"]`) : null;
      if (target) {
        target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        const prior = target.style.boxShadow;
        target.style.boxShadow = '0 0 0 3px var(--brand), 0 0 0 6px color-mix(in srgb, var(--brand) 20%, transparent)';
        window.setTimeout(() => { if (target.style.boxShadow.includes('var(--brand)')) target.style.boxShadow = prior; }, 1400);
      }
    };
    const scheduleScan = () => { window.clearTimeout(timer); timer = window.setTimeout(scan, 120); };
    const root = settingsContentRef.current;
    const observer = root ? new MutationObserver(scheduleScan) : null;
    observer?.observe(root!, { childList: true, characterData: true, subtree: true });
    scheduleScan();
    return () => { window.clearTimeout(timer); observer?.disconnect(); };
  }, [sheet, settingsQuery]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [resumePickerOpen, setResumePickerOpen] = useState(false);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [keymapOpen, setKeymapOpen] = useState(false);
  const [fallbackOpen, setFallbackOpen] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [computerReady, setComputerReady] = useState(false);
  const [computerUseEnabled, setComputerUseEnabled] = useState(() => pref('computer-use-enabled') !== 'false');
  const [input, setInput] = useState('');
  const [pendingProjectId, setPendingProjectId] = useState('');
  const [summaryEnabled, setSummaryEnabled] = useState(() => pref('pinned-summary') !== 'false');
  const [proactiveEnabled, setProactiveEnabled] = useState(() => pref('suggestions') !== 'false');
  const [wakeEnabled, setWakeEnabled] = useState(() => pref('wake-enabled') === 'true');
  const [wakeWord, setWakeWord] = useState(() => pref('wake-word') || '你好 Atlas');
  const [wakeTranscript, setWakeTranscript] = useState('');
  const wakeSessionRef = useRef<{ socket: WebSocket; stream: MediaStream; context: AudioContext; processor: ScriptProcessorNode } | null>(null);
  const [turnSuggestions, setTurnSuggestions] = useState<string[]>([]);
  const [whatsNewLoaded, setWhatsNewLoaded] = useState(false);
  const generatedSuggestionsRun = useRef('');
  const [homeGitStatus, setHomeGitStatus] = useState<{ isGit: boolean; changed: number; languages: string[] }>({ isGit: false, changed: 0, languages: [] });
  const [homeMode, setHomeMode] = useState('chat');
  const [createPrompt, setCreatePrompt] = useState('');
  const [toast, setToast] = useState('');
  const [memoryMarkerDrafts, setMemoryMarkerDrafts] = useState<MemoryMarkerDraft[] | null>(null);
  const [memoryMarkerSaving, setMemoryMarkerSaving] = useState(false);
  const [attachments, setAttachments] = useState<string[]>([]);
  const [recentScreenshots, setRecentScreenshots] = useState<RecentScreenshot[]>([]);
  const [files, setFiles] = useState<Array<RunFile & { size: number }>>([]);
  const [screenRecorderOpen, setScreenRecorderOpen] = useState(false);
  const [attachmentProgress, setAttachmentProgress] = useState('');
  const [failedAttachmentReads, setFailedAttachmentReads] = useState<File[]>([]);
  const attachmentReadsRef = useRef(0);
  const [editing, setEditing] = useState<{ id: string; original: string } | null>(null);
  const editingDraftRef = useRef<{ text: string; attachments: string[]; files: Array<RunFile & { size: number }>; mentions: MentionItem[] } | null>(null);
  const [rawText, setRawText] = useState<string | null>(null);
  const [rawTextTitle, setRawTextTitle] = useState('最近回复的原始文本');
  useEffect(() => {
    if (!store.connected || whatsNewLoaded) return;
    void api<{ highlights: Array<string | { date?: string; title?: string }> }>(store.apiBaseUrl, '/api/u6/whatsnew').then((result) => {
      const current = __APP_VERSION__; let previous = '';
      try { previous = localStorage.getItem('atlas.last-seen-version') || ''; localStorage.setItem('atlas.last-seen-version', current); } catch { /* optional preference */ }
      const details = result.highlights.map((item) => typeof item === 'string' ? item : `${item.date || ''} ${item.title || ''}`.trim()).filter(Boolean).join('\n');
      if (previous && previous !== current) { setRawTextTitle('有什么新功能'); setRawText(details || `Atlas ${current} 已更新。`); }
      setWhatsNewLoaded(true);
    }).catch(() => setWhatsNewLoaded(true));
  }, [store.connected, store.apiBaseUrl, whatsNewLoaded]);
  const [browserUrl, setBrowserUrl] = useState('');
  const [terminalCommand, setTerminalCommand] = useState<{ id: string; text: string } | null>(null);
  const [mentions, setMentions] = useState<MentionItem[]>([]);
  const composerSnapshotRef = useRef({ text: input, attachments, files, mentions });
  composerSnapshotRef.current = { text: input, attachments, files, mentions };
  const [recipesOpen, setRecipesOpen] = useState(false);
  const [workflowManagerOpen, setWorkflowManagerOpen] = useState(false);
  const [ideManagerOpen, setIdeManagerOpen] = useState(false);
  const [side, setSide] = useState<{ open: boolean; question?: string }>({ open: false });
  const [schedulePromptOpen, setSchedulePromptOpen] = useState(false);
  const scheduleBypass = useRef(false);
  // 发起时就固定目标/会话/工作区：面板不随当前会话切换而重发调研或被卸载。
  const [ultraplan, setUltraplan] = useState<{ goal: string; conversationId: string; workspace: string; title: string } | null>(null);
  const ultraplanStarting = useRef(false);
  const [ultraplanArtifact, setUltraplanArtifact] = useState<Artifact | null>(null);
  const [branches, setBranches] = useState<string[]>([]);
  const [gitBranch, setGitBranch] = useState('');
  const [processCount, setProcessCount] = useState<number | null>(null);
  const [remoteOpen, setRemoteOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [featureLessonsOpen, setFeatureLessonsOpen] = useState(false);
  const [messageTimestampsEnabled, setMessageTimestampsEnabled] = useState(() => pref('message-timestamps') === 'true');
  const [startupWarning, setStartupWarning] = useState('');
  const [diagnosticUnread, setDiagnosticUnread] = useState(0);
  const [peerInbox, setPeerInbox] = useState<Array<{ id: string; sender_conversation_id: string; sender_title: string; content: string; created_at: string }>>([]);
  const [besideId, setBesideId] = useState('');
  const [paneCount, setPaneCount] = useState(0);
  const [mainPaneFocused, setMainPaneFocused] = useState(true);
  const [handoffDraft, setHandoffDraft] = useState('');
  const [handoffSource, setHandoffSource] = useState('');
  const [handoffBusy, setHandoffBusy] = useState(false);
  useEffect(() => {
    const panes = (event: Event) => setPaneCount(Number((event as CustomEvent<{ count: number }>).detail?.count ?? 0));
    const focusMain = () => setMainPaneFocused(true);
    const focusSide = () => setMainPaneFocused(false);
    window.addEventListener('atlas:panes-change', panes);
    window.addEventListener('atlas:focus-main-pane', focusMain);
    window.addEventListener('atlas:focus-side-pane', focusSide);
    return () => { window.removeEventListener('atlas:panes-change', panes); window.removeEventListener('atlas:focus-main-pane', focusMain); window.removeEventListener('atlas:focus-side-pane', focusSide); };
  }, []);
  const [rewound, setRewound] = useState<{ conversationId: string; rewindId: string; text: string } | null>(null);
  const [defaultWorkspace, setDefaultWorkspace] = useState(() => pref('default-workspace') ?? '');
  const [tabs, setTabs] = useState<string[]>(() => { try { const saved = JSON.parse(pref('tabs') ?? '[]'); return Array.isArray(saved) ? saved.filter((id): id is string => typeof id === 'string') : []; } catch { return []; } });
  const [closedTabs, setClosedTabs] = useState<string[]>(() => { try { const saved = JSON.parse(pref('closed-tabs') ?? '[]'); return Array.isArray(saved) ? saved.filter((id): id is string => typeof id === 'string') : []; } catch { return []; } });
  const [bindings, setBindings] = useState(loadBindings);
  useEffect(() => {
    if (!store.connected) return;
    let active = true;
    const refresh = () => void api<{ unread: number }>(store.apiBaseUrl, '/api/diagnostics/alerts').then((result) => { if (active) setDiagnosticUnread(result.unread); }).catch(() => undefined);
    refresh(); const timer = window.setInterval(refresh, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [store.connected, store.apiBaseUrl]);
  useEffect(() => {
    const open = () => setSheet('diagnostics');
    window.addEventListener('atlas:open-diagnostics-settings', open);
    return () => window.removeEventListener('atlas:open-diagnostics-settings', open);
  }, []);
  const keybindingsMtimeRef = useRef(-1);
  useEffect(() => {
    const update = () => setBindings(loadBindings());
    window.addEventListener('atlas:shortcuts', update);
    return () => window.removeEventListener('atlas:shortcuts', update);
  }, []);
  useEffect(() => {
    if (!store.connected) return;
    let active = true; let warned = false;
    const refresh = () => void api<{ bindings: Record<string, string[]>; updated_at: number }>(store.apiBaseUrl, '/api/u6/keybindings').then((file) => {
      if (!active || file.updated_at < 0 || file.updated_at === keybindingsMtimeRef.current) return;
      keybindingsMtimeRef.current = file.updated_at; applyFileBindings(file.bindings);
    }).catch((error) => { if (active && !warned) { warned = true; setToast(`keybindings.json 无法读取：${error instanceof Error ? error.message : String(error)}`); } });
    refresh(); const timer = window.setInterval(refresh, 3000);
    void api(store.apiBaseUrl, '/api/u6/retention/run').catch(() => undefined);
    return () => { active = false; window.clearInterval(timer); };
  }, [store.connected, store.apiBaseUrl]);
  const [listening, setListening] = useState(false);
  const [dictationStarting, setDictationStarting] = useState(false);
  const [speechAutoSend, setSpeechAutoSend] = useState(() => pref('speech-auto-send') === 'true');
  const [speechInputMode, setSpeechInputMode] = useState<'toggle' | 'hold'>(() => pref('speech-input-mode') === 'hold' ? 'hold' : 'toggle');
  const [voiceOutput, setVoiceOutput] = useState(() => pref('voice-output') === 'true');
  const [speechRate, setSpeechRate] = useState(() => Number(pref('speech-rate') || 1));
  const [speechVoice, setSpeechVoice] = useState(() => pref('speech-voice') || '');
  const [speechVoices, setSpeechVoices] = useState<SpeechSynthesisVoice[]>([]);
  useEffect(() => {
    if (!store.connected) { setComputerReady(false); return; }
    let current = true;
    const refresh = () => void api<{ ready?: boolean; permission_mode?: string }>(store.apiBaseUrl, '/api/computer/status')
      .then((status) => { if (current) setComputerReady(status.ready === true && status.permission_mode === 'full_access'); })
      .catch(() => { if (current) setComputerReady(false); });
    refresh(); const timer = window.setInterval(refresh, 8000);
    return () => { current = false; window.clearInterval(timer); };
  }, [store.connected, store.apiBaseUrl]);
  const [username, setUsername] = useState(() => pref('username')?.trim() || 'User');
  const [statusBar, setStatusBar] = useState(readStatusBarPreferences);
  const [maximized, setMaximized] = useState(false);
  const [conversationGoal, setConversationGoal] = useState<{ text: string; status: string; turns_used: number; max_turns: number; subgoals: string[]; completed_subgoals?: number[] } | null>(null);
  const updateStatusBar = (key: keyof StatusBarPreferences, visible: boolean) => setStatusBar((current) => {
    const next = { ...current, [key]: visible };
    setPref('statusbar', JSON.stringify(next));
    return next;
  });
  const dictationRef = useRef<{ socket: WebSocket; stream: MediaStream; context: AudioContext; processor: ScriptProcessorNode; prefix: string; finalText: string; stopResolver?: () => void } | null>(null);
  const dictationStartingRef = useRef(false);
  const dictationStoppingRef = useRef(false);
  const spokenSequenceRef = useRef(0);
  const spokenRunRef = useRef('');
  const speechBufferRef = useRef('');
  const firstRunShownRef = useRef(false);
  const threadRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!('speechSynthesis' in window)) return;
    const refresh = () => setSpeechVoices(window.speechSynthesis.getVoices());
    refresh(); window.speechSynthesis.addEventListener('voiceschanged', refresh);
    return () => window.speechSynthesis.removeEventListener('voiceschanged', refresh);
  }, []);
  const speakText = (text: string) => {
    void speakRouted(text, { voice: speechVoice, rate: speechRate, onError: setToast });
  };

  const activeConversation = store.conversations.find((item) => item.id === store.activeConversationId);
  useEffect(() => {
    if (defaultWorkspace || store.conversationsLoading) return;
    const recentWorkspace = store.conversations.find((item) => typeof item.workspace === 'string' && item.workspace.trim())?.workspace;
    if (recentWorkspace) { setPref('default-workspace', recentWorkspace); setDefaultWorkspace(recentWorkspace); }
  }, [defaultWorkspace, store.conversations, store.conversationsLoading]);
  const activeRun = store.runs.find((run) => run.id === store.activeRunId);
  useEffect(() => { if (pref('keep-awake') === 'true') void window.atlasDesktop?.setKeepAwake?.(true); }, []);
  useEffect(() => {
    const active = store.runs.filter((run) => !TERMINAL.includes(run.status));
    const state = active.some((run) => run.status === 'waiting') ? 'waiting' : active.length ? 'running' : 'idle';
    window.atlasDesktop?.setRuntimeState?.(state);
  }, [store.runs]);
  const activeArtifacts = [...store.artifacts.filter((artifact) => artifact.runId === store.activeRunId),
    ...(ultraplanArtifact && ultraplanArtifact.name === `高级计划：${activeConversation?.title ?? ''}` ? [ultraplanArtifact] : [])];
  const activeEvents = activeRun?.events ?? [];
  const lastCanvasEventRef = useRef('');
  const runDone = Boolean(activeRun && TERMINAL.includes(activeRun.status));
  const currentPlan = [...activeEvents].reverse().find((event) => event.type === 'run.plan.updated')?.data.plan as { subtasks?: unknown[] } | undefined;
  const planSteps = Array.isArray(currentPlan?.subtasks) ? currentPlan.subtasks.filter((step): step is { status?: string } => Boolean(step) && typeof step === 'object') : [];
  const completedPlanSteps = planSteps.filter((step) => step.status === 'completed').length;
  const messages = (store.conversationMessages[store.activeConversationId] ?? []).filter((message) => message.role === 'user' || message.role === 'assistant');
  useEffect(() => {
    if (!activeRun || activeRun.conversationId !== store.activeConversationId || activeRun.status !== 'completed') return;
    if (!proactiveEnabled || generatedSuggestionsRun.current === activeRun.id) return;
    const response = [...messages].reverse().find((message) => message.role === 'assistant')?.content ?? '';
    if (!response.trim()) return;
    generatedSuggestionsRun.current = activeRun.id;
    setTurnSuggestions([]);
    // 本轮的目标是最近一条用户消息，不是整段对话的第一条。
    const goal = [...messages].reverse().find((message) => message.role === 'user')?.content ?? '';
    void api<{ suggestions: string[] }>(store.apiBaseUrl, '/api/u6/suggestions', { method: 'POST', json: { goal, response } })
      .then((result) => setTurnSuggestions(Array.isArray(result.suggestions) ? result.suggestions.slice(0, 3) : []))
      .catch(() => setTurnSuggestions([]));
  }, [activeRun?.id, activeRun?.status, activeRun?.conversationId, messages, proactiveEnabled, store.activeConversationId, store.apiBaseUrl]);
  // Once a run finishes the store reloads saved history, which then also contains the run's own turn.
  // The live activity already shows that turn (with its steps), so stop the history just before it.
  const runPrompt = activeRun && activeRun.conversationId === store.activeConversationId
    ? String(activeEvents.find((event) => event.type === 'run.started')?.data.content ?? '') : '';
  const runTurnIndex = runPrompt ? messages.map((message) => message.role === 'user' ? message.content : null).lastIndexOf(runPrompt) : -1;
  // History also keeps tool messages so stored tool calls show their results in the step track.
  const threadMessages = (store.conversationMessages[store.activeConversationId] ?? []).filter((message) => message.role === 'user' || message.role === 'assistant' || message.role === 'tool' || (message.role === 'system' && ['structured_component', 'agent_canvas'].includes(String((message.metadata as Record<string, unknown> | undefined)?.display_kind))));
  const componentSelections = Object.fromEntries(threadMessages.flatMap((message) => {
    if (message.role !== 'user') return [];
    const match = /^结构化卡片 \[([^\]]+)\]「[^」]*」选择：([^\n]+)/.exec(message.content);
    return match ? [[match[1], match[2]]] : [];
  }));
  const canvasHistoryEvents: AgentEvent[] = threadMessages.flatMap((message) => {
    const metadata = message.metadata as Record<string, unknown> | undefined;
    if (message.role !== 'system' || metadata?.display_kind !== 'agent_canvas' || !metadata.canvas || typeof metadata.canvas !== 'object' || Array.isArray(metadata.canvas)) return [];
    return [{ id: message.id, runId: String(metadata.run_id ?? ''), sequence: Number(metadata.sequence ?? 0), type: 'canvas.update', timestamp: message.created_at ?? '', data: metadata.canvas as Record<string, unknown> }];
  });
  const canvasEvents = activeEvents.some((event) => event.type === 'canvas.update') ? activeEvents : canvasHistoryEvents;
  useEffect(() => {
    const latest = [...canvasEvents].reverse().find((event) => event.type === 'canvas.update');
    if (!latest || latest.id === lastCanvasEventRef.current || !store.activeConversationId) return;
    lastCanvasEventRef.current = latest.id;
    showInspectorTab('canvas');
  }, [canvasEvents, store.activeConversationId]);
  const runTurnStart = runTurnIndex >= 0 && runTurnIndex >= messages.length - 3 ? threadMessages.indexOf(messages[runTurnIndex]) : -1;
  const history = runTurnStart >= 0 ? threadMessages.slice(0, runTurnStart) : threadMessages;
  const historyWithBranchNotes = [...history];
  for (const note of history.filter((item) => {
    const metadata = item.metadata as Record<string, unknown> | undefined;
    return metadata?.kind === 'branch_summary' && typeof metadata.fork_message_id === 'string';
  })) {
    const metadata = note.metadata as Record<string, unknown>;
    const oldIndex = historyWithBranchNotes.indexOf(note);
    if (oldIndex >= 0) historyWithBranchNotes.splice(oldIndex, 1);
    const forkIndex = historyWithBranchNotes.findIndex((item) => item.id === metadata.fork_message_id);
    historyWithBranchNotes.splice(forkIndex >= 0 ? forkIndex + 1 : historyWithBranchNotes.length, 0, note);
  }
  const modelName = store.models.find((model) => model.id === store.model)?.name ?? store.model ?? '默认模型';
  useEffect(() => {
    const sessionName = activeConversation?.title?.trim() || '新任务';
    const status = store.busy ? ' · 运行中…' : '';
    document.title = `${sessionName}${status} — Atlas`;
  }, [activeConversation?.title, store.busy]);
  const loadingMessages = store.loadingMessagesConversationId === store.activeConversationId && Boolean(store.activeConversationId);
  const working = store.busy && !store.paused;
  const reply = useMemo(() => {
    const completed = [...activeEvents].reverse().find((event) => event.type === 'message.completed');
    if (completed?.data.content) return String(completed.data.content);
    return activeEvents.filter((event) => event.type === 'message.delta').map((event) => String(event.data.content ?? '')).join('');
  }, [activeEvents]);
  // 当前运行的时间线，与 MessageThread 里的构建保持一致；TimelineNav 也要按它数行。
  const timelineItems = useMemo(() => buildTimeline(activeEvents), [activeEvents]);
  // X2：活动任务要求操作前台窗口、还没等到 computer.foreground_resumed 时，会话区顶部挂一条提示。
  const foregroundEvent = useMemo(() => {
    for (let index = activeEvents.length - 1; index >= 0; index--) {
      const type = activeEvents[index].type;
      if (type === 'computer.foreground_required') return activeEvents[index];
      if (type === 'computer.foreground_resumed') return undefined;
    }
    return undefined;
  }, [activeEvents]);
  const computerRunId = useMemo(() => {
    if (foregroundEvent?.runId) return foregroundEvent.runId;
    if (!activeRun || activeRun.conversationId !== store.activeConversationId) return undefined;
    const hasComputerTool = activeEvents.some((event) => event.type === 'tool.started'
      && String(event.data.name ?? '').startsWith('computer_'));
    return hasComputerTool ? activeRun.id : undefined;
  }, [activeEvents, activeRun, foregroundEvent, store.activeConversationId]);

  const go = useCallback((next: View) => startTransition(() => setView(next)), []);

  // Unsent text survives switching conversations and restarting the app.
  const draftOwnerRef = useRef(store.activeConversationId);
  const skipDraftRestoreRef = useRef(false);
  useEffect(() => {
    if (draftOwnerRef.current === store.activeConversationId) return;
    draftOwnerRef.current = store.activeConversationId;
    if (skipDraftRestoreRef.current) skipDraftRestoreRef.current = false;
    else setInput(readDraft(store.activeConversationId));
    setAttachments([]);
    setFiles([]);
    setMentions([]);
    setEditing(null);
    editingDraftRef.current = null;
  }, [store.activeConversationId]);
  useEffect(() => {
    const conversationId = store.activeConversationId;
    const timer = window.setTimeout(() => {
      if (useAtlasStore.getState().activeConversationId !== conversationId) return;
      writeDraft(conversationId, input);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [input, store.activeConversationId]);
  const notify = useCallback((text: string) => setToast(text), []);
  const saveUsername = (value: string) => {
    const next = value.trim() || 'User';
    setPref('username', next);
    setUsername(next);
  };
  const launchRecipeTemplate = async (request: RecipeLaunchRequest) => {
    if (request.modelId && request.modelId !== store.model) {
      if (!store.models.some((model) => model.id === request.modelId)) throw new Error('配方指定的模型当前不可用');
      await store.selectModel(request.modelId);
    }
    setSheet(null);
    go('chat');
    setInput(request.renderedPrompt);
    setToast('配方提示词已填入输入框；请检查后发送。扩展权限和结构化输出设置尚未接入当前运行时。');
  };

  useEffect(() => { void store.initialize(); }, []);
  useEffect(() => {
    const open = () => setSheet('expert');
    window.addEventListener(OPEN_EXPERT_SETTINGS, open);
    return () => window.removeEventListener(OPEN_EXPERT_SETTINGS, open);
  }, []);
  useEffect(() => window.atlasDesktop?.onDeepLink?.((route) => {
    if (route.type === 'settings') {
      const pane = SETTINGS_NAV.find(([candidate]) => candidate === route.section)?.[0];
      if (!pane) return;
      go('chat');
      setSheet(pane);
      return;
    }
    const openLinkedConversation = async () => {
      const current = useAtlasStore.getState();
      await current.refreshConversations();
      const target = useAtlasStore.getState().conversations.find((item) => item.id === route.conversationId);
      if (!target) {
        setToast('深链接中的对话不存在或已删除。');
        return;
      }
      setSheet(null);
      go('chat');
      await useAtlasStore.getState().openConversation(target);
    };
    void openLinkedConversation().catch((error: unknown) => {
      setToast(error instanceof Error ? error.message : '无法打开深链接中的对话。');
    });
  }), [go]);
  // H8 §10.3/§10.4: the backend boots in parallel with the window; startup progress
  // drives the「启动中」surfaces and re-reads real data once the backend is ready.
  useEffect(() => window.atlasDesktop?.onBackendStartupProgress((progress) => {
    setStartupProgress(progress);
    useAtlasStore.getState().applyStartupProgress(progress);
  }), []);
  useEffect(() => {
    let stale = false;
    const refreshHealth = async () => {
      try {
        const response = await fetch(`${store.apiBaseUrl.replace(/\/$/, '')}/api/health`, { signal: AbortSignal.timeout(2500) });
        if (!response.ok) return;
        const health = await response.json() as { components?: Record<string, unknown> };
        const components = Object.entries(health.components ?? {})
          .filter(([, value]) => {
            if (value && typeof value === 'object') {
              const status = String((value as { status?: unknown }).status ?? '').toLowerCase();
              return status && !['ok', 'ready', 'loaded', 'healthy', 'disabled'].includes(status);
            }
            return !['ok', 'ready', 'loaded', 'healthy', 'disabled'].includes(String(value).toLowerCase());
          })
          .map(([name]) => name);
        if (!stale) setPendingComponents(components);
      } catch { /* the startup banner handles connection failures */ }
    };
    void refreshHealth();
    const timer = window.setInterval(() => void refreshHealth(), 2500);
    return () => { stale = true; window.clearInterval(timer); };
  }, [store.apiBaseUrl]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      const current = useAtlasStore.getState();
      if (!current.connected && !current.backendStarting && !current.conversationsLoading) void current.initialize();
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    let stale = false;
    const refresh = () => void backend.getProcesses().then((items) => { if (!stale) setProcessCount(items.filter((item) => item.status === 'running').length); }).catch(() => { if (!stale) setProcessCount(null); });
    refresh(); const timer = window.setInterval(refresh, 8000);
    return () => { stale = true; window.clearInterval(timer); };
  }, []);
  useEffect(() => {
    const id = store.activeConversationId;
    if (!id || !store.connected) { setConversationGoal(null); return; }
    let stale = false;
    void backend.getConversationGoal(id).then((result) => { if (!stale) setConversationGoal(result.goal as typeof conversationGoal); }).catch(() => { if (!stale) setConversationGoal(null); });
    return () => { stale = true; };
  }, [store.activeConversationId, store.connected]);
  useEffect(() => {
    const id = store.activeConversationId;
    if (!id || !store.connected) { setPeerInbox([]); return; }
    let stale = false;
    const refresh = () => void api<{ messages: typeof peerInbox }>(store.apiBaseUrl, `/api/conversations/${encodeURIComponent(id)}/peer-inbox?unread_only=true`)
      .then((result) => { if (!stale) setPeerInbox(result.messages); })
      .catch(() => { if (!stale) setPeerInbox([]); });
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => { stale = true; window.clearInterval(timer); };
  }, [store.activeConversationId, store.connected, store.apiBaseUrl]);
  useEffect(() => {
    if (activeEvents.at(-1)?.type !== 'run.completed' || !store.activeConversationId || !store.connected) return;
    void backend.getConversationGoal(store.activeConversationId)
      .then((result) => setConversationGoal(result.goal as typeof conversationGoal))
      .catch(() => setConversationGoal(null));
  }, [activeEvents, store.activeConversationId, store.connected]);
  // After onboarding, open model settings once when no gateway key is saved.
  useEffect(() => {
    if (firstRunShownRef.current || !store.connected || store.conversationsLoading || store.apiKeyConfigured) return;
    firstRunShownRef.current = true;
    if (pref('onboarded') !== 'true') return;
    setSheet('models');
  }, [store.apiKeyConfigured, store.connected, store.conversationsLoading]);
  useEffect(() => window.atlasDesktop?.onMaximizeChange(setMaximized), []);

  useEffect(() => {
    const activeTheme = applyStoredTheme(theme);
    document.querySelector('meta[name=theme-color]')?.setAttribute('content', themeInfo(activeTheme).windowColor);
    window.atlasDesktop?.setTheme?.(activeTheme);
    if (activeTheme !== theme) setTheme(activeTheme);
  }, [theme]);

  // Streamed read-aloud. Events are always consumed so switching it on later never replays a backlog;
  // the voice call speaks for itself, so this stays quiet while it is open.
  useEffect(() => {
    if (spokenRunRef.current !== activeRun?.id) {
      spokenRunRef.current = activeRun?.id ?? '';
      spokenSequenceRef.current = activeRun && voiceOutput && !voiceOpen ? 0 : activeRun?.lastEventSequence ?? 0;
      speechBufferRef.current = '';
    }
    const speaking = voiceOutput && !voiceOpen && 'speechSynthesis' in window;
    for (const event of activeEvents) {
      if (event.sequence <= spokenSequenceRef.current) continue;
      spokenSequenceRef.current = event.sequence;
      if (!speaking) continue;
      if (event.type === 'message.delta') {
        speechBufferRef.current += String(event.data.content ?? '');
        const punctuation = /[。！？.!?；;\n]/;
        while (punctuation.test(speechBufferRef.current)) {
          const boundary = speechBufferRef.current.search(punctuation);
          const phrase = speechBufferRef.current.slice(0, boundary + 1).trim();
          speechBufferRef.current = speechBufferRef.current.slice(boundary + 1);
          if (phrase) speakText(phrase);
        }
      } else if (event.type === 'run.completed') {
        const remainder = speechBufferRef.current.trim();
        if (remainder) speakText(remainder);
        speechBufferRef.current = '';
      } else if (['run.failed', 'run.cancelled'].includes(event.type)) {
        speechBufferRef.current = '';
        cancelRoutedSpeech();
      }
    }
  }, [activeEvents, activeRun, voiceOutput, voiceOpen, speechRate, speechVoice, speechVoices]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(''), 2200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    const addContextFile = (event: Event) => {
      const detail = (event as CustomEvent<{ path?: unknown; element?: unknown; label?: unknown }>).detail;
      if (typeof detail?.element === 'string' && detail.element.trim()) {
        const id = `${String(detail.path ?? '')}#${detail.element}`;
        setMentions((current) => current.some((item) => item.kind === 'element' && item.id === id)
          ? current
          : [...current, { kind: 'element', id, label: String(detail.label ?? detail.element), hint: `${String(detail.path ?? '')} · ${String(detail.element)}` }]);
        return;
      }
      const path = detail?.path;
      if (typeof path !== 'string' || !path.trim()) return;
      setMentions((current) => current.some((item) => item.kind === 'file' && item.id === path)
        ? current
        : [...current, { kind: 'file', id: path, label: path.split(/[\\/]/).filter(Boolean).at(-1) ?? path, hint: path }]);
    };
    window.addEventListener('atlas:add-context-file', addContextFile);
    return () => window.removeEventListener('atlas:add-context-file', addContextFile);
  }, []);

  // 滚动定位（进入会话回到原位、流式跟底）由 MessageThread 里的虚拟列表接管。

  const newTask = useCallback(() => {
    if (store.creatingConversation) return;
    go('chat');
    if (store.activeConversationId) skipDraftRestoreRef.current = true;
    store.beginConversationDraft(defaultWorkspace || null);
    setInput('');
    setAttachments([]);
    setFiles([]);
    setMentions([]);
    setEditing(null);
    editingDraftRef.current = null;
  }, [go, store, defaultWorkspace]);
  useEffect(() => {
    const startProjectConversation = (event: Event) => {
      const project = (event as CustomEvent<{ project?: { project_id: string; workspace_path?: string } }>).detail?.project;
      if (!project?.project_id || store.creatingConversation) return;
      go('chat');
      if (store.activeConversationId) skipDraftRestoreRef.current = true;
      store.beginConversationDraft(project.workspace_path || defaultWorkspace || null);
      setPendingProjectId(project.project_id);
      setInput(''); setAttachments([]); setFiles([]); setMentions([]); setEditing(null);
    };
    window.addEventListener('atlas:new-project-conversation', startProjectConversation);
    return () => window.removeEventListener('atlas:new-project-conversation', startProjectConversation);
  }, [defaultWorkspace, go, store]);
  // First run: once the backend answers and no model key is saved, walk through setup (only once).
  useEffect(() => {
    if (store.connected && store.configLoaded && !store.apiKeyConfigured && pref('onboarded') !== 'true') setOnboardingOpen(true);
  }, [store.connected, store.configLoaded, store.apiKeyConfigured]);
  useEffect(() => {
    if (!store.connected) return;
    let stale = false;
    let timer: number | undefined;
    // 启动瞬间组件还在拉起，"正在启动"类告警是暂态：每 5 秒复查，最多 60 秒，稳定后只报真正的问题。
    const STARTING = /正在启动|仍在启动|starting/i;
    const check = (attempt: number) => void api<{ checks?: Array<{ id: string; label: string; status: string; detail: string }> }>(store.apiBaseUrl, '/api/diagnostics')
      .then((report) => {
        if (stale) return;
        const problems = (report.checks ?? []).filter((item) => ['warning', 'error'].includes(item.status));
        const transient = problems.some((item) => STARTING.test(item.detail));
        if (transient && attempt < 12) { timer = window.setTimeout(() => check(attempt + 1), 5000); return; }
        setStartupWarning(problems.length ? problems.slice(0, 3).map((item) => `${item.label}：${item.detail}`).join('；') : '');
      }).catch(() => undefined);
    check(0);
    return () => { stale = true; if (timer) window.clearTimeout(timer); };
  }, [store.connected, store.apiBaseUrl]);
  const closeOnboarding = () => { setOnboardingOpen(false); setPref('onboarded', 'true'); };

  const stopWakeCapture = () => {
    const session = wakeSessionRef.current;
    wakeSessionRef.current = null;
    if (!session) return;
    session.processor.disconnect(); session.stream.getTracks().forEach((track) => track.stop());
    void session.context.close();
    try { if (session.socket.readyState === WebSocket.OPEN) session.socket.send(JSON.stringify({ type: 'end' })); session.socket.close(); } catch { /* socket already closed */ }
  };
  const startVoice = async () => {
    if (voiceOpen) { setVoiceOpen(false); return; }
    if (dictationStartingRef.current) { setToast('语音识别正在连接，请稍等后再切换模式'); return; }
    stopWakeCapture();
    if (dictationRef.current) await stopSpeechInput();
    if (!navigator.mediaDevices?.getUserMedia) { setToast('当前设备没有麦克风访问能力'); return; }
    cancelRoutedSpeech();
    setVoiceOpen(true);
  };

  const dismissMemoryMarkerReview = () => {
    if (!memoryMarkerDrafts) return;
    setMemoryMarkerDrafts(null);
    setToast('消息已发送；记忆标记未保存');
  };
  const saveMemoryMarkerDrafts = async () => {
    if (!memoryMarkerDrafts?.length || memoryMarkerSaving) return;
    setMemoryMarkerSaving(true);
    let saved = 0;
    try {
      for (const item of memoryMarkerDrafts) {
        await api<{ id: string; path: string }>(store.apiBaseUrl, '/api/memlib/add', {
          method: 'POST', json: { path: item.path, text: item.text, session: item.session, ref: item.ref },
        });
        saved += 1;
      }
      setMemoryMarkerDrafts(null);
      setToast(`已保存 ${saved} 条记忆`);
      window.dispatchEvent(new Event('atlas:memories-updated'));
    } catch (error) {
      if (saved) setMemoryMarkerDrafts((current) => current?.slice(saved) ?? null);
      setToast(`记忆保存${saved ? `（已保存 ${saved} 条）` : ''}失败：${error instanceof Error ? error.message : String(error)}`);
    } finally { setMemoryMarkerSaving(false); }
  };

  const submit = async (fromHome: boolean, immediate = false, inputOverride?: string) => {
    const submittedInput = inputOverride ?? input;
    if (!submittedInput.trim() && !attachments.length && !files.length && !mentions.length) return;
    if (!fromHome && activeRun && !runDone && !immediate && !scheduleBypass.current) {
      setSchedulePromptOpen(true);
      return;
    }
    scheduleBypass.current = false;
    let text = submittedInput;
    const memoryCandidates = extractMemoryMarkers(submittedInput);
    const images = attachments;
    const documents = files.map(({ name, mime, data_base64 }) => ({ name, mime, data_base64 }));
    const elementRefs = mentions.filter((item) => item.kind === 'element');
    if (elementRefs.length) text += `\n\n请根据以下 PPT 元素引用进行精确修改：\n${elementRefs.map((item) => `- ${item.label}（文件/定位：${item.id}）`).join('\n')}`;
    const sessionRefs = mentions.filter((item) => item.kind === 'conversation');
    if (sessionRefs.length) text += `\n\n${sessionRefs.map((item) => `请用 read_session 读取会话 ${item.id}（${item.label}）。`).join('\n')}`;
    for (const reference of mentions.filter((item) => item.kind === 'resource')) {
      const [server_name, ...uriParts] = reference.id.split('\n');
      const uri = uriParts.join('\n');
      const payload = await api<{ contents: Array<{ text?: string; mime_type?: string }> }>(store.apiBaseUrl, '/api/mcp/resources/read', {
        method: 'POST', json: { server_name, uri },
      });
      const content = payload.contents.map((item) => item.text ?? '').join('\n');
      const bytes = new TextEncoder().encode(content); let binary = ''; bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
      documents.push({ name: `mcp-${reference.label.replace(/[^\p{L}\p{N}._-]+/gu, '_')}.txt`, mime: 'text/plain', data_base64: btoa(binary) });
    }
    // `!command` runs straight in the terminal panel instead of going to the Agent.
    if (!fromHome && text.trim().startsWith('!') && text.trim().length > 1) {
      if (typeof activeConversation?.workspace !== 'string' || !activeConversation.workspace) { setToast('先选工作目录，终端会在那里打开'); return; }
      if (activeConversation.workspace.startsWith('ssh://')) { setToast('远程目录没有终端面板，把命令直接交给 Atlas 去运行'); return; }
      setTerminalCommand({ id: crypto.randomUUID(), text: text.trim().slice(1).trim() });
      setInput('');
      writeDraft(store.activeConversationId, '');
      showInspectorTab('terminal');
      return;
    }
    if (editing && !fromHome) {
      if (attachments.length || files.length || mentions.length) {
        setToast('修改历史消息目前只支持文本，请先移除附件和引用后再发送');
        return;
      }
      setInput('');
      setEditing(null);
      editingDraftRef.current = null;
      void store.editMessage(editing.id, text);
      return;
    }
    if (fromHome && homeMode === 'image') {
      setCreatePrompt(text.trim());
      setInput('');
      go('create');
      return;
    }
    setInput('');
    writeDraft(store.activeConversationId, '');
    setAttachments([]);
    setFiles([]);
    setMentions([]);
    if (fromHome) {
      go('chat');
      // Home always starts something new, unless the open conversation is still empty.
      if (store.activeConversationId && messages.length) {
        skipDraftRestoreRef.current = true;
        store.beginConversationDraft(defaultWorkspace || null);
      }
    }
    const refs = { files: mentions.filter((item) => item.kind === 'file').map((item) => item.id), conversations: [] };
    setMentions([]);
    const messageSkills = resolveMessageSkillReferences(text, store.skills.map((skill) => skill.name));
    const existingOverrides = useAtlasStore.getState().pendingRunOverrides;
    store.setPendingRunOverrides({ ...existingOverrides, tool_deny: computerUseEnabled ? existingOverrides?.tool_deny : [...new Set([...(existingOverrides?.tool_deny ?? []), 'computer_*'])] });
    const sent = immediate && activeRun && !runDone
      ? store.sendNow(text, images, documents, refs)
      : store.sendMessage(text, images, documents, refs, undefined, undefined, messageSkills);
    void sent.then(async () => {
      const projectId = pendingProjectId;
      const conversationId = useAtlasStore.getState().activeConversationId;
      if (memoryCandidates.length) {
        let sourceMessageId = '';
        if (conversationId) {
          for (let attempt = 0; attempt < 5 && !sourceMessageId; attempt += 1) {
            if (attempt) await new Promise((resolve) => window.setTimeout(resolve, 180));
            const rows = await api<Array<{ id?: string; role?: string; content?: unknown }>>(
              store.apiBaseUrl, `/api/conversations/${encodeURIComponent(conversationId)}/messages?limit=30`,
            ).catch(() => []);
            const source = [...rows].reverse().find((row) => row.role === 'user'
              && typeof row.content === 'string' && row.content.trim() === submittedInput.trim());
            sourceMessageId = String(source?.id ?? '');
          }
        }
        const ref = sourceMessageId && conversationId ? `${conversationId}@${sourceMessageId}` : '';
        setMemoryMarkerDrafts(memoryCandidates.map((candidate) => ({
          text: candidate, path: '我.md', session: ref ? conversationId : undefined, ref: ref || undefined,
        })));
      }
      if (!projectId || !conversationId) return;
      try {
        await api(store.apiBaseUrl, `/api/projects/${encodeURIComponent(projectId)}/conversations`, { method: 'POST', json: { conversation_id: conversationId } });
        window.dispatchEvent(new Event('atlas:projects-updated'));
      } catch (error) { setToast(`会话已创建，但未能归入项目：${error instanceof Error ? error.message : String(error)}`); }
      setPendingProjectId('');
    });
  };
  /** Images go to the model as pictures; every other file rides along as a document. */
  const addFiles = (picked: FileList | null) => {
    if (!picked?.length) return;
    const all = Array.from(picked);
    const imageTypes = ['image/png', 'image/jpeg', 'image/webp'];
    addDocuments(all.filter((file) => !imageTypes.includes(file.type)));
    const images = all.filter((file) => imageTypes.includes(file.type));
    if (images.length) addImages(images);
  };
  const addFolderReferences = (folders: Array<{ name: string; path: string; count: number }>) => {
    const references = folders.map((folder) => {
      const json = JSON.stringify({ folder_reference: folder.path, file_count: folder.count });
      const bytes = new TextEncoder().encode(json);
      let binary = '';
      bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
      return { name: `📁 ${folder.name}（${folder.count} 个文件）`, mime: 'application/vnd.atlas.folder-reference+json', data_base64: btoa(binary), size: bytes.length };
    });
    setFiles((current) => [...current, ...references]);
    setToast(`已加入 ${folders.length} 个文件夹引用；只发送路径和文件数`);
  };
  const addDocuments = (picked: File[]) => {
    if (!picked.length) return;
    const conversationId = store.activeConversationId;
    const tooBig = picked.find((file) => file.size > 10 * 1024 * 1024);
    if (tooBig) { setToast(`${tooBig.name} 超过 10 MB，发不了`); return; }
    if (files.reduce((sum, file) => sum + file.size, 0) + picked.reduce((sum, file) => sum + file.size, 0) > 20 * 1024 * 1024) { setToast('一条消息的文件加起来不能超过 20 MB'); return; }
    Promise.allSettled(picked.map((file) => new Promise<RunFile & { size: number }>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => typeof reader.result === 'string'
        ? resolve({ name: file.name, mime: file.type || 'application/octet-stream', data_base64: reader.result.slice(reader.result.indexOf(',') + 1), size: file.size })
        : reject(new Error('无法读取文件'));
      reader.onprogress = (event) => {
        if (event.lengthComputable) setAttachmentProgress(`正在读取 ${file.name}（${Math.round(event.loaded / event.total * 100)}%）`);
      };
      reader.onerror = () => reject(new Error('无法读取文件'));
      reader.onloadend = () => { attachmentReadsRef.current -= 1; if (!attachmentReadsRef.current) setAttachmentProgress(''); };
      attachmentReadsRef.current += 1;
      setAttachmentProgress(`正在读取 ${file.name}`);
      reader.readAsDataURL(file);
    }))).then((results) => {
      if (useAtlasStore.getState().activeConversationId !== conversationId) return;
      const read = results.flatMap((result) => result.status === 'fulfilled' ? [result.value] : []);
      const failed = results.flatMap((result, index) => result.status === 'rejected' ? [picked[index]] : []);
      if (read.length) setFiles((current) => [...current, ...read]);
      if (failed.length) { setFailedAttachmentReads((current) => [...current, ...failed]); setToast(`读取 ${failed.length} 个文件失败，可重试`); }
    });
  };
  const addImages = (picked: File[]) => {
    const conversationId = store.activeConversationId;
    const selected = picked.slice(0, 4 - attachments.length);
    if (!selected.length) { setToast('每条消息最多 4 张图片'); return; }
    if (selected.some((file) => file.size > 4 * 1024 * 1024)) { setToast('单张图片不能超过 4 MiB'); return; }
    const queuedBytes = attachments.reduce((sum, image) => sum + Math.max(0, Math.floor((image.length - image.indexOf(',') - 1) * 3 / 4)), 0);
    if (queuedBytes + selected.reduce((sum, file) => sum + file.size, 0) > 8 * 1024 * 1024) { setToast('单条消息的图片总大小不能超过 8 MiB'); return; }
    Promise.allSettled(selected.map((file) => new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('无法读取图片'));
      reader.onerror = () => reject(new Error('无法读取图片'));
      reader.onprogress = (event) => {
        if (event.lengthComputable) setAttachmentProgress(`正在读取 ${file.name}（${Math.round(event.loaded / event.total * 100)}%）`);
      };
      reader.onloadend = () => { attachmentReadsRef.current -= 1; if (!attachmentReadsRef.current) setAttachmentProgress(''); };
      attachmentReadsRef.current += 1;
      setAttachmentProgress(`正在读取 ${file.name}`);
      reader.readAsDataURL(file);
    }))).then((results) => {
      if (useAtlasStore.getState().activeConversationId !== conversationId) return;
      const images = results.flatMap((result) => result.status === 'fulfilled' ? [result.value] : []);
      const failed = results.flatMap((result, index) => result.status === 'rejected' ? [selected[index]] : []);
      if (images.length) setAttachments((current) => [...current, ...images].slice(0, 4));
      if (failed.length) { setFailedAttachmentReads((current) => [...current, ...failed]); setToast(`读取 ${failed.length} 张图片失败，可重试`); }
    });
  };
  const retryFailedAttachments = () => {
    const retry = failedAttachmentReads;
    setFailedAttachmentReads([]);
    const imageTypes = ['image/png', 'image/jpeg', 'image/webp'];
    addDocuments(retry.filter((file) => !imageTypes.includes(file.type)));
    addImages(retry.filter((file) => imageTypes.includes(file.type)));
  };
  const addRecentScreenshots = (screenshots: RecentScreenshot[]) => {
    const available = Math.max(0, 4 - attachments.length);
    if (!available) { setToast('每条消息最多 4 张图片'); return; }
    const selected = screenshots.slice(0, available);
    setAttachments((items) => [...new Set([...items, ...selected.map((item) => item.dataUrl)])].slice(0, 4));
    setToast(selected.length < screenshots.length ? `已加入 ${selected.length} 张截图；每条消息最多 4 张图片` : `已加入 ${selected.length} 张截图`);
  };
  const addRecentScreenshot = (screenshot: RecentScreenshot) => addRecentScreenshots([screenshot]);
  const captureWindow = async (sourceId: string) => {
    const conversationId = useAtlasStore.getState().activeConversationId;
    try {
      const screenshot = await window.atlasDesktop?.captureWindow?.(sourceId, conversationId);
      if (!screenshot) return;
      setRecentScreenshots((items) => [screenshot, ...items.filter((item) => item.id !== screenshot.id)].slice(0, 8));
      addRecentScreenshot(screenshot);
    } catch (error) { setToast(`窗口截图失败：${error instanceof Error ? error.message : String(error)}`); }
  };
  const attachDrawing = (dataUrl: string): boolean => {
    if (attachments.length >= 4) { setToast('每条消息最多 4 张图片'); return false; }
    const bytes = Math.max(0, Math.floor((dataUrl.length - dataUrl.indexOf(',') - 1) * 3 / 4));
    if (bytes > 4 * 1024 * 1024) { setToast('白板图片超过 4 MiB，无法附加'); return false; }
    const queuedBytes = attachments.reduce((sum, image) => sum + Math.max(0, Math.floor((image.length - image.indexOf(',') - 1) * 3 / 4)), 0);
    if (queuedBytes + bytes > 8 * 1024 * 1024) { setToast('单条消息的图片总大小不能超过 8 MiB'); return false; }
    setAttachments((current) => [...current, dataUrl]);
    setToast('白板已作为图片附加到当前消息');
    return true;
  };
  const chooseWorkspace = async () => {
    const current = typeof activeConversation?.workspace === 'string' ? activeConversation.workspace : store.draftWorkspace ?? undefined;
    const picked = window.atlasDesktop?.selectDirectory
      ? await window.atlasDesktop.selectDirectory(current)
      : window.prompt('工作目录的完整路径', current ?? '')?.trim() || null;
    if (!picked) return;
    const conversationId = useAtlasStore.getState().activeConversationId;
    if (conversationId) store.setWorkspace(conversationId, picked);
    else store.setDraftWorkspace(picked);
    setPref('default-workspace', picked);
    setDefaultWorkspace(picked);
    setToast(`工作目录：${picked}`);
  };
  const stopSpeechInput = async (send = speechAutoSend) => {
    const session = dictationRef.current;
    if (!session) { setListening(false); return; }
    dictationStoppingRef.current = true;
    dictationRef.current = null;
    session.processor.disconnect(); session.stream.getTracks().forEach((track) => track.stop());
    setListening(false);
    try {
      if (session.socket.readyState === WebSocket.OPEN) {
        await new Promise<void>((resolve) => {
          const timeout = window.setTimeout(resolve, 1200);
          session.stopResolver = () => { window.clearTimeout(timeout); resolve(); };
          session.socket.send(JSON.stringify({ type: 'end' }));
        });
      }
    } catch { /* socket already closed */ }
    session.stopResolver = undefined;
    try { session.socket.close(); } catch { /* already closed */ }
    void session.context.close();
    dictationStoppingRef.current = false;
    const transcript = session.finalText.trim();
    if (send && transcript) {
      const content = `${session.prefix}${session.prefix ? ' ' : ''}${transcript}`.trim();
      setInput(content);
      await submit(false, true, content);
      setToast('语音转写已自动发送');
    }
  };
  const toggleSpeechInput = async (startOnly = false) => {
    if (voiceOpen) { setVoiceOpen(false); setToast('已结束语音通话；再次操作可开始听写'); return; }
    if (dictationStoppingRef.current) return;
    if (listening || dictationRef.current) { if (!startOnly) void stopSpeechInput(); return; }
    if (dictationStartingRef.current) return;
    if (!navigator.mediaDevices?.getUserMedia) { setToast('当前环境无法访问麦克风'); return; }
    stopWakeCapture();
    dictationStartingRef.current = true;
    setDictationStarting(true);
    try {
      setToast('正在连接本地语音识别；首次使用会自动下载模型并显示进度');
      const selectedInput = await getSelectedInputStream({ channelCount: 1, echoCancellation: true, noiseSuppression: true });
      const stream = selectedInput.stream;
      if (voiceOpen) { stream.getTracks().forEach((track) => track.stop()); return; }
      if (selectedInput.usedFallback) setToast('所选麦克风已断开，已回落到系统默认输入设备。');
      const context = new AudioContext();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const socketUrl = new URL('/ws/asr', store.apiBaseUrl);
      socketUrl.protocol = socketUrl.protocol === 'https:' ? 'wss:' : 'ws:';
      const socket = new WebSocket(socketUrl);
      const session: { socket: WebSocket; stream: MediaStream; context: AudioContext; processor: ScriptProcessorNode; prefix: string; finalText: string; stopResolver?: () => void } = { socket, stream, context, processor, prefix: input.trim(), finalText: '' };
      dictationRef.current = session;
      const render = (partial = '') => setInput(`${session.prefix}${session.prefix ? ' ' : ''}${session.finalText}${partial}`);
      socket.onmessage = (event) => {
        try {
        const message = JSON.parse(String(event.data)) as { type?: string; text?: string; detail?: string; progress?: number };
          if (message.type === 'final' && message.text) { session.finalText += `${session.finalText ? ' ' : ''}${message.text}`; render(); }
          else if (message.type === 'ended') session.stopResolver?.();
          else if (message.type === 'partial') render(message.text || '');
          else if (message.type === 'preparing') setToast(message.detail || '正在准备本地语音模型…');
          else if (message.type === 'progress') setToast(`正在下载语音模型… ${Math.round(Number(message.progress || 0) * 100)}%`);
          else if (message.type === 'ready') setToast('本地语音模型已就绪');
          else if (message.type === 'error') setToast(message.detail || '本地语音识别失败');
        } catch { /* ignore malformed ASR event */ }
      };
      socket.onerror = () => setToast('本地语音识别连接失败');
      socket.onclose = () => { if (dictationRef.current === session) { dictationRef.current = null; setListening(false); } };
      await new Promise<void>((resolve, reject) => { socket.addEventListener('open', () => resolve(), { once: true }); socket.addEventListener('error', () => reject(new Error('本地语音识别连接失败')), { once: true }); });
      const downsample = (samples: Float32Array, from: number) => {
        if (from <= 16000) return samples;
        const ratio = from / 16000;
        const output = new Float32Array(Math.floor(samples.length / ratio));
        for (let i = 0; i < output.length; i++) output[i] = samples[Math.floor(i * ratio)];
        return output;
      };
      processor.onaudioprocess = (event) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const samples = downsample(event.inputBuffer.getChannelData(0), context.sampleRate);
        const pcm = new Int16Array(samples.length);
        for (let i = 0; i < samples.length; i++) pcm[i] = Math.max(-1, Math.min(1, samples[i])) * 0x7fff;
        socket.send(pcm.buffer);
      };
      source.connect(processor); processor.connect(context.destination);
      setListening(true); setToast('正在使用本地语音识别；再次点击麦克风或按全局快捷键结束');
    } catch (error) {
      dictationRef.current?.stream.getTracks().forEach((track) => track.stop());
      dictationRef.current = null; setListening(false);
      setToast(`语音听写启动失败：${error instanceof Error ? error.message : String(error)}`);
    } finally { dictationStartingRef.current = false; setDictationStarting(false); }
  };
  const toggleSpeechInputRef = useRef(toggleSpeechInput);
  toggleSpeechInputRef.current = toggleSpeechInput;
  useEffect(() => { setPref('speech-auto-send', String(speechAutoSend)); }, [speechAutoSend]);
  useEffect(() => { setPref('speech-input-mode', speechInputMode); }, [speechInputMode]);
  useEffect(() => {
    setPref('wake-enabled', String(wakeEnabled));
  }, [wakeEnabled]);
  useEffect(() => window.atlasDesktop?.onVoiceHotkeyStop?.(() => {
    if (voiceOpen) setVoiceOpen(false);
    void stopSpeechInput(false).finally(() => window.atlasDesktop?.acknowledgeVoiceHotkeyStop?.());
  }), [voiceOpen, speechAutoSend]);
  useEffect(() => window.atlasDesktop?.onVoiceHudResult?.((transcript) => {
    const text = transcript.trim();
    if (!text) return;
    setInput(text);
    if (speechAutoSend) {
      window.setTimeout(() => { void submit(false, true, text); }, 0);
    } else {
      setToast('语音转写已放入草稿');
    }
  }), [speechAutoSend, submit]);
  useEffect(() => {
    setPref('wake-word', wakeWord);
  }, [wakeWord]);
  useEffect(() => {
    if (!wakeEnabled || voiceOpen || listening || dictationStarting || !store.connected || !navigator.mediaDevices?.getUserMedia) return;
    let active = true;
    let starting = false;
    const stop = () => {
      const session = wakeSessionRef.current;
      wakeSessionRef.current = null;
      if (!session) return;
      session.processor.disconnect(); session.stream.getTracks().forEach((track) => track.stop()); void session.context.close();
      try { session.socket.send(JSON.stringify({ type: 'end' })); session.socket.close(); } catch { /* socket already closed */ }
    };
    const begin = async () => {
      if (starting || !active || voiceOpen) return;
      starting = true;
      try {
        if (!active) return;
        const selectedInput = await getSelectedInputStream({ channelCount: 1, echoCancellation: true, noiseSuppression: true });
        const stream = selectedInput.stream;
        if (selectedInput.usedFallback) setToast('所选麦克风已断开，唤醒监听已回落到系统默认输入设备。');
        const context = new AudioContext(); const source = context.createMediaStreamSource(stream); const processor = context.createScriptProcessor(4096, 1, 1);
        const url = new URL('/ws/asr', store.apiBaseUrl); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
        const socket = new WebSocket(url); const session = { socket, stream, context, processor }; wakeSessionRef.current = session;
        socket.onmessage = (event) => {
          try {
            const message = JSON.parse(String(event.data)) as { type?: string; text?: string; progress?: number; detail?: string };
            if (message.type === 'error') { setToast(message.detail || '本地唤醒词模型准备失败'); return; }
            if (message.type === 'progress') { setToast(`正在准备本地唤醒识别… ${Math.round(Number(message.progress || 0) * 100)}%`); return; }
            if (message.type !== 'final' || !message.text) return;
            setWakeTranscript(message.text);
            const normalize = (value: string) => value.toLocaleLowerCase().replace(/[\s，。！？,.!?]/g, '');
            if (normalize(message.text).includes(normalize(wakeWord)) && active) { stop(); setWakeTranscript(''); setVoiceOpen(true); }
          } catch { /* ignore malformed local ASR response */ }
        };
        socket.onclose = () => { if (wakeSessionRef.current === session) wakeSessionRef.current = null; };
        await new Promise<void>((resolve, reject) => { socket.addEventListener('open', () => resolve(), { once: true }); socket.addEventListener('error', () => reject(new Error('本地唤醒监听连接失败')), { once: true }); });
        processor.onaudioprocess = (event) => {
          if (socket.readyState !== WebSocket.OPEN) return;
          const data = event.inputBuffer.getChannelData(0); const ratio = context.sampleRate / 16000; const samples = ratio <= 1 ? data : Float32Array.from({ length: Math.floor(data.length / ratio) }, (_, index) => data[Math.floor(index * ratio)]);
          const pcm = new Int16Array(samples.length); for (let i = 0; i < samples.length; i++) pcm[i] = Math.max(-1, Math.min(1, samples[i])) * 0x7fff;
          socket.send(pcm.buffer);
        };
        source.connect(processor); processor.connect(context.destination);
      } catch { stop(); }
      finally { starting = false; }
    };
    void begin();
    return () => { active = false; stop(); };
  }, [wakeEnabled, wakeWord, voiceOpen, listening, dictationStarting, store.connected, store.apiBaseUrl]);
  const readLastReply = () => {
    const lastReply = [...messages].reverse().find((message) => message.role === 'assistant')?.content || (runDone ? reply : '');
    if (!lastReply || !('speechSynthesis' in window)) { setToast('还没有可以朗读的回复'); return; }
    cancelRoutedSpeech();
    speakText(lastReply);
  };
  const toggleVoiceOutput = () => {
    const enabled = !voiceOutput;
    setVoiceOutput(enabled);
    setPref('voice-output', String(enabled));
    if (!enabled) { speechBufferRef.current = ''; cancelRoutedSpeech(); }
    setToast(enabled ? '新回复会自动朗读' : '已关闭自动朗读');
  };
  const chooseTheme = (next: Theme) => { clearCustomTheme(); setTheme(next); setPref('appearance', next); setPref('theme-mode', 'manual'); };
  const toggleTheme = () => { const next = nextTheme(theme); chooseTheme(next); setToast(`已切换到${themeInfo(next).label}`); };
  const toggleMini = () => setSideMini((current) => { setPref('sidebar-mini', String(!current)); return !current; });
  const toggleInspector = (open?: boolean) => setInspectorOpen((current) => { const next = open ?? !current; setPref('canvas', String(next)); return next; });
  const showInspectorTab = (tab: InspectorTab) => { setInspectorTab(tab); toggleInspector(true); };
  useEffect(() => {
    const onSelectionToDraft = (event: Event) => {
      const text = (event as CustomEvent<{ text?: unknown }>).detail?.text;
      if (typeof text !== 'string' || !text.trim()) return;
      const quote = text.trim().split(/\r?\n/).map((line) => `> ${line}`).join('\n');
      go('chat');
      setInput((current) => `${current.trim() ? `${current.trimEnd()}\n\n` : ''}${quote}\n\n`);
      setToast('已把选中文本加入消息草稿');
      requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('textarea[aria-label="消息内容"]')?.focus());
    };
    window.addEventListener('atlas:add-selection-to-draft', onSelectionToDraft);
    return () => window.removeEventListener('atlas:add-selection-to-draft', onSelectionToDraft);
  }, [go]);
  useEffect(() => {
    const onSelectionForSideChat = (event: Event) => {
      const text = (event as CustomEvent<{ text?: unknown }>).detail?.text;
      if (typeof text === 'string' && text.trim()) setSide({ open: true, question: `请围绕这段选中文本追问：\n\n> ${text.trim()}` });
    };
    window.addEventListener('atlas:side-chat-selection', onSelectionForSideChat);
    return () => window.removeEventListener('atlas:side-chat-selection', onSelectionForSideChat);
  }, []);
  useEffect(() => {
    const onChartSelection = (event: Event) => {
      const detail = (event as CustomEvent<{ node?: unknown; source?: unknown }>).detail;
      const node = typeof detail?.node === 'string' ? detail.node.slice(0, 300) : '';
      const source = typeof detail?.source === 'string' ? detail.source.slice(0, 4000) : '';
      if (node) void useAtlasStore.getState().sendMessage(`我在图表中选择了节点“${node}”。请解释它与图中其他节点的关系，并根据需要继续修改图表。\n\n图表源码：\n\`\`\`mermaid\n${source}\n\`\`\``);
    };
    window.addEventListener('atlas:chart-selection', onChartSelection);
    return () => window.removeEventListener('atlas:chart-selection', onChartSelection);
  }, []);
  useEffect(() => window.atlasDesktop?.onFloatingComposerSubmit?.((text) => {
    go('chat');
    void useAtlasStore.getState().sendMessage(text);
  }), [go]);
  // C6R: /review「打开文件」请求 → 切到文件面板;FilesPanel 自己消费请求并定位行。
  useEffect(() => { if (storeData.fileOpenRequest) showInspectorTab('files'); }, [storeData.fileOpenRequest]);
  useEffect(() => {
    const openPreview = (event: Event) => {
      const path = (event as CustomEvent<{ path?: string }>).detail?.path;
      if (!path) return;
      setPreviewFile(path);
      showInspectorTab('preview');
    };
    window.addEventListener('atlas:open-file-preview', openPreview);
    return () => window.removeEventListener('atlas:open-file-preview', openPreview);
  }, []);
  useEffect(() => {
    const revealInTree = (event: Event) => {
      const path = (event as CustomEvent<{ path?: string }>).detail?.path;
      if (!path) return;
      setPreviewFile(path);
      showInspectorTab('files');
    };
    window.addEventListener('atlas:reveal-file-in-tree', revealInTree);
    return () => window.removeEventListener('atlas:reveal-file-in-tree', revealInTree);
  }, []);
  const openConversation = (conversation: (typeof store.conversations)[number]) => {
    if (conversation.id !== store.activeConversationId) {
      setAttachments([]);
      setFiles([]);
      setMentions([]);
      setEditing(null);
      editingDraftRef.current = null;
    }
    go('chat');
    void store.openConversation(conversation);
  };
  const conversationWindowId = useMemo(() => new URLSearchParams(window.location.search).get('conversationId'), []);
  const newSessionWindow = useMemo(() => new URLSearchParams(window.location.search).get('newSession') === '1', []);
  const conversationWindowOpened = useRef(false);
  useEffect(() => {
    if (!newSessionWindow || conversationWindowOpened.current || !store.connected || store.conversationsLoading) return;
    conversationWindowOpened.current = true;
    go('chat');
    store.beginConversationDraft(store.draftWorkspace || null);
  }, [newSessionWindow, store.connected, store.conversationsLoading, store.draftWorkspace]);
  useEffect(() => {
    if (!conversationWindowId || conversationWindowOpened.current || !store.connected || store.conversationsLoading) return;
    const target = store.conversations.find((item) => item.id === conversationWindowId);
    if (!target) { conversationWindowOpened.current = true; setToast('找不到要打开的对话'); return; }
    conversationWindowOpened.current = true;
    go('chat');
    void store.openConversation(target);
  }, [conversationWindowId, store.connected, store.conversations, store.conversationsLoading]);
  const draft = (text: string) => {
    go('chat');
    if (store.activeConversationId) skipDraftRestoreRef.current = true;
    store.beginConversationDraft(defaultWorkspace || null);
    setInput(text);
  };
  const suggest = (suggestion: Suggestion) => { setInput(suggestion.text); setHomeMode(suggestion.mode ?? 'chat'); };
  const askSelectedText = () => {
    const selected = window.getSelection()?.toString().trim();
    if (!selected) { setToast('先选中一段对话或页面文字，再使用“询问选中文本”'); return; }
    go('chat');
    setInput(`请基于以下选中内容回答或继续处理：\n\n${selected}`);
    setToast('选中文本已放入消息草稿，可继续编辑后发送');
    requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('textarea[aria-label="消息内容"]')?.focus());
  };

  // Every conversation opened in the chat view becomes a tab; tabs of deleted conversations drop out.
  useEffect(() => {
    const id = store.activeConversationId;
    if (view !== 'chat' || !id) return;
    setTabs((current) => current.includes(id) ? current : [...current, id].slice(-12));
  }, [view, store.activeConversationId]);
  useEffect(() => {
    if (!store.conversations.length) return;
    const known = new Set(store.conversations.map((item) => item.id));
    setTabs((current) => { const next = current.filter((id) => known.has(id)); return next.length === current.length ? current : next; });
  }, [store.conversations]);
  useEffect(() => { setPref('tabs', JSON.stringify(tabs)); }, [tabs]);
  useEffect(() => { setPref('closed-tabs', JSON.stringify(closedTabs.slice(-12))); }, [closedTabs]);
  const closeTab = (id: string) => {
    const index = tabs.indexOf(id);
    const next = tabs.filter((item) => item !== id);
    setClosedTabs((current) => [...current.filter((item) => item !== id), id].slice(-12));
    setTabs(next);
    if (id !== store.activeConversationId || view !== 'chat') return;
    const neighbour = next[Math.min(index, next.length - 1)];
    const conversation = neighbour ? store.conversations.find((item) => item.id === neighbour) : undefined;
    if (conversation) openConversation(conversation); else go('home');
  };
  const reopenClosedTab = () => {
    const id = [...closedTabs].reverse().find((candidate) => store.conversations.some((item) => item.id === candidate));
    if (!id) { setToast('没有最近关闭的会话'); return; }
    setClosedTabs((current) => { const index = current.lastIndexOf(id); return current.filter((_, itemIndex) => itemIndex !== index); });
    setTabs((current) => current.includes(id) ? current : [...current, id].slice(-12));
    const conversation = store.conversations.find((item) => item.id === id);
    if (conversation) openConversation(conversation);
  };
  const cycleTab = (step: number) => {
    if (tabs.length < 2) return;
    const index = tabs.indexOf(store.activeConversationId);
    const target = store.conversations.find((item) => item.id === tabs[(index + step + tabs.length) % tabs.length]);
    if (target) openConversation(target);
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (voiceOpen || (event.target as HTMLElement | null)?.closest?.('[data-shortcut-recorder]')) return;
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 't') {
        event.preventDefault(); reopenClosedTab(); return;
      }
      const target = event.target as HTMLElement | null;
      if (event.key === '?' && !event.ctrlKey && !event.metaKey && !event.altKey && !target?.closest('input,textarea,[contenteditable="true"]')) {
        event.preventDefault(); setKeymapOpen((value) => !value); return;
      }
      if (event.ctrlKey && !event.shiftKey && event.key.toLowerCase() === 'p') {
        const configured = (() => { try { const parsed: unknown = JSON.parse(localStorage.getItem('atlas.model-cycle') ?? '[]'); return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string' && store.models.some((model) => model.id === id)) : []; } catch { return []; } })();
        const choices = configured.length ? configured : store.models.map((model) => model.id);
        if (choices.length > 1) { event.preventDefault(); const index = choices.indexOf(store.model); void store.selectModel(choices[(index + 1 + choices.length) % choices.length]); return; }
      }
      if (event.altKey && event.shiftKey && event.key.toLowerCase() === 'a') {
        event.preventDefault();
        askSelectedText();
        return;
      }
      if (event.ctrlKey && !event.altKey && !event.shiftKey && /^[1-9]$/.test(event.key)) {
        const target = tabs[Number(event.key) - 1];
        if (target) { event.preventDefault(); const conversation = store.conversations.find((item) => item.id === target); if (conversation) openConversation(conversation); }
        return;
      }
      if (event.ctrlKey && !event.altKey && !event.shiftKey && event.key.toLowerCase() === 't') {
        const focused = document.activeElement;
        if (inspectorTab === 'browser' && inspectorOpen && focused?.tagName.toLowerCase() === 'webview') return;
        event.preventDefault(); setTranscriptOpen(true); return;
      }
      if (event.key === 'Escape') {
        if (event.defaultPrevented) return;
        const target = event.target;
        const draft = target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement ? target.value : '';
        const overlay = document.querySelector('[role="dialog"], [role="menu"]');
        if (draft.trim() || overlay || !store.busy) return;
        event.preventDefault();
        store.stopTask();
        return;
      }
      const action = matchShortcut(event, bindings);
      if (!action) return;
      event.preventDefault();
      switch (action) {
        case 'palette': setPaletteOpen((value) => !value); break;
        case 'newTask': newTask(); break;
        case 'settings': setSheet((value) => value ? null : 'models'); break;
        case 'nextTab': cycleTab(1); break;
        case 'prevTab': cycleTab(-1); break;
        case 'closeTab': if (view === 'chat' && store.activeConversationId) closeTab(store.activeConversationId); break;
        case 'toggleSidebar': toggleMini(); break;
        case 'toggleInspector': if (view === 'chat') toggleInspector(); break;
        case 'focusComposer': document.querySelector<HTMLTextAreaElement>('textarea[aria-label="消息内容"]')?.focus(); break;
        case 'stopRun': if (store.busy) store.stopTask(); break;
        case 'sendNow': void submit(false, true); break;
        case 'stashInput': {
          const value = input.trim();
          if (!value) { window.dispatchEvent(new Event('atlas:open-input-stash')); break; }
          const key = `atlas.input-stash.${store.activeConversationId || 'home'}`;
          let saved: Array<{ id: string; text: string; createdAt: string }> = [];
          try { const parsed: unknown = JSON.parse(localStorage.getItem(key) ?? '[]'); if (Array.isArray(parsed)) saved = parsed.filter((item) => item && typeof item.text === 'string'); } catch { /* corrupt stash is ignored */ }
          saved.push({ id: crypto.randomUUID(), text: input, createdAt: new Date().toISOString() });
          try { localStorage.setItem(key, JSON.stringify(saved.slice(-30))); } catch { /* storage unavailable */ }
          setInput(''); writeDraft(store.activeConversationId, ''); window.dispatchEvent(new Event('atlas:open-input-stash')); break;
        }
        case 'sidebarSearch': window.dispatchEvent(new CustomEvent('atlas:sidebar-shortcut', { detail: { action: 'sidebar.search' } })); break;
        case 'sidebarProjectPicker': window.dispatchEvent(new CustomEvent('atlas:sidebar-shortcut', { detail: { action: 'sidebar.project-picker' } })); break;
        case 'sidebarNextGroup': window.dispatchEvent(new CustomEvent('atlas:sidebar-shortcut', { detail: { action: 'sidebar.next-group' } })); break;
        case 'sidebarPreviousGroup': window.dispatchEvent(new CustomEvent('atlas:sidebar-shortcut', { detail: { action: 'sidebar.previous-group' } })); break;
        case 'focusNextPane': window.dispatchEvent(new CustomEvent('atlas:focus-pane', { detail: { step: 1 } })); break;
        case 'focusPreviousPane': window.dispatchEvent(new CustomEvent('atlas:focus-pane', { detail: { step: -1 } })); break;
        case 'openDiff': if (view === 'chat') { setInspectorTab('changes'); setInspectorOpen(true); setPref('canvas', 'true'); setFullScreenDiff(true); } break;
        case 'diffPreviousHunk': if (fullScreenDiff) window.dispatchEvent(new CustomEvent('atlas:diff-action', { detail: { action: 'previous' } })); break;
        case 'diffNextHunk': if (fullScreenDiff) window.dispatchEvent(new CustomEvent('atlas:diff-action', { detail: { action: 'next' } })); break;
        case 'diffCollapseHunks': if (fullScreenDiff) window.dispatchEvent(new CustomEvent('atlas:diff-action', { detail: { action: 'collapse' } })); break;
        case 'diffExpandHunks': if (fullScreenDiff) window.dispatchEvent(new CustomEvent('atlas:diff-action', { detail: { action: 'expand' } })); break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
  useEffect(() => {
    let lastSent = 0;
    const updateContext = () => {
      const now = Date.now();
      if (now - lastSent < 500) return;
      lastSent = now;
      window.atlasDesktop?.setScreenshotContext?.(store.activeConversationId, now);
    };
    document.addEventListener('pointerdown', updateContext, true);
    document.addEventListener('keydown', updateContext, true);
    updateContext();
    return () => { document.removeEventListener('pointerdown', updateContext, true); document.removeEventListener('keydown', updateContext, true); };
  }, [store.activeConversationId]);
  useEffect(() => { void window.atlasDesktop?.listRecentScreenshots?.().then(setRecentScreenshots).catch(() => undefined); }, []);
  useEffect(() => window.atlasDesktop?.onSessionScreenshot?.((image, conversationId) => {
    void window.atlasDesktop?.listRecentScreenshots?.().then(setRecentScreenshots).catch(() => undefined);
    if (conversationId === useAtlasStore.getState().activeConversationId) {
      setAttachments((items) => items.length < 4 ? [...items, image] : items);
      setToast('截图已添加到当前会话输入框');
      return;
    }
    const key = `atlas.screenshot.${conversationId}`;
    try {
      const pending = parseRecentScreenshotCache(JSON.parse(localStorage.getItem(key) ?? '{}'));
      const recent = pending && Date.now() - pending.capturedAt < 30 * 60 * 1000 ? pending.items : [];
      localStorage.setItem(key, JSON.stringify({ capturedAt: Date.now(), items: [...recent, image].slice(-4) }));
    } catch { /* ignore local cache errors */ }
  }), []);
  useEffect(() => window.atlasDesktop?.onSessionScreenshotError?.((message) => setToast(message)), []);
  useEffect(() => {
    if (!store.activeConversationId) return;
    const key = `atlas.screenshot.${store.activeConversationId}`;
    try {
      const pending = parseRecentScreenshotCache(JSON.parse(localStorage.getItem(key) ?? '{}'));
      if (pending && Date.now() - pending.capturedAt < 30 * 60 * 1000 && pending.items.length) {
        setAttachments((items) => [...items, ...pending.items].slice(0, 4));
        localStorage.removeItem(key); setToast('最近的会话截图已放入输入框');
      } else localStorage.removeItem(key);
    } catch { /* corrupt screenshot cache is ignored */ }
  }, [store.activeConversationId]);
  useEffect(() => () => { dictationRef.current?.stream.getTracks().forEach((track) => track.stop()); void dictationRef.current?.context.close(); cancelRoutedSpeech(); }, []);

  const paletteItems: PaletteItem[] = [
    { id: 'new', group: '操作', label: '新任务', hint: 'Ctrl N', icon: <Plus />, run: newTask },
    { id: 'new-window', group: '操作', label: '新建窗口', hint: 'Ctrl Shift N', icon: <Plus />, run: () => window.atlasDesktop?.openNewWindow?.() },
    { id: 'new-session-window', group: '操作', label: '新会话并在新窗口打开', hint: 'Ctrl Alt N', icon: <Plus />, run: () => window.atlasDesktop?.openNewSessionWindow?.() },
    { id: 'voice', group: '操作', label: '开始语音通话', icon: <AudioLines />, run: startVoice },
    ...THEMES.filter((item) => item.id !== theme).map((item) => ({ id: `theme-${item.id}`, group: '外观', label: `切换到${item.label}`, hint: item.hint, icon: item.id === 'dark' ? <Moon /> : <Sun />, run: () => chooseTheme(item.id) })),
    { id: 'settings', group: '操作', label: '设置', hint: 'Ctrl ,', icon: <Settings />, run: () => setSheet('models') },
    { id: 'reopen-tab', group: '操作', label: '重新打开最近关闭的会话', hint: 'Ctrl Shift T', run: reopenClosedTab },
    ...(activeConversation ? [{ id: 'export', group: '操作', label: '导出当前对话', icon: <Download />, run: () => void store.exportConversation(activeConversation.id) }] : []),
    ...(activeConversation ? [{ id: 'side', group: '操作', label: '旁问', hint: '/btw', icon: <MessagesSquare />, run: () => setSide({ open: true }) }] : []),
    ...store.recipes.map((recipe) => ({ id: `recipe-${recipe.id}`, group: '配方', label: recipe.name, icon: <BookMarked />, run: () => setRecipesOpen(true) })),
    ...NAV.map(({ view: target, label, icon: Icon }) => ({ id: `go-${target}`, group: '前往', label, icon: <Icon />, run: () => go(target) })),
    ...MORE_NAV.map(({ view: target, label, icon: Icon }) => ({ id: `go-${target}`, group: '前往', label, icon: <Icon />, run: () => go(target) })),
    ...store.conversations.slice(0, 30).map((conversation) => ({ id: `c-${conversation.id}`, group: '任务', label: conversation.title, hint: relativeTime(conversation.updated_at), run: () => openConversation(conversation) })),
  ];

  /** 用户自定义命令（Markdown 命令 / 配方导出）跑起来：配方走配方自己的渲染，其余走命令渲染接口。 */
  const runCustomCommand = async (command: CustomCommandInfo, argument: string) => {
    const args = argument.trim();
    if (command.recipe_id) {
      const recipe = store.recipes.find((item) => item.id === command.recipe_id);
      const firstParam = recipe?.params[0]?.name;
      await store.runRecipe(command.recipe_id, args && firstParam ? { [firstParam]: args } : {});
      return;
    }
    if (!args && command.argument_hint) { setToast(`在 /${command.name} 后面写上：${command.argument_hint}`); return; }
    try {
      const rendered = await backend.renderCommand(command.id, args, workspacePath || undefined);
      if (rendered.mode === 'plan') store.setNextRunMode('plan');
      store.setPendingRunOverrides({
        model: rendered.model ?? undefined,
        tool_allow: rendered.tool_allow ?? undefined,
        tool_deny: rendered.tool_deny?.length ? rendered.tool_deny : undefined,
      });
      await store.sendMessage(rendered.prompt);
    } catch (error) {
      setToast(`命令没能运行：${error instanceof Error ? error.message : String(error)}`);
    }
  };
  const enhancePrompt = async (text: string) => {
    const result = await api<{ text: string; model?: string }>(store.apiBaseUrl, '/api/chat/prompt-enhance', {
      method: 'POST',
      json: { text, model: store.model || undefined },
    });
    return result.text;
  };
  const commandGroup = (source: string) => source === 'recipe' ? '配方命令'
    : source.startsWith('claude') ? 'Claude 命令' : source.startsWith('codex') ? 'Codex 命令'
      : source.startsWith('plugin') ? '插件命令' : source === 'atlas' ? 'Atlas 命令' : source;
  const startDynamicWorkflow = async (goal: string) => {
    const target = goal.trim();
    if (!target) { setToast('用法：/workflow <要完成的目标>'); return; }
    go('chat');
    if (!useAtlasStore.getState().activeConversationId) {
      const workspace = store.draftWorkspace ?? defaultWorkspace ?? '';
      if (!store.draftWorkspace && workspace) store.setDraftWorkspace(workspace);
      await store.createConversation(`工作流：${target.slice(0, 36)}`);
    }
    await store.sendMessage(`请使用 Atlas 的 workflow 工具执行以下目标。先由主 Agent 规划为有依赖关系的子任务 DAG，再并行运行可并行的子 Agent，并等待完成后汇总结果、错误和产物。\n\n目标：${target}`);
  };
  const prepareHandoff = async () => {
    if (!activeConversation || handoffBusy) return;
    setHandoffBusy(true);
    try {
      setHandoffSource(activeConversation.id);
      const result = await api<{ text: string }>(store.apiBaseUrl, `/api/conversations/${encodeURIComponent(activeConversation.id)}/handoff-summary${store.model ? `?model=${encodeURIComponent(store.model)}` : ''}`, { method: 'POST' });
      setHandoffDraft(result.text);
    } catch (error) {
      setToast(`生成交接摘要失败：${error instanceof Error ? error.message : String(error)}`);
      setHandoffDraft(`## 原会话\n${activeConversation.title || '未命名任务'} (${activeConversation.id})\n\n## 工作区与分支\n${activeConversation.worktree_path ? `${activeConversation.worktree_branch || '未知'} · ${activeConversation.worktree_path} · base ${activeConversation.base_branch || '未知'}` : String(activeConversation.workspace || '未设置')}\n\n## 完整记录\n${messages.filter((item) => item.role === 'user' || item.role === 'assistant').map((item) => `### ${item.role === 'user' ? '用户' : 'Atlas'}\n${item.content}`).join('\n\n')}`);
    } finally { setHandoffBusy(false); }
  };
  const createHandoffConversation = async () => {
    if (!handoffSource) return;
    try {
      const created = await api<{ id: string }>(store.apiBaseUrl, '/api/conversations', { method: 'POST', json: {
        title: `交接：${activeConversation?.title || '任务'}`,
        parent_conversation_id: handoffSource,
      } });
      await store.refreshConversations();
      const target = useAtlasStore.getState().conversations.find((item) => item.id === created.id);
      if (target) await openConversation(target);
      setInput(`请承接以下完整任务摘要，先检查待办并继续执行：\n\n${handoffDraft}\n\n我的新问题：`);
      setHandoffDraft(''); setHandoffSource('');
    } catch (error) { setToast(`创建交接会话失败：${error instanceof Error ? error.message : String(error)}`); }
  };
  const slashCommands: SlashCommand[] = [
    { id: 'new', label: '/new', hint: '生成完整上下文交接并在干净的新对话继续', run: () => {
      if (!activeConversation) { newTask(); return; }
      void prepareHandoff();
    } },
    { id: 'bg', label: '/bg', hint: '将当前运行放到后台并开始空白会话', run: () => {
      if (!activeRun || runDone) { setToast('当前没有可转入后台的运行'); return; }
      store.setRunBackground(activeRun.id, true);
      newTask();
      setToast(`「${activeConversation?.title || '当前会话'}」已在后台继续；可从侧栏打开、暂停或停止`);
    } },
    { id: 'handoff', label: '/handoff', hint: '生成、预览并编辑完整任务交接摘要', run: () => { void prepareHandoff(); } },
    { id: 'clear', label: '/clear', hint: '开始一段新对话', run: newTask },
    ...(activeConversation ? [
      { id: 'tag', label: '/tag', hint: '给当前会话加颜色标签，可在侧栏按标签搜索', takesArgument: true, run: (value: string) => {
        const label = value.trim().toLowerCase();
        const choices: Record<string, string> = { red: 'red', orange: 'orange', yellow: 'yellow', green: 'green', blue: 'blue', purple: 'purple', 红: 'red', 橙: 'orange', 黄: 'yellow', 绿: 'green', 蓝: 'blue', 紫: 'purple', clear: '' };
        if (!(label in choices)) { setToast('用法：/tag 红|橙|黄|绿|蓝|紫|clear'); return; }
        window.dispatchEvent(new CustomEvent('atlas:conversation-label', { detail: { id: activeConversation.id, label: choices[label] || null } }));
        setToast(choices[label] ? `已设置${value.trim()}色标签` : '已清除会话标签');
      } },
      { id: 'export', label: '/export', hint: '导出当前对话为 JSON', run: () => void store.exportConversation(activeConversation.id) },
      { id: 'export-clipboard', label: '/export-clipboard', hint: '复制当前对话 Markdown（含工具调用摘要）', run: () => {
        const toolSummary = activeEvents.filter((event) => /tool|command/i.test(event.type)).map((event) => `- ${event.type}`).join('\n');
        const transcript = messages.map((item) => `### ${item.role === 'user' ? '用户' : item.role === 'assistant' ? 'Atlas' : '工具'}\n\n${item.content}`).join('\n\n');
        void navigator.clipboard.writeText(`# ${activeConversation.title || 'Atlas 会话'}\n\n${transcript}${toolSummary ? `\n\n## 工具调用摘要\n\n${toolSummary}` : ''}`).then(() => setToast('会话 Markdown 已复制')).catch(() => setToast('剪贴板不可用'));
      } },
      { id: 'rename', label: '/rename', hint: '把后面的文字设为对话名称', takesArgument: true, run: (title: string) => { if (title.trim()) void store.renameConversation(activeConversation.id, title); else setToast('在 /rename 后面写上新名称'); } },
      { id: 'resume', label: '/resume', hint: '继续打开最近对话，或按名称搜索', takesArgument: true, run: (query: string) => { const target = query.trim() ? store.conversations.find((item) => item.id === query.trim() || item.title.toLowerCase().includes(query.trim().toLowerCase())) : null; if (target) openConversation(target); else if (!query.trim()) setResumePickerOpen(true); else setToast('没有找到可恢复的对话'); } },
      { id: 'fork', label: '/fork', hint: '从最近消息或指定检查点分叉', takesArgument: true, run: (target: string) => {
        const requested = target.trim();
        if (!requested) { const last = [...messages].reverse().find((item) => item.role === 'user'); if (last) void store.forkFrom(last.id); else setToast('当前对话还没有用户消息'); return; }
        const workspace = typeof activeConversation.workspace === 'string' ? activeConversation.workspace : '';
        void api<Array<{ id: string; created_at: string }>>(store.apiBaseUrl, `/api/checkpoints${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`).then((checkpoints) => {
          const checkpoint = requested.toLowerCase() === 'latest' ? checkpoints[0] : checkpoints.find((item) => item.id === requested);
          if (!checkpoint) { setToast('没有找到这个工作区检查点'); return; }
          const pointTime = Date.parse(checkpoint.created_at);
          const message = [...messages].reverse().find((item) => item.role === 'user' && (!Number.isFinite(pointTime) || Date.parse(item.created_at ?? '') <= pointTime));
          if (message) void store.forkFrom(message.id, true); else setToast('检查点之前没有可分叉的用户消息');
        }).catch((error) => setToast(`检查点读取失败：${error instanceof Error ? error.message : String(error)}`));
      } },
      { id: 'rewind', label: '/rewind', hint: '查看或恢复当前工作区检查点', takesArgument: true, run: (target: string) => {
        showInspectorTab('changes');
        const requested = target.trim(); if (!requested) return;
        const workspace = typeof activeConversation?.workspace === 'string' ? activeConversation.workspace : '';
        void api<Array<{ id: string; files?: Array<string | { path?: string; exists?: boolean }> }>>(store.apiBaseUrl, `/api/checkpoints${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`).then(async (checkpoints) => {
          const checkpoint = requested.toLowerCase() === 'latest' ? checkpoints[0] : checkpoints.find((item) => item.id === requested);
          if (!checkpoint) { setToast('没有找到这个工作区检查点'); return; }
          const files = (checkpoint.files ?? []).map((item) => typeof item === 'string' ? item : `${item.path ?? '未知路径'}${item.exists === false ? '（恢复时删除）' : ''}`);
          const impact = files.length ? files.map((file) => `• ${file}`).join('\n') : '此检查点没有文件清单。';
          if (!window.confirm(`将工作区恢复到检查点 ${checkpoint.id}，可能覆盖或删除以下文件：\n\n${impact}\n\n继续吗？`)) return;
          const result = await api<{ result: { restored?: unknown[] } }>(store.apiBaseUrl, '/api/agent/capabilities/workspace.checkpoint.restore/invoke', { method: 'POST', json: { checkpoint_id: checkpoint.id } });
          setToast(`已恢复 ${result.result?.restored?.length ?? checkpoint.files?.length ?? 0} 个文件`);
        }).catch((error) => setToast(`检查点恢复失败：${error instanceof Error ? error.message : String(error)}`));
      } },
      { id: 'undo', label: '/undo', hint: '撤回最近一条用户消息及其之后内容', run: () => { const last = [...messages].reverse().find((item) => item.role === 'user'); if (last) void rewind(last.id, false); else setToast('当前对话没有可撤回的用户消息'); } },
      { id: 'redo', label: '/redo', hint: '恢复刚刚撤回的内容', run: () => { if (rewound) void store.redoRewind(rewound.conversationId, rewound.rewindId).then((ok) => { if (ok) { setRewound(null); setToast('已重做'); } }); else setToast('当前没有可重做的撤回'); } },
      { id: 'approve', label: '/approve', hint: '打开当前对话的审批与活动', run: () => showInspectorTab('activity') },
      { id: 'side', label: '/side', hint: '在侧聊中追问，不打断主对话', takesArgument: true, run: (question: string) => setSide({ open: true, question: question.trim() || undefined }) },
      { id: 'worktree', label: '/worktree', hint: '查看当前对话的独立工作树', run: () => showInspectorTab('context') },
      { id: 'dashboard', label: '/dashboard', hint: '打开当前对话的持久工作面板', run: () => showInspectorTab('dashboard') },
      { id: 'overview', label: '/overview', hint: '汇总当前任务计划、来源、生成文件和会话摘要', run: () => showInspectorTab('overview') },
    ] : []),
    ...(activeRun && runDone && store.runPrompts[activeRun.id] ? [{ id: 'retry', label: '/retry', hint: '把上一条要求重新执行一遍', run: () => store.retryRun(activeRun.id) }] : []),
    { id: 'plan', label: '/plan', hint: store.nextRunMode === 'plan' ? '取消：下一条直接执行' : '下一条先出计划，你批准后再动手', run: () => store.setNextRunMode(store.nextRunMode === 'plan' ? 'act' : 'plan') },
    { id: 'ultraplan', label: '/ultraplan', hint: '并行调研后生成详细计划，批准后按步骤执行', takesArgument: true, run: (goal: string) => {
      if (!goal.trim()) { setToast('在 /ultraplan 后写上目标'); return; }
      const target = goal.trim();
      if (ultraplanStarting.current || ultraplan) { setToast('已有一个高级计划在进行中'); return; }
      if (activeConversation) {
        if (typeof activeConversation.workspace !== 'string' || !activeConversation.workspace) { setToast('高级计划需要先为会话选择工作目录'); return; }
        setUltraplan({ goal: target, conversationId: activeConversation.id, workspace: activeConversation.workspace, title: activeConversation.title });
        return;
      }
      // 新会话草稿还没有 conversation：用输入框下方显示的工作区（草稿/默认）先建会话，再开计划面板。
      const workspace = store.draftWorkspace ?? defaultWorkspace ?? '';
      if (!workspace) { setToast('高级计划需要先选择工作目录'); return; }
      ultraplanStarting.current = true;
      void (async () => {
        try {
          if (!store.draftWorkspace) store.setDraftWorkspace(workspace);
          const title = `高级计划：${target.slice(0, 30)}`;
          await store.createConversation(title);
          const conversationId = useAtlasStore.getState().activeConversationId;
          if (conversationId) setUltraplan({ goal: target, conversationId, workspace, title });
        } finally {
          ultraplanStarting.current = false;
        }
      })();
    } },
    { id: 'share', label: '/share', hint: '导出当前会话为离线只读 HTML；参数 tools / thinking 可包含对应内容', takesArgument: true, run: (options: string) => {
      if (!activeConversation) { setToast('先打开要分享的会话'); return; }
      void api<{ path: string }>(store.apiBaseUrl, `/api/conversations/${encodeURIComponent(activeConversation.id)}/share`, {
        method: 'POST', json: { include_tools: /\btools\b/i.test(options), include_thinking: /\bthinking\b/i.test(options) },
      }).then(async ({ path }) => {
        await navigator.clipboard?.writeText(path).catch(() => undefined);
        await window.atlasDesktop?.openPath?.(path).catch(() => undefined);
        setToast(`已导出并复制文件路径：${path}`);
      }).catch((error) => setToast(`导出失败：${error instanceof Error ? error.message : String(error)}`));
    } },
    { id: 'busy', label: '/busy', hint: '忙碌时段内暂缓桌面通知与手机推送；/busy off 解除', takesArgument: true, run: (value: string) => {
      const text = value.trim().toLowerCase();
      if (text === 'off') {
        void api<{ busy: boolean }>(store.apiBaseUrl, '/api/busy', { method: 'POST', json: { seconds: null } })
          .then(() => setToast('已解除忙碌状态')).catch((error) => setToast(String(error)));
        return;
      }
      const match = /^(\d+)(m|min|h|hr)?$/.exec(text || '60m');
      if (!match) { setToast('时长格式：/busy 30m、/busy 2h 或 /busy off'); return; }
      const seconds = Number(match[1]) * (match[2]?.startsWith('h') ? 3600 : 60);
      void api<{ until?: number }>(store.apiBaseUrl, '/api/busy', { method: 'POST', json: { seconds } })
        .then(({ until }) => setToast(`忙碌状态已开启，至 ${until ? new Date(until * 1000).toLocaleTimeString() : '稍后'}`))
        .catch((error) => setToast(String(error)));
    } },
    { id: 'pr', label: '/pr', hint: '输入 new 打开提交并开 PR 向导；否则关联 PR', takesArgument: true, run: (value: string) => {
      if (value.trim().toLowerCase() === 'new') { window.dispatchEvent(new CustomEvent('atlas:open-pr-wizard')); return; }
      if (!activeConversation) { setToast('先打开要关联 PR 的会话'); return; }
      const pr = value.replace(/\s+--auto\b/i, '').trim();
      if (!pr) { setToast('用法：/pr <链接或编号> [--auto]'); return; }
      void api<Record<string, unknown>>(store.apiBaseUrl, `/api/conversations/${encodeURIComponent(activeConversation.id)}/pr`, {
        method: 'POST', json: { pr },
      }).then(async () => {
        if (/\s+--auto\b/i.test(value)) await api(store.apiBaseUrl, `/api/conversations/${encodeURIComponent(activeConversation.id)}/pr`, { method: 'PATCH', json: { auto_fix: true } });
        setToast('PR 已关联；可在输入框旁查看状态');
      }).catch((error) => setToast(`PR 关联失败：${error instanceof Error ? error.message : String(error)}`));
    } },
    { id: 'folder', label: '/folder', hint: '选择这个对话的工作目录', run: () => void chooseWorkspace() },
    { id: 'pwd', label: '/pwd', hint: '显示当前对话的工作目录', run: () => {
      const path = activeConversation
        ? (typeof activeConversation.workspace === 'string' ? activeConversation.workspace : '')
        : store.draftWorkspace !== null ? store.draftWorkspace : defaultWorkspace;
      setToast(path || '当前没有设置工作目录');
    } },
    { id: 'cd', label: '/cd', hint: '切换工作目录；可写完整路径，--none 清除工作目录', takesArgument: true, run: (value: string) => {
      const path = value.trim();
      if (!path) { void chooseWorkspace(); return; }
      const id = useAtlasStore.getState().activeConversationId;
      if (path === '--none') {
        if (id) store.setWorkspace(id, null); else store.setDraftWorkspace('');
        setToast('已清除当前对话的工作目录；绝对路径搜索仍可用'); return;
      }
      if (id) store.setWorkspace(id, path); else store.setDraftWorkspace(path);
      setPref('default-workspace', path); setDefaultWorkspace(path); setToast(`工作目录：${path}`);
    } },
    { id: 'init', label: '/init', hint: '扫描工作区，生成或更新 AGENTS.md', run: () => { if (typeof activeConversation?.workspace !== 'string' || !activeConversation.workspace) { setToast('请先选择工作目录'); return; } void store.runInit(); } },
      { id: 'ide', label: '/ide', hint: '查看 IDE 插件版本、心跳和工作区；重连、配置或运行诊断', run: () => setIdeManagerOpen(true) },
      { id: 'recap', label: '/recap', hint: '用当前对话生成压缩回顾（Atlas 通过 /compact 保存回顾）', run: () => {
        if (!activeConversation) { setToast('先打开一个对话再生成回顾'); return; }
        void store.compactConversation(activeConversation.id, '生成当前对话的简短回顾，保留目标、关键决策、完成进度、未解决问题和下一步。').then((text) => { if (text) setToast(`对话回顾已更新：${text}`); });
      } },
      { id: 'raw', label: '/raw', hint: '查看最近一条 Atlas 回复的原始文本并复制', run: () => {
        const latest = [...messages].reverse().find((item) => item.role === 'assistant')?.content || reply;
        if (!latest) { setToast('当前还没有可查看的回复'); return; }
        setRawTextTitle('最近回复的原始文本'); setRawText(latest);
      } },
      { id: 'auto-review', label: '/auto-review', hint: '审查当前未提交改动', run: () => { void store.sendMessage('/review'); } },
      { id: 'ask-selection', label: '/ask-selection', hint: '把当前选中的文字放进消息草稿', run: askSelectedText },
    { id: 'review', label: '/review', hint: '代码审查：branch <名> / commit <sha>，默认审查未提交改动', takesArgument: true, run: (arg: string) => { const focus = arg.trim(); void store.sendMessage(focus ? `/review ${focus}` : '/review'); } },
    { id: 'ultrareview', label: '/ultrareview', hint: '全仓库并行审查正确性、安全与架构层；只读并显示归因报告', takesArgument: true, run: (model: string) => {
      if (!workspacePath || workspacePath.startsWith('ssh://')) { setToast('请先选择本机 Git 工作区'); return; }
      setToast('正在并行审查整个仓库…');
      void api<Record<string, unknown> & { findings: Array<Record<string, unknown>>; review_layers: string[]; layer_errors: Record<string, string> }>(store.apiBaseUrl, '/api/review/repository', {
        method: 'POST', json: { workspace: workspacePath, model: model.trim() || undefined },
      }).then((report) => {
        const findings = report.findings.map((finding) => `[${finding.severity}] ${finding.file}:${finding.line ?? '?'} · ${finding.title}\n${finding.explanation}\n归因：${(finding.review_layers as string[] ?? []).join(', ')}\n证据：${finding.evidence ?? ''}\n建议：${finding.suggested_fix ?? ''}`).join('\n\n');
        setRawTextTitle('仓库级并行审查');
        setRawText(`范围：${report.file_count} 个文件；上下文源文件：${report.included_file_count}；审查层：${report.review_layers.join(', ')}；去重发现：${report.findings.length}\n${report.context_truncated ? '本层 reviewer 正文按上下文预算和层级相关性选择；完整文件清单仍已采集。\n' : ''}${Object.entries(report.layer_errors).map(([name, error]) => `审查层失败 ${name}：${error}`).join('\n')}\n\n${findings || '没有发现问题。'}`.trim());
      }).catch((error) => setToast(`仓库审查失败：${error instanceof Error ? error.message : String(error)}`));
    } },
    { id: 'security-review', label: '/security-review', hint: '按安全检查清单只读审查当前未提交改动，可追加 branch <名> / commit <sha>', takesArgument: true, run: (arg: string) => { void store.sendMessage(`/security-review ${arg.trim()}`.trim()); } },
    { id: 'simplify', label: '/simplify', hint: '只审查可保持行为不变的简化与清理项', takesArgument: true, run: (arg: string) => { void store.sendMessage(`/simplify ${arg.trim()}`.trim()); } },
    { id: 'recipe', label: '/recipe', hint: '打开配方，带参数复跑保存过的任务', run: () => setRecipesOpen(true) },
    { id: 'workflow', label: '/workflow', hint: '规划并启动动态子 Agent DAG：/workflow <目标>', takesArgument: true, run: (goal: string) => { void startDynamicWorkflow(goal).catch((error) => setToast(`工作流启动失败：${error instanceof Error ? error.message : String(error)}`)); } },
    { id: 'dwf', label: '/dwf', hint: '查看工作流运行、节点输出、错误、产物并管理已保存定义', run: () => setWorkflowManagerOpen(true) },
    ...(activeConversation ? [{ id: 'btw', label: '/btw', hint: '旁问：不打断正在做的事，也不存进对话', takesArgument: true, run: (question: string) => setSide({ open: true, question: question.trim() || undefined }) }] : []),
    { id: 'open', label: '/open', hint: '在浏览器面板打开网址，如 /open localhost:5173', takesArgument: true, run: (target: string) => { if (target.trim()) setBrowserUrl(/^\w+:/.test(target.trim()) ? target.trim() : `http://${target.trim()}`); showInspectorTab('browser'); } },
    ...(activeConversation ? [{ id: 'compact', label: '/compact', hint: '压缩上下文，可附说明让摘要优先保留相关事项', takesArgument: true, run: (note: string) => void store.compactConversation(activeConversation.id, note).then((text) => { if (text) setToast(text); }) }] : []),
    { id: 'voice', label: '/voice', hint: '切换语音通话；再次执行可结束', run: startVoice },
      { id: 'record-screen', label: '/record-screen', hint: '录制屏幕视频，预览、保存、删除或作为消息附件发送给 Agent', run: () => setScreenRecorderOpen(true) },
    { id: 'auto', label: '/auto', hint: '打开自动化', run: () => go('auto') },
    { id: 'memory', label: '/memory', hint: '打开记忆', run: () => go('memory') },
    { id: 'context', label: '/context', hint: '查看彩色上下文网格、类别明细和注入来源', run: () => showInspectorTab('context') },
    { id: 'prompt-size', label: '/prompt-size', hint: '查看系统提示与工具 schema 的字节和估算 Token 归因', run: () => {
      const usage = [...(activeRun?.events ?? [])].reverse().find((event) => event.type === 'run.usage')?.data;
      const breakdown = usage?.context_breakdown as { byte_attribution?: Record<string, unknown> } | undefined;
      const bytes = breakdown?.byte_attribution;
      if (!bytes) { setToast('当前运行没有提供提示词归因数据；请先完成一次模型调用后再查看'); return; }
      const source = (activeRun?.events ?? []).filter((event) => event.type === 'run.context.sources').flatMap((event) =>
        Array.isArray(event.data.sources) ? event.data.sources : []);
      const lines = source.map((item) => {
        const row = item as Record<string, unknown>;
        return `- ${String(row.kind || 'source')}: ${String(row.path || row.name || row.id || '')}${typeof row.bytes === 'number' ? ` (${row.bytes} bytes)` : ''}`;
      });
      setRawTextTitle('提示词大小与来源');
      setRawText([
        `系统提示：${Number(bytes.system_prompt ?? 0).toLocaleString()} bytes · 约 ${Number(bytes.system_prompt_tokens_estimated ?? 0).toLocaleString()} tokens`,
        `工具 schema：${Number(bytes.tool_schema ?? 0).toLocaleString()} bytes · 约 ${Number(bytes.tool_schema_tokens_estimated ?? 0).toLocaleString()} tokens`,
        '字节数按本轮发送的 UTF-8 序列化内容计算；Token 数是 Atlas 估算值。',
        '', '本轮可追溯来源：', ...(lines.length ? lines : ['- 运行事件中没有额外来源清单']),
      ].join('\n'));
    } },
    { id: 'keymap', label: '/keymap', hint: '显示分组快捷键一览', run: () => setKeymapOpen(true) },
    { id: 'chapter', label: '/chapter', hint: '在当前对话末尾添加章节目录项', takesArgument: true, run: (title: string) => {
      const value = title.trim(); if (!value) { setToast('用法：/chapter 章节名称'); return; }
      window.dispatchEvent(new CustomEvent('atlas:add-chapter', { detail: { title: value } })); setToast(`已添加章节：${value}`);
    } },
    { id: 'version', label: '/version', hint: '显示 Atlas 版本', run: () => setToast(`Atlas ${__APP_VERSION__}`) },
    { id: 'diff', label: '/diff', hint: '查看本次运行的文件改动', run: () => showInspectorTab('changes') },
    { id: 'diff-open', label: '/diff.open', hint: '打开全屏差异查看器', run: () => { showInspectorTab('changes'); setFullScreenDiff(true); } },
    { id: 'rollout', label: '/rollout', hint: '查看本次运行的完整事件归档、路径和事件清单', run: () => showInspectorTab('rollout') },
    { id: 'android', label: '/android', hint: '打开 Android 模拟器嵌入预览并选择设备', run: () => showInspectorTab('android') },
    { id: 'model', label: '/model', hint: '选择或切换模型', takesArgument: true, run: (query: string) => { const found = store.models.find((item) => item.id.toLowerCase() === query.trim().toLowerCase() || (item.name ?? '').toLowerCase() === query.trim().toLowerCase()); if (found) void store.selectModel(found.id); else setSheet('models'); } },
    { id: 'editor', label: '/editor', hint: '用系统默认编辑器撰写长消息', run: () => {
      const open = window.atlasDesktop?.openMessageEditor;
      if (!open) { setToast('外部编辑器只在桌面版可用'); return; }
      void open(input).then((text) => { if (text !== null) { setInput(text); writeDraft(store.activeConversationId, text); } }).catch((error) => setToast(`编辑器打开失败：${error instanceof Error ? error.message : String(error)}`));
    } },
    { id: 'vim', label: '/vim', hint: '切换输入框 Vim 模式', run: () => {
      const enabled = pref('vim-mode') !== 'true'; setPref('vim-mode', String(enabled)); window.dispatchEvent(new Event('atlas:vim-toggle')); setToast(`${t('Vim 模式', readLocale())} ${t(enabled ? 'Vim 模式已开启' : 'Vim 模式已关闭', readLocale())}`);
    } },
    { id: 'fallback', label: '/fallback', hint: '配置主模型失败后的备用模型顺序', run: () => setFallbackOpen(true) },
    { id: 'fast', label: '/fast', hint: '切换快速模型服务档；不支持的路由会使用普通档并在运行记录中提示', takesArgument: true, run: (value: string) => {
      const arg = value.trim().toLowerCase();
      if (arg && !['on', 'off', 'status'].includes(arg)) { setToast('用法：/fast [on|off|status]'); return; }
      void api<{ fast_enabled: boolean }>(store.apiBaseUrl, '/api/models/service-tier').then((current) => {
        if (arg === 'status') { setToast(`快速服务档${current.fast_enabled ? '已开启' : '已关闭'}`); return; }
        const fast_enabled = arg === 'on' ? true : arg === 'off' ? false : !current.fast_enabled;
        return api<{ fast_enabled: boolean }>(store.apiBaseUrl, '/api/models/service-tier', { method: 'PUT', json: { fast_enabled } })
          .then(() => setToast(`快速服务档已${fast_enabled ? '开启' : '关闭'}；服务商不支持时会自动退回普通档并显示提示`));
      }).catch((error) => setToast(`快速服务档设置失败：${String(error)}`));
    } },
    { id: 'suggestions', label: '/suggestions', hint: '开启或关闭每轮结束后的主动建议', takesArgument: true, run: (value: string) => {
      const arg = value.trim().toLowerCase();
      const enabled = arg === 'on' ? true : arg === 'off' ? false : !proactiveEnabled;
      if (arg && arg !== 'on' && arg !== 'off') { setToast('用法：/suggestions on|off'); return; }
      setProactiveEnabled(enabled); setPref('suggestions', String(enabled)); if (!enabled) setTurnSuggestions([]);
      setToast(`主动建议已${enabled ? '开启' : '关闭'}`);
    } },
    { id: 'summary', label: '/summary', hint: '开启或关闭置顶任务摘要', takesArgument: true, run: (value: string) => {
      const arg = value.trim().toLowerCase();
      const enabled = arg === 'on' ? true : arg === 'off' ? false : !summaryEnabled;
      if (arg && arg !== 'on' && arg !== 'off') { setToast('用法：/summary on|off'); return; }
      setSummaryEnabled(enabled); setPref('pinned-summary', String(enabled)); setToast(`置顶摘要已${enabled ? '开启' : '关闭'}`);
    } },
    { id: 'reasoning', label: '/reasoning', hint: '打开模型选择，查看当前可用的推理强度', run: () => setSheet('models') },
    { id: 'usage', label: '/usage', hint: '查看用量和费用', run: () => setSheet('usage') },
    { id: 'insights', label: '/insights', hint: '生成最近 7 天使用习惯报告', takesArgument: true, run: (range: string) => {
      const days = range.trim() === '30' ? 30 : 7;
      void api<{ path: string; markdown: string }>(store.apiBaseUrl, `/api/u4/insights?days=${days}`).then((report) => {
        const id = `u4-insights-${Date.now()}`;
        useAtlasStore.getState().addArtifact({ id, runId: id, type: 'report', name: `最近 ${days} 天使用习惯报告`, path: report.path, summary: report.markdown, createdAt: new Date().toISOString() });
        useAtlasStore.getState().setActiveRun(id); showInspectorTab('artifacts'); setToast('使用习惯报告已加入产物面板');
      }).catch((error) => setToast(`生成报告失败：${error instanceof Error ? error.message : String(error)}`));
    } },
    { id: 'advisor', label: '/advisor', hint: '查看或切换顾问模型', takesArgument: true, run: (model: string) => {
      if (model.trim()) void api(store.apiBaseUrl, '/api/u4/settings', { method: 'PUT', json: { advisor_model: model.trim() } }).then(() => setToast(`顾问模型已设为 ${model.trim()}`)).catch((error) => setToast(`设置顾问模型失败：${String(error)}`));
      else { setSheet('u4'); setToast('在「会话与顾问」里查看或切换顾问模型'); }
    } },
    { id: 'preset', label: '/preset', hint: '查看、保存并应用会话预设', run: () => setSheet('u4') },
    { id: 'import-chatgpt', label: '/import-chatgpt', hint: '导入 ChatGPT 官方导出包的 conversations.json', run: () => setSheet('u4') },
    { id: 'cost', label: '/cost', hint: '查看本会话 Token、缓存、费用与耗时', run: () => {
      if (!activeConversation) { setToast('先打开一个会话再查看 /cost'); return; }
      setSheet('usage');
    } },
    { id: 'wake', label: '/wake', hint: '开启或关闭本机唤醒词监听', takesArgument: true, run: (argument: string) => {
      const value = argument.trim().toLowerCase();
      if (value === 'on') { setWakeEnabled(true); setToast(`已开启本地唤醒词「${wakeWord}」`); }
      else if (value === 'off') { setWakeEnabled(false); setWakeTranscript(''); setToast('已关闭唤醒词监听'); }
      else setToast('用法：/wake on 或 /wake off');
    } },
    { id: 'help', label: '/help', hint: '列出全部斜杠命令及用法', run: showHelp },
    { id: 'powerup', label: '/powerup', hint: '打开可重放的 Atlas 功能课程', run: () => setFeatureLessonsOpen(true) },
    { id: 'doctor', label: '/doctor', hint: '检查安装与配置并查看修复建议', run: () => setSheet('diagnostics') },
    { id: 'warnings', label: '/warnings', hint: '查看持久告警历史', run: () => { setSheet('diagnostics'); window.setTimeout(() => window.dispatchEvent(new CustomEvent('atlas:diagnostics-tab', { detail: 'alerts' })), 0); } },
    { id: 'tasks', label: '/tasks', hint: '任务管理器：查看运行状态、配置来源和后台任务，可逐个结束', run: () => { setSheet('diagnostics'); window.setTimeout(() => window.dispatchEvent(new CustomEvent('atlas:diagnostics-tab', { detail: 'tasks' })), 0); } },
    { id: 'debug', label: '/debug', hint: '切换实时调试浮层（Ctrl+Shift+D）', run: () => window.dispatchEvent(new CustomEvent('atlas:toggle-debug-overlay')) },
    { id: 'memories', label: '/memories', hint: '设置当前对话是否读取和生成记忆', run: () => setSheet('memories') },
    { id: 'teach', label: '/teach', hint: '录制桌面操作并生成可复用技能', run: () => setSheet('teach') },
    { id: 'config', label: '/config', hint: '打开配置面板', run: () => setSheet('mainConfig') },
    { id: 'whatsnew', label: '/whatsnew', hint: '查看仓库提交中的新功能亮点', run: () => { void api<{ source: string; highlights: Array<string | { date?: string; title?: string }> }>(store.apiBaseUrl, '/api/u6/whatsnew').then((result) => { setRawTextTitle('有什么新功能'); setRawText(result.highlights.map((item) => typeof item === 'string' ? item : `${item.date || ''} ${item.title || ''}`.trim()).filter(Boolean).join('\n') || '仓库里还没有可显示的更新亮点。'); }).catch((error) => setToast(`读取更新说明失败：${error instanceof Error ? error.message : String(error)}`)); } },
    { id: 'release-notes', label: '/release-notes', hint: '查看完整更新说明（按版本索引）', run: () => { void api<{ changelog?: string; highlights: Array<string | { date?: string; title?: string }> }>(store.apiBaseUrl, '/api/u6/whatsnew').then((result) => { setRawTextTitle('更新说明'); setRawText(result.changelog || result.highlights.map((item) => typeof item === 'string' ? item : `${item.date || ''} ${item.title || ''}`.trim()).filter(Boolean).join('\n')); }); } },
    { id: 'about', label: '/about', hint: '查看 Atlas 版本与更新说明', run: () => { void api<{ source?: string; changelog?: string; highlights: Array<string | { date?: string; title?: string }> }>(store.apiBaseUrl, '/api/u6/whatsnew').then((result) => { setRawTextTitle('关于 Atlas'); setRawText(`Atlas ${__APP_VERSION__}\n更新来源：${result.source || '未知'}\n\n${result.changelog || result.highlights.map((item) => typeof item === 'string' ? item : `${item.date || ''} ${item.title || ''}`.trim()).filter(Boolean).join('\n')}`); }); } },
    { id: 'status', label: '/status', hint: '显示模型、推理、权限、上下文、Token 与限额状态卡', run: () => {
      const usage = [...(activeRun?.events ?? [])].reverse().find((event) => event.type === 'run.usage')?.data;
      const inputTokens = typeof usage?.input_tokens === 'number' ? usage.input_tokens : null;
      const outputTokens = typeof usage?.output_tokens === 'number' ? usage.output_tokens : null;
      const cachedTokens = typeof usage?.cached_input_tokens === 'number' ? usage.cached_input_tokens : typeof usage?.cached_tokens === 'number' ? usage.cached_tokens : null;
      const reasoningTokens = typeof usage?.reasoning_tokens === 'number' ? usage.reasoning_tokens : null;
      const limit = typeof usage?.context_limit === 'number' ? usage.context_limit : null;
      const used = typeof usage?.context_tokens === 'number' ? usage.context_tokens : null;
      const rateFailure = [...(activeRun?.events ?? [])].reverse().find((event) => event.type === 'run.failed'
        && (['rate_limit', 'billing'].includes(String(event.data.category)) || /rate.?limit|quota|额度|限流|429|余额/i.test(String(event.data.detail ?? ''))))?.data;
      const resetAt = typeof usage?.rate_limit_reset_at === 'string' ? usage.rate_limit_reset_at : null;
      const limitEvent = rateFailure?.limit_event as Record<string, unknown> | undefined;
      const retryAfter = typeof rateFailure?.retry_after_seconds === 'number' ? rateFailure.retry_after_seconds : null;
      setRawTextTitle('Atlas 运行状态');
      setRawText([
        `版本：Atlas ${__APP_VERSION__}`, `模型：${modelName}`, `推理强度：${store.reasoningEffort || '默认'}`,
        `权限：${PERMISSION[permission].label}`, `连接：${store.connected ? 'API 已连接' : 'API 未连接'}`,
        `工具：${store.tools.length} 个可用`, `运行：${activeRun ? `${activeRun.status} · ${activeRun.id}` : '空闲'}`,
        `上下文：${used !== null && limit ? `${Math.round(used / limit * 100)}% 已用 / ${Math.max(0, 100 - Math.round(used / limit * 100))}% 剩余 · ${Math.max(0, limit - used).toLocaleString()} tokens 剩余` : '未知（本轮尚无提供方上下文用量）'}`,
        `Token：input ${inputTokens ?? '未知'} · output ${outputTokens ?? '未知'} · cache ${cachedTokens ?? '未知'} · reasoning ${reasoningTokens ?? '未知'}`,
        `限额状态：${typeof limitEvent?.reset_at === 'string' ? `提供方预计重置 ${new Date(limitEvent.reset_at).toLocaleString()}` : retryAfter !== null ? `提供方要求等待 ${Math.ceil(retryAfter)} 秒；重置约 ${new Date(Date.now() + retryAfter * 1000).toLocaleString()}` : resetAt ?? '未知（提供方未返回限额或重置数据）'}`,
        used !== null && limit && used / limit >= 0.8 ? '阈值动作：上下文达到 80%，建议使用 /compact 压缩。' : '阈值动作：达到 80% 时提示压缩。',
      ].join('\n'));
    } },
    { id: 'permissions', label: '/permissions', hint: '切换当前对话权限模式', run: () => { if (!activeConversation) { setToast('先打开一个对话再切换权限'); return; } setToast(`权限模式：${PERMISSION[cyclePermission()].label}`); } },
    { id: 'agents', label: '/agents', hint: '打开 Agents 页：常驻 Agent 花名册与详情', run: () => go('agents') },
    { id: 'ps', label: '/ps', hint: '查看后台进程和最近输出', run: () => showInspectorTab('processes') },
    { id: 'stop', label: '/stop', hint: '停止后台进程；不带编号时停止当前运行', takesArgument: true, run: (id: string) => { if (!id.trim()) store.stopTask(); else void backend.killProcess(id.trim()).then(() => setToast('后台进程已停止')).catch((error) => setToast(String(error))); } },
    { id: 'goal', label: '/goal', hint: '设置、查看、暂停、恢复、管理子目标（subgoal add/done）或清除目标', takesArgument: true, run: (command: string) => { if (!activeConversation) { setToast('先打开一个对话再设置目标'); return; } void backend.runConversationGoalCommand(activeConversation.id, command).then((result) => { setConversationGoal(result.goal as typeof conversationGoal); setToast(result.output); if (result.prompt) void store.sendMessage(result.prompt); }).catch((error) => setToast(error instanceof Error ? error.message : String(error))); } },
    { id: 'copy', label: '/copy', hint: '复制最近一条 Atlas 回复', run: () => { const text = [...messages].reverse().find((item) => item.role === 'assistant')?.content; if (text) void navigator.clipboard.writeText(text).then(() => setToast('已复制最近回复')).catch(() => setToast('复制失败')); else setToast('还没有可复制的回复'); } },
    ...store.skills.map((skill) => ({
      id: `skill-${skill.name}`, label: `/${skill.name}`,
      hint: `${skill.description || '技能'} · $ 提及作为消息文本插入，不会切换全局技能状态`,
      run: () => {
        if (store.activeSkills.includes(skill.name)) { store.removeSkill(skill.name); setToast(`已停用技能 ${skill.name}`); }
        else { store.applySkill(skill.name); setToast(`下一次任务会用上 ${skill.name}`); }
      },
    })),
    ...store.customCommands.map((command) => ({
      id: `command-${command.id}`, label: `/${command.name}`,
      hint: command.description || (command.argument_hint ? `参数：${command.argument_hint}` : '自定义命令'),
      group: commandGroup(command.source), source: command.source || '自定义命令', takesArgument: Boolean(command.argument_hint),
      run: (argument: string) => void runCustomCommand(command, argument),
    })),
  ];
  function showHelp() {
    const categories = ['会话', '工作区', '模型', '工具', '诊断', '技能'];
    setRawTextTitle('命令帮助');
    const commandIndex = categories.map((category) => {
      const commands = slashCommands.filter((command) => command.group === category
        || (category === '工作区' && command.group === '任务')
        || (category === '模型' && command.group === '状态'));
      return commands.length ? `## ${category}\n${commands.map((command) => `${command.label}${command.takesArgument ? ' <参数>' : ''} — ${command.hint}`).join('\n')}` : '';
    }).filter(Boolean).join('\n\n');
    setRawText(`${commandIndex}\n\n## 快捷键\n- Ctrl / ⌘ + K：搜索会话和命令\n- Ctrl / ⌘ + ,：打开设置\n- Enter：发送；Shift + Enter：换行\n- Esc：关闭当前弹层\n\n更多快捷键可在「设置 → 快捷键」查看和自定义。`);
  }
  slashCommands.forEach((command) => {
    command.group ??= command.id.startsWith('skill-') ? '技能'
      : ['new', 'clear', 'resume', 'fork', 'undo', 'redo', 'rename', 'export', 'handoff', 'preset', 'import-chatgpt', 'bg'].includes(command.id) ? '会话'
        : ['folder', 'pwd', 'cd', 'init', 'ide', 'worktree', 'open'].includes(command.id) ? '工作区'
          : ['model', 'reasoning', 'usage', 'cost', 'advisor'].includes(command.id) ? '模型'
            : ['doctor', 'config', 'release-notes', 'about', 'help', 'version', 'insights'].includes(command.id) ? '诊断'
              : command.id.startsWith('skill-') ? '技能' : '工具';
  });
  const conversationsRef = useRef(store.conversations);
  conversationsRef.current = store.conversations;
  const searchMessages = useCallback(async (query: string): Promise<PaletteItem[]> => {
    if (!store.connected) return [];
    // Quote the text so FTS treats it as a phrase instead of query syntax.
    const hits = await api<Array<{ id: number | string; conversation_id: string; content: string; snippet?: string; role?: string }>>(store.apiBaseUrl, `/api/search?limit=12&q=${encodeURIComponent(`"${query.replace(/"/g, '""')}"`)}`);
    const messageItems = rankSearchHits(hits).flatMap((hit) => {
      const conversation = conversationsRef.current.find((item) => item.id === hit.conversation_id);
      if (!conversation) return [];
      const excerpt = cleanSearchSnippet(hit, query, 60);
      const who = searchHitRoleLabel(hit.role);
      return [{ id: `m-${hit.id}`, group: '消息内容', label: excerpt || conversation.title, hint: who ? `${who} · ${conversation.title}` : conversation.title, run: () => openConversation(conversation) }];
    });
    // 新会话草稿还没有 conversation 时，用输入框下方显示的那个工作区（草稿/默认工作区）。
    const root = activeConversation
      ? (typeof activeConversation.workspace === 'string' ? activeConversation.workspace : '')
      : store.draftWorkspace ?? defaultWorkspace ?? '';
    const fileItems = root ? (await backend.searchWorkspace(root, query, 40)).filter((hit) => hit.type === 'file').map((hit) => ({
      id: `file-${hit.path}`, group: '工作区文件', label: hit.name, hint: hit.path, icon: <FileIcon />,
      run: () => { go('chat'); store.requestFileOpen(hit.path); showInspectorTab('files'); },
      runAlt: () => { go('chat'); window.dispatchEvent(new CustomEvent('atlas:add-context-file', { detail: { path: hit.path } })); },
    })) : [];
    return [...fileItems, ...messageItems];
  }, [store.apiBaseUrl, store.connected, store.draftWorkspace, defaultWorkspace, activeConversation, go, showInspectorTab]);
  const workspacePath = activeConversation
    ? (typeof activeConversation.workspace === 'string' ? activeConversation.workspace : '')
    : store.draftWorkspace !== null ? store.draftWorkspace : defaultWorkspace ?? '';
  const remoteHost = /^ssh:\/\/([^/]+)\//.exec(workspacePath)?.[1] ?? '';
  const workspaceName = workspacePath
    ? `${remoteHost ? `${remoteHost}:` : ''}${workspacePath.split(/[\\/]/).filter(Boolean).pop() ?? workspacePath}` : '';
  useEffect(() => {
    let stale = false;
    if (!workspacePath) { setHomeGitStatus({ isGit: false, changed: 0, languages: [] }); return; }
    void api<{ is_git: boolean; changed: number; languages: string[] }>(store.apiBaseUrl, `/api/u6/environment?workspace=${encodeURIComponent(workspacePath)}`)
      .then((value) => { if (!stale) setHomeGitStatus({ isGit: value.is_git, changed: value.changed, languages: value.languages }); })
      .catch(() => { if (!stale) setHomeGitStatus({ isGit: false, changed: 0, languages: [] }); });
    return () => { stale = true; };
  }, [store.apiBaseUrl, workspacePath]);
  const homeSuggestions = useMemo<Suggestion[]>(() => {
    const rows: Suggestion[] = [];
    if (workspacePath) {
      rows.push(homeGitStatus.isGit
        ? homeGitStatus.changed ? { label: `检查 ${homeGitStatus.changed} 项未提交改动`, text: `检查当前工作区的 ${homeGitStatus.changed} 项未提交改动，按风险和影响分组说明。` }
          : { label: `梳理 ${workspaceName} 项目`, text: `梳理当前 Git 项目 ${workspaceName} 的结构、主要语言和关键入口。` }
        : { label: `了解 ${workspaceName} 工作区`, text: `了解工作区 ${workspacePath} 的目录结构和主要文件类型。` });
      const language = store.skills.find((skill) => /python|typescript|javascript|rust|golang/i.test(skill.name));
      if (language) rows.push({ label: `用 ${language.name} 技能开始`, text: `结合当前工作区，使用 ${language.name} 技能检查我接下来的改动。` });
      else if (homeGitStatus.languages.length) rows.push({ label: `${homeGitStatus.languages[0]} 项目建议`, text: `结合当前 ${homeGitStatus.languages.join('、')} 项目结构，建议一个值得优先处理的改进并说明原因。` });
    }
    const recent = store.conversations.find((item) => item.id !== store.activeConversationId);
    if (recent) rows.push({ label: `继续：${recent.title.slice(0, 18)}`, text: `请继续会话“${recent.title}”的工作，先用 read_session 读取会话 ${recent.id}。` });
    if (rows.length < 3) rows.push({ label: '整理今天的待办', text: '帮我把今天要做的事按轻重缓急理一理。' });
    if (rows.length < 4) rows.push({ label: '画一张产品海报', text: '一张极简风格的产品海报，深色背景，主体居中，柔和的顶光', mode: 'image' });
    return rows.slice(0, 4);
  }, [workspacePath, workspaceName, homeGitStatus, store.skills, store.conversations, store.activeConversationId]);
  // 自定义命令跟工作目录走：换了目录或连上后端就重取一次，供 / 菜单使用。
  useEffect(() => { void store.reloadCommands(workspacePath || undefined); }, [store.connected, workspacePath]);
  const permission: PermissionMode = (activeConversation?.permission_mode as PermissionMode | undefined) ?? 'full_access';
  const cyclePermission = () => {
    const next = PERMISSION_CYCLE[(PERMISSION_CYCLE.indexOf(permission) + 1) % PERMISSION_CYCLE.length];
    const executor = activeConversation?.executor && activeConversation.executor !== 'atlas' && next !== 'full_access'
      ? { executor: 'atlas' } : {};
    store.setConversationSettings(store.activeConversationId, { permission_mode: next, ...executor });
    return next;
  };
  const findMentions = async (trigger: '@' | '#', query: string): Promise<MentionItem[]> => {
    const taken = new Set(mentions.map((item) => `${item.kind}:${item.id}`));
    if (trigger === '#') {
      const q = query.toLowerCase();
      return store.conversations.filter((item) => item.id !== store.activeConversationId && item.title.toLowerCase().includes(q) && !taken.has(`conversation:${item.id}`))
        .slice(0, 8).map((item) => ({ kind: 'conversation' as const, id: item.id, label: item.title, hint: relativeTime(item.updated_at) }));
    }
    const q = query.toLocaleLowerCase();
    const sessions = store.conversations.filter((item) => item.id !== store.activeConversationId && item.title.toLocaleLowerCase().includes(q) && !taken.has(`conversation:${item.id}`))
      .slice(0, 6).map((item) => ({ kind: 'conversation' as const, id: item.id, label: item.title, hint: `会话 · ${item.id}` }));
    const mcp = await api<{ servers: Array<{ name: string; resources?: Array<{ uri: string; name?: string; title?: string; description?: string }> }> }>(store.apiBaseUrl, '/api/mcp/resources').catch(() => ({ servers: [] }));
    const resources = mcp.servers.flatMap((server) => (server.resources ?? []).map((resource) => ({
      kind: 'resource' as const, id: `${server.name}\n${resource.uri}`,
      label: resource.title || resource.name || resource.uri,
      hint: `MCP · ${server.name} · ${resource.description || resource.uri}`,
    }))).filter((item) => item.label.toLocaleLowerCase().includes(q) || item.hint?.toLocaleLowerCase().includes(q))
      .filter((item) => !taken.has(`resource:${item.id}`)).slice(0, 6);
    const root = typeof activeConversation?.workspace === 'string' ? activeConversation.workspace : '';
    // @ refers to files in the working directory; without one there is nothing to search.
    if (!query) return [...sessions, ...resources].slice(0, 12);
    if (!root) return [...sessions, ...resources].slice(0, 12);
    const hits = await backend.searchWorkspace(root, query, 12);
    const files = hits.filter((hit) => hit.type === 'file' && !taken.has(`file:${hit.path}`)).map((hit) => ({ kind: 'file' as const, id: hit.path, label: hit.name, hint: hit.path }));
    return [...files, ...sessions, ...resources].slice(0, 12);
  };
  const currentModel = store.models.find((model) => model.id === store.model);
  const worktreeActive = Boolean(activeConversation?.worktree_path);
  const worktreeRequested = Boolean(store.worktreeRequests[store.activeConversationId]);
  const profileName = store.profiles.find((profile) => profile.id === store.profileId)?.name ?? '默认';
  const composerStatus = listening ? '正在听…' : store.connected ? '' : store.backendStarting ? 'Atlas 后端启动中…' : 'Atlas 后端没有连接';
  // Run settings sit on one line under the composer (Codex keeps environment controls outside the input box).
  const runTools = <>
    <Menu>
      <Tip label={workspaceName ? `工作目录：${workspacePath}` : '选择工作目录'}><MenuTrigger asChild>
        <button type="button" aria-label={workspaceName ? `工作目录：${workspaceName}` : '选择工作目录'} className={cn('inline-flex h-7 max-w-[170px] items-center gap-1.5 rounded-[9px] px-2 text-[12px] hover:bg-hover', workspaceName ? 'text-fg-2' : 'text-fg-3')}>
          {remoteHost ? <Server size={15} className="shrink-0 text-brand" /> : <FolderOpen size={15} className="shrink-0" />}{workspaceName && <span className="truncate">{workspaceName}</span>}
        </button>
      </MenuTrigger></Tip>
      <MenuContent side="top">
        {workspacePath && <MenuLabel>{workspacePath}</MenuLabel>}
        <MenuItem onSelect={() => void chooseWorkspace()}><Laptop />这台电脑上的文件夹…</MenuItem>
        <MenuItem onSelect={() => setRemoteOpen(true)}><Server />另一台电脑上的目录（SSH）…</MenuItem>
      </MenuContent>
    </Menu>
    {activeConversation && <Menu>
      <Tip label={PERMISSION[permission].hint}><MenuTrigger asChild>
        <button type="button" aria-label={`权限：${PERMISSION[permission].label}`} className={cn('inline-flex h-7 items-center gap-1.5 rounded-[9px] px-2 text-[12px] hover:bg-hover', permission === 'full_access' ? 'text-fg-3 hover:text-fg' : 'bg-brand-soft text-fg')}>
          {permission === 'read_only' ? <Lock size={15} /> : permission === 'full_access' ? <ShieldCheck size={15} /> : <ShieldAsk size={15} />}{permission !== 'full_access' && PERMISSION[permission].label}
        </button>
      </MenuTrigger></Tip>
      <MenuContent side="top">
        <MenuLabel>这个对话的权限</MenuLabel>
        {(['ask_each', 'ask_writes', 'auto_file', 'plan', 'full_access', 'read_only'] as const).map((mode) => <MenuItem key={mode} checked={permission === mode} onSelect={() => {
          // External Agents only run with full access; a stricter mode hands the work back to Atlas.
          const executor = activeConversation.executor && activeConversation.executor !== 'atlas' && mode !== 'full_access' ? { executor: 'atlas' } : {};
          store.setConversationSettings(activeConversation.id, { permission_mode: mode, ...executor });
          if ('executor' in executor) setToast('外部 Agent 只能在「完全访问」下用，已换回 Atlas');
        }}>
          <span className="min-w-0"><span className="block">{PERMISSION[mode].label}</span><small className="block text-[11.5px] text-fg-3">{PERMISSION[mode].hint}</small></span>
        </MenuItem>)}
      </MenuContent>
    </Menu>}
    {activeConversation && <Suspense fallback={null}><RunSetupMenu conversation={activeConversation} workspace={workspacePath}
      onChange={(patch) => store.setConversationSettings(activeConversation.id, patch)}
      onPickFolder={async () => window.atlasDesktop?.selectDirectory
        ? window.atlasDesktop.selectDirectory(workspacePath || undefined)
        : window.prompt('允许访问的目录（完整路径）', '')?.trim() || null} /></Suspense>}
    {store.profiles.length > 0 && <Menu>
      <Tip label={`角色：${profileName}`}><MenuTrigger asChild>
        <button type="button" aria-label={`角色：${profileName}`} className={cn('inline-flex h-7 items-center gap-1.5 rounded-[9px] px-2 text-[12px] hover:bg-hover', store.profileId !== 'default' ? 'bg-brand-soft text-fg' : 'text-fg-3 hover:text-fg')}>
          <UserCog size={15} />{store.profileId !== 'default' && profileName}
        </button>
      </MenuTrigger></Tip>
      <MenuContent side="top">
        <MenuLabel>角色</MenuLabel>
        {store.profiles.map((profile) => <MenuItem key={profile.id} checked={profile.id === store.profileId} hint={profile.mode === 'plan' ? '只读' : ''} onSelect={() => store.setProfile(profile.id)}>
          <span className="min-w-0"><span className="block">{profile.name}</span>{profile.description && <small className="block truncate text-[11.5px] text-fg-3">{profile.description}</small>}</span>
        </MenuItem>)}
      </MenuContent>
    </Menu>}
    {Boolean(currentModel?.supports_reasoning_effort) && <Menu>
      <Tip label={store.reasoningEffort ? `推理：${EFFORT_LABEL[store.reasoningEffort]}` : '推理档位：模型默认'}><MenuTrigger asChild>
        <button type="button" aria-label="推理档位" className={cn('inline-flex h-7 items-center gap-1.5 rounded-[9px] px-2 text-[12px] hover:bg-hover', store.reasoningEffort ? 'bg-brand-soft text-fg' : 'text-fg-3 hover:text-fg')}>
          <Brain size={15} />{store.reasoningEffort && EFFORT_LABEL[store.reasoningEffort]}
        </button>
      </MenuTrigger></Tip>
      <MenuContent side="top">
        <MenuLabel>推理档位</MenuLabel>
        <MenuItem checked={!store.reasoningEffort} onSelect={() => store.setReasoningEffort('')}>模型默认</MenuItem>
        {(['minimal', 'low', 'medium', 'high'] as const).map((effort) => <MenuItem key={effort} checked={store.reasoningEffort === effort} onSelect={() => store.setReasoningEffort(effort)}>{EFFORT_LABEL[effort]}</MenuItem>)}
      </MenuContent>
    </Menu>}
    {workspaceName && !remoteHost && <Menu onOpenChange={(opening) => { if (opening && !worktreeActive) void backend.getBranches(String(activeConversation?.workspace)).then((result) => { setBranches(result.branches); setGitBranch(result.current); }).catch(() => { setBranches([]); setGitBranch(''); }); }}>
      <Tip label={worktreeActive ? `在独立分支 ${activeConversation?.worktree_branch} 上工作` : worktreeRequested ? '下一条会在独立 worktree 里执行' : '隔离分支：在独立的 git worktree 里改，不动主目录'}><MenuTrigger asChild>
        <button type="button" aria-label="隔离分支" className={cn('inline-flex h-7 max-w-[150px] items-center gap-1.5 rounded-[9px] px-2 text-[12px] hover:bg-hover', worktreeActive || worktreeRequested ? 'bg-brand-soft text-fg' : 'text-fg-3 hover:text-fg')}>
          <GitBranch size={15} className="shrink-0" />{(worktreeActive || worktreeRequested) && <span className="truncate">{worktreeActive ? String(activeConversation?.worktree_branch ?? '') : '隔离'}</span>}
        </button>
      </MenuTrigger></Tip>
      <MenuContent side="top">
        {worktreeActive ? <>
          <MenuLabel>{`独立分支 ${activeConversation?.worktree_branch}，基于 ${activeConversation?.base_branch}`}</MenuLabel>
          <MenuItem onSelect={() => showInspectorTab('context')}>查看、合并或删除…</MenuItem>
        </> : <>
          <MenuLabel>在独立 worktree 里执行，起始分支</MenuLabel>
          {worktreeRequested && <MenuItem onSelect={() => store.requestWorktree(store.activeConversationId, null)}>取消隔离</MenuItem>}
          <MenuItem onSelect={() => store.requestWorktree(store.activeConversationId, '')}>当前分支</MenuItem>
          {branches.length > 0 && <MenuSeparator />}
          {branches.map((branch) => <MenuItem key={branch} checked={store.worktreeRequests[store.activeConversationId]?.base_branch === branch} onSelect={() => store.requestWorktree(store.activeConversationId, branch)}>{branch}</MenuItem>)}
        </>}
      </MenuContent>
    </Menu>}
    <Tip label={store.nextRunMode === 'plan' ? '下一条会先出计划，等你批准' : '先出计划：只读探索，批准后再动手'}>
      <button type="button" aria-pressed={store.nextRunMode === 'plan'} onClick={() => store.setNextRunMode(store.nextRunMode === 'plan' ? 'act' : 'plan')}
        className={cn('inline-flex h-7 items-center gap-1.5 rounded-[9px] px-2 text-[12px]', store.nextRunMode === 'plan' ? 'bg-brand-soft text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg')}>
        <ListChecks size={15} />{store.nextRunMode === 'plan' && '先出计划'}
      </button>
    </Tip>
  </>;
  const composerBase = {
    value: input, onChange: setInput, attachments, onPickImages: addFiles, onPickFolders: addFolderReferences, listening, onToggleMic: () => { void toggleSpeechInput(); },
    speechInputMode, onStartMic: () => { void toggleSpeechInput(true); }, onStopMic: () => { void stopSpeechInput(); },
    attachmentProgress, failedAttachmentCount: failedAttachmentReads.length, onRetryFailedAttachments: retryFailedAttachments,
    onEnhancePrompt: enhancePrompt, onAttachDrawing: attachDrawing, contextKey: store.activeConversationId,
    onExternalEditor: () => {
      const open = window.atlasDesktop?.openMessageEditor;
      if (!open) { setToast('外部编辑器只在桌面版可用'); return; }
      void open(input).then((text) => { if (text !== null) { setInput(text); writeDraft(store.activeConversationId, text); } }).catch((error) => setToast(`编辑器打开失败：${error instanceof Error ? error.message : String(error)}`));
    },
    onRemoveAttachment: (index: number) => setAttachments((items) => items.filter((_, position) => position !== index)),
    onListCaptureWindows: () => window.atlasDesktop?.listCaptureWindows?.() ?? Promise.resolve([]),
    onCaptureWindow: captureWindow, recentScreenshots, onPickRecentScreenshot: addRecentScreenshot, onPickRecentScreenshots: addRecentScreenshots,
    onDeleteRecentScreenshot: (id: string) => { void window.atlasDesktop?.deleteRecentScreenshot?.(id).then(() => setRecentScreenshots((items) => items.filter((item) => item.id !== id))); },
    files, onRemoveFile: (index: number) => setFiles((items) => items.filter((_, position) => position !== index)),
    findMentions, mentions, onAddMention: (item: MentionItem) => { if (item.id) setMentions((current) => [...current, item]); },
    onRemoveMention: (item: MentionItem) => setMentions((current) => current.filter((entry) => !(entry.kind === item.kind && entry.id === item.id))),
    onLongPaste: (text: string) => { addDocuments([new File([text], `粘贴的文本-${new Date().toLocaleTimeString().replace(/:/g, '')}.txt`, { type: 'text/plain' })]); setToast(`粘贴内容有 ${text.length} 个字，已转成附件`); },
    models: store.models, model: store.model, onSelectModel: (id: string) => void store.selectModel(id), onManageModels: () => setSheet('models'),
    status: composerStatus, autoFocus: true, commands: slashCommands,
    contextUsage: usageSummary(activeEvents)?.context,
    contextFiles: [...new Set([
      ...(activeRun ? store.runPrompts[activeRun.id]?.refs?.files ?? [] : []),
      ...(activeRun ? store.runPrompts[activeRun.id]?.files.map((file) => file.name) ?? [] : []),
      ...activeEvents.flatMap((event) => {
        if (event.type !== 'tool.started' && event.type !== 'tool.completed') return [];
        const data = event.data as Record<string, unknown>;
        const name = String(data.name ?? '').toLowerCase();
        if (!/(read|file|grep|glob|search)/.test(name)) return [];
        const args = (data.arguments ?? data.input) as Record<string, unknown> | undefined;
        const path = args?.path ?? args?.file_path ?? args?.file ?? args?.directory;
        return typeof path === 'string' && path.trim() ? [path] : [];
      }),
    ])],
    onCyclePermission: activeConversation ? cyclePermission : undefined,
    tools: <Tip label={!computerReady ? 'Computer Use 尚未就绪或当前权限模式不支持' : computerUseEnabled ? '本轮允许 Atlas 使用电脑操控' : '本轮关闭电脑操控'}>
      <button type="button" disabled={!computerReady || permission !== 'full_access'} aria-pressed={computerUseEnabled} onClick={() => setComputerUseEnabled((value) => { const next = !value; setPref('computer-use-enabled', String(next)); return next; })}
        className={cn('inline-flex h-7 items-center gap-1 rounded-lg px-2 text-[11.5px]', computerUseEnabled && computerReady && permission === 'full_access' ? 'bg-brand-soft text-brand' : 'text-fg-3 hover:bg-hover disabled:opacity-40')}>
        <Monitor size={14} />电脑操控{computerUseEnabled ? '开' : '关'}
      </button>
    </Tip>,
  };
  const rateFailure = [...(activeRun?.events ?? [])].reverse().find((event) => event.type === 'run.failed'
    && (['rate_limit', 'billing'].includes(String(event.data.category)) || event.data.reason === 'rate_limit' || /rate.?limit|quota|额度|限流|429|余额/i.test(String(event.data.detail ?? ''))))?.data;
  const rateRetrySeconds = typeof rateFailure?.retry_after_seconds === 'number' ? Math.max(0, Math.ceil(rateFailure.retry_after_seconds)) : 30;
  const selectedProvider = store.models.find((item) => item.id === store.model)?.provider?.toLowerCase()
    || store.models.find((item) => item.id === store.model)?.hermes_provider?.toLowerCase() || '';
  const usagePage = PROVIDER_USAGE_URL[selectedProvider];
  const errorNote = (store.error || rateFailure) && <div role="alert" className="anim-fade mt-3 flex items-start justify-between gap-3 rounded-xl bg-danger-soft px-4 py-2.5 text-[13px] text-danger">
    <div className="min-w-0">
      <span>{store.error || String(rateFailure?.detail ?? '服务商报告了限额错误，任务已暂停')}</span>
      {/* 原始报错（多为英文）不直接糊给用户，收进可展开的详情。 */}
      {store.errorDetail && <details className="mt-0.5">
        <summary className="cursor-pointer select-none text-[12px] text-fg-3 hover:text-fg-2">详细信息</summary>
        <pre className="mt-1 mb-0 max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-[11.5px] text-fg-3">{store.errorDetail}</pre>
      </details>}
      {(rateFailure || /rate.?limit|quota|额度|限流|429|余额/i.test(`${store.error} ${store.errorDetail ?? ''}`)) && <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="button" className="rounded-md border border-danger/30 px-2 py-1 text-[11.5px] hover:bg-danger/10" onClick={() => {
          if (!activeRun) { setToast('当前没有可重试的任务'); return; }
          if (!rateRetrySeconds) { void useAtlasStore.getState().retryRun(activeRun.id); return; }
          setToast(`${rateRetrySeconds} 秒后重试当前任务`); window.setTimeout(() => { if (useAtlasStore.getState().runPrompts[activeRun.id]) void useAtlasStore.getState().retryRun(activeRun.id); }, rateRetrySeconds * 1000);
        }}>等待 {rateRetrySeconds} 秒后重试</button>
        <button type="button" className="rounded-md border border-danger/30 px-2 py-1 text-[11.5px] hover:bg-danger/10" onClick={() => setSheet('models')}>换模型</button>
        {usagePage && <a className="rounded-md border border-danger/30 px-2 py-1 text-[11.5px] underline hover:bg-danger/10" href={usagePage.url} target="_blank" rel="noopener noreferrer">打开 {usagePage.label}</a>}
        {rateRetrySeconds > 0 && <span className="text-[11.5px]">{typeof rateFailure?.retry_after_seconds === 'number' ? '等待时间来自提供方响应' : '提供方未返回等待时间，按 30 秒建议重试'}</span>}
      </div>}
    </div>
    <button aria-label="关闭错误提示" onClick={store.dismissError} className="grid size-6 shrink-0 place-items-center rounded-md hover:bg-hover"><X size={14} /></button>
  </div>;

  const latestUsage = [...activeEvents].reverse().find((event) => event.type === 'run.usage')?.data;
  const rawContextLimit = typeof latestUsage?.context_limit === 'number' && latestUsage.context_limit > 0 ? latestUsage.context_limit : null;
  const effectiveContextLimit = rawContextLimit === null ? null : Math.min(rawContextLimit, 200_000);
  const contextUse = typeof latestUsage?.context_tokens === 'number' && effectiveContextLimit
    ? Math.min(100, Math.round(latestUsage.context_tokens / effectiveContextLimit * 100)) : null;
  const rewind = async (messageId: string, files: boolean) => {
    const conversationId = storeRef.current.activeConversationId;
    if (files) {
      const preview = await api<{ changes: Array<{ path: string; status: string; binary: boolean }>; removed_messages: number; legacy: boolean }>(
        storeRef.current.apiBaseUrl, `/api/conversations/${encodeURIComponent(conversationId)}/rewind/preview`,
        { method: 'POST', json: { message_id: messageId } },
      );
      const rows = preview.changes.map((item) => `• ${item.status === 'added' ? '删除新增文件' : item.status === 'deleted' ? '恢复已删除文件' : '恢复修改文件'}：${item.path}${item.binary ? '（二进制）' : ''}`);
      const details = rows.length ? rows.join('\n') : preview.legacy ? '此旧会话没有可用的文件检查点，后端将按旧撤销记录恢复。' : '工作区文件没有变化。';
      if (!window.confirm(`撤销将移除 ${preview.removed_messages} 条消息，并恢复以下工作区文件：\n\n${details}\n\n继续？`)) return;
    }
    const result = await storeRef.current.rewindTo(messageId, files);
    if (!result) return;
    const parts = [`撤回了 ${result.removed_messages} 条消息`];
    if (files) parts.push(result.restored_files.length ? `恢复了 ${result.restored_files.length} 个文件` : '没有文件需要恢复');
    if (result.skipped.length) parts.push(`${result.skipped.length} 个文件没能恢复`);
    setRewound({ conversationId, rewindId: result.rewind_id, text: parts.join('，') });
  };
  /** 历史消息的悬浮操作（改写/撤回/分叉），放进虚拟列表的行里。 */
  const canRewriteRef = useRef(false);
  const historyActions = useCallback((message: HistoryMessage) => {
    if (!canRewriteRef.current || !message.id) return undefined;
    return message.role === 'user'
      ? <>
        <MessageAction label="修改后重新发送" onClick={() => {
          editingDraftRef.current = composerSnapshotRef.current;
          setAttachments([]); setFiles([]); setMentions([]);
          setEditing({ id: message.id, original: message.content }); setInput(message.content);
        }}><Pencil size={13} /></MessageAction>
        <Menu>
          <Tip label="回到这条之前"><MenuTrigger asChild>
            <button aria-label="回到这条之前" className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><Undo2 size={13} /></button>
          </MenuTrigger></Tip>
          <MenuContent side="top" align="end">
            <MenuLabel>回到这条消息之前（可以重做）</MenuLabel>
            <MenuItem onSelect={() => void rewind(message.id, false)}><MessageSquareX />只撤回对话</MenuItem>
            <MenuItem onSelect={() => void rewind(message.id, true)}><RotateCcw />对话和改过的文件一起撤回</MenuItem>
          </MenuContent>
        </Menu>
      </>
      : <>
        <MessageAction label="从这里分叉出一个新对话" onClick={() => void storeRef.current.forkFrom(message.id)}><GitBranch size={13} /></MessageAction>
        <MessageAction label="分叉，并把前面的内容总结成一段" onClick={() => void storeRef.current.forkFrom(message.id, true)}><GitBranchPlus size={13} /></MessageAction>
      </>;
    // rewind 通过 storeRef 读最新状态，动作保持稳定，虚拟列表的行不必跟着重渲染。
  }, []);
  const rewindBanner = rewound && rewound.conversationId === store.activeConversationId && <div className="mb-2.5 flex items-center gap-2.5 pb-2.5 text-[12.5px] text-fg-2 shadow-[inset_0_-1px_0_var(--line)]">
    <Undo2 size={13} />{rewound.text}
    <span className="flex-1" />
    <Button size="sm" variant="ghost" onClick={() => { void store.redoRewind(rewound.conversationId, rewound.rewindId).then((ok) => { if (ok) { setRewound(null); setToast('已重做，回到撤回之前'); } }); }}>重做</Button>
    <Button size="sm" variant="ghost" onClick={() => setRewound(null)}>知道了</Button>
  </div>;
  const editBanner = editing && <div className="mb-2.5 flex items-center gap-2.5 pb-2.5 text-[12.5px] text-fg-2 shadow-[inset_0_-1px_0_var(--line)]">
    <Pencil size={13} />修改后重新发送，这条之后的对话会被替换
    <span className="flex-1" />
    <Button size="sm" variant="ghost" aria-label="取消修改并恢复之前的草稿" onClick={() => {
      const saved = editingDraftRef.current;
      setEditing(null); editingDraftRef.current = null;
      setInput(saved?.text ?? ''); setAttachments(saved?.attachments ?? []); setFiles(saved?.files ?? []); setMentions(saved?.mentions ?? []);
      requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('textarea[aria-label="消息内容"]')?.focus());
    }}>取消</Button>
  </div>;
  const runHeader = activeRun && !runDone && <div className="mb-2.5 flex items-center gap-2.5 text-[12.5px] text-fg-2 shadow-[inset_0_-1px_0_var(--line)] pb-2.5">
    <Mark className="size-[18px]" working={working} />
    <span role="status" aria-live="polite" aria-atomic="true" className={working ? 'text-fg' : undefined}>{store.paused ? '已暂停' : RUN_LABEL[activeRun.status] ?? '正在处理'}</span>
    {planSteps.length > 0 && <span className="flex items-center gap-2" aria-label="当前计划进度">
      <span className="h-[3px] w-24 overflow-hidden rounded-full bg-line"><i className="block h-full rounded-full bg-brand transition-[width] duration-500" style={{ width: `${completedPlanSteps / planSteps.length * 100}%` }} /></span>
      <span className="tabular-nums">{completedPlanSteps} / {planSteps.length}</span>
    </span>}
    {contextUse !== null && <Tip label="这次对话占用的上下文窗口，快满时可以用 /compact 压缩"><span className={cn('tabular-nums', contextUse >= 80 ? 'text-danger' : 'text-fg-3')}>上下文 {contextUse}%</span></Tip>}
    <span className="flex-1" />
    <div role="radiogroup" aria-label="运行中发送消息的方式" className="flex gap-0.5 rounded-[8px] bg-sunken p-[2px] shadow-[inset_0_0_0_1px_var(--line)]">
      {([['steer', '下一步', '等当前这一步结束后交给任务'], ['redirect', '立即转向', '中止正在生成的回复；工具运行时等工具结束'], ['queue', '排队', '等这次任务做完再发']] as const).map(([id, label, hint], index, all) =>
        <Tip key={id} label={hint}><button type="button" role="radio" aria-label={`${label}：${hint}`} aria-checked={store.followUpMode === id} tabIndex={store.followUpMode === id ? 0 : -1}
          onKeyDown={(event) => {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
            event.preventDefault();
            const offset = event.key === 'ArrowRight' ? 1 : -1;
            const next = (index + offset + all.length) % all.length;
            const options = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="radio"]');
            options?.[next]?.focus();
            store.setFollowUpMode(all[next][0]);
          }}
          onClick={() => store.setFollowUpMode(id)}
          className={cn('h-6 rounded-[6px] px-2 text-[12px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand', store.followUpMode === id ? 'raised text-fg' : 'text-fg-3 hover:text-fg')}>{label}</button></Tip>)}
    </div>
    {store.busy && <>
      <Button size="sm" variant="ghost" aria-label={store.paused ? '继续当前运行' : '暂停当前运行'} onClick={() => store.togglePaused()}>{store.paused ? <Play /> : <Pause />}{store.paused ? '继续' : '暂停'}</Button>
      <Button size="sm" variant="ghost" aria-label="停止当前生成或运行" onClick={() => store.stopTask()}><Square />停止</Button>
    </>}
  </div>;
  const failedRun = [...store.runs].reverse().find((run) => run.conversationId === store.activeConversationId && run.status === 'failed' && store.runPrompts[run.id]);
  const queuedRecovery = (store.queue[store.activeConversationId] ?? []).length > 0;
  const recoveryHeader = (failedRun || queuedRecovery) && <div className="mb-2 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-[12px] text-fg-2">
    <span className="flex-1">上次有未完成的任务</span>
    <button type="button" className="rounded-md bg-brand px-2.5 py-1 text-white" onClick={() => queuedRecovery ? store.resumeQueue(store.activeConversationId) : failedRun && store.retryRun(failedRun.id)}>继续</button>
    <button type="button" className="rounded-md px-2 py-1 text-fg-3 hover:bg-hover" onClick={() => {
      useAtlasStore.setState((state) => {
        const runPrompts = { ...state.runPrompts }; if (failedRun) delete runPrompts[failedRun.id];
        return { runPrompts, queue: { ...state.queue, [store.activeConversationId]: [] } };
      });
    }}>丢弃</button>
  </div>;
  const updateGoal = async (command: string) => {
    const id = store.activeConversationId;
    if (!id) return;
    try {
      const result = await api<{ goal: typeof conversationGoal }>(store.apiBaseUrl, `/api/conversations/${encodeURIComponent(id)}/goal`, { method: 'POST', json: { command } });
      setConversationGoal(result.goal);
    } catch (error) { notify(error instanceof Error ? error.message : '目标操作失败'); }
  };
  const goalHeader = conversationGoal && <div className="mb-2 flex items-center gap-2 rounded-lg bg-brand-soft px-2.5 py-1.5 text-[12px] text-fg-2" aria-label="当前会话目标">
    <ListChecks size={13} className="shrink-0 text-brand" /><span className="min-w-0 flex-1 truncate" title={conversationGoal.subgoals?.length ? conversationGoal.subgoals.map((item, index) => `${conversationGoal.completed_subgoals?.includes(index + 1) ? '✓' : '○'} ${index + 1}. ${item}`).join('\n') : conversationGoal.text}>目标：{conversationGoal.text}{conversationGoal.subgoals?.length ? ` · 子目标 ${conversationGoal.completed_subgoals?.length ?? 0}/${conversationGoal.subgoals.length}` : ''}</span>
    <span className="shrink-0 text-fg-3">{conversationGoal.status === 'active' ? '进行中' : conversationGoal.status === 'paused' ? '已暂停' : conversationGoal.status === 'done' ? '已完成' : conversationGoal.status} · {conversationGoal.turns_used}/{conversationGoal.max_turns}</span>
    <button type="button" title={conversationGoal.status === 'paused' ? '继续目标' : '暂停目标'} aria-label={conversationGoal.status === 'paused' ? '继续目标' : '暂停目标'} onClick={() => void updateGoal(conversationGoal.status === 'paused' ? 'resume' : 'pause')} className="rounded px-1.5 py-1 hover:bg-hover">{conversationGoal.status === 'paused' ? '继续' : '暂停'}</button>
    <button type="button" title="编辑目标" aria-label="编辑目标" onClick={() => { const value = window.prompt('编辑当前目标', conversationGoal.text); if (value?.trim()) void updateGoal(`edit ${value.trim()}`); }} className="rounded px-1.5 py-1 hover:bg-hover">编辑</button>
    <button type="button" title="清除目标" aria-label="清除目标" onClick={() => void updateGoal('clear')} className="rounded px-1.5 py-1 text-danger hover:bg-hover">清除</button>
  </div>;
  const pinnedSummary = summaryEnabled && messages.some((message) => message.role === 'user') && <div className="mx-8 mt-2 mb-1 flex items-start gap-2 rounded-xl border border-edge bg-panel/95 px-3 py-2 shadow-sm">
    <Pin size={13} className="mt-0.5 shrink-0 text-brand" />
    <div className="min-w-0 flex-1 text-[11.5px] leading-relaxed text-fg-2">
      <div className="truncate"><b className="text-fg">任务：</b>{messages.find((message) => message.role === 'user')?.content.replace(/\s+/g, ' ').slice(0, 200)}</div>
      {(() => { const progress = [...messages].reverse().find((message) => message.role === 'assistant')?.content.replace(/\s+/g, ' ').slice(0, 220); return progress ? <div className="mt-0.5 truncate"><b className="text-fg">进度：</b>{progress}</div> : null; })()}
    </div>
    <button type="button" aria-label="关闭置顶摘要" className="rounded px-1 text-fg-3 hover:bg-hover" onClick={() => { setSummaryEnabled(false); setPref('pinned-summary', 'false'); }}><X size={13} /></button>
  </div>;
  const suggestionHeader = turnSuggestions.length > 0 && <div className="mb-2 flex flex-wrap items-center gap-1.5" aria-label="下一步建议">
    <span className="mr-1 text-[11px] text-fg-3">下一步可以：</span>
    {turnSuggestions.map((suggestion) => <button key={suggestion} type="button" className="rounded-full bg-brand-soft px-2.5 py-1 text-[11.5px] text-fg hover:bg-hover" onClick={() => { setTurnSuggestions([]); void store.sendMessage(suggestion); }}>{suggestion}</button>)}
  </div>;

  const localUrls = useMemo(() => {
    const found: string[] = [];
    for (const event of [...activeEvents].reverse()) {
      const text = [event.data.text, event.data.content, event.data.result, event.data.execution && JSON.stringify(event.data.execution)].filter((value) => typeof value === 'string').join(' ');
      for (const match of text.matchAll(/https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(?:\/[^\s'"`<>)\]]*)?/g)) {
        const url = match[0].replace(/[.,;:，。]+$/, '');
        if (!found.includes(url)) found.push(url);
      }
      if (found.length >= 5) break;
    }
    return found;
  }, [activeEvents]);
  const pickElement = (picked: PickedElement) => {
    const block = picked.kind === 'region'
      ? [`页面区域（${picked.url}，见截图）`, picked.text && `区域里的文字：${picked.text}`].filter(Boolean).join('\n')
      : [`页面元素（${picked.url}）`, `选择器：${picked.selector}`, picked.text && `文字：${picked.text}`, `HTML：\n${picked.html}`].filter(Boolean).join('\n');
    setInput((current) => `${current.trim() ? `${current.trimEnd()}\n\n` : ''}${block}\n\n`);
    if (picked.screenshot) setAttachments((current) => current.length < 4 ? [...current, picked.screenshot!] : current);
    setToast(picked.kind === 'region' ? '已把这块区域放进输入框，可以接着框选别处' : '已把元素放进输入框，写上你想怎么改');
  };

  const conversationQueue = store.queue[store.activeConversationId] ?? [];
  const queuePaused = Boolean(store.queuePaused[store.activeConversationId]);
  // The newest todo list in this conversation: the running task's, or the last one a finished task left behind.
  const todoSource = useMemo(() => {
    const own = latestTodos(activeEvents);
    if (own?.todos.length) return { runId: activeRun?.id ?? '', ...own };
    const earlier = [...store.runs].reverse().filter((run) => run.conversationId === store.activeConversationId && run.id !== activeRun?.id);
    for (const run of earlier) {
      const found = latestTodos(run.events);
      if (found?.todos.length) return { runId: run.id, ...found };
    }
    return null;
  }, [activeEvents, activeRun?.id, store.runs, store.activeConversationId]);
  const todoStrip = todoSource && <TodoPanel key={store.activeConversationId} todos={todoSource.todos} revisionKey={`${todoSource.runId}:${todoSource.revision}`}
    running={Boolean(activeRun && !runDone)} onSubmit={(todos) => store.submitTodos(store.activeConversationId, todos)} />;
  const queueStrip = <ConversationQueuePanel key={store.activeConversationId} conversationId={store.activeConversationId} items={conversationQueue}
    paused={queuePaused} running={Boolean(activeRun && !runDone)} onResume={() => store.resumeQueue(store.activeConversationId)}
    onEdit={(item) => { const taken = store.takeQueued(store.activeConversationId, item.id); if (taken) {
      setInput(taken.content); setAttachments(taken.attachments);
      setFiles(taken.files.map((file) => ({ ...file, size: Math.floor(file.data_base64.length * 3 / 4) })));
      setMentions([...(taken.refs?.files ?? []).map((id) => ({ kind: 'file' as const, id, label: id })), ...(taken.refs?.conversations ?? []).map((id) => ({ kind: 'conversation' as const, id, label: id }))]);
      setToast('队列消息已取回输入框，可编辑后重新发送');
    } }}
    onSendNow={(id) => store.sendQueuedNow(store.activeConversationId, id)} onRemove={(id) => store.removeQueued(store.activeConversationId, id)}
    onRestore={(item, index) => store.restoreQueued(store.activeConversationId, item, index)}
    onMove={(itemId, beforeId) => store.moveQueued(store.activeConversationId, itemId, beforeId)}
    onSteer={(id) => store.steerQueued(store.activeConversationId, id)} />;
  const retryNote = activeRun?.status === 'failed' && store.runPrompts[activeRun.id] && !working && <div className="mt-3 flex items-center gap-3 text-[13px] text-fg-2">
    这次没有完成。<Button size="sm" variant="secondary" aria-label="重试上一次失败的运行" onClick={() => store.retryRun(activeRun.id)}><RotateCcw />重试</Button>
  </div>;

  // Rewriting history mid-run would race the run's own writes.
  const canRewrite = store.connected && !(activeRun && !runDone) && !loadingMessages;
  canRewriteRef.current = canRewrite;

  const pageTitle = view === 'chat' ? activeConversation?.title ?? '新任务' : '';
  const runningConversations = store.runs.filter((run) => !TERMINAL.includes(run.status)).map((run) => run.conversationId);
  const waitingConversations = [...new Set(store.runs.filter((run) => run.status === 'waiting').map((run) => run.conversationId))];
  // One open conversation reads better as a plain title; tabs appear from the second one.
  const showTabs = view === 'chat' && tabs.length > 1 && tabs.includes(store.activeConversationId);
  const connection = !store.connected
    ? store.backendStarting
      ? <span className="inline-flex items-center gap-1.5 text-[12px] text-fg-2"><i className="size-1.5 animate-pulse rounded-full bg-fg-3" />后端启动中{store.startupDetail ? `（${store.startupDetail}）` : '…'}</span>
      : <span className="inline-flex items-center gap-1.5 text-[12px] text-danger"><i className="size-1.5 rounded-full bg-danger" />后端没有连接</span>
    : null;

  return <TooltipProvider>
    <MarkDefs />
    <div className="flex h-full">
      <Sidebar view={view} onGo={go} mini={sideMini || narrow} onToggleMini={toggleMini}
        conversations={store.conversations} conversationsLoading={store.conversationsLoading}
        activeConversationId={store.activeConversationId} loadingConversationId={store.loadingMessagesConversationId}
        onOpenConversation={openConversation} onNewTask={newTask} creating={store.creatingConversation} onSearch={() => setPaletteOpen(true)}
        onJumpMessage={async (conversationId, messageId) => {
          const target = store.conversations.find((item) => item.id === conversationId);
          if (!target) return;
          await openConversation(target);
          for (let page = 0; page < 100; page += 1) {
            const state = useAtlasStore.getState();
            const messages = state.conversationMessages[conversationId] ?? [];
            if (messages.some((message) => String(message.id) === messageId) || !state.messagesHasEarlier[conversationId]) break;
            const oldest = messages[0]?.id;
            await state.loadEarlier(conversationId);
            const updated = useAtlasStore.getState().conversationMessages[conversationId] ?? [];
            if (updated[0]?.id === oldest) break;
          }
          window.dispatchEvent(new CustomEvent('atlas:jump-message', { detail: { conversationId, messageId } }));
        }}
        username={username} subtitle={store.connected ? modelName : store.backendStarting ? '后端启动中…' : '后端没有连接'}
        theme={theme} onToggleTheme={toggleTheme} onSettings={() => setSheet('models')}
        pinned={store.pinned} archived={store.archived} unread={store.unread}
        running={runningConversations} runs={store.runs} onPauseRun={(runId) => {
          const run = store.getRun(runId); if (!run) return;
          try { backend.controlRun(runId, run.status === 'paused' ? 'run.resume' : 'run.pause'); }
          catch (error) { setToast(`后台任务控制失败：${error instanceof Error ? error.message : String(error)}`); }
        }} onStopRun={store.stopRun}
        queued={Object.fromEntries(Object.entries(store.queue).map(([id, items]) => [id, items.length]))}
        waiting={waitingConversations} onSetUnread={store.setConversationUnread}
        onSetWorkspace={(id, workspace) => store.setWorkspace(id, workspace)}
        onRename={(id, title) => void store.renameConversation(id, title)} onDelete={(id) => void store.deleteConversation(id)}
        onTogglePinned={store.togglePinned} onToggleArchived={store.toggleArchived} onExport={(id, format) => void store.exportConversation(id, format)} onDuplicate={(id) => void store.duplicateConversation(id)} onOpenBeside={setBesideId} onOpenInWindow={(id) => window.atlasDesktop?.openConversationWindow?.(id)} />

      <main className="sheet relative my-1.5 mr-1.5 flex min-w-0 flex-1 flex-col overflow-hidden rounded-[12px]">
        <header className="drag flex h-11 shrink-0 items-center gap-1 pr-1.5 pl-5">
          <div className={cn('flex min-w-0 items-center gap-3', showTabs && 'flex-1')}>
            {showTabs
              ? <Suspense fallback={null}><TabStrip tabs={tabs} conversations={store.conversations} activeId={store.activeConversationId} running={runningConversations} onSelect={openConversation} onClose={closeTab} /></Suspense>
              : pageTitle && <span className="truncate text-[13.5px] text-fg-2">{pageTitle}</span>}
            {view === 'chat' && <Suspense fallback={null}><ForkTree conversations={store.conversations} activeId={store.activeConversationId} onOpen={openConversation} running={runningConversations} waiting={waitingConversations} /></Suspense>}
            {connection}
          </div>
          {/* With tabs the left group already fills the bar; its empty part still drags the window. */}
          {!showTabs && <span className="flex-1" />}
          <div className="no-drag flex items-center gap-0.5">
            <Tip label={`告警中心${diagnosticUnread ? ` · ${diagnosticUnread} 条未读` : ''}`}><button type="button" aria-label="打开告警中心" onClick={() => setSheet('diagnostics')} className="relative grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><Bell size={15} />{diagnosticUnread > 0 && <span className="absolute right-0.5 top-0.5 min-w-3.5 rounded-full bg-danger px-1 text-center text-[9px] leading-3 text-white">{diagnosticUnread > 99 ? '99+' : diagnosticUnread}</span>}</button></Tip>
            {/* Read-aloud, auto read-aloud and voice call share one menu so the bar stays quiet. */}
            <Menu>
              <Tip label="语音"><MenuTrigger asChild>
                <button aria-label="语音" className={cn('grid size-8 place-items-center rounded-lg hover:bg-hover', voiceOutput ? 'text-brand' : 'text-fg-3 hover:text-fg')}><AudioLines size={16} /></button>
              </MenuTrigger></Tip>
              <MenuContent align="end">
                <MenuItem onSelect={startVoice}><AudioLines />语音通话</MenuItem>
                {view === 'chat' && <MenuItem onSelect={readLastReply}><Volume2 />朗读最近的回复</MenuItem>}
                <MenuItem checked={voiceOutput} onSelect={toggleVoiceOutput}>自动朗读新回复</MenuItem>
                <div className="grid gap-1.5 border-t border-line px-2.5 py-2 text-[11.5px] text-fg-3" onPointerDown={(event) => event.stopPropagation()}>
                  <label className="flex items-center justify-between gap-3">音色<select aria-label="朗读音色" value={speechVoice} onChange={(event) => { setSpeechVoice(event.target.value); setPref('speech-voice', event.target.value); }} className="max-w-[170px] rounded-md border border-line bg-surface px-1.5 py-1 text-fg">{speechVoices.filter((voice) => voice.lang.toLowerCase().startsWith('zh')).map((voice) => <option key={voice.name} value={voice.name}>{voice.name}</option>)}</select></label>
                  <label className="flex items-center justify-between gap-3">语速<select aria-label="朗读语速" value={speechRate} onChange={(event) => { const rate = Number(event.target.value); setSpeechRate(rate); setPref('speech-rate', String(rate)); }} className="rounded-md border border-line bg-surface px-1.5 py-1 text-fg">{[0.8, 1, 1.2, 1.5].map((rate) => <option key={rate} value={rate}>{rate}×</option>)}</select></label>
                  <button type="button" onClick={() => { cancelRoutedSpeech(); speakText('你好，我是 Atlas。当前音色和语速可以在这里试听。'); }} className="justify-self-end rounded-md px-2 py-1 text-[11.5px] text-fg-2 hover:bg-hover">试听</button>
                </div>
              </MenuContent>
            </Menu>
            {view === 'chat' && <Tip label="任务面板"><button aria-label="切换任务面板" aria-pressed={inspectorOpen} onClick={() => toggleInspector()}
              className={cn('grid size-8 place-items-center rounded-lg hover:bg-hover', inspectorOpen ? 'text-fg' : 'text-fg-3 hover:text-fg')}><PanelRight size={16} /></button></Tip>}
            {window.atlasDesktop && window.atlasDesktop.platform !== 'darwin' && <div className="ml-1.5 flex">
              <button aria-label="最小化窗口" onClick={() => window.atlasDesktop?.minimize()} className="grid h-8 w-10 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><Minus size={15} /></button>
              <button aria-label="最大化窗口" onClick={() => window.atlasDesktop?.maximize()} className="grid h-8 w-10 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg">{maximized ? <Copy size={13} /> : <Square size={12} />}</button>
              <button aria-label="关闭窗口" onClick={() => window.atlasDesktop?.close()} className="grid h-8 w-10 place-items-center rounded-lg text-fg-3 hover:bg-[#D2453E] hover:text-white"><X size={16} /></button>
            </div>}
          </div>
        </header>
        <UpdateBanner />
        {startupWarning && <div role="alert" className="flex items-center gap-3 border-b border-danger/20 bg-danger/10 px-4 py-2 text-[12.5px] text-fg"><ShieldAsk size={15} className="shrink-0 text-danger" /><button type="button" onClick={() => setSheet('diagnostics')} className="min-w-0 flex-1 truncate text-left hover:underline">启动检查发现问题：{startupWarning} · 点击查看 /doctor</button><button type="button" aria-label="关闭启动告警" onClick={() => setStartupWarning('')} className="grid size-6 place-items-center rounded hover:bg-hover"><X size={13} /></button></div>}
        {startupProgress?.phase === 'failed' && !store.connected && <div role="alert" className="mx-4 mt-2 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-danger/25 bg-danger-soft px-4 py-3 text-[12.5px] text-danger">
          <div className="min-w-0"><p className="m-0 font-medium">Atlas 后端启动失败</p><p className="mb-0 mt-1 break-words opacity-85">{startupProgress.message ?? startupProgress.detail ?? '启动遇到问题，Atlas 会在稍后自动重试。'}</p></div>
          <div className="flex shrink-0 gap-2">
            <Button size="sm" variant="secondary" onClick={() => {
              if (window.atlasDesktop?.retryBackend) window.atlasDesktop.retryBackend();
              else void useAtlasStore.getState().initialize();
            }}><RotateCcw size={14} />立即重试</Button>
            <Button size="sm" variant="secondary" onClick={() => { void window.atlasDesktop?.openBackendLog?.(); }}>打开日志</Button>
          </div>
        </div>}
        {!!pendingComponents.length && <div role="status" aria-live="polite" className="mx-4 mt-2 flex items-center gap-2 rounded-lg bg-sunken px-3 py-2 text-[11.5px] text-fg-3">
          <i className="size-1.5 animate-pulse rounded-full bg-brand" />
          正在加载{pendingComponents.map((name) => ({ mcp: 'MCP', plugins: '插件', plugin: '插件', memory: '记忆', lsp: '代码服务', scheduler: '计划任务' }[name.toLowerCase()] ?? name)).join('、')}；可以先发送消息。
        </div>}

        <Suspense fallback={<div aria-label="正在加载页面" className="flex flex-1 flex-col gap-3 p-6" aria-busy="true"><div className="h-5 w-36 animate-pulse rounded bg-hover" /><div className="h-24 animate-pulse rounded-xl bg-sunken" /><div className="h-10 animate-pulse rounded-lg bg-sunken" /></div>}>
        {view === 'home' && <HomeView username={username} notice={errorNote} recent={store.conversations.slice(0, 3)} onOpen={openConversation} onSuggest={suggest} suggestions={homeSuggestions}
          composer={<><Composer {...composerBase} variant="hero" onSubmit={() => void submit(true)}
            placeholder={homeMode === 'image' ? '描述你想要的画面，Atlas 会带你去图像工作台' : '描述一件事，Atlas 会把它做完'}
            modes={{ value: homeMode, options: HOME_MODES, onChange: (id) => { if (id === 'voice') startVoice(); else setHomeMode(id); } }} />
            <div className="mt-1.5 flex min-w-0 items-center gap-0.5 overflow-x-auto px-1 text-[11.5px] text-fg-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" aria-label="运行设置">{runTools}</div></>} />}

        {view === 'chat' && <div className="flex min-h-0 flex-1">
          <Suspense fallback={null}><PaneWorkspace besideId={besideId} activeId={store.activeConversationId} conversations={store.conversations} username={username}
            onSwitch={(conversation) => { const previous = store.activeConversationId; void openConversation(conversation); setBesideId(previous); }}
            onRemove={(id) => { if (besideId === id) setBesideId(''); }}>
          <div className={`relative flex min-w-0 flex-1 flex-col ${paneCount > 0 && mainPaneFocused ? 'ring-1 ring-inset ring-brand/60' : ''}`} onPointerDown={() => setMainPaneFocused(true)}>
            {activeRun && activeRun.conversationId === store.activeConversationId && <div className="pointer-events-none absolute top-2 left-1/2 z-20 flex -translate-x-1/2 justify-center [&>*]:pointer-events-auto">
              <ProgressCapsule run={activeRun} events={activeEvents} onShowAll={() => showInspectorTab('activity')} />
            </div>}
            {computerRunId && <><ComputerEdgeBar apiBaseUrl={store.apiBaseUrl} runId={computerRunId} canPause={Boolean(foregroundEvent)} className="shrink-0" /><ComputerLivePreview runId={computerRunId} events={activeEvents} /></>}
            {!!peerInbox.length && <section className="mx-6 mt-2 rounded-xl border border-brand/20 bg-brand-soft px-3.5 py-2.5" aria-label="跨会话收件箱">
              <div className="flex items-center justify-between gap-3"><b className="text-[12.5px] text-fg">跨会话收件箱 · {peerInbox.length} 条未读</b>
                <button className="text-[11.5px] text-fg-3 hover:text-fg" onClick={() => void api<{ marked_read: number }>(store.apiBaseUrl, `/api/conversations/${encodeURIComponent(store.activeConversationId)}/peer-inbox/read`, { method: 'POST', json: { message_ids: peerInbox.map((item) => item.id) } }).then(() => setPeerInbox([])).catch((error) => setToast(error instanceof Error ? error.message : '标记已读失败'))}>标记已读</button></div>
              <ul className="mb-0 mt-1 grid max-h-24 gap-1 overflow-auto pl-4 text-[12px] text-fg-2">{peerInbox.map((item) => <li key={item.id}><b>{item.sender_title}</b>：{item.content}</li>)}</ul>
            </section>}
            {pinnedSummary}
            <TimelineNav threadRef={threadRef} resetKey={store.activeConversationId}
              history={historyWithBranchNotes} items={timelineItems}
              hasEarlier={Boolean(store.messagesHasEarlier[store.activeConversationId])}
              truncatedCount={activeRun?.eventsTruncated ? (activeRun.droppedEventCount ?? 0) : 0}
              loading={loadingMessages} />
            {store.activeConversationId && <ChaptersNav conversationId={store.activeConversationId} threadRef={threadRef} history={historyWithBranchNotes} events={activeEvents} />}
            <MessageThread history={historyWithBranchNotes} componentSelections={componentSelections} username={username} historyActions={historyActions} threadRef={threadRef} setTab={showInspectorTab}
              onOpenBrowser={(url) => { setBrowserUrl(url); showInspectorTab('browser'); }}
              emptyState={!messages.length && !activeEvents.length && !loadingMessages ? <div className="pt-[16vh] text-center">
                <Mark className="mx-auto mb-4 size-11" />
                <h2 className="m-0 text-[24px] font-semibold text-heading">这次要做什么？</h2>
                <p className="mt-2 text-[14px] text-fg-3">在下面说清楚目标，Atlas 会把过程和结果都放在这里。</p>
              </div> : null}
              footerNote={<>{retryNote}{errorNote}</>} />
            <div className="px-8 pb-5">
              <div className="mx-auto w-[min(760px,100%)]">
                <Suspense fallback={null}>{queueStrip}{todoStrip}</Suspense>
                {activeRun && !runDone && <div className="mb-2 flex items-center gap-2 rounded-lg border border-brand/20 bg-brand-soft px-3 py-2 text-[11.5px] text-fg-2" role="status">
                  <span className="size-1.5 animate-pulse rounded-full bg-brand" />
                  {activeRun && /^\s*\/review\b/i.test(store.runPrompts[activeRun.id]?.content ?? '') ? 'Reviewing · 正在审查' : '运行中 · 新消息可排队或转为优先任务'}
                </div>}
                <Composer {...composerBase} variant="dock" onSubmit={() => void submit(false)} placeholder={activeRun && !runDone ? '接着补充，会在这一步做完后发出…' : '接着说要做什么，/ 看命令，! 开头直接在终端运行…'} header={<>{suggestionHeader}{editBanner}{goalHeader}{recoveryHeader}{runHeader}{rewindBanner}</>} />
                <div className="mt-1 flex min-w-0 items-center gap-1 px-1 text-[11.5px] text-fg-3">
                  <div className="flex min-w-0 shrink items-center gap-0.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" aria-label="运行设置">{runTools}</div>
                  <span className="flex-1" />
                <div className="flex min-w-0 shrink-0 flex-wrap items-center justify-end gap-x-3 gap-y-1" aria-label="运行状态">
                  {statusBar.model && <span className="max-w-36 truncate" title={modelName}>{modelName}</span>}{statusBar.reasoning && <span>推理 {store.reasoningEffort ? EFFORT_LABEL[store.reasoningEffort] : '默认'}</span>}
                  {statusBar.context && contextUse !== null && <Tip label={contextUse >= 80 ? '上下文达到 80% 预警阈值，可用 /compact 压缩' : '上下文占用比例'}><span className={contextUse >= 80 ? 'text-danger' : ''}>上下文 {contextUse}% 已用 · {100 - contextUse}% 剩余</span></Tip>}
                  {statusBar.tokens && typeof latestUsage?.input_tokens === 'number' && <span>用量 {Number(latestUsage.input_tokens) + Number(latestUsage.output_tokens ?? 0)} tokens</span>}
                  {statusBar.cost && typeof latestUsage?.cost_usd === 'number' && <span>${Number(latestUsage.cost_usd).toFixed(4)}</span>}
                  {statusBar.git && (activeConversation?.worktree_branch || gitBranch) && <span className="max-w-32 truncate"><GitBranch size={10} className="mr-1 inline" />{String(activeConversation?.worktree_branch || gitBranch)}</span>}
                  {statusBar.permission && activeConversation && <span>{PERMISSION[permission].label}</span>}
                  {statusBar.processes && processCount !== null && <button onClick={() => showInspectorTab('processes')} className="hover:text-fg">后台进程 {processCount}</button>}
                </div>
                </div>
              </div>
            </div>
          </div>
          </PaneWorkspace></Suspense>
          {inspectorOpen && <Inspector tab={inspectorTab} onTab={setInspectorTab} onClose={() => { setFullScreenDiff(false); toggleInspector(false); }} fullScreenDiff={fullScreenDiff} onFullScreenDiffChange={setFullScreenDiff} run={activeRun} canvasEvents={canvasEvents} artifacts={activeArtifacts}
            conversationTitle={activeConversation?.title} modelName={modelName} tools={store.tools} skills={store.skills} activeSkills={store.activeSkills} capabilities={store.capabilities}
            apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify}
            workspace={typeof activeConversation?.workspace === 'string' ? activeConversation.workspace : null} onChooseWorkspace={() => void chooseWorkspace()}
            browserUrl={browserUrl} onBrowserUrl={setBrowserUrl} browserSuggestions={localUrls} onPick={pickElement}
            onPreview={(url) => { setBrowserUrl(url); showInspectorTab('browser'); }} previewPath={previewFile} conversationId={store.activeConversationId}
            worktree={activeConversation?.worktree_path ? { path: String(activeConversation.worktree_path), branch: String(activeConversation.worktree_branch ?? ''), base: String(activeConversation.base_branch ?? '') } : null}
            onWorktreeChanged={() => void store.refreshConversations()}
            onAsk={(text) => store.sendMessage(text)}
            terminalCommand={terminalCommand} onSendToAtlas={(text) => { setInput((current) => `${current.trim() ? `${current.trimEnd()}\n\n` : ''}终端输出：\n\`\`\`\n${text.trimEnd()}\n\`\`\`\n\n`); setToast('已把终端输出放进输入框'); }} />}
        </div>}

    {view === 'board' && <BoardPage apiBaseUrl={store.apiBaseUrl} conversations={store.conversations} runs={store.runs} queue={store.queue} unread={store.unread} archived={store.archived}
      onOpen={openConversation} onStop={store.stopRun} onArchive={store.toggleArchived} />}
    {view === 'agents' && <AgentsOverview runs={store.runs} conversations={store.conversations} apiBaseUrl={store.apiBaseUrl} onOpen={openConversation} onStop={store.stopRun} roster={<AgentsPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} username={username} />} />}
    {view === 'devices' && <DevicesPage onToast={notify} />}
    {view === 'workbench' && <WorkbenchPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
    {(view === 'skills' || view === 'library') && <LibraryPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify}
      market={<SkillsMarketPage apiBaseUrl={store.apiBaseUrl} onToast={notify} onTryInConversation={(name) => { store.applySkill(name); go('chat'); }} />} />}
    {view === 'groups' && <GroupsView onToast={notify} />}
    {view === 'code' && <CodePage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
        {view === 'create' && <CreatePage onDraft={draft} onVoice={startVoice} apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} initialPrompt={createPrompt} workspace={store.draftWorkspace ?? defaultWorkspace} />}
        {view === 'auto' && <AutomationPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
        {view === 'memory' && <MemoryPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
        {view === 'evolution' && <EvolutionPage apiBaseUrl={store.apiBaseUrl} onToast={notify} />}
        </Suspense>
      </main>
    </div>

    <Suspense fallback={<div aria-label="正在加载设置" className="fixed inset-0 z-50 grid place-items-center bg-black/20 text-[12px] text-fg-3" aria-busy="true">正在加载设置…</div>}>
    <Dialog open={Boolean(sheet)} onOpenChange={(open) => { if (!open) { setSheet(null); setSettingsQuery(''); } }} label="设置"
      className="grid h-[min(720px,calc(100vh-48px))] w-[min(980px,calc(100vw-32px))] grid-cols-[210px_minmax(0,1fr)]">
      <nav aria-label="设置分类" className="overflow-y-auto bg-sunken px-2.5 py-5 shadow-[inset_-1px_0_0_var(--line)]">
        <h2 className="m-0 px-2.5 pb-3 text-[18px] font-semibold text-heading">{t('设置', readLocale())}</h2>
        <label className="mx-1 mb-3 flex h-9 items-center gap-2 rounded-lg bg-surface px-2.5 shadow-[inset_0_0_0_1px_var(--line)] focus-within:shadow-[inset_0_0_0_1px_var(--brand)]">
          <Search size={14} className="shrink-0 text-fg-3" />
          <input aria-label="搜索设置" value={settingsQuery} onChange={(event) => setSettingsQuery(event.target.value)} placeholder="搜索设置项…" className="min-w-0 flex-1 bg-transparent text-[12px] text-fg outline-none placeholder:text-fg-3" />
          {settingsQuery && <button type="button" aria-label="清除设置搜索" onClick={() => setSettingsQuery('')} className="text-[11px] text-fg-3 hover:text-fg">清除</button>}
        </label>
        {SETTINGS_NAV.filter(([, label, , terms]) => `${label} ${terms}`.toLocaleLowerCase().includes(settingsQuery.trim().toLocaleLowerCase())).map(([pane, label, Icon]) =>
          <button key={pane} aria-current={sheet === pane} onClick={() => setSheet(pane)}
            className={cn('flex h-9 w-full items-center gap-2.5 rounded-[9px] px-2.5 text-left text-[13.5px] transition-colors', sheet === pane ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
            <Icon size={16} className={sheet === pane ? 'text-brand' : undefined} />{t(label, readLocale())}
          </button>)}
        {settingControlMatches.length > 0 && <div className="mt-2 border-t border-line pt-2" aria-label="匹配的设置控件"><p className="px-2.5 pb-1 text-[10.5px] text-fg-3">当前分类中的设置项</p>{settingControlMatches.map((match) => <button key={match.id} type="button" onClick={() => {
          setSheet(match.pane);
          window.setTimeout(() => {
            const target = settingsContentRef.current?.querySelector<HTMLElement>(`[data-setting-search-id="${CSS.escape(match.id)}"]`);
            target?.scrollIntoView({ block: 'center', behavior: 'smooth' });
            if (target) { const prior = target.style.boxShadow; target.style.boxShadow = '0 0 0 3px var(--brand)'; window.setTimeout(() => { if (target.style.boxShadow.includes('var(--brand)')) target.style.boxShadow = prior; }, 1400); }
          }, 140);
        }} className="block w-full truncate rounded-md px-2.5 py-1.5 text-left text-[11.5px] text-fg-2 hover:bg-hover">{t(match.label, readLocale())}</button>)}</div>}
        {settingsQuery.trim() && !settingControlMatches.length && SETTINGS_NAV.every(([, label, , terms]) => !`${label} ${terms}`.toLocaleLowerCase().includes(settingsQuery.trim().toLocaleLowerCase())) && <p className="px-2.5 py-2 text-[11px] text-fg-3">没有匹配的设置。</p>}
        <button onClick={() => { setSheet(null); setOnboardingOpen(true); }} className="mt-3 flex h-9 w-full items-center gap-2.5 rounded-[9px] px-2.5 text-left text-[13px] text-fg-3 hover:bg-hover hover:text-fg">
          <Sparkles size={16} />开始向导</button>
        <button onClick={() => { setSheet(null); setFeatureLessonsOpen(true); }} className="flex h-9 w-full items-center gap-2.5 rounded-[9px] px-2.5 text-left text-[13px] text-fg-3 hover:bg-hover hover:text-fg">
          <Sparkles size={16} />交互式功能课程</button>
      </nav>
      <div ref={settingsContentRef} className="relative min-h-0 overflow-auto px-8 pt-7 pb-8">
        <button aria-label="关闭设置" onClick={() => { setSheet(null); setSettingsQuery(''); }} className="absolute top-4 right-4 grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><X size={17} /></button>
        {sheet === 'models' && <><div className="mb-4 flex items-center justify-between rounded-xl border border-edge bg-sunken px-3 py-2"><span className="text-[12px] text-fg-2">主模型失败后，按备用链顺序继续本轮</span><Button size="sm" variant="secondary" onClick={() => setFallbackOpen(true)}>备用模型链</Button></div><SettingsPage username={username} onSaveUsername={saveUsername} apiBaseUrl={store.apiBaseUrl} providerBaseUrl={store.providerBaseUrl} connected={store.connected} apiKeyConfigured={store.apiKeyConfigured} busy={store.settingsBusy} connectionTest={store.connectionTest} error={store.error} errorDetail={store.errorDetail} models={store.models} selectedModel={store.model} subagentsEnabled={store.subagentsEnabled} subagentDefaultModel={store.subagentDefaultModel} onSaveSubagentSettings={(enabled, model) => store.saveSubagentSettings(enabled, model)} providers={store.providers} reasoningStages={store.reasoningStages} onBack={() => setSheet(null)} onSelectModel={(model) => void store.selectModel(model)} onSaveProvider={(baseUrl, apiKey) => store.saveProviderSettings(baseUrl, apiKey)} onAddModel={(model) => store.addCustomModel(model)} onTestConnection={(model) => void store.testModelConnection(model)} statusBar={statusBar} onStatusBarChange={updateStatusBar} onLoadProviders={store.loadProviders} onSaveProviderConfig={store.saveProviderConfig} onAddProviderKey={(providerId, secret, label) => store.addProviderKey(providerId, secret, label)} onRemoveProviderKey={(providerId, keyId) => void store.removeProviderKey(providerId, keyId)} onUpdateModel={(modelId, patch) => store.updateCustomModel(modelId, patch)} onDeleteModel={(modelId) => store.deleteCustomModel(modelId)} onSaveReasoningStages={(config) => store.saveReasoningStages(config)} /></>}
        {sheet === 'advanced' && <section>
          <h3 className="m-0 text-[17px] font-semibold text-heading">高级设置</h3>
          <p className="mt-1 mb-5 text-[13px] text-fg-3">配置会话压缩使用的辅助模型。</p>
          <label className="block max-w-[420px] text-[13px] text-fg-2">压缩辅助模型
            <select aria-label="压缩辅助模型" value={store.compressionModel} disabled={store.settingsBusy}
              onChange={(event) => void store.saveCompressionModel(event.target.value)}
              className="mt-2 block h-10 w-full rounded-lg border border-line bg-surface px-3 text-fg">
              <option value="">跟随当前模型</option>
              {store.models.map((model) => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}
            </select>
            <small className="mt-1 block text-fg-3">默认使用当前模型；也可以为 Hermes 上下文压缩单独选一个已配置模型。</small>
          </label>
          {store.error && <p role="alert" className="mt-3 text-[13px] text-danger">{store.error}</p>}
          <div className="mt-8 border-t border-line pt-6">
            <LspStatusSection workspace={workspacePath} connected={store.connected} />
          </div>
        </section>}
        {sheet === 'appearance' && <section>
          <h3 className="m-0 text-[17px] font-semibold text-heading">外观与语音</h3>
          <p className="mt-1 mb-5 text-[13px] text-fg-3">只影响这台电脑。</p>
          <AppearanceNotificationsPanel theme={theme} onThemeChange={chooseTheme} username={username} onSaveUsername={saveUsername} onToast={notify} section="all"
            speechVoice={speechVoice} speechVoices={speechVoices} speechRate={speechRate}
            onSpeechVoiceChange={(value) => { setSpeechVoice(value); setPref('speech-voice', value); }}
            onSpeechRateChange={(value) => { setSpeechRate(value); setPref('speech-rate', String(value)); }}
            onSpeechPreview={() => { cancelRoutedSpeech(); speakText('你好，我是 Atlas。当前音色和语速可以在这里试听。'); }} />
          <div className="mt-7"><NotificationsPanel apiBaseUrl={store.apiBaseUrl} /></div>
          <div className="set-list">
            <div className="set-row"><div>置顶任务摘要<small>在长对话顶部显示首条目标和最近进度</small></div><button className="switch" role="switch" aria-label="置顶任务摘要" aria-checked={summaryEnabled} onClick={() => { const next = !summaryEnabled; setSummaryEnabled(next); setPref('pinned-summary', String(next)); }} /></div>
            <div className="set-row"><div>显示消息时间戳<small>在对话中的每条消息旁显示本地时间</small></div><button className="switch" role="switch" aria-label="显示消息时间戳" aria-checked={messageTimestampsEnabled} onClick={() => { const next = !messageTimestampsEnabled; setMessageTimestampsEnabled(next); setPref('message-timestamps', String(next)); window.dispatchEvent(new Event('atlas:message-timestamps-changed')); }} /></div>
            <div className="set-row"><div>收起侧边栏<small>只显示图标，给内容更多空间</small></div><button className="switch" role="switch" aria-label="收起侧边栏" aria-checked={sideMini} onClick={toggleMini} /></div>
            <div className="set-row"><div>自动朗读新回复<small>用本机语音逐句读出 Atlas 的回答</small></div><button className="switch" role="switch" aria-label="自动朗读新回复" aria-checked={voiceOutput} onClick={toggleVoiceOutput} /></div>
            <div className="set-row"><div>按住说话<small>按住输入框麦克风录音，松开后结束识别；关闭时点击切换录音</small></div><button className="switch" role="switch" aria-label="按住说话模式" aria-checked={speechInputMode === 'hold'} onClick={() => setSpeechInputMode((mode) => mode === 'hold' ? 'toggle' : 'hold')} /></div>
            <div className="set-row"><div>转写后自动发送<small>关闭时只填入草稿，默认关闭</small></div><button className="switch" role="switch" aria-label="转写后自动发送" aria-checked={speechAutoSend} onClick={() => setSpeechAutoSend((value) => !value)} /></div>
            <div className="set-row"><div>本地唤醒词<small>后台监听只发送音频到 Atlas 本机识别服务</small></div><button className="switch" role="switch" aria-label="本地唤醒词" aria-checked={wakeEnabled} onClick={() => setWakeEnabled((value) => !value)} /></div>
          </div>
          <label className="mt-3 grid max-w-[760px] gap-1 text-[12px] text-fg-2">唤醒词<input value={wakeWord} onChange={(event) => setWakeWord(event.target.value)} placeholder="你好 Atlas" className="h-9 rounded-lg border border-line bg-surface px-2.5 text-[12px]" /></label>
          {wakeEnabled && <p className="mt-2 text-[11.5px] text-fg-3">{wakeTranscript ? `本地识别：${wakeTranscript}` : '已开启本地监听；需先在语音识别配置中下载本地模型。'}</p>}
          <div className="mt-5"><AudioDevicesPanel onToast={notify} /></div>
        </section>}
        {sheet === 'u4' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">会话与顾问</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">顾问模型、会话预设、历史导入和手机推送。</p><U4SettingsPanel apiBaseUrl={store.apiBaseUrl} models={store.models} currentModel={store.model} onToast={notify} onImported={() => void store.refreshConversations()} onApplyPreset={(preset) => {
          store.beginConversationDraft(preset.workspace || null);
          if (preset.model) void store.selectModel(preset.model);
          if (preset.reasoning_effort) store.setReasoningEffort(preset.reasoning_effort as Parameters<typeof store.setReasoningEffort>[0]);
          for (const skill of preset.skills ?? []) store.applySkill(skill);
          try { localStorage.setItem('atlas.preference.session-env-next', JSON.stringify(preset.env ?? {})); } catch { /* local-only */ }
          setSheet(null); go('chat'); notify(`已应用会话预设「${preset.label}」`);
        }} /></section>}
        {sheet === 'usage' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">用量</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">每次任务用了多少 token、缓存帮你省了多少、大概花了多少钱。</p><UsagePanel username={username} onSaveUsername={saveUsername} apiBaseUrl={store.apiBaseUrl} conversationId={activeConversation?.id ?? null} onOpenModels={() => setSheet('models')} /></section>}
        {sheet === 'plugins' && <section>
          <h3 className="m-0 text-[17px] font-semibold text-heading">插件与扩展</h3>
          <p className="mt-1 mb-5 text-[13px] text-fg-3">给 Atlas 增加新的工具和能力，也可以把 Claude Code / Codex 里已有的配置搬进来。</p>
          <div className="grid gap-3.5">
            <PluginsPanel apiBaseUrl={store.apiBaseUrl} />
            <ImportPanel workspace={workspacePath || undefined} />
          </div>
        </section>}
        {sheet === 'profiles' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">角色</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">把指令、模型、技能、工具和模式打包成一个角色，在输入框里一键切换。</p>
          <div className="grid gap-8"><ProfilesPanel profiles={store.profiles} models={store.models} skills={store.skills} onChanged={() => void store.reloadProfiles()} /><OutputStyleSettingsPanel apiBaseUrl={store.apiBaseUrl} /></div></section>}
        {sheet === 'tools' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">脚本工具</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">用一个小脚本给 Atlas 加新能力。</p><ScriptToolsPanel /></section>}
        {sheet === 'telegram' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">手机远程（Telegram）</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">不在电脑前时，用手机给 Atlas 布置任务、看结果、批准操作。</p><TelegramPanel /></section>}
        {sheet === 'channels' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">Gateway 与渠道账号</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">配置当前已注册渠道的账号和密钥；消息进来后交给哪个 Agent，在 Agents → Channels 里绑定。</p><ChannelsSettings apiBaseUrl={store.apiBaseUrl} onToast={notify} /></section>}
        {sheet === 'devices' && <div className="-mx-2 -mt-1"><DevicesPage onToast={notify} /></div>}
        {sheet === 'localModels' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">本地模型</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">管理本机 GGUF 模型；Ollama 模型在 loopback 上独立发现、下载并注册到 Atlas。</p><div className="grid gap-8"><LocalModelsSettings apiBaseUrl={store.apiBaseUrl} onToast={notify} /><LocalModelsPanel apiBaseUrl={store.apiBaseUrl} /></div></section>}
        {sheet === 'mainConfig' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">主体配置</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">直接查看和修改 Atlas 主体的配置文件。</p><MainConfigPanel apiBaseUrl={store.apiBaseUrl} onToast={notify} /></section>}
        {sheet === 'expert' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">专家模式</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">开着时在普通配置之上额外加载你自己仓库里装上的提示词、技能、插件、工具和 MCP。</p><ExpertModePanel apiBaseUrl={store.apiBaseUrl} onToast={notify} /></section>}
        {sheet === 'network' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">模型网络</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">为支持的模型连接配置本机代理与自定义 CA 证书。</p><NetworkSettingsPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'shortcuts' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">快捷键</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">改成你顺手的组合键，也同步到数据目录的 keybindings.json。</p><ShortcutsPanel apiBaseUrl={store.apiBaseUrl} models={store.models} /></section>}
        {sheet === 'hooks' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">Hooks</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">在任务开始、用工具前后、完成或失败时运行你自己的命令。</p><HooksPanel /></section>}
        {sheet === 'mcp' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">MCP 服务</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">管理 Atlas 已支持的 MCP 服务，并浏览服务显式提供的资源。</p><div className="grid gap-8"><McpServersPanel apiBaseUrl={store.apiBaseUrl} /><McpResourcesPanel apiBaseUrl={store.apiBaseUrl} /></div></section>}
        {sheet === 'skills' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">Skills</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">搜索、安装和审阅技能；外部技能会先进入安全复核。</p><SkillsMarketPage apiBaseUrl={store.apiBaseUrl} onToast={notify} onTryInConversation={(name) => { store.applySkill(name); go('chat'); setSheet(null); }} /></section>}
        {sheet === 'recipes' && <RecipeManagerPanel apiBaseUrl={store.apiBaseUrl} models={store.models} providers={store.providers} onLaunch={launchRecipeTemplate} />}
        {sheet === 'extensions' && <div className="grid gap-8"><ExtensionCatalogPanel apiBaseUrl={store.apiBaseUrl} /><ExtensionPackagesPanel apiBaseUrl={store.apiBaseUrl} /></div>}
        {sheet === 'transfer' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">配置导入导出</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">转移允许携带的本地偏好；密钥、地址和路径不会进入导出文件。</p><ConfigTransferPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'diagnostics' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">本机诊断</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">查看配置来源、告警历史、运行时调试和后台任务。密钥值会隐藏。</p><DiagnosticsPanel apiBaseUrl={store.apiBaseUrl} workspacePath={typeof activeConversation?.workspace === 'string' ? activeConversation.workspace : ''} /></section>}
        {sheet === 'security' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">工作区安全与会话设置</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">管理当前对话后续运行的权限、Docker 隔离、模型和凭据。</p>{activeConversation ? <><WorkspaceSecurityPanel apiBaseUrl={store.apiBaseUrl} conversation={activeConversation} onChange={(patch) => store.setConversationSettings(activeConversation.id, patch)} /><Suspense fallback={<div className="text-[11px] text-fg-3">正在加载会话模型设置…</div>}><ConversationModelSettings apiBaseUrl={store.apiBaseUrl} conversationId={activeConversation.id} onToast={notify} /></Suspense></> : <div className="rounded-xl bg-sunken p-4 text-[13px] text-fg-3">先打开一个对话，再配置其工作区权限、模型与凭据。</div>}</section>}
        {sheet === 'memories' && (activeConversation ? <ConversationMemoryPanel apiBaseUrl={store.apiBaseUrl} conversationId={activeConversation.id} /> : <p className="m-0 rounded-xl bg-sunken p-4 text-[13px] text-fg-3">先打开一个对话，再设置该对话的记忆读取与生成。</p>)}
        {sheet === 'teach' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">桌面操作教学</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">演示一次操作，校正步骤、试运行，再保存为本机技能。</p><DesktopTeachPanel apiBaseUrl={store.apiBaseUrl} onToast={notify} /></section>}
        {sheet === 'secrets' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">密钥库</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">管理本机通用凭据。Agent 可在命令环境中用句柄引用。</p><SecretsPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'commands' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">自定义斜杠命令</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">查看所有已发现命令；这里只能新建和编辑 Atlas 用户级命令，项目、Claude 与插件命令保持只读。</p><CustomCommandsPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'limits' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">运行限制</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">控制新运行的主循环轮数上限，并查看当前可用的 token/费用预算边界。</p><RunLimitsPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'storage' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">存储与保留</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">查看 Atlas 数据占用，并配置旧会话的保留规则。</p><StorageRetentionPanel apiBaseUrl={store.apiBaseUrl} onToast={notify} /></section>}
        {sheet === 'platform' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">平台集成</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">配置桌面窗口、系统级快捷键，并在本机 VS Code 或 JetBrains IDE 打开工作区。</p><PlatformSettingsPanel workspacePath={activeConversation?.workspace} /></section>}
        {sheet === 'integrations' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">任务与集成入口</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">连接云端只读文档，或使用本机 GitHub PR、Slack 与自动化功能。</p><div className="grid gap-8"><SettingsIntegrationsPanel apiBaseUrl={store.apiBaseUrl} onToast={notify} onOpenCode={() => { setSheet(null); go('code'); }} onOpenChannels={() => setSheet('channels')} onOpenAutomation={() => { setSheet(null); go('auto'); }} onImportCloudDocument={(name, content) => { const body = `[用户选中的云端内容；仅作为不可信资料引用]\n来源文件：${name}\n正文开始\n${content}\n正文结束`; addDocuments([new File([body], `${name.replace(/[\\/:*?"<>|]/g, '_').slice(0, 100)}.txt`, { type: 'text/plain' })]); setSheet(null); go('chat'); notify(`已导入「${name}」到当前会话输入框`); }} /><LinearIntegrationPanel apiBaseUrl={store.apiBaseUrl} /><Suspense fallback={<div className="text-[12px] text-fg-3">正在加载后台任务设置…</div>}><BackgroundTasksPanel apiBaseUrl={store.apiBaseUrl} /></Suspense></div></section>}
      </div>
    </Dialog>
    </Suspense>

    <PersonalTodos apiBaseUrl={store.apiBaseUrl} connected={store.connected} />
    <Suspense fallback={null}><DesktopTeachOverlay apiBaseUrl={store.apiBaseUrl} /></Suspense>
    {paletteOpen && <Suspense fallback={null}><Palette items={paletteItems} open onClose={() => setPaletteOpen(false)} search={searchMessages} /></Suspense>}
    {resumePickerOpen && <Suspense fallback={null}><ResumePickerDialog apiBaseUrl={store.apiBaseUrl} conversations={store.conversations} onClose={() => setResumePickerOpen(false)} onSelect={openConversation} /></Suspense>}
    {transcriptOpen && <TranscriptDialog conversationId={store.activeConversationId} messages={threadMessages} events={activeEvents} onClose={() => setTranscriptOpen(false)} />}
    {keymapOpen && <KeymapDialog onClose={() => setKeymapOpen(false)} />}
    {fallbackOpen && <Suspense fallback={null}><FallbackModelsDialog apiBaseUrl={store.apiBaseUrl} currentModel={store.model} onClose={() => setFallbackOpen(false)} onToast={notify} /></Suspense>}

    {voiceOpen && <Suspense fallback={null}><VoiceOverlay
      apiBaseUrl={store.apiBaseUrl}
      onClose={(toChat) => { setVoiceOpen(false); if (toChat) go('chat'); }}
      onSend={(text) => { if (view !== 'chat') go('chat'); void store.sendMessage(text); }}
      runId={store.activeRunId ?? null}
      reply={reply}
      runDone={runDone}
      modelName={modelName}
      speechVoice={speechVoice}
      speechVoices={speechVoices}
      onSpeechVoiceChange={(value) => { setSpeechVoice(value); setPref('speech-voice', value); }}
    /></Suspense>}

    {remoteOpen && <Suspense fallback={null}><RemoteFolderDialog open onClose={() => setRemoteOpen(false)} current={workspacePath}
      onChoose={(workspace) => { void (async () => {
        const conversationId = useAtlasStore.getState().activeConversationId;
        if (conversationId) store.setWorkspace(conversationId, workspace);
        else store.setDraftWorkspace(workspace);
        setToast(`工作目录：${workspace}`);
      })(); }} /></Suspense>}
    {store.initOpen && <Suspense fallback={null}><InitDialog onToast={notify} /></Suspense>}
    {onboardingOpen && <Suspense fallback={null}><OnboardingDialog open onClose={closeOnboarding} username={username}
      onUsername={(value) => { setPref('username', value); setUsername(value); }}
      defaultWorkspace={defaultWorkspace} onDefaultWorkspace={(path) => { setPref('default-workspace', path); setDefaultWorkspace(path); }}
      onTry={(text) => {
        closeOnboarding(); go('chat');
        if (store.activeConversationId) skipDraftRestoreRef.current = true;
        store.beginConversationDraft(defaultWorkspace || null);
        writeDraft('', text); setInput(text);
      }} /></Suspense>}
    <Suspense fallback={null}>{featureLessonsOpen && <FeatureLessons open onClose={() => setFeatureLessonsOpen(false)} />}</Suspense>
    {recipesOpen && <Suspense fallback={null}><RecipesDialog open onClose={() => setRecipesOpen(false)} recipes={store.recipes}
      onRun={(id, params) => { go('chat'); void store.runRecipe(id, params); }} onDelete={(id) => void store.deleteRecipe(id)} /></Suspense>}
    {workflowManagerOpen && <Suspense fallback={null}><WorkflowManagerDialog apiBaseUrl={store.apiBaseUrl} open onClose={() => setWorkflowManagerOpen(false)}
      onRun={(goal) => { void startDynamicWorkflow(goal).catch((error) => setToast(`工作流启动失败：${error instanceof Error ? error.message : String(error)}`)); }} onToast={notify} /></Suspense>}
    {ideManagerOpen && <Suspense fallback={null}><IDEManagerDialog open onClose={() => setIdeManagerOpen(false)} apiBaseUrl={store.apiBaseUrl} onToast={notify}
      workspacePath={typeof activeConversation?.workspace === 'string' ? activeConversation.workspace : ''}
      onOpenWorkspace={() => {
        const workspace = typeof activeConversation?.workspace === 'string' ? activeConversation.workspace : '';
        if (!workspace) return;
        if (workspace.startsWith('ssh://')) { notify('远程目录不能从本机外部编辑器打开'); return; }
        void window.atlasDesktop?.openPath?.(workspace).then((result) => notify(result === 'opened' || result === 'revealed' ? '已请求系统打开工作目录' : `无法打开工作目录：${result}`))
          .catch((error) => notify(`无法打开工作目录：${error instanceof Error ? error.message : String(error)}`));
      }} /></Suspense>}
    <Dialog open={rawText !== null} onOpenChange={(open) => { if (!open) setRawText(null); }} label={rawTextTitle} className="flex max-h-[82vh] w-[min(900px,92vw)] flex-col bg-panel p-4 shadow-xl">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="m-0 text-[15px] font-semibold text-heading">{rawTextTitle}</h2>
        <span className="flex-1" />
        <button type="button" aria-label="复制原始回复" onClick={() => {
          if (!rawText) return;
          void navigator.clipboard.writeText(rawText).then(() => setToast('已复制原始回复')).catch(() => setToast('复制失败'));
        }} className="rounded-lg px-3 py-1.5 text-[12.5px] text-fg-2 hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">复制</button>
        <button type="button" aria-label="关闭原始文本" onClick={() => setRawText(null)} className="grid size-8 place-items-center rounded-lg hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"><X size={16} /></button>
      </div>
      <pre className="m-0 min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-sunken p-3 font-mono text-[12px] leading-relaxed text-fg" tabIndex={0}>{rawText}</pre>
    </Dialog>
    <Dialog open={Boolean(handoffDraft) || handoffBusy} onOpenChange={(open) => { if (!open && !handoffBusy) { setHandoffDraft(''); setHandoffSource(''); } }} label="预览任务交接摘要" className="flex max-h-[88vh] w-[min(900px,92vw)] flex-col bg-panel p-5 shadow-xl">
      <div className="flex items-center gap-2"><h2 className="m-0 text-[16px] font-semibold text-heading">交接摘要</h2><span className="flex-1" /><button type="button" onClick={() => { setHandoffDraft(''); setHandoffSource(''); }} className="rounded-lg px-3 py-1.5 text-[12px] text-fg-2 hover:bg-hover">取消</button></div>
      <p className="my-2 text-[12px] text-fg-3">摘要由完整会话记录生成，可编辑。新会话会保存原会话引用，摘要会放入新会话输入框供你继续编辑后发送。</p>
      {handoffBusy ? <p role="status" className="m-0 py-8 text-center text-[13px] text-fg-3">正在整理目标、决策、约束、文件状态和待办…</p> : <textarea aria-label="交接摘要预览与编辑" autoFocus value={handoffDraft} onChange={(event) => setHandoffDraft(event.target.value)} className="min-h-0 flex-1 resize-y rounded-xl border border-line bg-sunken p-3 font-mono text-[12px] leading-relaxed text-fg outline-none focus:border-brand" />}
      {!handoffBusy && <div className="mt-3 flex justify-end gap-2"><Button variant="secondary" onClick={() => { setHandoffDraft(''); setHandoffSource(''); }}>取消</Button><Button variant="primary" disabled={!handoffDraft.trim()} onClick={() => void createHandoffConversation()}>创建关联的新会话</Button></div>}
    </Dialog>
    <Dialog open={Boolean(memoryMarkerDrafts?.length)} onOpenChange={(open) => { if (!open && !memoryMarkerSaving) dismissMemoryMarkerReview(); }} label="审阅待保存记忆" className="flex max-h-[86vh] w-[min(720px,92vw)] flex-col bg-panel p-5 shadow-xl">
      <div className="flex items-center gap-2"><h2 className="m-0 text-[16px] font-semibold text-heading">审阅待保存记忆</h2><span className="flex-1"/><button type="button" disabled={memoryMarkerSaving} onClick={dismissMemoryMarkerReview} className="rounded-lg px-3 py-1.5 text-[12px] text-fg-2 hover:bg-hover">关闭</button></div>
      <p className="mt-2 mb-3 text-[12px] text-fg-3">原消息已完整发送，标记内容不会从消息正文移除。检查或编辑后再确认写入记忆库；“仅发送”会放弃保存。</p>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">{memoryMarkerDrafts?.map((item, index) => <section key={index} className="rounded-xl border border-line p-3">
        <label className="mb-1 block text-[11px] text-fg-3" htmlFor={`memory-marker-${index}`}>记忆内容 {index + 1}</label>
        <textarea id={`memory-marker-${index}`} value={item.text} onChange={(event) => setMemoryMarkerDrafts((current) => current?.map((row, rowIndex) => rowIndex === index ? { ...row, text: event.target.value } : row) ?? null)} className="min-h-20 w-full resize-y rounded-lg border border-line bg-sunken p-2 text-[13px] text-fg" />
        <label className="mt-2 flex items-center gap-2 text-[11px] text-fg-3">保存到<select aria-label={`记忆内容 ${index + 1} 保存页面`} value={item.path} onChange={(event) => setMemoryMarkerDrafts((current) => current?.map((row, rowIndex) => rowIndex === index ? { ...row, path: event.target.value } : row) ?? null)} className="rounded-md border border-line bg-panel px-2 py-1 text-fg"><option value="我.md">关于我</option><option value="现状.md">当前情况</option><option value="它自己.md">Atlas 的记录</option></select></label>
      </section>)}</div>
      <p className="mt-3 mb-0 text-[11px] text-fg-3">语法：单行 `# 记忆内容` 或 `#记住：记忆内容`；后续非空行属于同一条，空行开始新段。代码围栏中的 # 不触发；行首写 `\#` 表示普通文本。</p>
      <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" disabled={memoryMarkerSaving} onClick={dismissMemoryMarkerReview}>仅发送，不保存</Button><Button variant="primary" disabled={memoryMarkerSaving || !memoryMarkerDrafts?.length || memoryMarkerDrafts.some((item) => !item.text.trim())} onClick={() => void saveMemoryMarkerDrafts()}>{memoryMarkerSaving ? '正在保存…' : '确认保存记忆'}</Button></div>
    </Dialog>
    {activeConversation && <Suspense fallback={null}><SideChat open={side.open} onClose={() => setSide({ open: false })} conversationId={activeConversation.id} model={store.model} initialQuestion={side.question} /></Suspense>}
    <Dialog open={schedulePromptOpen} onOpenChange={setSchedulePromptOpen} label="安排插话" className="w-[min(480px,92vw)] bg-panel p-5 shadow-xl">
      <h2 className="m-0 text-[16px] font-semibold text-heading">这条消息怎么交给正在运行的任务？</h2>
      <p className="mt-2 mb-4 text-[13px] text-fg-3">Atlas 会按文本初步识别意图；请确认执行时机。{/(刚才|上一步|改成|修改|更正|补充|不要|改为)/.test(input) ? '这句话看起来像对当前任务的修正。' : '这句话看起来可能是一个后续任务。'}</p>
      <div className="grid gap-2">
        <Button variant="secondary" onClick={() => { scheduleBypass.current = true; setSchedulePromptOpen(false); void submit(false); }}>当前步骤完成后排队</Button>
        <Button variant="primary" onClick={() => { scheduleBypass.current = true; setSchedulePromptOpen(false); void submit(false, true); }}>停止当前运行，优先处理这条</Button>
        <Button variant="ghost" onClick={() => setSchedulePromptOpen(false)}>继续编辑</Button>
      </div>
    </Dialog>
    {ultraplan && <Suspense fallback={null}><UltraplanPanel open goal={ultraplan.goal}
      apiBaseUrl={store.apiBaseUrl} workspace={ultraplan.workspace}
      conversationId={ultraplan.conversationId} model={store.model} onClose={() => setUltraplan(null)} onToast={notify}
      onOpenArtifact={(path, title) => { setUltraplanArtifact({ id: `ultraplan-${path}`, runId: '', type: 'file', name: `高级计划：${ultraplan.title}`, path, summary: title, createdAt: new Date().toISOString() }); setInspectorOpen(true); setInspectorTab('artifacts'); }} /></Suspense>}

    {view !== 'chat' && view !== 'home' && <Suspense fallback={null}><ExpertModeBadge apiBaseUrl={store.apiBaseUrl} onOpen={() => setSheet('expert')} /></Suspense>}
    <Suspense fallback={null}><SettingsProposalCards apiBaseUrl={store.apiBaseUrl} onModel={(model) => void store.selectModel(model)} onToast={notify} currentModel={store.model} modelName={(id) => store.models.find((model) => model.id === id)?.name ?? id} /></Suspense>
    <DiagnosticsFloatingOverlay apiBaseUrl={store.apiBaseUrl} />
    {screenRecorderOpen && <Suspense fallback={null}><ScreenRecorderDialog open onClose={() => setScreenRecorderOpen(false)} onToast={notify} onAttach={(file) => setFiles((current) => [...current, file])} /></Suspense>}
    {toast && <div role="status" className="pop anim-pop fixed bottom-7 left-1/2 z-[80] -translate-x-1/2 rounded-xl px-4 py-2.5 text-[13.5px] text-fg">{toast}</div>}
  </TooltipProvider>;
}

function TranscriptDialog({ conversationId, messages, events, onClose }: {
  conversationId: string;
  messages: HistoryMessage[]; events: Array<{ type: string; timestamp?: string; data: Record<string, unknown> }>;
  onClose: () => void;
}) {
  const [query, setQuery] = useState('');
  const [allMessages, setAllMessages] = useState(messages);
  const [loading, setLoading] = useState(false);
  useEffect(() => { const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); onClose(); } }; window.addEventListener('keydown', closeOnEscape); return () => window.removeEventListener('keydown', closeOnEscape); }, [onClose]);
  useEffect(() => {
    if (!conversationId) return;
    let stale = false;
    void (async () => {
      setLoading(true);
      const pages: HistoryMessage[][] = [];
      let beforeId: string | undefined;
      while (true) {
        const page = await backend.getMessages(conversationId, { limit: 1000, ...(beforeId ? { beforeId } : {}) });
        if (stale) return;
        if (!page.length) break;
        pages.unshift(page);
        if (page.length < 1000) break;
        const nextBeforeId = String(page[0]?.id ?? '');
        if (!nextBeforeId || nextBeforeId === beforeId) break;
        beforeId = nextBeforeId;
      }
      setAllMessages(pages.flat());
      setLoading(false);
    })().catch(() => { if (!stale) { setAllMessages(messages); setLoading(false); } });
    return () => { stale = true; };
  }, [conversationId]);
  const text = useMemo(() => [
    ...allMessages.map((item) => `[${item.role}] ${item.content}`),
    ...events.map((event) => `[${event.timestamp ?? ''}] ${event.type}\n${JSON.stringify(event.data, null, 2)}`),
  ].join('\n\n'), [allMessages, events]);
  const filtered = useMemo(() => query.trim() ? text.split(/\n\n/).filter((line) => line.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).join('\n\n') : text, [query, text]);
  return <div role="dialog" aria-modal="true" aria-label="完整对话记录" className="fixed inset-0 z-[100] flex flex-col bg-panel p-4 text-fg">
    <div className="flex items-center gap-2 border-b border-line pb-3"><h2 className="m-0 text-[15px] font-semibold">完整对话记录</h2><span className="text-[12px] text-fg-3">{loading ? '正在读取完整历史…' : `${allMessages.length} 条消息 · ${events.length} 个运行事件`}</span><span className="flex-1" /><button type="button" onClick={() => void navigator.clipboard.writeText(filtered)} className="rounded-lg px-3 py-1.5 text-[12px] hover:bg-hover">复制文本</button><button type="button" aria-label="关闭完整对话记录" onClick={onClose} className="rounded-lg px-3 py-1.5 text-[12px] hover:bg-hover">关闭</button></div>
    <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索全部对话记录…" aria-label="搜索完整对话记录" className="my-3 h-9 rounded-lg border border-line bg-sunken px-3 text-[13px] outline-none focus:border-brand" />
    <pre className="m-0 min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-code p-4 font-mono text-[12px] leading-5 text-fg-2">{filtered || '没有匹配的记录'}</pre>
    <span className="pt-2 text-[11px] text-fg-3">Ctrl+T 关闭 · Esc 关闭</span>
  </div>;
}

function MessageAction({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return <Tip label={label}><button aria-label={label} onClick={onClick} className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg">{children}</button></Tip>;
}
