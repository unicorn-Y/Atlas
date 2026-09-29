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
      <h2>运行环境检查</h2>
      <button className={styles.settingsActionSecondary} type="button" onClick={() => void check()} disabled={loading}>
        {loading ? '检查中…' : '开始检查'}
      </button>
    </div>
    <p>检查 Atlas 自带的 Node、MCP 工具服务和各项技能需要的依赖。只看不改，不会安装或修改任何东西。</p>
    <p>如果发现问题，按提示使用内置 Node、修好对应的 MCP 工具服务或装上缺的依赖，再检查一次。</p>
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {report && <div aria-live="polite">
      <p className={report.node.bundled.available ? styles.settingsSuccess : styles.settingsError}>
        内置 Node：{report.node.bundled.available ? `可用 ${report.node.bundled.version ?? ''}` : report.node.bundled.blocking_reason ?? '不可用'}
      </p>
      <p className={report.mcp_runtime.available ? styles.settingsSuccess : styles.settingsError}>
        MCP 运行环境：{report.mcp_runtime.available ? '可用' : report.mcp_runtime.blocking_reason ?? '不可用'}
      </p>
      <p>检查时间：{new Date(report.checked_at).toLocaleString()}</p>
      <h3>MCP 工具服务</h3>
      {report.mcp_servers.length ? report.mcp_servers.map((server) => <p key={server.name} title={`discovery: ${server.tool_discovery}`}>
        {server.name}：{server.state}，{server.tool_count} 个工具
        {server.blocking_reason ? `，${server.blocking_reason}` : ''}
      </p>) : <p>还没有配置 MCP 工具服务。</p>}
      <h3>技能依赖</h3>
      {report.skills.length ? report.skills.map((skill) => <div className={styles.dependencySkill} key={`${skill.name}@${skill.version}`}>
        <strong>{skill.name}@{skill.version}</strong>
        {skill.dependencies.length ? skill.dependencies.map((dependency) => <p key={`${dependency.kind}:${dependency.name}:${dependency.requested ?? ''}`}>
          {dependency.kind}:{dependency.name}{dependency.requested ? ` ${dependency.requested}` : ''} — {dependency.state}
          {dependency.blocking_reason ? ` · ${dependency.blocking_reason}` : ''}
        </p>) : <p>没有声明依赖。</p>}
      </div>) : <p>没有启用中的技能。</p>}
      {report.blocking.map((item, index) => <p className={styles.settingsError} role="status" key={`${item.scope}:${index}`}>
        阻止项（{item.scope}）：{item.reason}
      </p>)}
      {(report.blocking.length > 0 || report.skills.some((skill) => !skill.can_use)) && <p>
        下一步：使用内置 Node；配置或修复对应 MCP server；按说明安装缺失依赖后重新检查。Atlas 不会自动执行这些变更。
      </p>}
    </div>}
  </section>;
}
