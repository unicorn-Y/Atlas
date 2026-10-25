// Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015c: packages/ui/src/TaskListItemContextMenu.tsx, packages/ui/src/TaskActionMenuContent.tsx, packages/ui/src/workspace-grouped-tasks/task-context-menu-content.tsx, packages/ui/src/workspace-grouped-tasks/WorkspaceGroupedTasksSection.tsx (Apache-2.0)
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from 'react';
import {
  Archive, ArchiveRestore, ArrowUpDown, AppWindow, Blocks, BookOpen, Bot, Check, ChevronLeft, ChevronRight, Code2, Columns2, Copy, CopyPlus, Download,
  Folder, FolderOpen, GitBranch, GripVertical, Home, Info, KanbanSquare, MessageSquare, MonitorSmartphone, Moon, MoreHorizontal, PanelLeft,
  Library, ListTodo, Pause, Pencil, Pin, PinOff, Play, Plus, Repeat, Search, Settings, Sparkles, Square, SquarePen, Sun, Trash2, Users, X, Wand2, type LucideIcon,
} from 'lucide-react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import type { AgentRun } from '../../types/runtime';
import { api } from '../services/api';
import { backend } from '../store/useAtlasStore';
import Mark from '../components/Mark';
import SidebarConversationDetails from '../components/sidebar/ConversationDetails';
import { ProjectIcon } from '../pages/ProjectIcon';
import { Kbd } from '../ui/Kbd';
import { Dialog } from '../ui/Dialog';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from '../ui/Menu';
import { Tip } from '../ui/Tooltip';
import { cn } from '../ui/cn';
import { nextTheme, themeInfo, type Theme } from './themes';
import { cleanSearchSnippet, rankSearchHits, searchHitRoleLabel } from '../services/searchHits';
import TriageBoardDialog from '../components/TriageBoardDialog';

export type View = 'home' | 'chat' | 'groups' | 'agents' | 'board' | 'code' | 'create' | 'auto' | 'memory' | 'skills' | 'devices' | 'evolution' | 'workbench' | 'library';

export const NAV: Array<{ view: View; label: string; icon: LucideIcon }> = [
  { view: 'chat', label: '聊天', icon: MessageSquare },
  { view: 'agents', label: 'Agents', icon: Bot },
  { view: 'workbench', label: '工作台', icon: Blocks },
  { view: 'memory', label: '记忆', icon: BookOpen },
  { view: 'auto', label: '自动化', icon: Repeat },
  { view: 'skills', label: '技能与工具', icon: Library },
  { view: 'devices', label: '设备', icon: MonitorSmartphone },
  { view: 'evolution', label: '自动追新', icon: Sparkles },
];

export const MORE_NAV: Array<{ view: View; label: string; icon: LucideIcon }> = [
  { view: 'groups', label: '群聊', icon: Users },
  { view: 'home', label: '首页', icon: Home },
  { view: 'board', label: '看板', icon: KanbanSquare },
  { view: 'code', label: '项目', icon: Code2 },
  { view: 'create', label: '创作', icon: Wand2 },
];

/** Untitled conversations show in Chinese whatever the backend default was. */
const displayTitle = (title?: string) => !title || title === 'New conversation' ? '新对话' : title;

const LABELS = [
  { id: 'red', name: '红', color: '#e5484d' }, { id: 'orange', name: '橙', color: '#f76b15' }, { id: 'yellow', name: '黄', color: '#e2a336' },
  { id: 'green', name: '绿', color: '#30a46c' }, { id: 'blue', name: '蓝', color: '#3e63dd' }, { id: 'purple', name: '紫', color: '#8e4ec6' },
] as const;
type Arrange = 'time' | 'project' | 'workspace' | 'custom' | 'label' | 'name';
type StatusFilter = 'all' | 'running' | 'waiting' | 'completed' | 'failed' | 'unread' | 'archived' | 'worktree';
type CustomGroup = { id: string; name: string };
type Project = { project_id: string; name: string; color?: string; icon?: string; workspace_path?: string; status?: string; pinned?: boolean; default_model?: string; default_preset_id?: string; conversation_ids?: string[] };
type Section = { id: string; label: string; items: ConversationSummary[]; custom?: boolean };
type Dragged = { kind: 'conversation' | 'section'; id: string; groupId?: string };
type ConversationActivity = { conversation_id: string; status: string; updated_at?: string; waiting_for?: string };
type ConversationActivityEvent = { event_id: string; run_id: string; conversation_id: string; timestamp: string; event: string; status: string; waiting_for?: string; detail?: unknown };
type SidebarShortcut = 'sidebar.search' | 'sidebar.project-picker' | 'sidebar.next-group' | 'sidebar.previous-group';

const ARRANGE: Record<Arrange, string> = {
  time: '按时间分组', project: '按项目分组', workspace: '按工作区分组',
  custom: '按自定义分组', label: '按颜色分组', name: '按名称排序',
};
const STATUS_FILTERS: Record<StatusFilter, string> = {
  all: '全部会话', running: '运行中', waiting: '等待中', completed: '已完成', failed: '失败',
  unread: '未读', archived: '已归档', worktree: '工作树',
};
const STORE_KEYS = {
  labels: 'atlas.sidebar.labels', arrange: 'atlas.sidebar.arrange', manualOrder: 'atlas.sidebar.order',
  sectionOrder: 'atlas.sidebar.section-order', groups: 'atlas.sidebar.custom-groups',
  members: 'atlas.sidebar.custom-members', collapsed: 'atlas.sidebar.collapsed', unread: 'atlas.sidebar.unread',
};
const readJson = <T,>(key: string, fallback: T): T => {
  try { const value = localStorage.getItem(key); return value ? JSON.parse(value) as T : fallback; } catch { return fallback; }
};
const writeJson = (key: string, value: unknown) => {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
};
const moveBefore = (order: string[], id: string, targetId?: string) => {
  const next = order.filter((item) => item !== id);
  const index = targetId ? next.indexOf(targetId) : -1;
  next.splice(index < 0 ? next.length : index, 0, id);
  return next;
};
const pathOf = (conversation: ConversationSummary) => conversation.worktree_path || conversation.workspace || '';
const recordOf = (conversation: ConversationSummary) => conversation as Record<string, unknown>;
const stringValue = (value: unknown) => typeof value === 'string' ? value : '';
const waitingConversation = (conversation: ConversationSummary) => {
  const record = recordOf(conversation);
  const status = [record.status, record.run_status, record.runtime_status].map((value) => stringValue(value).toLowerCase());
  return record.waiting_for_input === true || record.needs_input === true || record.awaiting_approval === true
    || record.attention_required === true
    || status.some((value) => ['waiting', 'waiting_for_input', 'needs_input', 'awaiting_input', 'awaiting_approval', 'approval_required'].includes(value));
};
const parseDate = (value: string | undefined) => {
  if (!value) return 0;
  const parsed = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : value + 'Z').getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
};
function groupByDay(conversations: ConversationSummary[]): Section[] {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const day = 86400000;
  const groups: Section[] = [
    { id: 'time:today', label: '今天', items: [] }, { id: 'time:yesterday', label: '昨天', items: [] },
    { id: 'time:week', label: '最近 7 天', items: [] }, { id: 'time:earlier', label: '更早', items: [] },
  ];
  for (const conversation of conversations) {
    const raw = conversation.updated_at ?? stringValue(recordOf(conversation).created_at);
    const time = parseDate(raw);
    const index = time >= startOfToday.getTime() ? 0 : time >= startOfToday.getTime() - day ? 1 : time >= startOfToday.getTime() - 7 * day ? 2 : 3;
    groups[index].items.push(conversation);
  }
  return groups.filter((group) => group.items.length > 0);
}

interface SidebarProps {
  view: View; onGo: (view: View) => void; mini: boolean; onToggleMini: () => void;
  conversations: ConversationSummary[]; conversationsLoading: boolean;
  runs?: AgentRun[];
  onPauseRun?: (runId: string) => void;
  onStopRun?: (runId: string) => void;
  activeConversationId: string; loadingConversationId: string | null;
  onOpenConversation: (conversation: ConversationSummary) => void; onNewTask: () => void; creating: boolean; onSearch: () => void;
  username: string; subtitle: string; theme: Theme; onToggleTheme: () => void; onSettings: () => void;
  pinned: string[]; archived: string[]; unread: string[]; running: string[]; subtaskUnreadCounts?: Record<string, number>;
  queued?: Record<string, number>;
  onRename: (id: string, title: string) => void; onDelete: (id: string) => void;
  onTogglePinned: (id: string) => void; onToggleArchived: (id: string) => void;
  onExport: (id: string, format: 'json' | 'md') => void; onDuplicate: (id: string) => void;
  onOpenBeside?: (id: string) => void;
  onOpenInWindow?: (id: string) => void;
  onSetUnread?: (id: string, unread: boolean) => void;
  onSetWorkspace?: (id: string, workspace: string) => void;
  onJumpMessage?: (conversationId: string, messageId: string) => void;
  waiting?: string[];
}

export default function Sidebar(props: SidebarProps) {
  const { mini } = props;
  const [showArchived, setShowArchived] = useState(false);
  const [triageOpen, setTriageOpen] = useState(false);
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState('');
  const [confirmArchive, setConfirmArchive] = useState('');
  const [labels, setLabels] = useState<Record<string, string>>(() => readJson(STORE_KEYS.labels, {}));
  const [manualUnread, setManualUnread] = useState<string[]>(() => readJson(STORE_KEYS.unread, []));
  const [metadataReady, setMetadataReady] = useState(false);
  const [mode, setMode] = useState<Arrange>(() => readJson<Arrange>(STORE_KEYS.arrange, 'time'));
  const [manualOrder, setManualOrder] = useState<string[]>(() => readJson(STORE_KEYS.manualOrder, []));
  const [sectionOrder, setSectionOrder] = useState<string[]>(() => readJson(STORE_KEYS.sectionOrder, []));
  const [customGroups, setCustomGroups] = useState<CustomGroup[]>(() => readJson(STORE_KEYS.groups, []));
  const [customMembers, setCustomMembers] = useState<Record<string, string>>(() => readJson(STORE_KEYS.members, {}));
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => readJson(STORE_KEYS.collapsed, {}));
  const [projects, setProjects] = useState<Project[]>([]);
  const [activityById, setActivityById] = useState<Record<string, ConversationActivity>>({});
  const [activityEvents, setActivityEvents] = useState<ConversationActivityEvent[]>([]);
  const [activityConversation, setActivityConversation] = useState<ConversationSummary | null>(null);
  const [filterText, setFilterText] = useState('');
  const [contentMatches, setContentMatches] = useState<string[] | null>(null);
  const [contentHits, setContentHits] = useState<Array<{ id: string | number; conversation_id: string; content: string; snippet?: string; title?: string; role?: string }>>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [projectPickerOpen, setProjectPickerOpen] = useState(false);
  const [projectPickerQuery, setProjectPickerQuery] = useState('');
  const [focusSearchRequested, setFocusSearchRequested] = useState(false);
  const [focusSectionId, setFocusSectionId] = useState('');
  const [searchDialogOpen, setSearchDialogOpen] = useState(false);
  const [groupNavigatorOpen, setGroupNavigatorOpen] = useState(false);
  const [draggingConversation, setDraggingConversation] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const [confirmBulkArchive, setConfirmBulkArchive] = useState(false);
  const [confirmProjectArchive, setConfirmProjectArchive] = useState('');
  const [details, setDetails] = useState<ConversationSummary | null>(null);
  const [groupEditor, setGroupEditor] = useState<{ id: string | null; name: string } | null>(null);
  const [menuOpenKey, setMenuOpenKey] = useState('');
  const [contextAnchor, setContextAnchor] = useState<{ key: string; x: number; y: number } | null>(null);
  const [feedback, setFeedback] = useState('');
  const triggerRefs = useRef(new Map<string, HTMLButtonElement>());
  const sectionRefs = useRef(new Map<string, HTMLButtonElement>());
  const searchInputRef = useRef<HTMLInputElement>(null);
  const dragged = useRef<Dragged | null>(null);
  const longPress = useRef<{ timer: ReturnType<typeof setTimeout>; x: number; y: number; key: string } | null>(null);
  const suppressTouchClickUntil = useRef(0);

  useEffect(() => {
    let stale = false;
    void api<{ metadata?: Record<string, unknown> }>(backend.apiBaseUrl, '/api/ui/conversation-metadata').then(async (result) => {
      if (stale) return;
      const remote = result.metadata ?? {};
      const keys = [STORE_KEYS.labels, STORE_KEYS.unread, STORE_KEYS.arrange, STORE_KEYS.manualOrder, STORE_KEYS.sectionOrder, STORE_KEYS.groups, STORE_KEYS.members];
      const local = Object.fromEntries(keys.map((key) => [key, readJson(key, undefined)]));
      const migrated = !Object.keys(remote).length;
      const value = (key: string) => remote[key] ?? (migrated ? local[key] : undefined);
      if (value(STORE_KEYS.labels)) setLabels(value(STORE_KEYS.labels) as Record<string, string>);
      if (value(STORE_KEYS.unread)) setManualUnread(value(STORE_KEYS.unread) as string[]);
      if (value(STORE_KEYS.arrange)) setMode(value(STORE_KEYS.arrange) as Arrange);
      if (value(STORE_KEYS.manualOrder)) setManualOrder(value(STORE_KEYS.manualOrder) as string[]);
      if (value(STORE_KEYS.sectionOrder)) setSectionOrder(value(STORE_KEYS.sectionOrder) as string[]);
      if (value(STORE_KEYS.groups)) setCustomGroups(value(STORE_KEYS.groups) as CustomGroup[]);
      if (value(STORE_KEYS.members)) setCustomMembers(value(STORE_KEYS.members) as Record<string, string>);
      setMetadataReady(true);
      if (migrated) await api(backend.apiBaseUrl, '/api/ui/conversation-metadata', { method: 'PUT', json: { metadata: Object.fromEntries(keys.map((key) => [key, local[key]]).filter(([, item]) => item !== undefined)) } });
    }).catch(() => { if (!stale) setMetadataReady(true); });
    return () => { stale = true; };
  }, []);
  useEffect(() => {
    if (!metadataReady) return;
    const metadata = { [STORE_KEYS.labels]: labels, [STORE_KEYS.unread]: manualUnread, [STORE_KEYS.arrange]: mode,
      [STORE_KEYS.manualOrder]: manualOrder, [STORE_KEYS.sectionOrder]: sectionOrder,
      [STORE_KEYS.groups]: customGroups, [STORE_KEYS.members]: customMembers };
    const timer = window.setTimeout(() => { void api(backend.apiBaseUrl, '/api/ui/conversation-metadata', { method: 'PUT', json: { metadata } }).catch(() => undefined); }, 250);
    return () => window.clearTimeout(timer);
  }, [metadataReady, labels, manualUnread, mode, manualOrder, sectionOrder, customGroups, customMembers]);
  useEffect(() => writeJson(STORE_KEYS.collapsed, collapsed), [collapsed]);
  useEffect(() => {
    if (props.activeConversationId) {
      setManualUnread((current) => current.filter((id) => id !== props.activeConversationId));
      props.onSetUnread?.(props.activeConversationId, false);
    }
  }, [props.activeConversationId]);
  useEffect(() => {
    const onTag = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string; label?: string | null }>).detail;
      if (!detail?.id) return;
      setLabel(detail.id, typeof detail.label === 'string' ? detail.label : null);
    };
    window.addEventListener('atlas:conversation-label', onTag);
    return () => window.removeEventListener('atlas:conversation-label', onTag);
  }, []);
  useEffect(() => {
    if (!props.conversationsLoading) {
      const currentIds = new Set(props.conversations.map((item) => item.id));
      setManualUnread((current) => current.filter((id) => currentIds.has(id)));
    }
  }, [props.conversations, props.conversationsLoading]);

  useEffect(() => {
    let stale = false;
    const refresh = () => {
      void api<{ projects: Project[] }>(backend.apiBaseUrl, '/api/projects?include_conversations=true')
        .then((result) => { if (!stale) setProjects(Array.isArray(result.projects) ? result.projects : []); })
        .catch(() => { if (!stale) setProjects([]); });
    };
    refresh();
    window.addEventListener('atlas:projects-updated', refresh);
    return () => { stale = true; window.removeEventListener('atlas:projects-updated', refresh); };
  }, []);
  useEffect(() => {
    let stale = false;
    const refresh = () => {
      void api<{ items: ConversationActivity[]; events?: ConversationActivityEvent[] }>(backend.apiBaseUrl, '/api/conversation-activity?limit=100')
        .then((result) => {
          if (stale || !Array.isArray(result.items)) return;
          setActivityById(Object.fromEntries(result.items.filter((item) => item?.conversation_id).map((item) => [item.conversation_id, item])));
          setActivityEvents(Array.isArray(result.events) ? result.events : []);
        })
        .catch(() => { /* status props remain available while the activity endpoint is unavailable */ });
    };
    refresh();
    window.addEventListener('atlas:session-status-activity', refresh);
    return () => { stale = true; window.removeEventListener('atlas:session-status-activity', refresh); };
  }, []);
  useEffect(() => () => { if (longPress.current) clearTimeout(longPress.current.timer); }, []);
  useEffect(() => {
    const query = filterText.trim();
    if (!query) { setContentMatches(null); setContentHits([]); return; }
    let stale = false;
    const timer = window.setTimeout(() => {
      void api<Array<{ id: string | number; conversation_id: string; content: string; snippet?: string; title?: string; role?: string }>>(backend.apiBaseUrl, `/api/search?limit=100&q=${encodeURIComponent(query)}`)
        .then((rows) => { if (!stale) { setContentHits(rankSearchHits(rows)); setContentMatches([...new Set(rows.map((row) => row.conversation_id))]); } })
        .catch(() => { if (!stale) { setContentMatches([]); setContentHits([]); } });
    }, 180);
    return () => { stale = true; window.clearTimeout(timer); };
  }, [filterText]);

  const setLabel = (id: string, label: string | null) => setLabels((current) => {
    const next = { ...current };
    if (label && current[id] !== label) next[id] = label;
    else delete next[id];
    return next;
  });
  const toggleSelected = (id: string) => setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  const activityStatus = (id: string) => activityById[id]?.status?.toLowerCase() ?? '';
  const isRunning = (id: string) => activityById[id]
    ? ['running', 'queued', 'starting'].includes(activityStatus(id)) : props.running.includes(id);
  const isUnread = (id: string) => props.unread.includes(id) || manualUnread.includes(id);
  const isWaiting = (conversation: ConversationSummary) => activityById[conversation.id]
    ? Boolean(activityById[conversation.id].waiting_for || ['waiting', 'waiting_for_input', 'awaiting_approval'].includes(activityStatus(conversation.id)))
    : Boolean(props.waiting?.includes(conversation.id) || waitingConversation(conversation));
  const query = filterText.trim().toLocaleLowerCase();
  const matches = (conversation: ConversationSummary) => {
    const relatedProjects = projects.filter((project) => (project.conversation_ids ?? []).includes(conversation.id)).map((project) => project.name);
    const selectedLabel = labels[conversation.id];
    const text = [conversation.title, conversation.id, pathOf(conversation), conversation.worktree_branch, conversation.base_branch, selectedLabel, LABELS.find((label) => label.id === selectedLabel)?.name, ...relatedProjects].join(' ').toLocaleLowerCase();
    const titleMatch = !query || text.includes(query);
    const contentMatch = !query || (contentMatches?.includes(conversation.id) ?? false);
    if (query && !titleMatch && !contentMatch) return false;
    const archived = props.archived.includes(conversation.id);
    if (statusFilter === 'archived') return archived;
    if (archived) return false;
    if (statusFilter === 'running') return isRunning(conversation.id);
    if (statusFilter === 'unread') return isUnread(conversation.id);
    if (statusFilter === 'waiting') return isWaiting(conversation);
    if (statusFilter === 'completed') return ['completed', 'succeeded', 'success'].includes(activityStatus(conversation.id));
    if (statusFilter === 'failed') return ['failed', 'error'].includes(activityStatus(conversation.id));
    if (statusFilter === 'worktree') return Boolean(conversation.worktree_path || conversation.worktree_branch || conversation.base_branch);
    return true;
  };
  const sortedItems = (items: ConversationSummary[]) => {
    const rank = new Map(manualOrder.map((id, index) => [id, index]));
    const original = new Map(items.map((item, index) => [item.id, index]));
    return [...items].sort((a, b) => {
      const aRank = rank.get(a.id) ?? manualOrder.length + (original.get(a.id) ?? 0);
      const bRank = rank.get(b.id) ?? manualOrder.length + (original.get(b.id) ?? 0);
      return aRank - bRank;
    });
  };

  const allMatched = props.conversations.filter(matches);
  const pinnedItems = sortedItems(allMatched.filter((item) => props.pinned.includes(item.id) && !props.archived.includes(item.id)));
  const archivedItems = sortedItems(allMatched.filter((item) => props.archived.includes(item.id)));
  const activeItems = sortedItems(allMatched.filter((item) => !props.pinned.includes(item.id) && !props.archived.includes(item.id)));
  const activeProjects = projects.filter((project) => project.status !== 'archived').sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)));
  const projectIds = new Set(activeProjects.flatMap((project) => project.conversation_ids ?? []));
  let groups: Section[] = [];
  if (mode === 'time') groups = groupByDay(activeItems);
  else if (mode === 'name') groups = activeItems.length ? [{ id: 'name:all', label: '全部', items: [...activeItems].sort((a, b) => (a.title || '').localeCompare(b.title || '', 'zh-CN')) }] : [];
  else if (mode === 'label') {
    groups = LABELS.map((label) => ({ id: 'label:' + label.id, label: label.name + '色', items: activeItems.filter((item) => labels[item.id] === label.id) }))
      .concat([{ id: 'label:none', label: '未标记', items: activeItems.filter((item) => !labels[item.id]) }]);
  } else if (mode === 'project') {
    groups = activeProjects.map((project) => ({
      id: 'project:' + project.project_id, label: project.name || '未命名项目',
      items: activeItems.filter((item) => (project.conversation_ids ?? []).includes(item.id)),
    }));
    const unassigned = activeItems.filter((item) => !projectIds.has(item.id));
    groups.push({ id: 'project:unassigned', label: '未关联项目', items: unassigned });
    if (!groups.length && activeItems.length) groups = [{ id: 'project:unassigned', label: activeProjects.length ? '未关联项目' : '项目尚未加载', items: activeItems }];
  } else if (mode === 'workspace') {
    const byWorkspace = new Map<string, ConversationSummary[]>();
    for (const item of activeItems) {
      const workspace = pathOf(item) || '无工作区';
      const list = byWorkspace.get(workspace) ?? [];
      list.push(item);
      byWorkspace.set(workspace, list);
    }
    groups = [...byWorkspace.entries()].map(([workspace, items]) => ({ id: 'workspace:' + workspace, label: workspace, items }));
  } else {
    groups = customGroups.map((group) => ({
      id: 'custom:' + group.id, label: group.name, custom: true,
      items: activeItems.filter((item) => customMembers[item.id] === group.id),
    }));
    const unassigned = activeItems.filter((item) => !customMembers[item.id] || !customGroups.some((group) => group.id === customMembers[item.id]));
    groups.push({ id: 'custom:unassigned', label: '未分组', custom: true, items: unassigned });
  }
  const sectionRanks = new Map(sectionOrder.map((id, index) => [id, index]));
  groups = [...groups].sort((a, b) => (sectionRanks.get(a.id) ?? sectionOrder.length) - (sectionRanks.get(b.id) ?? sectionOrder.length));
  useEffect(() => {
    if (mini || !focusSearchRequested) return;
    searchInputRef.current?.focus();
    setFocusSearchRequested(false);
  }, [mini, focusSearchRequested]);
  useEffect(() => {
    if (mini || !focusSectionId) return;
    const heading = sectionRefs.current.get(focusSectionId);
    if (!heading) return;
    heading.scrollIntoView({ block: 'nearest' });
    heading.focus();
  }, [mini, mode, focusSectionId, projects, customGroups]);
  useEffect(() => {
    const onShortcut = (event: Event) => {
      const detail = (event as CustomEvent<SidebarShortcut | { action: SidebarShortcut }>).detail;
      const action = typeof detail === 'string' ? detail : detail?.action;
      const forcedMini = mini && window.matchMedia('(max-width: 900px)').matches;
      if (action === 'sidebar.search') {
        if (forcedMini) setSearchDialogOpen(true);
        else { if (mini) props.onToggleMini(); setFocusSearchRequested(true); }
      } else if (action === 'sidebar.project-picker') {
        setProjectPickerQuery('');
        setProjectPickerOpen(true);
      } else if (action === 'sidebar.next-group' || action === 'sidebar.previous-group') {
        if (!groups.length) { setGroupNavigatorOpen(true); return; }
        const current = groups.findIndex((group) => group.id === focusSectionId);
        const next = action === 'sidebar.next-group'
          ? (current + 1) % groups.length : (current < 0 ? groups.length - 1 : (current - 1 + groups.length) % groups.length);
        const id = groups[next].id;
        if (forcedMini) setGroupNavigatorOpen(true);
        else if (mini) props.onToggleMini();
        setCollapsed((value) => ({ ...value, [id]: false }));
        setFocusSectionId(id);
        if (!forcedMini) requestAnimationFrame(() => { sectionRefs.current.get(id)?.scrollIntoView({ block: 'nearest' }); sectionRefs.current.get(id)?.focus(); });
      }
    };
    window.addEventListener('atlas:sidebar-shortcut', onShortcut);
    return () => window.removeEventListener('atlas:sidebar-shortcut', onShortcut);
  });

  const setUnread = (id: string, unread: boolean) => {
    props.onSetUnread?.(id, unread);
    setManualUnread((current) => unread
      ? current.includes(id) ? current : [...current, id]
      : current.filter((item) => item !== id));
  };
  const copyText = async (text: string, label: string) => {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else {
        const input = document.createElement('textarea');
        input.value = text;
        input.style.position = 'fixed';
        input.style.opacity = '0';
        document.body.append(input);
        input.select();
        const copied = document.execCommand('copy');
        input.remove();
        if (!copied) throw new Error('复制失败');
      }
      setFeedback(label + '已复制');
    } catch { setFeedback('复制失败，请检查剪贴板权限'); }
  };
  const detachFromProject = async (projectId: string, conversationId: string) => {
    try {
      await api(backend.apiBaseUrl, '/api/projects/' + encodeURIComponent(projectId) + '/conversations/' + encodeURIComponent(conversationId), { method: 'DELETE' });
      setProjects((current) => current.map((project) => project.project_id === projectId
        ? { ...project, conversation_ids: (project.conversation_ids ?? []).filter((id) => id !== conversationId) }
        : project));
      setFeedback('已从项目移除');
    } catch (error) { setFeedback('移出项目失败：' + (error instanceof Error ? error.message : String(error))); }
  };
  const moveToProject = async (projectId: string, conversationId: string) => {
    const attached = projects.filter((project) => (project.conversation_ids ?? []).includes(conversationId));
    if (attached.length === 1 && attached[0].project_id === projectId) return;
    try {
      if (!attached.some((project) => project.project_id === projectId)) {
        await api(backend.apiBaseUrl, '/api/projects/' + encodeURIComponent(projectId) + '/conversations', { method: 'POST', json: { conversation_id: conversationId } });
      }
      for (const project of attached) {
        if (project.project_id !== projectId) {
          await api(backend.apiBaseUrl, '/api/projects/' + encodeURIComponent(project.project_id) + '/conversations/' + encodeURIComponent(conversationId), { method: 'DELETE' });
        }
      }
      setProjects((current) => current.map((project) => project.project_id === projectId
        ? { ...project, conversation_ids: [...new Set([...(project.conversation_ids ?? []), conversationId])] }
        : { ...project, conversation_ids: (project.conversation_ids ?? []).filter((id) => id !== conversationId) }));
      setFeedback('已移动到项目');
    } catch (error) {
      void api<{ projects: Project[] }>(backend.apiBaseUrl, '/api/projects?include_conversations=true')
        .then((result) => setProjects(Array.isArray(result.projects) ? result.projects : []))
        .catch(() => undefined);
      setFeedback('移动项目失败：' + (error instanceof Error ? error.message : String(error)));
    }
  };
  const openWorkspace = async (conversation: ConversationSummary) => {
    const path = pathOf(conversation);
    if (!path || path.startsWith('ssh://') || !window.atlasDesktop?.openPath) return;
    try {
      const result = await window.atlasDesktop.openPath(path);
      setFeedback(result === 'opened' || result === 'revealed' ? '已打开工作区目录' : '打开目录失败：' + result);
    } catch (error) { setFeedback('打开目录失败：' + (error instanceof Error ? error.message : String(error))); }
  };
  const chooseConversationWorkspace = async (conversation: ConversationSummary) => {
    if (!props.onSetWorkspace || !window.atlasDesktop?.selectDirectory) return;
    try {
      const selected = await window.atlasDesktop.selectDirectory(pathOf(conversation) || undefined);
      if (!selected) return;
      props.onSetWorkspace(conversation.id, selected);
      setFeedback('已更改后续工作目录');
    } catch (error) { setFeedback('更改工作目录失败：' + (error instanceof Error ? error.message : String(error))); }
  };
  const copyLogLocation = async (conversationId: string) => {
    try {
      const result = await api<{ path: string }>(backend.apiBaseUrl, `/api/conversations/${encodeURIComponent(conversationId)}/log-location`);
      await copyText(result.path, '会话日志数据库路径');
    } catch (error) { setFeedback('读取会话日志路径失败：' + (error instanceof Error ? error.message : String(error))); }
  };
  const commitRename = () => {
    if (editing && editing.title.trim() && editing.title.trim() !== props.conversations.find((item) => item.id === editing.id)?.title) props.onRename(editing.id, editing.title.trim());
    setEditing(null);
  };
  const openContextAt = (key: string, x: number, y: number) => {
    setContextAnchor({ key, x: Math.max(0, Math.min(x, window.innerWidth - 220)), y: Math.max(0, Math.min(y, window.innerHeight - 48)) });
    setMenuOpenKey(key);
  };
  const openContext = (event: ReactMouseEvent, key: string) => {
    event.preventDefault(); event.stopPropagation();
    openContextAt(key, event.clientX, event.clientY);
  };
  const openContextFromKeyboard = (event: ReactKeyboardEvent, key: string) => {
    if (event.key !== 'ContextMenu' && !(event.key === 'F10' && event.shiftKey)) return;
    event.preventDefault(); event.stopPropagation();
    const bounds = event.currentTarget.getBoundingClientRect();
    openContextAt(key, bounds.left + Math.min(bounds.width / 2, 90), bounds.bottom);
  };
  const clearLongPress = () => {
    if (longPress.current) clearTimeout(longPress.current.timer);
    longPress.current = null;
  };
  const startLongPress = (event: ReactPointerEvent, key: string) => {
    clearLongPress();
    if (event.pointerType !== 'touch') return;
    const { clientX: x, clientY: y } = event;
    longPress.current = { key, x, y, timer: setTimeout(() => {
      suppressTouchClickUntil.current = Date.now() + 800;
      openContextAt(key, x, y);
      longPress.current = null;
    }, 550) };
  };
  const moveLongPress = (event: ReactPointerEvent) => {
    const touch = longPress.current;
    if (touch && Math.hypot(event.clientX - touch.x, event.clientY - touch.y) > 10) clearLongPress();
  };
  const canDropOn = (targetGroup: string) => {
    const source = dragged.current;
    if (!source) return false;
    if (source.kind === 'section') return source.id !== targetGroup && groups.some((group) => group.id === targetGroup);
    if (targetGroup === 'pinned' || targetGroup === 'archived') return true;
    if (mode === 'time' || mode === 'name') return source.groupId === targetGroup;
    if (mode === 'workspace') return Boolean(props.onSetWorkspace)
      && !props.conversations.find((item) => item.id === source.id)?.worktree_path
      && targetGroup !== 'workspace:无工作区';
    return targetGroup.startsWith(mode + ':');
  };
  const dropConversation = (targetGroup: string, targetId?: string) => {
    const source = dragged.current;
    const allowed = canDropOn(targetGroup);
    dragged.current = null;
    setDraggingConversation(false);
    if (!source || !allowed) return;
    if (source.kind === 'section') {
      setSectionOrder(moveBefore(groups.map((group) => group.id), source.id, targetGroup));
      return;
    }
    if (source.id === targetId) return;
    if (targetGroup !== 'pinned' && props.pinned.includes(source.id)) props.onTogglePinned(source.id);
    if (targetGroup !== 'archived' && props.archived.includes(source.id)) props.onToggleArchived(source.id);
    if (mode === 'custom' && targetGroup.startsWith('custom:')) {
      const customId = targetGroup.slice('custom:'.length);
      setCustomMembers((current) => {
        const next = { ...current };
        if (customId === 'unassigned') delete next[source.id];
        else next[source.id] = customId;
        return next;
      });
    }
    if (mode === 'project' && targetGroup.startsWith('project:')) {
      const projectId = targetGroup.slice('project:'.length);
      if (projectId === 'unassigned') {
        for (const project of projects) if ((project.conversation_ids ?? []).includes(source.id)) void detachFromProject(project.project_id, source.id);
      } else {
        void moveToProject(projectId, source.id);
      }
    }
    if (mode === 'label' && targetGroup.startsWith('label:')) setLabels((current) => {
      const next = { ...current };
      if (targetGroup === 'label:none') delete next[source.id];
      else next[source.id] = targetGroup.slice('label:'.length);
      return next;
    });
    if (mode === 'workspace' && targetGroup.startsWith('workspace:')) props.onSetWorkspace?.(source.id, targetGroup.slice('workspace:'.length));
    if (targetGroup === 'pinned' && !props.pinned.includes(source.id)) props.onTogglePinned(source.id);
    if (targetGroup === 'archived' && !props.archived.includes(source.id)) props.onToggleArchived(source.id);
    const visible = [...new Set([...pinnedItems, ...groups.flatMap((group) => group.items), ...archivedItems].map((item) => item.id))];
    const targetItems = groups.find((group) => group.id === targetGroup)?.items.map((item) => item.id).filter((id) => id !== source.id) ?? [];
    const lastIndex = targetItems.length ? visible.indexOf(targetItems[targetItems.length - 1]) : -1;
    const beforeId = targetId ?? (lastIndex >= 0 ? visible[lastIndex + 1] : undefined);
    setManualOrder(moveBefore([...new Set([...manualOrder, ...visible])], source.id, beforeId));
  };
  const bulk = (action: 'pin' | 'unread' | 'archive' | 'delete' | 'export-md' | 'export-json') => {
    const targets = [...new Set(selectedIds.filter((id) => props.conversations.some((conversation) => conversation.id === id)))];
    if (action === 'pin') targets.filter((id) => !props.pinned.includes(id) && !props.archived.includes(id)).forEach(props.onTogglePinned);
    if (action === 'unread') targets.forEach((id) => setUnread(id, true));
    if (action === 'archive') {
      if (!confirmBulkArchive) { setConfirmBulkArchive(true); return; }
      targets.filter((id) => !props.archived.includes(id)).forEach(props.onToggleArchived);
      setConfirmBulkArchive(false);
    }
    if (action === 'delete') {
      if (!confirmBulkDelete) { setConfirmBulkDelete(true); return; }
      targets.forEach(props.onDelete);
      setConfirmBulkDelete(false);
      setSelectedIds([]);
      setSelectionMode(false);
    }
    if (action === 'export-md') targets.forEach((id) => props.onExport(id, 'md'));
    if (action === 'export-json') targets.forEach((id) => props.onExport(id, 'json'));
  };
  const createCustomGroup = () => {
    const editor = groupEditor;
    const name = editor?.name.trim();
    if (!editor || !name) return;
    if (editor.id) setCustomGroups((current) => current.map((group) => group.id === editor.id ? { ...group, name } : group));
    else setCustomGroups((current) => [...current, { id: crypto.randomUUID(), name }]);
    setMode('custom');
    setGroupEditor(null);
  };
  const removeCustomGroup = (id: string) => {
    setCustomGroups((current) => current.filter((group) => group.id !== id));
    setCustomMembers((current) => Object.fromEntries(Object.entries(current).filter(([, groupId]) => groupId !== id)));
  };

  const row = (conversation: ConversationSummary, groupId = 'all') => {
    const key = groupId + ':' + conversation.id;
    const navigationIndex = props.conversations.findIndex((item) => item.id === conversation.id);
    const previousConversation = navigationIndex >= 0 ? props.conversations[navigationIndex + 1] : undefined;
    const nextConversation = navigationIndex > 0 ? props.conversations[navigationIndex - 1] : undefined;
    const current = conversation.id === props.activeConversationId && props.view === 'chat';
    const isPinned = props.pinned.includes(conversation.id);
    const isArchived = props.archived.includes(conversation.id);
    const unread = isUnread(conversation.id);
    const subtaskUnreadCount = props.subtaskUnreadCounts?.[conversation.id] ?? 0;
    const running = isRunning(conversation.id);
    const run = [...(props.runs ?? [])].reverse().find((item) => item.conversationId === conversation.id && !['completed', 'failed', 'cancelled'].includes(item.status));
    const background = Boolean(run?.background);
    const waiting = isWaiting(conversation);
    const completed = ['completed', 'succeeded', 'success'].includes(activityStatus(conversation.id));
    const failed = ['failed', 'error'].includes(activityStatus(conversation.id));
    const queued = props.queued?.[conversation.id] ?? 0;
    const workspace = pathOf(conversation);
    if (editing?.id === conversation.id) {
      return <input key={key} autoFocus aria-label="会话名称" value={editing.title}
        onChange={(event) => setEditing({ id: conversation.id, title: event.target.value })}
        onBlur={commitRename}
        onKeyDown={(event) => { if (event.key === 'Enter') commitRename(); else if (event.key === 'Escape') setEditing(null); }}
        className="block w-full rounded-lg bg-sunken px-2.5 py-1.5 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--brand)]" />;
    }
    return <div key={key} draggable onDragStart={(event) => {
      clearLongPress();
      dragged.current = { kind: 'conversation', id: conversation.id, groupId };
      setDraggingConversation(true);
      event.dataTransfer.setData('text/plain', conversation.id);
      event.dataTransfer.effectAllowed = 'move';
    }} onDragEnd={() => { dragged.current = null; setDraggingConversation(false); }} onDragOver={(event) => { if (canDropOn(groupId)) event.preventDefault(); }} onDrop={(event) => {
      event.preventDefault(); event.stopPropagation(); dropConversation(groupId, conversation.id);
    }} onContextMenu={(event) => openContext(event, key)} onKeyDown={(event) => openContextFromKeyboard(event, key)}
      onPointerDown={(event) => startLongPress(event, key)} onPointerMove={moveLongPress}
      onPointerUp={clearLongPress} onPointerCancel={clearLongPress} onPointerLeave={clearLongPress}
      className={cn('group relative flex cursor-grab items-center rounded-lg transition-colors', current ? 'bg-selected' : 'hover:bg-hover')} data-current={current || undefined}>
      {selectionMode && <input type="checkbox" aria-label={'选择 ' + conversation.title} checked={selectedIds.includes(conversation.id)}
        onChange={() => toggleSelected(conversation.id)} className="ml-2 accent-[var(--brand)]" />}
      <button title={conversation.title} aria-current={current ? 'page' : undefined}
        aria-label={conversation.title + (waiting ? '，等待输入或审批' : running ? '，正在运行' : failed ? '，运行失败' : completed ? '，已完成' : '') + (unread ? '，有新结果' : '') + (queued ? `，${queued} 条待发送` : '')}
        disabled={props.loadingConversationId === conversation.id}
        onClick={(event) => { if (Date.now() < suppressTouchClickUntil.current) { event.preventDefault(); return; } selectionMode ? toggleSelected(conversation.id) : props.onOpenConversation(conversation); }}
        onDoubleClick={() => setEditing({ id: conversation.id, title: conversation.title })}
        className={cn('flex h-8 min-w-0 flex-1 items-center gap-2 pr-7 pl-2.5 text-left text-[13.5px] disabled:opacity-60', current ? 'text-fg' : 'text-fg-2 group-hover:text-fg')}>
        {waiting
          ? <i className="size-2 shrink-0 rounded-full bg-brand ring-2 ring-brand/20" aria-label="等待输入或审批" />
          : running
            ? <i className="size-1.5 shrink-0 animate-pulse rounded-full bg-brand" aria-label="正在运行" />
            : failed
              ? <i className="size-2 shrink-0 rounded-full bg-danger" aria-label="运行失败" />
              : completed
                ? <Check size={12} className="shrink-0 text-ok" aria-label="已完成" />
                : unread
              ? <i className="size-1.5 shrink-0 rounded-full bg-ok" aria-label="有新结果" />
              : labels[conversation.id] ? <i className="size-2 shrink-0 rounded-[3px]" style={{ background: LABELS.find((label) => label.id === labels[conversation.id])?.color }} aria-label={(LABELS.find((label) => label.id === labels[conversation.id])?.name || '') + '色标签'} />
                : null}
        <span className="truncate">{displayTitle(conversation.title)}</span>
        {background && run && !mini && <span className="shrink-0 rounded bg-brand/10 px-1.5 py-0.5 text-[10px] text-brand">后台 · {run.status === 'waiting' ? '等待你' : run.status === 'paused' ? '已暂停' : run.phase === 'verification' ? '验证' : run.phase === 'execution' ? '执行' : '规划'}</span>}
        {(conversation.worktree_path || conversation.worktree_branch) && <GitBranch size={12} className="shrink-0 text-fg-3" aria-label={'工作树' + (conversation.worktree_branch ? '：' + conversation.worktree_branch : '')} />}
        {unread && (waiting || running || completed || failed) && <i className="size-1.5 shrink-0 rounded-full bg-ok" aria-label="有新结果" />}
        {subtaskUnreadCount > 0 && <span className="shrink-0 rounded bg-brand/15 px-1.5 text-[10px] font-medium text-brand" aria-label={`${subtaskUnreadCount} 条子任务未读更新`}>{subtaskUnreadCount} 条更新</span>}
        {queued > 0 && <span className="shrink-0 rounded bg-brand/15 px-1 text-[10px] text-brand" title={`${queued} 条消息待发送`}>{queued}</span>}
      </button>
      <Menu open={menuOpenKey === key} onOpenChange={(open) => {
        setMenuOpenKey(open ? key : '');
        if (!open) { setContextAnchor(null); setConfirmDelete(''); setConfirmArchive(''); }
      }}>
        <MenuTrigger asChild>
          <button ref={(node) => { if (node) triggerRefs.current.set(key, node); else triggerRefs.current.delete(key); }}
            aria-label={conversation.title + ' 的更多操作'}
            style={contextAnchor?.key === key ? { position: 'fixed', left: contextAnchor.x, top: contextAnchor.y, width: 1, height: 1, opacity: 0 } : undefined}
            className="absolute right-1 grid size-6 place-items-center rounded-md text-fg-3 opacity-0 hover:bg-hover hover:text-fg group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100">
            <MoreHorizontal size={15} />
          </button>
        </MenuTrigger>
        <MenuContent align="start" className="min-w-[205px]">
          <MenuLabel>{conversation.title || '会话操作'}</MenuLabel>
          <MenuItem onSelect={() => setDetails(conversation)}><Info />会话信息</MenuItem>
          <MenuItem onSelect={() => setActivityConversation(conversation)}><Repeat />运行动态</MenuItem>
          {run && <>
            <MenuItem disabled={!props.onPauseRun} onSelect={() => props.onPauseRun?.(run.id)}>{run.status === 'paused' ? <Play /> : <Pause />}{run.status === 'paused' ? '继续后台任务' : '暂停后台任务'}</MenuItem>
            <MenuItem disabled={!props.onStopRun} onSelect={() => props.onStopRun?.(run.id)}><Square />终止任务</MenuItem>
          </>}
          <MenuItem disabled={!previousConversation} onSelect={() => { if (previousConversation) props.onOpenConversation(previousConversation); }}><ChevronLeft />上一个会话（更早）</MenuItem>
          <MenuItem disabled={!nextConversation} onSelect={() => { if (nextConversation) props.onOpenConversation(nextConversation); }}><ChevronRight />下一个会话（更新）</MenuItem>
          <MenuItem onSelect={() => setEditing({ id: conversation.id, title: conversation.title })}><Pencil />重命名</MenuItem>
          <MenuItem onSelect={() => setManualOrder((current) => [conversation.id, ...current.filter((id) => id !== conversation.id)])}><ArrowUpDown />移到顶部</MenuItem>
          <div className="flex items-center gap-1.5 px-2.5 py-1.5" role="group" aria-label="颜色标签">
            {LABELS.map((label) => <button key={label.id} type="button" aria-label={label.name + '色'} aria-pressed={labels[conversation.id] === label.id}
              onClick={() => setLabel(conversation.id, label.id)}
              className="grid size-5 place-items-center rounded-full outline-none ring-offset-1 ring-offset-[var(--overlay)] hover:ring-2 hover:ring-line-strong focus-visible:ring-2 focus-visible:ring-brand"
              style={{ background: label.color }}>{labels[conversation.id] === label.id && <Check size={11} className="text-white" strokeWidth={3} />}</button>)}
          </div>
          <MenuItem onSelect={() => void copyText(conversation.id, '会话 ID')}><Copy />复制会话 ID</MenuItem>
          <MenuItem onSelect={() => void copyLogLocation(conversation.id)}><Copy />复制会话日志数据库路径</MenuItem>
          <MenuItem disabled={!workspace} onSelect={() => void copyText(workspace, '工作区路径')}><Copy />复制工作区路径</MenuItem>
          <MenuItem disabled={!window.atlasDesktop?.openPath || !workspace || workspace.startsWith('ssh://')} onSelect={() => void openWorkspace(conversation)}><Folder />在资源管理器打开工作区</MenuItem>
          <MenuItem disabled={!window.atlasDesktop?.selectDirectory || !props.onSetWorkspace} onSelect={() => void chooseConversationWorkspace(conversation)}><FolderOpen />更改后续工作目录</MenuItem>
          <MenuItem disabled={!props.onSetUnread} onSelect={() => setUnread(conversation.id, !unread)}><Check />{unread ? '标记已读' : '标记未读'}</MenuItem>
          {!isArchived && <MenuItem onSelect={() => props.onTogglePinned(conversation.id)}>{isPinned ? <><PinOff />取消置顶</> : <><Pin />置顶</>}</MenuItem>}
          <MenuItem onSelect={(event) => {
            if (isArchived) { props.onToggleArchived(conversation.id); return; }
            if (confirmArchive === key) { props.onToggleArchived(conversation.id); setConfirmArchive(''); return; }
            event.preventDefault(); setConfirmArchive(key);
          }}>{isArchived ? <><ArchiveRestore />移出归档</> : <><Archive />{confirmArchive === key ? '确认归档' : '归档'}</>}</MenuItem>
          {projects.length > 0 && <>
            <MenuSeparator /><MenuLabel>项目关联</MenuLabel>
            {projects.map((project) => {
              const attached = (project.conversation_ids ?? []).includes(conversation.id);
              return <MenuItem key={project.project_id} checked={attached} onSelect={() => void moveToProject(project.project_id, conversation.id)}>
                <Folder />{attached ? '当前项目：' + project.name : '移动到 ' + project.name}
              </MenuItem>;
            })}
          </>}
          {customGroups.length > 0 && <>
            <MenuSeparator /><MenuLabel>移动到自定义分组</MenuLabel>
            <MenuItem checked={!customMembers[conversation.id]} onSelect={() => setCustomMembers((current) => {
              const next = { ...current }; delete next[conversation.id]; return next;
            })}>未分组</MenuItem>
            {customGroups.map((group) => <MenuItem key={group.id} checked={customMembers[conversation.id] === group.id}
              onSelect={() => setCustomMembers((current) => ({ ...current, [conversation.id]: group.id }))}><Users />{group.name}</MenuItem>)}
          </>}
          {props.onOpenBeside && !current && props.view === 'chat' && <MenuItem onSelect={() => props.onOpenBeside?.(conversation.id)}><Columns2 />在旁边打开</MenuItem>}
          {props.onOpenInWindow && <MenuItem onSelect={() => props.onOpenInWindow?.(conversation.id)}><AppWindow />在新窗口打开</MenuItem>}
          <MenuItem onSelect={() => props.onDuplicate(conversation.id)}><CopyPlus />复制一份</MenuItem>
          <MenuItem onSelect={() => props.onExport(conversation.id, 'md')}><Download />导出为 Markdown</MenuItem>
          <MenuItem onSelect={() => props.onExport(conversation.id, 'json')}><Download />导出为 JSON</MenuItem>
          <MenuSeparator />
          <MenuItem onSelect={(event) => {
            if (confirmDelete === key) { props.onDelete(conversation.id); setConfirmDelete(''); return; }
            event.preventDefault(); setConfirmDelete(key);
          }}><span className="flex items-center gap-2.5 text-danger [&_svg]:!text-danger"><Trash2 />{confirmDelete === key ? '再点一次确认删除' : '删除'}</span></MenuItem>
        </MenuContent>
      </Menu>
    </div>;
  };

  const renderSection = (section: Section) => {
    const project = section.id.startsWith('project:') ? projects.find((item) => `project:${item.project_id}` === section.id) : undefined;
    const archiveableProjectConversations = project
      ? props.conversations.filter((item) => (project.conversation_ids ?? []).includes(item.id) && !props.archived.includes(item.id))
      : [];
    return <section key={section.id} onDragOver={(event) => { if (canDropOn(section.id)) event.preventDefault(); }}
    onDrop={(event) => { event.preventDefault(); dropConversation(section.id); }} className="mb-2">
    <div draggable onDragStart={(event) => {
      dragged.current = { kind: 'section', id: section.id };
      event.dataTransfer.setData('text/plain', 'section:' + section.id);
      event.dataTransfer.effectAllowed = 'move';
    }} onDragEnd={() => { dragged.current = null; }}
    className="group/section flex items-center gap-1 rounded-md px-1">
      <button ref={(node) => { if (node) sectionRefs.current.set(section.id, node); else sectionRefs.current.delete(section.id); }}
        aria-expanded={!collapsed[section.id]} onClick={() => setCollapsed((current) => ({ ...current, [section.id]: !current[section.id] }))}
        className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left text-[12px] text-fg-3 hover:text-fg">
        <ChevronRight size={13} className={cn('shrink-0 transition-transform', !collapsed[section.id] && 'rotate-90')} />
        {project && <ProjectIcon icon={project.icon} color={project.color || undefined} size={13} />}
        <span title={section.label} className="truncate">{section.label}</span><span className="shrink-0">{section.items.length}</span>
      </button>
      <GripVertical size={13} className="shrink-0 text-fg-3 opacity-0 group-hover/section:opacity-100" aria-hidden="true" />
      {section.custom && section.id !== 'custom:unassigned' && <Menu>
        <MenuTrigger asChild><button aria-label={section.label + ' 分组操作'} className="grid size-6 place-items-center rounded text-fg-3 hover:bg-hover hover:text-fg"><MoreHorizontal size={14} /></button></MenuTrigger>
        <MenuContent align="end">
          <MenuItem onSelect={() => setGroupEditor({ id: section.id.slice('custom:'.length), name: section.label })}><Pencil />重命名分组</MenuItem>
          <MenuItem onSelect={() => removeCustomGroup(section.id.slice('custom:'.length))}><Trash2 />删除分组</MenuItem>
        </MenuContent>
      </Menu>}
      {project && <Menu>
        <MenuTrigger asChild><button aria-label={project.name + ' 项目操作'} className="grid size-6 place-items-center rounded text-fg-3 hover:bg-hover hover:text-fg"><MoreHorizontal size={14} /></button></MenuTrigger>
        <MenuContent align="end">
          <MenuItem onSelect={() => window.dispatchEvent(new CustomEvent('atlas:new-project-conversation', { detail: { project } }))}><Plus />在此项目中新建会话</MenuItem>
          <MenuItem onSelect={() => void api(backend.apiBaseUrl, `/api/projects/${encodeURIComponent(project.project_id)}`, { method: 'PUT', json: { pinned: !project.pinned } }).then(() => {
            setProjects((items) => items.map((item) => item.project_id === project.project_id ? { ...item, pinned: !project.pinned } : item));
          }).catch((error) => setFeedback('项目置顶设置失败：' + String(error)))}><Pin />{project.pinned ? '取消置顶' : '置顶项目'}</MenuItem>
          <MenuItem onSelect={() => {
            const name = window.prompt('项目名称', project.name); if (!name?.trim()) return;
            const color = window.prompt('项目颜色（十六进制，例如 #5274d9）', project.color || '#5274d9');
            if (color === null) return;
            void api(backend.apiBaseUrl, `/api/projects/${encodeURIComponent(project.project_id)}`, { method: 'PUT', json: { name: name.trim(), color } }).then(() => {
              setProjects((items) => items.map((item) => item.project_id === project.project_id ? { ...item, name: name.trim(), color } : item));
            }).catch((error) => setFeedback('项目设置保存失败：' + String(error)));
          }}><Pencil />改名或改色</MenuItem>
          <MenuItem onSelect={() => {
            const workspace_path = window.prompt('新会话默认工作目录', project.workspace_path || ''); if (workspace_path === null) return;
            const default_model = window.prompt('默认模型 ID（留空使用全局模型）', project.default_model || ''); if (default_model === null) return;
            void api(backend.apiBaseUrl, `/api/projects/${encodeURIComponent(project.project_id)}`, { method: 'PUT', json: { workspace_path, default_model } }).then(() => {
              setProjects((items) => items.map((item) => item.project_id === project.project_id ? { ...item, workspace_path, default_model } : item));
            }).catch((error) => setFeedback('项目默认值保存失败：' + String(error)));
          }}><Folder />设置新会话默认值</MenuItem>
          <MenuItem onSelect={() => {
            if (!window.confirm(`删除项目“${project.name}”？项目记忆将先按你的选择处理。`)) return;
            const memoryAction=window.prompt('项目记忆如何处理？输入 delete 删除、global 并入全局、archive 保留归档。', 'archive');
            if(memoryAction!=='delete'&&memoryAction!=='global'&&memoryAction!=='archive')return;
            void api(backend.apiBaseUrl, `/api/projects/${encodeURIComponent(project.project_id)}?memory_action=${memoryAction}`, { method: 'DELETE' }).then(() => setProjects((items) => items.filter((item) => item.project_id !== project.project_id)))
              .catch((error) => setFeedback('项目删除失败：' + String(error)));
          }}><Trash2 />删除项目</MenuItem>
          <MenuSeparator />
          <MenuItem disabled={!archiveableProjectConversations.length} onSelect={(event) => {
            if (confirmProjectArchive !== section.id) { event.preventDefault(); setConfirmProjectArchive(section.id); return; }
            archiveableProjectConversations.forEach((item) => props.onToggleArchived(item.id));
            setConfirmProjectArchive('');
          }}><Archive />{confirmProjectArchive === section.id
            ? `确认归档 ${archiveableProjectConversations.length} 个会话`
            : `归档项目会话 (${archiveableProjectConversations.length})`}</MenuItem>
        </MenuContent>
      </Menu>}
    </div>
    {!collapsed[section.id] && <div onDragOver={(event) => { if (canDropOn(section.id)) event.preventDefault(); }} onDrop={(event) => { event.preventDefault(); dropConversation(section.id); }}>
      {section.items.map((item) => row(item, section.id))}
      {!section.items.length && <div className="rounded-lg px-3 py-2 text-[11px] text-fg-3">将会话拖到这里</div>}
    </div>}
  </section>;
  };

  const filteredSelectedCount = new Set(selectedIds.filter((id) => allMatched.some((item) => item.id === id))).size;
  const visibleProjects = activeProjects.filter((project) => project.name.toLocaleLowerCase().includes(projectPickerQuery.trim().toLocaleLowerCase()));
  const selectedActivityEvents = activityEvents.filter((item) => item.conversation_id === activityConversation?.id).reverse();
  const selectedGroup = groups.find((group) => group.id === focusSectionId) ?? groups[0];
  const railButton = (current: boolean) => cn('relative grid size-9 place-items-center rounded-[10px] transition-colors',
    current ? 'bg-[var(--sheet-solid)] text-fg shadow-[0_0_0_.5px_var(--line-strong),0_1px_3px_rgba(0,0,0,.06)]' : 'text-fg-3 hover:bg-hover hover:text-fg');
  return <aside aria-label="侧边栏" className="flex min-h-0 shrink-0">
    {/* Page rail (Codex 26.1007: 52px icon column); pages leave the task list alone. */}
    <nav aria-label="主导航" className="drag flex w-[52px] shrink-0 flex-col items-center gap-1 pt-2.5 pb-2.5">
      <Tip label="Atlas" side="right"><span className="mb-1.5 grid size-9 place-items-center"><Mark className="size-[26px]" /></span></Tip>
      {NAV.map(({ view, label, icon: Icon }) => {
        const current = props.view === view;
        return <Tip key={view} label={label} side="right">
          <button onClick={() => props.onGo(view)} aria-current={current ? 'page' : undefined} aria-label={label} className={cn('no-drag', railButton(current))}>
            <Icon size={18} strokeWidth={current ? 2 : 1.75} />
          </button>
        </Tip>;
      })}
      <Menu>
        <Tip label="更多页面" side="right"><MenuTrigger asChild><button aria-label="更多页面" className={cn('no-drag', railButton(MORE_NAV.some(({ view }) => view !== 'home' && view === props.view)))}>
          <MoreHorizontal size={18} />
        </button></MenuTrigger></Tip>
        <MenuContent align="start" side="right" className="min-w-[150px]">
          <MenuLabel>所有页面</MenuLabel>
          {MORE_NAV.map(({ view, label, icon: Icon }) => <MenuItem key={view} checked={props.view === view} onSelect={() => props.onGo(view)}><Icon size={15} />{label}</MenuItem>)}
        </MenuContent>
      </Menu>
      <span className="flex-1" />
      <Tip label={'外观：' + themeInfo(props.theme).label + '，点击切换到' + themeInfo(nextTheme(props.theme)).label} side="right">
        <button aria-label={'切换到' + themeInfo(nextTheme(props.theme)).label} onClick={props.onToggleTheme} className={cn('no-drag', railButton(false))}>
          {props.theme === 'dark' ? <Moon size={17} /> : props.theme === 'aurora' ? <Sparkles size={17} /> : <Sun size={17} />}
        </button>
      </Tip>
      <Tip label="设置 Ctrl ," side="right"><button aria-label="设置" onClick={props.onSettings} className={cn('no-drag', railButton(false))}><Settings size={17} /></button></Tip>
      <Tip label={props.username + ' · ' + props.subtitle} side="right">
        <span className="no-drag mt-1 grid size-7 shrink-0 place-items-center rounded-full bg-[image:var(--avatar-bg)] text-[11.5px] font-semibold text-[var(--avatar-fg)]" aria-label={props.username + '，' + props.subtitle}>{props.username.slice(0, 1).toUpperCase()}</span>
      </Tip>
    </nav>

    {mini && <div className="flex flex-col items-center pt-2.5">
      <Tip label="跨会话收件箱与工作板" side="right"><button aria-label="跨会话收件箱与工作板" onClick={() => setTriageOpen(true)} className="mb-2 grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><ListTodo size={16} /></button></Tip>
      <Tip label="展开任务栏" side="right">
        <button aria-label="展开侧边栏" onClick={props.onToggleMini} className="grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><PanelLeft size={16} /></button>
      </Tip>
    </div>}

    {!mini && <div className="flex w-[238px] min-h-0 flex-col bg-[var(--panel-bg)] pt-2.5 pr-1.5 pb-2 pl-1">
    <div className="drag flex h-9 items-center gap-1 pr-0.5 pl-2">
      <b className="text-[15px] font-semibold tracking-[-.01em] text-heading">Atlas</b>
      <span className="flex-1" />
      <Tip label="搜索和命令 Ctrl K"><button onClick={props.onSearch} aria-label="搜索和命令" className="no-drag grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><Search size={15} /></button></Tip>
      <Tip label="收起任务栏"><button aria-label="收起侧边栏" onClick={props.onToggleMini} className="no-drag grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><PanelLeft size={15} /></button></Tip>
    </div>
    <div className="mt-1.5 flex h-8 items-center gap-1">
      <button onClick={props.onNewTask} disabled={props.creating} aria-label="新建对话"
        className="flex h-8 min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] text-fg hover:bg-hover disabled:opacity-60">
        <SquarePen size={16} className="text-fg-2" /><span>新任务</span><Kbd className="ml-auto">Ctrl N</Kbd>
      </button>
      <Menu>
        <MenuTrigger asChild><button type="button" aria-label="新窗口和新会话选项" title="新窗口和新会话选项" className="grid size-7 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><MoreHorizontal size={15} /></button></MenuTrigger>
        <MenuContent align="end" className="min-w-[225px]">
          <MenuLabel>新建</MenuLabel>
          <MenuItem onSelect={() => window.atlasDesktop?.openNewWindow?.()}><AppWindow />新建窗口</MenuItem>
          <MenuItem onSelect={() => window.atlasDesktop?.openNewSessionWindow?.()}><SquarePen />新会话并在新窗口打开</MenuItem>
          <MenuSeparator />
          <p className="m-0 max-w-[250px] px-2.5 py-1.5 text-[10.5px] leading-relaxed text-fg-3">关闭独立窗口只关闭该窗口；关闭主窗口会收起到系统托盘。会话仍保存在历史记录中。</p>
        </MenuContent>
      </Menu>
    </div>
    <button onClick={() => setTriageOpen(true)} aria-label="跨会话收件箱与工作板" className="mt-1 flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[12.5px] text-fg-2 hover:bg-hover"><ListTodo size={15} className="text-brand"/><span>分诊与工作板</span></button>
    <div className="mt-3 flex min-h-0 flex-1 flex-col overflow-hidden" aria-label="历史会话">
      <div className="mb-1.5 flex items-center gap-1 px-1">
        <label className="relative min-w-0 flex-1">
          <Search size={13} className="pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-fg-3" />
          <input ref={searchInputRef} type="search" aria-label="搜索会话" value={filterText} onChange={(event) => setFilterText(event.target.value)} placeholder="搜索任务"
            className="h-7 w-full rounded-md bg-transparent py-1 pr-2 pl-7 text-[12.5px] text-fg outline-none placeholder:text-fg-3 hover:bg-hover focus:bg-sunken focus:ring-1 focus:ring-line-strong" />
        </label>
        {/* Filter, grouping, bulk select and custom groups share one menu so the list keeps its room. */}
        <Menu>
          <MenuTrigger asChild><button aria-label={'筛选和分组：' + STATUS_FILTERS[statusFilter] + '，' + ARRANGE[mode]}
            className={cn('grid size-7 shrink-0 place-items-center rounded-md hover:bg-hover hover:text-fg', statusFilter !== 'all' || selectionMode ? 'text-brand' : 'text-fg-3')}><ArrowUpDown size={13} /></button></MenuTrigger>
          <MenuContent align="end"><MenuLabel>显示</MenuLabel>
            {(Object.keys(STATUS_FILTERS) as StatusFilter[]).map((filter) => <MenuItem key={filter} checked={statusFilter === filter} onSelect={() => setStatusFilter(filter)}>{STATUS_FILTERS[filter]}</MenuItem>)}
            <MenuSeparator /><MenuLabel>分组方式</MenuLabel>
            {(Object.keys(ARRANGE) as Arrange[]).map((key) => <MenuItem key={key} checked={mode === key} onSelect={() => {
              setMode(key);
              if (key === 'project') void api<{ projects: Project[] }>(backend.apiBaseUrl, '/api/projects?include_conversations=true')
                .then((result) => setProjects(Array.isArray(result.projects) ? result.projects : []))
                .catch(() => setProjects([]));
            }}>{ARRANGE[key]}</MenuItem>)}
            <MenuSeparator />
            <MenuItem checked={selectionMode} onSelect={() => { setSelectionMode((value) => !value); setSelectedIds([]); setConfirmBulkDelete(false); setConfirmBulkArchive(false); }}><Check />批量选择</MenuItem>
            <MenuItem onSelect={() => setGroupEditor({ id: null, name: '' })}><Plus />新建自定义分组</MenuItem>
          </MenuContent>
        </Menu>
      </div>
      {query && contentHits.length > 0 && <div className="mb-2 max-h-36 overflow-auto rounded-lg bg-sunken p-1" aria-label="正文搜索结果">
        {contentHits.slice(0, 5).map((hit) => {
          const conversation = props.conversations.find((item) => item.id === hit.conversation_id);
          const snippet = cleanSearchSnippet(hit, query, 90);
          const who = searchHitRoleLabel(hit.role);
          return <button key={String(hit.id)} type="button" onClick={() => conversation && props.onJumpMessage?.(hit.conversation_id, String(hit.id))} className="block w-full rounded-md px-2 py-1.5 text-left hover:bg-hover">
            <span className="block truncate text-[11px] text-fg-3">{who ? `${who} · ` : ''}{conversation?.title ?? hit.title ?? '对话'}</span><span className="block truncate text-[11.5px] text-fg-2">{snippet}</span>
          </button>;
        })}
      </div>}
      {selectionMode && <div className="mb-2 grid gap-1 rounded-lg border border-line bg-sunken p-1.5">
        <div className="flex items-center justify-between px-1 text-[11px] text-fg-2"><span>已选 {filteredSelectedCount} 项</span>
          <span className="flex items-center gap-2">
            <button onClick={() => setSelectedIds([...new Set(allMatched.map((item) => item.id))])} className="text-brand hover:underline">全选</button>
            <button aria-label="退出批量选择" onClick={() => { setSelectionMode(false); setSelectedIds([]); setConfirmBulkDelete(false); setConfirmBulkArchive(false); }}
              className="grid size-5 place-items-center rounded text-fg-3 hover:bg-hover hover:text-fg"><X size={12} /></button>
          </span>
        </div>
        <div className="grid grid-cols-3 gap-1">
          <button onClick={() => bulk('pin')} disabled={!selectedIds.length} className="rounded-md px-1 py-1 text-[10.5px] text-fg-2 hover:bg-hover disabled:opacity-40">置顶</button>
          <button onClick={() => bulk('unread')} disabled={!selectedIds.length || !props.onSetUnread} className="rounded-md px-1 py-1 text-[10.5px] text-fg-2 hover:bg-hover disabled:opacity-40">标未读</button>
          <button onClick={() => bulk('archive')} disabled={!selectedIds.length} className="rounded-md px-1 py-1 text-[10.5px] text-fg-2 hover:bg-hover disabled:opacity-40">{confirmBulkArchive ? '确认归档' : '归档'}</button>
          <button onClick={() => bulk('export-md')} disabled={!selectedIds.length} className="rounded-md px-1 py-1 text-[10.5px] text-fg-2 hover:bg-hover disabled:opacity-40">导出 MD</button>
          <button onClick={() => bulk('export-json')} disabled={!selectedIds.length} className="rounded-md px-1 py-1 text-[10.5px] text-fg-2 hover:bg-hover disabled:opacity-40">导出 JSON</button>
          <button onClick={() => bulk('delete')} disabled={!selectedIds.length} className="rounded-md px-1 py-1 text-[10.5px] text-danger hover:bg-danger/10 disabled:opacity-40">{confirmBulkDelete ? '确认删除' : '删除'}</button>
        </div>
      </div>}
      <div className="min-h-0 flex-1 overflow-auto pr-0.5">
        {(pinnedItems.length > 0 || draggingConversation) && <section className="mb-3"
          onDragOver={(event) => { if (canDropOn('pinned')) event.preventDefault(); }}
          onDrop={(event) => { event.preventDefault(); dropConversation('pinned'); }}>
          <h3 className="m-0 px-2.5 pb-1 text-[12px] font-normal text-fg-3">置顶 <span>{pinnedItems.length}</span></h3>
          {pinnedItems.map((item) => row(item, 'pinned'))}
          {!pinnedItems.length && <p className="m-0 px-2.5 py-1 text-[11px] text-fg-3">拖到这里置顶</p>}
        </section>}
        {groups.map(renderSection)}
        {(archivedItems.length > 0 || draggingConversation) && <section className="mb-3"
          onDragOver={(event) => { if (canDropOn('archived')) event.preventDefault(); }}
          onDrop={(event) => { event.preventDefault(); dropConversation('archived'); }}>
          <button onClick={() => setShowArchived((value) => !value)} aria-expanded={showArchived || statusFilter === 'archived'}
            className="flex w-full items-center gap-1 px-2.5 pb-1 text-left text-[12px] text-fg-3 hover:text-fg">
            <ChevronRight size={13} className={cn('transition-transform', (showArchived || statusFilter === 'archived') && 'rotate-90')} />已归档 {archivedItems.length}
          </button>
          {(showArchived || statusFilter === 'archived') && archivedItems.map((item) => row(item, 'archived'))}
          {!archivedItems.length && <p className="m-0 px-2.5 py-1 text-[11px] text-fg-3">拖到这里归档</p>}
        </section>}
        {!allMatched.length && <p className="px-2.5 text-[12.5px] text-fg-3">{props.conversationsLoading ? '正在加载…' : filterText || statusFilter !== 'all' ? '没有符合条件的会话。' : '还没有任务。点「新任务」开始。'}</p>}
        {feedback && <p role="status" aria-live="polite" className="px-2.5 py-1 text-[11px] text-fg-3">{feedback}</p>}
      </div>
    </div>
    </div>}

    <SidebarConversationDetails conversation={details} open={Boolean(details)} onOpenChange={(open) => { if (!open) setDetails(null); }}
      running={details ? isRunning(details.id) : false} unread={details ? isUnread(details.id) : false} waiting={details ? isWaiting(details) : false} />
    <TriageBoardDialog apiBaseUrl={backend.apiBaseUrl} open={triageOpen} onOpenChange={setTriageOpen} conversations={props.conversations} onOpenConversation={props.onOpenConversation} />
    <Dialog open={searchDialogOpen} onOpenChange={setSearchDialogOpen} label="搜索侧栏会话"
      className="w-[min(440px,calc(100vw-28px))] border border-line bg-overlay p-4 shadow-2xl" align="top">
      <h2 className="m-0 text-[16px] font-semibold text-heading">搜索会话</h2>
      <input autoFocus type="search" aria-label="搜索侧栏会话" value={filterText} onChange={(event) => setFilterText(event.target.value)}
        placeholder="按名称、工作区或项目搜索…" className="mt-3 h-9 w-full rounded-lg bg-sunken px-3 text-[13px] text-fg outline-none focus:ring-1 focus:ring-brand" />
      <div className="mt-2 max-h-[min(55vh,420px)] overflow-auto">
        {allMatched.slice(0, 30).map((conversation) => <button key={conversation.id} type="button"
          onClick={() => { setSearchDialogOpen(false); props.onOpenConversation(conversation); }}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[13px] text-fg-2 hover:bg-hover hover:text-fg">
          <MessageSquare size={14} className="shrink-0 text-fg-3" /><span className="min-w-0 flex-1 truncate">{displayTitle(conversation.title)}</span>
        </button>)}
        {!allMatched.length && <p className="px-2 text-[12px] text-fg-3">没有匹配的会话。</p>}
      </div>
    </Dialog>
    <Dialog open={groupNavigatorOpen} onOpenChange={setGroupNavigatorOpen} label="切换会话组"
      className="w-[min(440px,calc(100vw-28px))] border border-line bg-overlay p-4 shadow-2xl" align="top">
      <h2 className="m-0 text-[16px] font-semibold text-heading">会话组</h2>
      <div className="mt-3 flex max-h-28 flex-wrap gap-1 overflow-auto">
        {groups.map((group) => <button key={group.id} type="button" aria-current={selectedGroup?.id === group.id ? 'true' : undefined}
          onClick={() => setFocusSectionId(group.id)}
          className={cn('rounded-lg px-2 py-1 text-[12px]', selectedGroup?.id === group.id ? 'bg-selected text-brand' : 'text-fg-2 hover:bg-hover')}>
          {group.label} {group.items.length}
        </button>)}
      </div>
      <div className="mt-3 max-h-[min(45vh,340px)] overflow-auto border-t border-line pt-2">
        {selectedGroup?.items.map((conversation) => <button key={conversation.id} type="button"
          onClick={() => { setGroupNavigatorOpen(false); props.onOpenConversation(conversation); }}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[13px] text-fg-2 hover:bg-hover hover:text-fg">
          <MessageSquare size={14} className="shrink-0 text-fg-3" /><span className="min-w-0 flex-1 truncate">{displayTitle(conversation.title)}</span>
        </button>)}
        {!selectedGroup?.items.length && <p className="px-2 text-[12px] text-fg-3">这个组还没有会话。</p>}
      </div>
    </Dialog>
    <Dialog open={projectPickerOpen} onOpenChange={setProjectPickerOpen} label="选择项目"
      className="w-[min(420px,calc(100vw-28px))] border border-line bg-overlay p-4 shadow-2xl" align="top">
      <h2 className="m-0 text-[16px] font-semibold text-heading">选择项目</h2>
      <input autoFocus type="search" aria-label="查找项目" value={projectPickerQuery} onChange={(event) => setProjectPickerQuery(event.target.value)}
        placeholder="查找项目…" className="mt-3 h-9 w-full rounded-lg bg-sunken px-3 text-[13px] text-fg outline-none focus:ring-1 focus:ring-brand" />
      <div className="mt-2 max-h-[min(50vh,360px)] overflow-auto">
        {visibleProjects.map((project) => <button key={project.project_id} type="button"
          onClick={() => { const id = 'project:' + project.project_id; setMode('project'); setProjectPickerOpen(false); setCollapsed((value) => ({ ...value, [id]: false })); setFocusSectionId(id); if (mini) props.onToggleMini(); }}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[13px] text-fg-2 hover:bg-hover hover:text-fg">
          <ProjectIcon icon={project.icon} color={project.color || undefined} size={16} /><span className="min-w-0 flex-1 truncate">{project.name}</span>
        </button>)}
        {!visibleProjects.length && <p className="px-2 text-[12px] text-fg-3">{activeProjects.length ? '没有匹配的项目。' : '还没有可用项目。'}</p>}
      </div>
    </Dialog>
    <Dialog open={Boolean(activityConversation)} onOpenChange={(open) => { if (!open) setActivityConversation(null); }} label="会话运行动态"
      className="w-[min(500px,calc(100vw-28px))] border border-line bg-overlay p-4 shadow-2xl">
      <h2 className="m-0 truncate text-[16px] font-semibold text-heading">{activityConversation?.title || '会话'} · 运行动态</h2>
      <div className="mt-3 max-h-[min(60vh,420px)] overflow-auto">
        {selectedActivityEvents.map((entry) => <div key={entry.event_id} className="border-b border-line px-1 py-2 last:border-0">
          <div className="flex items-center justify-between gap-2 text-[12px] text-fg">
            <span className="truncate">{entry.event.replace(/_/g, ' ')} · {entry.status}</span>
            <time className="shrink-0 text-[11px] text-fg-3" dateTime={entry.timestamp}>{new Date(entry.timestamp).toLocaleString()}</time>
          </div>
          {entry.waiting_for && <p className="m-0 mt-1 text-[11px] text-brand">等待：{entry.waiting_for}</p>}
          {typeof entry.detail === 'string' && entry.detail && <p className="m-0 mt-1 text-[11px] text-fg-3">{entry.detail}</p>}
        </div>)}
        {!selectedActivityEvents.length && <p className="text-[12px] text-fg-3">还没有运行动态。</p>}
      </div>
    </Dialog>
    <Dialog open={Boolean(groupEditor)} onOpenChange={(open) => { if (!open) setGroupEditor(null); }} label={groupEditor?.id ? '重命名分组' : '新建分组'}
      className="w-[min(380px,calc(100vw-28px))] border border-line bg-overlay p-5 shadow-2xl">
      <form onSubmit={(event) => { event.preventDefault(); createCustomGroup(); }}>
        <h2 className="m-0 text-[16px] font-semibold text-heading">{groupEditor?.id ? '重命名自定义分组' : '新建自定义分组'}</h2>
        <label className="mt-4 grid gap-1.5 text-[12px] text-fg-2">分组名称
          <input autoFocus required maxLength={48} value={groupEditor?.name ?? ''} onChange={(event) => setGroupEditor((current) => current ? { ...current, name: event.target.value } : current)}
            className="h-9 rounded-lg bg-sunken px-3 text-[13px] text-fg outline-none focus:ring-1 focus:ring-brand" />
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={() => setGroupEditor(null)} className="rounded-lg px-3 py-2 text-[12px] text-fg-2 hover:bg-hover">取消</button>
          <button type="submit" className="rounded-lg bg-brand px-3 py-2 text-[12px] font-medium text-on-primary">{groupEditor?.id ? '保存' : '创建分组'}</button>
        </div>
      </form>
    </Dialog>
  </aside>;
}
