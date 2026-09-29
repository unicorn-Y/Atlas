import type { ReactNode } from 'react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import { Orb } from '../components/Mark';
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

export default function HomeView({ username, composer, notice, recent, onOpen, onSuggest }: {
  username: string;
  composer: ReactNode;
  notice?: ReactNode;
  recent: ConversationSummary[];
  onOpen: (conversation: ConversationSummary) => void;
  onSuggest: (suggestion: Suggestion) => void;
}) {
  return <div className="relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
    <Orb className="orb-bg pointer-events-none absolute -top-[120px] -right-[120px] size-[540px]" />
    <div className="relative mx-auto w-[min(720px,100%)] px-6 pt-[9vh] pb-16">
      <h1 className="m-0 font-serif text-[44px] leading-[1.15] font-semibold tracking-[.01em] text-heading [text-wrap:balance]">
        {greeting()}{username !== 'User' ? `，${username}` : ''}
      </h1>
      <p className="mt-2.5 mb-8 text-[15px] text-fg-2">今天想让 Atlas 做点什么？</p>
      {composer}
      {notice}
      <div className="mt-4 flex flex-wrap gap-2">
        {SUGGESTIONS.map((suggestion) => <button key={suggestion.label} onClick={() => onSuggest(suggestion)}
          className="h-8 rounded-full bg-sunken px-3.5 text-[13px] text-fg-2 shadow-[inset_0_0_0_1px_var(--line)] transition-colors hover:bg-hover hover:text-fg">
          {suggestion.label}
        </button>)}
      </div>
      {recent.length > 0 && <section className="mt-12">
        <h2 className="m-0 mb-3 text-[13px] font-semibold text-fg-2">继续</h2>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3">
          {recent.map((conversation) => <button key={conversation.id} onClick={() => onOpen(conversation)}
            className="card-surface flex min-h-[92px] flex-col rounded-[14px] px-4 pt-3.5 pb-3 text-left transition-[filter] hover:brightness-110 dark:hover:brightness-125">
            <b className="line-clamp-2 text-[14px] leading-[1.45] font-medium text-fg">{conversation.title}</b>
            <span className="mt-auto pt-3 text-[12px] text-fg-3">{conversation.updated_at ? relativeTime(conversation.updated_at) : '对话'}</span>
          </button>)}
        </div>
      </section>}
    </div>
  </div>;
}
