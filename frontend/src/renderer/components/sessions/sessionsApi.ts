/** 独立会话（core/atlas/sessions）的前端接口：提议卡片、子会话列表、开始/停止/发消息。 */
import { api } from '../../services/api';
import { backend, useAtlasStore } from '../../store/useAtlasStore';

export type LinkedSessionStatus = 'proposed' | 'starting' | 'running' | 'waiting' | 'idle' | 'failed' | 'stopped' | 'dismissed' | 'expired';
export interface LinkedSession {
  session_id: string; name: string; title: string; prompt: string; context: 'fresh' | 'fork';
  initiation: 'user_asked' | 'offer' | 'own_initiative'; status: LinkedSessionStatus;
  parent_conversation_id: string | null; conversation_id: string | null;
  use_worktree: boolean; worktree_path: string | null; worktree_branch: string | null;
  last_report: string; last_status: string | null; stats: { duration_s?: number | null; input_tokens?: number; output_tokens?: number };
  error: string | null; created_at: string; updated_at: string; expires_at: string | null; run_id?: string; waiting_for?: string | null;
}

export const STATUS_LABEL: Record<LinkedSessionStatus, string> = {
  proposed: '等你开始', starting: '启动中', running: '运行中', waiting: '等你确认', idle: '已停下',
  failed: '失败', stopped: '已停止', dismissed: '已忽略', expired: '已失效',
};

const base = () => backend.apiBaseUrl;
export const sessionsApi = {
  list: (parent?: string) => api<{ sessions: LinkedSession[] }>(base(), `/api/sessions${parent ? `?parent=${encodeURIComponent(parent)}` : ''}`),
  activeRun: (conversationId: string) => api<{ run: { run_id: string; status: string } | null }>(base(), `/api/sessions/active-run?conversation_id=${encodeURIComponent(conversationId)}`),
  start: (id: string) => api<{ session: LinkedSession }>(base(), `/api/sessions/${encodeURIComponent(id)}/start`, { method: 'POST' }),
  dismiss: (id: string, reason = '') => api<{ session: LinkedSession }>(base(), `/api/sessions/${encodeURIComponent(id)}/dismiss`, { method: 'POST', json: { reason } }),
  stop: (id: string) => api<{ session: LinkedSession }>(base(), `/api/sessions/${encodeURIComponent(id)}/stop`, { method: 'POST' }),
  message: (id: string, text: string) => api<{ status: string; run_id: string }>(base(), `/api/sessions/${encodeURIComponent(id)}/message`, { method: 'POST', json: { text } }),
};

/** 打开一个会话（子会话可能刚建出来，列表里还没有就先刷新）。 */
export async function openConversationById(conversationId: string): Promise<void> {
  const store = useAtlasStore.getState();
  let conversation = store.conversations.find((item) => item.id === conversationId);
  if (!conversation) {
    await store.refreshConversations();
    conversation = useAtlasStore.getState().conversations.find((item) => item.id === conversationId);
  }
  if (conversation) await useAtlasStore.getState().openConversation(conversation);
  const run = await sessionsApi.activeRun(conversationId).catch(() => null);
  if (run?.run) useAtlasStore.getState().attachRun(conversationId, run.run.run_id);
}

export function sessionsChanged() { window.dispatchEvent(new Event('atlas:linked-sessions')); }
