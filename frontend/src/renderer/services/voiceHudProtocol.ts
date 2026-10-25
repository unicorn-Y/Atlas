export type HudStatus = 'idle' | 'connecting' | 'preparing' | 'listening' | 'error';
export interface HudState { status: HudStatus; detail: string; transcript: string; committedTranscript: string }
export interface HudMessage { type?: string; text?: string; detail?: string; progress?: number }

export const initialHudState = (): HudState => ({ status: 'idle', detail: '快捷键开始语音输入', transcript: '', committedTranscript: '' });

export function reduceHudMessage(state: HudState, message: HudMessage): HudState {
  if (message.type === 'preparing') return { ...state, status: 'preparing', detail: message.detail || '正在准备本地语音模型…' };
  if (message.type === 'progress') return { ...state, status: 'preparing', detail: `正在准备语音模型 ${Math.round((message.progress ?? 0) * 100)}%` };
  if (message.type === 'ready') return { ...state, status: 'listening', detail: '正在聆听' };
  if (message.type === 'partial') return { ...state, transcript: `${state.committedTranscript}${state.committedTranscript ? ' ' : ''}${message.text || ''}` };
  if (message.type === 'final' && message.text?.trim()) {
    const committedTranscript = `${state.committedTranscript}${state.committedTranscript ? ' ' : ''}${message.text.trim()}`.slice(-600);
    return { ...state, committedTranscript, transcript: committedTranscript };
  }
  if (message.type === 'error') return { ...state, status: 'error', detail: message.detail || '语音识别失败' };
  return state;
}
