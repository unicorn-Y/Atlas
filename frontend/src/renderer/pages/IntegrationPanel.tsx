import { useCallback, useEffect, useState } from 'react';
import { LoaderCircle, RefreshCw } from 'lucide-react';
import styles from '../App.module.css';

interface Integration {
  id: string;
  kind: string;
  source: string;
  version: string | null;
  status: string;
  enabled: boolean;
  connected: boolean;
  last_error: string | null;
}

interface RegistryResponse {
  capabilities: Integration[];
}

const labels: Record<string, [string, string]> = {
  'atlas.native': ['Atlas 核心', '负责思考和调度的主引擎'],
  'local.full_access': ['本机操作', '读写文件、运行命令'],
  'computer.cua': ['电脑操控 · Cua', '看屏幕、点鼠标、敲键盘'],
  'computer.pywinauto': ['Windows 窗口操控', '操作桌面程序里的按钮和输入框'],
  'browser.browser_use': ['浏览器代理 · Browser Use', '自己打开网页把事情办完'],
  'mcp.playwright': ['网页自动化 · Playwright', '打开、点击、填写网页'],
  'mcp.chrome_devtools': ['浏览器调试 · Chrome DevTools', '查看网页的请求、控制台和性能'],
  'coding.serena': ['代码理解 · Serena', '按符号查找和修改代码'],
  'coding.ast_grep': ['代码结构搜索 · ast-grep', '按语法结构批量搜索代码'],
  'coding.repo_map': ['仓库地图 · Aider', '快速了解一个仓库的结构'],
  'durable.dbos': ['持久任务 · DBOS', '重启后长任务能接着跑'],
  'agent.acp': ['外部 Agent 连接 · ACP', '把任务交给其他编程 Agent'],
  'agent.codex': ['Codex', '外部编程 Agent'],
  'agent.claude': ['Claude Agent', '外部编程 Agent'],
  'agent.hermes': ['Hermes', '外部 Agent'],
  'agent.pi': ['Pi', '外部编程 Agent'],
  'agent.zcode': ['ZCode', '外部编程 Agent'],
};

function stateOf(item: Integration): { text: string; tone: 'ok' | 'warn' | 'bad' | 'off' } {
  if (!item.enabled) return { text: '已停用', tone: 'off' };
  if (item.status === 'ready') return { text: item.connected ? '运行中' : '可用', tone: 'ok' };
  if (item.status === 'degraded') return { text: '部分可用', tone: 'warn' };
  return { text: '不可用', tone: 'bad' };
}
const TONE = { ok: 'var(--ok)', warn: 'var(--brand)', bad: 'var(--danger)', off: 'var(--fg-3)' };

export default function IntegrationPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [items, setItems] = useState<Integration[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations?refresh=true`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json() as RegistryResponse;
      setItems(body.capabilities);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Registry request failed');
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  const toggle = async (item: Integration) => {
    setBusy(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations/${encodeURIComponent(item.id)}/enabled`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !item.enabled }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Integration update failed');
    } finally {
      setBusy(false);
    }
  };

  return <section className={styles.settingsCard} aria-label="集成与能力">
    <div className={styles.settingsCardHeading}>
      <div><h2>能力与集成</h2><p>Atlas 能用的 {items.length} 项能力，以及它们现在的状态。</p></div>
      <button className={styles.settingsActionSecondary} disabled={busy} onClick={() => void refresh()}>
        {busy ? <LoaderCircle size={14} className={styles.settingsSpinner} /> : <RefreshCw size={14} />}刷新
      </button>
    </div>
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    <div className={styles.integrationList}>
      {items.map((item) => {
        const [name, hint] = labels[item.id] ?? [item.id, item.kind];
        const state = stateOf(item);
        return <div className={styles.integrationRow} key={item.id} title={`${item.id}，${item.kind}，${item.version ?? '未安装'}，${item.source}`}>
        <div><strong>{name}</strong><small>{hint}{item.version ? `，版本 ${item.version}` : ''}</small>
          {item.last_error && <small className={styles.integrationError}>{item.last_error}</small>}
        </div>
        <span className={styles.integrationState} style={{ color: TONE[state.tone], display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <i style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }} />{state.text}
        </span>
        <button className={styles.settingsActionSecondary} disabled={busy || item.id === 'atlas.native' || item.id === 'local.full_access'} onClick={() => void toggle(item)}>
          {item.enabled ? '停用' : '启用'}
        </button>
      </div>;
      })}
      {!items.length && !busy && <p>后端未返回集成状态。</p>}
    </div>
  </section>;
}
