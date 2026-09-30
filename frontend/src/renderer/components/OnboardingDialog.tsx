import { useEffect, useState, type FormEvent } from 'react';
import { Check, FolderOpen, LoaderCircle, Radio, Sparkles } from 'lucide-react';
import { useAtlasStore } from '../store/useAtlasStore';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';
import { cn } from '../ui/cn';
import Mark from './Mark';

const PRESETS = [
  { label: 'DeepSeek', url: 'https://api.deepseek.com/v1' },
  { label: 'OpenRouter', url: 'https://openrouter.ai/api/v1' },
  { label: '本机 Ollama', url: 'http://127.0.0.1:11434/v1' },
];
const TRIES = [
  '看看我桌面上有哪些文件，按类型归个类告诉我',
  '帮我写一个 Python 脚本，把一个文件夹里的图片按拍摄日期重命名',
  '搜索一下这周 AI Agent 领域有什么新东西，列 5 条',
];
const STEPS = ['称呼', '连接模型', '工作目录', '开始'];

/** First run: a name, a model that answers, a folder to work in, then a first task to try. */
export default function OnboardingDialog({ open, onClose, username, onUsername, defaultWorkspace, onDefaultWorkspace, onTry }: {
  open: boolean; onClose: () => void; username: string; onUsername: (name: string) => void;
  defaultWorkspace: string; onDefaultWorkspace: (path: string) => void; onTry: (text: string) => void;
}) {
  const store = useAtlasStore();
  const [step, setStep] = useState(0);
  const [name, setName] = useState(username === 'User' ? '' : username);
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [tested, setTested] = useState(false);
  useEffect(() => {
    if (!open) return;
    setStep(0); setTested(false);
    // Before any configuration is saved the store holds Atlas's own address, not a model provider's.
    const current = useAtlasStore.getState();
    setBaseUrl(current.configLoaded && current.providerBaseUrl !== current.apiBaseUrl ? current.providerBaseUrl : '');
  }, [open]);

  const saveModel = async (event: FormEvent) => {
    event.preventDefault();
    if (baseUrl.trim() && (apiKey.trim() || !store.apiKeyConfigured)) {
      if (!await store.saveProviderSettings(baseUrl.trim(), apiKey.trim())) return;
      setApiKey('');
    }
    setTested(true);
    await store.testModelConnection(useAtlasStore.getState().model);
  };
  const pickFolder = async () => {
    const picked = window.atlasDesktop?.selectDirectory
      ? await window.atlasDesktop.selectDirectory(defaultWorkspace || undefined)
      : window.prompt('常用工作目录的完整路径', defaultWorkspace)?.trim() || null;
    if (picked) onDefaultWorkspace(picked);
  };
  const connected = tested && store.connectionTest?.ok;
  const field = 'h-10 w-full rounded-[10px] bg-sunken px-3 text-[14px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';

  return <Dialog open={open} onOpenChange={(value) => { if (!value) onClose(); }} label="开始使用 Atlas" className="w-[min(560px,calc(100vw-32px))]">
    <div className="grid gap-5 p-7">
      <div className="flex items-center gap-3">
        <Mark className="size-9" />
        <div className="min-w-0 flex-1">
          <h2 className="m-0 font-serif text-[21px] font-semibold text-heading">开始使用 Atlas</h2>
          <p className="m-0 mt-0.5 text-[13px] text-fg-3">三分钟配好，之后都能在设置里改。</p>
        </div>
      </div>
      <ol className="m-0 flex list-none gap-1.5 p-0" aria-label="步骤">
        {STEPS.map((label, index) => <li key={label} aria-current={index === step ? 'step' : undefined} className="flex flex-1 flex-col gap-1.5">
          <span className={cn('h-1 rounded-full', index <= step ? 'bg-brand' : 'bg-line-strong')} />
          <span className={cn('text-[12px]', index === step ? 'text-fg' : 'text-fg-3')}>{label}</span>
        </li>)}
      </ol>

      {step === 0 && <form onSubmit={(event) => { event.preventDefault(); onUsername(name.trim() || 'User'); setStep(1); }} className="grid gap-3">
        <label className="grid gap-1.5 text-[13.5px] text-fg-2">Atlas 该怎么称呼你？
          <input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="比如：小王" className={field} /></label>
        <div className="flex justify-end gap-2"><Button type="submit" variant="primary">下一步</Button></div>
      </form>}

      {step === 1 && <form onSubmit={(event) => void saveModel(event)} className="grid gap-3">
        <p className="m-0 text-[13px] leading-[1.7] text-fg-2">Atlas 通过 OpenAI 兼容接口调用模型。选一个服务商，或者填你自己的地址。</p>
        <div className="flex flex-wrap gap-1.5">{PRESETS.map((preset) => <button key={preset.url} type="button" onClick={() => setBaseUrl(preset.url)}
          className={cn('h-7 rounded-lg px-2.5 text-[12.5px]', baseUrl === preset.url ? 'bg-brand-soft text-fg' : 'bg-sunken text-fg-2 hover:text-fg')}>{preset.label}</button>)}</div>
        <label className="grid gap-1.5 text-[13px] text-fg-2">API 地址<input type="url" required value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" className={field} /></label>
        <label className="grid gap-1.5 text-[13px] text-fg-2">API 密钥<input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)}
          placeholder={store.apiKeyConfigured ? '已保存；留空保持不变' : '本机 Ollama 可以不填'} className={field} /></label>
        {store.models.length > 0 && <label className="grid gap-1.5 text-[13px] text-fg-2">用哪个模型
          <select value={store.model} onChange={(event) => { void store.selectModel(event.target.value); setTested(false); }} className={field}>
            {store.models.map((model) => <option key={model.id} value={model.id}>{model.name ?? model.id}</option>)}
          </select></label>}
        {tested && store.connectionTest && <p role="status" className={cn('m-0 rounded-lg px-3 py-2 text-[12.5px]', store.connectionTest.ok ? 'bg-ok-soft text-fg' : 'bg-danger-soft text-danger')}>
          {store.connectionTest.ok ? '连上了，模型有回应。' : `没连上：${store.connectionTest.message}`}</p>}
        {!tested && store.error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{store.error}</p>}
        <div className="flex items-center justify-end gap-2">
          <button type="button" onClick={() => setStep(2)} className="mr-auto text-[12.5px] text-fg-3 hover:text-fg">先跳过</button>
          <Button type="submit" disabled={store.settingsBusy || !baseUrl.trim()}>{store.settingsBusy ? <LoaderCircle className="spin" /> : <Radio />}保存并测试</Button>
          <Button type="button" variant="primary" disabled={!connected} onClick={() => setStep(2)}>下一步</Button>
        </div>
      </form>}

      {step === 2 && <div className="grid gap-3">
        <p className="m-0 text-[13px] leading-[1.7] text-fg-2">Atlas 读写文件、运行命令都在工作目录里进行。选一个常用的，新任务会默认用它；每个对话也可以单独换。</p>
        <button onClick={() => void pickFolder()} className="flex items-center gap-3 rounded-xl card-surface px-4 py-3 text-left hover:brightness-105">
          <FolderOpen size={18} className="shrink-0 text-brand" />
          <span className="min-w-0 flex-1 truncate text-[13.5px] text-fg">{defaultWorkspace || '选择文件夹…'}</span>
          {defaultWorkspace && <Check size={16} className="shrink-0 text-ok" />}
        </button>
        <div className="flex items-center justify-end gap-2">
          <button onClick={() => setStep(3)} className="mr-auto text-[12.5px] text-fg-3 hover:text-fg">{defaultWorkspace ? '' : '不设置，每次自己选'}</button>
          <Button variant="primary" onClick={() => setStep(3)}>下一步</Button>
        </div>
      </div>}

      {step === 3 && <div className="grid gap-3">
        <p className="m-0 text-[13px] leading-[1.7] text-fg-2">好了{name.trim() ? `，${name.trim()}` : ''}。挑一个试试，或者直接关掉自己写：</p>
        {TRIES.map((text) => <button key={text} onClick={() => onTry(text)} className="flex items-center gap-2.5 rounded-xl card-surface px-4 py-3 text-left text-[13.5px] text-fg hover:brightness-105">
          <Sparkles size={15} className="shrink-0 text-brand" />{text}
        </button>)}
        <div className="flex justify-end"><Button variant="primary" onClick={onClose}>完成</Button></div>
      </div>}
    </div>
  </Dialog>;
}
