import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  AudioLines, Bell, Brain, Code2, Copy, FileText, Home, MessageSquare, Minus, Moon, PanelLeft, PanelRight,
  Pause, Play, Plus, Puzzle, Repeat, Search, Settings, SlidersHorizontal, Sparkles, Square, Sun, Volume2, VolumeX, Wand2, X,
} from 'lucide-react';
import { useAtlasStore } from './store/useAtlasStore';
import ConversationActivity from './components/ConversationActivity';
import ConversationMessage from './components/ConversationMessage';
import Composer from './components/Composer';
import Mark, { MarkDefs } from './components/Mark';
import Palette, { type PaletteItem } from './components/Palette';
import VoiceOverlay, { getSpeechRecognition, type SpeechRecognitionLike } from './components/VoiceOverlay';
import SettingsPage from './pages/SettingsPage';
import SkillDiscoveryPage from './pages/SkillDiscoveryPage';
import MemoryPage from './pages/MemoryPage';
import AutomationPage from './pages/AutomationPage';
import CodePage from './pages/CodePage';
import CreatePage from './pages/CreatePage';
import { NotificationsPanel, PluginsPanel } from './pages/ConsolePage';
import { api, relativeTime } from './services/api';

type View = 'home' | 'chat' | 'code' | 'create' | 'auto' | 'memory' | 'skills';
type CanvasTab = 'context' | 'artifacts' | 'activity' | 'skills';
type SheetPane = 'models' | 'appearance' | 'plugins' | 'notifications';

const NAV: Array<{ view: View; label: string; icon: typeof Home }> = [
  { view: 'home', label: '今天', icon: Home },
  { view: 'chat', label: '对话', icon: MessageSquare },
  { view: 'code', label: '项目与代码', icon: Code2 },
  { view: 'create', label: '创作', icon: Wand2 },
  { view: 'auto', label: '自动化', icon: Repeat },
  { view: 'memory', label: '记忆与资料', icon: Brain },
  { view: 'skills', label: '技能发现', icon: Sparkles },
];
const SKY: Record<View, string> = { home: 'dawn', chat: 'dawn', memory: 'dawn', code: 'cool', auto: 'cool', skills: 'cool', create: 'warm' };
const TERMINAL = ['completed', 'failed', 'cancelled'];
const RUN_LABEL: Record<string, string> = { running: '正在处理', queued: '排队中', paused: '已暂停', completed: '已完成', failed: '出错了', cancelled: '已停止', waiting_approval: '等你确认' };
const HIDDEN_CANDIDATES = 'atlas.memory.hidden-candidates';
const pref = (key: string) => localStorage.getItem(`atlas.preference.${key}`);
const setPref = (key: string, value: string) => localStorage.setItem(`atlas.preference.${key}`, value);

function greeting() {
  const hour = new Date().getHours();
  return hour < 5 ? '夜深了' : hour < 11 ? '早上好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好';
}

export default function App() {
  const store = useAtlasStore();
  const [view, setView] = useState<View>('home');
  const [canvasOpen, setCanvasOpen] = useState(() => pref('canvas') === 'true');
  const [canvasTab, setCanvasTab] = useState<CanvasTab>('context');
  const [selectedArtifact, setSelectedArtifact] = useState('');
  const [theme, setTheme] = useState<'light' | 'dark'>(() => pref('theme') === 'dark' ? 'dark' : 'light');
  const [sideMini, setSideMini] = useState(() => pref('sidebar-mini') === 'true');
  const [sideOpen, setSideOpen] = useState(false);
  const [sheet, setSheet] = useState<SheetPane | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [input, setInput] = useState('');
  const [toast, setToast] = useState('');
  const [attachments, setAttachments] = useState<string[]>([]);
  const [listening, setListening] = useState(false);
  const [voiceOutput, setVoiceOutput] = useState(() => pref('voice-output') === 'true');
  const [username, setUsername] = useState(() => pref('username')?.trim() || 'User');
  const [maximized, setMaximized] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [hub, setHub] = useState<{ running?: boolean; task_count?: number } | null>(null);
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
  const modelName = store.models.find((model) => model.id === store.model)?.name ?? store.model ?? '默认模型';
  const loadingMessages = store.loadingMessagesConversationId === store.activeConversationId && Boolean(store.activeConversationId);
  const reply = useMemo(() => {
    const completed = [...activeEvents].reverse().find((event) => event.type === 'message.completed');
    if (completed?.data.content) return String(completed.data.content);
    return activeEvents.filter((event) => event.type === 'message.delta').map((event) => String(event.data.content ?? '')).join('');
  }, [activeEvents]);

  const go = useCallback((next: View) => { setView(next); setSideOpen(false); }, []);
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
    const body = document.body;
    body.dataset.theme = theme;
    body.dataset.view = view;
    body.dataset.sky = SKY[view];
    body.classList.toggle('canvas-open', canvasOpen);
    body.classList.toggle('side-mini', sideMini);
    body.classList.toggle('side-open', sideOpen);
    body.classList.toggle('voice-on', voiceOpen);
    document.querySelector('meta[name=theme-color]')?.setAttribute('content', theme === 'dark' ? '#0B1120' : '#E6ECF4');
  }, [theme, view, canvasOpen, sideMini, sideOpen, voiceOpen]);

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
    const timer = window.setTimeout(() => setToast(''), 1800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  // Keep the thread pinned to the bottom while new content streams in, unless the user scrolled up.
  useEffect(() => {
    const element = threadRef.current;
    if (!element) return;
    if (element.scrollHeight - element.scrollTop - element.clientHeight < 160) element.scrollTop = element.scrollHeight;
  }, [messages.length, activeEvents.length, view]);

  // Home summary: pending memories and the automation service.
  useEffect(() => {
    if (view !== 'home' || !store.connected) return;
    let hidden: string[] = [];
    try { hidden = JSON.parse(localStorage.getItem(HIDDEN_CANDIDATES) ?? '[]'); } catch { hidden = []; }
    api<Array<{ id: string }>>(store.apiBaseUrl, '/api/memory/candidates?status=pending')
      .then((items) => setPendingCount(items.filter((item) => !hidden.includes(item.id)).length)).catch(() => undefined);
    api<{ running?: boolean; task_count?: number }>(store.apiBaseUrl, '/api/hub/status').then(setHub).catch(() => setHub(null));
  }, [view, store.connected, store.apiBaseUrl]);

  const newTask = useCallback(() => {
    if (store.creatingConversation) return;
    go('chat');
    setInput('');
    setAttachments([]);
    void store.createConversation();
  }, [go, store]);

  const submit = async (fromHome: boolean) => {
    if (!input.trim() && !attachments.length) return;
    const text = input;
    const images = attachments;
    setInput('');
    setAttachments([]);
    recognitionRef.current?.stop();
    if (fromHome) {
      go('chat');
      // Home always starts something new, unless the open conversation is still empty.
      if (store.activeConversationId && messages.length) await store.createConversation(text.trim().slice(0, 40) || 'New conversation');
    }
    void store.sendMessage(text, images);
  };
  const addImages = (files: FileList | null) => {
    if (!files?.length) return;
    const selected = Array.from(files).filter((file) => ['image/png', 'image/jpeg', 'image/webp'].includes(file.type)).slice(0, 4 - attachments.length);
    if (!selected.length) { setToast('请选择 PNG、JPEG 或 WebP 图片，每条消息最多 4 张'); return; }
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
  const toggleTheme = () => setTheme((current) => { const next = current === 'dark' ? 'light' : 'dark'; setPref('theme', next); return next; });
  const toggleMini = () => setSideMini((current) => { setPref('sidebar-mini', String(!current)); return !current; });
  const toggleCanvas = (open?: boolean) => setCanvasOpen((current) => { const next = open ?? !current; setPref('canvas', String(next)); return next; });
  const showCanvasTab = (tab: CanvasTab) => { setCanvasTab(tab); toggleCanvas(true); };
  const openConversation = (conversation: (typeof store.conversations)[number]) => { go('chat'); void store.openConversation(conversation); };
  const startVoice = () => {
    if (!getSpeechRecognition()) { setToast('这台设备不支持语音识别，暂时无法通话'); return; }
    recognitionRef.current?.stop();
    window.speechSynthesis?.cancel();
    setVoiceOpen(true);
  };
  const draft = (text: string) => { go('chat'); setInput(text); void store.createConversation(); };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (voiceOpen) return;
      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.key.toLowerCase() === 'k') { event.preventDefault(); setPaletteOpen((value) => !value); }
      else if (mod && event.key.toLowerCase() === 'n') { event.preventDefault(); newTask(); }
      else if (mod && event.key === ',') { event.preventDefault(); setSheet((value) => value ? null : 'models'); }
      else if (event.key === 'Escape' && sheet && !paletteOpen) setSheet(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [newTask, sheet, paletteOpen, voiceOpen]);
  useEffect(() => () => { recognitionRef.current?.stop(); window.speechSynthesis?.cancel(); }, []);

  const paletteItems: PaletteItem[] = [
    { id: 'new', group: '操作', label: '新任务', hint: 'Ctrl N', icon: <Plus size={16} />, run: newTask },
    { id: 'voice', group: '操作', label: '开始语音通话', icon: <AudioLines size={16} />, run: startVoice },
    { id: 'theme', group: '操作', label: theme === 'dark' ? '切换到浅色' : '切换到深色', icon: theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />, run: toggleTheme },
    { id: 'settings', group: '操作', label: '设置', hint: 'Ctrl ,', icon: <Settings size={16} />, run: () => setSheet('models') },
    ...NAV.map(({ view: target, label, icon: Icon }) => ({ id: `go-${target}`, group: '前往', label, icon: <Icon size={16} />, run: () => go(target) })),
    ...store.conversations.slice(0, 30).map((conversation) => ({ id: `c-${conversation.id}`, group: '对话', label: conversation.title, hint: relativeTime(conversation.updated_at), run: () => openConversation(conversation) })),
  ];

  const composer = (fromHome: boolean) => <Composer
    value={input}
    onChange={setInput}
    onSubmit={() => void submit(fromHome)}
    placeholder={fromHome ? '继续告诉 Atlas 你想做什么，写代码、查资料、安排事情都可以' : '继续告诉 Atlas 要做什么…'}
    attachments={attachments}
    onRemoveAttachment={(index) => setAttachments((items) => items.filter((_, position) => position !== index))}
    onPickImages={addImages}
    listening={listening}
    onToggleMic={toggleSpeechInput}
    models={store.models}
    model={store.model}
    onSelectModel={(id) => void store.selectModel(id)}
    onManageModels={() => setSheet('models')}
    status={listening ? '正在听…' : store.connected ? '' : 'Atlas 后端未连接'}
    autoFocus
  />;
  const errorNote = store.error && <div className="error-note" role="alert"><span>{store.error}</span><button className="iconbtn" aria-label="关闭错误提示" onClick={store.dismissError}><X size={15} /></button></div>;

  const title: Record<View, ReactNode> = {
    home: '今天', chat: activeConversation?.title ?? '对话', code: '项目与代码', create: '创作', auto: '自动化', memory: '记忆与资料', skills: '技能发现',
  };
  const statusClass = !store.connected ? 'status off' : store.busy ? 'status busy' : 'status';
  const statusText = !store.connected ? '后端未连接' : store.busy ? (store.paused ? '已暂停' : '正在处理') : '已连接';

  return <>
    <MarkDefs />
    <div className="sky" aria-hidden="true"><i className="dawn" /><i className="cool" /><i className="warm" /><i className="night" /><i className="stars" /><i className="grain" /></div>
    <div className="app">
      <aside className="side glass" aria-label="侧边栏">
        <div className="brand">
          <Mark />
          <b>Atlas</b>
          <button className="iconbtn collapse" aria-label={sideMini ? '展开侧边栏' : '收起侧边栏'} onClick={toggleMini}><PanelLeft size={17} /></button>
        </div>
        <div className="newrow">
          <button className="newbtn" aria-label="新建对话" title="新任务 (Ctrl N)" disabled={store.creatingConversation} onClick={newTask}><Plus size={17} /><span>新任务</span><kbd>Ctrl N</kbd></button>
          <button className="search" aria-label="搜索和命令 (Ctrl K)" onClick={() => setPaletteOpen(true)}><Search size={16} /></button>
        </div>
        <nav className="nav" aria-label="主导航">
          {NAV.map(({ view: target, label, icon: Icon }) => <button key={target} aria-current={view === target ? 'page' : undefined} title={label} onClick={() => go(target)}>
            <Icon size={17} /><span>{label}</span>{target === 'memory' && pendingCount > 0 && <span className="count">{pendingCount}</span>}
          </button>)}
        </nav>
        <div className="recents">
          <h4>最近</h4>
          {store.conversations.map((conversation) => <button key={conversation.id} title={conversation.title} aria-current={conversation.id === store.activeConversationId && view === 'chat' ? 'page' : undefined} disabled={store.loadingMessagesConversationId === conversation.id} onClick={() => openConversation(conversation)}>
            <MessageSquare size={14} /><span>{conversation.title}</span>
          </button>)}
          {!store.conversations.length && <div className="empty-note" role={store.conversationsLoading ? 'status' : undefined}>{store.conversationsLoading ? '正在加载对话…' : '还没有对话'}</div>}
        </div>
        <div className="me">
          <span className="avatar" aria-hidden="true">{username.slice(0, 1).toUpperCase()}</span>
          <div><span>{username}</span><small>{store.connected ? modelName : '后端未连接'}</small></div>
          <button className="iconbtn" aria-label={theme === 'dark' ? '切换到浅色' : '切换到深色'} onClick={toggleTheme}>{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}</button>
          <button className="iconbtn" aria-label="设置" onClick={() => setSheet('models')}><Settings size={16} /></button>
        </div>
      </aside>

      <main className="main">
        <header className="top">
          <button className="iconbtn menu-toggle" aria-label="打开侧边栏" onClick={() => setSideOpen((value) => !value)}><PanelLeft size={17} /></button>
          <div className="title"><span>{title[view]}</span><span className={statusClass} role="status">{statusText}</span></div>
          <div className="spacer" />
          <button className="iconbtn" aria-label="切换实时语音朗读" aria-pressed={voiceOutput} title={voiceOutput ? '自动朗读已开' : '自动朗读新回复'} onClick={toggleVoiceOutput}>{voiceOutput ? <Volume2 size={17} /> : <VolumeX size={17} />}</button>
          <button className="iconbtn" aria-label="开始语音通话" title="语音通话" onClick={startVoice}><AudioLines size={17} /></button>
          {view === 'chat' && <button className="iconbtn" aria-label="切换上下文面板" aria-pressed={canvasOpen} onClick={() => toggleCanvas()}><PanelRight size={17} /></button>}
          {window.atlasDesktop && window.atlasDesktop.platform !== 'darwin' && <div className="winctl">
            <button aria-label="最小化窗口" onClick={() => window.atlasDesktop?.minimize()}><Minus size={15} /></button>
            <button aria-label="最大化窗口" onClick={() => window.atlasDesktop?.maximize()}>{maximized ? <Copy size={13} /> : <Square size={13} />}</button>
            <button className="x" aria-label="关闭窗口" onClick={() => window.atlasDesktop?.close()}><X size={16} /></button>
          </div>}
        </header>

        <div className="stage">
          {view === 'home' && <div className="screen home"><div className="home-inner">
            <div className="hello"><Mark /><h1>{greeting()}{username !== 'User' ? `，${username}` : ''}</h1></div>
            <p className="lede">对话、写代码、生成图像、安排日程 —— 说一句，剩下的交给 Atlas。</p>
            {composer(true)}
            {errorNote}
            <div className="section-h" style={{ marginTop: 32 }}><h2>能做什么</h2></div>
            <div className="tiles">
              <button className="tile" onClick={() => go('create')}><span className="ico brass"><Wand2 size={18} /></span><div><b>生成图像</b><small>出图、海报、插画</small></div></button>
              <button className="tile" onClick={() => go('code')}><span className="ico ether"><Code2 size={18} /></span><div><b>写代码 · 项目</b><small>建项目、改代码、查仓库</small></div></button>
              <button className="tile" onClick={() => go('auto')}><span className="ico ok"><Repeat size={18} /></span><div><b>自动化</b><small>定时任务、后台执行</small></div></button>
              <button className="tile" onClick={startVoice}><span className="ico brass"><AudioLines size={18} /></span><div><b>语音通话</b><small>像打电话一样对话</small></div></button>
              <button className="tile" onClick={() => go('memory')}><span className="ico ether"><Brain size={18} /></span><div><b>记忆与资料</b><small>长期记住、随时调用</small></div></button>
              <button className="tile" onClick={() => go('skills')}><span className="ico ok"><Puzzle size={18} /></span><div><b>技能发现</b><small>给 Atlas 装新本事</small></div></button>
            </div>
            {store.conversations.length > 0 && <>
              <div className="section-h"><h2>接着做</h2><button onClick={() => setPaletteOpen(true)}>全部对话</button></div>
              <div className="resume glass">
                {store.conversations.slice(0, 3).map((conversation) => <div key={conversation.id}>
                  <span className="ico ether"><MessageSquare size={17} /></span>
                  <div style={{ minWidth: 0 }}><p>{conversation.title}</p><small>{conversation.updated_at ? `${relativeTime(conversation.updated_at)}更新` : '对话'}</small></div>
                  <button className="btn" aria-label={`继续：${conversation.title}`} onClick={() => openConversation(conversation)}>继续</button>
                </div>)}
              </div>
            </>}
            {(pendingCount > 0 || hub) && <>
              <div className="section-h"><h2>在等你</h2></div>
              <div className="resume glass">
                {pendingCount > 0 && <div>
                  <span className="ico brass"><Brain size={17} /></span>
                  <div><p>{pendingCount} 条记忆等你确认</p><small>Atlas 从对话里发现的，确认后才会长期记住</small></div>
                  <button className="btn" onClick={() => go('memory')}>去确认</button>
                </div>}
                {hub && <div>
                  <span className={`ico ${hub.running ? 'ok' : 'dim'}`}><Repeat size={17} /></span>
                  <div><p>{hub.running ? `自动化运行中，${hub.task_count ?? 0} 个任务` : '自动化后台服务没有运行'}</p><small>{hub.running ? '到点会自动执行' : '启动后定时任务才会执行'}</small></div>
                  <button className="btn" onClick={() => go('auto')}>查看</button>
                </div>}
              </div>
            </>}
          </div></div>}

          {view === 'chat' && <div className="screen">
            <div className="thread" ref={threadRef} aria-label="任务活动"><div className="thread-inner">
              {messages.map((message) => <ConversationMessage key={message.id} role={message.role === 'user' ? 'user' : 'assistant'} content={message.content} username={username} status={message.role === 'assistant' ? '历史消息' : undefined} />)}
              {loadingMessages && <div className="empty-note" role="status">正在载入对话历史…</div>}
              {!messages.length && !activeEvents.length && !loadingMessages && <div className="thread-empty">
                <Mark /><h2>{activeConversation ? '这次要做什么？' : '开始一个新任务'}</h2>
                <p>{activeConversation ? '在下面说清楚目标，Atlas 会把过程和结果都放在这里。' : '点左上角的「新任务」，或直接在下面输入。'}</p>
              </div>}
              <ConversationActivity events={runDone ? activeEvents.filter((event) => !['run.started', 'message.delta', 'message.completed'].includes(event.type)) : activeEvents} store={store} username={username} setTab={showCanvasTab} />
              {store.busy && !store.paused && !activeEvents.some((event) => event.type === 'message.delta') && <div className="typing" aria-label="Atlas 正在思考"><i /><i /><i /></div>}
              {errorNote}
            </div></div>
            <div className="dock">
              {(activeRun || messages.length > 0) && <div className="runbar">
                {activeRun && (store.busy && !store.paused ? <span className="live-tag">{RUN_LABEL[activeRun.status] ?? '正在处理'}</span> : <span>{store.paused ? '已暂停' : RUN_LABEL[activeRun.status] ?? '就绪'}</span>)}
                {activeRun && <span className="phase">{activeRun.phase} · {activeRun.status}</span>}
                {planSteps.length > 0 && <span className="plan" aria-label="当前计划进度"><span className="meter"><i style={{ width: `${completedPlanSteps / planSteps.length * 100}%` }} /></span>{completedPlanSteps}/{planSteps.length} 步</span>}
                <span className="grow" />
                <button className="btn ghost" aria-label="朗读最近回复" onClick={readLastReply}><Volume2 size={14} />朗读</button>
                {activeRun && store.busy && <>
                  <button className="btn ghost" onClick={() => store.togglePaused()}>{store.paused ? <Play size={14} /> : <Pause size={14} />}{store.paused ? '继续' : '暂停'}</button>
                  <button className="btn ghost" onClick={() => store.stopTask()}><Square size={13} />停止</button>
                </>}
              </div>}
              {composer(false)}
            </div>
          </div>}

          {view === 'code' && <CodePage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
          {view === 'create' && <CreatePage onDraft={draft} onVoice={startVoice} apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
          {view === 'auto' && <AutomationPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} />}
          {view === 'memory' && <MemoryPage apiBaseUrl={store.apiBaseUrl} connected={store.connected} onToast={notify} onPendingChange={setPendingCount} />}
          {view === 'skills' && <div className="screen"><SkillDiscoveryPage apiBaseUrl={store.apiBaseUrl} activeSkills={store.activeSkills} onApplySkill={(name) => store.activeSkills.includes(name) ? store.removeSkill(name) : store.applySkill(name)} /></div>}

          <aside className="canvas glass" aria-label="上下文面板" aria-hidden={!(canvasOpen && view === 'chat')}>
            <div className="chead">
              <h3>任务面板</h3>
              <div className="tabs" role="tablist">{(['context', 'artifacts', 'activity', 'skills'] as CanvasTab[]).map((name) => <button role="tab" key={name} aria-selected={canvasTab === name} onClick={() => setCanvasTab(name)}>{name === 'context' ? '上下文' : name === 'artifacts' ? '产物' : name === 'activity' ? '活动' : '技能'}</button>)}</div>
              <span className="grow" />
              <button className="iconbtn" aria-label="收起检查器" onClick={() => toggleCanvas(false)}><X size={16} /></button>
            </div>
            <div className="cbody">
              {canvasTab === 'context' && <>
                <dl className="kv">
                  <div><dt>对话</dt><dd>{activeConversation?.title ?? '未选择'}</dd></div>
                  <div><dt>模型</dt><dd>{modelName}</dd></div>
                  <div><dt>运行状态</dt><dd>{activeRun ? RUN_LABEL[activeRun.status] ?? activeRun.status : '空闲'}</dd></div>
                  <div><dt>执行阶段</dt><dd>{activeRun?.phase ?? '—'}</dd></div>
                  <div><dt>事件数</dt><dd>{activeRun?.events.length ?? 0}</dd></div>
                </dl>
                <div className="cap">可用工具 {store.tools.length}</div>
                {store.tools.length ? <div className="chips">{store.tools.map((tool) => <span key={tool.name}>{tool.name.split('.')[0]}</span>)}</div> : <div className="note">后端连接后会列出 Atlas 能用的工具。</div>}
                <div className="cap">运行编号</div>
                <div className="note" style={{ fontFamily: 'var(--f-mono)', fontSize: 12 }}>{activeRun ? `${activeRun.id}，seq ${activeRun.lastEventSequence}` : store.connected ? '还没有运行' : '等待 Atlas 后端'}</div>
              </>}
              {canvasTab === 'artifacts' && <>
                <div className="cap">任务产物 {activeArtifacts.length}</div>
                {activeArtifacts.length ? <div className="alist">{activeArtifacts.map((artifact) => <button key={artifact.id} aria-pressed={selectedArtifact === artifact.id} onClick={() => setSelectedArtifact(artifact.id)}>
                  <span className="ico brass"><FileText size={16} /></span><span style={{ minWidth: 0 }}><b>{artifact.name}</b><small>{artifact.type}，{artifact.path ?? '运行时产物'}</small></span>
                </button>)}</div> : <div className="note">这次运行还没有产出文件。</div>}
                {activeArtifacts.find((item) => item.id === selectedArtifact) && <div className="note" style={{ marginTop: 12, color: 'var(--ink2)' }}>{activeArtifacts.find((item) => item.id === selectedArtifact)?.summary}</div>}
              </>}
              {canvasTab === 'activity' && <>
                <div className="cap">事件时间线</div>
                {activeRun ? <ul className="events">{activeEvents.map((event) => <li key={event.id}><span className="dot" /><div><b>{event.type}</b><small>{new Date(event.timestamp).toLocaleTimeString()}　{String(event.data.name ?? event.data.phase ?? event.data.status ?? event.data.content ?? '')}</small></div></li>)}</ul> : <div className="note">开始一次任务后，这里会逐条显示 Atlas 做了什么。</div>}
              </>}
              {canvasTab === 'skills' && <>
                <div className="cap">后续运行应用的 Skill</div>
                <div className="note" aria-label="后续运行应用的 Skill">{store.activeSkills.join('，') || '未选择 Skill'}</div>
                <div className="cap">已安装技能 {store.skills.length}</div>
                {store.skills.length ? <div className="skills">{store.skills.map((skill) => <div key={skill.name}><b>{skill.name}</b><small>{skill.category || 'general'}</small><p>{skill.description}</p></div>)}</div> : <div className="note">后端连接后会显示可用技能。</div>}
                <div className="cap">扩展能力 {store.capabilities.length}</div>
                {store.capabilities.length ? <div className="chips">{store.capabilities.map((capability) => <span key={capability.name} title={capability.description}>{capability.name}</span>)}</div> : <div className="note">当前没有注册扩展能力。</div>}
              </>}
            </div>
          </aside>
        </div>
      </main>
    </div>

    {sheet && <div className="scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) setSheet(null); }}>
      <div className="sheet glass" role="dialog" aria-modal="true" aria-label="设置">
        <nav aria-label="设置分类">
          <h2>设置</h2>
          {([['models', '模型与服务', SlidersHorizontal], ['appearance', '外观与语音', Sun], ['plugins', '插件', Puzzle], ['notifications', '通知', Bell]] as Array<[SheetPane, string, typeof Bell]>).map(([pane, label, Icon]) => <button key={pane} aria-current={sheet === pane} onClick={() => setSheet(pane)}><Icon size={16} />{label}</button>)}
        </nav>
        <div className="sheet-body">
          <button className="iconbtn close" aria-label="关闭设置" onClick={() => setSheet(null)}><X size={17} /></button>
          {sheet === 'models' && <SettingsPage username={username} onSaveUsername={(value) => { const next = value.trim() || 'User'; setPref('username', next); setUsername(next); }} apiBaseUrl={store.apiBaseUrl} providerBaseUrl={store.providerBaseUrl} connected={store.connected} apiKeyConfigured={store.apiKeyConfigured} busy={store.settingsBusy} connectionTest={store.connectionTest} error={store.error} models={store.models} selectedModel={store.model} onBack={() => setSheet(null)} onSelectModel={(model) => void store.selectModel(model)} onSaveProvider={(baseUrl, apiKey) => store.saveProviderSettings(baseUrl, apiKey)} onAddModel={(model) => store.addCustomModel(model)} onTestConnection={(model) => void store.testModelConnection(model)} />}
          {sheet === 'appearance' && <div className="set-pane">
            <h3>外观与语音</h3><p>只影响这台设备。</p>
            <div className="set-list">
              <div className="set-row"><div>深色模式<small>夜里用眼更舒服</small></div><button className="switch" role="switch" aria-label="深色模式" aria-checked={theme === 'dark'} onClick={toggleTheme} /></div>
              <div className="set-row"><div>收起侧边栏<small>只显示图标，给内容更多空间</small></div><button className="switch" role="switch" aria-label="收起侧边栏" aria-checked={sideMini} onClick={toggleMini} /></div>
              <div className="set-row"><div>自动朗读新回复<small>用本机语音逐句读出 Atlas 的回答</small></div><button className="switch" role="switch" aria-label="自动朗读新回复" aria-checked={voiceOutput} onClick={toggleVoiceOutput} /></div>
            </div>
          </div>}
          {sheet === 'plugins' && <div className="set-pane"><h3>插件</h3><p>给 Atlas 增加新的工具和能力。</p><PluginsPanel apiBaseUrl={store.apiBaseUrl} /></div>}
          {sheet === 'notifications' && <div className="set-pane"><h3>通知</h3><p>任务完成、需要确认时怎么提醒你。</p><NotificationsPanel apiBaseUrl={store.apiBaseUrl} /></div>}
        </div>
      </div>
    </div>}

    {paletteOpen && <div className="scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) setPaletteOpen(false); }}>
      <Palette items={paletteItems} onClose={() => setPaletteOpen(false)} />
    </div>}

    {voiceOpen && <VoiceOverlay
      onClose={(toChat) => { setVoiceOpen(false); if (toChat) go('chat'); }}
      onSend={(text) => { if (view !== 'chat') setView('chat'); void store.sendMessage(text); }}
      runId={store.activeRunId ?? null}
      reply={reply}
      runDone={runDone}
      modelName={modelName}
    />}

    {toast && <div role="status" className="toast">{toast}</div>}
  </>;
}
