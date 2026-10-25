import { useState, type ReactNode } from 'react';
import { ChevronLeft, ChevronRight, Lightbulb } from 'lucide-react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import { relativeTime } from '../services/api';

export interface Suggestion { label: string; text: string; mode?: string }

export const SUGGESTIONS: Suggestion[] = [
  { label: '理一理今天要做的事', text: '帮我把今天要做的事理一理，按轻重缓急排个顺序：' },
  { label: '把桌面截图按日期归档', text: '把桌面上的截图按拍摄日期归档到「图片/截图/年-月」文件夹里' },
  { label: '写个脚本批量改文件名', text: '写一个脚本，把这个文件夹里的文件按「日期_序号」批量重命名：' },
  { label: '画一张产品海报', text: '一张极简风格的产品海报，深色背景，产品居中，柔和的顶光', mode: 'image' },
];

export function greeting() {
  const hour = new Date().getHours();
  return hour < 5 ? '夜深了' : hour < 11 ? '早上好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好';
}

export function stepHomeTip(index: number, offset: number): number {
  return (index + offset + SUGGESTIONS.length) % SUGGESTIONS.length;
}

export default function HomeView({ username, composer, notice, recent, onOpen, onSuggest, suggestions = SUGGESTIONS }: {
  username: string;
  composer: ReactNode;
  notice?: ReactNode;
  recent: ConversationSummary[];
  onOpen: (conversation: ConversationSummary) => void;
  onSuggest: (suggestion: Suggestion) => void;
  suggestions?: Suggestion[];
}) {
  const [tipIndex, setTipIndex] = useState(0);
  const tip = SUGGESTIONS[tipIndex % SUGGESTIONS.length];
  return <div className="relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
    <div className="relative mx-auto w-[min(800px,100%)] px-6 pt-[14vh] pb-16">
      <h1 className="m-0 text-[28px] leading-[1.25] font-semibold tracking-[-.01em] text-heading [text-wrap:balance]">
        {greeting()}{username !== 'User' ? `，${username}` : ''}
      </h1>
      <p className="mt-1.5 mb-7 text-[14px] text-fg-3">今天想让 Atlas 做点什么？</p>
      {composer}
      {notice}
      <section aria-label="固定提示示例" className="mt-4 rounded-2xl border border-line bg-surface p-3.5 shadow-sm">
        <div className="flex items-center gap-2">
          <Lightbulb size={15} className="shrink-0 text-brand" />
          <b className="min-w-0 flex-1 truncate text-[12px] font-medium text-fg">试试这个完整示例：{tip.label}</b>
          <button type="button" aria-label="上一条首页示例" onClick={() => setTipIndex((index) => stepHomeTip(index, -1))} className="grid size-7 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><ChevronLeft size={16} /></button>
          <button type="button" aria-label="下一条首页示例" onClick={() => setTipIndex((index) => stepHomeTip(index, 1))} className="grid size-7 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><ChevronRight size={16} /></button>
        </div>
        <p className="mb-3 mt-2 whitespace-pre-wrap text-[12.5px] leading-5 text-fg-2">{tip.text}</p>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-1" aria-label={`第 ${tipIndex + 1} 条，共 ${SUGGESTIONS.length} 条`}>
            {SUGGESTIONS.map((item, index) => <button type="button" key={item.label} aria-label={`查看示例 ${index + 1}`} aria-current={index === tipIndex ? 'true' : undefined} onClick={() => setTipIndex(index)} className={`h-1.5 rounded-full transition-all ${index === tipIndex ? 'w-5 bg-brand' : 'w-1.5 bg-line-strong hover:bg-fg-3'}`} />)}
          </div>
          <button type="button" onClick={() => onSuggest(tip)} className="rounded-lg bg-brand px-3 py-1.5 text-[11.5px] font-medium text-white hover:brightness-105">填入完整示例</button>
        </div>
      </section>
      <section aria-label="结合当前工作区的建议" className="mt-4">
        <div className="mb-2 text-[11.5px] font-medium text-fg-3">结合当前工作区的建议</div>
        <div className="flex flex-wrap gap-2">
        {suggestions.map((suggestion) => <button key={suggestion.label} onClick={() => onSuggest(suggestion)}
          className="h-8 rounded-full px-3.5 text-[13px] text-fg-2 shadow-[inset_0_0_0_1px_var(--line-strong)] transition-colors hover:bg-hover hover:text-fg">
          {suggestion.label}
        </button>)}
        </div>
      </section>
      {recent.length > 0 && <section className="mt-14">
        <h2 className="m-0 mb-2.5 text-[12.5px] font-medium text-fg-3">继续</h2>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3">
          {recent.map((conversation) => <button key={conversation.id} onClick={() => onOpen(conversation)}
            className="card-surface flex min-h-[84px] flex-col rounded-[10px] px-3.5 pt-3 pb-2.5 text-left transition-colors hover:bg-hover">
            <b className="line-clamp-2 text-[13.5px] leading-[1.45] font-medium text-fg">{conversation.title}</b>
            <span className="mt-auto pt-3 text-[12px] text-fg-3">{conversation.updated_at ? relativeTime(conversation.updated_at) : '对话'}</span>
          </button>)}
        </div>
      </section>}
    </div>
  </div>;
}
