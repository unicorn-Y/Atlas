import { useCallback, useEffect, useState } from 'react';
import { api } from '../../services/api';

type RouteRow = {
  purpose: string;
  label?: string;
  resolved: boolean;
  provider?: string | null;
  api_mode?: string | null;
  model?: string | null;
  wire_model?: string | null;
  base_url?: string | null;
  fallback_reason?: string | null;
};

type ModelRow = { id: string; provider: string; current: boolean };

type Payload = {
  current_model: string;
  routes: RouteRow[];
  models: ModelRow[];
  note?: string;
};

export default function ModelRoutesPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api<Payload>(apiBaseUrl, '/api/maintenance/model-routes'));
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void load(); }, [load]);

  const routes = data?.routes ?? [];
  const distinct = new Set(routes.filter((row) => row.resolved).map((row) => row.model ?? ''));
  const onlyOne = distinct.size === 1;

  return (
    <div className="grid gap-3">
      <p className="m-0 text-[11.5px] text-fg-3">
        每种用途实际会走哪个模型、用哪种协议。这里只做解析，不发任何模型请求，所以点多少次都不会产生费用。
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => void load()} className="rounded border border-line px-2.5 py-1 text-[11px] text-fg">
          {loading ? '解析中…' : '重新解析'}
        </button>
        {data?.current_model && (
          <span className="text-[11.5px] text-fg-2">
            当前模型 <strong className="text-fg">{data.current_model}</strong>
            {data.models.length > 1 && ` · 可选 ${data.models.length} 个`}
          </span>
        )}
      </div>

      {error && <p role="alert" className="m-0 text-danger">读取路由失败：{error}</p>}

      {onlyOne && (
        <p className="m-0 rounded-lg bg-sunken px-3 py-2 text-[11.5px] text-fg-2">
          现在所有用途都指向同一个模型。想让便宜模型干杂活、强模型干主对话，就在这里换掉对应用途的模型后重新解析确认。
        </p>
      )}

      {routes.length > 0 && (
        <div className="overflow-auto rounded-lg border border-line">
          <table className="w-full border-collapse text-[11.5px]">
            <thead className="bg-sunken text-left text-fg-3">
              <tr>
                <th className="px-2 py-1.5 font-medium">用途</th>
                <th className="px-2 py-1.5 font-medium">模型</th>
                <th className="px-2 py-1.5 font-medium">协议</th>
                <th className="px-2 py-1.5 font-medium">提供方</th>
                <th className="px-2 py-1.5 font-medium">备注</th>
              </tr>
            </thead>
            <tbody>
              {routes.map((row) => (
                <tr key={row.purpose} className="border-t border-line align-top">
                  <td className="px-2 py-1.5 text-fg">
                    {row.label ?? row.purpose}
                    <div className="font-mono text-[10px] text-fg-3">{row.purpose}</div>
                  </td>
                  <td className="px-2 py-1.5 font-mono text-fg-2">{row.resolved ? (row.model ?? '—') : '—'}</td>
                  <td className="px-2 py-1.5 text-fg-3">{row.api_mode ?? '—'}</td>
                  <td className="px-2 py-1.5 text-fg-3">{row.provider ?? '—'}</td>
                  <td className={`px-2 py-1.5 ${row.resolved && !row.fallback_reason ? 'text-fg-3' : 'text-danger'}`}>
                    {row.fallback_reason ? (row.resolved ? `已降级：${row.fallback_reason}` : row.fallback_reason) : '正常'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data?.note && <p className="m-0 text-[10.5px] text-fg-3">{data.note}</p>}
    </div>
  );
}
