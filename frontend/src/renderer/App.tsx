import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react';
import {
  Activity, Archive, Bell, BookOpen, Bot, Check, ChevronDown, ChevronRight,
  CircleHelp, FileText, Folder, LayoutDashboard, Mic, MoreHorizontal,
  PanelRight, Paperclip, Pause, Play, Plus, Search, Send, Settings, Shield, Square,
  Wrench, X,
} from 'lucide-react';
import { useAtlasStore } from './store/useAtlasStore';
import type { AgentEvent } from '../types/runtime';
import styles from './App.module.css';

type InspectorTab = 'context' | 'artifacts' | 'activity';
export default function App() {
  const [planOpen, setPlanOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [capabilitiesOpen, setCapabilitiesOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [tab, setTab] = useState<InspectorTab>('context');
  const [selectedArtifact, setSelectedArtifact] = useState('');
  const [input, setInput] = useState('');
  const [toast, setToast] = useState('');
  const [approvalDetails, setApprovalDetails] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const store = useAtlasStore();
  const activeConversation = store.conversations.find((item) => item.id === store.activeConversationId);
  const activeRun = store.runs.find((run) => run.id === store.activeRunId);
  const activeArtifacts = store.artifacts.filter((artifact) => artifact.runId === store.activeRunId);
  const activeEvents = activeRun?.events ?? [];

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
  const pauseTask = () => {
    store.togglePaused();
  };
  const stopTask = () => {
    store.stopTask();
  };
  return <div className={styles.app}>
    <aside className={styles.sidebar}>
      <div className={styles.brand}><div className={styles.brandMark}>A</div><div><div className={styles.brandName}>Atlas</div><div className={styles.brandTag}>YOUR PERSONAL AGENT</div></div></div>
      <nav className={styles.navList} aria-label="主导航">
        <button className={`${styles.navItem} ${styles.active}`}><BookOpen /><span>对话</span></button>
        <button className={styles.navItem} onClick={() => setToast('输入关键词即可搜索消息')}><Search /><span>搜索</span></button>
        <button className={styles.navItem} onClick={() => setCapabilitiesOpen(true)}><Wrench /><span>能力中心</span><ChevronRight className={styles.navChevron} /></button>
        <button className={styles.navItem} onClick={() => setToast('项目空间已就绪')}><Folder /><span>项目空间</span></button>
      </nav>
      <div className={styles.sectionLabel}>最近对话 <button aria-label="新建对话" onClick={() => setToast('新对话将在下一条消息发送后创建')}><Plus size={15} /></button></div>
      <div className={styles.historyList}>
        {store.conversations.map((conversation, index) => <button key={conversation.id}
          className={`${styles.historyItem} ${conversation.id === store.activeConversationId ? styles.historyCurrent : ''}`}
          onClick={() => void store.openConversation(conversation)}>
          {index === 0 && <span className={styles.historyDot} />}{conversation.title}
        </button>)}
        {!store.conversations.length && <><button className={`${styles.historyItem} ${styles.historyCurrent}`}><span className={styles.historyDot} />MemoryOS Protected State</button><button className={styles.historyItem}>Recall 路径复核</button><button className={styles.historyItem}>SQLite 迁移方案</button></>}
      </div>
      <div className={styles.sidebarBottom}>
        <button className={styles.navItem} onClick={() => setToast('设置面板即将开放')}><Settings /><span>设置</span></button>
        <div className={styles.userProfile}><div className={styles.userAvatar}>L</div><div><div className={styles.userName}>Lin</div><div className={styles.userWorkspace}>Personal workspace</div></div><MoreHorizontal size={17} /></div>
      </div>
    </aside>

    <main className={styles.main}>
      <header className={styles.topbar}>
        <div className={styles.topbarTitle}>对话 <span>/</span> {activeConversation?.title ?? '新对话'}</div>
        <div className={styles.topbarActions}>
          <div className={styles.modelPickerWrap}><button className={styles.modelButton} onClick={() => setModelOpen((value) => !value)}><i />{store.models.find((model) => model.id === store.model)?.name ?? 'GPT-5.6 Luna'}<ChevronDown size={14} /></button>
            {modelOpen && <div className={styles.modelMenu}>{(store.models.length ? store.models : [{ id: store.model, name: 'GPT-5.6 Luna' }]).map((model) => <button key={model.id} onClick={() => { void store.selectModel(model.id); setModelOpen(false); }}>{model.id === store.model && <Check size={14} />}{model.name ?? model.id}</button>)}</div>}
          </div>
          <button className={styles.iconButton} aria-label="搜索" onClick={() => setToast('搜索会话和消息')}><Search /></button>
          <button className={styles.iconButton} aria-label="通知" onClick={() => setToast('没有新的通知')}><Bell /></button>
          <button className={styles.iconButton} aria-label="切换上下文面板" onClick={() => setInspectorOpen((value) => !value)}><PanelRight /></button>
          <button className={styles.avatarButton} aria-label="能力中心" onClick={() => setCapabilitiesOpen(true)}>A</button>
          {window.atlasDesktop?.platform !== 'darwin' && <div className={styles.desktopControls}><button aria-label="最小化窗口" onClick={() => window.atlasDesktop?.minimize()}>−</button><button aria-label="最大化窗口" onClick={() => window.atlasDesktop?.maximize()}>{maximized ? '❐' : '□'}</button><button aria-label="关闭窗口" onClick={() => window.atlasDesktop?.close()}>×</button></div>}
        </div>
      </header>

      <section className={styles.taskbar}>
        <div className={styles.taskIdentity}><div className={styles.eyebrow}>当前任务</div><div className={styles.taskTitle}>{activeRun?.title ?? activeConversation?.title ?? 'Atlas 任务'}</div><div className={styles.taskSubtitle}>{activeRun ? `${activeRun.phase} · ${activeRun.status}` : '在当前工作区继续与 Atlas 协作'}</div></div>
        <div className={styles.taskState}><i className={store.busy && !store.paused ? styles.stateWorking : ''} />{store.paused ? '已暂停' : store.busy ? '执行中' : activeRun?.status ?? '就绪'}</div>
        <div className={styles.taskRuntime}>{store.mode === 'backend' ? '已连接' : 'Mock 模式'}</div><div className={styles.taskSpacer} />
        <div className={styles.taskActions}><button className={styles.quietButton} disabled={!activeRun || !store.busy} onClick={pauseTask}>{store.paused ? <Play /> : <Pause />}{store.paused ? '继续' : '暂停'}</button><button className={styles.quietButton} disabled={!activeRun || !store.busy} onClick={stopTask}><Square />停止</button><button className={styles.iconButton} aria-label="更多任务操作" onClick={() => setToast('更多任务操作')}><MoreHorizontal /></button></div>
      </section>
      <div className={styles.planStrip}><button className={styles.planLink} aria-expanded={planOpen} onClick={() => setPlanOpen((value) => !value)}><strong>计划</strong><span>5 步 · 3/5 完成</span><ChevronRight className={planOpen ? styles.rotated : ''} size={15} /></button><div className={styles.planProgress}><i /></div></div>
      {planOpen && <div className={styles.planPanel}><span className={styles.stepDone}><Check />阅读规格</span><span className={styles.stepDone}><Check />检查现有实现</span><span className={styles.stepActive}>• 修复 Recall Propagation</span><span>4　运行测试</span><span>5　审查结果</span></div>}

      <div className={`${styles.workspace} ${inspectorOpen ? '' : styles.inspectorHidden}`}>
        <section className={styles.activityColumn} aria-label="任务活动">
          <div className={styles.activityScroll}><div className={styles.activityInner}>
            <div className={styles.conversationHeading}>任务对话</div>
            {(store.conversationMessages[store.activeConversationId] ?? []).filter((message) => message.role === 'user' || message.role === 'assistant').map((message) => message.role === 'user'
              ? <div className={styles.userMessage} key={message.id}><div className={styles.userBubble}>{message.content}</div><div className={styles.userAvatar}>L</div></div>
              : <div className={styles.assistantMessage} key={message.id}><div className={styles.assistantAvatar}>A</div><div className={styles.messageBody}><div className={styles.messageMeta}><strong>Atlas</strong><span>历史消息</span></div><div className={styles.messageText}>{message.content}</div></div></div>)}
            {renderEventList(activeRun && ['completed', 'failed', 'cancelled'].includes(activeRun.status)
              ? activeEvents.filter((event) => !['run.started', 'message.delta', 'message.completed'].includes(event.type))
              : activeEvents, store, setTab, setApprovalDetails, approvalDetails)}
            {store.error && <div className={styles.errorCard}><span>{store.error}</span><button onClick={store.dismissError}><X size={15} /></button></div>}
          </div></div>
          <div className={styles.composerZone}><form className={styles.composer} onSubmit={submit}><textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={onInputKey} placeholder="继续告诉 Atlas 要做什么…" rows={2} /><div className={styles.composerBottom}><div className={styles.composerTools}><button type="button" aria-label="添加附件" onClick={() => setToast('附件功能即将开放')}><Paperclip /></button><button type="button" aria-label="语音输入" onClick={() => setToast('语音输入即将开放')}><Mic /></button><span>{store.mode === 'mock' ? 'Mock 运行模式' : '已连接 Atlas 后端'}</span></div><button className={styles.sendButton} aria-label="发送消息" type="submit" disabled={!input.trim()}><Send size={15} />发送</button></div></form><div className={styles.composerHint}>Atlas 会在当前任务上下文中继续工作 <CircleHelp size={13} /></div></div>
        </section>

        {inspectorOpen && <aside className={styles.inspector}><div className={styles.inspectorHead}><div className={styles.tabs}>{(['context', 'artifacts', 'activity'] as InspectorTab[]).map((name) => <button className={tab === name ? styles.tabActive : ''} key={name} onClick={() => setTab(name)}>{name === 'context' ? '上下文' : name === 'artifacts' ? '产物' : '活动'}</button>)}</div><button className={styles.inspectorClose} aria-label="收起检查器" onClick={() => setInspectorOpen(false)}><ChevronRight /></button></div>
          <div className={styles.inspectorContent}>
            {tab === 'context' && <><div className={styles.inspectorCaption}>当前任务</div><div className={styles.contextList}><div><span>项目</span><strong>Atlas</strong></div><div><span>工作目录</span><strong>D:\Atlas</strong></div><div><span>模型</span><strong>{store.models.find((model) => model.id === store.model)?.name ?? 'GPT-5.6 Luna'}</strong></div><div><span>运行状态</span><strong>{activeRun?.status ?? '空闲'}</strong></div><div><span>执行阶段</span><strong>{activeRun?.phase ?? '—'}</strong></div><div><span>事件数</span><strong>{activeRun?.events.length ?? 0}</strong></div></div><div className={styles.inspectorCaption}>可用工具</div><div className={styles.toolList}>{(store.tools.length ? store.tools.map((tool) => tool.name.split('.')[0]) : ['Terminal', 'Files', 'Git', 'Browser']).map((tool) => <span key={tool}>{tool}</span>)}</div><div className={styles.backendNote}>{activeRun ? `Run ${activeRun.id} · ${activeRun.status} · seq ${activeRun.lastEventSequence}` : store.mode === 'backend' ? 'API 已连接' : '等待后端服务，当前使用本地 Mock 数据'}</div></>}
            {tab === 'artifacts' && <><div className={styles.inspectorCaption}>任务产物 · {activeArtifacts.length}</div>{activeArtifacts.length ? <><div className={styles.artifactList}>{activeArtifacts.map((artifact) => <button className={selectedArtifact === artifact.id ? styles.artifactSelected : ''} key={artifact.id} onClick={() => setSelectedArtifact(artifact.id)}><FileText /><span><strong>{artifact.name}</strong><small>{artifact.type} · {artifact.path ?? 'Runtime artifact'}</small></span></button>)}</div>{activeArtifacts.find((item) => item.id === selectedArtifact) && <div className={styles.artifactPreview}><div>{activeArtifacts.find((item) => item.id === selectedArtifact)?.name}</div><p>{activeArtifacts.find((item) => item.id === selectedArtifact)?.summary}</p></div>}</> : <div className={styles.backendNote}>当前运行尚未报告可预览的文件产物。</div>}</>}
            {tab === 'activity' && <><div className={styles.inspectorCaption}>Agent Run 事件时间线</div>{activeRun ? <div className={styles.timeline}>{activeEvents.map((event) => <div key={event.id}><i />{new Date(event.timestamp).toLocaleTimeString()}　{event.type}<span>{String(event.data.name ?? event.data.phase ?? event.data.status ?? event.data.content ?? '')}</span></div>)}</div> : <div className={styles.backendNote}>当前对话活动将由 Runtime Event 提供。</div>}</>}
          </div>
        </aside>}
      </div>

      {capabilitiesOpen && <div className={styles.popoverBackdrop} onClick={() => setCapabilitiesOpen(false)}><section className={styles.capabilityPopover} role="dialog" aria-label="能力中心" onClick={(event) => event.stopPropagation()}><div className={styles.capabilityHead}>能力中心<button onClick={() => setCapabilitiesOpen(false)} aria-label="关闭"><X size={17} /></button></div><div className={styles.capabilityGrid}>{[[Folder, '文件'], [BookOpen, '记忆'], [Wrench, '工具'], [LayoutDashboard, '自动化'], [Bot, '模型'], [Archive, '项目']].map(([Icon, label]) => { const TileIcon = Icon as typeof Folder; return <button key={String(label)} onClick={() => setToast(`${String(label)}能力已就绪`)}><TileIcon /><span>{String(label)}</span></button>; })}</div><div className={styles.capabilityFoot}>我的智能体　·　模板中心　·　MCP 服务</div></section></div>}
      {toast && <div role="status" className={styles.toast}>{toast}</div>}
    </main>
  </div>;
}

function renderEventList(
  events: AgentEvent[],
  store: ReturnType<typeof useAtlasStore.getState>,
  setTab: (value: InspectorTab) => void,
  setApprovalDetails: (value: (open: boolean) => boolean) => void,
  approvalDetails: boolean,
) {
  const result: React.ReactNode[] = [];
  let deltaBuffer: { content: string; ids: string[] } | null = null;

  const flushDelta = () => {
    if (!deltaBuffer) return;
    const merged = deltaBuffer;
    result.push(
      <div className={styles.assistantMessage} key={merged.ids[0]}>
        <div className={styles.assistantAvatar}>A</div>
        <div className={styles.messageBody}>
          <div className={styles.messageMeta}><strong>Atlas</strong><span>实时输出</span></div>
          <div className={styles.messageText}>{merged.content}</div>
        </div>
      </div>
    );
    deltaBuffer = null;
  };

  for (const event of events) {
    if (event.type === 'message.delta') {
      const chunk = String(event.data.content ?? '');
      if (deltaBuffer) {
        deltaBuffer.content += chunk;
        deltaBuffer.ids.push(event.id);
      } else {
        deltaBuffer = { content: chunk, ids: [event.id] };
      }
      continue;
    }
    // Non-delta event: flush any accumulated delta first
    if (event.type !== 'message.completed') {
      flushDelta();
    } else {
      // message.completed replaces accumulated deltas with final content
      const finalContent = String(event.data.content ?? (deltaBuffer?.content ?? ''));
      deltaBuffer = null;
      result.push(
        <div className={styles.assistantMessage} key={event.id}>
          <div className={styles.assistantAvatar}>A</div>
          <div className={styles.messageBody}>
            <div className={styles.messageMeta}><strong>Atlas</strong><span>回复完成</span></div>
            <div className={styles.messageText}>{finalContent}</div>
          </div>
        </div>
      );
      continue;
    }
    result.push(renderRuntimeEvent(event, store, setTab, setApprovalDetails, approvalDetails));
  }
  flushDelta(); // flush any trailing deltas
  return result;
}

function renderRuntimeEvent(
  event: AgentEvent,
  store: ReturnType<typeof useAtlasStore.getState>,
  setTab: (value: InspectorTab) => void,
  setApprovalDetails: (value: (open: boolean) => boolean) => void,
  approvalDetails: boolean,
) {
  const data = event.data;
  if (event.type === 'run.started' && typeof data.content === 'string') return <div className={styles.userMessage} key={event.id}><div className={styles.userBubble}>{data.content}</div><div className={styles.userAvatar}>L</div></div>;
  // message.delta and message.completed are handled by renderEventList
  if (event.type === 'message.delta' || event.type === 'message.completed') return null;
  if (event.type === 'tool.started' || event.type === 'tool.completed') return <details className={styles.activityCard} key={event.id} open={event.type === 'tool.started'}><summary><span className={styles.activityIcon}><Activity /></span><span>{String(data.name ?? 'Tool')} · {event.type === 'tool.started' ? '执行中' : '已完成'}</span><span className={styles.activityMeta}>{event.type === 'tool.started' ? '运行中' : 'Runtime'}</span></summary><div className={styles.activityDetail}><span>工具与结果</span><span>{JSON.stringify(data.result ?? data.arguments ?? {})}</span></div></details>;
  if (event.type === 'artifact.updated') return <div className={styles.fileChange} key={event.id}><div className={styles.fileHead}><FileText /><div><strong>{String(data.name ?? data.path ?? 'Artifact')}</strong><small>{String(data.artifact_type ?? 'file')} · Runtime 更新</small></div></div><p>{String(data.summary ?? data.change ?? '')}</p><button className={styles.quietButton} onClick={() => setTab('artifacts')}>在产物中查看</button></div>;
  if (event.type === 'approval.required') {
    const response = store.getRun(event.runId)?.events.find((item) => item.type === 'approval.responded' && (item.data.event_id === event.id || item.data.approval_id === data.approval_id));
    const choice = response?.data.choice;
    const toolName = String(data.tool ?? data.name ?? '未知工具');
    return <div className={styles.approvalCard} key={event.id}><div className={styles.approvalTitle}><Shield size={16} />需要你的确认 <span>{toolName}</span></div><div className={styles.approvalCopy}>{String(data.description ?? `Agent Runtime 请求执行 ${toolName}。`)}<br />{data.input ? <code>{JSON.stringify(data.input)}</code> : data.arguments ? <code>{JSON.stringify(data.arguments)}</code> : null}</div>{choice ? <div className={styles.approvalResolved}>{choice === 'allow' ? '已允许' : '已拒绝'} · Runtime 已收到处理结果。</div> : <><div className={styles.approvalActions}><button onClick={() => store.approve(event.id)}>允许</button><button onClick={() => store.reject(event.id)}>拒绝</button><button onClick={() => setApprovalDetails((open) => !open)}>查看详情</button></div>{approvalDetails && <p className={styles.approvalDetail}>选择将以 approval.response 发送到对应的 Agent Run。</p>}</>}</div>;
  }
  if (event.type === 'run.completed') return <div className={styles.resultCard} key={event.id}><div className={styles.resultTitle}><Check />任务完成</div><p>{String(data.result ?? 'Agent Run 已完成。')}</p><div className={styles.resultActions}><button onClick={() => setTab('artifacts')}>查看产物</button><button onClick={() => setTab('activity')}>查看事件</button></div></div>;
  if (event.type === 'run.failed') return <div className={styles.failureCard} key={event.id}>运行失败：{String(data.detail ?? data.code ?? '未知错误')}</div>;
  return <div className={styles.timeline} key={event.id}><div><i />{event.type}<span>{String(data.phase ?? data.status ?? data.detail ?? '')}</span></div></div>;
}
