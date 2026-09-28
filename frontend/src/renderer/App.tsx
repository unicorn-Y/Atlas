import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { BookOpen, LayoutDashboard, Check, ChevronDown, ChevronRight, CircleHelp, FileText, Mic, MoreHorizontal, PanelRight, Paperclip, Pause, Play, Plus, Search, Send, Settings, Square, Volume2, X } from 'lucide-react';
import { useAtlasStore } from './store/useAtlasStore';
import styles from './App.module.css';
import ConversationActivity from './components/ConversationActivity';
import ConversationMessage from './components/ConversationMessage';
import SettingsPage from './pages/SettingsPage';
import SkillDiscoveryPage from './pages/SkillDiscoveryPage';
import ConsolePage from './pages/ConsolePage';

type InspectorTab = 'context' | 'artifacts' | 'activity' | 'skills';
type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  onresult: ((event: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

export default function App() {
  const [page, setPage] = useState<'chat' | 'console' | 'settings' | 'skills'>('chat');
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [modelOpen, setModelOpen] = useState(false);
  const [tab, setTab] = useState<InspectorTab>('context');
  const [selectedArtifact, setSelectedArtifact] = useState('');
  const [input, setInput] = useState('');
  const [toast, setToast] = useState('');
  const [attachments, setAttachments] = useState<string[]>([]);
  const [listening, setListening] = useState(false);
  const [voiceOutput, setVoiceOutput] = useState(() => localStorage.getItem('atlas.preference.voice-output') === 'true');
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const spokenSequenceRef = useRef(0);
  const spokenRunRef = useRef('');
  const speechBufferRef = useRef('');
  const [username, setUsername] = useState(() => localStorage.getItem('atlas.preference.username')?.trim() || 'User');
  const [maximized, setMaximized] = useState(false);
  const store = useAtlasStore();
  const activeConversation = store.conversations.find((item) => item.id === store.activeConversationId);
  const activeRun = store.runs.find((run) => run.id === store.activeRunId);
  const activeArtifacts = store.artifacts.filter((artifact) => artifact.runId === store.activeRunId);
  const activeEvents = activeRun?.events ?? [];
  const currentPlan = [...activeEvents].reverse().find((event) => event.type === 'run.plan.updated')?.data.plan as { subtasks?: unknown[] } | undefined;
  const planSteps = Array.isArray(currentPlan?.subtasks) ? currentPlan.subtasks.filter((step): step is { status?: string } => Boolean(step) && typeof step === 'object') : [];
  const completedPlanSteps = planSteps.filter((step) => step.status === 'completed').length;
  const messages = (store.conversationMessages[store.activeConversationId] ?? []).filter((message) => message.role === 'user' || message.role === 'assistant');

  useEffect(() => { void store.initialize(); }, []);
  useEffect(() => {
    if (store.connected && !store.conversationsLoading && !store.apiKeyConfigured) setPage('settings');
  }, [store.apiKeyConfigured, store.connected, store.conversationsLoading]);
  useEffect(() => window.atlasDesktop?.onMaximizeChange(setMaximized), []);
  useEffect(() => {
    if (spokenRunRef.current !== activeRun?.id) {
      spokenRunRef.current = activeRun?.id ?? '';
      spokenSequenceRef.current = 0;
      speechBufferRef.current = '';
    }
    if (!voiceOutput || !('speechSynthesis' in window)) return;
    for (const event of activeEvents) {
      if (event.sequence <= spokenSequenceRef.current) continue;
      spokenSequenceRef.current = event.sequence;
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
  }, [activeEvents, activeRun?.id, voiceOutput]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(''), 1800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!input.trim() && !attachments.length) return;
    void store.sendMessage(input, attachments);
    setInput('');
    setAttachments([]);
  };
  const addImages = (files: FileList | null) => {
    if (!files?.length) return;
    const selected = Array.from(files).filter((file) => ['image/png', 'image/jpeg', 'image/webp'].includes(file.type)).slice(0, 4 - attachments.length);
    if (!selected.length) { setToast('请选择 PNG、JPEG 或 WebP 图片'); return; }
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
    const speechWindow = window as typeof window & { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike };
    const Constructor = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
    if (!Constructor) { setToast('此设备的浏览器不支持语音识别'); return; }
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
    const lastReply = [...messages].reverse().find((message) => message.role === 'assistant')?.content;
    if (!lastReply || !('speechSynthesis' in window)) { setToast('当前没有可朗读的回复'); return; }
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(lastReply));
  };
  const toggleVoiceOutput = () => {
    const enabled = !voiceOutput;
    setVoiceOutput(enabled);
    localStorage.setItem('atlas.preference.voice-output', String(enabled));
    if (!enabled) { speechBufferRef.current = ''; window.speechSynthesis?.cancel(); }
  };
  const onInputKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
  };
  useEffect(() => () => { recognitionRef.current?.stop(); window.speechSynthesis?.cancel(); }, []);

  return <div className={styles.app}>
    <aside className={styles.sidebar}>
      <div className={styles.brand}><div className={styles.brandMark}>A</div><div><div className={styles.brandName}>Atlas</div><div className={styles.brandTag}>YOUR PERSONAL AGENT</div></div></div>
      <nav className={styles.navList} aria-label="主导航">
        <button className={`${styles.navItem} ${page === 'chat' ? styles.active : ''}`} onClick={() => setPage('chat')}><BookOpen /><span>对话</span></button>
        <button className={`${styles.navItem} ${page === 'skills' ? styles.active : ''}`} onClick={() => setPage('skills')}><Search /><span>技能发现</span></button>
        <button className={`${styles.navItem} ${page === 'console' ? styles.active : ''}`} onClick={() => setPage('console')}><LayoutDashboard /><span>控制台</span></button>
      </nav>
      <div className={styles.sectionLabel}>最近对话 <button aria-label="新建对话" disabled={store.creatingConversation} onClick={() => { setPage('chat'); void store.createConversation(); }}><Plus size={15} /></button></div>
      <div className={styles.historyList}>
        {store.conversations.map((conversation) => <button key={conversation.id} aria-current={conversation.id === store.activeConversationId ? 'page' : undefined} disabled={store.loadingMessagesConversationId === conversation.id} className={`${styles.historyItem} ${conversation.id === store.activeConversationId ? styles.historyCurrent : ''}`} onClick={() => void store.openConversation(conversation)}>
          {conversation.id === store.activeConversationId && <span className={styles.historyDot} />}{conversation.title}
        </button>)}
        {!store.conversations.length && <div className={styles.historyEmpty} role={store.conversationsLoading ? 'status' : undefined}>{store.conversationsLoading ? '正在加载对话…' : '暂无对话'}</div>}
      </div>
      <div className={styles.sidebarBottom}>
        <button className={`${styles.navItem} ${page === 'settings' ? styles.active : ''}`} onClick={() => setPage('settings')}><Settings /><span>设置</span></button>
        <div className={styles.connectionProfile}><i className={store.connected ? styles.connectedDot : ''} />{store.connected ? '后端已连接' : '后端未连接'}</div>
      </div>
    </aside>

    <main className={styles.main}>
      {page === 'settings' ? <SettingsPage username={username} onSaveUsername={(value) => { const next = value.trim() || 'User'; localStorage.setItem('atlas.preference.username', next); setUsername(next); }} apiBaseUrl={store.apiBaseUrl} providerBaseUrl={store.providerBaseUrl} connected={store.connected} apiKeyConfigured={store.apiKeyConfigured} busy={store.settingsBusy} connectionTest={store.connectionTest} error={store.error} models={store.models} selectedModel={store.model} onBack={() => setPage('chat')} onSelectModel={(model) => void store.selectModel(model)} onSaveProvider={(baseUrl, apiKey) => store.saveProviderSettings(baseUrl, apiKey)} onAddModel={(model) => store.addCustomModel(model)} onTestConnection={(model) => void store.testModelConnection(model)} /> : page === 'console' ? <div className={styles.settingsPage} aria-label="控制台容器"><header className={styles.settingsHeader}><div><h1>控制台</h1><p>项目、后台任务、插件与通知——Atlas 的长期记忆和后台都在这里。</p></div></header><ConsolePage apiBaseUrl={store.apiBaseUrl} /></div> : page === 'skills' ? <SkillDiscoveryPage apiBaseUrl={store.apiBaseUrl} activeSkills={store.activeSkills} onApplySkill={(name) => store.activeSkills.includes(name) ? store.removeSkill(name) : store.applySkill(name)} /> : <>
        <header className={styles.topbar}>
          <div className={styles.topbarTitle}>对话 <span>/</span> {activeConversation?.title ?? '新对话'}</div>
          <div className={styles.topbarActions}>
            <div className={styles.modelPickerWrap}><button className={styles.modelButton} disabled={!store.models.length} onClick={() => setModelOpen((value) => !value)}><i />{store.models.find((model) => model.id === store.model)?.name ?? '默认模型'}<ChevronDown size={14} /></button>
              {modelOpen && <div className={styles.modelMenu}>{store.models.map((model) => <button key={model.id} onClick={() => { void store.selectModel(model.id); setModelOpen(false); }}>{model.id === store.model && <Check size={14} />}{model.name ?? model.id}</button>)}</div>}
            </div>
            <button className={styles.iconButton} aria-label="切换上下文面板" onClick={() => setInspectorOpen((value) => !value)}><PanelRight /></button>
            {window.atlasDesktop?.platform !== 'darwin' && <div className={styles.desktopControls}><button aria-label="最小化窗口" onClick={() => window.atlasDesktop?.minimize()}>−</button><button aria-label="最大化窗口" onClick={() => window.atlasDesktop?.maximize()}>{maximized ? '❐' : '□'}</button><button aria-label="关闭窗口" onClick={() => window.atlasDesktop?.close()}>×</button></div>}
          </div>
        </header>

        <section className={styles.taskbar}>
          <div className={styles.taskIdentity}><div className={styles.eyebrow}>当前任务</div><div className={styles.taskTitle}>{activeRun?.title ?? activeConversation?.title ?? '新对话'}</div><div className={styles.taskSubtitle}>{activeRun ? `${activeRun.phase} · ${activeRun.status}` : activeConversation ? '在当前对话中继续与 Atlas 协作' : '新建对话以开始协作'}</div></div>
          <div className={styles.taskState}><i className={store.busy && !store.paused ? styles.stateWorking : ''} />{store.paused ? '已暂停' : store.busy ? '执行中' : activeRun?.status ?? '就绪'}</div>
          <div className={styles.taskRuntime}>{store.connected ? '已连接' : '后端未连接'}</div><div className={styles.taskSpacer} />
          <div className={styles.taskActions}><button className={styles.quietButton} aria-label="切换实时语音朗读" aria-pressed={voiceOutput} onClick={toggleVoiceOutput}><Volume2 size={15} />{voiceOutput ? '朗读已开' : '语音输出'}</button><button className={styles.quietButton} aria-label="朗读最近回复" onClick={readLastReply}><Volume2 size={15} />朗读</button><button className={styles.quietButton} disabled={!activeRun || !store.busy} onClick={() => store.togglePaused()}>{store.paused ? <Play /> : <Pause />}{store.paused ? '继续' : '暂停'}</button><button className={styles.quietButton} disabled={!activeRun || !store.busy} onClick={() => store.stopTask()}><Square />停止</button><button className={styles.iconButton} aria-label="新建对话" onClick={() => void store.createConversation()}><Plus /></button><button className={styles.iconButton} aria-label="更多任务操作" onClick={() => setToast(activeRun ? `Run ${activeRun.id}` : '当前没有运行中的任务')}><MoreHorizontal /></button></div>
        </section>

        {planSteps.length > 0 && <div className={styles.planStrip} aria-label="当前计划进度"><strong>{planSteps.length} 步 · {completedPlanSteps}/{planSteps.length} 完成</strong><div className={styles.planProgress}><i style={{ width: `${completedPlanSteps / planSteps.length * 100}%` }} /></div></div>}

        <div className={`${styles.workspace} ${inspectorOpen ? '' : styles.inspectorHidden}`}>
          <section className={styles.activityColumn} aria-label="任务活动">
            <div className={styles.activityScroll}><div className={styles.activityInner}>
              <div className={styles.conversationHeading}>任务对话</div>
              {messages.map((message) => <ConversationMessage key={message.id} role={message.role === 'user' ? 'user' : 'assistant'} content={message.content} username={username} status={message.role === 'assistant' ? '历史消息' : undefined} />)}
              {store.loadingMessagesConversationId === store.activeConversationId && <div className={styles.loadingConversation} role="status">正在载入对话历史…</div>}
              {!messages.length && !activeEvents.length && store.loadingMessagesConversationId !== store.activeConversationId && <div className={styles.emptyConversation}>{activeConversation ? '发送消息，开始这段对话。' : '新建对话，开始与 Atlas 协作。'}</div>}
              <ConversationActivity events={activeRun && ['completed', 'failed', 'cancelled'].includes(activeRun.status) ? activeEvents.filter((event) => !['run.started', 'message.delta', 'message.completed'].includes(event.type)) : activeEvents} store={store} username={username} setTab={setTab} />
              {store.error && <div className={styles.errorCard} role="alert"><span>{store.error}</span><button aria-label="关闭错误提示" onClick={store.dismissError}><X size={15} /></button></div>}
            </div></div>
            <div className={styles.composerZone}><form className={styles.composer} onSubmit={submit}><textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={onInputKey} placeholder="继续告诉 Atlas 要做什么…" rows={2} />{attachments.length > 0 && <div className={styles.attachmentStrip} aria-label="待发送图片">{attachments.map((image, index) => <div key={`${index}-${image.length}`}><img src={image} alt={`待发送图片 ${index + 1}`} /><button type="button" aria-label="移除图片" onClick={() => setAttachments((items) => items.filter((_, position) => position !== index))}>×</button></div>)}</div>}<input ref={fileInputRef} hidden type="file" accept="image/png,image/jpeg,image/webp" multiple capture="environment" onChange={(event) => { addImages(event.target.files); event.currentTarget.value = ''; }} /><div className={styles.composerBottom}><div className={styles.composerTools}><button type="button" aria-label="添加图片或使用摄像头" onClick={() => fileInputRef.current?.click()}><Paperclip /></button><button type="button" aria-label={listening ? '停止语音输入' : '开始语音输入'} aria-pressed={listening} onClick={toggleSpeechInput}><Mic /></button><span>{listening ? '正在听取语音…' : store.connected ? '已连接 Atlas 后端' : '后端未连接'}</span></div><button className={styles.sendButton} aria-label="发送消息" type="submit" disabled={!input.trim() && !attachments.length}><Send size={15} />发送</button></div></form><div className={styles.composerHint}>Atlas 可接收图像，语音识别和朗读由当前设备提供 <CircleHelp size={13} /></div></div>
          </section>

          {inspectorOpen && <aside className={styles.inspector}><div className={styles.inspectorHead}><div className={styles.tabs}>{(['context', 'artifacts', 'activity', 'skills'] as InspectorTab[]).map((name) => <button className={tab === name ? styles.tabActive : ''} key={name} onClick={() => setTab(name)}>{name === 'context' ? '上下文' : name === 'artifacts' ? '产物' : name === 'activity' ? '活动' : '技能'}</button>)}</div><button className={styles.inspectorClose} aria-label="收起检查器" onClick={() => setInspectorOpen(false)}><ChevronRight /></button></div>
            <div className={styles.inspectorContent}>
              {tab === 'context' && <><div className={styles.inspectorCaption}>当前任务</div><div className={styles.contextList}><div><span>对话</span><strong>{activeConversation?.title ?? '未选择'}</strong></div><div><span>模型</span><strong>{store.models.find((model) => model.id === store.model)?.name ?? '默认模型'}</strong></div><div><span>运行状态</span><strong>{activeRun?.status ?? '空闲'}</strong></div><div><span>执行阶段</span><strong>{activeRun?.phase ?? '—'}</strong></div><div><span>事件数</span><strong>{activeRun?.events.length ?? 0}</strong></div></div><div className={styles.inspectorCaption}>可用工具 · {store.tools.length}</div><div className={styles.toolList}>{store.tools.map((tool) => <span key={tool.name}>{tool.name.split('.')[0]}</span>)}</div><div className={styles.backendNote}>{activeRun ? `Run ${activeRun.id} · ${activeRun.status} · seq ${activeRun.lastEventSequence}` : store.connected ? 'API 已连接' : '等待 Atlas 后端服务'}</div></>}
              {tab === 'artifacts' && <><div className={styles.inspectorCaption}>任务产物 · {activeArtifacts.length}</div>{activeArtifacts.length ? <><div className={styles.artifactList}>{activeArtifacts.map((artifact) => <button className={selectedArtifact === artifact.id ? styles.artifactSelected : ''} key={artifact.id} onClick={() => setSelectedArtifact(artifact.id)}><FileText /><span><strong>{artifact.name}</strong><small>{artifact.type} · {artifact.path ?? 'Runtime artifact'}</small></span></button>)}</div>{activeArtifacts.find((item) => item.id === selectedArtifact) && <div className={styles.artifactPreview}><div>{activeArtifacts.find((item) => item.id === selectedArtifact)?.name}</div><p>{activeArtifacts.find((item) => item.id === selectedArtifact)?.summary}</p></div>}</> : <div className={styles.backendNote}>当前运行尚未报告可预览的文件产物。</div>}</>}
              {tab === 'activity' && <><div className={styles.inspectorCaption}>Agent Run 事件时间线</div>{activeRun ? <div className={styles.timeline}>{activeEvents.map((event) => <div key={event.id}><i />{new Date(event.timestamp).toLocaleTimeString()}　{event.type}<span>{String(event.data.name ?? event.data.phase ?? event.data.status ?? event.data.content ?? '')}</span></div>)}</div> : <div className={styles.backendNote}>当前对话活动将由 Runtime Event 提供。</div>}</>}
              {tab === 'skills' && <><div className={styles.inspectorCaption}>技能 · {store.skills.length}</div>{store.skills.length ? <div className={styles.skillList}>{store.skills.map((skill) => <div key={skill.name}><strong>{skill.name}</strong><small>{skill.category || 'general'}</small><p>{skill.description}</p></div>)}</div> : <div className={styles.backendNote}>后端连接后会显示可用技能。</div>}<div className={styles.inspectorCaption}>后续运行应用的 Skill</div><div aria-label="后续运行应用的 Skill">{store.activeSkills.join(' · ') || '未选择 Skill'}</div><div className={styles.inspectorCaption}>Agent 扩展 · {store.capabilities.length}</div>{store.capabilities.length ? <div className={styles.toolList}>{store.capabilities.map((capability) => <span key={capability.name} title={capability.description}>{capability.name}</span>)}</div> : <div className={styles.backendNote}>当前没有注册扩展能力。</div>}</>}
            </div>
          </aside>}
        </div>
      </>}
      {toast && <div role="status" className={styles.toast}>{toast}</div>}
    </main>
  </div>;
}
