import type { ReactNode } from 'react';
import { Archive, CircleAlert, CircleCheck, Clock3, FolderOpen, ListOrdered, LoaderCircle, MessageCircleQuestion, Square } from 'lucide-react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import type { AgentRun } from '../../types/runtime';
import type { QueuedMessage } from '../store/useAtlasStore';
import { relativeTime } from '../services/api';
import { cn } from '../ui/cn';

type Column = 'running' | 'attention' | 'queued' | 'done';

interface Card { conversation: ConversationSummary; run?: AgentRun; queued: number; unread: boolean }

const COLUMNS: Array<{ id: Column; title: string; hint: string; icon: ReactNode }> = [
  { id: 'running', title: '进行中', hint: 'Atlas 正在做', icon: <LoaderCircle size={15} className="spin text-brand" /> },
  { id: 'attention', title: '等你处理', hint: '要你确认、回答，或者出错了', icon: <MessageCircleQuestion size={15} className="text-danger" /> },
  { id: 'queued', title: '排队中', hint: '还有消息等着发', icon: <ListOrdered size={15} className="text-fg-2" /> },
  { id: 'done', title: '最近完成', hint: '做完了，或者最近动过', icon: <CircleCheck size={15} className="text-ok" /> },
];
const STATUS: Record<string, string> = { running: '正在处理', planning: '正在规划', waiting: '等你确认', paused: '已暂停', completed: '已完成', failed: '出错了', cancelled: '已停止' };

function columnOf(card: Card): Column {
  const status = card.run?.status;
  if (status === 'waiting' || status === 'failed' || status === 'paused') return 'attention';
  if (status === 'running' || status === 'planning') return 'running';
  if (card.queued) return 'queued';
  return 'done';
}

/** Every conversation at a glance, grouped by what it needs: the command centre for parallel work. */
export default function BoardPage({ conversations, runs, queue, unread, archived, onOpen, onStop, onArchive }: {
  conversations: ConversationSummary[];
  runs: AgentRun[];
  queue: Record<string, QueuedMessage[]>;
  unread: string[];
  archived: string[];
  onOpen: (conversation: ConversationSummary) => void;
  onStop: (runId: string) => void;
  onArchive: (id: string) => void;
}) {
  const latestRun = new Map<string, AgentRun>();
  for (const run of runs) latestRun.set(run.conversationId, run);
  const cards: Card[] = conversations.filter((conversation) => !archived.includes(conversation.id)).map((conversation) => ({
    conversation, run: latestRun.get(conversation.id), queued: queue[conversation.id]?.length ?? 0, unread: unread.includes(conversation.id),
  }));
  const grouped = new Map<Column, Card[]>(COLUMNS.map((column) => [column.id, []]));
  for (const card of cards) grouped.get(columnOf(card))!.push(card);
  grouped.set('done', grouped.get('done')!.slice(0, 24));

  return <div className="screen page"><div className="page-inner" style={{ maxWidth: 'none' }}>
    <header className="page-head">
      <div><h1>任务看板</h1><p>所有对话按状态排好，同时跑几件事时从这里照看。</p></div>
    </header>
    <div className="grid min-h-0 gap-4 [grid-template-columns:repeat(4,minmax(220px,1fr))] overflow-x-auto pb-4">
      {COLUMNS.map((column) => {
        const items = grouped.get(column.id)!;
        return <section key={column.id} aria-label={column.title} className="flex min-h-[320px] min-w-0 flex-col rounded-2xl bg-sunken p-3">
          <header className="mb-3 flex items-center gap-2 px-1">
            {column.icon}<b className="text-[13.5px] font-semibold text-fg">{column.title}</b>
            <span className="rounded-full bg-hover px-1.5 text-[11.5px] tabular-nums text-fg-3">{items.length}</span>
          </header>
          <div className="grid gap-2">
            {items.map((card) => <BoardCard key={card.conversation.id} card={card} onOpen={onOpen} onStop={onStop} onArchive={onArchive} />)}
            {!items.length && <p className="m-0 px-1 text-[12.5px] leading-[1.6] text-fg-3">{column.hint}，现在没有。</p>}
          </div>
        </section>;
      })}
    </div>
  </div></div>;
}

function BoardCard({ card, onOpen, onStop, onArchive }: { card: Card; onOpen: (conversation: ConversationSummary) => void; onStop: (runId: string) => void; onArchive: (id: string) => void }) {
  const { conversation, run } = card;
  const live = run && ['running', 'planning', 'waiting', 'paused'].includes(run.status);
  const lastStep = run ? [...run.events].reverse().find((event) => event.type === 'tool.started' || event.type === 'input.required' || event.type === 'run.plan.proposed' || event.type === 'approval.required') : undefined;
  const detail = lastStep?.type === 'input.required' ? `问你：${String(lastStep.data.question ?? '')}`
    : lastStep?.type === 'run.plan.proposed' ? '计划等你批准'
    : lastStep?.type === 'approval.required' ? '有一步等你确认'
    : run?.status === 'failed' ? String([...run.events].reverse().find((event) => event.type === 'run.failed')?.data.detail ?? '出错了')
    : lastStep ? `在用 ${String(lastStep.data.name ?? '工具')}` : '';
  const workspace = typeof conversation.workspace === 'string' ? conversation.workspace.split(/[\\/]/).filter(Boolean).pop() : '';
  return <div className="group rounded-xl card-surface">
    <button onClick={() => onOpen(conversation)} className="block w-full px-3 pt-2.5 pb-2 text-left">
      <span className="flex items-start gap-2">
        {card.unread && <i className="mt-[7px] size-1.5 shrink-0 rounded-full bg-ok" aria-label="有新结果" />}
        <b className="line-clamp-2 text-[13px] font-medium text-fg">{conversation.title}</b>
      </span>
      {detail && <span className={cn('mt-1 line-clamp-2 block text-[12px]', run?.status === 'failed' ? 'text-danger' : 'text-fg-3')}>{detail}</span>}
      <span className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-fg-3">
        {run && <span className={cn(run.status === 'failed' && 'text-danger')}>{run.status === 'failed' ? <CircleAlert size={11} className="mr-0.5 inline" /> : null}{STATUS[run.status] ?? run.status}</span>}
        {card.queued > 0 && <span>还有 {card.queued} 条待发</span>}
        {workspace && <span className="inline-flex items-center gap-0.5"><FolderOpen size={11} />{workspace}</span>}
        <span className="inline-flex items-center gap-0.5"><Clock3 size={11} />{relativeTime(run?.updatedAt ?? conversation.updated_at)}</span>
      </span>
    </button>
    <div className="flex justify-end gap-0.5 px-2 pb-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
      {live && run && <button aria-label="停止" onClick={() => onStop(run.id)} className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[12px] text-fg-3 hover:bg-hover hover:text-danger"><Square size={11} />停止</button>}
      {!live && <button aria-label="归档" onClick={() => onArchive(conversation.id)} className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[12px] text-fg-3 hover:bg-hover hover:text-fg"><Archive size={12} />归档</button>}
    </div>
  </div>;
}
