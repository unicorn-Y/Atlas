/**
 * StatusPanel（S5）—— 服务状态与采集控制。
 * GET /api/unified-memory/status（契约 §6：接线、数据、outbox、形成、索引、
 * 模型和 worker 状态；显示降级原因与最后水位；§6.1 水位 conversation/tool/
 * passive 三分开，不能用总水位判断被动采集已停止）。
 * GET /api/unified-memory/capture/status + POST pause/start：
 * 采集开关（暂停 / 恢复）：capture 和 Observer 都停止；恢复后不补采暂停期间的内容。
 * 待整理数量：formation.queue.pending。
 * 今日 Observer 用量与 MemoryOS 在线状态如实可见。
 */
import { useCallback, useEffect, useState } from 'react';
import { Activity, LoaderCircle, PauseCircle, PlayCircle, RefreshCw, ShieldCheck } from 'lucide-react';
import { api } from '../../services/api';
import { isFeatureDisabled, isNotEnabled, str } from './common';

export interface StatusPayload {
  raw: Record<string, unknown>;
}

export interface CaptureStatus {
  state: 'RUNNING' | 'PAUSED' | 'STOPPED' | string;
  revision: number;
  passiveCaptureWatermark?: number | string | null;
  error?: string;
}

export async function fetchStatus(apiBaseUrl: string): Promise<StatusPayload> {
  const payload = await api<unknown>(apiBaseUrl, '/api/unified-memory/status');
  return { raw: (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown> };
}

export async function fetchCaptureStatus(apiBaseUrl: string): Promise<CaptureStatus> {
  try {
    const payload = await api<Record<string, unknown>>(apiBaseUrl, '/api/unified-memory/capture/status');
    return {
      state: str(payload.state) || 'RUNNING',
      revision: typeof payload.revision === 'number' ? payload.revision : 1,
      passiveCaptureWatermark: payload.passive_capture_watermark as number | string | undefined,
    };
  } catch (exc) {
    return {
      state: 'UNKNOWN',
      revision: 1,
      error: exc instanceof Error ? exc.message : String(exc),
    };
  }
}

export async function pauseCapture(apiBaseUrl: string, expectedRevision?: number): Promise<unknown> {
  return api<unknown>(apiBaseUrl, '/api/unified-memory/capture/pause', {
    method: 'POST',
    json: {
      request_id: `ui-pause-${Date.now()}`,
      expected_revision: expectedRevision,
    },
  });
}

export async function resumeCapture(apiBaseUrl: string, expectedRevision?: number): Promise<unknown> {
  return api<unknown>(apiBaseUrl, '/api/unified-memory/capture/start', {
    method: 'POST',
    json: {
      request_id: `ui-resume-${Date.now()}`,
      expected_revision: expectedRevision,
      sources: [{ kind: 'window', value: 'active' }],
    },
  });
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

/** S5 状态概览：采集开关（暂停/恢复）、MemoryOS 在线状态、待整理数量、今日 Observer 用量。 */
export function S5StatusOverview({
  captureStatus,
  rawStatus,
  onToggleCapture,
  busy = false,
}: {
  captureStatus?: CaptureStatus | null;
  rawStatus?: Record<string, unknown> | null;
  onToggleCapture?: () => void;
  busy?: boolean;
}) {
  const isPaused = captureStatus?.state?.toUpperCase() === 'PAUSED';
  const isRunning = captureStatus?.state?.toUpperCase() === 'RUNNING';

  const formation = (rawStatus?.formation && typeof rawStatus.formation === 'object'
    ? rawStatus.formation
    : {}) as Record<string, unknown>;
  const formationQueue = (formation.queue && typeof formation.queue === 'object'
    ? formation.queue
    : {}) as Record<string, unknown>;
  const pendingCount = typeof formationQueue.pending === 'number'
    ? formationQueue.pending
    : 0;

  const watermarks = (rawStatus?.watermarks && typeof rawStatus.watermarks === 'object'
    ? rawStatus.watermarks
    : {}) as Record<string, unknown>;
  const obsAcked = (watermarks.OBSERVATION_ACKED && typeof watermarks.OBSERVATION_ACKED === 'object'
    ? watermarks.OBSERVATION_ACKED
    : {}) as Record<string, unknown>;
  const counts = (rawStatus?.counts && typeof rawStatus.counts === 'object'
    ? rawStatus.counts
    : {}) as Record<string, unknown>;
  const todayUsageText = obsAcked.event_count !== undefined
    ? `${obsAcked.event_count} 条事件`
    : counts.evidence_events !== undefined
      ? `${counts.evidence_events} 条事件`
      : '正常 (≤50,000 budget)';

  const isMemoryOSOnline = Boolean(rawStatus && Object.keys(rawStatus).length > 0);

  return <div className="card glass" style={{ marginBottom: 14 }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
      <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
        <ShieldCheck size={18} />
        记忆服务状态闭环（S5）
      </h2>
      <span className="tag" style={{ background: isMemoryOSOnline ? 'var(--ok-soft)' : 'var(--danger-soft)', color: isMemoryOSOnline ? 'var(--ok)' : 'var(--danger)' }}>
        MemoryOS {isMemoryOSOnline ? '在线' : '离线'}
      </span>
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 12 }}>
      {/* 1. 采集开关（暂停 / 恢复） */}
      <div style={{ borderRadius: 10, background: 'var(--sunken)', padding: '12px 14px' }}>
        <p className="cap" style={{ margin: '0 0 6px' }}>采集开关（Capture & Observer）</p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <span
            className="tag"
            style={{
              background: isPaused ? 'var(--warn-soft)' : isRunning ? 'var(--ok-soft)' : 'var(--sunken)',
              color: isPaused ? 'var(--warn)' : isRunning ? 'var(--ok)' : 'var(--fg-2)',
            }}
          >
            {isPaused ? '已暂停' : isRunning ? '运行中' : str(captureStatus?.state || '运行中')}
          </span>
          {onToggleCapture && (
            <button
              className={`btn ${isPaused ? '' : 'ghost'}`}
              style={{ fontSize: 12, padding: '2px 8px' }}
              disabled={busy}
              onClick={onToggleCapture}
            >
              {isPaused ? <PlayCircle size={13} /> : <PauseCircle size={13} />}
              {isPaused ? '恢复采集' : '暂停采集'}
            </button>
          )}
        </div>
        <small style={{ color: 'var(--fg-3)', display: 'block', lineHeight: 1.4 }}>
          {isPaused
            ? '暂停采集：capture 和 Observer 均已停止；恢复后不补采暂停期间内容。'
            : '采集正常：持续记录对话并由 Observer 提炼记忆。'}
        </small>
      </div>

      {/* 2. MemoryOS 在线状态 */}
      <div style={{ borderRadius: 10, background: 'var(--sunken)', padding: '12px 14px' }}>
        <p className="cap" style={{ margin: '0 0 6px' }}>MemoryOS 状态</p>
        <div style={{ fontSize: 16, fontWeight: 600, color: isMemoryOSOnline ? 'var(--ok)' : 'var(--danger)', marginBottom: 4 }}>
          {isMemoryOSOnline ? '在线服务中' : '服务未就绪'}
        </div>
        <small style={{ color: 'var(--fg-3)', display: 'block' }}>
          契约版本: {str(rawStatus?.contract_version || 'UM-WIN-1.0')}
        </small>
      </div>

      {/* 3. 待整理数量 */}
      <div style={{ borderRadius: 10, background: 'var(--sunken)', padding: '12px 14px' }}>
        <p className="cap" style={{ margin: '0 0 6px' }}>待整理数量（Formation 队列）</p>
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--fg)', marginBottom: 4 }}>
          {pendingCount}
        </div>
        <small style={{ color: 'var(--fg-3)', display: 'block' }}>
          {pendingCount === 0 ? '所有观察事件均已整理完毕' : '等待 formation worker 消费整理'}
        </small>
      </div>

      {/* 4. 今日 Observer 用量 */}
      <div style={{ borderRadius: 10, background: 'var(--sunken)', padding: '12px 14px' }}>
        <p className="cap" style={{ margin: '0 0 6px' }}>今日 Observer 用量</p>
        <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--fg)', marginBottom: 4 }}>
          {todayUsageText}
        </div>
        <small style={{ color: 'var(--fg-3)', display: 'block' }}>
          日上限 50,000 Token；超额保留不阻塞
        </small>
      </div>
    </div>
  </div>;
}

/** 面板主体（静态可渲染）。 */
export function StatusPanelBody({
  payload,
  captureStatus,
  loading,
  error,
  onToggleCapture,
  busy = false,
}: {
  payload: StatusPayload | null;
  captureStatus?: CaptureStatus | null;
  loading: boolean;
  error: string;
  onToggleCapture?: () => void;
  busy?: boolean;
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
    <S5StatusOverview
      captureStatus={captureStatus}
      rawStatus={raw}
      onToggleCapture={onToggleCapture}
      busy={busy}
    />
    {curated.length > 0 && <div className="card glass"><h2>服务概况</h2><KvList entries={curated} /></div>}
    {passive && <div className="card glass"><h2>被动采集水位</h2><KvList entries={[['passive_capture_watermark', passive]]} /></div>}
    {watermarks && <WatermarkCards watermarks={watermarks} />}
    {Object.entries(raw)
      .filter(([key, value]) => value && typeof value === 'object' && key !== 'watermarks')
      .map(([key, value]) => <GenericSection key={key} title={labelOf(key)} value={value} />)}
  </section>;
}

export default function StatusPanel({ apiBaseUrl, connected, onToast }: { apiBaseUrl: string; connected: boolean; onToast?: (msg: string) => void }) {
  const [payload, setPayload] = useState<StatusPayload | null>(null);
  const [captureStatus, setCaptureStatus] = useState<CaptureStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!connected) return;
    setLoading(true);
    try {
      const [statusRes, capRes] = await Promise.all([
        fetchStatus(apiBaseUrl),
        fetchCaptureStatus(apiBaseUrl),
      ]);
      setPayload(statusRes);
      setCaptureStatus(capRes);
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setLoading(false); }
  }, [apiBaseUrl, connected]);

  useEffect(() => { void load(); }, [load]);

  const handleToggleCapture = async () => {
    if (!connected || busy) return;
    setBusy(true);
    const isPaused = captureStatus?.state?.toUpperCase() === 'PAUSED';
    try {
      if (isPaused) {
        await resumeCapture(apiBaseUrl, captureStatus?.revision);
        onToast?.('已恢复采集');
      } else {
        await pauseCapture(apiBaseUrl, captureStatus?.revision);
        onToast?.('已暂停采集：capture 和 Observer 均停止');
      }
      const newCap = await fetchCaptureStatus(apiBaseUrl);
      setCaptureStatus(newCap);
    } catch (exc) {
      const msg = exc instanceof Error ? exc.message : String(exc);
      onToast?.(`操作采集失败：${msg}`);
    } finally {
      setBusy(false);
    }
  };

  if (!connected) return <section aria-label="统一记忆服务状态"><div className="note">等待 Atlas 后端连接后读取服务状态。</div></section>;

  return <section>
    <div className="filterbar" style={{ marginBottom: 10 }}>
      <button className="btn ghost" disabled={loading || !connected} onClick={() => void load()}>
        <RefreshCw size={14} className={loading ? 'spin' : undefined} />刷新
      </button>
      <span className="empty-note">水位按对话/工具/被动三分开显示；降级原因如实列出。</span>
    </div>
    <StatusPanelBody
      payload={payload}
      captureStatus={captureStatus}
      loading={loading}
      error={error}
      onToggleCapture={handleToggleCapture}
      busy={busy}
    />
    {!loading && !error && <div style={{ textAlign: 'center', marginTop: 8 }}>
      <span className="live-tag"><Activity size={13} aria-hidden />以上来自 GET /api/unified-memory/status 的实时回执</span>
    </div>}
  </section>;
}
