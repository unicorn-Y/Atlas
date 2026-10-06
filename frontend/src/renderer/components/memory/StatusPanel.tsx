/**
 * StatusPanel（T12.1）—— 服务状态。
 * GET /api/unified-memory/status（契约 §6：接线、数据、outbox、形成、索引、
 * 模型和 worker 状态；显示降级原因与最后水位；§6.1 水位 conversation/tool/
 * passive 三分开，不能用总水位判断被动采集已停止）。
 * 服务端字段可能随波次演进：已知字段用中文标签呈现，未知字段原样列出
 * （宁可见到原始名，不隐藏），长内容换行不破版。
 */
import { useCallback, useEffect, useState } from 'react';
import { Activity, LoaderCircle, RefreshCw } from 'lucide-react';
import { api } from '../../services/api';
import { isFeatureDisabled, isNotEnabled, str } from './common';

export interface StatusPayload {
  raw: Record<string, unknown>;
}

export async function fetchStatus(apiBaseUrl: string): Promise<StatusPayload> {
  const payload = await api<unknown>(apiBaseUrl, '/api/unified-memory/status');
  return { raw: (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown> };
}

/** 浅层取值：对象只保留非空标量（嵌套对象交给通用块渲染；空串不留占位）。 */
function scalarsOf(value: unknown): Array<[string, string]> {
  if (!value || typeof value !== 'object') return [];
  return Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v === null || ['string', 'number', 'boolean'].includes(typeof v))
    .map(([k, v]) => [k, str(v)] as [string, string])
    .filter(([, v]) => v !== '');
}

const KNOWN_LABELS: Record<string, string> = {
  authority_id: '权威标识', contract_version: '契约版本', state: '状态',
  degraded: '已降级', degraded_reasons: '降级原因', degradations: '降级原因',
  last_error: '最近错误', revision: '版本', total: '总数', pending: '待处理',
  captured: '已捕获', gaps: '缺口', buckets: '分组', healthy: '健康',
};

function labelOf(key: string): string {
  return KNOWN_LABELS[key] ?? key;
}

function KvList({ entries }: { entries: Array<[string, string]> }) {
  if (entries.length === 0) return null;
  return <dl className="kv" style={{ margin: 0 }}>
    {entries.map(([key, value]) => <div key={key}>
      <dt>{labelOf(key)}</dt>
      <dd title={value} style={{ whiteSpace: 'normal', overflowWrap: 'anywhere', maxWidth: '100%', wordBreak: 'break-all' }}>{value}</dd>
    </div>)}
  </dl>;
}

/** 顶层未识别的子对象 → 通用小节（浅层标量 + 嵌套逐层展开一层）。 */
function GenericSection({ title, value }: { title: string; value: unknown }) {
  if (value === null || value === undefined) return null;
  if (['string', 'number', 'boolean'].includes(typeof value)) {
    const text = str(value);
    if (!text) return null;
    return <div className="card glass">
      <h2>{title}</h2>
      <KvList entries={[[title, text]]} />
    </div>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    return <div className="card glass">
      <h2>{title}<span style={{ color: 'var(--fg-3)', fontWeight: 400 }}>（{value.length}）</span></h2>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: 'var(--fg-2)' }}>
        {value.slice(0, 20).map((entry, index) => <li key={index} style={{ overflowWrap: 'anywhere' }}>{typeof entry === 'string' ? entry : JSON.stringify(entry)}</li>)}
      </ul>
    </div>;
  }
  const scalars = scalarsOf(value);
  const nested = Object.entries(value as Record<string, unknown>).filter(([, v]) => v && typeof v === 'object' && !Array.isArray(v));
  const arrays = Object.entries(value as Record<string, unknown>).filter(([, v]) => Array.isArray(v) && (v as unknown[]).length > 0);
  if (scalars.length === 0 && nested.length === 0 && arrays.length === 0) return null;
  return <div className="card glass">
    <h2>{title}</h2>
    <KvList entries={scalars} />
    {nested.map(([key, nestedValue]) => <div key={key} style={{ marginTop: 12 }}>
      <p className="cap" style={{ margin: '0 0 6px' }}>{labelOf(key)}</p>
      <KvList entries={scalarsOf(nestedValue)} />
    </div>)}
    {arrays.map(([key, arrayValue]) => <div key={key} style={{ marginTop: 12 }}>
      <p className="cap" style={{ margin: '0 0 6px' }}>{labelOf(key)}（{(arrayValue as unknown[]).length}）</p>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: 'var(--fg-2)' }}>
        {(arrayValue as unknown[]).slice(0, 10).map((entry, index) => <li key={index} style={{ overflowWrap: 'anywhere' }}>{typeof entry === 'string' ? entry : JSON.stringify(entry)}</li>)}
      </ul>
    </div>)}
  </div>;
}

/** 水位三分：conversation/tool/passive（契约 §6.1 硬性要求分开显示）。 */
export function WatermarkCards({ watermarks }: { watermarks: Record<string, unknown> }) {
  const NAMES: Record<string, string> = { conversation: '对话水位', tool: '工具水位', passive: '被动采集水位' };
  return <div className="card glass">
    <h2>水位（各自独立，不合并）</h2>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
      {Object.entries(watermarks).map(([key, value]) => {
        const scalars = value && typeof value === 'object' && !Array.isArray(value) ? scalarsOf(value) : [];
        return <div key={key} style={{ borderRadius: 10, background: 'var(--sunken)', padding: '10px 12px' }}>
          <p className="cap" style={{ margin: 0 }}>{NAMES[key] ?? key}</p>
          {scalars.length > 0
            ? <KvList entries={scalars} />
            : <p style={{ margin: 0, fontSize: 13 }}>{str(value) || '（无数据）'}</p>}
        </div>;
      })}
    </div>
  </div>;
}

/** 面板主体（静态可渲染）。 */
export function StatusPanelBody({ payload, loading, error }: {
  payload: StatusPayload | null;
  loading: boolean;
  error: string;
}) {
  if (loading) return <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取服务状态…</b></div></div>;

  const degraded = isFeatureDisabled(error) || isNotEnabled(error);
  if (degraded) return <div className="note">统一记忆服务状态不可用：服务端未接线或统一记忆未开启（{error}）。这不是页面故障，等后端启用后会自动可用。</div>;
  if (error) return <div className="error-note" role="alert"><span>读取服务状态失败：{error}</span></div>;
  if (!payload) return null;

  const raw = payload.raw;
  const watermarks = (raw.watermarks && typeof raw.watermarks === 'object' ? raw.watermarks : null) as Record<string, unknown> | null;
  const passive = str(raw.passive_capture_watermark);
  const curated = scalarsOf(raw).filter(([key]) => key !== 'watermarks');

  return <section aria-label="统一记忆服务状态">
    {curated.length > 0 && <div className="card glass"><h2>服务概况</h2><KvList entries={curated} /></div>}
    {passive && <div className="card glass"><h2>被动采集水位</h2><KvList entries={[['passive_capture_watermark', passive]]} /></div>}
    {watermarks && <WatermarkCards watermarks={watermarks} />}
    {Object.entries(raw)
      .filter(([key, value]) => value && typeof value === 'object' && key !== 'watermarks')
      .map(([key, value]) => <GenericSection key={key} title={labelOf(key)} value={value} />)}
  </section>;
}

export default function StatusPanel({ apiBaseUrl, connected }: { apiBaseUrl: string; connected: boolean }) {
  const [payload, setPayload] = useState<StatusPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!connected) return;
    setLoading(true);
    try {
      setPayload(await fetchStatus(apiBaseUrl));
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setLoading(false); }
  }, [apiBaseUrl, connected]);

  useEffect(() => { void load(); }, [load]);

  if (!connected) return <section aria-label="统一记忆服务状态"><div className="note">等待 Atlas 后端连接后读取服务状态。</div></section>;

  return <section>
    <div className="filterbar" style={{ marginBottom: 10 }}>
      <button className="btn ghost" disabled={loading || !connected} onClick={() => void load()}>
        <RefreshCw size={14} className={loading ? 'spin' : undefined} />刷新
      </button>
      <span className="empty-note">水位按对话/工具/被动三分开显示；降级原因如实列出。</span>
    </div>
    <StatusPanelBody payload={payload} loading={loading} error={error} />
    {!loading && !error && <div style={{ textAlign: 'center', marginTop: 8 }}>
      <span className="live-tag"><Activity size={13} aria-hidden />以上来自 GET /api/unified-memory/status 的实时回执</span>
    </div>}
  </section>;
}
