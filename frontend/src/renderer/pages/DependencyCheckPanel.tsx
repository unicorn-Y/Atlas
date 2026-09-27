import { useState } from 'react';
import styles from '../App.module.css';

interface DependencyState {
  name: string;
  kind: string;
  requested?: string | null;
  detected?: unknown;
  state: 'satisfied' | 'missing' | 'incompatible' | 'unknown';
  blocking_reason?: string | null;
}

interface DependencyReport {
  checked_at: string;
  read_only: boolean;
  node: {
    available: boolean;
    source: string;
    version: string | null;
    bundled: { available: boolean; version: string | null; blocking_reason?: string | null };
    blocking_reason?: string | null;
  };
  mcp_runtime: { available: boolean; blocking_reason?: string | null };
  mcp_servers: Array<{
    name: string;
    state: string;
    connected: boolean;
    tool_discovery: string;
    tool_count: number;
    blocking_reason?: string | null;
  }>;
  skills: Array<{
    name: string;
    version: string;
    dependencies: DependencyState[];
    blocking: DependencyState[];
    can_use: boolean;
  }>;
  blocking: Array<{ scope: string; reason: string }>;
}

export default function DependencyCheckPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [report, setReport] = useState<DependencyReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const check = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/api/runtime/dependency-check`);
      if (!response.ok) throw new Error(`检查失败 (${response.status})`);
      setReport(await response.json() as DependencyReport);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setReport(null);
    } finally {
      setLoading(false);
    }
  };

  return <section className={styles.settingsCard} aria-label="依赖检查">
    <div className={styles.settingsCardHeading}>
      <h2>运行环境与 Skill 依赖</h2>
      <button className={styles.settingsActionSecondary} type="button" onClick={() => void check()} disabled={loading}>
        {loading ? '检查中…' : '检查依赖'}
      </button>
    </div>
    <p>只读检查 Atlas 内置 Node、MCP server 与 Skill canonical dependencies，不会安装或修改环境。</p>
    <p>发现阻塞项后，可使用内置 Node、配置 MCP server 或安装缺失依赖，再重新检查。</p>
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {report && <div aria-live="polite">
      <p className={report.node.bundled.available ? styles.settingsSuccess : styles.settingsError}>
        内置 Node：{report.node.bundled.available ? `可用 ${report.node.bundled.version ?? ''}` : report.node.bundled.blocking_reason ?? '不可用'}
      </p>
      <p className={report.mcp_runtime.available ? styles.settingsSuccess : styles.settingsError}>
        MCP runtime：{report.mcp_runtime.available ? '可用' : report.mcp_runtime.blocking_reason ?? '不可用'}
      </p>
      <p>检查时间：{new Date(report.checked_at).toLocaleString()}</p>
      <h3>MCP servers</h3>
      {report.mcp_servers.length ? report.mcp_servers.map((server) => <p key={server.name}>
        {server.name}：{server.state} · tools {server.tool_count} · discovery {server.tool_discovery}
        {server.blocking_reason ? ` · ${server.blocking_reason}` : ''}
      </p>) : <p>没有已配置的 MCP server。</p>}
      <h3>Skill dependencies</h3>
      {report.skills.length ? report.skills.map((skill) => <div className={styles.dependencySkill} key={`${skill.name}@${skill.version}`}>
        <strong>{skill.name}@{skill.version}</strong>
        {skill.dependencies.length ? skill.dependencies.map((dependency) => <p key={`${dependency.kind}:${dependency.name}:${dependency.requested ?? ''}`}>
          {dependency.kind}:{dependency.name}{dependency.requested ? ` ${dependency.requested}` : ''} — {dependency.state}
          {dependency.blocking_reason ? ` · ${dependency.blocking_reason}` : ''}
        </p>) : <p>没有声明依赖。</p>}
      </div>) : <p>没有已注册的 active Skill。</p>}
      {report.blocking.map((item, index) => <p className={styles.settingsError} role="status" key={`${item.scope}:${index}`}>
        阻止项（{item.scope}）：{item.reason}
      </p>)}
      {(report.blocking.length > 0 || report.skills.some((skill) => !skill.can_use)) && <p>
        下一步：使用内置 Node；配置或修复对应 MCP server；按说明安装缺失依赖后重新检查。Atlas 不会自动执行这些变更。
      </p>}
    </div>}
  </section>;
}
