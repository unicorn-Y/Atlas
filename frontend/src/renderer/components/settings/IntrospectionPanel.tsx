import { useCallback, useEffect, useMemo, useState } from 'react';
import { Boxes, RefreshCw, Search, Terminal } from 'lucide-react';
import { Button } from '../../ui/Button';
import styles from '../../App.module.css';

/**
 * Atlas inspecting itself.
 *
 * The backend can answer twelve questions about its own live state — which
 * services are actually bound, which routes exist and which are shadowed, which
 * tools loaded and which are hidden, what the event contract looks like, where
 * context pressure sits, whether the Office/telemetry/TTS paths are usable. All
 * of that was reachable only by `curl`ing a route nobody could discover; the
 * frontend never called `/api/introspect` at all.
 *
 * This panel is the discoverable half: it lists the providers, shows each
 * method's arguments *from the manifest* (no hand-maintained copy that drifts),
 * and prints the raw answer with its duration so a slow provider is visible as a
 * slow provider rather than as "the app feels sluggish".
 */

interface IntrospectInputSchema {
  type?: string;
  properties?: Record<string, { type?: string; description?: string; enum?: unknown[] }>;
  required?: string[];
  additionalProperties?: boolean;
}

interface IntrospectMethod {
  name: string;
  summary: string;
  input?: IntrospectInputSchema;
}

interface IntrospectProvider {
  id: string;
  title: string;
  summary: string;
  methods: IntrospectMethod[];
}

interface IntrospectManifest {
  count: number;
  providers: IntrospectProvider[];
  method_count: number;
}

interface QueryEnvelope {
  provider: string;
  method: string;
  duration_ms?: number;
  result?: unknown;
  error?: string;
}

const providerIcons: Record<string, typeof Boxes> = {};

function iconFor(id: string) {
  return providerIcons[id] ?? Boxes;
}

function formatDuration(ms: number | undefined): string {
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return '';
  return ms < 10 ? `${ms.toFixed(1)} ms` : `${Math.round(ms)} ms`;
}

/** One line describing what the answer is, so the JSON is not the only signal. */
function summarize(answer: unknown): string {
  if (answer === null || answer === undefined) return '（空）';
  if (Array.isArray(answer)) return `数组，${answer.length} 项`;
  if (typeof answer !== 'object') return String(answer);
  const record = answer as Record<string, unknown>;
  const parts: string[] = [];
  for (const [key, value] of Object.entries(record)) {
    if (Array.isArray(value)) parts.push(`${key} ${value.length} 项`);
    else if (value && typeof value === 'object') parts.push(`${key} {…}`);
    else if (typeof value === 'boolean' || typeof value === 'number') parts.push(`${key}=${String(value)}`);
    if (parts.length >= 4) break;
  }
  if (typeof record.sentence === 'string') return record.sentence;
  if (typeof record.summary === 'string') return record.summary;
  return parts.length ? parts.join(' · ') : `${Object.keys(record).length} 个字段`;
}

export default function IntrospectionPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [manifest, setManifest] = useState<IntrospectManifest | null>(null);
  const [manifestError, setManifestError] = useState('');
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState('health');
  const [methodName, setMethodName] = useState('');
  const [argsText, setArgsText] = useState('{}');
  const [argsError, setArgsError] = useState('');
  const [busy, setBusy] = useState(false);
  const [envelope, setEnvelope] = useState<QueryEnvelope | null>(null);
  const [queryError, setQueryError] = useState('');
  const [filter, setFilter] = useState('');

  const base = apiBaseUrl.replace(/\/+$/, '');

  const loadManifest = useCallback(async () => {
    setLoading(true);
    setManifestError('');
    try {
      const response = await fetch(`${base}/api/introspect/providers`);
      const text = await response.text();
      if (!response.ok) throw new Error(text || `HTTP ${response.status}`);
      setManifest(JSON.parse(text) as IntrospectManifest);
    } catch (error) {
      setManifestError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => { void loadManifest(); }, [loadManifest]);

  const provider = useMemo(
    () => manifest?.providers.find((item) => item.id === selected) ?? null,
    [manifest, selected],
  );

  // Default to the first method of a provider rather than leaving the query
  // button pointing at whatever the previous provider had.
  useEffect(() => {
    if (!provider) return;
    if (provider.methods.some((item) => item.name === methodName)) return;
    setMethodName(provider.methods[0]?.name ?? '');
    setArgsText('{}');
    setArgsError('');
  }, [methodName, provider]);

  const method = provider?.methods.find((item) => item.name === methodName) ?? null;

  const visibleProviders = useMemo(() => {
    if (!manifest) return [];
    const needle = filter.trim().toLowerCase();
    if (!needle) return manifest.providers;
    return manifest.providers.filter((item) => [item.id, item.title, item.summary, ...item.methods.map((method) => method.name)]
      .some((field) => field.toLowerCase().includes(needle)));
  }, [filter, manifest]);

  const runQuery = async () => {
    if (!provider || !method) return;
    let inputs: unknown;
    try {
      inputs = argsText.trim() ? JSON.parse(argsText) as unknown : {};
    } catch (error) {
      setArgsError(`参数不是合法 JSON：${error instanceof Error ? error.message : String(error)}`);
      return;
    }
    if (inputs === null || typeof inputs !== 'object' || Array.isArray(inputs)) {
      setArgsError('参数必须是一个 JSON 对象，例如 {}。');
      return;
    }
    setArgsError('');
    setQueryError('');
    setBusy(true);
    try {
      const response = await fetch(`${base}/api/introspect/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: provider.id, method: method.name, input: inputs }),
      });
      const text = await response.text();
      let parsed: unknown = null;
      try { parsed = text ? JSON.parse(text) as unknown : null; } catch { parsed = text; }
      if (!response.ok) {
        const detail = parsed && typeof parsed === 'object' && 'detail' in parsed
          ? String((parsed as { detail: unknown }).detail)
          : text;
        throw new Error(detail || `HTTP ${response.status}`);
      }
      setEnvelope(parsed as QueryEnvelope);
    } catch (error) {
      setEnvelope(null);
      setQueryError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return <section className={styles.settingsCard} aria-label="运行时自省">
    <div className={styles.settingsCardHeading}>
      <div>
        <h2>运行时自省</h2>
        <p>直接问正在运行的 Atlas：接线了哪些服务、哪些接口被遮挡、工具和事件是什么样、上下文还剩多少。</p>
      </div>
      <Terminal size={18} className="text-fg-3" />
    </div>

    {manifestError && <p className={styles.settingsError} role="alert">读取自省清单失败：{manifestError}</p>}
    {loading && !manifest && <p className="m-0 text-[12.5px] text-fg-3">正在读取自省清单…</p>}

    {manifest && <>
      <p className="m-0 mb-2.5 text-[12px] text-fg-3">
        {manifest.count} 个提供方、{manifest.method_count} 个只读方法。清单本身来自后端，界面不维护第二份。
      </p>

      <div className="mb-2.5 flex items-center gap-2 rounded-lg bg-sunken px-2.5 py-1.5 shadow-[inset_0_0_0_1px_var(--line)]">
        <Search size={14} className="shrink-0 text-fg-3" />
        <input value={filter} onChange={(event) => setFilter(event.target.value)}
          placeholder="筛选提供方或方法…" aria-label="筛选自省提供方"
          className="min-w-0 flex-1 border-0 bg-transparent text-[12.5px] text-fg outline-none" />
        <Button type="button" variant="ghost" size="icon-sm" disabled={loading}
          aria-label="重新读取清单" title="重新读取清单" onClick={() => void loadManifest()}>
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </Button>
      </div>

      <div className="grid gap-2.5 md:grid-cols-[minmax(0,220px)_minmax(0,1fr)]">
        <div className="grid content-start gap-1" role="tablist" aria-label="自省提供方">
          {visibleProviders.map((item) => {
            const Icon = iconFor(item.id);
            const active = item.id === provider?.id;
            return <button key={item.id} type="button" role="tab" aria-selected={active}
              onClick={() => setSelected(item.id)}
              className={`flex items-start gap-2 rounded-lg px-2.5 py-2 text-left text-[12.5px] ${active
                ? 'bg-card text-fg shadow-[inset_0_0_0_1px_var(--line)]'
                : 'text-fg-3 hover:bg-sunken'}`}>
              <Icon size={14} className="mt-0.5 shrink-0" />
              <span className="grid min-w-0 gap-0.5">
                <span className="truncate font-medium">{item.title}</span>
                <span className="truncate text-[11px] text-fg-3">{item.id} · {item.methods.length} 个方法</span>
              </span>
            </button>;
          })}
          {!visibleProviders.length && <p className="m-0 px-2 text-[12px] text-fg-3">没有匹配的提供方。</p>}
        </div>

        {provider && <div className="grid min-w-0 content-start gap-2.5">
          <p className="m-0 text-[12px] leading-[1.6] text-fg-2">{provider.summary}</p>

          <div className="flex flex-wrap gap-1.5">
            {provider.methods.map((item) => <button key={item.name} type="button"
              onClick={() => { setMethodName(item.name); setArgsText('{}'); setArgsError(''); }}
              title={item.summary}
              className={`rounded-md px-2 py-1 text-[11.5px] ${item.name === methodName
                ? 'bg-fg text-bg'
                : 'bg-sunken text-fg-3 hover:text-fg'}`}>{item.name}</button>)}
          </div>

          {method && <>
            <p className="m-0 text-[12px] leading-[1.6] text-fg-3">{method.summary}</p>
            <label className="grid gap-1 text-[12px] text-fg-3">
              参数（JSON 对象）
              <textarea value={argsText} onChange={(event) => setArgsText(event.target.value)}
                rows={4} spellCheck={false}
                className={`${styles.settingsCard} !p-2 font-mono text-[12px]`}
                aria-label="自省查询参数" />
            </label>
            {method.input?.properties && Object.keys(method.input.properties).length > 0
              ? <div className="grid gap-1 rounded-lg bg-sunken p-2.5 text-[11.5px] text-fg-3">
                {Object.entries(method.input.properties).map(([name, schema]) => <div key={name} className="flex flex-wrap gap-x-1.5">
                  <code className="text-fg">{name}</code>
                  <span>{schema.type || 'any'}</span>
                  {method.input?.required?.includes(name) && <span className="text-warn">必填</span>}
                  {schema.description && <span className="text-fg-3">— {schema.description}</span>}
                </div>)}
              </div>
              : <p className="m-0 text-[11.5px] text-fg-3">这个方法不需要参数，传 {'{}'} 即可。</p>}
            {argsError && <p className={styles.settingsError} role="alert">{argsError}</p>}
            <div className="flex items-center gap-2">
              <Button type="button" variant="primary" size="sm" disabled={busy} onClick={() => void runQuery()}>
                {busy ? '查询中…' : '运行查询'}
              </Button>
              {envelope && <span className="text-[11.5px] text-fg-3">
                {envelope.provider}.{envelope.method} · {formatDuration(envelope.duration_ms)}
              </span>}
            </div>
          </>}

          {queryError && <p className={styles.settingsError} role="alert">{queryError}</p>}

          {envelope?.result !== undefined && <div className="grid gap-1.5">
            <p className="m-0 text-[12px] text-fg-2">{summarize(envelope.result)}</p>
            <pre className="m-0 max-h-[420px] overflow-auto rounded-lg bg-sunken p-3 font-mono text-[11.5px] leading-[1.5] text-fg-2">{JSON.stringify(envelope.result, null, 2)}</pre>
            <p className="m-0 text-[11px] text-fg-3">
              只读查询：自省不会写入任何状态，配置里的密钥值在离开进程前已被遮盖。
            </p>
          </div>}
        </div>}
      </div>
    </>}
  </section>;
}
