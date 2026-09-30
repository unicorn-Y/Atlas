import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AudioLines, Bell, BookMarked, Brain, Copy, Keyboard, Sparkles, Laptop, Webhook, Server, ShieldCheck, ShieldAlert as ShieldAsk, Lock, Download, FolderOpen, GitBranch, GitBranchPlus, MessagesSquare, UserCog, Image as ImageIcon, ListChecks, MessageCircle, MessageSquarePlus, Minus, Moon, PanelRight, Pause, Pencil, Play, Plus, Puzzle, RotateCcw, Send, Settings,
  SlidersHorizontal, Square, Sun, Volume2, VolumeX, X,
} from 'lucide-react';
import { backend, useAtlasStore } from './store/useAtlasStore';
import type { RunFile } from '@atlas/backend-adapter';
import ConversationActivity from './components/ConversationActivity';
import ConversationMessage from './components/ConversationMessage';
import Composer, { type ComposerMode, type MentionItem, type SlashCommand } from './components/Composer';
import RecipesDialog from './components/RecipesDialog';
import SideChat from './components/SideChat';
import RemoteFolderDialog from './components/RemoteFolderDialog';
import TimelineNav from './components/TimelineNav';
import ForkTree from './components/ForkTree';
import RunSetupMenu from './components/RunSetupMenu';
import TabStrip from './components/TabStrip';
import OnboardingDialog from './components/OnboardingDialog';
import SidePane from './components/SidePane';
import ShortcutsPanel from './pages/ShortcutsPanel';
import { loadBindings, matchShortcut } from './services/shortcuts';
import type { PermissionMode } from '@atlas/backend-adapter';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from './ui/Menu';
import Mark, { MarkDefs } from './components/Mark';
import Palette, { type PaletteItem } from './components/Palette';
import VoiceOverlay, { getSpeechRecognition, type SpeechRecognitionLike } from './components/VoiceOverlay';
import SettingsPage from './pages/SettingsPage';
import SkillDiscoveryPage from './pages/SkillDiscoveryPage';
import MemoryPage from './pages/MemoryPage';
import AutomationPage from './pages/AutomationPage';
import CodePage from './pages/CodePage';
import CreatePage from './pages/CreatePage';
import BoardPage from './pages/BoardPage';
import ProfilesPanel from './pages/ProfilesPanel';
import HooksPanel from './pages/HooksPanel';
import { NotificationsPanel, PluginsPanel } from './pages/ConsolePage';
import Sidebar, { NAV, type View } from './shell/Sidebar';
import HomeView, { type Suggestion } from './shell/HomeView';
import Inspector, { type InspectorTab } from './shell/Inspector';
import type { PickedElement } from './shell/panels/BrowserPanel';
import { THEMES, isTheme, nextTheme, themeInfo, type Theme } from './shell/themes';
import { api, relativeTime } from './services/api';
import { Button } from './ui/Button';
import { Dialog } from './ui/Dialog';
import { Tip, TooltipProvider } from './ui/Tooltip';
import { cn } from './ui/cn';

type SheetPane = 'models' | 'profiles' | 'hooks' | 'shortcuts' | 'appearance' | 'plugins' | 'notifications';

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
  ask_writes: { label: '改前问我', hint: '改文件、运行命令前先问你' },
  read_only: { label: '只读', hint: '只能查看，不能改任何东西' },
};
const EFFORT_LABEL: Record<string, string> = { minimal: '最低', low: '低', medium: '中', high: '高' };
const draftKey = (conversationId: string) => `atlas.draft.${conversationId || 'home'}`;
const readDraft = (conversationId: string) => { try { return localStorage.getItem(draftKey(conversationId)) ?? ''; } catch { return ''; } };
const writeDraft = (conversationId: string, text: string) => {
  try { if (text) localStorage.setItem(draftKey(conversationId), text); else localStorage.removeItem(draftKey(conversationId)); } catch { /* storage unavailable */ }
};
const pref = (key: string) => { try { return localStorage.getItem(`atlas.preference.${key}`); } catch { return null; } };
const setPref = (key: string, value: string) => { try { localStorage.setItem(`atlas.preference.${key}`, value); } catch { /* storage unavailable */ } };

export default function App() {
  const store = useAtlasStore();
  const [view, setView] = useState<View>('home');
  const [inspectorOpen, setInspectorOpen] = useState(() => pref('canvas') === 'true');
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('artifacts');
  const [theme, setTheme] = useState<Theme>(() => { const saved = pref('appearance'); return isTheme(saved) ? saved : 'light'; });
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
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [input, setInput] = useState('');
  const [homeMode, setHomeMode] = useState('chat');
  const [createPrompt, setCreatePrompt] = useState('');
  const [toast, setToast] = useState('');
  const [attachments, setAttachments] = useState<string[]>([]);
  const [files, setFiles] = useState<Array<RunFile & { size: number }>>([]);
  const [editing, setEditing] = useState<{ id: string; original: string } | null>(null);
  const [browserUrl, setBrowserUrl] = useState('');
  const [terminalCommand, setTerminalCommand] = useState<{ id: string; text: string } | null>(null);
  const [mentions, setMentions] = useState<MentionItem[]>([]);
  const [recipesOpen, setRecipesOpen] = useState(false);
  const [side, setSide] = useState<{ open: boolean; question?: string }>({ open: false });
  const [branches, setBranches] = useState<string[]>([]);
  const [remoteOpen, setRemoteOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [besideId, setBesideId] = useState('');
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
  const [maximized, setMaximized] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
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
  const modelName = store.models.find((model) => model.id === store.model)?.name ?? store.model ?? '默认模型';
  const loadingMessages = store.loadingMessagesConversationId === store.activeConversationId && Boolean(store.activeConversationId);
  const working = store.busy && !store.paused;
  const reply = useMemo(() => {
    const completed = [...activeEvents].reverse().find((event) => event.type === 'message.completed');
    if (completed?.data.content) return String(completed.data.content);
    return activeEvents.filter((event) => event.type === 'message.delta').map((event) => String(event.data.content ?? '')).join('');
  }, [activeEvents]);

  const go = useCallback((next: View) => setView(next), []);

  // Unsent text survives switching conversations and restarting the app.
  const draftOwnerRef = useRef(store.activeConversationId);
  useEffect(() => {
    if (draftOwnerRef.current === store.activeConversationId) return;
    draftOwnerRef.current = store.activeConversationId;
    setInput(readDraft(store.activeConversationId));
  }, [store.activeConversationId]);
  useEffect(() => {
    const timer = window.setTimeout(() => writeDraft(draftOwnerRef.current, input), 300);
    return () => window.clearTimeout(timer);
  }, [input]);
  const notify = useCallback((text: string) => setToast(text), []);

  useEffect(() => { void store.initialize(); }, []);
  // First run: the settings sheet opens once, as soon as the backend reports no API key.
  useEffect(() => {
    if (firstRunShownRef.current || !store.connected || store.conversationsLoading || store.apiKeyConfigured) return;
    firstRunShownRef.current = true;
    setSheet('models');
  }, [store.apiKeyConfigured, store.connected, store.conversationsLoading]);
  useEffect(() => window.atlasDesktop?.onMaximizeChange(setMaximized), []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name=theme-color]')?.setAttribute('content', themeInfo(theme).windowColor);
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

  // Each conversation reopens where it was left; new ones start at the latest message.
  const scrollPositions = useRef(new Map<string, number>());
  const restoredRef = useRef('');
  useEffect(() => {
    const element = threadRef.current;
    if (!element || view !== 'chat' || loadingMessages || restoredRef.current === store.activeConversationId) return;
    restoredRef.current = store.activeConversationId;
    const saved = scrollPositions.current.get(store.activeConversationId);
    element.scrollTop = saved ?? element.scrollHeight;
  }, [store.activeConversationId, loadingMessages, view]);
  useEffect(() => { if (view !== 'chat') restoredRef.current = ''; }, [view]);

  // Keep the thread pinned to the bottom while new content streams in, unless the user scrolled up.
  useEffect(() => {
    const element = threadRef.current;
    if (!element) return;
    if (element.scrollHeight - element.scrollTop - element.clientHeight < 160) element.scrollTop = element.scrollHeight;
  }, [messages.length, activeEvents.length, view]);

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
    setEditing(null);
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
      setInput('');
      setEditing(null);
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
    if (fromHome) {
      go('chat');
      // Home always starts something new, unless the open conversation is still empty.
      if (store.activeConversationId && messages.length) await store.createConversation(text.trim().slice(0, 40) || 'New conversation');
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
    }))).then((read) => setFiles((current) => [...current, ...read])).catch(() => setToast('读取文件失败'));
  };
  const addImages = (picked: File[]) => {
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
    }))).then((images) => setAttachments((current) => [...current, ...images].slice(0, 4))).catch(() => setToast('读取图片失败'));
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
  const chooseTheme = (next: Theme) => { setTheme(next); setPref('appearance', next); };
  const toggleTheme = () => { const next = nextTheme(theme); chooseTheme(next); setToast(`已切换到${themeInfo(next).label}`); };
  const toggleMini = () => setSideMini((current) => { setPref('sidebar-mini', String(!current)); return !current; });
  const toggleInspector = (open?: boolean) => setInspectorOpen((current) => { const next = open ?? !current; setPref('canvas', String(next)); return next; });
  const showInspectorTab = (tab: InspectorTab) => { setInspectorTab(tab); toggleInspector(true); };
  const openConversation = (conversation: (typeof store.conversations)[number]) => { go('chat'); void store.openConversation(conversation); };
  const draft = (text: string) => { go('chat'); setInput(text); void store.createConversation(); };
  const suggest = (suggestion: Suggestion) => { setInput(suggestion.text); setHomeMode(suggestion.mode ?? 'chat'); };

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
    ...store.conversations.slice(0, 30).map((conversation) => ({ id: `c-${conversation.id}`, group: '任务', label: conversation.title, hint: relativeTime(conversation.updated_at), run: () => openConversation(conversation) })),
  ];

  const slashCommands: SlashCommand[] = [
    { id: 'new', label: '/new', hint: '新任务', run: newTask },
    ...(activeConversation ? [
      { id: 'export', label: '/export', hint: '导出当前对话为 JSON', run: () => void store.exportConversation(activeConversation.id) },
      { id: 'rename', label: '/rename', hint: '把后面的文字设为对话名称', takesArgument: true, run: (title: string) => { if (title.trim()) void store.renameConversation(activeConversation.id, title); else setToast('在 /rename 后面写上新名称'); } },
    ] : []),
    ...(activeRun && runDone && store.runPrompts[activeRun.id] ? [{ id: 'retry', label: '/retry', hint: '把上一条要求重新执行一遍', run: () => store.retryRun(activeRun.id) }] : []),
    { id: 'plan', label: '/plan', hint: store.nextRunMode === 'plan' ? '取消：下一条直接执行' : '下一条先出计划，你批准后再动手', run: () => store.setNextRunMode(store.nextRunMode === 'plan' ? 'act' : 'plan') },
    { id: 'folder', label: '/folder', hint: '选择这个对话的工作目录', run: () => void chooseWorkspace() },
    { id: 'recipe', label: '/recipe', hint: '打开配方，带参数复跑保存过的任务', run: () => setRecipesOpen(true) },
    ...(activeConversation ? [{ id: 'btw', label: '/btw', hint: '旁问：不打断正在做的事，也不存进对话', takesArgument: true, run: (question: string) => setSide({ open: true, question: question.trim() || undefined }) }] : []),
    { id: 'open', label: '/open', hint: '在浏览器面板打开网址，如 /open localhost:5173', takesArgument: true, run: (target: string) => { if (target.trim()) setBrowserUrl(/^\w+:/.test(target.trim()) ? target.trim() : `http://${target.trim()}`); showInspectorTab('browser'); } },
    ...(activeConversation ? [{ id: 'compact', label: '/compact', hint: '压缩这个对话的上下文，省 token', run: () => void store.compactConversation(activeConversation.id).then((text) => { if (text) setToast(text); }) }] : []),
    { id: 'voice', label: '/voice', hint: '开始语音通话', run: startVoice },
    { id: 'auto', label: '/auto', hint: '打开自动化', run: () => go('auto') },
    { id: 'memory', label: '/memory', hint: '打开记忆', run: () => go('memory') },
    ...store.skills.map((skill) => ({
      id: `skill-${skill.name}`, label: `/${skill.name}`,
      hint: store.activeSkills.includes(skill.name) ? '技能已启用，选中后停用' : skill.description || '启用这个技能',
      run: () => {
        if (store.activeSkills.includes(skill.name)) { store.removeSkill(skill.name); setToast(`已停用技能 ${skill.name}`); }
        else { store.applySkill(skill.name); setToast(`下一次任务会用上 ${skill.name}`); }
      },
    })),
  ];
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
  const permission: PermissionMode = (activeConversation?.permission_mode as PermissionMode | undefined) ?? 'full_access';
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
  const composerStatus = listening ? '正在听…' : store.connected ? '' : 'Atlas 后端没有连接';
  const composerBase = {
    value: input, onChange: setInput, attachments, onPickImages: addFiles, listening, onToggleMic: toggleSpeechInput,
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
            {permission === 'read_only' ? <Lock size={15} /> : permission === 'ask_writes' ? <ShieldAsk size={15} /> : <ShieldCheck size={15} />}{permission !== 'full_access' && PERMISSION[permission].label}
          </button>
        </MenuTrigger></Tip>
        <MenuContent side="top">
          <MenuLabel>这个对话的权限</MenuLabel>
          {(['full_access', 'ask_writes', 'read_only'] as const).map((mode) => <MenuItem key={mode} checked={permission === mode} onSelect={() => {
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
      {workspaceName && !remoteHost && <Menu onOpenChange={(opening) => { if (opening && !worktreeActive) void backend.getBranches(String(activeConversation?.workspace)).then((result) => setBranches(result.branches)).catch(() => setBranches([])); }}>
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
  };
  const errorNote = store.error && <div role="alert" className="anim-fade mt-3 flex items-center justify-between gap-3 rounded-xl bg-danger-soft px-4 py-2.5 text-[13px] text-danger">
    <span>{store.error}</span>
    <button aria-label="关闭错误提示" onClick={store.dismissError} className="grid size-6 place-items-center rounded-md hover:bg-hover"><X size={14} /></button>
  </div>;

  const latestUsage = [...activeEvents].reverse().find((event) => event.type === 'run.usage')?.data;
  const contextUse = typeof latestUsage?.context_tokens === 'number' && typeof latestUsage?.context_limit === 'number' && latestUsage.context_limit > 0
    ? Math.round(latestUsage.context_tokens / latestUsage.context_limit * 100) : null;
  const editBanner = editing && <div className="mb-2.5 flex items-center gap-2.5 pb-2.5 text-[12.5px] text-fg-2 shadow-[inset_0_-1px_0_var(--line)]">
    <Pencil size={13} />修改后重新发送，这条之后的对话会被替换
    <span className="flex-1" />
    <Button size="sm" variant="ghost" onClick={() => { setEditing(null); setInput(''); }}>取消</Button>
  </div>;
  const runHeader = activeRun && !runDone && <div className="mb-2.5 flex items-center gap-2.5 text-[12.5px] text-fg-2 shadow-[inset_0_-1px_0_var(--line)] pb-2.5">
    <Mark className="size-[18px]" working={working} />
    <span className={working ? 'text-fg' : undefined}>{store.paused ? '已暂停' : RUN_LABEL[activeRun.status] ?? '正在处理'}</span>
    {planSteps.length > 0 && <span className="flex items-center gap-2" aria-label="当前计划进度">
      <span className="h-[3px] w-24 overflow-hidden rounded-full bg-line"><i className="block h-full rounded-full bg-brand transition-[width] duration-500" style={{ width: `${completedPlanSteps / planSteps.length * 100}%` }} /></span>
      <span className="tabular-nums">{completedPlanSteps} / {planSteps.length}</span>
    </span>}
    {contextUse !== null && <Tip label="这次对话占用的上下文窗口，快满时可以用 /compact 压缩"><span className={cn('tabular-nums', contextUse >= 80 ? 'text-danger' : 'text-fg-3')}>上下文 {contextUse}%</span></Tip>}
    <span className="flex-1" />
    <div role="radiogroup" aria-label="运行中发的消息" className="flex gap-0.5 rounded-[8px] bg-sunken p-[2px] shadow-[inset_0_0_0_1px_var(--line)]">
      {([['steer', '插话', '马上交给正在做的任务'], ['queue', '排队', '等这次做完再发']] as const).map(([id, label, hint]) =>
        <Tip key={id} label={hint}><button role="radio" aria-checked={store.followUpMode === id} onClick={() => store.setFollowUpMode(id)}
          className={cn('h-6 rounded-[6px] px-2 text-[12px]', store.followUpMode === id ? 'raised text-fg' : 'text-fg-3 hover:text-fg')}>{label}</button></Tip>)}
    </div>
    {store.busy && <>
      <Button size="sm" variant="ghost" onClick={() => store.togglePaused()}>{store.paused ? <Play /> : <Pause />}{store.paused ? '继续' : '暂停'}</Button>
      <Button size="sm" variant="ghost" onClick={() => store.stopTask()}><Square />停止</Button>
    </>}
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
    这次没有完成。<Button size="sm" variant="secondary" onClick={() => store.retryRun(activeRun.id)}><RotateCcw />重试</Button>
  </div>;

  // Rewriting history mid-run would race the run's own writes.
  const canRewrite = store.connected && !(activeRun && !runDone) && !loadingMessages;

  const pageTitle = view === 'chat' ? activeConversation?.title ?? '新任务' : '';
  const besideConversation = view === 'chat' && besideId !== store.activeConversationId ? store.conversations.find((item) => item.id === besideId) : undefined;
  const runningConversations = store.runs.filter((run) => !TERMINAL.includes(run.status)).map((run) => run.conversationId);
  // One open conversation reads better as a plain title; tabs appear from the second one.
  const showTabs = view === 'chat' && tabs.length > 1 && tabs.includes(store.activeConversationId);
  const connection = !store.connected
    ? <span className="inline-flex items-center gap-1.5 text-[12px] text-danger"><i className="size-1.5 rounded-full bg-danger" />后端没有连接</span>
    : null;

  return <TooltipProvider>
    <MarkDefs />
    <div className="flex h-full">
      <Sidebar view={view} onGo={go} mini={sideMini || narrow} onToggleMini={toggleMini}
        conversations={store.conversations} conversationsLoading={store.conversationsLoading}
        activeConversationId={store.activeConversationId} loadingConversationId={store.loadingMessagesConversationId}
        onOpenConversation={openConversation} onNewTask={newTask} creating={store.creatingConversation} onSearch={() => setPaletteOpen(true)}
        pendingMemories={pendingCount} username={username} subtitle={store.connected ? modelName : '后端没有连接'}
        theme={theme} onToggleTheme={toggleTheme} onSettings={() => setSheet('models')}
        pinned={store.pinned} archived={store.archived} unread={store.unread}
        running={runningConversations}
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
            <TimelineNav threadRef={threadRef} resetKey={store.activeConversationId} />
            <div ref={threadRef} aria-label="任务活动" className="min-h-0 flex-1 overflow-auto px-8 pt-2"
              onScroll={(event) => { if (restoredRef.current === store.activeConversationId) scrollPositions.current.set(store.activeConversationId, event.currentTarget.scrollTop); }}>
              <div className="mx-auto w-[min(720px,100%)] pb-8">
                {history.map((message) => <ConversationMessage key={message.id} role={message.role === 'user' ? 'user' : 'assistant'} content={message.content} username={username}
                  actions={canRewrite && message.id ? message.role === 'user'
                    ? <MessageAction label="修改后重新发送" onClick={() => { setEditing({ id: message.id, original: message.content }); setInput(message.content); }}><Pencil size={13} /></MessageAction>
                    : <>
                      <MessageAction label="从这里分叉出一个新对话" onClick={() => void store.forkFrom(message.id)}><GitBranch size={13} /></MessageAction>
                      <MessageAction label="分叉，并把前面的内容总结成一段" onClick={() => void store.forkFrom(message.id, true)}><GitBranchPlus size={13} /></MessageAction>
                    </> : undefined} />)}
                {loadingMessages && <p className="py-6 text-center text-[13px] text-fg-3" role="status">正在载入这段对话…</p>}
                {!messages.length && !activeEvents.length && !loadingMessages && <div className="pt-[16vh] text-center">
                  <Mark className="mx-auto mb-4 size-11" />
                  <h2 className="m-0 font-serif text-[24px] font-semibold text-heading">这次要做什么？</h2>
                  <p className="mt-2 text-[14px] text-fg-3">在下面说清楚目标，Atlas 会把过程和结果都放在这里。</p>
                </div>}
                <ConversationActivity events={activeEvents} store={store} username={username} setTab={showInspectorTab} />
                {working && !activeEvents.some((event) => event.type === 'message.delta' || event.type === 'tool.started') && <div className="my-5 flex items-center gap-3 text-[13px] text-fg-3" aria-label="Atlas 正在思考">
                  <Mark className="size-[26px]" working />正在想…
                </div>}
                {retryNote}
                {errorNote}
              </div>
            </div>
            <div className="px-8 pb-5">
              <div className="mx-auto w-[min(720px,100%)]">
                {queueStrip}
                <Composer {...composerBase} variant="dock" onSubmit={() => void submit(false)} placeholder={activeRun && !runDone ? '接着补充，会在这一步做完后发出…' : '接着说要做什么，/ 看命令，! 开头直接在终端运行…'} header={editBanner || runHeader || undefined} />
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
        {view === 'code' && <CodePage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
        {view === 'create' && <CreatePage onDraft={draft} onVoice={startVoice} apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} initialPrompt={createPrompt} />}
        {view === 'auto' && <AutomationPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
        {view === 'memory' && <MemoryPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} onPendingChange={setPendingCount} />}
        {view === 'skills' && <div className="screen"><SkillDiscoveryPage apiBaseUrl={store.apiBaseUrl} activeSkills={store.activeSkills} onApplySkill={(name) => store.activeSkills.includes(name) ? store.removeSkill(name) : store.applySkill(name)} /></div>}
      </main>
    </div>

    <Dialog open={Boolean(sheet)} onOpenChange={(open) => { if (!open) setSheet(null); }} label="设置"
      className="grid h-[min(720px,calc(100vh-48px))] w-[min(980px,calc(100vw-32px))] grid-cols-[210px_minmax(0,1fr)]">
      <nav aria-label="设置分类" className="bg-sunken px-2.5 py-5 shadow-[inset_-1px_0_0_var(--line)]">
        <h2 className="m-0 px-2.5 pb-3 font-serif text-[18px] font-semibold text-heading">设置</h2>
        {([['models', '模型与服务', SlidersHorizontal], ['profiles', '角色', UserCog], ['hooks', 'Hooks', Webhook], ['shortcuts', '快捷键', Keyboard], ['appearance', '外观与语音', Sun], ['plugins', '插件', Puzzle], ['notifications', '通知', Bell]] as Array<[SheetPane, string, typeof Bell]>).map(([pane, label, Icon]) =>
          <button key={pane} aria-current={sheet === pane} onClick={() => setSheet(pane)}
            className={cn('flex h-9 w-full items-center gap-2.5 rounded-[9px] px-2.5 text-left text-[13.5px] transition-colors', sheet === pane ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
            <Icon size={16} className={sheet === pane ? 'text-brand' : undefined} />{label}
          </button>)}
        <button onClick={() => { setSheet(null); setOnboardingOpen(true); }} className="mt-3 flex h-9 w-full items-center gap-2.5 rounded-[9px] px-2.5 text-left text-[13px] text-fg-3 hover:bg-hover hover:text-fg">
          <Sparkles size={16} />开始向导</button>
      </nav>
      <div className="relative min-h-0 overflow-auto px-8 pt-7 pb-8">
        <button aria-label="关闭设置" onClick={() => setSheet(null)} className="absolute top-4 right-4 grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><X size={17} /></button>
        {sheet === 'models' && <SettingsPage username={username} onSaveUsername={(value) => { const next = value.trim() || 'User'; setPref('username', next); setUsername(next); }} apiBaseUrl={store.apiBaseUrl} providerBaseUrl={store.providerBaseUrl} connected={store.connected} apiKeyConfigured={store.apiKeyConfigured} busy={store.settingsBusy} connectionTest={store.connectionTest} error={store.error} models={store.models} selectedModel={store.model} onBack={() => setSheet(null)} onSelectModel={(model) => void store.selectModel(model)} onSaveProvider={(baseUrl, apiKey) => store.saveProviderSettings(baseUrl, apiKey)} onAddModel={(model) => store.addCustomModel(model)} onTestConnection={(model) => void store.testModelConnection(model)} />}
        {sheet === 'appearance' && <section>
          <h3 className="m-0 text-[17px] font-semibold text-heading">外观与语音</h3>
          <p className="mt-1 mb-5 text-[13px] text-fg-3">只影响这台电脑。</p>
          <div role="radiogroup" aria-label="外观" className="mb-6 grid grid-cols-3 gap-3">
            {THEMES.map((item) => <button key={item.id} role="radio" aria-checked={theme === item.id} onClick={() => chooseTheme(item.id)}
              className={cn('card-surface rounded-2xl p-2.5 text-left transition-shadow', theme === item.id && 'shadow-[0_0_0_2px_var(--brand)]')}>
              <span className="block h-20 rounded-xl shadow-[inset_0_0_0_1px_var(--line)]" style={{ background: item.swatch }} />
              <b className="mt-2.5 block px-1 text-[13.5px] font-medium text-fg">{item.label}</b>
              <small className="block px-1 pb-0.5 text-[12px] text-fg-3">{item.hint}</small>
            </button>)}
          </div>
          <div className="set-list">
            <div className="set-row"><div>收起侧边栏<small>只显示图标，给内容更多空间</small></div><button className="switch" role="switch" aria-label="收起侧边栏" aria-checked={sideMini} onClick={toggleMini} /></div>
            <div className="set-row"><div>自动朗读新回复<small>用本机语音逐句读出 Atlas 的回答</small></div><button className="switch" role="switch" aria-label="自动朗读新回复" aria-checked={voiceOutput} onClick={toggleVoiceOutput} /></div>
          </div>
        </section>}
        {sheet === 'plugins' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">插件</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">给 Atlas 增加新的工具和能力。</p><PluginsPanel apiBaseUrl={store.apiBaseUrl} /></section>}
        {sheet === 'profiles' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">角色</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">把指令、模型、技能、工具和模式打包成一个角色，在输入框里一键切换。</p>
          <ProfilesPanel profiles={store.profiles} models={store.models} skills={store.skills} onChanged={() => void store.reloadProfiles()} /></section>}
        {sheet === 'shortcuts' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">快捷键</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">改成你顺手的组合键，只在这台电脑上生效。</p><ShortcutsPanel /></section>}
        {sheet === 'hooks' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">Hooks</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">在任务开始、用工具前后、完成或失败时运行你自己的命令。</p><HooksPanel /></section>}
        {sheet === 'notifications' && <section><h3 className="m-0 text-[17px] font-semibold text-heading">通知</h3><p className="mt-1 mb-5 text-[13px] text-fg-3">任务完成、需要确认时怎么提醒你。</p><NotificationsPanel apiBaseUrl={store.apiBaseUrl} /></section>}
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
    {activeConversation && <SideChat open={side.open} onClose={() => setSide({ open: false })} conversationId={activeConversation.id} model={store.model} initialQuestion={side.question} />}

    {toast && <div role="status" className="pop anim-pop fixed bottom-7 left-1/2 z-[80] -translate-x-1/2 rounded-xl px-4 py-2.5 text-[13.5px] text-fg">{toast}</div>}
  </TooltipProvider>;
}

function MessageAction({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return <Tip label={label}><button aria-label={label} onClick={onClick} className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg">{children}</button></Tip>;
}
