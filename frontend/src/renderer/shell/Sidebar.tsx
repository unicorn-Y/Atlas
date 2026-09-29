import { BookOpen, Code2, Home, Moon, PanelLeft, Plus, Puzzle, Repeat, Search, Settings, Sparkles, Sun, Wand2, type LucideIcon } from 'lucide-react';
import { nextTheme, themeInfo, type Theme } from './themes';
import type { ConversationSummary } from '@atlas/backend-adapter';
import Mark from '../components/Mark';
import { Kbd } from '../ui/Kbd';
import { Tip } from '../ui/Tooltip';
import { cn } from '../ui/cn';

export type View = 'home' | 'chat' | 'code' | 'create' | 'auto' | 'memory' | 'skills';

export const NAV: Array<{ view: View; label: string; icon: LucideIcon }> = [
  { view: 'home', label: '首页', icon: Home },
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
}

export default function Sidebar(props: SidebarProps) {
  const { mini } = props;
  const groups = groupByDay(props.conversations);
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
      {groups.map((group) => <section key={group.label} className="mb-3">
        <h3 className="m-0 px-2.5 pb-1 text-[12px] font-normal text-fg-3">{group.label}</h3>
        {group.items.map((conversation) => {
          const current = conversation.id === props.activeConversationId && props.view === 'chat';
          return <button key={conversation.id} title={conversation.title} aria-current={current ? 'page' : undefined}
            disabled={props.loadingConversationId === conversation.id} onClick={() => props.onOpenConversation(conversation)}
            className={cn('block w-full truncate rounded-lg px-2.5 py-1.5 text-left text-[13px] transition-colors disabled:opacity-60',
              current ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
            {conversation.title}
          </button>;
        })}
      </section>)}
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
