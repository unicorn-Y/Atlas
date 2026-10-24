import { useState } from 'react';
import { CheckSquare, ClipboardList, LoaderCircle, Square } from 'lucide-react';
import type { ExternalImportItem } from '@atlas/backend-adapter';
import { backend, useAtlasStore } from '../store/useAtlasStore';
import { cn } from '../ui/cn';
import { api } from '../services/api';
import styles from '../App.module.css';

type ImportSource = 'claude' | 'codex' | 'openclaw';

const SOURCE_META: Record<ImportSource, { label: string; hint: string }> = {
  claude: { label: '从 Claude Code 导入', hint: '读取 Claude Code 的配置：MCP 服务、Hooks、CLAUDE.md 等规则文件、技能、子 Agent 定义、自定义命令和模型偏好；历史会话可在下方逐条预览后选择导入。不会改动 Claude Code 的文件。' },
  codex: { label: '从 Codex 导入', hint: '读取 Codex 的配置；历史会话可在下方逐条预览后选择导入。不会改动 Codex 的文件。' },
  openclaw: { label: '从 OpenClaw 导入', hint: '扫描 OpenClaw 的 MCP、工作区说明、技能和子 Agent；历史会话会逐条预览后选择导入。只读源文件，不导入源凭据。' },
};

const KIND_LABEL: Record<string, string> = {
  mcp: 'MCP 服务',
  hooks: 'Hooks',
  rules: '规则文件',
  skills: '技能',
  agents: '子 Agent',
  commands: '自定义命令',
  prompts: '提示词命令',
  model_preferences: '模型偏好',
  history: '最近对话',
};
const kindLabel = (kind: string) => KIND_LABEL[kind] ?? kind;

type HistorySession = {
  key: string;
  title: string;
  modified_at: string;
  message_count: number;
  preview: string;
  imported: boolean;
};

type ExternalHistoryScan = {
  sessions: HistorySession[];
  total_files: number;
  omitted_files: number;
  truncated: boolean;
};

function formatHistoryTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}

/** Scan Claude Code / Codex / OpenClaw, review entries, then import selected files and sessions. */
export default function ImportPanel({ workspace }: { workspace?: string }) {
  const apiBaseUrl = useAtlasStore((state) => state.apiBaseUrl);
  const refreshConversations = useAtlasStore((state) => state.refreshConversations);
  const [source, setSource] = useState<ImportSource | null>(null);
  const [items, setItems] = useState<ExternalImportItem[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [sources, setSources] = useState<string[] | undefined>(undefined);
  const [scanning, setScanning] = useState(false);
  const [importing, setImporting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<ExternalHistoryScan | null>(null);
  const [historyChecked, setHistoryChecked] = useState<Set<string>>(new Set());
  const [historyScanning, setHistoryScanning] = useState(false);
  const [historyImporting, setHistoryImporting] = useState(false);
  const [historyDays, setHistoryDays] = useState<7 | 30 | 90 | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyNotice, setHistoryNotice] = useState<string | null>(null);

  const keyOf = (item: ExternalImportItem) => `${item.kind}:${item.path}`;

  const scan = async (target: ImportSource) => {
    setSource(target);
    setItems([]);
    setChecked(new Set());
    setNotice(null);
    setError(null);
    setHistory(null);
    setHistoryChecked(new Set());
    setHistoryError(null);
    setHistoryNotice(null);
    setScanning(true);
    try {
      const result = await backend.scanExternalImport(target, workspace || undefined);
      setItems(result.items ?? []);
      setSources(result.sources);
      // 已存在的同名项（conflict）默认不勾，由用户逐条决定要不要覆盖。
      setChecked(new Set((result.items ?? []).filter((item) => !item.conflict).map(keyOf)));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setScanning(false);
    }
  };

  const scanHistory = async (days: 7 | 30 | 90 | null = historyDays) => {
    if (!source) return;
    setHistoryScanning(true);
    setHistoryError(null);
    setHistoryNotice(null);
    setHistoryChecked(new Set());
    try {
      const result = await api<ExternalHistoryScan & { source: ImportSource }>(
        apiBaseUrl, `/api/import/external/history?source=${source}${days ? `&days=${days}` : ''}`,
      );
      setHistory(result);
    } catch (exc) {
      setHistoryError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setHistoryScanning(false);
    }
  };

  const importHistory = async () => {
    if (!source || !historyChecked.size) return;
    setHistoryImporting(true);
    setHistoryError(null);
    setHistoryNotice(null);
    try {
      const result = await api<{
        imported: number;
        messages_imported: number;
        skipped: number;
        results: Array<{ key: string; status: string; error?: string }>;
      }>(apiBaseUrl, '/api/import/external/history/import', {
        method: 'POST',
        json: { source, session_keys: [...historyChecked] },
      });
      const failures = result.results.filter((item) => item.status === 'failed');
      setHistoryNotice(`已导入 ${result.imported} 段会话、${result.messages_imported} 条消息；跳过 ${result.skipped} 段。${failures.length ? `失败：${failures.map((item) => item.error || '未知错误').join('；')}` : ''}`);
      setHistoryChecked(new Set());
      await refreshConversations();
      await scanHistory();
    } catch (exc) {
      setHistoryError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setHistoryImporting(false);
    }
  };

  const runImport = async () => {
    if (!source) return;
    const picked = items.filter((item) => checked.has(keyOf(item)));
    if (!picked.length) { setNotice('先勾选要导入的内容'); return; }
    setImporting(true);
    setError(null);
    try {
      const result = await backend.importExternal(source, picked, workspace || undefined);
      const report = typeof result.report === 'string' && result.report.trim() ? `\n${result.report.trim()}` : '';
      setNotice(`导入完成：${result.imported} 项成功，${result.skipped} 项跳过。${report}`.trim());
      setItems([]);
      setChecked(new Set());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setImporting(false);
    }
  };

  return <section className={styles.settingsCard} aria-label="从其他工具导入">
    <h2>导入其他工具的配置</h2>
    <p style={{ marginBottom: 12 }}>把 Claude Code、Codex 或 OpenClaw 里已有的内容搬进 Atlas。导入前先扫描列出清单，勾选之后才会真正导入。</p>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {(Object.keys(SOURCE_META) as ImportSource[]).map((key) => (
        <button key={key} className={source === key ? styles.settingsAction : styles.settingsActionSecondary} disabled={scanning || importing}
          onClick={() => void scan(key)}>
          {source === key && scanning ? <LoaderCircle size={14} className={styles.settingsSpinner} /> : <ClipboardList size={14} />}
          {SOURCE_META[key].label}
        </button>
      ))}
    </div>
    {source && <p style={{ margin: '10px 0 0', fontSize: 12.5, color: 'var(--fg-3)' }}>{SOURCE_META[source].hint}</p>}
    {sources && sources.length > 0 && <p style={{ margin: '6px 0 0', fontSize: 12.5, color: 'var(--fg-3)' }}>找到来源：{sources.join('、')}</p>}
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {notice && <p role="status" style={{ margin: '10px 0 0', fontSize: 13, color: 'var(--fg-2)', whiteSpace: 'pre-wrap' }}>{notice}</p>}

    {source && items.length > 0 && <div style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ fontSize: 13, color: 'var(--fg-2)' }}>找到 {items.length} 项，已勾选 {checked.size} 项。标了「已存在」的不勾，想要才勾。</span>
        <button className={styles.settingsAction} disabled={importing || !checked.size} onClick={() => void runImport()}>
          {importing ? <LoaderCircle size={14} className={styles.settingsSpinner} /> : <CheckSquare size={14} />}
          导入所选
        </button>
      </div>
      <ul className={styles.integrationList}>
        {items.map((item) => {
          const key = keyOf(item);
          const on = checked.has(key);
          return <label key={key} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '8px 12px', borderRadius: 10, background: 'var(--sunken)', cursor: 'pointer' }}>
            <input type="checkbox" checked={on} onChange={(event) => {
              setChecked((previous) => {
                const next = new Set(previous);
                if (event.target.checked) next.add(key); else next.delete(key);
                return next;
              });
            }} style={{ marginTop: 3 }} />
            <span style={{ minWidth: 0, flex: 1 }}>
              <span style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 13.5 }}>
                {on ? <CheckSquare size={13} className="text-brand" /> : <Square size={13} className="text-fg-3" />}
                <strong style={{ color: 'var(--fg)' }}>{item.name}</strong>
                <span style={{ fontSize: 11.5, color: 'var(--fg-3)' }}>{kindLabel(item.kind)}</span>
                {item.conflict && <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 6, background: 'var(--danger-soft)', color: 'var(--danger)' }}>已存在，默认跳过</span>}
                {item.action && <span style={{ fontSize: 11.5, color: 'var(--fg-3)' }}>动作：{item.action}</span>}
              </span>
              <span className={cn('block truncate')} style={{ fontSize: 12, color: 'var(--fg-3)' }} title={item.path}>{item.path}</span>
              {item.detail && <span className="block" style={{ fontSize: 12, color: 'var(--fg-3)' }}>{item.detail}</span>}
            </span>
          </label>;
        })}
      </ul>
    </div>}
    {source && !scanning && items.length === 0 && !error && <p style={{ margin: '10px 0 0', fontSize: 13, color: 'var(--fg-3)' }}>没有扫描到可以导入的内容。</p>}

    {source && <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--line)' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 14 }}>导入历史会话</h3>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--fg-3)' }}>只扫描本机识别的 Claude Code / Codex 会话目录；每段会话先展示截断预览，选择后追加到新的 Atlas 会话。</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ fontSize: 12, color: 'var(--fg-3)' }}>扫描时间
            <select aria-label="会话历史时间范围" value={historyDays ?? 'all'} disabled={historyScanning || historyImporting}
              onChange={(event) => {
                const raw = event.target.value;
                const days = raw === 'all' ? null : Number(raw) as 7 | 30 | 90;
                setHistoryDays(days);
                void scanHistory(days);
              }}
              style={{ marginLeft: 6, padding: '5px 8px', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface)', color: 'var(--fg)' }}>
              <option value="7">最近 7 天</option><option value="30">最近 30 天</option>
              <option value="90">最近 90 天</option><option value="all">全部时间</option>
            </select>
          </label>
          <button className={styles.settingsActionSecondary} disabled={historyScanning || historyImporting} onClick={() => void scanHistory()}>
            {historyScanning ? <LoaderCircle size={14} className={styles.settingsSpinner} /> : <ClipboardList size={14} />}
            扫描会话
          </button>
        </div>
      </div>
      {historyError && <p className={styles.settingsError} role="alert">{historyError}</p>}
      {historyNotice && <p className={styles.settingsSuccess} role="status">{historyNotice}</p>}
      {history && <>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap', margin: '10px 0 8px' }}>
          <span style={{ fontSize: 12.5, color: 'var(--fg-2)' }}>
            列出 {history.sessions.length} 段会话{history.total_files > 0 ? `（共发现 ${history.total_files} 个历史文件）` : ''}，已选 {historyChecked.size} 段。
            {history.omitted_files > 0 || history.truncated ? ` 已省略 ${history.omitted_files} 个无法安全读取或超出扫描上限的文件。` : ''}
          </span>
          <button className={styles.settingsAction} disabled={historyImporting || !historyChecked.size} onClick={() => void importHistory()}>
            {historyImporting ? <LoaderCircle size={14} className={styles.settingsSpinner} /> : <CheckSquare size={14} />}
            导入选中会话
          </button>
        </div>
        {history.sessions.length === 0 ? <p style={{ margin: '8px 0', fontSize: 13, color: 'var(--fg-3)' }}>没有找到包含可显示文本的历史会话。</p> :
          <ul className={styles.integrationList}>
            {history.sessions.map((session) => {
              const checkedOn = historyChecked.has(session.key);
              return <li key={session.key} style={{ listStyle: 'none', padding: '9px 12px', borderRadius: 10, background: 'var(--sunken)' }}>
                <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: session.imported ? 'default' : 'pointer' }}>
                  <input type="checkbox" checked={checkedOn} disabled={session.imported || historyImporting} onChange={(event) => {
                    setHistoryChecked((previous) => {
                      const next = new Set(previous);
                      if (event.target.checked) next.add(session.key); else next.delete(session.key);
                      return next;
                    });
                  }} style={{ marginTop: 3 }} />
                  <span style={{ minWidth: 0, flex: 1 }}>
                    <span style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 13.5 }}>
                      {checkedOn ? <CheckSquare size={13} className="text-brand" /> : <Square size={13} className="text-fg-3" />}
                      <strong style={{ color: 'var(--fg)' }}>{session.title}</strong>
                      <span style={{ fontSize: 11.5, color: 'var(--fg-3)' }}>{session.message_count} 条文本消息</span>
                      {formatHistoryTime(session.modified_at) && <span style={{ fontSize: 11.5, color: 'var(--fg-3)' }}>{formatHistoryTime(session.modified_at)}</span>}
                      {session.imported && <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 6, background: 'var(--ok-soft)', color: 'var(--ok)' }}>已导入</span>}
                    </span>
                    <span className="block whitespace-pre-wrap" style={{ marginTop: 5, fontSize: 12, color: 'var(--fg-2)' }}>{session.preview}</span>
                  </span>
                </label>
              </li>;
            })}
          </ul>}
      </>}
    </div>}
  </section>;
}
