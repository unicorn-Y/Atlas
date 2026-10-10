import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type MutableRefObject } from 'react';
import { Virtuoso, type StateSnapshot, type VirtuosoHandle } from 'react-virtuoso';
import { History, ListChecks } from 'lucide-react';
import type { ConversationMessage as ConversationMessageData } from '@atlas/backend-adapter';
import { useAtlasStore } from '../store/useAtlasStore';
import { TimelineRow } from './ConversationActivity';
import ConversationMessage from './ConversationMessage';
import Mark from './Mark';
import { buildTimeline, todoEditNotice, type TimelineItem } from './timeline';
import { isTodoEdit } from './runInsights';
import { Button } from '../ui/Button';
import type { InspectorTab } from '../shell/Inspector';
import type { AgentEvent } from '../../types/runtime';

/** 每个会话最近一次的虚拟列表滚动状态，切回来时原位恢复。 */
const savedScrollStates = new Map<string, StateSnapshot>();
/** 向上翻页会在头部插入行；每个会话记住已插入多少行，滚动锚点和恢复的存档才不会错位。 */
const firstItemIndexByConversation = new Map<string, number>();

const EMPTY_EVENTS: AgentEvent[] = [];

/** 合并后的列表行：历史消息 + 实时时间线 + 头尾占位，交给一个 Virtuoso 实例统一虚拟化。 */
type ThreadRow =
  | { kind: 'load-earlier'; id: string }
  | { kind: 'truncated'; id: string; count: number }
  | { kind: 'history'; id: string; message: ConversationMessageData }
  | { kind: 'empty'; id: string }
  | { kind: 'timeline'; id: string; item: TimelineItem; firstInTurn: boolean; last: boolean };

export interface MessageThreadProps {
  /** 历史消息（已按分叉备注排好序、去掉当前运行那一轮）。 */
  history: ConversationMessageData[];
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
}

export default function MessageThread({ history, username, historyActions, emptyState, footerNote, threadRef, setTab, onOpenBrowser }: MessageThreadProps) {
  // 窄选择器：只有当前会话的运行事件/正文变化才重渲染这里，别的会话流式输出不打扰。
  const conversationId = useAtlasStore((state) => state.activeConversationId);
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
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const conversationRef = useRef(conversationId);
  conversationRef.current = conversationId;
  const previousHistory = useRef({ conversationId: '', length: 0 });

  const timelineItems = useMemo(() => buildTimeline(events), [events]);
  const thinking = working && !events.some((event) => event.type === 'message.delta' || event.type === 'tool.started');

  // TimelineRow 需要的 store：动作函数恒定，响应式字段（answers/profiles）单独订阅后合入。
  const activityStore = useMemo(() => ({ ...useAtlasStore.getState(), answers, profiles }), [answers, profiles]);

  const rows = useMemo<ThreadRow[]>(() => {
    const rows: ThreadRow[] = [];
    if (hasEarlier) rows.push({ kind: 'load-earlier', id: 'load-earlier' });
    if (truncatedCount > 0) rows.push({ kind: 'truncated', id: 'truncated', count: truncatedCount });
    for (const message of history) rows.push({ kind: 'history', id: `h-${message.id}`, message });
    if (!history.length && !timelineItems.length && !loading && emptyState) rows.push({ kind: 'empty', id: 'empty' });
    // Each Atlas turn shows its header once; later steps and replies in the same turn hang beneath it.
    let headed = false;
    for (let index = 0; index < timelineItems.length; index++) {
      const item = timelineItems[index];
      if (item.kind === 'user') headed = false;
      const firstInTurn = item.kind !== 'user' && !headed;
      if (item.kind !== 'user') headed = true;
      rows.push({ kind: 'timeline', id: `t-${item.id}`, item, firstInTurn, last: index === timelineItems.length - 1 });
    }
    return rows;
  }, [history, loading, timelineItems, hasEarlier, truncatedCount]);

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
    const id = conversationRef.current;
    virtuosoRef.current?.getState((state) => { savedScrollStates.set(id, state); });
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
        return <div className="my-3 ml-10 flex items-center gap-2 text-[12.5px] text-fg-3" role="note">
          <History size={13} className="shrink-0 text-fg-3" />已折叠早期事件（{row.count} 条）
        </div>;
      case 'history':
        if (row.message.role === 'user' && isTodoEdit(row.message.content)) return <div className="my-3 ml-10 flex items-center gap-2 text-[12.5px] text-fg-2">
          <ListChecks size={13} className="shrink-0 text-brand" /><span>{todoEditNotice(row.message.content)}</span>
        </div>;
        return <ConversationMessage role={row.message.role === 'user' ? 'user' : 'assistant'} content={row.message.content} username={username} actions={historyActions(row.message)} />;
      case 'empty':
        return emptyState;
      case 'timeline':
        return <TimelineRow item={row.item} context={context} firstInTurn={row.firstInTurn} last={row.last} />;
      default:
        return null;
    }
  }, [context, conversationId, emptyState, historyActions, loadEarlier, loadingEarlier, username]);

  return <div
    ref={(element) => { threadRef.current = element; setScrollParent(element); }}
    aria-label="任务活动"
    className="min-h-0 flex-1 overflow-auto px-8 pt-2"
  >
    <div className="mx-auto w-[min(720px,100%)] pb-8">
      {scrollParent && !loading && <Virtuoso
        key={conversationId}
        ref={virtuosoRef}
        customScrollParent={scrollParent}
        data={rows}
        computeItemKey={(_index, row) => row.id}
        itemContent={(_index, row) => renderRow(row)}
        increaseViewportBy={{ top: 600, bottom: 600 }}
        atBottomThreshold={160}
        followOutput={(isAtBottom: boolean) => (isAtBottom ? 'auto' : false)}
        startReached={startReached}
        isScrolling={(scrolling) => { if (!scrolling) saveScrollState(); }}
        initialTopMostItemIndex={Math.max(0, rows.length - 1)}
        firstItemIndex={firstItemIndex}
        restoreStateFrom={savedScrollStates.get(conversationId)}
      />}
      {loading && <p className="py-6 text-center text-[13px] text-fg-3" role="status">正在载入这段对话…</p>}
      {thinking && <div className="my-5 flex items-center gap-3 text-[13px] text-fg-3" aria-label="Atlas 正在思考">
        <Mark className="size-[26px]" working />正在想…
      </div>}
      {footerNote}
    </div>
  </div>;
}
