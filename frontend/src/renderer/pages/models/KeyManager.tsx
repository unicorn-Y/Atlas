import { useState, type FormEvent } from 'react';
import { KeyRound, Plus, Trash2 } from 'lucide-react';
import type { KeySlotInfo } from '@atlas/backend-adapter';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';

interface KeyManagerProps {
  keys: KeySlotInfo[];
  busy?: boolean;
  /** Off when the Atlas backend is not connected. */
  disabled?: boolean;
  /** Returns true when the key was stored, so the inputs can be cleared. */
  onAdd: (secret: string, label: string) => Promise<boolean>;
  onRemove: (keyId: string) => void;
  onActivate?: (keyId: string) => Promise<boolean>;
}

const shortId = (id: string) => (id.length > 12 ? `${id.slice(0, 4)}…${id.slice(-4)}` : id);

/** Human-readable remaining cooldown; the backend counts in epoch seconds. */
export function cooldownText(cooldownUntil?: number | null): string | null {
  if (!cooldownUntil) return null;
  const minutes = Math.ceil((cooldownUntil * 1000 - Date.now()) / 60000);
  if (minutes <= 0) return null;
  return minutes >= 60 ? `冷却中 · 约剩 ${Math.floor(minutes / 60)} 小时` : `冷却中 · 约剩 ${minutes} 分钟`;
}

/** Key slots of one provider: add, remove, and see pool status. Secrets are write-only. */
export default function KeyManager({ keys, busy, disabled, onAdd, onRemove, onActivate }: KeyManagerProps) {
  const [secret, setSecret] = useState('');
  const [label, setLabel] = useState('');
  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!secret.trim()) return;
    if (await onAdd(secret, label.trim())) { setSecret(''); setLabel(''); }
  };

  return <fieldset className="grid gap-2.5" disabled={disabled}>
    <legend className="text-[13px] font-medium text-fg-2">API 密钥（{keys.length}）</legend>
    <p className="m-0 text-[12px] leading-[1.6] text-fg-3">密钥原文只保存在本机系统钥匙串里，保存后不会再显示。可以放多把：一把被限流时会自动换下一把。</p>
    {keys.map((key) => {
      const cooldown = cooldownText(key.cooldown_until);
      return <div key={key.id} className="flex items-center justify-between gap-3 rounded-lg bg-sunken px-3 py-2 text-[12.5px]">
        <span className="grid min-w-0 gap-0.5">
          <span className="truncate text-fg">{key.label || `密钥 ${shortId(key.id)}`}</span>
          <span className="truncate text-fg-3">
            {cooldown ? <b className={cn('font-medium', 'text-danger')}>{cooldown}</b> : '可用'}
            {' · '}调用 {key.request_count ?? 0} 次
            {key.last_error ? ` · 上次错误：${key.last_error}` : ''}
          </span>
        </span>
        {onActivate && <Button variant={key.active ? 'secondary' : 'ghost'} size="sm" aria-pressed={Boolean(key.active)} disabled={busy || key.active} onClick={() => void onActivate(key.id)}>{key.active ? '优先使用' : '设为优先'}</Button>}
        <Button variant="ghost" size="icon-sm" aria-label={`删除密钥 ${key.label || shortId(key.id)}`} disabled={busy} title="删除这把密钥" onClick={() => onRemove(key.id)}>
          <Trash2 />
        </Button>
      </div>;
    })}
    {!keys.length && <p className="m-0 text-[12.5px] text-fg-3">这一家还没有保存密钥。</p>}
    <form className="flex flex-wrap items-center gap-2" onSubmit={(event) => void submit(event)}>
      <div className="relative">
        <KeyRound size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-fg-3" />
        <input type="password" autoComplete="new-password" required value={secret} disabled={disabled || busy}
          onChange={(event) => setSecret(event.target.value)} placeholder="粘贴密钥原文（sk-…）"
          className={cn(field, 'w-[240px] pl-8')} />
      </div>
      <input value={label} disabled={disabled || busy} onChange={(event) => setLabel(event.target.value)} placeholder="备注名，如「主密钥」" className={cn(field, 'w-[160px]')} />
      <Button type="submit" variant="secondary" size="md" disabled={disabled || busy || !secret.trim()}><Plus />添加密钥</Button>
    </form>
  </fieldset>;
}
