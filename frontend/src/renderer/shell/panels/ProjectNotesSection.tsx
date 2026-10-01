import { useEffect, useState } from 'react';
import { ChevronRight, NotebookPen, Pencil } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { backend } from '../../store/useAtlasStore';
import { cn } from '../../ui/cn';

/**
 * `.atlas/NOTES.md`: things worth knowing every time in this project (how to run the tests, the
 * build command, preferences you corrected). Atlas appends to it; you can read and edit it here.
 */
export default function ProjectNotesSection({ root, refreshKey }: { root: string; refreshKey: string }) {
  const [content, setContent] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'untrusted' | 'error'>('loading');
  const [open, setOpen] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const [message, setMessage] = useState('');

  useEffect(() => {
    let stale = false;
    setState('loading');
    backend.getProjectNotes(root).then((text) => { if (!stale) { setContent(text); setState('ready'); } })
      .catch((exc) => { if (!stale) setState(/403|not trusted/i.test(String(exc instanceof Error ? exc.message : exc)) ? 'untrusted' : 'error'); });
    return () => { stale = true; };
  }, [root, refreshKey]);

  const save = async () => {
    if (draft === null) return;
    try { await backend.saveProjectNotes(root, draft); setContent(draft); setDraft(null); setMessage('已保存'); }
    catch (exc) { setMessage(exc instanceof Error ? exc.message : String(exc)); }
  };
  const entries = (content ?? '').split('\n').filter((line) => /^\s*[-*]\s/.test(line)).length;
  const long = (content ?? '').split('\n').length > 10;

  return <section>
    <div className="mb-2 flex items-center gap-1.5">
      <button onClick={() => setOpen((value) => !value)} aria-expanded={open} className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-[12.5px] font-semibold text-fg-2 hover:text-fg">
        <ChevronRight size={13} className={cn('shrink-0 text-fg-3 transition-transform', open && 'rotate-90')} /><NotebookPen size={13} />项目记事本
        {entries > 0 && <span className="font-normal text-fg-3">{entries} 条</span>}
      </button>
      {open && state === 'ready' && draft === null && <button onClick={() => { setDraft(content ?? ''); setMessage(''); }} aria-label="编辑项目记事本"
        className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] text-fg-3 hover:bg-hover hover:text-fg"><Pencil size={11} />编辑</button>}
    </div>
    {open && <>
      {state === 'loading' && <p className="m-0 text-[12.5px] text-fg-3">正在读取…</p>}
      {state === 'untrusted' && <p className="m-0 text-[12px] leading-[1.6] text-fg-3">信任这个目录后才能用记事本（第一次在这里运行任务时会问你）。</p>}
      {state === 'error' && <p className="m-0 text-[12px] text-danger">读不到记事本。</p>}
      {state === 'ready' && draft !== null && <div className="grid gap-2">
        <textarea autoFocus value={draft} onChange={(event) => setDraft(event.target.value)} rows={10} aria-label="项目记事本内容"
          placeholder={'## 构建与测试\n- 跑测试：npm test\n\n## 代码约定\n- …'}
          className="w-full resize-y rounded-[9px] bg-sunken px-3 py-2 font-mono text-[12px] leading-[1.6] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
        <div className="flex items-center gap-2">
          <button onClick={() => void save()} className="primary-fill h-7 rounded-lg px-2.5 text-[12.5px]">保存</button>
          <button onClick={() => setDraft(null)} className="h-7 rounded-lg px-2 text-[12.5px] text-fg-3 hover:text-fg">取消</button>
          {message && <span className="text-[12px] text-danger">{message}</span>}
        </div>
      </div>}
      {state === 'ready' && draft === null && (content?.trim()
        ? <div>
          <div className={cn('prose-atlas relative overflow-hidden rounded-xl bg-sunken px-3 py-2 text-[12.5px]', !expanded && long && 'max-h-44')}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            {!expanded && long && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-[var(--sunken)] to-transparent" />}
          </div>
          {long && <button onClick={() => setExpanded((value) => !value)} className="mt-1 text-[12px] text-fg-3 hover:text-fg">{expanded ? '收起' : '展开全部'}</button>}
          {message && <span className="ml-2 text-[12px] text-ok">{message}</span>}
        </div>
        : <p className="m-0 text-[12px] leading-[1.6] text-fg-3">还没有记录。Atlas 发现以后每次都用得上的东西（怎么跑测试、构建命令、你纠正过的习惯）会记在这里，你也可以自己写。</p>)}
    </>}
  </section>;
}
