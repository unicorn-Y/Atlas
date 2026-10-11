import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import {
  AudioLines, Bell, BookMarked, Brain, Copy, Cpu, Keyboard, Monitor, Radio, Smartphone, Wrench, Sparkles, Laptop, Webhook, Server, ShieldCheck, ShieldAlert as ShieldAsk, Lock, Download, FolderOpen, GitBranch, GitBranchPlus, MessagesSquare, UserCog, Image as ImageIcon, ListChecks, MessageCircle, MessageSquarePlus, MessageSquareX, Undo2, Minus, Moon, PanelRight, Pause, Pencil, Play, Plus, Puzzle, RotateCcw, Send, Settings,
  SlidersHorizontal, Square, Sun, Zap, FileCog, Volume2, VolumeX, X, Gauge, Search,
} from 'lucide-react';
import { backend, useAtlasStore } from './store/useAtlasStore';
import type { ConversationMessage as HistoryMessage, RunFile } from '@atlas/backend-adapter';
import MessageThread from './components/MessageThread';
import TodoPanel from './components/TodoPanel';
import ProgressCapsule from './components/ProgressCapsule';
import { latestTodos } from './components/runInsights';
import Composer, { type ComposerMode, type MentionItem, type SlashCommand } from './components/Composer';
import RecipesDialog from './components/RecipesDialog';
import SideChat from './components/SideChat';
import RemoteFolderDialog from './components/RemoteFolderDialog';
import InitDialog from './components/InitDialog';
import LspStatusSection from './components/LspStatusSection';
import TimelineNav from './components/TimelineNav';
import ForkTree from './components/ForkTree';
import RunSetupMenu from './components/RunSetupMenu';
import TabStrip from './components/TabStrip';
import OnboardingDialog from './components/OnboardingDialog';
import SidePane from './components/SidePane';
import ShortcutsPanel from './pages/ShortcutsPanel';
import ScriptToolsPanel from './pages/ScriptToolsPanel';
import TelegramPanel from './pages/TelegramPanel';
import UsagePanel from './pages/UsagePanel';
import { loadBindings, matchShortcut } from './services/shortcuts';
import type { CustomCommandInfo, PermissionMode } from '@atlas/backend-adapter';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from './ui/Menu';
import Mark, { MarkDefs } from './components/Mark';
import Palette, { type PaletteItem } from './components/Palette';
import VoiceOverlay, { getSpeechRecognition, type SpeechRecognitionLike } from './components/VoiceOverlay';
import SettingsPage, { STATUS_BAR_ITEMS, type StatusBarPreferences } from './pages/SettingsPage';
import SkillsMarketPage from './pages/SkillsMarketPage';
import LibraryPage from './pages/LibraryPage';
import EvolutionPage from './pages/EvolutionPage';
import MemoryPage from './pages/MemoryPage';
import AutomationPage from './pages/AutomationPage';
import CodePage from './pages/CodePage';
import CreatePage from './pages/CreatePage';
import BoardPage from './pages/BoardPage';
import ProfilesPanel from './pages/ProfilesPanel';
import HooksPanel from './pages/HooksPanel';
import AgentsPage from './pages/agents/AgentsPage';
import DevicesPage from './pages/DevicesPage';
import WorkbenchPage from './pages/WorkbenchPage';
import GroupsView from './pages/GroupsView';
import ChannelsSettings from './pages/settings/ChannelsSettings';
import LocalModelsSettings from './pages/settings/LocalModelsSettings';
import ImportPanel from './components/ImportPanel';
import { NotificationsPanel, PluginsPanel } from './pages/ConsolePage';
import McpServersPanel from './components/settings/McpServersPanel';
import ConfigTransferPanel from './components/settings/ConfigTransferPanel';
import DiagnosticsPanel from './components/settings/DiagnosticsPanel';
import TelemetryPrivacyPanel from './pages/TelemetryPrivacyPanel';
import RecipeManagerPanel, { type RecipeLaunchRequest } from './components/settings/RecipeManagerPanel';
import ExtensionPackagesPanel from './components/settings/ExtensionPackagesPanel';
import ExtensionCatalogPanel from './components/settings/ExtensionCatalogPanel';
import AppearanceNotificationsPanel from './components/settings/AppearanceNotificationsPanel';
import WorkspaceSecurityPanel from './components/settings/WorkspaceSecurityPanel';
import CustomCommandsPanel from './components/settings/CustomCommandsPanel';
import RunLimitsPanel from './components/settings/RunLimitsPanel';
import PlatformSettingsPanel from './components/settings/PlatformSettingsPanel';
import SettingsIntegrationsPanel from './components/settings/SettingsIntegrationsPanel';
import NetworkSettingsPanel from './components/settings/NetworkSettingsPanel';
import MainConfigPanel from './components/settings/MainConfigPanel';
import ExpertModePanel, { ExpertModeBadge, OPEN_EXPERT_SETTINGS } from './components/settings/ExpertModePanel';
import OutputStyleSettingsPanel from './components/settings/OutputStyleSettingsPanel';
import McpResourcesPanel from './components/settings/McpResourcesPanel';
import LocalModelsPanel from './components/settings/LocalModelsPanel';
import LinearIntegrationPanel from './components/settings/LinearIntegrationPanel';
import Sidebar, { MORE_NAV, NAV, type View } from './shell/Sidebar';
import HomeView, { type Suggestion } from './shell/HomeView';
import Inspector, { type InspectorTab } from './shell/Inspector';
import type { PickedElement } from './shell/panels/BrowserPanel';
import { THEMES, applyStoredTheme, clearCustomTheme, initialTheme, nextTheme, themeInfo, type Theme } from './shell/themes';
import { api, relativeTime } from './services/api';
import { buildTimeline } from './components/timeline';
import { ComputerEdgeBar } from './components/x2';
import UpdateBanner from './components/UpdateBanner';
import { Button } from './ui/Button';
import { Dialog } from './ui/Dialog';
import { Tip, TooltipProvider } from './ui/Tooltip';
import { cn } from './ui/cn';

type SheetPane = 'models' | 'advanced' | 'usage' | 'limits' | 'profiles' | 'hooks' | 'tools' | 'telegram' | 'channels' | 'devices' | 'localModels' | 'shortcuts' | 'appearance' | 'plugins' | 'notifications' | 'mcp' | 'skills' | 'recipes' | 'extensions' | 'transfer' | 'diagnostics' | 'telemetry' | 'security' | 'commands' | 'platform' | 'integrations' | 'network' | 'expert' | 'mainConfig';

const SETTINGS_NAV: Array<[SheetPane, string, typeof Bell, string]> = [
  ['models', '模型与服务', SlidersHorizontal, 'provider 模型 model API key 密钥 reasoning 推理 连接'],
  ['mainConfig', '主体配置', FileCog, 'atlas.toml config 配置 文件 user-settings 界面设置 当前生效 备份 恢复 编辑'],
  ['expert', '专家模式', Zap, 'expert 专家 模式 切换 覆盖 overlay 额外配置 附加说明'],
  ['network', '模型网络', Server, 'proxy 代理 CA certificate certificate authority 网络 HTTPS TLS'],
  ['security', '工作区安全', ShieldCheck, 'workspace trust 信任 sandbox 沙箱 network permission 权限 rules AGENTS CLAUDE'],
  ['channels', 'Gateway 与渠道账号', Radio, 'gateway channel 渠道 账号'],
  ['localModels', '本地模型', Cpu, 'local 本地模型'],
  ['advanced', '高级', Settings, 'compression 压缩 高级'],
  ['usage', '用量', Gauge, 'usage token cost 费用 预算 个人资料 profile'],
  ['limits', '运行限制', Gauge, 'run limits max turns 轮数 token budget cost limit 费用上限'],
  ['profiles', '角色', UserCog, 'profile 角色 agent'],
  ['hooks', 'Hooks', Webhook, 'hook 事件'],
  ['commands', '自定义命令', BookMarked, 'slash command 命令 prompt 参数'],
  ['tools', '脚本工具', Wrench, 'script tool 工具'],
  ['telegram', '手机远程', Smartphone, 'telegram remote 手机 远程'],
  ['devices', '设备', Monitor, 'device remote pairing 设备 配对'],
  ['shortcuts', '快捷键', Keyboard, 'shortcut keybinding 快捷键 按键'],
  ['appearance', '外观与语音', Sun, 'appearance theme font voice 外观 主题 字体 语音'],
  ['plugins', '插件与导入', Puzzle, 'plugin import 插件 导入 Claude Codex'],
  ['skills', 'Skills', BookMarked, 'skill 技能 安全发现'],
  ['mcp', 'MCP 服务', Server, 'mcp server tool 服务'],
  ['notifications', '通知', Bell, 'notification sound 通知 声音'],
  ['recipes', '配方', BookMarked, 'recipe template 参数化 配方'],
  ['extensions', '扩展目录与来源', Puzzle, 'extension package registry catalog 扩展 包 目录 来源'],
  ['transfer', '配置导入导出', Download, 'settings config export import backup 配置 导入 导出 备份'],
  ['diagnostics', '诊断', ShieldCheck, 'diagnostics health config errors 诊断 健康 配置 错误'],
  ['telemetry', '遥测隐私', ShieldCheck, 'telemetry privacy memos ARMS 遥测 隐私'],
  ['platform', '平台集成', Laptop, 'desktop platform global shortcut hotkey always on top VS Code JetBrains deep link'],
  ['integrations', '任务与集成', GitBranchPlus, 'github pull request Slack Linear cloud tasks automation'],
];

const TERMINAL = ['completed', 'failed', 'cancelled'];
const RUN_LABEL: Record<string, string> = { running: '正在处理', planning: '正在规划', queued: '排队中', paused: '已暂停', waiting: '等你确认', waiting_approval: '等你确认', completed: '已完成', failed: '出错了', cancelled: '已停止' };
const HIDDEN_CANDIDATES = 'atlas.memory.hidden-candidates';
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
/** Shift+Tab 和 /permissions 共用的切换顺序；read_only 不在循环里，只能从菜单选。 */
const PERMISSION_CYCLE: PermissionMode[] = ['ask_each', 'ask_writes', 'auto_file', 'plan', 'full_access'];
const draftKey = (conversationId: string) => `atlas.draft.${conversationId || 'home'}`;
const readDraft = (conversationId: string) => { try { return localStorage.getItem(draftKey(conversationId)) ?? ''; } catch { return ''; } };
const writeDraft = (conversationId: string, text: string) => {
  try { if (text) localStorage.setItem(draftKey(conversationId), text); else localStorage.removeItem(draftKey(conversationId)); } catch { /* storage unavailable */ }
};
const pref = (key: string) => { try { return localStorage.getItem(`atlas.preference.${key}`); } catch { return null; } };
const setPref = (key: string, value: string) => { try { localStorage.setItem(`atlas.preference.${key}`, value); } catch { /* storage unavailable */ } };
const readStatusBarPreferences = (): StatusBarPreferences => {
  let saved: Partial<StatusBarPreferences> = {};
  try { saved = JSON.parse(pref('statusbar') ?? '{}') as Partial<StatusBarPreferences>; } catch { /* use defaults */ }
  return Object.fromEntries(STATUS_BAR_ITEMS.map(([key]) => [key, typeof saved[key] === 'boolean' ? saved[key] : true])) as StatusBarPreferences;
};

export default function App() {
  // 窄选择器：只订阅这个界面真正要读的数据字段；动作函数恒定，从 getState 合入。
  // conversationMessages 仍在列（朗读/撤回/复制要用），但重列表的渲染已交给 MessageThread 自己的窄订阅。
  const storeData = useAtlasStore(useShallow((state) => ({
    apiBaseUrl: state.apiBaseUrl, providerBaseUrl: state.providerBaseUrl, apiKeyConfigured: state.apiKeyConfigured,
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
  const [view, setView] = useState<View>('home');
  const [inspectorOpen, setInspectorOpen] = useState(() => pref('canvas') === 'true');
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('artifacts');
  const [theme, setTheme] = useState<Theme>(() => initialTheme());
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
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [input, setInput] = useState('');
  const [homeMode, setHomeMode] = useState('chat');
  const [createPrompt, setCreatePrompt] = useState('');
  const [toast, setToast] = useState('');
  const [attachments, setAttachments] = useState<string[]>([]);
  const [files, setFiles] = useState<Array<RunFile & { size: number }>>([]);
  const [editing, setEditing] = useState<{ id: string; original: string } | null>(null);
  const editingDraftRef = useRef<{ text: string; attachments: string[]; files: Array<RunFile & { size: number }>; mentions: MentionItem[] } | null>(null);
  const [rawText, setRawText] = useState<string | null>(null);
  const [browserUrl, setBrowserUrl] = useState('');
  const [terminalCommand, setTerminalCommand] = useState<{ id: string; text: string } | null>(null);
  const [mentions, setMentions] = useState<MentionItem[]>([]);
  const composerSnapshotRef = useRef({ text: input, attachments, files, mentions });
  composerSnapshotRef.current = { text: input, attachments, files, mentions };
  const [recipesOpen, setRecipesOpen] = useState(false);
  const [side, setSide] = useState<{ open: boolean; question?: string }>({ open: false });
  const [branches, setBranches] = useState<string[]>([]);
  const [gitBranch, setGitBranch] = useState('');
  const [processCount, setProcessCount] = useState<number | null>(null);
  const [remoteOpen, setRemoteOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [besideId, setBesideId] = useState('');
  const [rewound, setRewound] = useState<{ conversationId: string; rewindId: string; text: string } | null>(null);
  const [defaultWorkspace, setDefaultWorkspace] = useState(() => pref('default-workspace') ?? '');
  const [tabs, setTabs] = useState<string[]>(() => { try { const saved = JSON.parse(pref('tabs') ?? '[]'); return Array.isArray(saved) ? saved.filter((id): id is string => typeof id === 'string') : []; } catch { return []; } });
  const [bindings, setBindings] = useState(loadBindings);
  useEffect(() => {
    const update = () => setBindings(loadBindings());
    window.addEventListener('atlas:shortcuts', update);
    return () => window.removeEventListener('atlas:shortcuts', update);
  }, []);
  const [listening, setListening] = useState(false);
  const [voiceOutput, setVoiceOutput] = useState(() => pref('voice-output') === 'true');
  const [username, setUsername] = useState(() => pref('username')?.trim() || 'User');
  const [statusBar, setStatusBar] = useState(readStatusBarPreferences);
  const [maximized, setMaximized] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [conversationGoal, setConversationGoal] = useState<{ text: string; status: string; turns_used: number; max_turns: number; subgoals: unknown[] } | null>(null);
  const updateStatusBar = (key: keyof StatusBarPreferences, visible: boolean) => setStatusBar((current) => {
    const next = { ...current, [key]: visible };
    setPref('statusbar', JSON.stringify(next));
    return next;
  });
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const spokenSequenceRef = useRef(0);
  const spokenRunRef = useRef('');
  const speechBufferRef = useRef('');
  const firstRunShownRef = useRef(false);
  const threadRef = useRef<HTMLDivElement>(null);

  const activeConversation = store.conversations.find((item) => item.id === store.activeConversationId);
  const activeRun = store.runs.find((run) => run.id === store.activeRunId);
  const activeArtifacts = store.artifacts.filter((artifact) => artifact.runId === store.activeRunId);
  const activeEvents = activeRun?.events ?? [];
  const runDone = Boolean(activeRun && TERMINAL.includes(activeRun.status));
  const currentPlan = [...activeEvents].reverse().find((event) => event.type === 'run.plan.updated')?.data.plan as { subtasks?: unknown[] } | undefined;
  const planSteps = Array.isArray(currentPlan?.subtasks) ? currentPlan.subtasks.filter((step): step is { status?: string } => Boolean(step) && typeof step === 'object') : [];
  const completedPlanSteps = planSteps.filter((step) => step.status === 'completed').length;
  const messages = (store.conversationMessages[store.activeConversationId] ?? []).filter((message) => message.role === 'user' || message.role === 'assistant');
  // Once a run finishes the store reloads saved history, which then also contains the run's own turn.
  // The live activity already shows that turn (with its steps), so stop the history just before it.
  const runPrompt = activeRun && activeRun.conversationId === store.activeConversationId
    ? String(activeEvents.find((event) => event.type === 'run.started')?.data.content ?? '') : '';
  const runTurnIndex = runPrompt ? messages.map((message) => message.role === 'user' ? message.content : null).lastIndexOf(runPrompt) : -1;
  const history = runTurnIndex >= 0 && runTurnIndex >= messages.length - 3 ? messages.slice(0, runTurnIndex) : messages;
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

  const go = useCallback((next: View) => setView(next), []);

  // Unsent text survives switching conversations and restarting the app.
  const draftOwnerRef = useRef(store.activeConversationId);
  useEffect(() => {
    if (draftOwnerRef.current === store.activeConversationId) return;
    draftOwnerRef.current = store.activeConversationId;
    setInput(readDraft(store.activeConversationId));
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
  useEffect(() => window.atlasDesktop?.onBackendStartupProgress(
    (progress) => useAtlasStore.getState().applyStartupProgress(progress),
  ), []);
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
    void backend.getConversationGoal(id).then((result) => { if (!stale) setConversationGoal(result.goal); }).catch(() => { if (!stale) setConversationGoal(null); });
    return () => { stale = true; };
  }, [store.activeConversationId, store.connected]);
  useEffect(() => {
    if (activeEvents.at(-1)?.type !== 'run.completed' || !store.activeConversationId || !store.connected) return;
    void backend.getConversationGoal(store.activeConversationId)
      .then((result) => setConversationGoal(result.goal))
      .catch(() => setConversationGoal(null));
  }, [activeEvents, store.activeConversationId, store.connected]);
  // First run: the settings sheet opens once, as soon as the backend reports no API key.
  useEffect(() => {
    if (firstRunShownRef.current || !store.connected || store.conversationsLoading || store.apiKeyConfigured) return;
    firstRunShownRef.current = true;
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
          if (phrase) window.speechSynthesis.speak(new SpeechSynthesisUtterance(phrase));
        }
      } else if (event.type === 'run.completed') {
        const remainder = speechBufferRef.current.trim();
        if (remainder) window.speechSynthesis.speak(new SpeechSynthesisUtterance(remainder));
        speechBufferRef.current = '';
      } else if (['run.failed', 'run.cancelled'].includes(event.type)) {
        speechBufferRef.current = '';
        window.speechSynthesis.cancel();
      }
    }
  }, [activeEvents, activeRun, voiceOutput, voiceOpen]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(''), 2200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  // 滚动定位（进入会话回到原位、流式跟底）由 MessageThread 里的虚拟列表接管。

  // Memories waiting for confirmation show as a badge on the navigation.
  useEffect(() => {
    if (!store.connected) return;
    let hidden: string[] = [];
    try { hidden = JSON.parse(localStorage.getItem(HIDDEN_CANDIDATES) ?? '[]'); } catch { hidden = []; }
    api<Array<{ id: string }>>(store.apiBaseUrl, '/api/memory/candidates?status=pending')
      .then((items) => setPendingCount(items.filter((item) => !hidden.includes(item.id)).length)).catch(() => undefined);
  }, [view, store.connected, store.apiBaseUrl]);

  const newTask = useCallback(() => {
    if (store.creatingConversation) return;
    go('chat');
    setInput('');
    setAttachments([]);
    setFiles([]);
    setMentions([]);
    setEditing(null);
    editingDraftRef.current = null;
    void store.createConversation().then(() => {
      // New tasks start in the usual folder chosen during setup.
      const id = useAtlasStore.getState().activeConversationId;
      if (id && defaultWorkspace) store.setWorkspace(id, defaultWorkspace);
    });
  }, [go, store, defaultWorkspace]);
  // First run: once the backend answers and no model key is saved, walk through setup (only once).
  useEffect(() => {
    if (store.connected && store.configLoaded && !store.apiKeyConfigured && pref('onboarded') !== 'true') setOnboardingOpen(true);
  }, [store.connected, store.configLoaded, store.apiKeyConfigured]);
  const closeOnboarding = () => { setOnboardingOpen(false); setPref('onboarded', 'true'); };

  const startVoice = () => {
    if (!getSpeechRecognition()) { setToast('这台设备不支持语音识别，暂时无法通话'); return; }
    recognitionRef.current?.stop();
    window.speechSynthesis?.cancel();
    setVoiceOpen(true);
  };

  const submit = async (fromHome: boolean) => {
    if (!input.trim() && !attachments.length && !files.length && !mentions.length) return;
    const text = input;
    const images = attachments;
    const documents = files.map(({ name, mime, data_base64 }) => ({ name, mime, data_base64 }));
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
    recognitionRef.current?.stop();
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
      if (store.activeConversationId && messages.length) await store.createConversation(text.trim().slice(0, 40) || '新对话');
    }
    const refs = { files: mentions.filter((item) => item.kind === 'file').map((item) => item.id), conversations: mentions.filter((item) => item.kind === 'conversation').map((item) => item.id).slice(0, 3) };
    setMentions([]);
    void store.sendMessage(text, images, documents, refs);
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
  const addDocuments = (picked: File[]) => {
    if (!picked.length) return;
    const conversationId = store.activeConversationId;
    const tooBig = picked.find((file) => file.size > 10 * 1024 * 1024);
    if (tooBig) { setToast(`${tooBig.name} 超过 10 MB，发不了`); return; }
    if (files.reduce((sum, file) => sum + file.size, 0) + picked.reduce((sum, file) => sum + file.size, 0) > 20 * 1024 * 1024) { setToast('一条消息的文件加起来不能超过 20 MB'); return; }
    Promise.all(picked.map((file) => new Promise<RunFile & { size: number }>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => typeof reader.result === 'string'
        ? resolve({ name: file.name, mime: file.type || 'application/octet-stream', data_base64: reader.result.slice(reader.result.indexOf(',') + 1), size: file.size })
        : reject(new Error('无法读取文件'));
      reader.onerror = () => reject(new Error('无法读取文件'));
      reader.readAsDataURL(file);
    }))).then((read) => {
      if (useAtlasStore.getState().activeConversationId === conversationId) setFiles((current) => [...current, ...read]);
    }).catch(() => { if (useAtlasStore.getState().activeConversationId === conversationId) setToast('读取文件失败'); });
  };
  const addImages = (picked: File[]) => {
    const conversationId = store.activeConversationId;
    const selected = picked.slice(0, 4 - attachments.length);
    if (!selected.length) { setToast('每条消息最多 4 张图片'); return; }
    if (selected.some((file) => file.size > 4 * 1024 * 1024)) { setToast('单张图片不能超过 4 MiB'); return; }
    const queuedBytes = attachments.reduce((sum, image) => sum + Math.max(0, Math.floor((image.length - image.indexOf(',') - 1) * 3 / 4)), 0);
    if (queuedBytes + selected.reduce((sum, file) => sum + file.size, 0) > 8 * 1024 * 1024) { setToast('单条消息的图片总大小不能超过 8 MiB'); return; }
    Promise.all(selected.map((file) => new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('无法读取图片'));
      reader.onerror = () => reject(new Error('无法读取图片'));
      reader.readAsDataURL(file);
    }))).then((images) => {
      if (useAtlasStore.getState().activeConversationId === conversationId) setAttachments((current) => [...current, ...images].slice(0, 4));
    }).catch(() => { if (useAtlasStore.getState().activeConversationId === conversationId) setToast('读取图片失败'); });
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
    const current = typeof activeConversation?.workspace === 'string' ? activeConversation.workspace : undefined;
    const picked = window.atlasDesktop?.selectDirectory
      ? await window.atlasDesktop.selectDirectory(current)
      : window.prompt('工作目录的完整路径', current ?? '')?.trim() || null;
    if (!picked) return;
    if (!store.activeConversationId) await store.createConversation();
    const conversationId = useAtlasStore.getState().activeConversationId;
    if (conversationId) { store.setWorkspace(conversationId, picked); setToast(`工作目录：${picked}`); }
  };
  const toggleSpeechInput = () => {
    if (recognitionRef.current) { recognitionRef.current.stop(); recognitionRef.current = null; setListening(false); return; }
    const Constructor = getSpeechRecognition();
    if (!Constructor) { setToast('这台设备不支持语音识别'); return; }
    const recognition = new Constructor();
    recognition.lang = 'zh-CN';
    recognition.interimResults = true;
    const prefix = input.trim();
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results).map((result) => result[0].transcript).join('');
      if (transcript) setInput(`${prefix}${prefix ? ' ' : ''}${transcript}`);
    };
    recognition.onerror = () => setToast('语音识别不可用，请检查麦克风权限和网络');
    recognition.onend = () => { recognitionRef.current = null; setListening(false); };
    recognitionRef.current = recognition;
    setListening(true);
    recognition.start();
  };
  const readLastReply = () => {
    const lastReply = [...messages].reverse().find((message) => message.role === 'assistant')?.content || (runDone ? reply : '');
    if (!lastReply || !('speechSynthesis' in window)) { setToast('还没有可以朗读的回复'); return; }
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(lastReply));
  };
  const toggleVoiceOutput = () => {
    const enabled = !voiceOutput;
    setVoiceOutput(enabled);
    setPref('voice-output', String(enabled));
    if (!enabled) { speechBufferRef.current = ''; window.speechSynthesis?.cancel(); }
    setToast(enabled ? '新回复会自动朗读' : '已关闭自动朗读');
  };
  const chooseTheme = (next: Theme) => { clearCustomTheme(); setTheme(next); setPref('appearance', next); };
  const toggleTheme = () => { const next = nextTheme(theme); chooseTheme(next); setToast(`已切换到${themeInfo(next).label}`); };
  const toggleMini = () => setSideMini((current) => { setPref('sidebar-mini', String(!current)); return !current; });
  const toggleInspector = (open?: boolean) => setInspectorOpen((current) => { const next = open ?? !current; setPref('canvas', String(next)); return next; });
  const showInspectorTab = (tab: InspectorTab) => { setInspectorTab(tab); toggleInspector(true); };
  // C6R: /review「打开文件」请求 → 切到文件面板;FilesPanel 自己消费请求并定位行。
  useEffect(() => { if (storeData.fileOpenRequest) showInspectorTab('files'); }, [storeData.fileOpenRequest]);
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
  const draft = (text: string) => { go('chat'); setInput(text); void store.createConversation(); };
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
  const closeTab = (id: string) => {
    const index = tabs.indexOf(id);
    const next = tabs.filter((item) => item !== id);
    setTabs(next);
    if (id !== store.activeConversationId || view !== 'chat') return;
    const neighbour = next[Math.min(index, next.length - 1)];
    const conversation = neighbour ? store.conversations.find((item) => item.id === neighbour) : undefined;
    if (conversation) openConversation(conversation); else go('home');
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
      if (event.altKey && event.shiftKey && event.key.toLowerCase() === 'a') {
        event.preventDefault();
        askSelectedText();
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
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
  useEffect(() => () => { recognitionRef.current?.stop(); window.speechSynthesis?.cancel(); }, []);

  const paletteItems: PaletteItem[] = [
    { id: 'new', group: '操作', label: '新任务', hint: 'Ctrl N', icon: <Plus />, run: newTask },
    { id: 'voice', group: '操作', label: '开始语音通话', icon: <AudioLines />, run: startVoice },
    ...THEMES.filter((item) => item.id !== theme).map((item) => ({ id: `theme-${item.id}`, group: '外观', label: `切换到${item.label}`, hint: item.hint, icon: item.id === 'dark' ? <Moon /> : <Sun />, run: () => chooseTheme(item.id) })),
    { id: 'settings', group: '操作', label: '设置', hint: 'Ctrl ,', icon: <Settings />, run: () => setSheet('models') },
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
  const slashCommands: SlashCommand[] = [
    { id: 'new', label: '/new', hint: '新任务', run: newTask },
    { id: 'clear', label: '/clear', hint: '开始一段新对话', run: newTask },
    ...(activeConversation ? [
      { id: 'export', label: '/export', hint: '导出当前对话为 JSON', run: () => void store.exportConversation(activeConversation.id) },
      { id: 'rename', label: '/rename', hint: '把后面的文字设为对话名称', takesArgument: true, run: (title: string) => { if (title.trim()) void store.renameConversation(activeConversation.id, title); else setToast('在 /rename 后面写上新名称'); } },
      { id: 'resume', label: '/resume', hint: '继续打开最近对话，或按名称搜索', takesArgument: true, run: (query: string) => { const target = query.trim() ? store.conversations.find((item) => item.id === query.trim() || item.title.toLowerCase().includes(query.trim().toLowerCase())) : store.conversations[0]; if (target) openConversation(target); else setToast('没有找到可恢复的对话'); } },
      { id: 'fork', label: '/fork', hint: '从最近一条用户消息分叉', run: () => { const last = [...messages].reverse().find((item) => item.role === 'user'); if (last) void store.forkFrom(last.id); else setToast('当前对话还没有用户消息'); } },
      { id: 'undo', label: '/undo', hint: '撤回最近一条用户消息及其之后内容', run: () => { const last = [...messages].reverse().find((item) => item.role === 'user'); if (last) void rewind(last.id, false); else setToast('当前对话没有可撤回的用户消息'); } },
      { id: 'redo', label: '/redo', hint: '恢复刚刚撤回的内容', run: () => { if (rewound) void store.redoRewind(rewound.conversationId, rewound.rewindId).then((ok) => { if (ok) { setRewound(null); setToast('已重做'); } }); else setToast('当前没有可重做的撤回'); } },
      { id: 'approve', label: '/approve', hint: '打开当前对话的审批与活动', run: () => showInspectorTab('activity') },
      { id: 'side', label: '/side', hint: '在侧聊中追问，不打断主对话', takesArgument: true, run: (question: string) => setSide({ open: true, question: question.trim() || undefined }) },
      { id: 'worktree', label: '/worktree', hint: '查看当前对话的独立工作树', run: () => showInspectorTab('context') },
      { id: 'dashboard', label: '/dashboard', hint: '打开当前对话的持久工作面板', run: () => showInspectorTab('dashboard') },
    ] : []),
    ...(activeRun && runDone && store.runPrompts[activeRun.id] ? [{ id: 'retry', label: '/retry', hint: '把上一条要求重新执行一遍', run: () => store.retryRun(activeRun.id) }] : []),
    { id: 'plan', label: '/plan', hint: store.nextRunMode === 'plan' ? '取消：下一条直接执行' : '下一条先出计划，你批准后再动手', run: () => store.setNextRunMode(store.nextRunMode === 'plan' ? 'act' : 'plan') },
    { id: 'folder', label: '/folder', hint: '选择这个对话的工作目录', run: () => void chooseWorkspace() },
    { id: 'init', label: '/init', hint: '扫描工作区，生成或更新 AGENTS.md', run: () => { if (typeof activeConversation?.workspace !== 'string' || !activeConversation.workspace) { setToast('请先选择工作目录'); return; } void store.runInit(); } },
      { id: 'ide', label: '/ide', hint: '用系统默认程序打开当前工作目录；实际 IDE 关联由系统决定', run: () => {
        if (typeof activeConversation?.workspace !== 'string' || !activeConversation.workspace) { setToast('请先选择本机工作目录'); return; }
        if (activeConversation.workspace.startsWith('ssh://')) { setToast('远程目录不能从本机外部编辑器打开'); return; }
        if (!window.atlasDesktop?.openPath) { setToast('当前运行环境没有外部文件打开能力'); return; }
        void window.atlasDesktop.openPath(activeConversation.workspace).then((result) => {
          setToast(result === 'opened' || result === 'revealed' ? '已请求系统打开工作目录' : `无法打开工作目录：${result}`);
        }).catch((error) => setToast(`无法打开工作目录：${error instanceof Error ? error.message : String(error)}`));
      } },
      { id: 'recap', label: '/recap', hint: '用当前对话生成压缩回顾（Atlas 通过 /compact 保存回顾）', run: () => {
        if (!activeConversation) { setToast('先打开一个对话再生成回顾'); return; }
        void store.compactConversation(activeConversation.id, '生成当前对话的简短回顾，保留目标、关键决策、完成进度、未解决问题和下一步。').then((text) => { if (text) setToast(`对话回顾已更新：${text}`); });
      } },
      { id: 'raw', label: '/raw', hint: '查看最近一条 Atlas 回复的原始文本并复制', run: () => {
        const latest = [...messages].reverse().find((item) => item.role === 'assistant')?.content || reply;
        if (!latest) { setToast('当前还没有可查看的回复'); return; }
        setRawText(latest);
      } },
      { id: 'auto-review', label: '/auto-review', hint: '运行 Atlas 代码审查（映射到 /review，默认审查未提交改动；暂无独立自动审查开关）', run: () => { void store.sendMessage('/review'); } },
      { id: 'ask-selection', label: '/ask-selection', hint: '把当前选中的文字放进消息草稿', run: askSelectedText },
    { id: 'review', label: '/review', hint: '代码审查：branch <名> / commit <sha>，默认审查未提交改动', takesArgument: true, run: (arg: string) => { const focus = arg.trim(); void store.sendMessage(focus ? `/review ${focus}` : '/review'); } },
    { id: 'recipe', label: '/recipe', hint: '打开配方，带参数复跑保存过的任务', run: () => setRecipesOpen(true) },
    ...(activeConversation ? [{ id: 'btw', label: '/btw', hint: '旁问：不打断正在做的事，也不存进对话', takesArgument: true, run: (question: string) => setSide({ open: true, question: question.trim() || undefined }) }] : []),
    { id: 'open', label: '/open', hint: '在浏览器面板打开网址，如 /open localhost:5173', takesArgument: true, run: (target: string) => { if (target.trim()) setBrowserUrl(/^\w+:/.test(target.trim()) ? target.trim() : `http://${target.trim()}`); showInspectorTab('browser'); } },
    ...(activeConversation ? [{ id: 'compact', label: '/compact', hint: '压缩上下文，可附说明让摘要优先保留相关事项', takesArgument: true, run: (note: string) => void store.compactConversation(activeConversation.id, note).then((text) => { if (text) setToast(text); }) }] : []),
    { id: 'voice', label: '/voice', hint: '开始语音通话', run: startVoice },
    { id: 'auto', label: '/auto', hint: '打开自动化', run: () => go('auto') },
    { id: 'memory', label: '/memory', hint: '打开记忆', run: () => go('memory') },
    { id: 'context', label: '/context', hint: '查看上下文用量明细', run: () => showInspectorTab('context') },
    { id: 'diff', label: '/diff', hint: '查看本次运行的文件改动', run: () => showInspectorTab('changes') },
    { id: 'model', label: '/model', hint: '选择或切换模型', takesArgument: true, run: (query: string) => { const found = store.models.find((item) => item.id.toLowerCase() === query.trim().toLowerCase() || (item.name ?? '').toLowerCase() === query.trim().toLowerCase()); if (found) void store.selectModel(found.id); else setSheet('models'); } },
    { id: 'reasoning', label: '/reasoning', hint: '打开模型选择，查看当前可用的推理强度', run: () => setSheet('models') },
    { id: 'usage', label: '/usage', hint: '查看用量和费用', run: () => setSheet('usage') },
    { id: 'status', label: '/status', hint: '显示当前模型、推理强度和权限', run: () => setToast(`${modelName} · 推理 ${store.reasoningEffort || '默认'} · ${PERMISSION[permission].label}`) },
    { id: 'permissions', label: '/permissions', hint: '切换当前对话权限模式', run: () => { if (!activeConversation) { setToast('先打开一个对话再切换权限'); return; } setToast(`权限模式：${PERMISSION[cyclePermission()].label}`); } },
    { id: 'agents', label: '/agents', hint: '打开 Agents 页：常驻 Agent 花名册与详情', run: () => go('agents') },
    { id: 'ps', label: '/ps', hint: '查看后台进程和最近输出', run: () => showInspectorTab('processes') },
    { id: 'stop', label: '/stop', hint: '停止后台进程；不带编号时停止当前运行', takesArgument: true, run: (id: string) => { if (!id.trim()) store.stopTask(); else void backend.killProcess(id.trim()).then(() => setToast('后台进程已停止')).catch((error) => setToast(String(error))); } },
    { id: 'goal', label: '/goal', hint: '设置、查看、暂停、恢复或清除当前会话目标', takesArgument: true, run: (command: string) => { if (!activeConversation) { setToast('先打开一个对话再设置目标'); return; } void backend.runConversationGoalCommand(activeConversation.id, command).then((result) => { setConversationGoal(result.goal); setToast(result.output); if (result.prompt) void store.sendMessage(result.prompt); }).catch((error) => setToast(error instanceof Error ? error.message : String(error))); } },
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
      group: commandGroup(command.source), takesArgument: Boolean(command.argument_hint),
      run: (argument: string) => void runCustomCommand(command, argument),
    })),
  ];
  slashCommands.forEach((command) => {
    command.group ??= command.id.startsWith('skill-') ? '技能'
      : ['new', 'clear', 'resume', 'fork', 'undo', 'redo', 'rename', 'export'].includes(command.id) ? '会话'
        : ['goal', 'plan', 'agents', 'ps', 'stop', 'status'].includes(command.id) ? '任务'
          : ['model', 'permissions', 'usage', 'context', 'diff'].includes(command.id) ? '状态' : '工具';
  });
  const conversationsRef = useRef(store.conversations);
  conversationsRef.current = store.conversations;
  const searchMessages = useCallback(async (query: string): Promise<PaletteItem[]> => {
    if (!store.connected) return [];
    // Quote the text so FTS treats it as a phrase instead of query syntax.
    const hits = await api<Array<{ id: number | string; conversation_id: string; content: string }>>(store.apiBaseUrl, `/api/search?limit=12&q=${encodeURIComponent(`"${query.replace(/"/g, '""')}"`)}`);
    return hits.flatMap((hit) => {
      const conversation = conversationsRef.current.find((item) => item.id === hit.conversation_id);
      if (!conversation) return [];
      const at = hit.content.toLowerCase().indexOf(query.toLowerCase());
      const excerpt = hit.content.slice(Math.max(0, at - 16), Math.max(0, at - 16) + 60).replace(/\s+/g, ' ');
      return [{ id: `m-${hit.id}`, group: '消息内容', label: excerpt || conversation.title, hint: conversation.title, run: () => openConversation(conversation) }];
    });
  }, [store.apiBaseUrl, store.connected]);
  const workspacePath = typeof activeConversation?.workspace === 'string' ? activeConversation.workspace : '';
  const remoteHost = /^ssh:\/\/([^/]+)\//.exec(workspacePath)?.[1] ?? '';
  const workspaceName = workspacePath
    ? `${remoteHost ? `${remoteHost}:` : ''}${workspacePath.split(/[\\/]/).filter(Boolean).pop() ?? workspacePath}` : '';
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
    const root = typeof activeConversation?.workspace === 'string' ? activeConversation.workspace : '';
    // @ refers to files in the working directory; without one there is nothing to search.
    if (!root || !query) return [];
    const hits = await backend.searchWorkspace(root, query, 12);
    return hits.filter((hit) => hit.type === 'file' && !taken.has(`file:${hit.path}`)).map((hit) => ({ kind: 'file' as const, id: hit.path, label: hit.name, hint: hit.path }));
  };
  const currentModel = store.models.find((model) => model.id === store.model);
  const worktreeActive = Boolean(activeConversation?.worktree_path);
  const worktreeRequested = Boolean(store.worktreeRequests[store.activeConversationId]);
  const profileName = store.profiles.find((profile) => profile.id === store.profileId)?.name ?? '默认';
  const composerStatus = listening ? '正在听…' : store.connected ? '' : store.backendStarting ? 'Atlas 后端启动中…' : 'Atlas 后端没有连接';
  const composerBase = {
    value: input, onChange: setInput, attachments, onPickImages: addFiles, listening, onToggleMic: toggleSpeechInput,
    onEnhancePrompt: enhancePrompt, onAttachDrawing: attachDrawing, contextKey: store.activeConversationId,
    onRemoveAttachment: (index: number) => setAttachments((items) => items.filter((_, position) => position !== index)),
    files, onRemoveFile: (index: number) => setFiles((items) => items.filter((_, position) => position !== index)),
    findMentions, mentions, onAddMention: (item: MentionItem) => { if (item.id) setMentions((current) => [...current, item]); },
    onRemoveMention: (item: MentionItem) => setMentions((current) => current.filter((entry) => !(entry.kind === item.kind && entry.id === item.id))),
    onLongPaste: (text: string) => { addDocuments([new File([text], `粘贴的文本-${new Date().toLocaleTimeString().replace(/:/g, '')}.txt`, { type: 'text/plain' })]); setToast(`粘贴内容有 ${text.length} 个字，已转成附件`); },
    tools: <>
      <Menu>
        <Tip label={workspaceName ? `工作目录：${workspacePath}` : '选择工作目录'}><MenuTrigger asChild>
          <button type="button" className={cn('inline-flex h-8 max-w-[170px] items-center gap-1.5 rounded-[9px] px-2 text-[12.5px] hover:bg-hover', workspaceName ? 'text-fg-2' : 'text-fg-3')}>
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
          <button type="button" className={cn('inline-flex h-8 items-center gap-1.5 rounded-[9px] px-2 text-[12.5px] hover:bg-hover', permission === 'full_access' ? 'text-fg-3 hover:text-fg' : 'bg-brand-soft text-fg')}>
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
      {activeConversation && <RunSetupMenu conversation={activeConversation} workspace={workspacePath}
        onChange={(patch) => store.setConversationSettings(activeConversation.id, patch)}
        onPickFolder={async () => window.atlasDesktop?.selectDirectory
          ? window.atlasDesktop.selectDirectory(workspacePath || undefined)
          : window.prompt('允许访问的目录（完整路径）', '')?.trim() || null} />}
      {store.profiles.length > 0 && <Menu>
        <Tip label={`角色：${profileName}`}><MenuTrigger asChild>
          <button type="button" className={cn('inline-flex h-8 items-center gap-1.5 rounded-[9px] px-2 text-[12.5px] hover:bg-hover', store.profileId !== 'default' ? 'bg-brand-soft text-fg' : 'text-fg-3 hover:text-fg')}>
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
          <button type="button" className={cn('inline-flex h-8 items-center gap-1.5 rounded-[9px] px-2 text-[12.5px] hover:bg-hover', store.reasoningEffort ? 'bg-brand-soft text-fg' : 'text-fg-3 hover:text-fg')}>
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
          <button type="button" className={cn('inline-flex h-8 max-w-[150px] items-center gap-1.5 rounded-[9px] px-2 text-[12.5px] hover:bg-hover', worktreeActive || worktreeRequested ? 'bg-brand-soft text-fg' : 'text-fg-3 hover:text-fg')}>
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
          className={cn('inline-flex h-8 items-center gap-1.5 rounded-[9px] px-2 text-[12.5px]', store.nextRunMode === 'plan' ? 'bg-brand-soft text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg')}>
          <ListChecks size={15} />{store.nextRunMode === 'plan' && '先出计划'}
        </button>
      </Tip>
    </>,
    models: store.models, model: store.model, onSelectModel: (id: string) => void store.selectModel(id), onManageModels: () => setSheet('models'),
    status: composerStatus, autoFocus: true, commands: slashCommands,
    onCyclePermission: activeConversation ? cyclePermission : undefined,
  };
  const errorNote = store.error && <div role="alert" className="anim-fade mt-3 flex items-start justify-between gap-3 rounded-xl bg-danger-soft px-4 py-2.5 text-[13px] text-danger">
    <div className="min-w-0">
      <span>{store.error}</span>
      {/* 原始报错（多为英文）不直接糊给用户，收进可展开的详情。 */}
      {store.errorDetail && <details className="mt-0.5">
        <summary className="cursor-pointer select-none text-[12px] text-fg-3 hover:text-fg-2">详细信息</summary>
        <pre className="mt-1 mb-0 max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono text-[11.5px] text-fg-3">{store.errorDetail}</pre>
      </details>}
    </div>
    <button aria-label="关闭错误提示" onClick={store.dismissError} className="grid size-6 shrink-0 place-items-center rounded-md hover:bg-hover"><X size={14} /></button>
  </div>;

  const latestUsage = [...activeEvents].reverse().find((event) => event.type === 'run.usage')?.data;
  const contextUse = typeof latestUsage?.context_tokens === 'number' && typeof latestUsage?.context_limit === 'number' && latestUsage.context_limit > 0
    ? Math.round(latestUsage.context_tokens / latestUsage.context_limit * 100) : null;
  const rewind = async (messageId: string, files: boolean) => {
    const conversationId = storeRef.current.activeConversationId;
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
  const goalHeader = conversationGoal && <div className="mb-2 flex items-center gap-2 rounded-lg bg-brand-soft px-2.5 py-1.5 text-[12px] text-fg-2" aria-label="当前会话目标">
    <ListChecks size={13} className="shrink-0 text-brand" /><span className="min-w-0 flex-1 truncate">目标：{conversationGoal.text}</span>
    <span className="shrink-0 text-fg-3">{conversationGoal.status === 'active' ? '进行中' : conversationGoal.status === 'paused' ? '已暂停' : conversationGoal.status === 'done' ? '已完成' : conversationGoal.status} · {conversationGoal.turns_used}/{conversationGoal.max_turns}</span>
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
  const queueStrip = conversationQueue.length > 0 && <div className="mb-2 grid gap-1.5" aria-label="待发送的消息">
    {queuePaused && <div className="flex items-center gap-2 rounded-xl bg-sunken px-3 py-2 text-[12.5px] text-fg-2">
      <Pause size={13} />任务已停止，后面的 {conversationQueue.length} 条先不发。<span className="flex-1" />
      <Button size="sm" variant="ghost" onClick={() => store.resumeQueue(store.activeConversationId)}><Play />继续发送</Button>
    </div>}
    {conversationQueue.map((item, index) => <div key={item.id} className="flex items-center gap-2.5 rounded-xl bg-sunken px-3 py-2 text-[13px]">
      <span className="shrink-0 text-[12px] text-fg-3 tabular-nums">{index === 0 ? '下一条' : `第 ${index + 1} 条`}</span>
      <span className="min-w-0 flex-1 truncate text-fg">{item.content}</span>
      {item.attachments.length + item.files.length > 0 && <span className="shrink-0 text-[12px] text-fg-3">{item.attachments.length + item.files.length} 个附件</span>}
      {activeRun && !runDone && !item.attachments.length && !item.files.length && <Tip label="现在就交给正在做的任务"><button aria-label="把这条插话进当前任务" onClick={() => store.steerQueued(store.activeConversationId, item.id)}
        className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><MessageSquarePlus size={13} /></button></Tip>}
      <Tip label="取回来修改"><button aria-label="编辑这条待发消息" onClick={() => { const taken = store.takeQueued(store.activeConversationId, item.id); if (taken) { setInput(taken.content); setAttachments(taken.attachments); setFiles(taken.files.map((file) => ({ ...file, size: Math.floor(file.data_base64.length * 3 / 4) }))); } }}
        className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><Pencil size={13} /></button></Tip>
      <Tip label="停下当前这一步，马上发这条"><button aria-label="立即发送这条消息" onClick={() => store.sendQueuedNow(store.activeConversationId, item.id)}
        className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><Send size={13} /></button></Tip>
      <Tip label="不发了"><button aria-label="删除这条待发消息" onClick={() => store.removeQueued(store.activeConversationId, item.id)}
        className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><X size={13} /></button></Tip>
    </div>)}
  </div>;
  const retryNote = activeRun?.status === 'failed' && store.runPrompts[activeRun.id] && !working && <div className="mt-3 flex items-center gap-3 text-[13px] text-fg-2">
    这次没有完成。<Button size="sm" variant="secondary" aria-label="重试上一次失败的运行" onClick={() => store.retryRun(activeRun.id)}><RotateCcw />重试</Button>
  </div>;

  // Rewriting history mid-run would race the run's own writes.
  const canRewrite = store.connected && !(activeRun && !runDone) && !loadingMessages;
  canRewriteRef.current = canRewrite;

  const pageTitle = view === 'chat' ? activeConversation?.title ?? '新任务' : '';
  const besideConversation = view === 'chat' && besideId !== store.activeConversationId ? store.conversations.find((item) => item.id === besideId) : undefined;
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
        pendingMemories={pendingCount} username={username} subtitle={store.connected ? modelName : store.backendStarting ? '后端启动中…' : '后端没有连接'}
        theme={theme} onToggleTheme={toggleTheme} onSettings={() => setSheet('models')}
        pinned={store.pinned} archived={store.archived} unread={store.unread}
        running={runningConversations} queued={Object.fromEntries(Object.entries(store.queue).map(([id, items]) => [id, items.length]))}
        waiting={waitingConversations} onSetUnread={store.setConversationUnread}
        onSetWorkspace={(id, workspace) => store.setWorkspace(id, workspace)}
        onRename={(id, title) => void store.renameConversation(id, title)} onDelete={(id) => void store.deleteConversation(id)}
        onTogglePinned={store.togglePinned} onToggleArchived={store.toggleArchived} onExport={(id, format) => void store.exportConversation(id, format)} onDuplicate={(id) => void store.duplicateConversation(id)} onOpenBeside={setBesideId} />

      <main className="sheet relative my-2 mr-2 flex min-w-0 flex-1 flex-col overflow-hidden rounded-[14px]">
        <header className="drag flex h-11 shrink-0 items-center gap-1 pr-1.5 pl-5">
          <div className={cn('flex min-w-0 items-center gap-3', showTabs && 'flex-1')}>
            {showTabs
              ? <TabStrip tabs={tabs} conversations={store.conversations} activeId={store.activeConversationId} running={runningConversations} onSelect={openConversation} onClose={closeTab} />
              : pageTitle && <span className="truncate text-[13.5px] text-fg-2">{pageTitle}</span>}
            {view === 'chat' && <ForkTree conversations={store.conversations} activeId={store.activeConversationId} onOpen={openConversation} />}
            {connection}
          </div>
          {/* With tabs the left group already fills the bar; its empty part still drags the window. */}
          {!showTabs && <span className="flex-1" />}
          <div className="no-drag flex items-center gap-0.5">
            {view === 'chat' && <Tip label="朗读最近的回复"><button aria-label="朗读最近的回复" onClick={readLastReply} className="grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><Volume2 size={16} /></button></Tip>}
            <Tip label={voiceOutput ? '自动朗读已开' : '自动朗读新回复'}>
              <button aria-label="切换自动朗读" aria-pressed={voiceOutput} onClick={toggleVoiceOutput}
                className={cn('grid size-8 place-items-center rounded-lg hover:bg-hover', voiceOutput ? 'text-brand' : 'text-fg-3 hover:text-fg')}>
                {voiceOutput ? <Volume2 size={16} /> : <VolumeX size={16} />}
              </button>
            </Tip>
            <Tip label="语音通话"><button aria-label="开始语音通话" onClick={startVoice} className="grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><AudioLines size={16} /></button></Tip>
            {view === 'chat' && <Tip label="任务面板"><button aria-label="切换任务面板" aria-pressed={inspectorOpen} onClick={() => toggleInspector()}
              className={cn('grid size-8 place-items-center rounded-lg hover:bg-hover', inspectorOpen ? 'text-fg' : 'text-fg-3 hover:text-fg')}><PanelRight size={16} /></button></Tip>}
            {window.atlasDesktop && window.atlasDesktop.platform !== 'darwin' && <div className="ml-1.5 flex">
              <button aria-label="最小化窗口" onClick={() => window.atlasDesktop?.minimize()} className="grid h-8 w-10 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><Minus size={15} /></button>
              <button aria-label="最大化窗口" onClick={() => window.atlasDesktop?.maximize()} className="grid h-8 w-10 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg">{maximized ? <Copy size={13} /> : <Square size={12} />}</button>
              <button aria-label="关闭窗口" onClick={() => window.atlasDesktop?.close()} className="grid h-8 w-10 place-items-center rounded-lg text-fg-3 hover:bg-[#D2453E] hover:text-white"><X size={16} /></button>
            </div>}
          </div>
        </header>

        {view === 'home' && <HomeView username={username} notice={errorNote} recent={store.conversations.slice(0, 3)} onOpen={openConversation} onSuggest={suggest}
          composer={<Composer {...composerBase} variant="hero" onSubmit={() => void submit(true)}
            placeholder={homeMode === 'image' ? '描述你想要的画面，Atlas 会带你去图像工作台' : '描述一件事，Atlas 会把它做完'}
            modes={{ value: homeMode, options: HOME_MODES, onChange: (id) => { if (id === 'voice') startVoice(); else setHomeMode(id); } }} />} />}

        {view === 'chat' && <div className="flex min-h-0 flex-1">
          <div className="relative flex min-w-0 flex-1 flex-col">
            {activeRun && activeRun.conversationId === store.activeConversationId && <div className="pointer-events-none absolute top-2 right-5 z-20 flex justify-end [&>*]:pointer-events-auto">
              <ProgressCapsule run={activeRun} events={activeEvents} onShowAll={() => showInspectorTab('activity')} />
            </div>}
            {foregroundEvent && <ComputerEdgeBar apiBaseUrl={store.apiBaseUrl} runId={foregroundEvent.runId} className="shrink-0" />}
            <TimelineNav threadRef={threadRef} resetKey={store.activeConversationId}
              history={historyWithBranchNotes} items={timelineItems}
              hasEarlier={Boolean(store.messagesHasEarlier[store.activeConversationId])}
              truncatedCount={activeRun?.eventsTruncated ? (activeRun.droppedEventCount ?? 0) : 0}
              loading={loadingMessages} />
            <MessageThread history={historyWithBranchNotes} username={username} historyActions={historyActions} threadRef={threadRef} setTab={showInspectorTab}
              onOpenBrowser={(url) => { setBrowserUrl(url); showInspectorTab('browser'); }}
              emptyState={!messages.length && !activeEvents.length && !loadingMessages ? <div className="pt-[16vh] text-center">
                <Mark className="mx-auto mb-4 size-11" />
                <h2 className="m-0 font-serif text-[24px] font-semibold text-heading">这次要做什么？</h2>
                <p className="mt-2 text-[14px] text-fg-3">在下面说清楚目标，Atlas 会把过程和结果都放在这里。</p>
              </div> : null}
              footerNote={<>{retryNote}{errorNote}</>} />
            <div className="px-8 pb-5">
              <div className="mx-auto w-[min(720px,100%)]">
                {queueStrip}
                {todoStrip}
                <Composer {...composerBase} variant="dock" onSubmit={() => void submit(false)} placeholder={activeRun && !runDone ? '接着补充，会在这一步做完后发出…' : '接着说要做什么，/ 看命令，! 开头直接在终端运行…'} header={<>{editBanner}{goalHeader}{runHeader}{rewindBanner}</>} />
                <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[10.5px] text-fg-3" aria-label="运行状态">
                  {statusBar.model && <span className="max-w-36 truncate" title={modelName}>{modelName}</span>}{statusBar.reasoning && <span>推理 {store.reasoningEffort ? EFFORT_LABEL[store.reasoningEffort] : '默认'}</span>}
                  {statusBar.context && contextUse !== null && <span>上下文 {contextUse}%</span>}
                  {statusBar.tokens && typeof latestUsage?.input_tokens === 'number' && <span>用量 {Number(latestUsage.input_tokens) + Number(latestUsage.output_tokens ?? 0)} tokens</span>}
                  {statusBar.cost && typeof latestUsage?.cost_usd === 'number' && <span>${Number(latestUsage.cost_usd).toFixed(4)}</span>}
                  {statusBar.git && (activeConversation?.worktree_branch || gitBranch) && <span className="max-w-32 truncate"><GitBranch size={10} className="mr-1 inline" />{String(activeConversation?.worktree_branch || gitBranch)}</span>}
                  {statusBar.permission && activeConversation && <span>{PERMISSION[permission].label}</span>}
                  {statusBar.processes && processCount !== null && <button onClick={() => showInspectorTab('processes')} className="hover:text-fg">后台进程 {processCount}</button>}
                </div>
              </div>
            </div>
          </div>
          {besideConversation && <SidePane conversation={besideConversation} username={username} onClose={() => setBesideId('')}
            onSwitch={() => { const previous = store.activeConversationId; openConversation(besideConversation); setBesideId(previous); }} />}
          {inspectorOpen && <Inspector tab={inspectorTab} onTab={setInspectorTab} onClose={() => toggleInspector(false)} run={activeRun} artifacts={activeArtifacts}
            conversationTitle={activeConversation?.title} modelName={modelName} tools={store.tools} skills={store.skills} activeSkills={store.activeSkills} capabilities={store.capabilities}
            apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify}
            workspace={typeof activeConversation?.workspace === 'string' ? activeConversation.workspace : null} onChooseWorkspace={() => void chooseWorkspace()}
            browserUrl={browserUrl} onBrowserUrl={setBrowserUrl} browserSuggestions={localUrls} onPick={pickElement}
            onPreview={(url) => { setBrowserUrl(url); showInspectorTab('browser'); }} conversationId={store.activeConversationId}
            worktree={activeConversation?.worktree_path ? { path: String(activeConversation.worktree_path), branch: String(activeConversation.worktree_branch ?? ''), base: String(activeConversation.base_branch ?? '') } : null}
            onWorktreeChanged={() => void store.refreshConversations()}
            onAsk={(text) => void store.sendMessage(text)}
            terminalCommand={terminalCommand} onSendToAtlas={(text) => { setInput((current) => `${current.trim() ? `${current.trimEnd()}\n\n` : ''}终端输出：\n\`\`\`\n${text.trimEnd()}\n\`\`\`\n\n`); setToast('已把终端输出放进输入框'); }} />}
        </div>}

    {view === 'board' && <BoardPage conversations={store.conversations} runs={store.runs} queue={store.queue} unread={store.unread} archived={store.archived}
      onOpen={openConversation} onStop={store.stopRun} onArchive={store.toggleArchived} />}
    {view === 'agents' && <AgentsPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} username={username} />}
    {view === 'devices' && <DevicesPage onToast={notify} />}
    {view === 'workbench' && <WorkbenchPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
    {view === 'library' && <LibraryPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
    {view === 'groups' && <GroupsView onToast={notify} />}
    {view === 'code' && <CodePage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
        {view === 'create' && <CreatePage onDraft={draft} onVoice={startVoice} apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} initialPrompt={createPrompt} />}
        {view === 'auto' && <AutomationPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
        {view === 'memory' && <MemoryPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} onPendingChange={setPendingCount} />}
        {view === 'skills' && <div className="screen"><SkillsMarketPage apiBaseUrl={store.apiBaseUrl} onToast={notify}
          onTryInConversation={(name) => { store.applySkill(name); go('chat'); }} /></div>}
        {view === 'evolution' && <EvolutionPage apiBaseUrl={store.apiBaseUrl} onToast={notify} />}
      </main>
    </div>

    <Dialog open={Boolean(sheet)} onOpenChange={(open) => { if (!open) setSheet(null); }} label="设置"
      className="grid h-[min(720px,calc(100vh-48px))] w-[min(980px,calc(100vw-32px))] grid-cols-[210px_minmax(0,1fr)]">
      <nav aria-label="设置分类" className="overflow-y-auto bg-sunken px-2.5 py-5 shadow-[inset_-1px_0_0_var(--line)]">
        <h2 className="m-0 px-2.5 pb-3 font-serif text-[18px] font-semibold text-heading">设置</h2>
        <label className="mx-1 mb-3 flex h-9 items-center gap-2 rounded-lg bg-surface px-2.5 shadow-[inset_0_0_0_1px_var(--line)] focus-within:shadow-[inset_0_0_0_1px_var(--brand)]">
          <Search size={14} className="shrink-0 text-fg-3" />
          <input aria-label="搜索设置" value={settingsQuery} onChange={(event) => setSettingsQuery(event.target.value)} placeholder="搜索设置项…" className="min-w-0 flex-1 bg-transparent text-[12px] text-fg outline-none placeholder:text-fg-3" />
          {settingsQuery && <button type="button" aria-label="清除设置搜索" onClick={() => setSettingsQuery('')} className="text-[11px] text-fg-3 hover:text-fg">清除</button>}
        </label>
        {SETTINGS_NAV.filter(([, label, , terms]) => `${label} ${terms}`.toLowerCase().includes(settingsQuery.trim().toLowerCase())).map(([pane, label, Icon]) =>
          <button key={pane} aria-current={sheet === pane} onClick={() => { setSheet(pane); setSettingsQuery(''); }}
            className={cn('flex h-9 w-full items-center gap-2.5 rounded-[9px] px-2.5 text-left text-[13.5px] transition-colors', sheet === pane ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
            <Icon size={16} className={sheet === pane ? 'text-brand' : undefined} />{label}
          </button>)}
        {SETTINGS_NAV.every(([, label, , terms]) => !`${label} ${terms}`.toLowerCase().includes(settingsQuery.trim().toLowerCase())) && <p className="px-2.5 py-2 text-[11px] text-fg-3">没有匹配的设置。</p>}
        <button onClick={() => { setSheet(null); setOnboardingOpen(true); }} className="mt-3 flex h-9 w-full items-center gap-2.5 rounded-[9px] px-2.5 text-left text-[13px] text-fg-3 hover:bg-hover hover:text-fg">
          <Sparkles size={16} />开始向导</button>
      </nav>
      <div className="relative min-h-0 overflow-auto px-8 pt-7 pb-8">
        <button aria-label="关闭设置" onClick={() => setSheet(null)} className="absolute top-4 right-4 grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><X size={17} /></button>
        {sheet === 'models' && <SettingsPage username={username} onSaveUsername={saveUsername} apiBaseUrl={store.apiBaseUrl} providerBaseUrl={store.providerBaseUrl} connected={store.connected} apiKeyConfigured={store.apiKeyConfigured} busy={store.settingsBusy} connectionTest={store.connectionTest} error={store.error} errorDetail={store.errorDetail} models={store.models} selectedModel={store.model} subagentsEnabled={store.subagentsEnabled} subagentDefaultModel={store.subagentDefaultModel} onSaveSubagentSettings={(enabled, model) => store.saveSubagentSettings(enabled, model)} providers={store.providers} reasoningStages={store.reasoningStages} onBack={() => setSheet(null)} onSelectModel={(model) => void store.selectModel(model)} onSaveProvider={(baseUrl, apiKey) => store.saveProviderSettings(baseUrl, apiKey)} onAddModel={(model) => store.addCustomModel(model)} onTestConnection={(model) => void store.testModelConnection(model)} statusBar={statusBar} onStatusBarChange={updateStatusBar} onLoadProviders={store.loadProviders} onSaveProviderConfig={store.saveProviderConfig} onAddProviderKey={(providerId, secret, label) => store.addProviderKey(providerId, secret, label)} onRemoveProviderKey={(providerId, keyId) => void store.removeProviderKey(providerId, keyId)} onUpdateModel={(modelId, patch) => store.updateCustomModel(modelId, patch)} onDeleteModel={(modelId) => store.deleteCustomModel(modelId)} onSaveReasoningStages={(config) => void store.saveReasoningStages(config)} />}
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
          <AppearanceNotificationsPanel theme={theme} onThemeChange={chooseTheme} username={username} onSaveUsername={saveUsername} onToast={notify} section="appearance" />
          <div className="set-list">
            <div className="set-row"><div>收起侧边栏<small>只显示图标，给内容更多空间</small></div><button className="switch" role="switch" aria-label="收起侧边栏" aria-checked={sideMini} onClick={toggleMini} /></div>
            <div className="set-row"><div>自动朗读新回复<small>用本机语音逐句读出 Atlas 的回答</small></div><button className="switch" role="switch" aria-label="自动朗读新回复" aria-checked={voiceOutput} onClick={toggleVoiceOutput} /></div>
          </div>
        </section>}
        {sheet === 'usage' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">用量</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">每次任务用了多少 token、缓存帮你省了多少、大概花了多少钱。</p><UsagePanel username={username} onSaveUsername={saveUsername} /></section>}
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
        {sheet === 'expert' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">专家模式</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">一键切换：开着时在普通配置之上额外加载你自己写的配置和说明。</p><ExpertModePanel apiBaseUrl={store.apiBaseUrl} onToast={notify} /></section>}
        {sheet === 'network' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">模型网络</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">为支持的模型连接配置本机代理与自定义 CA 证书。</p><NetworkSettingsPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'shortcuts' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">快捷键</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">改成你顺手的组合键，只在这台电脑上生效。</p><ShortcutsPanel /></section>}
        {sheet === 'hooks' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">Hooks</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">在任务开始、用工具前后、完成或失败时运行你自己的命令。</p><HooksPanel /></section>}
        {sheet === 'notifications' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">通知</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">任务完成、需要确认时怎么提醒你。</p><div className="grid gap-6"><AppearanceNotificationsPanel theme={theme} onThemeChange={chooseTheme} username={username} onSaveUsername={saveUsername} onToast={notify} section="notifications" /><NotificationsPanel apiBaseUrl={store.apiBaseUrl} /></div></section>}
        {sheet === 'mcp' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">MCP 服务</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">管理 Atlas 已支持的 MCP 服务，并浏览服务显式提供的资源。</p><div className="grid gap-8"><McpServersPanel apiBaseUrl={store.apiBaseUrl} /><McpResourcesPanel apiBaseUrl={store.apiBaseUrl} /></div></section>}
        {sheet === 'skills' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">Skills</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">搜索、安装和审阅技能；外部技能会先进入安全复核。</p><SkillsMarketPage apiBaseUrl={store.apiBaseUrl} onToast={notify} onTryInConversation={(name) => { store.applySkill(name); go('chat'); setSheet(null); }} /></section>}
        {sheet === 'recipes' && <RecipeManagerPanel apiBaseUrl={store.apiBaseUrl} models={store.models} providers={store.providers} onLaunch={launchRecipeTemplate} />}
        {sheet === 'extensions' && <div className="grid gap-8"><ExtensionCatalogPanel apiBaseUrl={store.apiBaseUrl} /><ExtensionPackagesPanel apiBaseUrl={store.apiBaseUrl} /></div>}
        {sheet === 'transfer' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">配置导入导出</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">转移允许携带的本地偏好；密钥、地址和路径不会进入导出文件。</p><ConfigTransferPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'diagnostics' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">本机诊断</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">只读检查本机 Atlas 状态；报告不会上传原始配置、日志、密钥或路径。</p><DiagnosticsPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'telemetry' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">遥测隐私</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">只管理 Atlas 附带的 MemOS Local 插件 sender，不影响其他服务。</p><TelemetryPrivacyPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'security' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">工作区安全</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">管理当前对话后续运行的权限与 Docker 隔离。工作区规则仍在首次读取时由你确认。</p>{activeConversation ? <WorkspaceSecurityPanel apiBaseUrl={store.apiBaseUrl} conversation={activeConversation} onChange={(patch) => store.setConversationSettings(activeConversation.id, patch)} /> : <div className="rounded-xl bg-sunken p-4 text-[13px] text-fg-3">先打开一个对话，再配置该对话的工作区权限和沙箱。</div>}</section>}
        {sheet === 'commands' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">自定义斜杠命令</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">查看所有已发现命令；这里只能新建和编辑 Atlas 用户级命令，项目、Claude 与插件命令保持只读。</p><CustomCommandsPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'limits' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">运行限制</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">控制新运行的主循环轮数上限，并查看当前可用的 token/费用预算边界。</p><RunLimitsPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'platform' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">平台集成</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">配置桌面窗口、系统级快捷键，并在本机 VS Code 或 JetBrains IDE 打开工作区。</p><PlatformSettingsPanel workspacePath={activeConversation?.workspace} /></section>}
        {sheet === 'integrations' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">任务与集成入口</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">使用已接通的 GitHub PR、Linear、Slack 和本机自动化功能；云端任务服务未提供。</p><div className="grid gap-8"><SettingsIntegrationsPanel onOpenCode={() => { setSheet(null); go('code'); }} onOpenChannels={() => setSheet('channels')} onOpenAutomation={() => { setSheet(null); go('auto'); }} /><LinearIntegrationPanel apiBaseUrl={store.apiBaseUrl} /></div></section>}
      </div>
    </Dialog>

    <Palette items={paletteItems} open={paletteOpen} onClose={() => setPaletteOpen(false)} search={searchMessages} />

    {voiceOpen && <VoiceOverlay
      onClose={(toChat) => { setVoiceOpen(false); if (toChat) go('chat'); }}
      onSend={(text) => { if (view !== 'chat') setView('chat'); void store.sendMessage(text); }}
      runId={store.activeRunId ?? null}
      reply={reply}
      runDone={runDone}
      modelName={modelName}
    />}

    <RemoteFolderDialog open={remoteOpen} onClose={() => setRemoteOpen(false)} current={workspacePath}
      onChoose={(workspace) => { void (async () => {
        if (!store.activeConversationId) await store.createConversation();
        const conversationId = useAtlasStore.getState().activeConversationId;
        if (conversationId) { store.setWorkspace(conversationId, workspace); setToast(`工作目录：${workspace}`); }
      })(); }} />
    <InitDialog onToast={notify} />
    <OnboardingDialog open={onboardingOpen} onClose={closeOnboarding} username={username}
      onUsername={(value) => { setPref('username', value); setUsername(value); }}
      defaultWorkspace={defaultWorkspace} onDefaultWorkspace={(path) => { setPref('default-workspace', path); setDefaultWorkspace(path); }}
      onTry={(text) => {
        closeOnboarding(); go('chat');
        // Opening a conversation restores its saved draft, so the example goes in as that draft.
        void store.createConversation().then(() => {
          const id = useAtlasStore.getState().activeConversationId;
          if (!id) return;
          if (defaultWorkspace) store.setWorkspace(id, defaultWorkspace);
          writeDraft(id, text); setInput(text);
        });
      }} />
    <RecipesDialog open={recipesOpen} onClose={() => setRecipesOpen(false)} recipes={store.recipes}
      onRun={(id, params) => { go('chat'); void store.runRecipe(id, params); }} onDelete={(id) => void store.deleteRecipe(id)} />
    <Dialog open={rawText !== null} onOpenChange={(open) => { if (!open) setRawText(null); }} label="最近回复的原始文本" className="flex max-h-[82vh] w-[min(900px,92vw)] flex-col bg-panel p-4 shadow-xl">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="m-0 text-[15px] font-semibold text-heading">最近回复的原始文本</h2>
        <span className="flex-1" />
        <button type="button" aria-label="复制原始回复" onClick={() => {
          if (!rawText) return;
          void navigator.clipboard.writeText(rawText).then(() => setToast('已复制原始回复')).catch(() => setToast('复制失败'));
        }} className="rounded-lg px-3 py-1.5 text-[12.5px] text-fg-2 hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">复制</button>
        <button type="button" aria-label="关闭原始文本" onClick={() => setRawText(null)} className="grid size-8 place-items-center rounded-lg hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"><X size={16} /></button>
      </div>
      <pre className="m-0 min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-sunken p-3 font-mono text-[12px] leading-relaxed text-fg" tabIndex={0}>{rawText}</pre>
    </Dialog>
    {activeConversation && <SideChat open={side.open} onClose={() => setSide({ open: false })} conversationId={activeConversation.id} model={store.model} initialQuestion={side.question} />}

    <UpdateBanner />
    {view !== 'chat' && view !== 'home' && <ExpertModeBadge apiBaseUrl={store.apiBaseUrl} onOpen={() => setSheet('expert')} />}
    {toast && <div role="status" className="pop anim-pop fixed bottom-7 left-1/2 z-[80] -translate-x-1/2 rounded-xl px-4 py-2.5 text-[13.5px] text-fg">{toast}</div>}
  </TooltipProvider>;
}

function MessageAction({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return <Tip label={label}><button aria-label={label} onClick={onClick} className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg">{children}</button></Tip>;
}
