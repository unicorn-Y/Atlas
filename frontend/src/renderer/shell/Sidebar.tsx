import { useState } from 'react';
import { Archive, ArchiveRestore, BookOpen, ChevronRight, Code2, CopyPlus, Download, Home, KanbanSquare, Moon, MoreHorizontal, PanelLeft, Pencil, Pin, PinOff, Plus, Puzzle, Repeat, Search, Settings, Sparkles, Sun, Trash2, Wand2, type LucideIcon } from 'lucide-react';
import { nextTheme, themeInfo, type Theme } from './themes';
import type { ConversationSummary } from '@atlas/backend-adapter';
import Mark from '../components/Mark';
import { Kbd } from '../ui/Kbd';
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from '../ui/Menu';
import { Tip } from '../ui/Tooltip';
import { cn } from '../ui/cn';

export type View = 'home' | 'chat' | 'board' | 'code' | 'create' | 'auto' | 'memory' | 'skills';

export const NAV: Array<{ view: View; label: string; icon: LucideIcon }> = [
  { view: 'home', label: '首页', icon: Home },
  { view: 'board', label: '看板', icon: KanbanSquare },
  { view: 'code', label: '项目', icon: Code2 },
  { view: 'create', label: '创作', icon: Wand2 },
  { view: 'auto', label: '自动化', icon: Repeat },
  { view: 'memory', label: '记忆', icon: BookOpen },
  { view: 'skills', label: '技能', icon: Puzzle },
];

function groupByDay(conversations: ConversationSummary[]) {
  const startOfToday = new Date(); startOfToday.setHours(0, 0, 0, 0);
  const day = 86400000;
  const groups: Array<{ label: string; items: ConversationSummary[] }> = [
    { label: '今天', items: [] }, { label: '昨天', items: [] }, { label: '最近 7 天', items: [] }, { label: '更早', items: [] },
  ];
  for (const conversation of conversations) {
    const raw = conversation.updated_at ?? (typeof conversation.created_at === 'string' ? conversation.created_at : undefined);
    const time = raw ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(raw) ? raw : `${raw}Z`).getTime() : 0;
    const index = time >= startOfToday.getTime() ? 0 : time >= startOfToday.getTime() - day ? 1 : time >= startOfToday.getTime() - 7 * day ? 2 : 3;
    groups[index].items.push(conversation);
  }
  return groups.filter((group) => group.items.length);
}

interface SidebarProps {
  view: View;
  onGo: (view: View) => void;
  mini: boolean;
  onToggleMini: () => void;
  conversations: ConversationSummary[];
  conversationsLoading: boolean;
  activeConversationId: string;
  loadingConversationId: string | null;
  onOpenConversation: (conversation: ConversationSummary) => void;
  onNewTask: () => void;
  creating: boolean;
  onSearch: () => void;
  pendingMemories: number;
  username: string;
  subtitle: string;
  theme: Theme;
  onToggleTheme: () => void;
  onSettings: () => void;
  pinned: string[];
  archived: string[];
  unread: string[];
  running: string[];
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onTogglePinned: (id: string) => void;
  onToggleArchived: (id: string) => void;
  onExport: (id: string) => void;
  onDuplicate: (id: string) => void;
}

export default function Sidebar(props: SidebarProps) {
  const { mini } = props;
  const [showArchived, setShowArchived] = useState(false);
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState('');
  const byId = new Map(props.conversations.map((item) => [item.id, item]));
  const pinnedItems = props.pinned.map((id) => byId.get(id)).filter((item): item is ConversationSummary => Boolean(item) && !props.archived.includes(item!.id));
  const archivedItems = props.conversations.filter((item) => props.archived.includes(item.id));
  const groups = groupByDay(props.conversations.filter((item) => !props.pinned.includes(item.id) && !props.archived.includes(item.id)));
  const commitRename = () => {
    if (editing && editing.title.trim() && editing.title.trim() !== byId.get(editing.id)?.title) props.onRename(editing.id, editing.title);
    setEditing(null);
  };

  const row = (conversation: ConversationSummary) => {
    const current = conversation.id === props.activeConversationId && props.view === 'chat';
    const isPinned = props.pinned.includes(conversation.id);
    const isArchived = props.archived.includes(conversation.id);
    if (editing?.id === conversation.id) {
      return <input key={conversation.id} autoFocus aria-label="对话名称" value={editing.title}
        onChange={(event) => setEditing({ id: conversation.id, title: event.target.value })}
        onBlur={commitRename}
        onKeyDown={(event) => { if (event.key === 'Enter') commitRename(); else if (event.key === 'Escape') setEditing(null); }}
        className="block w-full rounded-lg bg-sunken px-2.5 py-1.5 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--brand)]" />;
    }
    return <div key={conversation.id} className={cn('group relative flex items-center rounded-lg transition-colors', current ? 'bg-selected' : 'hover:bg-hover')}>
      <button title={conversation.title} aria-current={current ? 'page' : undefined}
        disabled={props.loadingConversationId === conversation.id} onClick={() => props.onOpenConversation(conversation)}
        onDoubleClick={() => setEditing({ id: conversation.id, title: conversation.title })}
        className={cn('flex min-w-0 flex-1 items-center gap-2 py-1.5 pr-7 pl-2.5 text-left text-[13px] disabled:opacity-60', current ? 'text-fg' : 'text-fg-2 group-hover:text-fg')}>
        {props.running.includes(conversation.id)
          ? <i className="size-1.5 shrink-0 animate-pulse rounded-full bg-brand" aria-label="正在运行" />
          : props.unread.includes(conversation.id) ? <i className="size-1.5 shrink-0 rounded-full bg-ok" aria-label="有新结果" /> : null}
        <span className="truncate">{conversation.title}</span>
      </button>
      <Menu onOpenChange={(open) => { if (!open) setConfirmDelete(''); }}>
        <MenuTrigger asChild>
          <button aria-label={`${conversation.title} 的更多操作`}
            className="absolute right-1 grid size-6 place-items-center rounded-md text-fg-3 opacity-0 hover:bg-hover hover:text-fg group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100">
            <MoreHorizontal size={15} />
          </button>
        </MenuTrigger>
        <MenuContent align="start" className="min-w-[180px]">
          <MenuItem onSelect={() => setEditing({ id: conversation.id, title: conversation.title })}><Pencil />改名</MenuItem>
          {!isArchived && <MenuItem onSelect={() => props.onTogglePinned(conversation.id)}>{isPinned ? <><PinOff />取消置顶</> : <><Pin />置顶</>}</MenuItem>}
          <MenuItem onSelect={() => props.onToggleArchived(conversation.id)}>{isArchived ? <><ArchiveRestore />移出归档</> : <><Archive />归档</>}</MenuItem>
          <MenuItem onSelect={() => props.onDuplicate(conversation.id)}><CopyPlus />复制一份</MenuItem>
          <MenuItem onSelect={() => props.onExport(conversation.id)}><Download />导出为 JSON</MenuItem>
          <MenuSeparator />
          <MenuItem onSelect={(event) => {
            if (confirmDelete === conversation.id) { props.onDelete(conversation.id); setConfirmDelete(''); return; }
            event.preventDefault();
            setConfirmDelete(conversation.id);
          }}><span className="flex items-center gap-2.5 text-danger [&_svg]:!text-danger"><Trash2 />{confirmDelete === conversation.id ? '再点一次确认删除' : '删除'}</span></MenuItem>
        </MenuContent>
      </Menu>
    </div>;
  };
  return <aside aria-label="侧边栏" className={cn('flex min-h-0 flex-col pt-3 pb-3 transition-[width] duration-300', mini ? 'w-[64px] items-center px-2' : 'w-[236px] px-3')}>
    <div className={cn('drag flex items-center gap-2.5 pb-4', mini ? 'flex-col px-0' : 'px-1.5')}>
      <Mark className="size-7" />
      {!mini && <b className="font-serif text-[17px] font-semibold tracking-[.05em] text-heading">Atlas</b>}
      <Tip label={mini ? '展开侧边栏' : '收起侧边栏'} side="right">
        <button aria-label={mini ? '展开侧边栏' : '收起侧边栏'} onClick={props.onToggleMini}
          className={cn('no-drag grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg', !mini && 'ml-auto')}><PanelLeft size={16} /></button>
      </Tip>
    </div>

    <div className={cn('mb-4 flex gap-1.5', mini && 'flex-col')}>
      <Tip label="新任务 Ctrl N" side="right">
        <button onClick={props.onNewTask} disabled={props.creating} aria-label="新建对话"
          className={cn('card-surface flex h-9 items-center gap-2 rounded-[10px] text-[13.5px] font-medium text-fg hover:brightness-110 disabled:opacity-60',
            mini ? 'w-10 justify-center' : 'flex-1 px-3')}>
          <Plus size={17} className="text-brand" />{!mini && <><span>新任务</span><Kbd className="ml-auto">Ctrl N</Kbd></>}
        </button>
      </Tip>
      <Tip label="搜索和命令 Ctrl K" side="right">
        <button onClick={props.onSearch} aria-label="搜索和命令" className="grid size-9 place-items-center rounded-[10px] text-fg-2 hover:bg-hover hover:text-fg"><Search size={16} /></button>
      </Tip>
    </div>

    <nav aria-label="主导航" className="grid gap-0.5">
      {NAV.map(({ view, label, icon: Icon }) => {
        const current = props.view === view;
        return <Tip key={view} label={label} side="right">
          <button onClick={() => props.onGo(view)} aria-current={current ? 'page' : undefined}
            className={cn('relative flex h-[34px] items-center gap-2.5 rounded-[9px] text-[13.5px] transition-colors',
              mini ? 'w-10 justify-center' : 'px-2.5',
              current ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
            <Icon size={17} className={current ? 'text-brand' : undefined} />
            {!mini && <span>{label}</span>}
            {view === 'memory' && props.pendingMemories > 0 && (mini
              ? <span className="absolute top-1 right-1 size-2 rounded-full bg-brand" />
              : <span className="ml-auto grid h-[18px] min-w-[18px] place-items-center rounded-full bg-brand px-1.5 text-[11px] font-semibold text-on-primary">{props.pendingMemories}</span>)}
          </button>
        </Tip>;
      })}
    </nav>

    {!mini && <div className="mt-5 min-h-0 flex-1 overflow-auto pr-0.5" aria-label="历史任务">
      {pinnedItems.length > 0 && <section className="mb-3">
        <h3 className="m-0 px-2.5 pb-1 text-[12px] font-normal text-fg-3">置顶</h3>
        {pinnedItems.map(row)}
      </section>}
      {groups.map((group) => <section key={group.label} className="mb-3">
        <h3 className="m-0 px-2.5 pb-1 text-[12px] font-normal text-fg-3">{group.label}</h3>
        {group.items.map(row)}
      </section>)}
      {archivedItems.length > 0 && <section className="mb-3">
        <button onClick={() => setShowArchived((value) => !value)} aria-expanded={showArchived}
          className="flex w-full items-center gap-1 px-2.5 pb-1 text-left text-[12px] text-fg-3 hover:text-fg">
          <ChevronRight size={13} className={cn('transition-transform', showArchived && 'rotate-90')} />已归档 {archivedItems.length}
        </button>
        {showArchived && archivedItems.map(row)}
      </section>}
      {!props.conversations.length && <p className="px-2.5 text-[12.5px] text-fg-3">{props.conversationsLoading ? '正在加载…' : '还没有任务。点「新任务」开始。'}</p>}
    </div>}
    {mini && <div className="flex-1" />}

    <div className={cn('flex items-center gap-2.5 pt-2.5', mini ? 'flex-col' : 'px-1.5')}>
      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-[image:var(--avatar-bg)] text-[12.5px] font-semibold text-[var(--avatar-fg)]" aria-hidden="true">{props.username.slice(0, 1).toUpperCase()}</span>
      {!mini && <div className="min-w-0 flex-1 leading-tight">
        <div className="truncate text-[13px] text-fg">{props.username}</div>
        <div className="truncate text-[11.5px] text-fg-3">{props.subtitle}</div>
      </div>}
      <Tip label={`外观：${themeInfo(props.theme).label}，点击切换到${themeInfo(nextTheme(props.theme)).label}`} side="top">
        <button aria-label={`切换到${themeInfo(nextTheme(props.theme)).label}`} onClick={props.onToggleTheme} className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg">
          {props.theme === 'dark' ? <Moon size={15} /> : props.theme === 'aurora' ? <Sparkles size={15} /> : <Sun size={15} />}
        </button>
      </Tip>
      <Tip label="设置 Ctrl ," side="top">
        <button aria-label="设置" onClick={props.onSettings} className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><Settings size={15} /></button>
      </Tip>
    </div>
  </aside>;
}
