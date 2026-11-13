import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type MutableRefObject } from 'react';
import { Virtuoso, type StateSnapshot, type VirtuosoHandle } from 'react-virtuoso';
import { BookOpenText, History, ListChecks } from 'lucide-react';
import type { ConversationMessage as ConversationMessageData } from '@atlas/backend-adapter';
import { useAtlasStore } from '../store/useAtlasStore';
import { TimelineRow } from './ConversationActivity';
import ConversationMessage from './ConversationMessage';
import Mark from './Mark';
import { attachHistoryResult, historyStep, todoEditNotice, type Step, type TimelineItem } from './timeline';
import { TimelineProjection } from './timelineProjection';
import { structuredComponent } from './StructuredComponentCard';
import { isTodoEdit } from './runInsights';
import { Button } from '../ui/Button';
import { loadBindings, matchShortcut } from '../services/shortcuts';
import { clearConversationHighlights, ConversationSearch, findConversationMatches, highlightConversationRow } from './conversation-search/ConversationSearch';
import type { ConversationSearchRow } from './conversation-search/ConversationSearch';
import type { InspectorTab } from '../shell/Inspector';
import type { AgentEvent } from '../../types/runtime';
import { settingsForMode, ThreadClassGroup, ThreadPresentationControls, THREAD_CLASSES, useThreadPresentationSettings, type ThreadClassId, type ThreadPresentationMode } from './ThreadPresentation';
import ComputerUseTrail from './ComputerUseTrail';

/** 每个会话最近一次的虚拟列表滚动状态，切回来时原位恢复。 */
const savedScrollStates = new Map<string, StateSnapshot>();
/** 向上翻页会在头部插入行；每个会话记住已插入多少行，滚动锚点和恢复的存档才不会错位。 */
const firstItemIndexByConversation = new Map<string, number>();

const EMPTY_EVENTS: AgentEvent[] = [];

/** 合并后的列表行：历史消息 + 实时时间线 + 头尾占位，交给一个 Virtuoso 实例统一虚拟化。 */
type ThreadRow =
  | { kind: 'load-earlier'; id: string }
  | { kind: 'truncated'; id: string; count: number }
  | { kind: 'history'; id: string; message: ConversationMessageData; continued?: boolean }
  | { kind: 'subtask'; id: string; activity: Record<string, unknown> }
  | { kind: 'recap'; id: string; summary: string; createdAt: string }
  | { kind: 'empty'; id: string }
  | { kind: 'timeline'; id: string; item: TimelineItem; firstInTurn: boolean; last: boolean };

type ThreadDisplayRow =
  | { kind: 'row'; id: string; row: ThreadRow }
  | { kind: 'category'; id: string; classId: ThreadClassId; rows: ThreadRow[]; grouped: boolean };

function timelineClass(item: TimelineItem): ThreadClassId {
  switch (item.kind) {
    case 'user': case 'reply': return 'messages';
    case 'reasoning': return 'model';
    case 'steps': case 'group': return 'tools';
    case 'approval': case 'question': case 'trust': case 'foreground': case 'handoff': return 'approvals';
    case 'plan': return 'plans';
    case 'checks': case 'review': case 'lsp': return 'checks';
    case 'component': return 'messages';
    case 'extension': return 'messages';
    case 'artifact': case 'done': return 'files';
    case 'cancelled': case 'notice': case 'failed': return 'status';
  }
}

function pendingInteraction(row: ThreadRow, answers: Record<string, string | undefined>): boolean {
  if (row.kind !== 'timeline') return false;
  const item = row.item;
  switch (item.kind) {
    case 'foreground':
    case 'handoff':
    case 'approval':
      return true;
    case 'question':
    case 'plan':
    case 'trust': {
      const eventId = String(item.event.data.event_id ?? item.event.id);
      return answers[eventId] === undefined;
    }
    default:
      return false;
  }
}

function presentRows(rows: ThreadRow[], settings: ReturnType<typeof useThreadPresentationSettings>[0], answers: Record<string, string | undefined>): ThreadDisplayRow[] {
  const visible = rows.filter((row) => {
    if (row.kind !== 'timeline') return true;
    const classId = timelineClass(row.item);
    return settings.show[classId] || pendingInteraction(row, answers);
  });
  const output: ThreadDisplayRow[] = [];
  let group: ThreadRow[] = [];
  let groupClass: ThreadClassId | null = null;
  const flush = () => {
    if (!group.length || !groupClass) return;
    output.push({ kind: 'category', id: `category-${groupClass}-${group[0].id}`, classId: groupClass, rows: group, grouped: true });
    group = [];
    groupClass = null;
  };
  for (const row of visible) {
    if (row.kind !== 'timeline') {
      flush();
      output.push({ kind: 'row', id: row.id, row });
      continue;
    }
    const isPending = pendingInteraction(row, answers);
    if (isPending) {
      flush();
      output.push({ kind: 'row', id: row.id, row });
      continue;
    }
    const classId = timelineClass(row.item);
    if (settings.groupByClass) {
      if (groupClass !== classId) flush();
      groupClass = classId;
      group.push(row);
    } else if (settings.collapsed[classId]) {
      flush();
      output.push({ kind: 'category', id: `category-${classId}-${row.id}`, classId, rows: [row], grouped: false });
    } else {
      flush();
      output.push({ kind: 'row', id: row.id, row });
    }
  }
  flush();
  return output;
}

const OMIT_SEARCH_KEYS = new Set(['id', 'kind', 'timestamp', 'startedAt', 'endedAt', 'imagePreview', 'preview']);

function collectSearchText(value: unknown, output: string[], key = '') {
  if (OMIT_SEARCH_KEYS.has(key)) return;
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    const text = String(value).trim();
    if (text) output.push(text);
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectSearchText(item, output);
    return;
  }
  if (!value || typeof value !== 'object') return;
  for (const [childKey, child] of Object.entries(value)) collectSearchText(child, output, childKey);
}

function searchTextForRow(row: ThreadRow): string {
  if (row.kind === 'history') return row.message.content;
  if (row.kind !== 'timeline') return '';
  const values: string[] = [];
  collectSearchText(row.item, values);
  return values.join('\n');
}

export interface MessageThreadProps {
  /** 历史消息（已按分叉备注排好序、去掉当前运行那一轮）。 */
  history: ConversationMessageData[];
  componentSelections?: Record<string, string>;
  username: string;
  /** 允许改写历史（运行已结束）时，历史消息的悬浮操作按钮。 */
  historyActions: (message: ConversationMessageData) => ReactNode;
  /** 空会话的占位（「这次要做什么？」）；条件由 App 判断，null 表示不显示。 */
  emptyState: ReactNode;
  /** 底部区域：重试提示、错误提示等，跟随在时间线后面。 */
  footerNote: ReactNode;
  /** 滚动容器 ref，交给 App 的 TimelineNav 等复用。 */
  threadRef: MutableRefObject<HTMLDivElement | null>;
  /** 任务面板跳转。 */
  setTab: (tab: InspectorTab) => void;
  /** X2 交接卡「在浏览器面板打开」：带网址打开浏览器面板。 */
  onOpenBrowser?: (url: string) => void;
  focusMode?: boolean;
  focusSummary?: string;
  tuiFullscreen?: boolean;
  onToast?: (message: string) => void;
}

export default function MessageThread({ history, componentSelections = {}, username, historyActions, emptyState, footerNote, threadRef, setTab, onOpenBrowser, focusMode = false, focusSummary = '', tuiFullscreen = false, onToast }: MessageThreadProps) {
  // 窄选择器：只有当前会话的运行事件/正文变化才重渲染这里，别的会话流式输出不打扰。
  const conversationId = useAtlasStore((state) => state.activeConversationId);
  const activeRunId = useAtlasStore((state) => state.activeRunId);
  const events = useAtlasStore((state) => state.runs.find((run) => run.id === state.activeRunId)?.events ?? EMPTY_EVENTS);
  const truncatedCount = useAtlasStore((state) => {
    const run = state.runs.find((item) => item.id === state.activeRunId);
    return run?.eventsTruncated ? (run.droppedEventCount ?? 0) : 0;
  });
  const working = useAtlasStore((state) => state.busy && !state.paused);
  const answers = useAtlasStore((state) => state.answers);
  const profiles = useAtlasStore((state) => state.profiles);
  const hasEarlier = useAtlasStore((state) => state.messagesHasEarlier[conversationId] ?? false);
  const loadingEarlier = useAtlasStore((state) => state.loadingEarlierConversationId === conversationId);
  const loading = useAtlasStore((state) => state.loadingMessagesConversationId === conversationId && Boolean(conversationId));
  const loadEarlier = useAtlasStore((state) => state.loadEarlier);

  const [scrollParent, setScrollParent] = useState<HTMLDivElement | null>(null);
  const [scrollSpeed, setScrollSpeed] = useState(() => {
    try {
      const value = Number(localStorage.getItem('atlas.preference.scroll-speed'));
      return Number.isFinite(value) && value >= 0.25 && value <= 3 ? value : 1;
    } catch { return 1; }
  });
  const [presentation, setPresentation] = useThreadPresentationSettings();
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeSearchKey, setActiveSearchKey] = useState<string | null>(null);
  const [searchHistoryLoading, setSearchHistoryLoading] = useState(false);
  const [searchHistoryIncomplete, setSearchHistoryIncomplete] = useState(false);
  const [externalJump, setExternalJump] = useState<{ conversationId: string; messageId: string } | null>(null);
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const historyLoadAttemptRef = useRef<string | null>(null);
  const searchTargetRef = useRef('');
  const scrollStateKey = `${conversationId}:${searchOpen ? 'search' : JSON.stringify(presentation)}`;
  const scrollStateKeyRef = useRef(scrollStateKey);
  const lastAnnouncedReplyRef = useRef<{ conversationId: string; eventId: string } | null>(null);
  const [screenReaderAnnouncement, setScreenReaderAnnouncement] = useState('');
  scrollStateKeyRef.current = scrollStateKey;
  const previousHistory = useRef({ conversationId: '', length: 0 });

  useEffect(() => {
    const onSpeed = (event: Event) => {
      const value = (event as CustomEvent<unknown>).detail;
      if (typeof value === 'number' && Number.isFinite(value)) setScrollSpeed(Math.min(3, Math.max(0.25, value)));
    };
    window.addEventListener('atlas:scroll-speed', onSpeed);
    return () => window.removeEventListener('atlas:scroll-speed', onSpeed);
  }, []);

  useEffect(() => {
    if (!scrollParent || scrollSpeed === 1) return;
    const onWheel = (event: WheelEvent) => {
      // Keep browser zoom and horizontal/modified gestures native; normalize legacy line/page wheels.
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.deltaY === 0) return;
      const unit = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16
        : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? scrollParent.clientHeight : 1;
      event.preventDefault();
      scrollParent.scrollBy({ top: event.deltaY * unit * scrollSpeed, behavior: 'auto' });
    };
    scrollParent.addEventListener('wheel', onWheel, { passive: false });
    return () => scrollParent.removeEventListener('wheel', onWheel);
  }, [scrollParent, scrollSpeed]);

  useEffect(() => {
    const onJump = (event: Event) => {
      const detail = (event as CustomEvent<{ conversationId?: string; messageId?: string }>).detail;
      if (detail?.conversationId && detail.messageId) setExternalJump({ conversationId: detail.conversationId, messageId: detail.messageId });
    };
    window.addEventListener('atlas:jump-message', onJump);
    return () => window.removeEventListener('atlas:jump-message', onJump);
  }, []);

  const timelineProjectionRef = useRef<{ runId: string | null; projection: TimelineProjection } | null>(null);
  const timelineItems = useMemo(() => {
    if (timelineProjectionRef.current?.runId !== activeRunId) {
      timelineProjectionRef.current = { runId: activeRunId, projection: new TimelineProjection() };
    }
    const items = timelineProjectionRef.current.projection.project(events);
    if (!focusMode || !working) return focusMode ? [] : items;
    const compact: TimelineItem[] = items.filter((item) => item.kind === 'user' || item.kind === 'reply');
    const userIndex = compact.reduce((found, item, index) => item.kind === 'user' ? index : found, -1);
    const insertAt = compact.findIndex((item, index) => index > userIndex && item.kind === 'reply');
    compact.splice(insertAt < 0 ? compact.length : insertAt, 0, { kind: 'notice', id: 'focus-summary', tone: 'switch', text: focusSummary || '正在处理当前请求' });
    return compact;
  }, [activeRunId, events, focusMode, working, focusSummary]);
  // The placeholder only covers the gap before anything streams; once thinking text arrives the
  // reasoning row takes over (keeping both stacked them on top of each other).
  const thinking = working && !events.some((event) => event.type === 'message.delta' || event.type === 'tool.started' || event.type === 'tool.preparing'
    || (event.type === 'run.status' && event.data.status === 'reasoning' && typeof event.data.text === 'string' && event.data.text.trim().length > 0));

  // TimelineRow 需要的 store：动作函数恒定，响应式字段（answers/profiles）单独订阅后合入。
  const activityStore = useMemo(() => ({ ...useAtlasStore.getState(), answers, profiles }), [answers, profiles]);

  const rows = useMemo<ThreadRow[]>(() => {
    const rows: ThreadRow[] = [];
    if (hasEarlier && !focusMode) rows.push({ kind: 'load-earlier', id: 'load-earlier' });
    if (truncatedCount > 0 && !focusMode) rows.push({ kind: 'truncated', id: 'truncated', count: truncatedCount });
    // Stored turns: text replies stay messages; tool calls and their results fold into the same
    // compact step track the live view uses, so reopened chats don't show empty "Atlas" headers.
    let historyHeaded = false;
    let pending: Step[] = [];
    const stepsById = new Map<string, Step>();
    const componentRows = new Map<string, number>();
    const selectedComponents = new Map<string, string>(Object.entries(componentSelections));
    for (const message of history) {
      if (message.role !== 'user') continue;
      const match = /^结构化卡片 \[([^\]]+)\]「[^」]*」选择：([^\n]+)/.exec(message.content);
      if (match) selectedComponents.set(match[1], match[2]);
    }
    const flushSteps = () => {
      if (!pending.length) return;
      const id = `hs-${pending[0].id}`;
      rows.push({ kind: 'timeline', id, item: { kind: 'steps', id, steps: pending }, firstInTurn: !historyHeaded, last: false });
      historyHeaded = true;
      pending = [];
    };
    // History keeps no thinking timestamps; the gap since the previous message (the model call that
    // produced this reply) stands in for "思考 · 持续了 N 秒".
    let previousAt = '';
    for (const message of history) {
      const metadata = (message.metadata && typeof message.metadata === 'object' ? message.metadata : {}) as Record<string, unknown>;
      const createdAt = message.created_at ?? '';
      const startedAt = previousAt;
      previousAt = createdAt || previousAt;
      if (message.role === 'system' && metadata.display_kind === 'subtask_activity') {
        flushSteps();
        const activity = metadata.activity;
        if (activity && typeof activity === 'object' && !Array.isArray(activity)) {
          const id = `subtask-${message.id}`;
          rows.push({ kind: 'subtask', id, activity: activity as Record<string, unknown> });
          historyHeaded = true;
        }
        continue;
      }
      if (message.role === 'system' && metadata.display_kind === 'auto_recap') {
        flushSteps();
        rows.push({ kind: 'recap', id: message.id, summary: message.content, createdAt });
        historyHeaded = true;
        continue;
      }
      if (message.role === 'system' && metadata.display_kind === 'structured_component') {
        flushSteps();
        const componentData = metadata.component;
        if (!componentData || typeof componentData !== 'object' || Array.isArray(componentData)) continue;
        const event: AgentEvent = { id: message.id, runId: String(metadata.run_id ?? ''), sequence: Number(metadata.sequence ?? 0), type: 'component.push', timestamp: createdAt, data: componentData as Record<string, unknown> };
        const component = structuredComponent(event);
        if (!component) continue;
        component.selectedLabel = selectedComponents.get(component.id);
        const item: TimelineItem = { kind: 'component', id: message.id, component };
        const prior = componentRows.get(component.id);
        if (prior === undefined) {
          componentRows.set(component.id, rows.length);
          rows.push({ kind: 'timeline', id: `hc-${component.id}`, item, firstInTurn: !historyHeaded, last: false });
        } else {
          rows[prior] = { kind: 'timeline', id: `hc-${component.id}`, item, firstInTurn: false, last: false };
        }
        historyHeaded = true;
        continue;
      }
      if (message.role === 'system' && metadata.display_kind === 'agent_canvas') continue;
      if (message.role === 'tool') {
        const step = stepsById.get(String(metadata.tool_call_id ?? ''));
        if (step) attachHistoryResult(step, message.content, metadata, createdAt);
        continue;
      }
      if (message.role === 'assistant') {
        const calls = Array.isArray(metadata.tool_calls) ? metadata.tool_calls : [];
        const reasoning = typeof metadata.reasoning === 'string' ? metadata.reasoning
          : typeof metadata.reasoning_content === 'string' ? metadata.reasoning_content : '';
        if (reasoning.trim()) {
          flushSteps();
          const id = `hr-${message.id}`;
          rows.push({ kind: 'timeline', id, item: { kind: 'reasoning', id, text: reasoning, eventCount: 1, truncated: false, source: 'history',
            ...(startedAt && createdAt ? { startedAt, endedAt: createdAt } : {}) }, firstInTurn: !historyHeaded, last: false });
          historyHeaded = true;
        }
        if (message.content.trim()) {
          flushSteps();
          rows.push({ kind: 'history', id: `h-${message.id}`, message, continued: historyHeaded });
          historyHeaded = true;
        }
        for (const call of calls) {
          const step = historyStep(call, createdAt);
          if (!step) continue;
          pending.push(step);
          stepsById.set(step.id, step);
        }
        continue;
      }
      flushSteps();
      if (message.role === 'user') historyHeaded = false;
      rows.push({ kind: 'history', id: `h-${message.id}`, message });
    }
    flushSteps();
    if (!history.length && !timelineItems.length && !loading && emptyState) rows.push({ kind: 'empty', id: 'empty' });
    // Each Atlas turn shows its header once; later steps and replies in the same turn hang beneath it.
    let headed = false;
    for (let index = 0; index < timelineItems.length; index++) {
      const original = timelineItems[index];
      const item: TimelineItem = original.kind === 'component' && selectedComponents.has(original.component.id)
        ? { ...original, component: { ...original.component, selectedLabel: selectedComponents.get(original.component.id) } }
        : original;
      if (item.kind === 'user') headed = false;
      const firstInTurn = item.kind !== 'user' && !headed;
      if (item.kind !== 'user') headed = true;
      rows.push({ kind: 'timeline', id: `t-${item.id}`, item, firstInTurn, last: index === timelineItems.length - 1 });
    }
    return rows;
  }, [history, componentSelections, loading, timelineItems, hasEarlier, truncatedCount, focusMode]);

  const hasReasoning = rows.some((row) => row.kind === 'timeline' && row.item.kind === 'reasoning' && row.item.text.trim().length > 0);

  const displayRows = useMemo(() => searchOpen
    ? rows.map((row) => ({ kind: 'row' as const, id: row.id, row }))
    : presentRows(rows, presentation, answers), [answers, presentation, rows, searchOpen]);
  useEffect(() => {
    if (!externalJump || externalJump.conversationId !== conversationId) return;
    const matchesMessage = (row: ThreadRow) => row.kind === 'history' && String(row.message.id) === externalJump.messageId;
    const index = displayRows.findIndex((entry) => entry.kind === 'row'
      ? matchesMessage(entry.row)
      : entry.rows.some(matchesMessage));
    if (index < 0) return;
    virtuosoRef.current?.scrollToIndex({ index, align: 'center', behavior: 'smooth' });
    setExternalJump(null);
  }, [conversationId, displayRows, externalJump]);
  const latestCompletedEvent = useMemo(() => [...events].reverse().find((event) => event.type === 'message.completed'), [events]);

  useEffect(() => {
    const previous = lastAnnouncedReplyRef.current;
    if (!previous || previous.conversationId !== conversationId) {
      lastAnnouncedReplyRef.current = { conversationId, eventId: latestCompletedEvent?.id ?? '' };
      setScreenReaderAnnouncement('');
      return;
    }
    if (latestCompletedEvent?.id && latestCompletedEvent.id !== previous.eventId) {
      lastAnnouncedReplyRef.current = { conversationId, eventId: latestCompletedEvent.id };
      setScreenReaderAnnouncement(typeof latestCompletedEvent.data.content === 'string' ? latestCompletedEvent.data.content : '已收到回复');
    }
  }, [conversationId, latestCompletedEvent]);

  const searchableRows = useMemo<ConversationSearchRow[]>(() => rows.flatMap((row) => {
    if (row.kind !== 'history' && row.kind !== 'timeline') return [];
    return [{ id: row.id, text: searchTextForRow(row) }];
  }), [rows]);
  const searchMatches = useMemo(() => findConversationMatches(searchableRows, searchQuery), [searchableRows, searchQuery]);
  const activeSearchIndex = activeSearchKey ? searchMatches.findIndex((match) => match.key === activeSearchKey) : -1;
  const activeSearchMatch = searchMatches[activeSearchIndex >= 0 ? activeSearchIndex : 0];

  const openSearch = useCallback(() => {
    if (!searchOpen && document.activeElement instanceof HTMLElement) previousFocusRef.current = document.activeElement;
    setSearchOpen(true);
    requestAnimationFrame(() => searchInputRef.current?.focus());
  }, [searchOpen]);

  const closeSearch = useCallback(() => {
    setSearchOpen(false);
    clearConversationHighlights();
    requestAnimationFrame(() => previousFocusRef.current?.focus());
  }, []);

  const moveSearch = useCallback((direction: number) => {
    if (!searchMatches.length) return;
    const current = activeSearchIndex < 0 ? 0 : activeSearchIndex;
    setActiveSearchKey(searchMatches[(current + direction + searchMatches.length) % searchMatches.length].key);
  }, [activeSearchIndex, searchMatches]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement | null)?.closest?.('[data-shortcut-recorder]')) return;
      const isSearchShortcut = (event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 'f';
      if (isSearchShortcut && !event.defaultPrevented && !matchShortcut(event, loadBindings())) {
        event.preventDefault();
        event.stopPropagation();
        openSearch();
        return;
      }
      if (!searchOpen) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        closeSearch();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        event.stopPropagation();
        moveSearch(event.shiftKey ? -1 : 1);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [closeSearch, moveSearch, openSearch, searchOpen]);

  // Searching the whole conversation intentionally pages older history in through the store's existing API.
  useEffect(() => {
    if (!searchOpen || !searchQuery.trim() || !conversationId || !hasEarlier || loading || loadingEarlier) {
      if (!searchQuery.trim() || !searchOpen) {
        if (searchHistoryLoading) setSearchHistoryLoading(false);
        if (searchHistoryIncomplete) setSearchHistoryIncomplete(false);
      }
      return;
    }
    const oldestId = history[0]?.id ?? '';
    const attemptKey = `${conversationId}:${oldestId}`;
    if (historyLoadAttemptRef.current === attemptKey) return;
    historyLoadAttemptRef.current = attemptKey;
    setSearchHistoryLoading(true);
    void loadEarlier(conversationId).then(() => {
      const state = useAtlasStore.getState();
      if (state.activeConversationId !== conversationId) return;
      const nextOldestId = state.conversationMessages[conversationId]?.[0]?.id ?? '';
      const failedToAdvance = nextOldestId === oldestId && state.messagesHasEarlier[conversationId] !== false;
      setSearchHistoryLoading(false);
      setSearchHistoryIncomplete(failedToAdvance);
    });
  }, [conversationId, hasEarlier, history, loadEarlier, loading, loadingEarlier, searchHistoryIncomplete, searchHistoryLoading, searchOpen, searchQuery]);

  useEffect(() => {
    if (!searchOpen || !searchQuery.trim() || !activeSearchMatch) {
      clearConversationHighlights();
      searchTargetRef.current = '';
      return;
    }
    const targetSignature = `${conversationId}:${searchQuery}:${activeSearchMatch.key}`;
    if (searchTargetRef.current === targetSignature) return;
    searchTargetRef.current = targetSignature;
    const index = rows.findIndex((row) => row.id === activeSearchMatch.rowId);
    if (index < 0) return;
    virtuosoRef.current?.scrollToIndex({ index, align: 'center', behavior: 'smooth' });

    let attempts = 0;
    let frame = 0;
    const reveal = () => {
      const root = Array.from(threadRef.current?.querySelectorAll<HTMLElement>('[data-conversation-search-row]') ?? [])
        .find((element) => element.dataset.conversationSearchRow === activeSearchMatch.rowId);
      if (!root && attempts++ < 16) { frame = requestAnimationFrame(reveal); return; }
      if (!root) return;
      const range = highlightConversationRow(root, searchQuery, activeSearchMatch.occurrence);
      if (!range) return;
      const rect = range.getBoundingClientRect();
      const parent = threadRef.current;
      if (!parent || !rect.height) return;
      const parentRect = parent.getBoundingClientRect();
      parent.scrollTo({ top: parent.scrollTop + rect.top - parentRect.top - Math.min(120, parent.clientHeight * 0.2), behavior: 'smooth' });
    };
    frame = requestAnimationFrame(reveal);
    return () => cancelAnimationFrame(frame);
  }, [activeSearchMatch, conversationId, rows, searchOpen, searchQuery, threadRef]);

  const context = useMemo(() => ({ events, store: activityStore, username, setTab, busy: working, onOpenBrowser }), [events, activityStore, username, setTab, working, onOpenBrowser]);

  // 会话切换：卸载前把当前滚动位置存起来；新会话没有存档就从最新一条开始。
  useEffect(() => {
    const handle = virtuosoRef.current;
    return () => {
      try {
        handle?.getState((state) => { savedScrollStates.set(conversationId, state); });
      } catch { /* 列表已卸载，忽略 */ }
    };
  }, [conversationId]);

  // 向上翻页在头部插入了新行：调高 firstItemIndex，Virtuoso 会保持视口不动。
  // 必须在渲染期算好（Virtuoso 同一帧就要用到），按 (conversationId, length) 幂等。
  if (previousHistory.current.conversationId !== conversationId || previousHistory.current.length !== history.length) {
    const previous = previousHistory.current;
    if (previous.conversationId === conversationId && history.length > previous.length) {
      const current = firstItemIndexByConversation.get(conversationId) ?? 0;
      firstItemIndexByConversation.set(conversationId, current + (history.length - previous.length));
    }
    if (history.length === 0) firstItemIndexByConversation.delete(conversationId);
    previousHistory.current = { conversationId, length: history.length };
  }
  const firstItemIndex = firstItemIndexByConversation.get(conversationId) ?? 0;

  // 每次滚动停下就存档一次，切会话/切视图时最多丢最后半屏的精确位置。
  const saveScrollState = useCallback(() => {
    const key = scrollStateKeyRef.current;
    virtuosoRef.current?.getState((state) => { savedScrollStates.set(key, state); });
  }, []);

  const startReached = useCallback(() => {
    const state = useAtlasStore.getState();
    if (state.loadingEarlierConversationId || state.messagesHasEarlier[conversationId] === false) return;
    if (!state.conversationMessages[conversationId]?.length) return;
    void state.loadEarlier(conversationId);
  }, [conversationId]);

  const renderRow = useCallback((row: ThreadRow) => {
    switch (row.kind) {
      case 'load-earlier':
        return <div className="flex justify-center py-2">
          {loadingEarlier
            ? <span className="flex items-center gap-2 text-[12.5px] text-fg-3">正在载入更早的消息…</span>
            : <Button size="sm" variant="ghost" onClick={() => void loadEarlier(conversationId)}><History size={14} />载入更早的消息</Button>}
        </div>;
      case 'truncated':
        return <div className="my-3 flex items-center gap-2 text-[12.5px] text-fg-3" role="note">
          <History size={13} className="shrink-0 text-fg-3" />已折叠早期事件（{row.count} 条）
        </div>;
      case 'history':
        if (row.message.role === 'user' && isTodoEdit(row.message.content)) return <div className="my-3 flex items-center gap-2 text-[12.5px] text-fg-2">
          <ListChecks size={13} className="shrink-0 text-brand" /><span>{todoEditNotice(row.message.content)}</span>
        </div>;
        const metadata = row.message.metadata && typeof row.message.metadata === 'object' ? row.message.metadata as Record<string, unknown> : {};
        const memoryCitations = Array.isArray(metadata.memory_citations) ? metadata.memory_citations.filter((ref): ref is string => typeof ref === 'string') : [];
        return <ConversationMessage id={String(row.message.id)} role={row.message.role === 'user' ? 'user' : 'assistant'} content={row.message.content} username={username} continued={row.continued} actions={historyActions(row.message)} memoryCitations={memoryCitations} createdAt={row.message.created_at} />;
      case 'subtask': return <SubtaskActivityCard activity={row.activity} />;
      case 'recap': return <article className="my-3 rounded-xl border border-brand/20 bg-brand-soft/50 px-3.5 py-3" aria-label="自动回顾"><div className="flex items-center gap-2 text-[11px] font-medium text-brand"><BookOpenText size={13} />本轮自动回顾{row.createdAt ? ` · ${new Date(row.createdAt).toLocaleString()}` : ''}</div><div className="mt-2 whitespace-pre-wrap text-[12.5px] leading-relaxed text-fg-2">{row.summary}</div></article>;
      case 'empty':
        return emptyState;
      case 'timeline':
        return <TimelineRow item={row.item} context={context} firstInTurn={row.firstInTurn} last={row.last} />;
      default:
        return null;
    }
  }, [context, conversationId, emptyState, historyActions, loadEarlier, loadingEarlier, username]);

  useEffect(() => {
    const onOpenSubtask = (event: Event) => {
      const subtaskId = (event as CustomEvent<{ subtaskId?: string }>).detail?.subtaskId;
      if (!subtaskId) return;
      let attempts = 0;
      const locate = () => {
        const target = document.querySelector<HTMLElement>(`[data-subtask-card="${CSS.escape(subtaskId)}"]`);
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'center' });
          target.focus({ preventScroll: true });
        } else if (attempts++ < 30) requestAnimationFrame(locate);
      };
      locate();
    };
    window.addEventListener('atlas:open-subtask', onOpenSubtask);
    return () => window.removeEventListener('atlas:open-subtask', onOpenSubtask);
  }, [conversationId]);

  const renderDisplayRow = useCallback((displayRow: ThreadDisplayRow) => {
    if (displayRow.kind === 'row') return renderRow(displayRow.row);
    const label = THREAD_CLASSES.find(({ id }) => id === displayRow.classId)?.label ?? displayRow.classId;
    return <ThreadClassGroup key={displayRow.id} classId={displayRow.classId} label={label} count={displayRow.rows.length}
      collapsed={presentation.collapsed[displayRow.classId]}>
      {displayRow.rows.map((row) => <div key={row.id}>{renderRow(row)}</div>)}
    </ThreadClassGroup>;
  }, [presentation.collapsed, renderRow]);

  const onThreadKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const target = event.target;
    const editable = target instanceof HTMLElement && (target.isContentEditable || Boolean(target.closest('input, textarea, select, button, [role="button"], [data-shortcut-recorder]')));
    if (tuiFullscreen && !editable && event.ctrlKey && event.shiftKey && !event.metaKey && event.key.toLowerCase() === 'c') {
      event.preventDefault();
      const selected = window.getSelection()?.toString().trim() ?? '';
      if (!selected) { onToast?.('先选中要复制的对话文字，再按 Ctrl+Shift+C'); return; }
      if (!navigator.clipboard?.writeText) { onToast?.('剪贴板不可用'); return; }
      void navigator.clipboard.writeText(selected).then(() => onToast?.('已复制选中的对话文字')).catch(() => onToast?.('剪贴板不可用'));
      return;
    }
    if (tuiFullscreen && !editable && !event.altKey && !event.ctrlKey && !event.metaKey && (event.key === 'PageUp' || event.key === 'PageDown')) {
      event.preventDefault();
      threadRef.current?.scrollBy({ top: (event.key === 'PageDown' ? 1 : -1) * threadRef.current.clientHeight * 0.88, behavior: 'smooth' });
      return;
    }
    if (editable || event.defaultPrevented || event.altKey || event.shiftKey || !event.ctrlKey || event.metaKey || event.key.toLowerCase() !== 'o') return;
    event.preventDefault();
    const modes: ThreadPresentationMode[] = hasReasoning
      ? ['normal', 'thinking', 'verbose']
      : ['normal', 'verbose'];
    const current = modes.indexOf(presentation.mode);
    setPresentation(settingsForMode(modes[(current + 1 + modes.length) % modes.length]));
  };

  return <div
    ref={(element) => { threadRef.current = element; setScrollParent(element); }}
    role="region"
    aria-label="任务活动"
    aria-describedby="thread-keyboard-help"
    aria-keyshortcuts={tuiFullscreen ? 'PageUp PageDown Escape Control+Shift+C Control+O' : 'Control+O'}
    tabIndex={0}
    onKeyDown={onThreadKeyDown}
    className="min-h-0 flex-1 overflow-auto px-8 pt-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand focus-visible:outline-offset-[-2px]"
  >
    <span id="thread-keyboard-help" className="sr-only">对话活动区域。{tuiFullscreen ? '全屏时按 Page Up 或 Page Down 翻页；按 Escape 退出；选中对话文字后按 Ctrl+Shift+C 复制。' : ''}焦点在此区域时，按 Ctrl 加 O 在常规、思考和详细显示方式间切换。按 Tab 访问消息操作与活动设置。</span>
    <ThreadPresentationControls settings={presentation} onChange={setPresentation} hasReasoning={hasReasoning} />
    <ConversationSearch
      open={searchOpen}
      query={searchQuery}
      active={searchMatches.length ? (activeSearchIndex >= 0 ? activeSearchIndex : 0) + 1 : 0}
      total={searchMatches.length}
      historyLoading={searchHistoryLoading}
      historyIncomplete={searchHistoryIncomplete}
      inputRef={searchInputRef}
      onOpen={openSearch}
      onQueryChange={(value) => { setSearchQuery(value); setActiveSearchKey(null); }}
      onPrevious={() => moveSearch(-1)}
      onNext={() => moveSearch(1)}
      onClose={closeSearch}
    />
    <div className="mx-auto w-[min(760px,100%)] pb-8">
      {scrollParent && !loading && <Virtuoso
        key={scrollStateKey}
        ref={virtuosoRef}
        customScrollParent={scrollParent}
        data={displayRows}
        computeItemKey={(_index, row) => row.id}
        itemContent={(_index, row) => <div data-conversation-search-row={row.kind === 'row' ? row.id : row.rows[0]?.id} style={{ display: 'contents' }}>{renderDisplayRow(row)}</div>}
        increaseViewportBy={{ top: 600, bottom: 600 }}
        atBottomThreshold={160}
        followOutput={(isAtBottom: boolean) => (isAtBottom ? 'auto' : false)}
        startReached={startReached}
        isScrolling={(scrolling) => { if (!scrolling) saveScrollState(); }}
        initialTopMostItemIndex={Math.max(0, displayRows.length - 1)}
        firstItemIndex={firstItemIndex}
        restoreStateFrom={savedScrollStates.get(scrollStateKey)}
      />}
      {loading && <p className="py-6 text-center text-[13px] text-fg-3" role="status">正在载入这段对话…</p>}
      {!focusMode && presentation.show.tools && <ComputerUseTrail events={events} />}
      {!focusMode && thinking && <div className="my-5 flex items-center gap-3 text-[13px] text-fg-3" aria-label="Atlas 正在思考">
        <Mark className="size-[26px]" working />正在想…
      </div>}
      {screenReaderAnnouncement && <div className="sr-only" role="status" aria-live={presentation.announceCompletedReplies ? 'polite' : 'off'} aria-atomic="true">Atlas 回复：{screenReaderAnnouncement}</div>}
      {!focusMode && footerNote}
    </div>
  </div>;
}

function SubtaskActivityCard({ activity }: { activity: Record<string, unknown> }) {
  const subtaskId = typeof activity.subtask_id === 'string' ? activity.subtask_id : '';
  const event = typeof activity.event === 'string' ? activity.event : '';
  const status = event === 'subtask.started' ? '已开始'
    : event === 'subtask.completed' || event === 'subtask.background_completed' || event === 'subtask.group_completed' ? '已完成'
      : '有进展';
  const title = String(activity.title ?? activity.goal ?? `子任务 ${subtaskId.slice(0, 8)}`);
  const detail = String(activity.summary ?? activity.text ?? '');
  if (!subtaskId) return null;
  return <article data-subtask-card={subtaskId} tabIndex={-1} className="my-3 rounded-xl border border-line bg-sunken px-3.5 py-3 outline-none focus-visible:ring-2 focus-visible:ring-brand">
    <div className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg">子任务：{title}</span><span className="shrink-0 rounded-full bg-brand/10 px-2 py-0.5 text-[10.5px] text-brand">{status}</span></div>
    {detail && <p className="mb-0 mt-1.5 whitespace-pre-wrap break-words text-[12px] leading-5 text-fg-2">{detail}</p>}
  </article>;
}
