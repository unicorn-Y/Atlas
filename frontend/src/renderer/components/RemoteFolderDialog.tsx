import { useEffect, useState, type FormEvent } from 'react';
import { LoaderCircle, Server } from 'lucide-react';
import { backend } from '../store/useAtlasStore';
import { Dialog } from '../ui/Dialog';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';

/** Pick a directory on another machine over SSH; the conversation then works there. */
export default function RemoteFolderDialog({ open, onClose, onChoose, current }: {
  open: boolean; onClose: () => void; onChoose: (workspace: string) => void; current?: string | null;
}) {
  const [hosts, setHosts] = useState<Array<{ alias: string; hostname?: string; user?: string }>>([]);
  const [host, setHost] = useState('');
  const [path, setPath] = useState('');
  const [check, setCheck] = useState<{ state: 'idle' | 'testing' | 'ok' | 'failed'; detail?: string }>({ state: 'idle' });

  useEffect(() => {
    if (!open) return;
    const match = current?.startsWith('ssh://') ? /^ssh:\/\/([^/]+)\/(.*)$/.exec(current) : null;
    if (match) { setHost(match[1]); setPath(match[2]); }
    setCheck({ state: 'idle' });
    void backend.getSshHosts().then((list) => { setHosts(list); if (!match && list[0]) setHost((value) => value || list[0].alias); }).catch(() => setHosts([]));
  }, [open, current]);

  const test = async () => {
    if (!host) return;
    setCheck({ state: 'testing' });
    try {
      const result = await backend.testSsh(host);
      setCheck(result.ok ? { state: 'ok', detail: `连上了，对方是 ${result.os === 'windows' ? 'Windows' : result.os ?? '未知系统'}` } : { state: 'failed', detail: result.detail });
    } catch (exc) { setCheck({ state: 'failed', detail: exc instanceof Error ? exc.message : String(exc) }); }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const cleaned = path.trim().replace(/\\/g, '/').replace(/^\/+/, '');
    if (!host || !cleaned) return;
    onChoose(`ssh://${host}/${cleaned}`);
    onClose();
  };

  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} label="远程目录" className="w-[min(520px,calc(100vw-32px))] p-6">
    <form onSubmit={submit} className="grid gap-4 text-[13px] text-fg-2">
      <div>
        <h2 className="m-0 flex items-center gap-2 text-[16px] font-semibold text-heading"><Server size={17} className="text-brand" />远程目录（SSH）</h2>
        <p className="mt-1 mb-0 text-fg-3">Atlas 读写文件、运行命令都会在那台电脑上进行。用的是你 ~/.ssh/config 里的主机和密钥，不需要也不会保存密码。</p>
      </div>
      <label className="grid gap-1">主机
        {hosts.length
          ? <select value={host} onChange={(event) => { setHost(event.target.value); setCheck({ state: 'idle' }); }} className={field}>
            {hosts.map((item) => <option key={item.alias} value={item.alias}>{item.alias}{item.hostname && item.hostname !== item.alias ? `（${item.user ? `${item.user}@` : ''}${item.hostname}）` : ''}</option>)}
          </select>
          : <input value={host} onChange={(event) => setHost(event.target.value)} placeholder="ssh config 里的主机名" className={field} />}
      </label>
      <label className="grid gap-1">目录<input value={path} onChange={(event) => setPath(event.target.value)} placeholder="D:/Atlas 或 /home/me/project" className={field} /></label>
      {check.state !== 'idle' && <p role="status" className={cn('m-0 rounded-lg px-3 py-2', check.state === 'ok' ? 'bg-ok-soft text-fg' : check.state === 'failed' ? 'bg-danger-soft text-danger' : 'bg-sunken text-fg-3')}>
        {check.state === 'testing' ? '正在连接…' : check.detail}</p>}
      <div className="flex gap-2">
        <Button onClick={() => void test()} disabled={!host || check.state === 'testing'}>{check.state === 'testing' ? <LoaderCircle className="spin" /> : null}测试连接</Button>
        <span className="flex-1" />
        <Button onClick={onClose}>取消</Button>
        <Button type="submit" variant="primary" disabled={!host || !path.trim()}>使用这个目录</Button>
      </div>
    </form>
  </Dialog>;
}
