import { useEffect, useState } from 'react';
import { FolderOpen, Radio } from 'lucide-react';
import type { TelegramSettings } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';

const NOTIFY: Record<TelegramSettings['notify_on'][number], string> = { completed: '任务完成', failed: '任务失败', approval: '需要你确认' };

/** Send Atlas tasks from the phone through your own Telegram bot; only the listed accounts are served. */
export default function TelegramPanel() {
  const [settings, setSettings] = useState<TelegramSettings | null>(null);
  const [token, setToken] = useState('');
  const [ids, setIds] = useState('');
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const fail = (exc: unknown) => setMessage({ ok: false, text: exc instanceof Error ? exc.message : String(exc) });
  useEffect(() => {
    backend.getTelegram().then((value) => { setSettings(value); setIds(value.allowed_user_ids.join(', ')); }).catch(fail);
  }, []);
  if (!settings) return <p className="text-[13px] text-fg-3">{message?.text ?? '正在读取…'}</p>;

  const save = async (patch: Parameters<typeof backend.saveTelegram>[0], note = '已保存') => {
    try { const next = await backend.saveTelegram(patch); setSettings(next); setIds(next.allowed_user_ids.join(', ')); setMessage({ ok: true, text: note }); return true; }
    catch (exc) { fail(exc); return false; }
  };
  const parsedIds = ids.split(/[\s,，]+/).filter(Boolean).map(Number);
  const idsValid = parsedIds.every((value) => Number.isInteger(value) && value > 0);
  const pickFolder = async () => {
    const picked = window.atlasDesktop?.selectDirectory
      ? await window.atlasDesktop.selectDirectory(settings.default_workspace || undefined)
      : window.prompt('手机发来的任务在哪个目录里运行（完整路径）', settings.default_workspace)?.trim() || null;
    if (picked) void save({ default_workspace: picked });
  };
  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  const ready = settings.bot_token_set && settings.allowed_user_ids.length > 0 && Boolean(settings.default_workspace);

  return <div className="grid max-w-[620px] gap-4 text-[13px] text-fg-2">
    <ol className="m-0 grid list-decimal gap-1 pl-5 text-[12.5px] leading-[1.7] text-fg-3">
      <li>在 Telegram 里找 <b className="font-medium text-fg-2">@BotFather</b>，发 /newbot 建一个自己的机器人，拿到密钥。</li>
      <li>找 <b className="font-medium text-fg-2">@userinfobot</b> 查到你自己的数字 ID，填到下面「允许的账号」。</li>
      <li>之后给你的机器人发文字就是布置任务；/list 看最近任务，/status 看正在跑的，/stop 停止。</li>
    </ol>
    <label className="grid gap-1">机器人密钥 {settings.bot_token_set && <small className="text-ok">已保存（不会显示出来）</small>}
      <div className="flex gap-2">
        <input type="password" autoComplete="new-password" value={token} onChange={(event) => setToken(event.target.value)} placeholder={settings.bot_token_set ? '要换新密钥才填' : '123456:ABC-DEF…'} className={cn(field, 'min-w-0 flex-1 font-mono text-[12.5px]')} />
        <Button disabled={!token.trim()} onClick={() => { void save({ bot_token: token.trim() }, '密钥已保存到系统凭据库').then((ok) => { if (ok) setToken(''); }); }}>保存</Button>
        <Button disabled={!settings.bot_token_set} onClick={() => { backend.testTelegram().then((result) => setMessage({ ok: true, text: `连上了：@${result.username}` })).catch(fail); }}><Radio />测试</Button>
      </div>
    </label>
    <label className="grid gap-1">允许的账号（Telegram 数字 ID，多个用逗号隔开；其他人发的消息一律忽略）
      <div className="flex gap-2">
        <input value={ids} onChange={(event) => setIds(event.target.value)} placeholder="123456789" className={cn(field, 'min-w-0 flex-1 font-mono text-[12.5px]', !idsValid && 'shadow-[inset_0_0_0_1px_var(--danger)]')} />
        <Button disabled={!idsValid} onClick={() => void save({ allowed_user_ids: parsedIds })}>保存</Button>
      </div>
    </label>
    <div className="grid gap-1">手机发来的任务在哪个目录里运行
      <button onClick={() => void pickFolder()} className="flex items-center gap-2 rounded-[9px] bg-sunken px-3 py-2 text-left text-fg shadow-[inset_0_0_0_1px_var(--line)] hover:brightness-105">
        <FolderOpen size={15} className="shrink-0 text-brand" /><span className="min-w-0 truncate">{settings.default_workspace || '选择文件夹…'}</span>
      </button>
      <small className="text-[12px] text-fg-3">这些任务默认是「改前问我」：要改文件或运行命令时，机器人会发「允许 / 拒绝」按钮给你。</small>
    </div>
    <div className="grid gap-1.5">什么时候通知你
      <div className="flex gap-4">{(Object.keys(NOTIFY) as Array<keyof typeof NOTIFY>).map((key) => <label key={key} className="flex items-center gap-2">
        <input type="checkbox" checked={settings.notify_on.includes(key)}
          onChange={(event) => void save({ notify_on: event.target.checked ? [...settings.notify_on, key] : settings.notify_on.filter((item) => item !== key) })} />{NOTIFY[key]}
      </label>)}</div>
    </div>
    <label className="flex items-center gap-2.5 rounded-xl card-surface px-4 py-3">
      <input type="checkbox" checked={settings.enabled} disabled={!ready && !settings.enabled} onChange={(event) => void save({ enabled: event.target.checked }, event.target.checked ? '已开启，现在可以在手机上给机器人发任务了' : '已关闭')} />
      <span className="flex-1"><b className="block font-medium text-fg">开启手机远程</b>
        <small className="text-[12px] text-fg-3">{ready ? '只在 Atlas 运行时生效；开了后台常驻的话，关掉窗口也能用。' : '先填好密钥、允许的账号和目录。'}</small></span>
    </label>
    {message && <p role="status" className={cn('m-0 rounded-lg px-3 py-2 text-[12.5px]', message.ok ? 'bg-ok-soft text-fg' : 'bg-danger-soft text-danger')}>{message.text}</p>}
  </div>;
}
