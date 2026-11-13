import type { MentionItem } from '../components/Composer';

export interface ComposerDraft {
  text: string;
  mentions: MentionItem[];
  attachments: Array<{ id: string; name: string; mime: string; size: number; kind: 'image' | 'file' }>;
}

const keyFor = (conversationId: string) => `atlas.draft.v2.${conversationId || 'home'}`;

export function readComposerDraft(storage: Pick<Storage, 'getItem'>, conversationId: string): ComposerDraft {
  try {
    const raw = storage.getItem(keyFor(conversationId));
    if (raw) {
      const value: unknown = JSON.parse(raw);
      if (value && typeof value === 'object') {
        const row = value as Partial<ComposerDraft>;
        return {
          text: typeof row.text === 'string' ? row.text : '',
          mentions: Array.isArray(row.mentions) ? row.mentions.filter(isMention) : [],
          attachments: Array.isArray(row.attachments) ? row.attachments.filter(isAttachment) : [],
        };
      }
    }
    return { text: storage.getItem(`atlas.draft.${conversationId || 'home'}`) ?? '', mentions: [], attachments: [] };
  } catch { return { text: '', mentions: [], attachments: [] }; }
}

export function writeComposerDraft(storage: Pick<Storage, 'setItem' | 'removeItem'>, conversationId: string, draft: ComposerDraft): void {
  try {
    if (!draft.text && !draft.mentions.length && !draft.attachments.length) {
      storage.removeItem(keyFor(conversationId));
      storage.removeItem(`atlas.draft.${conversationId || 'home'}`);
    } else storage.setItem(keyFor(conversationId), JSON.stringify(draft));
  } catch { /* storage unavailable; attachment bytes remain staged in IndexedDB */ }
}

export function serializeMentionContext(text: string, mentions: MentionItem[]): string {
  if (!mentions.length) return text;
  const instruction: Record<MentionItem['kind'], (item: MentionItem) => string> = {
    file: (item) => `- 文件 ${item.label}（${item.id}）`,
    conversation: (item) => `- 请用 read_session 读取会话 ${item.id}（${item.label}）`,
    resource: (item) => `- MCP 资源 ${item.label}（${item.id}）`,
    element: (item) => `- 请根据 PPT 元素引用进行精确修改：${item.label}（文件/定位：${item.id}）`,
  };
  return `${text}\n\n引用上下文：\n${mentions.map((item) => instruction[item.kind](item)).join('\n')}`;
}

function isMention(value: unknown): value is MentionItem {
  if (!value || typeof value !== 'object') return false;
  const row = value as Partial<MentionItem>;
  return ['file', 'conversation', 'resource', 'element'].includes(String(row.kind)) && typeof row.id === 'string' && typeof row.label === 'string';
}

function isAttachment(value: unknown): value is ComposerDraft['attachments'][number] {
  if (!value || typeof value !== 'object') return false;
  const row = value as Partial<ComposerDraft['attachments'][number]>;
  return typeof row.id === 'string' && typeof row.name === 'string' && typeof row.mime === 'string'
    && typeof row.size === 'number' && (row.kind === 'image' || row.kind === 'file');
}
