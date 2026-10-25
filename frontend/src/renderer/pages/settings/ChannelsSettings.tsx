import { useCallback, useEffect, useState } from 'react';
import { LoaderCircle, Radio, RefreshCw, Save } from 'lucide-react';
import { channelsApi, type ChannelStatusRow } from '../../services/persistentApi';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import { field } from '../agents/shared';

/** 渠道字段的显隐表：secret 字段走系统凭据库（POST /credential），其余走 PUT /accounts。 */
interface ChannelField { key: string; label: string; secret?: boolean; placeholder?: string }
const CHANNEL_FIELDS: Record<string, ChannelField[]> = {
  telegram: [{ key: 'bot_token', label: '机器人密钥', secret: true, placeholder: '123456:ABC-DEF…' }],
  slack: [
    { key: 'bot_token', label: 'Bot Token（xoxb…）', secret: true },
    { key: 'app_token', label: 'App Token（Socket Mode）', secret: true },
  ],
  webhook: [{ key: 'secret', label: 'HMAC 签名密钥', secret: true }],
  email: [
    { key: 'account', label: '邮箱地址', placeholder: 'me@example.com' },
    { key: 'host', label: 'IMAP 服务器', placeholder: 'imap.example.com' },
    { key: 'user', label: '登录名' },
    { key: 'password', label: '密码 / 授权码', secret: true },
    { key: 'smtp_host', label: 'SMTP 服务器（可选）' },
  ],
};

type ChannelPolicy = {
  dm_policy: 'disabled' | 'pairing' | 'open' | 'allowlist';
  dm_allowlist: string[];
  allow_when_empty: boolean;
  group_policy: 'disabled' | 'open' | 'allowlist';
  group_allowlist: string[];
  require_mention: boolean;
};
type ChannelStatusWithPolicy = ChannelStatusRow & { policy?: ChannelPolicy };
type ChannelPolicyPatch = Partial<ChannelPolicy>;
const DEFAULT_CHANNEL_POLICY: ChannelPolicy = {
  dm_policy: 'open', dm_allowlist: ['*'], allow_when_empty: true,
  group_policy: 'open', group_allowlist: [], require_mention: false,
};
function cloneChannelPolicy(policy?: ChannelPolicy): ChannelPolicy {
  return { ...DEFAULT_CHANNEL_POLICY, ...policy,
    dm_allowlist: [...(policy?.dm_allowlist ?? DEFAULT_CHANNEL_POLICY.dm_allowlist)],
    group_allowlist: [...(policy?.group_allowlist ?? DEFAULT_CHANNEL_POLICY.group_allowlist)],
  };
}
/** 设置 → 渠道与 Gateway：网关状态 / 各渠道账号与凭据 / 测试发送。 */
export default function ChannelsSettings({ apiBaseUrl, onToast }: { apiBaseUrl: string; onToast: (text: string) => void }) {
  const [rows, setRows] = useState<ChannelStatusRow[]>([]);
  const [dispatcher, setDispatcher] = useState<boolean | null>(null);
  const [degraded, setDegraded] = useState('');
  const [loading, setLoading] = useState(true);
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  const [policies, setPolicies] = useState<Record<string, ChannelPolicy>>({});
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [busyChannel, setBusyChannel] = useState('');
  const [test, setTest] = useState({ channel: '', chatId: '', text: 'Atlas 测试消息' });
  const [sessionLinks, setSessionLinks] = useState<Array<{ session_key: string; conversation_id: string; linked_by: string; created_at: string }>>([]);
  const [linkDraft, setLinkDraft] = useState({ agent_id: 'main', channel: 'telegram', account: '', peer: '', conversation_id: '' });

  const reloadSessionLinks = useCallback(async () => {
    try {
      const result = await api<{ links: typeof sessionLinks }>(apiBaseUrl, '/api/channels/session-links');
      setSessionLinks(result.links);
    } catch { setSessionLinks([]); }
  }, [apiBaseUrl]);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const status = await channelsApi.status(apiBaseUrl) as { channels: ChannelStatusWithPolicy[]; dispatcher_connected?: boolean };
      setRows(status.channels);
      setPolicies((current) => {
        const next = { ...current };
        for (const row of status.channels) next[row.name] ??= cloneChannelPolicy(row.policy);
        return next;
      });
      setDispatcher(status.dispatcher_connected ?? null);
      setDegraded('');
      setEnabled((current) => ({ ...Object.fromEntries(status.channels.map((row) => [row.name, row.enabled])), ...current }));
      await reloadSessionLinks();
    } catch (error) {
      setRows([]); setDegraded(error instanceof Error ? error.message : String(error));
    }
    setLoading(false);
  }, [apiBaseUrl, reloadSessionLinks]);
  useEffect(() => { void reload(); }, [reload]);

  const enabledRows = rows.filter((row) => row.enabled);
  useEffect(() => {
    if (enabledRows.some((row) => row.name === test.channel)) return;
    setTest((current) => ({ ...current, channel: enabledRows[0]?.name ?? '' }));
  }, [rows, test.channel]);

  const saveChannel = async (name: string) => {
    setBusyChannel(name);
    let backendChanged = false;
    try {
      const fields = CHANNEL_FIELDS[name] ?? [];
      const wasEnabled = rowFor(name)?.enabled ?? false;
      const willEnable = enabled[name] ?? false;
      const config: Record<string, unknown> = { enabled: enabled[name] ?? false };
      let credentialsChanged = false;
      let channelRestarted = false;
      if (!willEnable) {
        await channelsApi.putAccounts(apiBaseUrl, { [name]: config });
        backendChanged = true;
      }
      for (const spec of fields) {
        const value = (values[name]?.[spec.key] ?? '').trim();
        if (!value) continue;
        if (spec.secret) {
          const result = await channelsApi.setCredential(apiBaseUrl, name, spec.key, value) as { ok: boolean; set: boolean; restarted?: boolean };
          backendChanged = true;
          credentialsChanged = true;
          channelRestarted = channelRestarted || result.restarted === true;
        } else config[spec.key] = value;
      }
      if (willEnable) {
        await channelsApi.putAccounts(apiBaseUrl, { [name]: config });
        backendChanged = true;
      }
      setValues((current) => ({ ...current, [name]: {} }));
      await reload();
      if (!credentialsChanged) onToast(`${name} 设置已保存，状态已刷新`);
      else if (channelRestarted) onToast(`${name} 凭据已保存，已触发渠道重连；连接结果见 Gateway 状态`);
      else if (!wasEnabled && willEnable) onToast(`${name} 凭据已保存并提交启用；Gateway 状态已刷新`);
      else if (!willEnable) onToast(`${name} 凭据已保存；渠道未启用，启用时会读取新凭据`);
      else onToast(`${name} 凭据已保存；Gateway 未在线重连，新凭据会在下次启动时读取`);
    } catch (error) {
      if (backendChanged) await reload();
      onToast(error instanceof Error ? error.message : String(error));
    }
    setBusyChannel('');
  };

  const clearCredential = async (name: string, key: string) => {
    setBusyChannel(name);
    try {
      const result = await channelsApi.setCredential(apiBaseUrl, name, key, '') as { ok: boolean; set: boolean; restarted?: boolean };
      setValue(name, key, '');
      await reload();
      onToast(result.restarted
        ? `${name} 的 ${key} 已从系统凭据库清除并触发渠道重连；环境变量仍可能提供回退凭据`
        : `${name} 的 ${key} 已从系统凭据库清除；未在线重连，环境变量仍可能提供回退凭据`);
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setBusyChannel('');
  };

  const sendTest = async () => {
    if (!test.channel) { onToast('没有已启用的渠道可发送测试消息'); return; }
    if (!test.chatId.trim()) { onToast('先填目标 chat id'); return; }
    setBusyChannel('__test');
    try {
      await channelsApi.sendTest(apiBaseUrl, test.channel, test.chatId.trim(), test.text);
      onToast('测试消息已进投递队列');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setBusyChannel('');
  };

  const policyFor = (name: string) => policies[name] ?? cloneChannelPolicy();
  const updatePolicy = (name: string, patch: ChannelPolicyPatch) => setPolicies((current) => ({
    ...current, [name]: { ...cloneChannelPolicy(current[name]), ...patch },
  }));
  const parseAllowlist = (value: string) => [...new Set(value.split(/\r?\n/).map((entry) => entry.trim()).filter(Boolean))];
  const savePolicy = async (name: string) => {
    setBusyChannel(name);
    try {
      const saved = await api<{ ok: boolean; channel: string; policy: ChannelPolicy }>(apiBaseUrl, `/api/channels/${encodeURIComponent(name)}/policy`, {
        method: 'PUT', json: policyFor(name),
      });
      setPolicies((current) => ({ ...current, [name]: cloneChannelPolicy(saved.policy) }));
      onToast(`${name} 消息访问策略已保存并应用`);
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setBusyChannel('');
  };
  const rowFor = (name: string) => rows.find((row) => row.name === name);
  const setValue = (name: string, key: string, value: string) =>
    setValues((current) => ({ ...current, [name]: { ...current[name], [key]: value } }));

  const linkSession = async () => {
    try {
      await api(apiBaseUrl, '/api/channels/session-links', { method: 'PUT', json: linkDraft });
      setLinkDraft((current) => ({ ...current, peer: '', conversation_id: '' }));
      await reloadSessionLinks();
      onToast('渠道身份已绑定到既有会话');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
  };
  const unlinkSession = async (key: string) => {
    try {
      await api(apiBaseUrl, `/api/channels/session-links?session_key=${encodeURIComponent(key)}`, { method: 'DELETE' });
      await reloadSessionLinks();
      onToast('渠道会话绑定已解除');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
  };

  return <div className="grid max-w-[680px] gap-5 text-[13px] text-fg-2">
    <section aria-label="Gateway 状态" className="rounded-xl bg-sunken px-4 py-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
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

    {rows.map(({ name }) => {
      const fields = CHANNEL_FIELDS[name] ?? [];
      const status = rowFor(name);
      const policy = policyFor(name);
      return <section key={name} aria-label={`${name} 渠道配置`} className="rounded-xl px-4 py-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
        <header className="flex items-center gap-2.5">
          <b className="font-medium text-fg">{name}</b>
          {status && <span className={cn('rounded-full px-2 py-0.5 text-[11px]', status.running ? 'bg-ok-soft text-fg' : 'bg-sunken text-fg-3')}>{status.running ? '运行中' : '未运行'}</span>}
          <span className="flex-1" />
          <label className="flex items-center gap-1.5 text-[12.5px]">
            <input type="checkbox" checked={enabled[name] ?? false} onChange={(event) => setEnabled((current) => ({ ...current, [name]: event.target.checked }))} />启用
          </label>
        </header>
        <div className="mt-2.5 grid gap-2">
          {fields.map((spec) => <div key={spec.key} className="grid gap-1 text-[12.5px] text-fg-2">
            <label htmlFor={`${name}-${spec.key}`}>
              {spec.label}{spec.secret && <small className="ml-1.5 text-fg-3">保存在系统凭据库，不会回显</small>}
            </label>
            <div className="flex gap-2">
              <input id={`${name}-${spec.key}`} type={spec.secret ? 'password' : 'text'} autoComplete="new-password" value={values[name]?.[spec.key] ?? ''}
                onChange={(event) => setValue(name, spec.key, event.target.value)} placeholder={spec.placeholder}
                className={cn(field, 'min-w-0 flex-1 font-mono text-[12.5px]')} />
              {spec.secret && <Button size="sm" variant="ghost" disabled={busyChannel === name} onClick={() => void clearCredential(name, spec.key)}>清除</Button>}
            </div>
          </div>)}
          {!fields.length && <p className="m-0 text-[12px] text-fg-3">这个渠道没有额外配置，直接启用即可。</p>}
        </div>
        <div className="mt-2.5 flex justify-end">
          <Button size="sm" variant="secondary" disabled={busyChannel === name} onClick={() => void saveChannel(name)}><Save size={13} />保存 {name}</Button>
        </div>
        <div className="mt-4 border-t border-line pt-3">
          <div className="flex items-center gap-2"><b className="font-medium text-fg">消息访问策略</b><span className="flex-1" /><Button type="button" size="sm" variant="secondary" disabled={busyChannel === name} onClick={() => void savePolicy(name)}><Save size={13} />保存策略</Button></div>
          <div className="mt-2.5 grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-[12.5px] text-fg-2">私聊策略
              <select value={policy.dm_policy} onChange={(event) => updatePolicy(name, { dm_policy: event.target.value as ChannelPolicy['dm_policy'] })} className={field}>
                <option value="disabled">禁用</option><option value="open">开放（仍检查允许名单）</option><option value="allowlist">仅允许名单</option><option value="pairing">配对门控（当前仅检查允许名单）</option>
              </select>
            </label>
            <label className="grid gap-1 text-[12.5px] text-fg-2">私聊允许发送者 ID（每行一项；* 匹配所有人）
              <textarea rows={3} value={policy.dm_allowlist.join('\n')} onChange={(event) => updatePolicy(name, { dm_allowlist: parseAllowlist(event.target.value) })} className={cn(field, 'w-full resize-y font-mono text-[12px]')} />
            </label>
            <label className="flex items-start gap-2 text-[12.5px] text-fg-2"><input type="checkbox" checked={policy.allow_when_empty} onChange={(event) => updatePolicy(name, { allow_when_empty: event.target.checked })} />空私聊允许名单时放行（仅影响开放 / 仅名单策略）</label>
            <label className="grid gap-1 text-[12.5px] text-fg-2">群消息策略
              <select value={policy.group_policy} onChange={(event) => updatePolicy(name, { group_policy: event.target.value as ChannelPolicy['group_policy'] })} className={field}>
                <option value="disabled">禁用</option><option value="open">开放</option><option value="allowlist">仅允许名单</option>
              </select>
            </label>
            <label className="grid gap-1 text-[12.5px] text-fg-2">群消息允许发送者 ID（每行一项；* 匹配所有人）
              <textarea rows={3} value={policy.group_allowlist.join('\n')} onChange={(event) => updatePolicy(name, { group_allowlist: parseAllowlist(event.target.value) })} className={cn(field, 'w-full resize-y font-mono text-[12px]')} />
            </label>
            <label className="flex items-start gap-2 text-[12.5px] text-fg-2"><input type="checkbox" checked={policy.require_mention} onChange={(event) => updatePolicy(name, { require_mention: event.target.checked })} />群消息要求提及或回复事件</label>
          </div>
          <p className="mb-0 mt-2 text-[11.5px] leading-[1.55] text-fg-3">群策略设为“仅允许名单”且群名单为空时，运行时回退到私聊允许名单；两者都空时，现有运行时会放行。提及检查使用事件的 is_mention 或 reply_to_event_id。配对门控目前没有自动申请 / 批准流程。</p>
        </div>
      </section>;
    })}

    <section aria-label="跨渠道会话绑定" className="rounded-xl px-4 py-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
      <b className="font-medium text-fg">跨渠道会话延续</b>
      <p className="mb-3 mt-1 text-[12px] text-fg-3">将一个渠道账号中的 chat id 显式接到既有会话。绑定按渠道、账号、chat id 和 Agent 唯一；已有不同会话的身份必须先解除绑定。这里不合并消息记录。</p>
      <div className="grid gap-2 md:grid-cols-2">
        <label className="grid gap-1">Agent ID<input className={field} value={linkDraft.agent_id} onChange={(event) => setLinkDraft({ ...linkDraft, agent_id: event.target.value })} /></label>
        <label className="grid gap-1">渠道<select className={field} value={linkDraft.channel} onChange={(event) => setLinkDraft({ ...linkDraft, channel: event.target.value })}>{rows.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}</select></label>
        <label className="grid gap-1">账号标签（可空）<input className={field} value={linkDraft.account} onChange={(event) => setLinkDraft({ ...linkDraft, account: event.target.value })} /></label>
        <label className="grid gap-1">chat id / peer<input className={field} value={linkDraft.peer} onChange={(event) => setLinkDraft({ ...linkDraft, peer: event.target.value })} /></label>
        <label className="grid gap-1 md:col-span-2">既有会话 ID<input className={field} value={linkDraft.conversation_id} onChange={(event) => setLinkDraft({ ...linkDraft, conversation_id: event.target.value })} /></label>
      </div>
      <div className="mt-2 flex justify-end"><Button size="sm" variant="secondary" disabled={!linkDraft.peer.trim() || !linkDraft.conversation_id.trim()} onClick={() => void linkSession()}>绑定既有会话</Button></div>
      <div className="mt-2 grid gap-1">{sessionLinks.map((item) => <div key={item.session_key} className="flex items-center gap-2 rounded-lg bg-sunken px-2.5 py-2 text-[11px]"><code className="min-w-0 flex-1 truncate">{item.session_key} → {item.conversation_id}</code><Button size="sm" variant="ghost" onClick={() => void unlinkSession(item.session_key)}>解除</Button></div>)}{!sessionLinks.length && <span className="text-[11px] text-fg-3">尚无显式绑定</span>}</div>
    </section>

    <section aria-label="测试发送" className="rounded-xl px-4 py-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
      <b className="font-medium text-fg">测试发送</b>
      <p className="mb-2 mt-1 text-[12px] text-fg-3">走正式投递队列发一条，验证凭据和目标都对。</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-[12.5px] text-fg-2">渠道
          <select value={test.channel} onChange={(event) => setTest({ ...test, channel: event.target.value })} className={cn(field, 'w-32')}>
            {!enabledRows.length && <option value="">暂无已启用渠道</option>}
            {enabledRows.map((row) => <option key={row.name} value={row.name}>{row.name}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-[12.5px] text-fg-2">目标 chat id
          <input value={test.chatId} onChange={(event) => setTest({ ...test, chatId: event.target.value })} className={cn(field, 'w-40 font-mono text-[12.5px]')} />
        </label>
        <label className="grid min-w-[160px] flex-1 gap-1 text-[12.5px] text-fg-2">内容
          <input value={test.text} onChange={(event) => setTest({ ...test, text: event.target.value })} className={field} />
        </label>
        <Button variant="secondary" disabled={busyChannel === '__test' || !enabledRows.length} onClick={() => void sendTest()}>发送测试</Button>
      </div>
    </section>
  </div>;
}
