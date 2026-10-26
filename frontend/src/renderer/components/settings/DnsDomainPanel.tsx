import { useState } from 'react';
import { api } from '../../services/api';

type DomainSettings = { domain: string; target: string; record_type: 'A' | 'AAAA' | 'CNAME'; provider: 'manual' | 'cloudflare' | 'route53' };
type RecordPlan = { domain: string; provider: string; record: { type: string; name: string; value: string; ttl: number; proxy?: string | null }; status: string; note: string };
type DomainCheck = { status: string; dns: { ok: boolean; addresses: string[]; expected: string; matches_expected: boolean | null; error: string | null }; tls: { ok: boolean; version?: string; expires_at?: string; error?: string }; record_plan: RecordPlan['record'] };

function initialSettings(): DomainSettings {
  try {
    const parsed = JSON.parse(localStorage.getItem('atlas.dns-domain-settings') ?? '{}') as Partial<DomainSettings>;
    return { domain: parsed.domain ?? '', target: parsed.target ?? '', record_type: ['A', 'AAAA', 'CNAME'].includes(parsed.record_type ?? '') ? parsed.record_type as DomainSettings['record_type'] : 'A', provider: ['manual', 'cloudflare', 'route53'].includes(parsed.provider ?? '') ? parsed.provider as DomainSettings['provider'] : 'manual' };
  } catch { return { domain: '', target: '', record_type: 'A', provider: 'manual' }; }
}

export default function DnsDomainPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [settings, setSettings] = useState(initialSettings);
  const [plan, setPlan] = useState<RecordPlan | null>(null);
  const [check, setCheck] = useState<DomainCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const update = (key: keyof DomainSettings, value: string) => setSettings((current) => {
    const next = { ...current, [key]: value } as DomainSettings;
    localStorage.setItem('atlas.dns-domain-settings', JSON.stringify(next));
    return next;
  });
  const payload = () => ({ ...settings, domain: settings.domain.trim(), target: settings.target.trim() });
  const run = async (action: 'plan' | 'verify') => {
    setBusy(true); setError('');
    try {
      if (action === 'plan') { setPlan(await api<RecordPlan>(apiBaseUrl, '/api/dns/plan', { method: 'POST', json: payload() })); setCheck(null); }
      else { setCheck(await api<DomainCheck>(apiBaseUrl, '/api/dns/verify', { method: 'POST', json: payload() })); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };
  return <article className="grid gap-3 rounded-xl border border-line p-4" aria-label="DNS 与自定义域名">
    <div><h3 className="m-0 text-[13.5px] font-medium text-heading">DNS 与自定义域名</h3><p className="mb-0 mt-1 text-[12px] leading-relaxed text-fg-3">生成待执行记录，并检查公开 DNS 解析和 HTTPS 证书。Atlas 只读验证，不会替你更改 DNS。</p></div>
    <div className="grid gap-2 sm:grid-cols-2">
      <label className="grid gap-1 text-[11px] text-fg-3">域名<input aria-label="自定义域名" value={settings.domain} onChange={(event) => update('domain', event.target.value)} placeholder="atlas.example.com" className="rounded-lg border border-line bg-sunken px-3 py-2 text-[12px] text-fg" /></label>
      <label className="grid gap-1 text-[11px] text-fg-3">目标地址<input aria-label="DNS 目标地址" value={settings.target} onChange={(event) => update('target', event.target.value)} placeholder="203.0.113.10 或 gateway.example.net" className="rounded-lg border border-line bg-sunken px-3 py-2 text-[12px] text-fg" /></label>
      <label className="grid gap-1 text-[11px] text-fg-3">记录类型<select aria-label="DNS 记录类型" value={settings.record_type} onChange={(event) => update('record_type', event.target.value)} className="rounded-lg border border-line bg-sunken px-3 py-2 text-[12px] text-fg"><option>A</option><option>AAAA</option><option>CNAME</option></select></label>
      <label className="grid gap-1 text-[11px] text-fg-3">DNS 服务商<select aria-label="DNS 服务商" value={settings.provider} onChange={(event) => update('provider', event.target.value)} className="rounded-lg border border-line bg-sunken px-3 py-2 text-[12px] text-fg"><option value="manual">手动配置</option><option value="cloudflare">Cloudflare</option><option value="route53">Amazon Route 53</option></select></label>
    </div>
    <div className="flex flex-wrap gap-2"><button type="button" disabled={busy} onClick={() => void run('plan')} className="rounded-lg border border-line px-3 py-1.5 text-[11px] hover:bg-hover disabled:opacity-50">{busy ? '处理中…' : '生成待执行 DNS 记录'}</button><button type="button" disabled={busy} onClick={() => void run('verify')} className="rounded-lg border border-line px-3 py-1.5 text-[11px] hover:bg-hover disabled:opacity-50">检查 DNS 与 TLS</button></div>
    {error && <p role="alert" className="m-0 text-[11px] text-danger">{error}</p>}
    {plan && <div className="grid gap-1 rounded-lg bg-sunken p-3 text-[11px]" role="status"><strong>{plan.record.type} {plan.record.name} → {plan.record.value} (TTL {plan.record.ttl})</strong>{plan.record.proxy && <span>Cloudflare 代理：{plan.record.proxy}</span>}<span>{plan.note}</span></div>}
    {check && <div className="grid gap-1 rounded-lg bg-sunken p-3 text-[11px]" role="status"><strong>状态：{check.status === 'healthy' ? 'DNS 与 TLS 正常' : '需要处理'}</strong><span>解析：{check.dns.ok ? check.dns.addresses.join(', ') : `失败：${check.dns.error ?? '没有解析记录'}`}{check.dns.matches_expected === false ? `（与目标 ${check.dns.expected} 不符）` : ''}</span><span>TLS：{check.tls.ok ? `${check.tls.version}，证书到期 ${check.tls.expires_at ?? '未知'}` : `失败：${check.tls.error}`}</span><span>待执行记录：{check.record_plan.type} {check.record_plan.name} → {check.record_plan.value}</span></div>}
  </article>;
}
