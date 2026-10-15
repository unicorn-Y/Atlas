import { useEffect, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { api } from '../../services/api';
import styles from '../../App.module.css';

type SearchProvider = {
  id: string;
  name: string;
  signup_url: string;
  env_var: string;
  configured: boolean;
  source: 'keyring' | 'env' | null;
  hint: string | null;
};

type SearchSettings = { providers: SearchProvider[]; order: string[] };

type TestResult = {
  ok: boolean;
  error?: string;
  count?: number;
  seconds: number;
  sample?: Array<{ title: string; url: string }>;
};

const ENGINE_LABEL: Record<string, string> = {
  bocha: '博查', tavily: 'Tavily', duckduckgo: 'DuckDuckGo', bing: 'Bing',
};

const NOTES: Record<string, string> = {
  bocha: '国内服务，不走代理也能直连，中文结果好。注册送 1000 次，之后约 3.6 元/千次（预付费）。',
  tavily: '面向 AI 的搜索，英文结果好。每月免费 1000 次，不用绑卡；在国外，优先走系统代理。',
};

export default function SearchSettingsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [settings, setSettings] = useState<SearchSettings | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  const field = 'h-9 w-full rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)] disabled:opacity-60';

  useEffect(() => {
    void api<SearchSettings>(apiBaseUrl, '/api/search-settings')
      .then(setSettings)
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [apiBaseUrl]);

  const run = async (id: string, work: () => Promise<void>) => {
    setBusy(id);
    setError(null);
    setMessage(null);
    try {
      await work();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  const save = (provider: SearchProvider, clear: boolean) => run(provider.id, async () => {
    const body = clear ? { provider: provider.id, clear: true } : { provider: provider.id, api_key: (drafts[provider.id] ?? '').trim() };
    const updated = await api<SearchSettings>(apiBaseUrl, '/api/search-settings', { method: 'PUT', json: body });
    setSettings(updated);
    setDrafts((current) => ({ ...current, [provider.id]: '' }));
    setTests((current) => { const next = { ...current }; delete next[provider.id]; return next; });
    setMessage(clear ? `已清除 ${provider.name} 的 key。` : `${provider.name} 的 key 已保存到系统凭据库，下一次搜索就会用上。`);
  });

  const test = (provider: SearchProvider) => run(`test:${provider.id}`, async () => {
    const result = await api<TestResult>(apiBaseUrl, '/api/search-settings/test', { method: 'POST', json: { provider: provider.id } });
    setTests((current) => ({ ...current, [provider.id]: result }));
  });

  const sourceText = (provider: SearchProvider) => {
    if (!provider.configured) return '未设置';
    const hint = provider.hint ? `（${provider.hint}）` : '';
    return provider.source === 'env' ? `已设置${hint}，来自环境变量 ${provider.env_var}` : `已设置${hint}，存在系统凭据库`;
  };

  return <section className={styles.settingsCard} aria-label="联网搜索设置">
    <div className={styles.settingsCardHeading}><h2>联网搜索</h2></div>
    <p>web_search 按顺序尝试下面的搜索服务，第一个返回结果的生效：
      {' '}{(settings?.order ?? ['bocha', 'tavily', 'duckduckgo', 'bing']).map((id) => ENGINE_LABEL[id] ?? id).join(' → ')}。
      没填 key 的服务会被跳过；DuckDuckGo 和 Bing 不用 key，只是在国内网络下不稳定。key 不会从接口返回。</p>
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {message && <p className={styles.settingsSuccess} role="status">{message}</p>}
    <div className="mt-4 grid gap-4">
      {(settings?.providers ?? []).map((provider) => {
        const draft = drafts[provider.id] ?? '';
        const result = tests[provider.id];
        const disabled = busy !== null;
        return <div key={provider.id} className="grid gap-2 rounded-[12px] p-4 shadow-[inset_0_0_0_1px_var(--line)]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="m-0 text-[13.5px] font-medium text-fg">{provider.name}
              <span className={`ml-2 text-[11.5px] font-normal ${provider.configured ? 'text-ok' : 'text-fg-3'}`}>{sourceText(provider)}</span>
            </p>
            <a href={provider.signup_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[12px] text-brand hover:underline">注册 / 获取 key<ExternalLink size={12} /></a>
          </div>
          <p className="m-0 text-[11.5px] text-fg-3">{NOTES[provider.id]}</p>
          <form className="flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); void save(provider, false); }}>
            <input className={`${field} min-w-[220px] flex-1`} type="password" autoComplete="off" spellCheck={false}
              value={draft} onChange={(event) => setDrafts((current) => ({ ...current, [provider.id]: event.target.value }))}
              placeholder={provider.configured ? '填新 key 可替换，留空不变' : '粘贴 API key'} disabled={disabled} />
            <button className={styles.settingsActionSecondary} type="submit" disabled={disabled || !draft.trim()}>{busy === provider.id ? '保存中…' : '保存'}</button>
            <button className={styles.settingsActionSecondary} type="button" disabled={disabled || !provider.configured} onClick={() => void test(provider)}>{busy === `test:${provider.id}` ? '测试中…' : '测试'}</button>
            {provider.configured && provider.source === 'keyring' && <button className={styles.settingsActionSecondary} type="button" disabled={disabled} onClick={() => void save(provider, true)}>清除</button>}
          </form>
          {result && (result.ok
            ? <div className="text-[12px] text-fg-2">
                <span className="text-ok">可用</span>：{result.seconds} 秒，返回 {result.count} 条
                {(result.sample ?? []).length > 0 && <ul className="m-0 mt-1 pl-4 text-[11.5px] text-fg-3">
                  {(result.sample ?? []).map((item) => <li key={item.url} className="truncate">{item.title} — {item.url}</li>)}
                </ul>}
              </div>
            : <p className="m-0 text-[12px] text-danger">失败（{result.seconds} 秒）：{result.error}</p>)}
        </div>;
      })}
    </div>
  </section>;
}
