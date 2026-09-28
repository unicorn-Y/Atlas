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

const labels: Record<string, string> = {
  'atlas.native': 'Atlas Native', 'local.full_access': '本机 FULL_ACCESS',
  'computer.cua': 'Cua Driver', 'computer.pywinauto': 'pywinauto',
  'browser.browser_use': 'Browser Use', 'mcp.playwright': 'Playwright MCP',
  'mcp.chrome_devtools': 'Chrome DevTools MCP', 'coding.serena': 'Serena',
  'coding.ast_grep': 'ast-grep', 'coding.repo_map': 'Aider Repo Map',
  'durable.dbos': 'DBOS', 'agent.acp': 'ACP client', 'agent.codex': 'Codex',
  'agent.claude': 'Claude Agent SDK', 'agent.hermes': 'Hermes',
  'agent.pi': 'Pi', 'agent.zcode': 'ZCode',
};

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
      <div><h2>集成与能力</h2><p>共 {items.length} 项；显示本机依赖发现与运行状态。</p></div>
      <button className={styles.settingsActionSecondary} disabled={busy} onClick={() => void refresh()}>
        {busy ? <LoaderCircle size={14} className={styles.settingsSpinner} /> : <RefreshCw size={14} />}刷新
      </button>
    </div>
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    <div className={styles.integrationList}>
      {items.map((item) => <div className={styles.integrationRow} key={item.id}>
        <div><strong>{labels[item.id] ?? item.id}</strong><small>{item.kind} · {item.version ?? '未安装'} · {item.source}</small>
          {item.last_error && <small className={styles.integrationError}>{item.last_error}</small>}
        </div>
        <span className={`${styles.integrationState} ${item.status === 'ready' ? styles.integrationReady : ''}`}>
          {item.status} · {item.connected ? '已连接' : '未连接'}
        </span>
        <button className={styles.settingsActionSecondary} disabled={busy || item.id === 'atlas.native' || item.id === 'local.full_access'} onClick={() => void toggle(item)}>
          {item.enabled ? '停用' : '启用'}
        </button>
      </div>)}
      {!items.length && !busy && <p>后端未返回集成状态。</p>}
    </div>
  </section>;
}
