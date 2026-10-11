import { useCallback, useEffect, useState } from 'react';
import { api } from '../services/api';
import { Button } from '../ui/Button';

interface TelemetryPrivacyState {
  enabled: boolean;
  scope: 'memos-local-plugin';
  applies_to?: 'next_bridge_start';
  applied?: boolean;
}

interface TelemetryPrivacyPanelProps {
  apiBaseUrl: string;
}

export default function TelemetryPrivacyPanel({ apiBaseUrl }: TelemetryPrivacyPanelProps) {
  const [state, setState] = useState<TelemetryPrivacyState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const result = await api<TelemetryPrivacyState>(apiBaseUrl, '/api/diagnostics/telemetry-privacy');
      setState(result);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, [apiBaseUrl]);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    if (!state) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await api<TelemetryPrivacyState>(apiBaseUrl, '/api/diagnostics/telemetry-privacy', {
        method: 'PUT',
        json: { enabled: !state.enabled },
      });
      setState(result);
      setNotice(result.enabled ? '已启用；后续 bridge 会按部署的遥测凭据决定是否发送。' : '已关闭，并已停止当前 MemOS bridge。');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      await load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-fg">MemOS 插件遥测与错误事件</h3>
          <p className="mt-1.5 max-w-3xl text-xs leading-5 text-fg-2">
            仅控制 Atlas 附带的 MemOS Local Hermes 插件。部署配置了 ARMS 遥测凭据时，插件会发送匿名汇总事件和错误类别；来源代码不会发送会话文本或查询内容。
            关闭会写入 bridge 实际读取的 MemOS 配置，并立即终止当前 bridge；正在执行的 MemOS 操作会中断，之后会按关闭状态重启。Atlas 本机诊断、系统日志和其他服务的遥测不受此项控制。
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <span className={`text-xs font-medium ${state?.enabled ? 'text-amber-400' : 'text-emerald-400'}`}>
            {state ? (state.enabled ? '允许发送（需部署凭据）' : '已关闭') : '读取中'}
          </span>
          <Button type="button" onClick={() => void save()} disabled={!state || busy}>
            {busy ? '保存中…' : state?.enabled ? '关闭遥测' : '启用遥测'}
          </Button>
        </div>
      </div>
      {notice && <p className="mt-3 text-xs text-emerald-400" role="status">{notice}</p>}
      {error && <p className="mt-3 whitespace-pre-wrap text-xs text-red-400" role="alert">{error}</p>}
      {!error && state && <p className="mt-3 text-[11px] text-fg-3">状态保存在 MemOS 的 telemetry.enabled 配置中。</p>}
    </section>
  );
}
