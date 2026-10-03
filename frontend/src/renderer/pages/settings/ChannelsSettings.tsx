import { useCallback, useEffect, useMemo, useState } from 'react';
import { LoaderCircle, Radio, RefreshCw, Save } from 'lucide-react';
import { channelsApi, type ChannelStatusRow } from '../../services/persistentApi';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import { field } from '../agents/shared';

/** 渠道字段的显隐表：secret 字段走系统凭据库（POST /credential），其余走 PUT /accounts。 */
interface ChannelField { key: string; label: string; secret?: boolean; placeholder?: string }
const CHANNEL_FIELDS: Record<string, ChannelField[]> = {
  telegram: [{ key: 'bot_token', label: '机器人密钥', secret: true, placeholder: '123456:ABC-DEF…' }],
  slack: [
    { key: 'bot_token', label: 'Bot Token（xoxb…）', secret: true },
    { key: 'app_token', label: 'App Token（xapp…）', secret: true },
    { key: 'bot_user_id', label: 'Bot User ID（可选）', secret: true },
  ],
  webhook: [{ key: 'secret', label: 'HMAC 签名密钥', secret: true }],
  email: [
    { key: 'account', label: '邮箱地址', placeholder: 'me@example.com' },
    { key: 'host', label: 'IMAP 服务器', placeholder: 'imap.example.com' },
    { key: 'user', label: '登录名' },
    { key: 'password', label: '密码 / 授权码', secret: true },
    { key: 'smtp_host', label: 'SMTP 服务器（可选）' },
  ],
  feishu: [
    { key: 'app_id', label: 'App ID', secret: true },
    { key: 'app_secret', label: 'App Secret', secret: true },
  ],
  dingtalk: [
    { key: 'client_id', label: 'Client ID', secret: true },
    { key: 'client_secret', label: 'Client Secret', secret: true },
  ],
  wecom: [
    { key: 'token', label: 'Token', secret: true },
    { key: 'encoding_aes_key', label: 'Encoding AES Key', secret: true },
  ],
};
const ALL_CHANNELS = ['telegram', 'slack', 'feishu', 'dingtalk', 'wecom', 'email', 'webhook'];

/** 设置 → 渠道与 Gateway：网关状态 / 各渠道账号与凭据 / 测试发送。 */
export default function ChannelsSettings({ apiBaseUrl, onToast }: { apiBaseUrl: string; onToast: (text: string) => void }) {
  const [rows, setRows] = useState<ChannelStatusRow[]>([]);
  const [dispatcher, setDispatcher] = useState<boolean | null>(null);
  const [degraded, setDegraded] = useState('');
  const [loading, setLoading] = useState(true);
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [busyChannel, setBusyChannel] = useState('');
  const [test, setTest] = useState({ channel: 'telegram', chatId: '', text: 'Atlas 测试消息' });

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const status = await channelsApi.status(apiBaseUrl);
      setRows(status.channels);
      setDispatcher(status.dispatcher_connected ?? null);
      setDegraded('');
      setEnabled((current) => ({ ...Object.fromEntries(status.channels.map((row) => [row.name, row.enabled])), ...current }));
    } catch (error) {
      setRows([]); setDegraded(error instanceof Error ? error.message : String(error));
    }
    setLoading(false);
  }, [apiBaseUrl]);
  useEffect(() => { void reload(); }, [reload]);

  const channelNames = useMemo(() => {
    const known = new Set(rows.map((row) => row.name));
    return [...ALL_CHANNELS.filter((name) => !known.has(name)), ...rows.map((row) => row.name)];
  }, [rows]);

  const saveChannel = async (name: string) => {
    setBusyChannel(name);
    try {
      const fields = CHANNEL_FIELDS[name] ?? [];
      const config: Record<string, unknown> = { enabled: enabled[name] ?? false };
      for (const spec of fields) {
        const value = (values[name]?.[spec.key] ?? '').trim();
        if (!value) continue;
        if (spec.secret) await channelsApi.setCredential(apiBaseUrl, name, spec.key, value);
        else config[spec.key] = value;
      }
      await channelsApi.putAccounts(apiBaseUrl, { [name]: config });
      setValues((current) => ({ ...current, [name]: {} }));
      onToast(`${name} 已保存（密钥进了系统凭据库）`);
      await reload();
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setBusyChannel('');
  };

  const sendTest = async () => {
    if (!test.chatId.trim()) { onToast('先填目标 chat id'); return; }
    setBusyChannel('__test');
    try {
      await channelsApi.sendTest(apiBaseUrl, test.channel, test.chatId.trim(), test.text);
      onToast('测试消息已进投递队列');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setBusyChannel('');
  };

  const rowFor = (name: string) => rows.find((row) => row.name === name);
  const setValue = (name: string, key: string, value: string) =>
    setValues((current) => ({ ...current, [name]: { ...current[name], [key]: value } }));

  return <div className="grid max-w-[680px] gap-5 text-[13px] text-fg-2">
    <section aria-label="Gateway 状态" className="rounded-[14px] bg-sunken px-4 py-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
      <header className="flex items-center gap-2.5">
        <Radio size={16} className="text-brand" />
        <b className="font-medium text-fg">渠道 Gateway</b>
        <span className="flex-1" />
        <Button size="icon-sm" variant="ghost" aria-label="刷新状态" onClick={() => void reload()}>{loading ? <LoaderCircle className="spin" /> : <RefreshCw />}</Button>
      </header>
      {degraded
        ? <p className="mb-0 mt-2 text-[12.5px] text-danger">网关没有就绪：{degraded}</p>
        : <p className="mb-0 mt-1.5 text-[12.5px] text-fg-3">
          分发器{dispatcher ? '已连接' : '未连接'}；收到的消息先进持久队列再交给绑定的 Agent（绑定在 Agents → Channels 里配）。
        </p>}
      <div className="mt-2.5 grid gap-1">
        {rows.map((row) => <div key={row.name} className="flex items-center gap-2.5 text-[12.5px]">
          <i className={cn('size-1.5 shrink-0 rounded-full', row.running ? 'bg-ok' : row.enabled ? 'bg-brand' : 'bg-current opacity-40')} />
          <b className="w-20 shrink-0 font-medium text-fg">{row.name}</b>
          <span className="min-w-0 flex-1 truncate text-fg-3">
            {row.running ? '运行中' : row.enabled ? '已配置未运行' : '未启用'}
            {row.paused ? ' · 已暂停' : ''}{row.last_error ? ` · ${row.last_error}` : ''}
          </span>
          {row.counts && <span className="shrink-0 tabular-nums text-fg-3">收 {row.counts.received ?? 0} / 发 {row.counts.delivered ?? 0}{row.counts.dropped ? ` / 丢 ${row.counts.dropped}` : ''}</span>}
        </div>)}
      </div>
    </section>

    {channelNames.map((name) => {
      const fields = CHANNEL_FIELDS[name] ?? [];
      const status = rowFor(name);
      return <section key={name} aria-label={`${name} 渠道配置`} className="rounded-[14px] px-4 py-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
        <header className="flex items-center gap-2.5">
          <b className="font-medium text-fg">{name}</b>
          {status && <span className={cn('rounded-full px-2 py-0.5 text-[11px]', status.running ? 'bg-ok-soft text-fg' : 'bg-sunken text-fg-3')}>{status.running ? '运行中' : '未运行'}</span>}
          <span className="flex-1" />
          <label className="flex items-center gap-1.5 text-[12.5px]">
            <input type="checkbox" checked={enabled[name] ?? false} onChange={(event) => setEnabled((current) => ({ ...current, [name]: event.target.checked }))} />启用
          </label>
        </header>
        <div className="mt-2.5 grid gap-2">
          {fields.map((spec) => <label key={spec.key} className="grid gap-1 text-[12.5px] text-fg-2">
            {spec.label}{spec.secret && <small className="text-fg-3">保存在系统凭据库，不会回显</small>}
            <input type={spec.secret ? 'password' : 'text'} autoComplete="new-password" value={values[name]?.[spec.key] ?? ''}
              onChange={(event) => setValue(name, spec.key, event.target.value)} placeholder={spec.placeholder}
              className={cn(field, 'font-mono text-[12.5px]')} />
          </label>)}
          {!fields.length && <p className="m-0 text-[12px] text-fg-3">这个渠道没有额外配置，直接启用即可。</p>}
        </div>
        <div className="mt-2.5 flex justify-end">
          <Button size="sm" variant="secondary" disabled={busyChannel === name} onClick={() => void saveChannel(name)}><Save size={13} />保存 {name}</Button>
        </div>
      </section>;
    })}

    <section aria-label="测试发送" className="rounded-[14px] px-4 py-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
      <b className="font-medium text-fg">测试发送</b>
      <p className="mb-2 mt-1 text-[12px] text-fg-3">走正式投递队列发一条，验证凭据和目标都对。</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-[12.5px] text-fg-2">渠道
          <select value={test.channel} onChange={(event) => setTest({ ...test, channel: event.target.value })} className={cn(field, 'w-32')}>
            {rows.filter((row) => row.enabled).map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}
            {!rows.some((row) => row.enabled) && <option value="telegram">telegram</option>}
          </select>
        </label>
        <label className="grid gap-1 text-[12.5px] text-fg-2">目标 chat id
          <input value={test.chatId} onChange={(event) => setTest({ ...test, chatId: event.target.value })} className={cn(field, 'w-40 font-mono text-[12.5px]')} />
        </label>
        <label className="grid min-w-[160px] flex-1 gap-1 text-[12.5px] text-fg-2">内容
          <input value={test.text} onChange={(event) => setTest({ ...test, text: event.target.value })} className={field} />
        </label>
        <Button variant="secondary" disabled={busyChannel === '__test'} onClick={() => void sendTest()}>发送测试</Button>
      </div>
    </section>
  </div>;
}
