import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react';
import { BookOpen, Check, ChevronDown, ChevronRight, CircleHelp, FileText, Mic, MoreHorizontal, PanelRight, Paperclip, Pause, Play, Plus, Send, Settings, Square, X } from 'lucide-react';
import { useAtlasStore } from './store/useAtlasStore';
import styles from './App.module.css';
import ConversationActivity from './components/ConversationActivity';
import ConversationMessage from './components/ConversationMessage';
import SettingsPage from './pages/SettingsPage';

type InspectorTab = 'context' | 'artifacts' | 'activity';

export default function App() {
  const [page, setPage] = useState<'chat' | 'settings'>('chat');
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [modelOpen, setModelOpen] = useState(false);
  const [tab, setTab] = useState<InspectorTab>('context');
  const [selectedArtifact, setSelectedArtifact] = useState('');
  const [input, setInput] = useState('');
  const [toast, setToast] = useState('');
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
  useEffect(() => window.atlasDesktop?.onMaximizeChange(setMaximized), []);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(''), 1800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!input.trim()) return;
    void store.sendMessage(input);
    setInput('');
  };
  const onInputKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
  };

  return <div className={styles.app}>
    <aside className={styles.sidebar}>
      <div className={styles.brand}><div className={styles.brandMark}>A</div><div><div className={styles.brandName}>Atlas</div><div className={styles.brandTag}>YOUR PERSONAL AGENT</div></div></div>
      <nav className={styles.navList} aria-label="主导航">
        <button className={`${styles.navItem} ${page === 'chat' ? styles.active : ''}`} onClick={() => setPage('chat')}><BookOpen /><span>对话</span></button>
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
      {page === 'settings' ? <SettingsPage username={username} onSaveUsername={(value) => { const next = value.trim() || 'User'; localStorage.setItem('atlas.preference.username', next); setUsername(next); }} apiBaseUrl={store.apiBaseUrl} providerBaseUrl={store.providerBaseUrl} connected={store.connected} apiKeyConfigured={store.apiKeyConfigured} busy={store.settingsBusy} connectionTest={store.connectionTest} error={store.error} models={store.models} selectedModel={store.model} onBack={() => setPage('chat')} onSelectModel={(model) => void store.selectModel(model)} onSaveProvider={(baseUrl, apiKey) => store.saveProviderSettings(baseUrl, apiKey)} onAddModel={(model) => store.addCustomModel(model)} onTestConnection={(model) => void store.testModelConnection(model)} /> : <>
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
          <div className={styles.taskActions}><button className={styles.quietButton} disabled={!activeRun || !store.busy} onClick={() => store.togglePaused()}>{store.paused ? <Play /> : <Pause />}{store.paused ? '继续' : '暂停'}</button><button className={styles.quietButton} disabled={!activeRun || !store.busy} onClick={() => store.stopTask()}><Square />停止</button><button className={styles.iconButton} aria-label="新建对话" onClick={() => void store.createConversation()}><Plus /></button><button className={styles.iconButton} aria-label="更多任务操作" onClick={() => setToast(activeRun ? `Run ${activeRun.id}` : '当前没有运行中的任务')}><MoreHorizontal /></button></div>
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
            <div className={styles.composerZone}><form className={styles.composer} onSubmit={submit}><textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={onInputKey} placeholder="继续告诉 Atlas 要做什么…" rows={2} /><div className={styles.composerBottom}><div className={styles.composerTools}><button type="button" aria-label="添加附件" onClick={() => setToast('附件功能尚未配置')}><Paperclip /></button><button type="button" aria-label="语音输入" onClick={() => setToast('语音输入尚未配置')}><Mic /></button><span>{store.connected ? '已连接 Atlas 后端' : '后端未连接'}</span></div><button className={styles.sendButton} aria-label="发送消息" type="submit" disabled={!input.trim()}><Send size={15} />发送</button></div></form><div className={styles.composerHint}>Atlas 会在当前任务上下文中继续工作 <CircleHelp size={13} /></div></div>
          </section>

          {inspectorOpen && <aside className={styles.inspector}><div className={styles.inspectorHead}><div className={styles.tabs}>{(['context', 'artifacts', 'activity'] as InspectorTab[]).map((name) => <button className={tab === name ? styles.tabActive : ''} key={name} onClick={() => setTab(name)}>{name === 'context' ? '上下文' : name === 'artifacts' ? '产物' : '活动'}</button>)}</div><button className={styles.inspectorClose} aria-label="收起检查器" onClick={() => setInspectorOpen(false)}><ChevronRight /></button></div>
            <div className={styles.inspectorContent}>
              {tab === 'context' && <><div className={styles.inspectorCaption}>当前任务</div><div className={styles.contextList}><div><span>对话</span><strong>{activeConversation?.title ?? '未选择'}</strong></div><div><span>模型</span><strong>{store.models.find((model) => model.id === store.model)?.name ?? '默认模型'}</strong></div><div><span>运行状态</span><strong>{activeRun?.status ?? '空闲'}</strong></div><div><span>执行阶段</span><strong>{activeRun?.phase ?? '—'}</strong></div><div><span>事件数</span><strong>{activeRun?.events.length ?? 0}</strong></div></div><div className={styles.inspectorCaption}>可用工具 · {store.tools.length}</div><div className={styles.toolList}>{store.tools.map((tool) => <span key={tool.name}>{tool.name.split('.')[0]}</span>)}</div><div className={styles.backendNote}>{activeRun ? `Run ${activeRun.id} · ${activeRun.status} · seq ${activeRun.lastEventSequence}` : store.connected ? 'API 已连接' : '等待 Atlas 后端服务'}</div></>}
              {tab === 'artifacts' && <><div className={styles.inspectorCaption}>任务产物 · {activeArtifacts.length}</div>{activeArtifacts.length ? <><div className={styles.artifactList}>{activeArtifacts.map((artifact) => <button className={selectedArtifact === artifact.id ? styles.artifactSelected : ''} key={artifact.id} onClick={() => setSelectedArtifact(artifact.id)}><FileText /><span><strong>{artifact.name}</strong><small>{artifact.type} · {artifact.path ?? 'Runtime artifact'}</small></span></button>)}</div>{activeArtifacts.find((item) => item.id === selectedArtifact) && <div className={styles.artifactPreview}><div>{activeArtifacts.find((item) => item.id === selectedArtifact)?.name}</div><p>{activeArtifacts.find((item) => item.id === selectedArtifact)?.summary}</p></div>}</> : <div className={styles.backendNote}>当前运行尚未报告可预览的文件产物。</div>}</>}
              {tab === 'activity' && <><div className={styles.inspectorCaption}>Agent Run 事件时间线</div>{activeRun ? <div className={styles.timeline}>{activeEvents.map((event) => <div key={event.id}><i />{new Date(event.timestamp).toLocaleTimeString()}　{event.type}<span>{String(event.data.name ?? event.data.phase ?? event.data.status ?? event.data.content ?? '')}</span></div>)}</div> : <div className={styles.backendNote}>当前对话活动将由 Runtime Event 提供。</div>}</>}
            </div>
          </aside>}
        </div>
      </>}
      {toast && <div role="status" className={styles.toast}>{toast}</div>}
    </main>
  </div>;
}
