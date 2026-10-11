import { useEffect, useState, type FormEvent } from 'react';
import { api } from '../../services/api';
import styles from '../../App.module.css';

type NetworkSettings = {
  proxy_configured: boolean;
  proxy_status: 'not_configured' | 'configured' | 'missing' | 'unavailable';
  proxy_label: string | null;
  ca_bundle_path: string;
  restart_required: boolean;
  supported_transports: string[];
  unsupported_transports: string[];
};

export default function NetworkSettingsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [settings, setSettings] = useState<NetworkSettings | null>(null);
  const [proxyUrl, setProxyUrl] = useState('');
  const [clearProxy, setClearProxy] = useState(false);
  const [caBundlePath, setCaBundlePath] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const field = 'h-9 w-full rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)] disabled:opacity-60';

  const load = async () => {
    const result = await api<NetworkSettings>(apiBaseUrl, '/api/model-network-settings');
    setSettings(result);
    setCaBundlePath(result.ca_bundle_path);
  };

  useEffect(() => {
    void load().catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [apiBaseUrl]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const body: { proxy_url?: string; clear_proxy: boolean; ca_bundle_path: string } = {
        clear_proxy: clearProxy,
        ca_bundle_path: caBundlePath.trim(),
      };
      if (proxyUrl.trim()) body.proxy_url = proxyUrl.trim();
      const updated = await api<NetworkSettings>(apiBaseUrl, '/api/model-network-settings', {
        method: 'PUT', json: body,
      });
      setSettings(updated);
      setProxyUrl('');
      setClearProxy(false);
      setCaBundlePath(updated.ca_bundle_path);
      setMessage('已保存。请重启 Atlas 后端；当前运行中的会话和 Hermes 辅助模型缓存不会即时更新。');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return <section className={styles.settingsCard} aria-label="模型网络设置">
    <div className={styles.settingsCardHeading}><h2>模型网络</h2></div>
    <p>代理与 CA 只应用于 Atlas 的模型 HTTPX 请求，不会改写系统代理环境变量，也不会代理插件、更新或普通外联。设置保存在本机；代理地址凭据写入系统凭据库。保存后重启 Atlas 后端以重建主模型和辅助模型连接。</p>
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {message && <p className={styles.settingsSuccess} role="status">{message}</p>}
    <form onSubmit={(event) => void save(event)} className="grid gap-4">
      <label className="grid gap-1 text-[12px] text-fg-2">
        模型代理 URL
        <input className={field} autoComplete="off" spellCheck={false} value={proxyUrl} onChange={(event) => setProxyUrl(event.target.value)} placeholder="http://127.0.0.1:7890" disabled={busy} />
        <span className="text-[11px] text-fg-3">
          {settings?.proxy_status === 'configured' ? `当前代理：${settings.proxy_label}。留空保持不变。` : settings?.proxy_status === 'missing' || settings?.proxy_status === 'unavailable' ? '当前代理凭据不可用；请重新填写或勾选清除。' : '支持 http:// 和 https:// 代理地址。地址及其中的凭据不会从 API 返回。'}
        </span>
      </label>
      <label className="flex items-center gap-2 text-[12px] text-fg-2">
        <input type="checkbox" checked={clearProxy} onChange={(event) => setClearProxy(event.target.checked)} disabled={busy || Boolean(proxyUrl.trim())} />
        清除已保存的代理
      </label>
      <label className="grid gap-1 text-[12px] text-fg-2">
        自定义 CA bundle 路径
        <input className={field} autoComplete="off" spellCheck={false} value={caBundlePath} onChange={(event) => setCaBundlePath(event.target.value)} placeholder="留空使用系统证书信任库" disabled={busy} />
        <span className="text-[11px] text-fg-3">路径必须指向不大于 5 MiB、包含有效 PEM 证书的本机文件。留空会移除自定义 CA。</span>
      </label>
      <div>
        <button className={styles.settingsActionSecondary} type="submit" disabled={busy}>{busy ? '保存中…' : '保存模型网络设置'}</button>
      </div>
    </form>
    {settings && <p className="mt-3 text-[11px] leading-relaxed text-fg-3">
      已接入：{settings.supported_transports.join('、')}。{settings.unsupported_transports.join(' 与 ')}未接入；配置启用时使用这些 transport 的模型会被明确拒绝，不会静默绕过代理/CA。
    </p>}
  </section>;
}

