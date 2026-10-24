import { useEffect, useState } from 'react';
import { api } from '../services/api';

type ConversationMemory = { metadata?: { use_memories?: boolean; generate_memories?: boolean } };

export default function ConversationMemoryPanel({ apiBaseUrl, conversationId }: { apiBaseUrl: string; conversationId: string }) {
  const [settings, setSettings] = useState({ use_memories: true, generate_memories: true });
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api<ConversationMemory>(apiBaseUrl, `/api/conversations/${encodeURIComponent(conversationId)}`)
      .then((value) => { if (active) setSettings({ use_memories: value.metadata?.use_memories !== false, generate_memories: value.metadata?.generate_memories !== false }); })
      .catch((exc) => { if (active) setError(exc instanceof Error ? exc.message : String(exc)); });
    return () => { active = false; };
  }, [apiBaseUrl, conversationId]);
  const update = async (key: keyof typeof settings, checked: boolean) => {
    const next = { ...settings, [key]: checked };
    setSettings(next); setError('');
    try { await api(apiBaseUrl, `/api/conversations/${encodeURIComponent(conversationId)}`, { method: 'PUT', json: next }); }
    catch (exc) { setSettings(settings); setError(exc instanceof Error ? exc.message : String(exc)); }
  };
  return <section>
    <h3 className="m-0 text-[17px] font-semibold text-heading">本对话记忆</h3>
    <p className="mt-1 mb-5 text-[13px] text-fg-3">分别控制 Atlas 是否在本对话读取已有记忆，以及是否从后续对话生成记忆。</p>
    <div className="grid gap-3 rounded-xl bg-sunken p-4">
      <label className="flex items-center gap-2 text-[13px] text-fg"><input type="checkbox" checked={settings.use_memories} onChange={(event) => void update('use_memories', event.target.checked)} />读取记忆</label>
      <label className="flex items-center gap-2 text-[13px] text-fg"><input type="checkbox" checked={settings.generate_memories} onChange={(event) => void update('generate_memories', event.target.checked)} />生成记忆</label>
      {error && <p role="alert" className="m-0 text-[12px] text-danger">设置保存失败：{error}</p>}
    </div>
  </section>;
}
