import { useState } from 'react';
import { api } from '../../services/api';

type Estimate = {
  schema_tokens_before: number;
  schema_tokens_after: number;
  prompt_tokens: number;
  chars_per_token: number;
};

type ToolDetail = { rank?: number; score?: number; family?: string; kept?: boolean; reason?: string };

type Result = {
  tier: string;
  bucket: string;
  tool_source: string;
  tool_count_total: number;
  tool_count_offered: number;
  offered: string[];
  schema_chars_before: number;
  schema_chars_after: number;
  schema_saved_ratio: number | null;
  estimate: Estimate;
  selection: { tools?: Record<string, ToolDetail>; query_tokens?: string[]; error?: string };
  note?: string;
};

export default function PlanSimulatePanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [prompt, setPrompt] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const run = async () => {
    const text = prompt.trim();
    if (!text) { setError('先写一句你想让 Atlas 做的事。'); return; }
    setLoading(true);
    setError('');
    try {
      setResult(await api<Result>(apiBaseUrl, '/api/maintenance/plan-simulate', {
        method: 'POST',
        json: { prompt: text },
      }));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const tools = result?.selection.tools ?? {};
  const offeredSet = new Set(result?.offered ?? []);

  return (
    <div className="grid gap-3">
      <p className="m-0 text-[11.5px] text-fg-3">
        把一句话先在这里过一遍：它会落到哪个档位、会带哪些工具、要吃掉多少 token。
        全程只做本地推导，不发模型请求，所以随便试。
      </p>

      <div className="flex gap-2">
        <textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void run(); }
          }}
          rows={2}
          placeholder="比如：修一下 kernel/loop.py 的工具裁剪，跑测试验证"
          className="min-w-0 flex-1 resize-y rounded border border-line bg-canvas px-2 py-1.5 text-[12px] text-fg outline-none focus:border-accent"
        />
        <button
          type="button"
          onClick={() => void run()}
          disabled={loading}
          className="h-fit shrink-0 rounded border border-line px-3 py-1.5 text-[11.5px] text-fg disabled:opacity-50"
        >
          {loading ? '推导中…' : '预演（⌘↵）'}
        </button>
      </div>

      {error && <p role="alert" className="m-0 text-danger">{error}</p>}

      {result && (
        <div className="grid gap-2">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[11.5px] text-fg-2">
            <span>档位 <strong className="text-fg">{result.tier}</strong></span>
            <span className="text-fg-3">（{result.bucket}）</span>
            <span>工具 <strong className="text-fg">{result.tool_count_offered}</strong>/{result.tool_count_total}</span>
            {result.schema_saved_ratio !== null && (
              <span className="text-success">省 {Math.round(result.schema_saved_ratio * 1000) / 10}% 工具描述</span>
            )}
            <span className="text-fg-3">
              约 {result.estimate.schema_tokens_after.toLocaleString()} tok（未裁剪要 {result.estimate.schema_tokens_before.toLocaleString()} tok）
            </span>
          </div>

          {result.selection.error && (
            <p className="m-0 text-danger">选择器报错：{result.selection.error}</p>
          )}

          {result.offered.length > 0 && (
            <div className="grid gap-1 rounded-lg border border-line p-2">
              <div className="text-[10.5px] text-fg-3">这次会带给模型的工具（按相关度排序）</div>
              <div className="flex flex-wrap gap-1">
                {result.offered.map((name) => {
                  const detail = tools[name];
                  return (
                    <span
                      key={name}
                      title={detail ? `家族 ${detail.family ?? '—'} · 得分 ${detail.score ?? '—'}` : undefined}
                      className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[10.5px] text-fg-2"
                    >
                      {name}
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          {Object.keys(tools).length > 0 && (
            <details className="rounded-lg border border-line p-2">
              <summary className="cursor-pointer text-[11px] text-fg-2">
                看看每个工具为什么被选或被丢（{Object.keys(tools).length} 条）
              </summary>
              <div className="mt-1.5 max-h-64 overflow-auto">
                <table className="w-full border-collapse text-[10.5px]">
                  <thead className="text-left text-fg-3">
                    <tr>
                      <th className="px-1 py-1 font-medium">工具</th>
                      <th className="px-1 py-1 font-medium">家族</th>
                      <th className="px-1 py-1 font-medium">得分</th>
                      <th className="px-1 py-1 font-medium">结果</th>
                      <th className="px-1 py-1 font-medium">原因</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(tools)
                      .sort((a, b) => (b[1].score ?? 0) - (a[1].score ?? 0))
                      .map(([name, detail]) => (
                        <tr key={name} className="border-t border-line">
                          <td className="px-1 py-1 font-mono text-fg-2">{name}</td>
                          <td className="px-1 py-1 text-fg-3">{detail.family ?? '—'}</td>
                          <td className="px-1 py-1 text-fg-3">{detail.score ?? '—'}</td>
                          <td className={`px-1 py-1 ${offeredSet.has(name) ? 'text-success' : 'text-fg-3'}`}>
                            {offeredSet.has(name) ? '带上' : '留下次'}
                          </td>
                          <td className="px-1 py-1 text-fg-3">{detail.reason ?? '—'}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}

          {result.note && <p className="m-0 text-[10.5px] text-fg-3">{result.note}</p>}
        </div>
      )}
    </div>
  );
}
