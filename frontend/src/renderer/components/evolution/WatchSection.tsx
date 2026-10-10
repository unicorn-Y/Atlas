import { useCallback, useEffect, useState } from 'react';
import { ChevronRight, LoaderCircle, Radar } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getUpstreamWatch, startUpstreamWatch, type UpstreamWatch } from '../../services/upstreamApi';

function agoSeconds(epoch: number): string {
  if (!epoch) return '从未运行';
  const minutes = Math.round((Date.now() / 1000 - epoch) / 60);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} 小时前` : `${Math.round(hours / 24)} 天前`;
}

/** 「参考项目动态」：一流 Agent 项目（Codex、Claude Code、ZCode……）最近改了什么。后端每 24 小时自动跑。 */
export default function WatchSection({ apiBaseUrl, onToast }: { apiBaseUrl: string; onToast?: (message: string) => void }) {
  const [watch, setWatch] = useState<UpstreamWatch | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setWatch(await getUpstreamWatch(apiBaseUrl));
    } catch {
      setWatch(null);
    }
  }, [apiBaseUrl]);

  const running = Boolean(watch?.running);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), running ? 5000 : 120000);
    return () => window.clearInterval(timer);
  }, [load, running]);

  const start = async () => {
    try {
      const result = await startUpstreamWatch(apiBaseUrl);
      onToast?.(result.started ? '开始检查参考项目，几分钟后出报告' : '已经在检查了');
    } catch (cause) {
      onToast?.(cause instanceof Error ? cause.message : '没能开始检查');
    }
    await load();
  };

  const markdown = watch?.markdown ?? '';
  const summary = markdown.split('\n').find((line) => line.includes('个项目，')) ?? '还没有报告。';

  return <div className="border-t border-[var(--line)]">
    <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-[12.5px]">
      <button type="button" className="flex min-w-0 items-center gap-1.5 font-medium text-fg" onClick={() => setOpen((value) => !value)}
        aria-expanded={open}>
        <ChevronRight size={14} className={`text-fg-3 transition-transform ${open ? 'rotate-90' : ''}`} />
        <Radar size={14} className="text-fg-3" />参考项目动态
      </button>
      <span className="min-w-0 truncate text-fg-3">{summary} · {agoSeconds(watch?.last_run ?? 0)}</span>
      <span className="ml-auto flex items-center gap-2">
        {running && <span className="flex items-center gap-1 text-fg-3"><LoaderCircle size={13} className="spin" />检查中</span>}
        <button className="btn ghost !px-2 !py-0.5 text-[12px]" disabled={running} onClick={() => void start()}>立即检查</button>
      </span>
    </div>
    {open && <div className="max-h-[560px] overflow-auto border-t border-[var(--line)] px-4 py-3">
      {markdown
        ? <div className="prose-atlas text-[13px]"><ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown></div>
        : <p className="m-0 text-[12.5px] text-fg-3">还没有报告。点「立即检查」，或等 Atlas 每天自动跑一次。</p>}
    </div>}
  </div>;
}
