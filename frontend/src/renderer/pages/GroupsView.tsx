import { useCallback, useEffect, useMemo, useState } from 'react';
import { LoaderCircle, Plus, RefreshCw, Send, Square, Trash2, Users, X } from 'lucide-react';
import { useAtlasStore } from '../store/useAtlasStore';
import { relativeTime } from '../services/api';
import type { GroupTimelineEntry } from '../services/persistentApi';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';

const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';

const ACTOR_STYLE: Record<string, string> = {
  user: 'bg-brand-soft text-fg',
  agent: 'bg-sunken text-fg-2 shadow-[inset_0_0_0_1px_var(--line)]',
  system: 'bg-sunken text-fg-3',
};

/**
 * 群聊（W8 契约）：建群（选 persistent agent）/ timeline（actor 徽标）/ 输入触发 turn / stop。
 * 后端 W8 未挂载时路由 404：整个面板降级为「群聊服务未就绪」占位，不崩。
 */
export default function GroupsView({ onToast }: { onToast: (text: string) => void }) {
  const agents = useAtlasStore((state) => state.agents);
  const groups = useAtlasStore((state) => state.groups);
  const groupsAvailable = useAtlasStore((state) => state.groupsAvailable);
  const groupsLoading = useAtlasStore((state) => state.groupsLoading);
  const groupsError = useAtlasStore((state) => state.groupsError);
  const timelines = useAtlasStore((state) => state.groupTimelines);
  const busyMap = useAtlasStore((state) => state.groupBusy);
  const loadAgents = useAtlasStore((state) => state.loadAgents);
  const loadGroups = useAtlasStore((state) => state.loadGroups);
  const createGroup = useAtlasStore((state) => state.createGroup);
  const deleteGroup = useAtlasStore((state) => state.deleteGroup);
  const sendGroupTurn = useAtlasStore((state) => state.sendGroupTurn);
  const loadGroupTimeline = useAtlasStore((state) => state.loadGroupTimeline);
  const stopGroup = useAtlasStore((state) => state.stopGroup);

  const [selected, setSelected] = useState('');
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [members, setMembers] = useState<string[]>([]);
  const [input, setInput] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => { void loadAgents(); void loadGroups(); }, [loadAgents, loadGroups]);

  const persistent = useMemo(() => agents.filter((agent) => agent.kind === 'persistent'), [agents]);
  const group = groups.find((item) => item.id === selected);
  const timeline = timelines[selected] ?? [];
  const busy = Boolean(busyMap[selected]);

  useEffect(() => {
    if (selected || !groups.length) return;
    setSelected(groups[0].id);
  }, [groups, selected]);
  useEffect(() => setConfirmDelete(false), [selected]);

  // turn 是异步编排，轮询 timeline 让其它成员的回合一点点显出来；404 时不打扰。
  useEffect(() => {
    if (!selected || groupsAvailable === false) return;
    void loadGroupTimeline(selected);
    const timer = window.setInterval(() => void loadGroupTimeline(selected), 5000);
    return () => window.clearInterval(timer);
  }, [selected, groupsAvailable, loadGroupTimeline]);

  const agentName = useCallback((id: string) => agents.find((agent) => agent.id === id)?.name ?? id, [agents]);

  const submit = async () => {
    const text = input.trim();
    if (!text || !selected || busy) return;
    setInput('');
    if (!await sendGroupTurn(selected, text)) onToast(useAtlasStore.getState().groupsError || '这条没有发出去');
  };

  const create = async () => {
    if (!name.trim() || !members.length) return;
    if (await createGroup(name.trim(), members)) {
      setName(''); setMembers([]); setCreating(false);
      onToast('群聊已创建');
    }
  };

  if (groupsAvailable === false) return <div className="screen page"><div className="page-inner">
    <header className="page-head"><div><h1>群聊</h1><p>把几个 Agent 拉进同一个房间，@谁谁说话。</p></div></header>
    <div className="empty glass rounded-xl py-16"><Users size={22} /><b>群聊服务未就绪</b>群聊编排服务（W8）还没有在这台后端上挂载；等它上线后这里会自动亮起来。</div>
  </div></div>;

  return <div className="flex min-h-0 flex-1">
    <div className="flex w-[248px] shrink-0 flex-col border-r border-line px-3 pt-4 pb-3">
      <div className="mb-2 flex items-center justify-between px-1">
        <h2 className="m-0 text-[13px] font-semibold text-fg-2">群聊</h2>
        <Button size="icon-sm" variant="ghost" aria-label="新建群聊" onClick={() => setCreating(true)}><Plus /></Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {groups.map((item) => <button key={item.id} aria-current={item.id === selected}
          onClick={() => setSelected(item.id)}
          className={cn('flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px]', item.id === selected ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
          <Users size={14} className="shrink-0 text-fg-3" />
          <span className="min-w-0 flex-1 truncate">{item.name}</span>
          <span className="shrink-0 text-[11px] text-fg-3">{(item.members ?? []).length}</span>
        </button>)}
        {!groups.length && !groupsLoading && <p className="px-2.5 text-[12.5px] text-fg-3">{groupsAvailable === null ? '正在读取…' : '还没有群聊。点 + 建一个。'}</p>}
      </div>
      {groupsError && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-2.5 py-1.5 text-[12px] text-danger">{groupsError}</p>}
    </div>

    <div className="flex min-w-0 flex-1 flex-col">
      {creating && <div className="border-b border-line bg-surface px-6 py-4">
        <form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); void create(); }}>
          <div className="flex items-center justify-between">
            <h3 className="m-0 text-[14px] font-semibold text-heading">新建群聊</h3>
            <Button size="icon-sm" variant="ghost" aria-label="取消新建" onClick={() => setCreating(false)}><X /></Button>
          </div>
          <label className="grid max-w-[320px] gap-1 text-[13px] text-fg-2">群名称
            <input autoFocus required value={name} onChange={(event) => setName(event.target.value)} placeholder="比如：项目评审室" className={field} />
          </label>
          <div className="text-[13px] text-fg-2">成员（选 persistent Agent）
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {persistent.map((agent) => {
                const on = members.includes(agent.id);
                return <button key={agent.id} type="button" aria-pressed={on}
                  onClick={() => setMembers((current) => on ? current.filter((id) => id !== agent.id) : [...current, agent.id])}
                  className={cn('rounded-lg px-2.5 py-1 text-[12.5px]', on ? 'bg-brand-soft text-fg' : 'bg-sunken text-fg-3 shadow-[inset_0_0_0_1px_var(--line)] hover:text-fg')}>
                  {agent.name}
                </button>;
              })}
              {!persistent.length && <span className="text-[12.5px] text-fg-3">还没有 persistent Agent，先去 Agents 页创建。</span>}
            </div>
          </div>
          <div className="flex gap-2">
            <Button type="submit" variant="primary" disabled={!name.trim() || members.length < 1}>创建</Button>
            <Button variant="ghost" onClick={() => setCreating(false)}>取消</Button>
          </div>
        </form>
      </div>}

      {group ? <>
        <header className="flex h-11 shrink-0 items-center gap-3 border-b border-line px-5">
          <Users size={15} className="text-fg-3" />
          <b className="text-[13.5px] font-medium text-fg">{group.name}</b>
          <span className="text-[12px] text-fg-3">{(group.members ?? []).map((member) => agentName(member.agent_id)).join('、')}</span>
          <span className="flex-1" />
          <Button size="sm" variant="ghost" disabled={busy} aria-label="停止群聊回合" onClick={() => void stopGroup(group.id).then(() => onToast('已请求停止'))}><Square />停止</Button>
          <Button size="icon-sm" variant="ghost" aria-label="刷新时间线" onClick={() => void loadGroupTimeline(group.id)}><RefreshCw /></Button>
          <Button size="icon-sm" variant={confirmDelete ? 'danger' : 'ghost'} aria-label="解散群聊"
            onClick={() => { if (!confirmDelete) { setConfirmDelete(true); return; } void deleteGroup(group.id); setSelected(''); onToast('群聊已解散'); }}>
            <Trash2 />
          </Button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto px-6 py-4" aria-label="群聊时间线">
          <div className="mx-auto grid w-[min(720px,100%)] gap-3">
            {timeline.map((entry, index) => <GroupBubble key={entry.id ?? index} entry={entry} agentName={agentName} />)}
            {!timeline.length && <div className="empty py-16"><Users size={22} /><b>还没有消息</b>在下面说一句，成员们会按顺序轮流接话。</div>}
          </div>
        </div>
        <div className="border-t border-line px-6 py-3">
          <div className="mx-auto flex w-[min(720px,100%)] items-end gap-2">
            <textarea aria-label="群聊消息" rows={1} value={input} disabled={busy}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }}
              placeholder={busy ? '成员们正在接话…' : '说一句，或 @某个成员点名它（Shift+Enter 换行）'}
              className={cn(field, 'max-h-32 min-h-[38px] w-full resize-none py-2 leading-[1.55]', busy && 'opacity-60')} />
            <Button size="icon" variant="primary" aria-label="发送" disabled={!input.trim() || busy} onClick={() => void submit()}>
              {busy ? <LoaderCircle className="spin" /> : <Send />}
            </Button>
          </div>
        </div>
      </> : <div className="grid flex-1 place-items-center text-[13px] text-fg-3">
        {groupsLoading ? '正在读取群聊…' : '选一个群聊，或者新建一个。'}
      </div>}
    </div>
  </div>;
}

function GroupBubble({ entry, agentName }: { entry: GroupTimelineEntry; agentName: (id: string) => string }) {
  const kind = String(entry.actor_kind ?? 'agent');
  const who = kind === 'user' ? '我' : agentName(String(entry.actor ?? entry.actor_id ?? '?'));
  const at = entry.at ? relativeTime(entry.at) : '';
  const text = String(entry.text ?? entry.content ?? '');
  if (kind === 'system') return <div className="mx-auto w-fit rounded-full bg-sunken px-3 py-1 text-[12px] text-fg-3">{text}</div>;
  return <div className={cn('flex gap-2.5', kind === 'user' && 'flex-row-reverse')}>
    <span className={cn('mt-0.5 grid h-7 shrink-0 place-items-center rounded-full px-2 text-[11.5px] font-medium', ACTOR_STYLE[kind] ?? ACTOR_STYLE.agent)}>{who.slice(0, 2)}</span>
    <div className={cn('max-w-[76%]', kind === 'user' && 'text-right')}>
      <div className="mb-0.5 text-[11.5px] text-fg-3">{who}{at && ` · ${at}`}</div>
      <div className="inline-block rounded-[12px] bg-sunken px-3.5 py-2 text-left text-[13.5px] leading-[1.6] whitespace-pre-wrap text-fg shadow-[inset_0_0_0_1px_var(--line)]">{text}</div>
    </div>
  </div>;
}
