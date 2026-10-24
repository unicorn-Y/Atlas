import { useEffect, useState } from 'react';
import { api } from '../services/api';
import { readNotificationPreferences, saveNotificationPreferences } from '../services/notificationsSettings';

interface Proposal { id: string; key: string; from: unknown; to: unknown; reason: string }

const LEVEL_LABELS: Record<string, string> = { attention: '只在需要我时', all: '全部', off: '关闭' };

export default function SettingsProposalCards({ apiBaseUrl, onModel, onToast, currentModel, modelName }: {
  apiBaseUrl: string; onModel: (id: string) => void; onToast: (text: string) => void;
  currentModel?: string; modelName?: (id: string) => string;
}) {
  const [advisor, setAdvisor] = useState<string>('');
  const [rows, setRows] = useState<Proposal[]>([]);
  const refresh = () => void api<{ proposals: Proposal[] }>(apiBaseUrl, '/api/u4/proposals').then((data) => setRows(data.proposals)).catch(() => setRows([]));
  useEffect(() => { if (rows.some((row) => row.key === 'advisor_model')) void api<{ advisor_model?: string }>(apiBaseUrl, '/api/u4/settings').then((data) => setAdvisor(String(data.advisor_model ?? ''))).catch(() => undefined); }, [apiBaseUrl, rows]);
  useEffect(() => { refresh(); const timer = window.setInterval(refresh, 2500); return () => window.clearInterval(timer); }, [apiBaseUrl]);
  const resolve = async (item: Proposal, approve: boolean) => {
    try {
      await api(apiBaseUrl, `/api/u4/proposals/${encodeURIComponent(item.id)}/resolve`, { method: 'POST', json: { approve } });
      if (approve && item.key === 'model') onModel(String(item.to));
      if (approve && item.key === 'notifications.level') {
        const current = readNotificationPreferences(); const level = item.to === 'all' || item.to === 'off' || item.to === 'attention' ? item.to : null;
        if (!level) throw new Error(`不支持的通知级别 ${String(item.to)}`);
        saveNotificationPreferences({ ...current, level, enabled: level !== 'off' });
      }
      onToast(approve ? '已应用这项设置建议' : '已拒绝这项设置建议'); refresh();
    } catch (error) { onToast(`处理设置建议失败：${error instanceof Error ? error.message : String(error)}`); }
  };
  if (!rows.length) return null;
  const show = (key: string, value: unknown) => {
    const text = String(value ?? '');
    if (key === 'notifications.level') return LEVEL_LABELS[text] ?? text;
    if (!text) return key === 'advisor_model' ? '不使用顾问' : '未设置';
    return modelName ? modelName(text) : text;
  };
  const current = (key: string) => key === 'notifications.level' ? readNotificationPreferences().level : key === 'model' ? currentModel : advisor;
  const label = (key: string) => key === 'model' ? '默认模型' : key === 'notifications.level' ? '通知级别' : '顾问模型';
  return <aside aria-label="待确认的设置建议" className="fixed right-5 bottom-5 z-[75] grid w-[min(420px,calc(100vw-2rem))] gap-2">
    {rows.map((item) => <section key={item.id} className="rounded-xl border border-line bg-panel p-4 shadow-xl">
      <b className="text-[13px] text-heading">设置修改建议：{label(item.key)}</b>
      <p className="my-2 text-[12.5px] text-fg-2">从 <code>{show(item.key, current(item.key))}</code> 改为 <code>{show(item.key, item.to)}</code></p>
      {item.reason && <p className="mb-3 mt-0 text-[12px] text-fg-3">{item.reason}</p>}
      <div className="flex justify-end gap-2"><button onClick={() => void resolve(item, false)} className="h-8 rounded-lg border border-line px-3 text-[12px]">拒绝</button><button onClick={() => void resolve(item, true)} className="h-8 rounded-lg bg-brand px-3 text-[12px] text-on-primary">确认修改</button></div>
    </section>)}
  </aside>;
}
