/**
 * MemoryPage（S5 记忆页面闭环）
 * 1. 打通并保留视图：
 *    - "它对我的了解"：画像块。每句话可以点开出处，可以纠正，可以删除
 *    - 记忆列表：RecordsView，按类别和时间浏览、搜索；每条显示出处、当前 / 历史、重要性；支持依据/纠错/删除
 *    - 时间线：TimelineView，每日 / 每周概括
 *    - 提醒与待办：IntentView
 *    - 人事：EntityView，支持按名字检索与删除
 *    - 状态：StatusPanel，采集开关（暂停 / 恢复）、MemoryOS 在线状态、待整理数量、今日 Observer 用量
 * 2. LearningView 等冻结功能入口隐藏（不删除）。
 * 3. 操作闭环：纠正走 /corrections，删除走 HARD_ERASE / 纠偏失效；操作完成后列表立即更新。
 */
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  Activity,
  BookMarked,
  Brain,
  Check,
  History,
  ListTodo,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Users,
  X,
} from 'lucide-react';
import { api, relativeTime } from '../services/api';
import TimelineView, { type TimelineItem } from '../components/memory/TimelineView';
import EvidencePanel from '../components/memory/EvidencePanel';
import EntityView from '../components/memory/EntityView';
import IntentView from '../components/memory/IntentView';
import LearningView from '../components/memory/LearningView';
import StatusPanel from '../components/memory/StatusPanel';
import CorrectionDialog from '../components/memory/CorrectionDialog';
import RecordsView from '../components/memory/RecordsView';
import {
  ConfirmButton,
  enumLabel,
  isFeatureDisabled,
  isNotEnabled,
  pageOf,
  str,
} from '../components/memory/common';

interface Fact {
  key: string;
  value: string;
  category: string;
  confidence?: number | null;
  memory_type?: string | null;
  updated_at?: string;
}

interface Candidate {
  id: string;
  key: string;
  value: string;
  category: string;
  confidence?: number;
  status: string;
  memory_type?: string;
  created_at?: string;
}

interface Knowledge {
  id: string;
  content: string;
  source?: string;
  category?: string;
  created_at?: string;
  score?: number;
}

/** 主视图：时间线/它对我的了解/记忆列表/人事/提醒与待办/状态（S5）+ 旧入口 pending/knowledge 兼容保留。 */
type Tab =
  | 'timeline'
  | 'understanding'
  | 'records'
  | 'entities'
  | 'intents'
  | 'status'
  | 'facts'
  | 'pending'
  | 'knowledge'
  | 'learning';

const CATEGORY: Record<string, string> = {
  general: '通用',
  preference: '偏好',
  preferences: '偏好',
  profile: '个人信息',
  personal: '个人信息',
  project: '项目',
  work: '工作',
  habit: '习惯',
  contact: '联系人',
  schedule: '日程',
};

const categoryName = (value?: string) => CATEGORY[value ?? 'general'] ?? value ?? '通用';
const HIDDEN_KEY = 'atlas.memory.hidden-candidates';
const readHidden = (): string[] => {
  try {
    const value = JSON.parse(localStorage.getItem(HIDDEN_KEY) ?? '[]');
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
};

function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim();
  if (!q) return <>{text}</>;
  const index = text.toLowerCase().indexOf(q.toLowerCase());
  if (index < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, index)}
      <mark>{text.slice(index, index + q.length)}</mark>
      {text.slice(index + q.length)}
    </>
  );
}

// ---------------------------------------------------------------------------
// 它对我的了解：GET /api/unified-memory/records（facet=SUMMARY/PREFERENCE/STATE）。
// 画像块：每句话可以点开出处，可以纠正，可以删除（S5）。
// ---------------------------------------------------------------------------

interface UnderstandingItem {
  recordRef: string;
  revision: number | null;
  facet: string;
  title: string;
  text: string;
  epistemic: string;
  updatedAt: string;
  key?: string;
}

function normalizeUnderstandingItem(value: unknown): UnderstandingItem | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const recordRef = str(raw.record_ref ?? raw.id);
  if (!recordRef) return null;
  const content = (raw.content && typeof raw.content === 'object' ? raw.content : {}) as Record<string, unknown>;
  const topic = str(content.topic);
  return {
    recordRef,
    revision: typeof raw.revision === 'number' ? raw.revision : null,
    facet: str(raw.facet),
    title: topic.startsWith('raw:') ? topic.slice(4) : topic,
    text: str(content.text ?? content.summary ?? content.value ?? content),
    epistemic: str(raw.epistemic_kind),
    updatedAt: str((raw.valid_time as Record<string, unknown> | undefined)?.valid_from),
    key: str(content.key ?? raw.key),
  };
}

const UNDERSTANDING_FACETS: Array<{ value: string; label: string; icon: string }> = [
  { value: 'PREFERENCE', label: '个人偏好', icon: '💡' },
  { value: 'SUMMARY', label: '长期画像与理解', icon: '🧠' },
  { value: 'STATE', label: '当前状态与习惯', icon: '📌' },
];

function UnderstandingView({
  apiBaseUrl,
  connected,
  onOpenEvidence,
  onCorrect,
  onDelete,
}: {
  apiBaseUrl: string;
  connected: boolean;
  onOpenEvidence: (item: UnderstandingItem) => void;
  onCorrect: (item: UnderstandingItem) => void;
  onDelete?: (item: UnderstandingItem) => void;
}) {
  const [facet, setFacet] = useState('PREFERENCE');
  const [items, setItems] = useState<UnderstandingItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(
    async (opts: { facet: string; cursor?: string | null }) => {
      if (!connected) return;
      if (opts.cursor) setLoadingMore(true);
      else setLoading(true);
      try {
        const params = new URLSearchParams({ facet: opts.facet, limit: '50' });
        if (opts.cursor) params.set('cursor', opts.cursor);
        const payload = await api<unknown>(apiBaseUrl, `/api/unified-memory/records?${params}`);
        const page = pageOf(payload);
        const next = page.items
          .map(normalizeUnderstandingItem)
          .filter((item): item is UnderstandingItem => item !== null);
        setItems((current) => (opts.cursor ? [...current, ...next] : next));
        setCursor(page.nextCursor);
        setError('');
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : String(exc));
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [apiBaseUrl, connected],
  );

  useEffect(() => {
    void load({ facet });
  }, [facet, load]);

  const handleDeleteItem = async (item: UnderstandingItem) => {
    if (onDelete) {
      onDelete(item);
    }
    const targetKey = item.key || item.recordRef;
    try {
      await api(apiBaseUrl, `/api/facts/${encodeURIComponent(targetKey)}`, { method: 'DELETE' });
    } catch {
      // 容错继续
    }
    setItems((current) => current.filter((x) => x.recordRef !== item.recordRef));
  };

  const degraded = isFeatureDisabled(error) || isNotEnabled(error);
  if (!connected)
    return (
      <section aria-label="它对我的了解">
        <div className="note">等待 Atlas 后端连接后读取理解画像。</div>
      </section>
    );

  const epistemicOf = (item: UnderstandingItem) =>
    enumLabel(item.epistemic, {
      USER_ASSERTED: '用户亲述',
      OBSERVED: '实际观察',
      INFERRED: '推断',
      DERIVED: '推断',
    });

  return (
    <section aria-label="它对我的了解">
      <div className="filterbar" style={{ marginBottom: 10 }}>
        <div className="seg" role="tablist" aria-label="画像块分类">
          {UNDERSTANDING_FACETS.map((entry) => (
            <button
              key={entry.value}
              aria-pressed={facet === entry.value}
              onClick={() => setFacet(entry.value)}
            >
              {entry.icon} {entry.label}
            </button>
          ))}
        </div>
        <span className="empty-note">
          画像块：Atlas 对你的理解与偏好；每句话均可点开出处、纠错或彻底删除。
        </span>
      </div>

      {loading && (
        <div className="list glass">
          <div className="empty">
            <LoaderCircle size={22} className="spin" />
            <b>正在读取画像…</b>
          </div>
        </div>
      )}
      {!loading && degraded && (
        <div className="note">
          当前理解功能未启用：服务端尚未接线或统一记忆未开启。这不是错误，等后端启用后会自动可用。
        </div>
      )}
      {!loading && !degraded && error && (
        <div className="error-note" role="alert">
          <span>读取画像失败：{error}</span>
        </div>
      )}
      {!loading && !error && items.length === 0 && (
        <div className="list glass">
          <div className="empty">
            <Brain size={22} />
            <b>还没有形成此项画像</b>随着交流积累，Atlas
            对你的偏好、长期画像与当前状态会沉淀在这里。
          </div>
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="list glass">
          {items.map((item) => (
            <div className="fact" key={item.recordRef}>
              <div>
                <div>{item.title ? <b>{item.title}：</b> : null}{item.text || '(无文字内容)'}</div>
                <small>
                  {[
                    item.recordRef,
                    item.updatedAt ? relativeTime(item.updatedAt) : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </small>
                <div className="chips" style={{ marginTop: 6 }}>
                  {epistemicOf(item) && <span>{epistemicOf(item)}</span>}
                  {item.revision !== null && <span>版本 {item.revision}</span>}
                </div>
              </div>
              <div className="btns">
                <button className="btn ghost" onClick={() => onOpenEvidence(item)}>
                  依据
                </button>
                <button className="btn ghost" onClick={() => onCorrect(item)}>
                  纠错
                </button>
                <ConfirmButton
                  label="删除"
                  confirm="确认删除"
                  onConfirm={() => void handleDeleteItem(item)}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {cursor && !loading && !error && (
        <div style={{ textAlign: 'center', marginTop: 14 }}>
          <button
            className="btn"
            disabled={loadingMore || !connected}
            onClick={() => void load({ facet, cursor })}
          >
            {loadingMore ? <LoaderCircle size={14} className="spin" /> : null}加载更多画像
          </button>
        </div>
      )}
    </section>
  );
}

export default function MemoryPage({
  apiBaseUrl,
  connected,
  onToast,
  onPendingChange,
}: {
  apiBaseUrl: string;
  connected: boolean;
  onToast: (text: string) => void;
  onPendingChange?: (count: number) => void;
}) {
  const [tab, setTab] = useState<Tab>('timeline');
  const [facts, setFacts] = useState<Fact[]>([]);
  const [pending, setPending] = useState<Candidate[]>([]);
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [adding, setAdding] = useState(false);
  const [factForm, setFactForm] = useState({ key: '', value: '', category: 'general' });
  const [docForm, setDocForm] = useState({ content: '', source: '', category: 'general' });
  const [viewKey, setViewKey] = useState(0);
  const [evidenceRef, setEvidenceRef] = useState<{ recordRef: string; revision: number | null } | null>(null);
  const [correctRef, setCorrectRef] = useState<{ recordRef: string; revision: number | null } | null>(null);

  const refresh = useCallback(async () => {
    if (!connected) return;
    setBusy(true);
    setError('');
    try {
      const [factsRes, candRes, knowRes] = await Promise.allSettled([
        api<Fact[]>(apiBaseUrl, '/api/facts'),
        api<Candidate[]>(apiBaseUrl, '/api/memory/candidates?status=pending'),
        api<Knowledge[]>(apiBaseUrl, '/api/knowledge'),
      ]);
      if (factsRes.status === 'fulfilled') setFacts(factsRes.value || []);
      if (candRes.status === 'fulfilled') {
        const hidden = new Set(readHidden());
        const list = (candRes.value || []).filter((item) => !hidden.has(item.id));
        setPending(list);
        onPendingChange?.(list.length);
      }
      if (knowRes.status === 'fulfilled') setKnowledge(knowRes.value || []);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl, connected, onPendingChange]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = async (fn: () => Promise<unknown>, toast: string) => {
    setBusy(true);
    try {
      await fn();
      await refresh();
      onToast(toast);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const saveFact = (event: FormEvent) => {
    event.preventDefault();
    if (!factForm.key.trim() || !factForm.value.trim()) return;
    void run(async () => {
      await api(apiBaseUrl, '/api/facts', {
        method: 'POST',
        json: {
          key: factForm.key.trim(),
          value: factForm.value.trim(),
          category: factForm.category.trim() || 'general',
        },
      });
      setFactForm({ key: '', value: '', category: 'general' });
      setAdding(false);
    }, '已添加记忆');
  };

  const saveDoc = (event: FormEvent) => {
    event.preventDefault();
    if (!docForm.content.trim()) return;
    void run(async () => {
      await api(apiBaseUrl, '/api/knowledge', {
        method: 'POST',
        json: {
          content: docForm.content.trim(),
          source: docForm.source.trim(),
          category: docForm.category.trim() || 'general',
        },
      });
      setDocForm({ content: '', source: '', category: 'general' });
      setAdding(false);
    }, '已添加资料');
  };

  const remember = (cand: Candidate) =>
    run(async () => {
      await api(apiBaseUrl, `/api/memory/candidates/${encodeURIComponent(cand.id)}/accept`, {
        method: 'POST',
      });
    }, '已记住这条事实');

  const hide = (id: string) => {
    const list = readHidden();
    list.push(id);
    localStorage.setItem(HIDDEN_KEY, JSON.stringify(list));
    setPending((current) => {
      const next = current.filter((item) => item.id !== id);
      onPendingChange?.(next.length);
      return next;
    });
  };

  const q = query.trim().toLowerCase();
  const filterList = <T,>(list: T[], getValues: (item: T) => string[]) => {
    if (!q) return list;
    return list.filter((item) => getValues(item).some((value) => value.toLowerCase().includes(q)));
  };

  const shownFacts = useMemo(
    () => filterList(facts, (item) => [item.key, item.value, item.category]),
    [facts, q],
  );
  const shownPending = useMemo(
    () => filterList(pending, (item) => [item.key, item.value, item.category]),
    [pending, q],
  );
  const shownDocs = useMemo(
    () => filterList(knowledge, (item) => [item.content, item.source ?? '', item.category ?? '']),
    [knowledge, q],
  );

  const groups = useMemo(() => {
    const map: Record<string, Fact[]> = {};
    for (const item of shownFacts) {
      const groupName = categoryName(item.category);
      (map[groupName] = map[groupName] || []).push(item);
    }
    return map;
  }, [shownFacts]);

  const openEvidence = (recordRef: string, revision: number | null) =>
    setEvidenceRef({ recordRef, revision });
  const openCorrection = (recordRef: string, revision: number | null) =>
    setCorrectRef({ recordRef, revision });

  const showOldSearch = tab === 'facts' || tab === 'pending' || tab === 'knowledge';

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>记忆与资料</h1>
          <p>
            Atlas
            记住的关于你的事，以及你交给它的资料。每一条都可以查看出处、修改或彻底删除。
          </p>
        </div>
        <div className="btns">
          <button
            className="btn ghost"
            onClick={() => void refresh()}
            disabled={busy || !connected}
          >
            {busy ? (
              <LoaderCircle size={15} className="spin" />
            ) : (
              <RefreshCw size={15} />
            )}
            刷新
          </button>
          {(tab === 'facts' || tab === 'knowledge') && (
            <button
              className="btn primary"
              disabled={!connected}
              onClick={() => setAdding((value) => !value)}
            >
              <Plus size={15} />
              {tab === 'facts' ? '添加记忆' : '添加资料'}
            </button>
          )}
        </div>
      </header>

      <div className="filterbar">
        <div className="seg" role="tablist">
          <button
            aria-pressed={tab === 'timeline'}
            onClick={() => {
              setTab('timeline');
              setAdding(false);
            }}
          >
            <History size={14} />时间线
          </button>
          <button
            aria-pressed={tab === 'understanding'}
            onClick={() => {
              setTab('understanding');
              setAdding(false);
            }}
          >
            <Brain size={14} />它对我的了解
          </button>
          <button
            aria-pressed={tab === 'records'}
            onClick={() => {
              setTab('records');
              setAdding(false);
            }}
          >
            <Sparkles size={14} />记忆列表
          </button>
          <button
            aria-pressed={tab === 'entities'}
            onClick={() => {
              setTab('entities');
              setAdding(false);
            }}
          >
            <Users size={14} />人事
          </button>
          <button
            aria-pressed={tab === 'intents'}
            onClick={() => {
              setTab('intents');
              setAdding(false);
            }}
          >
            <ListTodo size={14} />提醒与待办
          </button>
          <button
            aria-pressed={tab === 'status'}
            onClick={() => {
              setTab('status');
              setAdding(false);
            }}
          >
            <Activity size={14} />状态
          </button>
          <span
            aria-hidden
            style={{ width: 1, background: 'var(--line)', margin: '0 4px' }}
          />
          <button
            aria-pressed={tab === 'pending'}
            onClick={() => {
              setTab('pending');
              setAdding(false);
            }}
          >
            待确认 {pending.length || ''}
          </button>
          <button
            aria-pressed={tab === 'knowledge'}
            onClick={() => {
              setTab('knowledge');
              setAdding(false);
            }}
          >
            资料 {knowledge.length || ''}
          </button>
        </div>
        {showOldSearch && (
          <label className="field">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={tab === 'knowledge' ? '按内容搜索资料' : '搜索记忆'}
              aria-label="搜索记忆"
            />
          </label>
        )}
      </div>

      {!connected && (
        <div className="error-note">Atlas 后端未连接，暂时无法读取记忆。</div>
      )}
      {error && (
        <div className="error-note" role="alert">
          <span>{error}</span>
          <button
            className="iconbtn"
            aria-label="关闭错误提示"
            onClick={() => setError('')}
          >
            <X size={15} />
          </button>
        </div>
      )}

      {adding && tab === 'facts' && (
        <form className="card glass form" onSubmit={saveFact}>
          <h2>添加一条记忆</h2>
          <div className="two">
            <label>
              名称
              <input
                required
                value={factForm.key}
                onChange={(event) =>
                  setFactForm({ ...factForm, key: event.target.value })
                }
                placeholder="例如：常用编辑器"
              />
            </label>
            <label>
              分类
              <input
                value={factForm.category}
                onChange={(event) =>
                  setFactForm({ ...factForm, category: event.target.value })
                }
                placeholder="general"
              />
            </label>
          </div>
          <label>
            内容
            <textarea
              required
              value={factForm.value}
              onChange={(event) =>
                setFactForm({ ...factForm, value: event.target.value })
              }
              placeholder="例如：写代码用 VS Code，主题偏暗"
            />
          </label>
          <div className="foot">
            <button
              type="button"
              className="btn ghost"
              onClick={() => setAdding(false)}
            >
              取消
            </button>
            <button className="btn primary" disabled={busy}>
              保存记忆
            </button>
          </div>
        </form>
      )}
      {adding && tab === 'knowledge' && (
        <form className="card glass form" onSubmit={saveDoc}>
          <h2>添加资料</h2>
          <label>
            内容
            <textarea
              required
              value={docForm.content}
              onChange={(event) =>
                setDocForm({ ...docForm, content: event.target.value })
              }
              placeholder="粘贴一段文字、笔记或说明，Atlas 会在需要时检索它"
            />
          </label>
          <div className="two">
            <label>
              来源
              <input
                value={docForm.source}
                onChange={(event) =>
                  setDocForm({ ...docForm, source: event.target.value })
                }
                placeholder="链接或文件名（可选）"
              />
            </label>
            <label>
              分类
              <input
                value={docForm.category}
                onChange={(event) =>
                  setDocForm({ ...docForm, category: event.target.value })
                }
                placeholder="general"
              />
            </label>
          </div>
          <div className="foot">
            <button
              type="button"
              className="btn ghost"
              onClick={() => setAdding(false)}
            >
              取消
            </button>
            <button className="btn primary" disabled={busy}>
              加入资料
            </button>
          </div>
        </form>
      )}

      {tab === 'facts' &&
        (Object.keys(groups).length ? (
          Object.entries(groups).map(([name, items]) => (
            <section className="mem-group" key={name}>
              <h3>
                {name}
                <span>{items.length}</span>
              </h3>
              <div className="list glass">
                {items.map((item) => (
                  <div className="fact" key={item.key}>
                    <div>
                      <Highlight text={item.value} query={query} />
                      <small>
                        <Highlight text={item.key} query={query} />
                        {item.updated_at
                          ? ` · ${relativeTime(item.updated_at)}更新`
                          : ''}
                      </small>
                    </div>
                    <ConfirmButton
                      label="忘掉"
                      confirm="确认忘掉"
                      disabled={busy}
                      onConfirm={() =>
                        void run(
                          () =>
                            api(
                              apiBaseUrl,
                              `/api/facts/${encodeURIComponent(item.key)}`,
                              { method: 'DELETE' },
                            ),
                          '已忘掉这条记忆',
                        )
                      }
                    />
                  </div>
                ))}
              </div>
            </section>
          ))
        ) : (
          <div className="list glass">
            <div className="empty">
              <Brain size={22} />
              <b>{q ? '没有匹配的记忆' : '还没有记忆'}</b>
              {q
                ? '换个关键词试试。'
                : '和 Atlas 聊天时它会提出想记住的内容，也可以点「添加记忆」手动告诉它。'}
            </div>
          </div>
        ))}

      {tab === 'pending' &&
        (shownPending.length ? (
          <div className="list glass">
            {shownPending.map((item) => (
              <div className="fact" key={item.id}>
                <div>
                  <Highlight text={item.value} query={query} />
                  <small>
                    {categoryName(item.category)}
                    {typeof item.confidence === 'number'
                      ? ` · 把握 ${Math.round(item.confidence * 100)}%`
                      : ''}
                    {item.created_at ? ` · ${relativeTime(item.created_at)}` : ''}
                  </small>
                </div>
                <div className="btns">
                  <button
                    className="btn ghost"
                    disabled={busy}
                    onClick={() => {
                      hide(item.id);
                      onToast('已忽略，只在本机隐藏');
                    }}
                  >
                    忽略
                  </button>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() => void remember(item)}
                  >
                    <Check size={14} />记住
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="list glass">
            <div className="empty">
              <Sparkles size={22} />
              <b>没有待确认的内容</b>Atlas 从对话中发现值得记住的事时，会先放在这里等你确认。
            </div>
          </div>
        ))}

      {tab === 'knowledge' &&
        (shownDocs.length ? (
          <div className="list glass">
            {shownDocs.map((item) => (
              <div className="fact" key={item.id}>
                <div>
                  <Highlight
                    text={
                      item.content.length > 280
                        ? `${item.content.slice(0, 280)}…`
                        : item.content
                    }
                    query={query}
                  />
                  <small>
                    {[
                      item.source,
                      categoryName(item.category),
                      relativeTime(item.created_at),
                    ]
                      .filter(Boolean)
                      .join('，')}
                  </small>
                </div>
                <ConfirmButton
                  label="删除"
                  confirm="确认删除"
                  disabled={busy}
                  onConfirm={() =>
                    void run(
                      () =>
                        api(
                          apiBaseUrl,
                          `/api/knowledge/${encodeURIComponent(item.id)}`,
                          { method: 'DELETE' },
                        ),
                      '已删除资料',
                    )
                  }
                />
              </div>
            ))}
          </div>
        ) : (
          <div className="list glass">
            <div className="empty">
              <BookMarked size={22} />
              <b>{q ? '没有找到相关资料' : '资料库是空的'}</b>
              {q
                ? '换个说法试试，搜索会按意思匹配。'
                : '把常用的说明、笔记加进来，Atlas 回答时会参考它们。'}
            </div>
          </div>
        ))}

      {/* 统一记忆主视图（S5 闭环）：条目点开弹依据；纠错走真实 corrections API；删除走 HARD_ERASE 级闭环。 */}
      {tab !== 'facts' && tab !== 'pending' && tab !== 'knowledge' && (
        <div key={viewKey}>
          {tab === 'timeline' && (
            <TimelineView
              apiBaseUrl={apiBaseUrl}
              connected={connected}
              onOpenEvidence={(item: TimelineItem) =>
                openEvidence(item.recordRef, item.revision)
              }
              onCorrect={(item: TimelineItem) =>
                openCorrection(item.recordRef, item.revision)
              }
            />
          )}
          {tab === 'understanding' && (
            <UnderstandingView
              apiBaseUrl={apiBaseUrl}
              connected={connected}
              onOpenEvidence={(item) =>
                openEvidence(item.recordRef, item.revision)
              }
              onCorrect={(item) => openCorrection(item.recordRef, item.revision)}
              onDelete={() => {
                onToast('已删除画像条目');
                setViewKey((v) => v + 1);
              }}
            />
          )}
          {tab === 'records' && (
            <RecordsView
              apiBaseUrl={apiBaseUrl}
              connected={connected}
              onOpenEvidence={openEvidence}
              onCorrect={openCorrection}
              onDelete={() => {
                onToast('已删除条目');
                setViewKey((v) => v + 1);
              }}
            />
          )}
          {tab === 'entities' && (
            <EntityView
              apiBaseUrl={apiBaseUrl}
              connected={connected}
              onDelete={() => {
                onToast('已删除实体');
                setViewKey((v) => v + 1);
              }}
            />
          )}
          {tab === 'intents' && (
            <IntentView apiBaseUrl={apiBaseUrl} connected={connected} />
          )}
          {tab === 'learning' && (
            <LearningView apiBaseUrl={apiBaseUrl} connected={connected} />
          )}
          {tab === 'status' && (
            <StatusPanel apiBaseUrl={apiBaseUrl} connected={connected} />
          )}
        </div>
      )}

      {evidenceRef && (
        <EvidencePanel
          apiBaseUrl={apiBaseUrl}
          recordRef={evidenceRef.recordRef}
          revision={evidenceRef.revision}
          onClose={() => setEvidenceRef(null)}
        />
      )}
      {correctRef && (
        <CorrectionDialog
          apiBaseUrl={apiBaseUrl}
          targetRef={correctRef.recordRef}
          expectedRevision={correctRef.revision}
          onClose={() => setCorrectRef(null)}
          onCorrected={() => {
            onToast('纠偏成功，新会话立即生效');
            setViewKey((value) => value + 1);
          }}
        />
      )}
    </div>
  );
}
