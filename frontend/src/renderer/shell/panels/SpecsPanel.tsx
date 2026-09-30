import { useEffect, useState, type FormEvent } from 'react';
import { CheckSquare, ChevronLeft, FileText, FolderOpen, ListChecks, Play, Plus, RefreshCw, Ruler } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { backend } from '../../store/useAtlasStore';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import { Empty } from './Empty';

const ROOT = '.atlas/specs';
const DOCS = [
  { file: 'requirements.md', label: '需求', icon: FileText },
  { file: 'design.md', label: '设计', icon: Ruler },
  { file: 'tasks.md', label: '任务', icon: ListChecks },
] as const;
type Doc = typeof DOCS[number]['file'];

/** Checkbox items of tasks.md, in order. */
const parseTasks = (text: string) => [...text.matchAll(/^\s*[-*] \[( |x|X)\] (.+)$/gm)].map((match) => ({ done: match[1] !== ' ', title: match[2].trim() }));

const PROMPTS = {
  requirements: (dir: string, idea: string) => `我们用「规格驱动」的方式做一个功能。先只写需求文档，不要写代码、不要改其他文件。

功能描述：${idea}

把需求写到 \`${dir}/requirements.md\`：
- 开头一段话说清楚目标和不做什么；
- 然后是用户故事，每条「作为…，我想…，以便…」，下面列验收标准，用「当…时，系统应当…」的句式，可以逐条验证；
- 最后列出你不确定、需要我拍板的问题。
写完告诉我路径，等我确认。`,
  design: (dir: string) => `读 \`${dir}/requirements.md\`，再看一下这个项目现有的代码结构，然后写设计文档 \`${dir}/design.md\`：整体方案、要改或新增的模块和文件、数据结构和接口、错误处理、测试方案，以及考虑过但没选的方案和原因。只写设计，不要改代码。写完等我确认。`,
  tasks: (dir: string) => `读 \`${dir}/requirements.md\` 和 \`${dir}/design.md\`，把实现拆成任务清单写到 \`${dir}/tasks.md\`：每项一行，用 \`- [ ] \` 开头，按执行顺序排；每项小到一次能做完并验证，写明要改的文件和怎么验证，并注明对应哪几条需求。只写清单，不要开始实现。`,
  next: (dir: string, index: number, title: string) => `按 \`${dir}\` 下的规格执行任务清单第 ${index + 1} 项：「${title}」。
先读 requirements.md、design.md 和 tasks.md，只做这一项，做完按清单里写的方法验证；通过后把 tasks.md 里这一项的 \`- [ ]\` 改成 \`- [x]\`。最后说明改了什么、怎么验证的。如果发现设计有问题，停下来告诉我，不要自行扩大范围。`,
};

/** Kiro-style specs: requirements → design → tasks as files in the workspace, then one task at a time. */
export default function SpecsPanel({ workspace, onChooseWorkspace, refreshKey, onAsk }: {
  workspace?: string | null; onChooseWorkspace: () => void; refreshKey: string; onAsk: (text: string) => void;
}) {
  const [specs, setSpecs] = useState<string[] | null>(null);
  const [selected, setSelected] = useState('');
  const [docs, setDocs] = useState<Partial<Record<Doc, string>>>({});
  const [doc, setDoc] = useState<Doc>('requirements.md');
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: '', idea: '' });
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    if (!workspace) return;
    let stale = false;
    backend.getWorkspaceTree(workspace, ROOT)
      .then((entries) => { if (!stale) setSpecs(entries.filter((entry) => entry.type === 'dir').map((entry) => entry.name).sort()); })
      .catch(() => { if (!stale) setSpecs([]); });
    return () => { stale = true; };
  }, [workspace, refreshKey, reloads]);

  useEffect(() => {
    if (!workspace || !selected) { setDocs({}); return; }
    let stale = false;
    void Promise.all(DOCS.map(({ file }) => backend.getWorkspaceFile(workspace, `${ROOT}/${selected}/${file}`)
      .then((result) => [file, result.content] as const).catch(() => [file, undefined] as const)))
      .then((entries) => {
        if (stale) return;
        const next = Object.fromEntries(entries.filter(([, text]) => text !== undefined)) as Partial<Record<Doc, string>>;
        setDocs(next);
        // Open the furthest stage written so far.
        setDoc((current) => next[current] !== undefined && current !== 'requirements.md' ? current : next['tasks.md'] !== undefined ? 'tasks.md' : next['design.md'] !== undefined ? 'design.md' : 'requirements.md');
      });
    return () => { stale = true; };
  }, [workspace, selected, refreshKey, reloads]);

  if (!workspace) return <Empty title="先选一个工作目录" body="规格文档存放在工作目录的 .atlas/specs 里。" icon={<FolderOpen size={22} />}
    action={<Button variant="primary" onClick={onChooseWorkspace}><FolderOpen />选择文件夹</Button>} />;
  if (workspace.startsWith('ssh://')) return <Empty title="远程目录暂不支持" body="规格面板目前只用于这台电脑上的目录。" />;

  const dir = `${ROOT}/${selected}`;
  const create = (event: FormEvent) => {
    event.preventDefault();
    const name = form.name.trim().toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '');
    if (!name || !form.idea.trim()) return;
    onAsk(PROMPTS.requirements(`${ROOT}/${name}`, form.idea.trim()));
    setCreating(false); setForm({ name: '', idea: '' }); setSelected(name);
  };

  if (creating || (specs && !specs.length && !selected)) return <form onSubmit={create} className="grid gap-3 text-[13px] text-fg-2">
    {specs && specs.length > 0 && <button type="button" onClick={() => setCreating(false)} className="flex items-center gap-1 text-[12.5px] text-fg-3 hover:text-fg"><ChevronLeft size={13} />返回</button>}
    <p className="m-0 leading-[1.7]">先把要做的功能写成规格：Atlas 依次写<b className="font-medium text-fg">需求 → 设计 → 任务清单</b>，每一步你看过再往下，最后按清单一项一项做。</p>
    <label className="grid gap-1">名称（英文、数字、短横线）<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="export-to-pdf"
      className="h-9 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" /></label>
    <label className="grid gap-1">要做什么<textarea required value={form.idea} onChange={(event) => setForm({ ...form, idea: event.target.value })} rows={4} placeholder="比如：对话可以导出成排版好的 PDF，带代码高亮和图片"
      className="rounded-[9px] bg-sunken px-3 py-2 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" /></label>
    <div><Button type="submit" variant="primary" disabled={!form.name.trim() || !form.idea.trim()}>让 Atlas 写需求</Button></div>
  </form>;

  if (!selected) return <div className="grid gap-2">
    <div className="flex items-center gap-2">
      <h3 className="m-0 flex-1 text-[12.5px] font-semibold text-fg-2">规格</h3>
      <button aria-label="刷新" onClick={() => setReloads((value) => value + 1)} className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><RefreshCw size={13} /></button>
      <Button size="sm" onClick={() => setCreating(true)}><Plus />新规格</Button>
    </div>
    {specs === null ? <p className="py-6 text-center text-[13px] text-fg-3">正在读取…</p>
      : specs.map((name) => <button key={name} onClick={() => setSelected(name)} className="flex items-center gap-2.5 rounded-xl card-surface px-3.5 py-2.5 text-left text-[13px] text-fg hover:brightness-105">
        <ListChecks size={15} className="shrink-0 text-brand" /><span className="min-w-0 flex-1 truncate font-mono">{name}</span>
      </button>)}
  </div>;

  const tasks = parseTasks(docs['tasks.md'] ?? '');
  const nextIndex = tasks.findIndex((task) => !task.done);
  const stage = docs['tasks.md'] !== undefined ? 'tasks' : docs['design.md'] !== undefined ? 'design' : docs['requirements.md'] !== undefined ? 'requirements' : 'none';
  const text = docs[doc];

  return <div className="flex h-full min-h-0 flex-col gap-3">
    <div className="flex items-center gap-2">
      <button aria-label="返回规格列表" onClick={() => setSelected('')} className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><ChevronLeft size={15} /></button>
      <code className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-fg">{selected}</code>
      <button aria-label="刷新" onClick={() => setReloads((value) => value + 1)} className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><RefreshCw size={13} /></button>
    </div>
    <div className="flex gap-1" role="tablist" aria-label="规格文档">
      {DOCS.map(({ file, label, icon: Icon }) => <button key={file} role="tab" aria-selected={doc === file} onClick={() => setDoc(file)}
        className={cn('inline-flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px]', doc === file ? 'bg-selected text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg', docs[file] === undefined && 'opacity-50')}>
        <Icon size={13} />{label}{file === 'tasks.md' && tasks.length > 0 && <span className="tabular-nums text-fg-3">{tasks.filter((task) => task.done).length}/{tasks.length}</span>}
      </button>)}
    </div>
    {tasks.length > 0 && doc === 'tasks.md' && <div className="h-1.5 overflow-hidden rounded-full bg-sunken" aria-label="任务进度">
      <div className="h-full rounded-full bg-brand transition-[width]" style={{ width: `${Math.round(tasks.filter((task) => task.done).length / tasks.length * 100)}%` }} />
    </div>}
    <div className="min-h-0 flex-1 overflow-auto rounded-xl card-surface px-4 py-3">
      {text === undefined ? <p className="m-0 text-[13px] text-fg-3">{doc === 'requirements.md' ? 'Atlas 正在写需求，写好后点右上角刷新。' : '这一步还没写。'}</p>
        : doc === 'tasks.md' && tasks.length
          ? <ul className="m-0 grid list-none gap-1.5 p-0 text-[13px]">{tasks.map((task, index) => <li key={index} className={cn('flex items-start gap-2', task.done ? 'text-fg-3 line-through' : index === nextIndex ? 'text-fg' : 'text-fg-2')}>
            {task.done ? <CheckSquare size={14} className="mt-0.5 shrink-0 text-ok" /> : <span className={cn('mt-0.5 size-3.5 shrink-0 rounded-[3px] shadow-[inset_0_0_0_1.5px_var(--line-strong)]', index === nextIndex && 'shadow-[inset_0_0_0_1.5px_var(--brand)]')} />}
            <span className="min-w-0">{task.title}</span></li>)}</ul>
          : <div className="prose-atlas text-[13px]"><ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown></div>}
    </div>
    <div className="flex flex-wrap gap-2">
      {stage === 'requirements' && <Button variant="primary" onClick={() => onAsk(PROMPTS.design(dir))}><Ruler />需求没问题，写设计</Button>}
      {stage === 'design' && <Button variant="primary" onClick={() => onAsk(PROMPTS.tasks(dir))}><ListChecks />设计没问题，拆任务</Button>}
      {stage === 'tasks' && nextIndex >= 0 && <Button variant="primary" onClick={() => onAsk(PROMPTS.next(dir, nextIndex, tasks[nextIndex].title))}><Play />执行第 {nextIndex + 1} 项</Button>}
      {stage === 'tasks' && tasks.length > 0 && nextIndex < 0 && <p className="m-0 text-[13px] text-ok">全部任务都完成了。</p>}
      {stage !== 'none' && <p className="m-0 w-full text-[12px] text-fg-3">想改文档，直接在对话里告诉 Atlas，比如「需求第 3 条改成…」。</p>}
    </div>
  </div>;
}
