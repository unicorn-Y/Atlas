import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, RotateCcw, SkipForward, Sparkles, X } from 'lucide-react';
import { Button } from '../ui/Button';

const LESSONS = [
  { id: 'workspace', title: '让 Atlas 了解你的工作区', description: '给对话设置工作目录，Atlas 就能围绕项目读取文件、搜索代码并生成改动。', demo: ['打开「设置 → 模型与工作区」', '选择一个项目文件夹', '在对话中问：这个项目的入口在哪里？'], practice: '试着为当前项目选择一个工作目录，然后让 Atlas 找出应用入口。' },
  { id: 'artifacts', title: '查看任务产物和运行记录', description: '生成的文件、工具调用和检查结果都可以从任务活动和右侧面板继续查看。', demo: ['运行一个会生成文件的任务', '在产物卡上选择「查看」', '从右侧面板打开文件并检查内容'], practice: '让 Atlas 创建一份简短的 Markdown 项目说明，再从产物面板打开它。' },
  { id: 'commands', title: '用斜杠命令快速操作', description: '输入 / 打开命令列表；命令支持搜索，常用入口也可以通过键盘完成。', demo: ['在输入框键入 /', '搜索 /help、/model 或 /usage', '按 Enter 执行选中的命令'], practice: '在输入框试试 /help，查看完整命令说明。' },
];
const STORAGE_KEY = 'atlas.preference.feature-lessons.completed';
function readCompleted(): string[] { try { const data: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]'); return Array.isArray(data) ? data.filter((id): id is string => typeof id === 'string') : []; } catch { return []; } }

/** Reopenable, keyboard-operable feature lessons with short animated demos and practice prompts. */
export default function FeatureLessons({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const [completed, setCompleted] = useState<string[]>(readCompleted);
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => { if (open) setIndex(0); }, [open]);
  useEffect(() => { if (!open) return; dialogRef.current?.querySelector<HTMLElement>('button')?.focus(); const key = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); if (event.key === 'ArrowRight') setIndex((value) => Math.min(LESSONS.length - 1, value + 1)); if (event.key === 'ArrowLeft') setIndex((value) => Math.max(0, value - 1)); if (event.key === 'Tab' && dialogRef.current) { const items = [...dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled])')]; const first = items[0], last = items.at(-1); if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); } } }; window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key); }, [open, onClose]);
  if (!open) return null;
  const lesson = LESSONS[index];
  const save = (next: string[]) => { setCompleted(next); try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* local preference storage may be unavailable */ } };
  const finish = () => { save(completed.includes(lesson.id) ? completed : [...completed, lesson.id]); setIndex((value) => Math.min(LESSONS.length - 1, value + 1)); };
  return <div className="fixed inset-0 z-[100] grid place-items-center bg-black/45 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="feature-lessons-title" aria-describedby="feature-lessons-description" className="w-[min(620px,calc(100vw-32px))] overflow-hidden rounded-2xl border border-line bg-panel shadow-2xl">
      <header className="flex items-center gap-3 border-b border-line px-5 py-4"><Sparkles size={18} className="text-brand" /><div className="min-w-0 flex-1"><h2 id="feature-lessons-title" className="m-0 text-[17px] font-semibold text-heading">交互式功能课程</h2><p className="m-0 text-[12px] text-fg-3">课程 {index + 1} / {LESSONS.length} · {completed.length} 项已完成</p></div><button type="button" aria-label="关闭课程" onClick={onClose} className="grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover"><X size={16} /></button></header>
      <div className="grid gap-4 p-5"><div className="lesson-enter rounded-xl border border-line bg-sunken p-4"><h3 className="m-0 text-[15px] font-semibold text-fg">{lesson.title}</h3><p id="feature-lessons-description" className="mb-0 mt-1 text-[13px] leading-6 text-fg-2">{lesson.description}</p></div>
        <div aria-label="演示步骤" className="grid gap-2">{lesson.demo.map((step, stepIndex) => <div key={step} className="lesson-enter flex items-center gap-3 rounded-lg card-surface px-3 py-2.5" style={{ animationDelay: `${stepIndex * 160}ms` }}><span className="grid size-6 shrink-0 place-items-center rounded-full bg-brand-soft text-[11px] font-semibold text-brand">{stepIndex + 1}</span><span className="text-[12.5px] text-fg-2">{step}</span></div>)}</div>
        <div className="rounded-lg border border-brand/30 bg-brand-soft/40 p-3"><p className="m-0 text-[11px] font-semibold text-brand">动手练习</p><p className="mb-0 mt-1 text-[12.5px] leading-5 text-fg-2">{lesson.practice}</p></div>
        <div className="flex items-center gap-2"><Button variant="ghost" size="sm" disabled={index === 0} onClick={() => setIndex((value) => value - 1)}><ArrowLeft size={14} />上一步</Button><Button variant="ghost" size="sm" onClick={() => { save([]); setIndex(0); }}><RotateCcw size={14} />重置</Button><Button variant="ghost" size="sm" onClick={() => setIndex((value) => Math.min(LESSONS.length - 1, value + 1))}><SkipForward size={14} />跳过</Button><span className="flex-1" />{index === LESSONS.length - 1 ? <Button variant="primary" size="sm" onClick={() => { save(completed.includes(lesson.id) ? completed : [...completed, lesson.id]); onClose(); }}><Check size={14} />完成</Button> : <Button variant="primary" size="sm" onClick={finish}><Check size={14} />标记完成 <ArrowRight size={14} /></Button>}</div>
      </div>
    </section>
    <style>{'@keyframes lesson-enter{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}.lesson-enter{animation:lesson-enter .36s ease-out both}@media(prefers-reduced-motion:reduce){.lesson-enter{animation:none}}'}</style>
  </div>;
}
