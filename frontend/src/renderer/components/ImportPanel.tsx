import { useState } from 'react';
import { CheckSquare, ClipboardList, LoaderCircle, Square } from 'lucide-react';
import type { ExternalImportItem } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
import { cn } from '../ui/cn';
import styles from '../App.module.css';

type ImportSource = 'claude' | 'codex';

const SOURCE_META: Record<ImportSource, { label: string; hint: string }> = {
  claude: { label: '从 Claude Code 导入', hint: '读取 Claude Code 的配置：MCP 服务、Hooks、CLAUDE.md 等规则文件、技能、子 Agent 定义、自定义命令、模型偏好和最近对话。只读取，不会改动原来那边的任何文件。' },
  codex: { label: '从 Codex 导入', hint: '读取 Codex 的配置和会话记录。只读取，不会改动原来那边的任何文件。' },
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

/** Pick the two import entries (Claude Code / Codex), scan, check off a list, then import and see a short report. */
export default function ImportPanel({ workspace }: { workspace?: string }) {
  const [source, setSource] = useState<ImportSource | null>(null);
  const [items, setItems] = useState<ExternalImportItem[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [sources, setSources] = useState<string[] | undefined>(undefined);
  const [scanning, setScanning] = useState(false);
  const [importing, setImporting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const keyOf = (item: ExternalImportItem) => `${item.kind}:${item.path}`;

  const scan = async (target: ImportSource) => {
    setSource(target);
    setItems([]);
    setChecked(new Set());
    setNotice(null);
    setError(null);
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
    <p style={{ marginBottom: 12 }}>把 Claude Code 或 Codex 里已有的东西搬进 Atlas。导入前先扫描列出清单，勾选之后才会真正导入。</p>
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
  </section>;
}
