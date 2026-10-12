import { useState } from 'react';
import { GripVertical, MessageSquarePlus, Pause, Pencil, Play, RotateCcw, Send, X } from 'lucide-react';
import type { QueuedMessage } from '../store/useAtlasStore';
import { cn } from '../ui/cn';

interface ConversationQueuePanelProps {
  conversationId: string;
  items: QueuedMessage[];
  paused: boolean;
  running: boolean;
  onResume: () => void;
  onEdit: (item: QueuedMessage) => void;
  onSendNow: (id: string) => void;
  onRemove: (id: string) => void;
  onRestore?: (item: QueuedMessage, index: number) => void;
  onMove: (itemId: string, beforeItemId: string | null) => void;
  onSteer: (id: string) => void;
}

/** Queue controls stay controlled by the conversation store; this component owns only drag/undo UI state. */
export default function ConversationQueuePanel({
  conversationId, items, paused, running, onResume, onEdit, onSendNow, onRemove, onRestore, onMove, onSteer,
}: ConversationQueuePanelProps) {
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const [removed, setRemoved] = useState<{ item: QueuedMessage; index: number } | null>(null);
  if (!items.length && !(removed && onRestore)) return null;

  const remove = (item: QueuedMessage, index: number) => {
    setRemoved({ item, index });
    onRemove(item.id);
  };
  const restore = () => {
    if (!removed || !onRestore) return;
    onRestore(removed.item, removed.index);
    setRemoved(null);
  };

  return <div className="mb-2 grid gap-1.5" aria-label="待发送的消息" data-conversation-id={conversationId}>
    {paused && items.length > 0 && <div className="flex items-center gap-2 rounded-xl bg-sunken px-3 py-2 text-[12.5px] text-fg-2">
      <Pause size={13} />任务已停止，后面的 {items.length} 条先不发。<span className="flex-1" />
      <button type="button" onClick={onResume} className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-hover"><Play size={13} />继续发送</button>
    </div>}
    {items.map((item, index) => <div key={item.id} draggable
      onDragStart={(event) => { setDragId(item.id); event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', item.id); }}
      onDragOver={(event) => { if (dragId && dragId !== item.id) { event.preventDefault(); setOverId(item.id); } }}
      onDragLeave={() => setOverId((current) => current === item.id ? null : current)}
      onDrop={(event) => {
        event.preventDefault();
        const sourceId = dragId || event.dataTransfer.getData('text/plain');
        const sourceIndex = items.findIndex((entry) => entry.id === sourceId);
        const targetIndex = items.findIndex((entry) => entry.id === item.id);
        if (sourceIndex >= 0 && targetIndex >= 0 && sourceIndex !== targetIndex) {
          const before = sourceIndex < targetIndex ? items[targetIndex + 1]?.id ?? null : item.id;
          onMove(sourceId, before);
        }
        setDragId(null); setOverId(null);
      }}
      onDragEnd={() => { setDragId(null); setOverId(null); }}
      className={cn('flex items-center gap-2.5 rounded-xl bg-sunken px-3 py-2 text-[13px]', dragId === item.id && 'opacity-40', overId === item.id && 'shadow-[inset_0_2px_0_var(--brand)]')}>
      <span aria-label="拖动以调整顺序" className="shrink-0 cursor-grab text-fg-3 active:cursor-grabbing"><GripVertical size={14} /></span>
      <span className="shrink-0 text-[12px] text-fg-3 tabular-nums">{index === 0 ? '下一条' : `第 ${index + 1} 条`}</span>
      <span className="min-w-0 flex-1 truncate text-fg" title={item.content}>{item.content}</span>
      {item.attachments.length + item.files.length > 0 && <span className="shrink-0 text-[12px] text-fg-3">{item.attachments.length + item.files.length} 个附件</span>}
      {running && !item.attachments.length && !item.files.length && !item.refs && !item.profileId && !item.agentId && <button type="button" title="现在就交给正在做的任务" aria-label="把这条插话进当前任务" onClick={() => onSteer(item.id)}
        className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><MessageSquarePlus size={13} /></button>}
      <button type="button" title="取回来修改" aria-label="编辑这条待发消息" onClick={() => onEdit(item)}
        className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><Pencil size={13} /></button>
      <button type="button" title="停下当前这一步，马上发这条" aria-label="立即发送这条消息" onClick={() => onSendNow(item.id)}
        className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><Send size={13} /></button>
      <button type="button" title="不发了" aria-label="删除这条待发消息" onClick={() => remove(item, index)}
        className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><X size={13} /></button>
    </div>)}
    {removed && onRestore && <div role="status" className="flex items-center gap-2 rounded-lg px-3 py-1 text-[12px] text-fg-2">
      已移除一条待发消息。<span className="flex-1" /><button type="button" onClick={restore} className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-hover"><RotateCcw size={12} />撤销</button>
    </div>}
  </div>;
}
