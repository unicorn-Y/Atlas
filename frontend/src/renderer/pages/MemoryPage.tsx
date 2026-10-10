/**
 * MemoryPage —— 记忆与资料。Atlas 只有一个记忆引擎：MemOS 的 Atlas fork（vendor/memos-local-plugin）。
 *   - 关于你：FactsView，你说过的关于自己的事（当前 / 历史 / 到期），每轮对话自动带上
 *   - 记忆变动：MemoryChangesView，每一次新增 / 修改 / 删除 / 淡忘，附改动前后内容；暂停 / 恢复
 *   - 经验与技能：LibraryView，MemOS 提炼出的技能、策略、世界模型
 *   - 提醒：RemindersView，聊天里建的提醒，可取消
 *   - 资料：用户交给 Atlas 的笔记和说明（/api/knowledge）
 */
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { BellRing, BookMarked, GitCompare, LoaderCircle, Plus, RefreshCw, Search, Sparkles, UserRound, X } from 'lucide-react';
import { api, relativeTime } from '../services/api';
import FactsView from '../components/memory/FactsView';
import LibraryView from '../components/memory/LibraryView';
import MemoryChangesView from '../components/memory/MemoryChangesView';
import RemindersView from '../components/memory/RemindersView';
import { ConfirmButton } from '../components/memory/common';

interface Knowledge {
  id: string;
  content: string;
  source?: string;
  category?: string;
  created_at?: string;
}

type Tab = 'facts' | 'changes' | 'library' | 'reminders' | 'knowledge';

const TABS: Array<{ value: Tab; label: string; icon: typeof UserRound }> = [
  { value: 'facts', label: '关于你', icon: UserRound },
  { value: 'changes', label: '记忆变动', icon: GitCompare },
  { value: 'library', label: '经验与技能', icon: Sparkles },
  { value: 'reminders', label: '提醒', icon: BellRing },
  { value: 'knowledge', label: '资料', icon: BookMarked },
];

const CATEGORY: Record<string, string> = {
  general: '通用', preference: '偏好', profile: '个人信息', project: '项目', work: '工作',
};
const categoryName = (value?: string) => CATEGORY[value ?? 'general'] ?? value ?? '通用';

function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim();
  if (!q) return <>{text}</>;
  const index = text.toLowerCase().indexOf(q.toLowerCase());
  if (index < 0) return <>{text}</>;
  return <>{text.slice(0, index)}<mark>{text.slice(index, index + q.length)}</mark>{text.slice(index + q.length)}</>;
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
  const [tab, setTab] = useState<Tab>('facts');
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [adding, setAdding] = useState(false);
  const [docForm, setDocForm] = useState({ content: '', source: '', category: 'general' });

  // The old "待确认" queue belonged to the retired local memory; nothing is pending anymore.
  useEffect(() => { onPendingChange?.(0); }, [onPendingChange]);

  const loadKnowledge = useCallback(async () => {
    if (!connected) return;
    setBusy(true);
    try {
      setKnowledge((await api<Knowledge[]>(apiBaseUrl, '/api/knowledge')) || []);
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setBusy(false); }
  }, [apiBaseUrl, connected]);

  useEffect(() => { if (tab === 'knowledge') void loadKnowledge(); }, [tab, loadKnowledge]);

  const run = async (fn: () => Promise<unknown>, toast: string) => {
    setBusy(true);
    try {
      await fn();
      await loadKnowledge();
      onToast(toast);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setBusy(false); }
  };

  const saveDoc = (event: FormEvent) => {
    event.preventDefault();
    if (!docForm.content.trim()) return;
    void run(async () => {
      await api(apiBaseUrl, '/api/knowledge', {
        method: 'POST',
        json: { content: docForm.content.trim(), source: docForm.source.trim(), category: docForm.category.trim() || 'general' },
      });
      setDocForm({ content: '', source: '', category: 'general' });
      setAdding(false);
    }, '已添加资料');
  };

  const q = query.trim().toLowerCase();
  const shownDocs = useMemo(
    () => (q ? knowledge.filter((item) => [item.content, item.source ?? '', item.category ?? ''].some((v) => v.toLowerCase().includes(q))) : knowledge),
    [knowledge, q],
  );

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>记忆与资料</h1>
          <p>Atlas 记住的关于你的事、学到的经验，以及你交给它的资料。每一条都能看到出处，都可以删除。</p>
        </div>
        {tab === 'knowledge' && <div className="btns">
          <button className="btn ghost" onClick={() => void loadKnowledge()} disabled={busy || !connected}>
            {busy ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}刷新
          </button>
          <button className="btn primary" disabled={!connected} onClick={() => setAdding((value) => !value)}>
            <Plus size={15} />添加资料
          </button>
        </div>}
      </header>

      <div className="filterbar">
        <div className="seg" role="tablist">
          {TABS.map(({ value, label, icon: Icon }) => <button key={value} aria-pressed={tab === value}
            onClick={() => { setTab(value); setAdding(false); }}>
            <Icon size={14} />{label}{value === 'knowledge' && knowledge.length ? ` ${knowledge.length}` : ''}
          </button>)}
        </div>
        {tab === 'knowledge' && <label className="field">
          <Search size={16} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按内容搜索资料" aria-label="搜索资料" />
        </label>}
      </div>

      {!connected && <div className="error-note">Atlas 后端未连接，暂时无法读取记忆。</div>}
      {error && <div className="error-note" role="alert">
        <span>{error}</span>
        <button className="iconbtn" aria-label="关闭错误提示" onClick={() => setError('')}><X size={15} /></button>
      </div>}

      {tab === 'facts' && <FactsView apiBaseUrl={apiBaseUrl} connected={connected} onToast={onToast} />}
      {tab === 'changes' && <MemoryChangesView apiBaseUrl={apiBaseUrl} connected={connected} />}
      {tab === 'library' && <LibraryView apiBaseUrl={apiBaseUrl} connected={connected} onToast={onToast} />}
      {tab === 'reminders' && <RemindersView apiBaseUrl={apiBaseUrl} connected={connected} onToast={onToast} />}

      {tab === 'knowledge' && adding && <form className="card glass form" onSubmit={saveDoc}>
        <h2>添加资料</h2>
        <label>内容
          <textarea required value={docForm.content} onChange={(event) => setDocForm({ ...docForm, content: event.target.value })}
            placeholder="粘贴一段文字、笔记或说明，Atlas 会在需要时检索它" />
        </label>
        <div className="two">
          <label>来源
            <input value={docForm.source} onChange={(event) => setDocForm({ ...docForm, source: event.target.value })} placeholder="链接或文件名（可选）" />
          </label>
          <label>分类
            <input value={docForm.category} onChange={(event) => setDocForm({ ...docForm, category: event.target.value })} placeholder="general" />
          </label>
        </div>
        <div className="foot">
          <button type="button" className="btn ghost" onClick={() => setAdding(false)}>取消</button>
          <button className="btn primary" disabled={busy}>加入资料</button>
        </div>
      </form>}

      {tab === 'knowledge' && (shownDocs.length ? <div className="list glass">
        {shownDocs.map((item) => <div className="fact" key={item.id}>
          <div>
            <Highlight text={item.content.length > 280 ? `${item.content.slice(0, 280)}…` : item.content} query={query} />
            <small>{[item.source, categoryName(item.category), relativeTime(item.created_at)].filter(Boolean).join('，')}</small>
          </div>
          <ConfirmButton label="删除" confirm="确认删除" disabled={busy}
            onConfirm={() => void run(() => api(apiBaseUrl, `/api/knowledge/${encodeURIComponent(item.id)}`, { method: 'DELETE' }), '已删除资料')} />
        </div>)}
      </div> : <div className="list glass"><div className="empty">
        <BookMarked size={22} />
        <b>{q ? '没有找到相关资料' : '资料库是空的'}</b>
        {q ? '换个说法试试，搜索会按意思匹配。' : '把常用的说明、笔记加进来，Atlas 回答时会参考它们。'}
      </div></div>)}
    </div>
  );
}
