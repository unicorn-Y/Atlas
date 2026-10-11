import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUp, Brain, Check, ChevronRight, CircleStop, KeyRound, LoaderCircle, ShieldQuestion, Wrench, X } from 'lucide-react';
import MarkdownContent from '../../components/MarkdownContent';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import type { SessionInfo, SessionSnapshot, WorkbenchAgent, WorkbenchApi, WorkbenchEvent } from '../../services/workbenchApi';

type Json = Record<string, any>;
type Item =
  | { type: 'user'; text: string }
  | { type: 'agent'; text: string }
  | { type: 'thought'; text: string }
  | { type: 'tool'; id: string; call: Json }
  | { type: 'plan'; entries: Array<{ content: string; status: string }> }
  | { type: 'permission'; requestId: string; toolCall: Json; options: Array<{ optionId: string; name: string; kind: string }>; answer?: string | null }
  | { type: 'error'; text: string; auth?: SessionInfo['auth_methods'] }
  | { type: 'done'; reason: string };

/** 把挂件的事件流（ACP session/update 等）折叠成对话条目。 */
function fold(events: WorkbenchEvent[]): { items: Item[]; mode?: string; commands: Array<{ name: string; description?: string }> } {
  const items: Item[] = [];
  const tools = new Map<string, number>();
  let mode: string | undefined;
  let commands: Array<{ name: string; description?: string }> = [];
  const appendText = (type: 'agent' | 'thought' | 'user', text: string) => {
    const last = items[items.length - 1];
    if (last && last.type === type) last.text += text; else items.push({ type, text });
  };
  for (const event of events) {
    if (event.kind === 'user') items.push({ type: 'user', text: String(event.text ?? '') });
    else if (event.kind === 'error') items.push({ type: 'error', text: String(event.detail ?? '出错了'), auth: event.auth_methods as SessionInfo['auth_methods'] });
    else if (event.kind === 'done') { const reason = String(event.stop_reason ?? ''); if (reason && reason !== 'end_turn') items.push({ type: 'done', reason }); }
    else if (event.kind === 'permission') items.push({ type: 'permission', requestId: String(event.request_id), toolCall: (event.tool_call ?? {}) as Json, options: (event.options ?? []) as any });
    else if (event.kind === 'permission_result') {
      const target = items.find((item) => item.type === 'permission' && item.requestId === event.request_id) as Extract<Item, { type: 'permission' }> | undefined;
      if (target) target.answer = (event.option_id as string | null) ?? null;
    } else if (event.kind === 'update') {
      const update = (event.update ?? {}) as Json;
      const kind = update.sessionUpdate as string;
      const text = update.content?.type === 'text' ? String(update.content.text ?? '') : '';
      if (kind === 'agent_message_chunk') appendText('agent', text);
      else if (kind === 'agent_thought_chunk') appendText('thought', text);
      else if (kind === 'user_message_chunk') appendText('user', text);
      else if (kind === 'tool_call') { tools.set(update.toolCallId, items.length); items.push({ type: 'tool', id: update.toolCallId, call: update }); }
      else if (kind === 'tool_call_update') {
        const index = tools.get(update.toolCallId);
        if (index === undefined) { tools.set(update.toolCallId, items.length); items.push({ type: 'tool', id: update.toolCallId, call: update }); }
        else { const item = items[index] as Extract<Item, { type: 'tool' }>; item.call = { ...item.call, ...Object.fromEntries(Object.entries(update).filter(([, v]) => v !== undefined && v !== null)) }; }
      } else if (kind === 'plan') {
        const existing = items.findIndex((item) => item.type === 'plan');
        const plan: Item = { type: 'plan', entries: (update.entries ?? []) as any };
        if (existing >= 0) items.splice(existing, 1);
        items.push(plan);
      } else if (kind === 'current_mode_update') mode = update.currentModeId;
      else if (kind === 'available_commands_update') commands = update.availableCommands ?? [];
    }
  }
  return { items, mode, commands };
}

const TOOL_KIND: Record<string, string> = { read: '读取', edit: '修改', delete: '删除', move: '移动', search: '搜索', execute: '执行', think: '思考', fetch: '联网', switch_mode: '切换模式', other: '工具' };
const STATUS: Record<string, string> = { pending: '等待', in_progress: '进行中', completed: '完成', failed: '失败' };

function ToolCard({ call }: { call: Json }) {
  const [open, setOpen] = useState(false);
  const status = String(call.status ?? 'pending');
  const content: Json[] = Array.isArray(call.content) ? call.content : [];
  const paths: string[] = Array.isArray(call.locations) ? call.locations.map((loc: Json) => loc.path).filter(Boolean) : [];
  return <div className="overflow-hidden rounded-xl card-surface text-[12.5px]">
    <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-3 py-2 text-left">
      <ChevronRight size={12} className={cn('shrink-0 text-fg-3 transition-transform', open && 'rotate-90')} />
      <Wrench size={13} className="shrink-0 text-fg-3" />
      <span className="shrink-0 text-fg-3">{TOOL_KIND[call.kind] ?? '工具'}</span>
      <span className="min-w-0 flex-1 truncate text-fg">{call.title || paths[0] || call.toolCallId}</span>
      <span className={cn('shrink-0', status === 'failed' ? 'text-danger' : status === 'completed' ? 'text-ok' : 'text-brand')}>{STATUS[status] ?? status}</span>
    </button>
    {open && <div className="grid gap-2 px-3 pb-3">
      {paths.length > 0 && <p className="m-0 font-mono text-[11.5px] text-fg-3">{paths.join('  ')}</p>}
      {call.rawInput && <pre className="m-0 max-h-48 overflow-auto rounded-lg bg-code p-2 font-mono text-[11.5px] whitespace-pre-wrap text-fg-2">{JSON.stringify(call.rawInput, null, 2)}</pre>}
      {content.map((block, index) => block.type === 'diff'
        ? <div key={index} className="overflow-hidden rounded-lg bg-code">
            <p className="m-0 px-2 py-1 font-mono text-[11.5px] text-fg-2 shadow-[inset_0_-1px_0_var(--line)]">{block.path}</p>
            {block.oldText && <pre className="m-0 max-h-40 overflow-auto bg-danger-soft p-2 font-mono text-[11.5px] whitespace-pre-wrap">{block.oldText}</pre>}
            <pre className="m-0 max-h-60 overflow-auto bg-ok-soft p-2 font-mono text-[11.5px] whitespace-pre-wrap">{block.newText}</pre>
          </div>
        : block.type === 'content' && block.content?.type === 'text'
          ? <pre key={index} className="m-0 max-h-60 overflow-auto rounded-lg bg-code p-2 font-mono text-[11.5px] whitespace-pre-wrap text-fg-2">{block.content.text}</pre>
          : block.type === 'terminal' ? <p key={index} className="m-0 text-fg-3">终端输出（{block.terminalId}）</p> : null)}
      {call.rawOutput && <pre className="m-0 max-h-60 overflow-auto rounded-lg bg-code p-2 font-mono text-[11.5px] whitespace-pre-wrap text-fg-2">{typeof call.rawOutput === 'string' ? call.rawOutput : JSON.stringify(call.rawOutput, null, 2)}</pre>}
    </div>}
  </div>;
}

function Thought({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return <div className="text-[12.5px] text-fg-3">
    <button onClick={() => setOpen(!open)} className="inline-flex items-center gap-1 hover:text-fg-2"><Brain size={13} />思考过程<ChevronRight size={12} className={cn('transition-transform', open && 'rotate-90')} /></button>
    {open && <p className="m-0 mt-1 whitespace-pre-wrap border-l-2 border-[var(--line-strong)] pl-3">{text}</p>}
  </div>;
}

/** 一个挂件会话：实时事件走 WebSocket，历史从 jsonl 读。 */
export default function AgentChat({ api, agent, sessionId, onToast, onSessionsChanged }: {
  api: WorkbenchApi; agent: WorkbenchAgent; sessionId: string;
  onToast: (text: string) => void; onSessionsChanged: () => void;
}) {
  const [events, setEvents] = useState<WorkbenchEvent[]>([]);
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [live, setLive] = useState(false);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [connectKey, setConnectKey] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    setEvents([]); setSnapshot(null); setLive(false);
    void api.events(agent.id, sessionId).then(({ events: past }) => {
      if (disposed) return;
      setEvents(past);
      socket = new WebSocket(api.streamUrl(sessionId));
      socket.onmessage = (message) => {
        if (disposed) return;
        let event: WorkbenchEvent;
        try { event = JSON.parse(String(message.data)); } catch { return; }
        if (event.kind === 'snapshot') { setSnapshot(event as unknown as SessionSnapshot); setLive(true); return; }
        if (event.kind === 'status' && event.status === 'closed') { setLive(false); return; }
        if (event.kind === 'session') setSnapshot((current) => current && { ...current, status: 'ready', info: event.info as SessionInfo });
        if (event.kind === 'done' || event.kind === 'error') { setSnapshot((current) => current && { ...current, busy: false }); onSessionsChanged(); }
        setEvents((current) => [...current, event]);
      };
      socket.onclose = () => { if (!disposed) setLive(false); };
    }).catch((cause: Error) => onToast(cause.message));
    return () => { disposed = true; socket?.close(); };
  }, [api, agent.id, sessionId, connectKey]);

  const { items, mode, commands } = useMemo(() => fold(events), [events]);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight }); }, [items.length, events.length]);

  const busy = Boolean(snapshot?.busy) || sending;
  const info = snapshot?.info;
  const currentMode = mode ?? info?.modes?.currentModeId;

  const resume = async () => {
    try { await api.start(agent.id, sessionId); onSessionsChanged(); setConnectKey((key) => key + 1); }
    catch (cause) { onToast((cause as Error).message); }
  };

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setSending(true);
    try { const snap = await api.prompt(sessionId, text); setSnapshot(snap); setInput(''); }
    catch (cause) { onToast((cause as Error).message); }
    finally { setSending(false); }
  };

  return <div className="flex h-full min-h-0 flex-col">
    <div className="flex flex-wrap items-center gap-2 px-1 pb-2 text-[12px] text-fg-3">
      <span className={cn('size-1.5 rounded-full', live ? (busy ? 'bg-brand' : 'bg-ok') : 'bg-fg-3')} />
      <span>{live ? (busy ? '正在干活' : '就绪') : '未连接（只读历史）'}</span>
      {info?.modes && live && <select value={currentMode} onChange={(event) => void api.setMode(sessionId, event.target.value).then(setSnapshot).catch((cause: Error) => onToast(cause.message))}
        className="rounded-md bg-sunken px-1.5 py-0.5 text-fg-2" title="模式">
        {info.modes.availableModes.map((item) => <option key={item.id} value={item.id} title={item.description}>{item.name}</option>)}
      </select>}
      {live && info?.config_options?.filter((option) => option.options?.length).map((option) =>
        <select key={option.id} value={String(option.currentValue ?? '')} title={option.name}
          onChange={(event) => void api.setOption(sessionId, option.id, event.target.value).then(setSnapshot).catch((cause: Error) => onToast(cause.message))}
          className="rounded-md bg-sunken px-1.5 py-0.5 text-fg-2">
          {option.options!.map((item) => <option key={item.value} value={item.value}>{item.name}</option>)}
        </select>)}
      {!live && <Button size="sm" variant="secondary" onClick={() => void resume()}>{info?.load_session === false ? '用新进程继续' : '重新连上'}</Button>}
    </div>
    <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto rounded-xl bg-sunken/50 p-3">
      {!items.length && <p className="m-0 p-6 text-center text-[13px] text-fg-3">给「{agent.name}」派个活。它只在自己的工作目录里干，看不到 Atlas 的记忆和配置。</p>}
      <div className="grid gap-3">{items.map((item, index) => {
        if (item.type === 'user') return <div key={index} className="ml-auto max-w-[85%] rounded-2xl bg-selected px-3.5 py-2 text-[13.5px] whitespace-pre-wrap text-fg">{item.text}</div>;
        if (item.type === 'agent') return <div key={index} className="max-w-full text-[13.5px] text-fg"><MarkdownContent content={item.text} /></div>;
        if (item.type === 'thought') return <Thought key={index} text={item.text} />;
        if (item.type === 'tool') return <ToolCard key={index} call={item.call} />;
        if (item.type === 'plan') return <div key={index} className="rounded-xl card-surface px-3 py-2 text-[12.5px]">
          <p className="m-0 mb-1 font-semibold text-fg-2">计划</p>
          {item.entries.map((entry, i) => <p key={i} className={cn('m-0 flex items-center gap-1.5', entry.status === 'completed' ? 'text-fg-3 line-through' : 'text-fg')}>
            {entry.status === 'completed' ? <Check size={12} className="text-ok" /> : entry.status === 'in_progress' ? <LoaderCircle size={12} className="animate-spin text-brand" /> : <span className="size-3" />}{entry.content}</p>)}
        </div>;
        if (item.type === 'permission') return <div key={index} className="rounded-xl bg-brand-soft px-3 py-2.5 text-[13px]">
          <p className="m-0 flex items-center gap-1.5 font-semibold text-fg"><ShieldQuestion size={14} />它想：{item.toolCall.title ?? '执行一个操作'}</p>
          {item.toolCall.rawInput && <pre className="m-0 mt-1.5 max-h-32 overflow-auto rounded-lg bg-code p-2 font-mono text-[11.5px] whitespace-pre-wrap text-fg-2">{JSON.stringify(item.toolCall.rawInput, null, 2)}</pre>}
          {item.answer === undefined && live
            ? <div className="mt-2 flex flex-wrap gap-1.5">
                {item.options.map((option) => <Button key={option.optionId} size="sm" variant={option.kind.startsWith('allow') ? 'primary' : 'secondary'}
                  onClick={() => void api.permission(sessionId, item.requestId, option.optionId).catch((cause: Error) => onToast(cause.message))}>{option.name}</Button>)}
                <Button size="sm" variant="ghost" onClick={() => void api.permission(sessionId, item.requestId, null).catch((cause: Error) => onToast(cause.message))}><X size={13} />拒绝</Button>
              </div>
            : <p className="m-0 mt-1 text-[12px] text-fg-3">{item.answer ? `已选：${item.options.find((o) => o.optionId === item.answer)?.name ?? item.answer}` : item.answer === null ? '已拒绝' : '已过期'}</p>}
        </div>;
        if (item.type === 'error') return <div key={index} className="rounded-xl bg-danger-soft px-3 py-2 text-[12.5px] text-danger">
          <p className="m-0 whitespace-pre-wrap">{item.text}</p>
          {!!item.auth?.length && <div className="mt-2 flex flex-wrap gap-1.5">{item.auth.map((method) =>
            <Button key={method.id} size="sm" variant="secondary" title={method.description}
              onClick={() => void api.authenticate(sessionId, method.id).then((snap) => { setSnapshot(snap); onToast('已登录'); }).catch((cause: Error) => onToast(cause.message))}><KeyRound size={13} />{method.name}</Button>)}
            <span className="self-center text-fg-3">也可以点上面的「隔离终端」在里面手动登录</span></div>}
        </div>;
        return <p key={index} className="m-0 text-center text-[12px] text-fg-3">— {item.reason === 'cancelled' ? '已停止' : item.reason} —</p>;
      })}</div>
    </div>
    {commands.length > 0 && input.startsWith('/') && <div className="mt-1.5 flex flex-wrap gap-1">{commands.filter((c) => `/${c.name}`.startsWith(input.split(' ')[0])).slice(0, 12).map((command) =>
      <button key={command.name} title={command.description} onClick={() => setInput(`/${command.name} `)} className="rounded-md bg-sunken px-1.5 py-0.5 text-[12px] text-fg-2 hover:bg-hover">/{command.name}</button>)}</div>}
    <div className="mt-2 flex items-end gap-2 rounded-2xl card-surface p-2">
      <textarea value={input} onChange={(event) => setInput(event.target.value)} rows={2} disabled={!live}
        onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }}
        placeholder={live ? `让 ${agent.name} 做点什么…（Enter 发送，Shift+Enter 换行）` : '会话没在运行，先点上面的「重新连上」'}
        className="min-h-[44px] flex-1 resize-none bg-transparent px-1.5 py-1 text-[13.5px] text-fg outline-none placeholder:text-fg-3" />
      {busy
        ? <Button size="icon" variant="secondary" aria-label="停止" onClick={() => void api.cancel(sessionId).catch((cause: Error) => onToast(cause.message))}><CircleStop /></Button>
        : <Button size="icon" variant="primary" aria-label="发送" disabled={!input.trim() || !live} onClick={() => void send()}><ArrowUp /></Button>}
    </div>
  </div>;
}
