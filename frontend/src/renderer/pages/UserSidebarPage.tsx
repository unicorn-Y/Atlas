import { useEffect, useState } from 'react';
import MarkdownContent from '../components/MarkdownContent';

export type UserSidebarPageDefinition = { id: string; title: string; description: string; content: string };

export const USER_SIDEBAR_PAGES_KEY = 'atlas.sidebar.user-pages';
export function readUserSidebarPages(): UserSidebarPageDefinition[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(USER_SIDEBAR_PAGES_KEY) ?? '[]');
    if (!Array.isArray(raw)) return [];
    return raw.flatMap((item): UserSidebarPageDefinition[] => item && typeof item.id === 'string' && typeof item.title === 'string'
      ? [{ id: item.id, title: item.title.slice(0, 80), description: typeof item.description === 'string' ? item.description.slice(0, 240) : '', content: typeof item.content === 'string' ? item.content : '' }]
      : []);
  } catch { return []; }
}

export default function UserSidebarPage({ page, onChange }: { page: UserSidebarPageDefinition; onChange: (page: UserSidebarPageDefinition) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(page);
  useEffect(() => { setDraft(page); }, [page]);
  const update = (patch: Partial<UserSidebarPageDefinition>) => { const next = { ...draft, ...patch }; setDraft(next); onChange(next); };
  return <section aria-label={`自定义页面：${page.title}`} className="mx-auto flex h-full w-full max-w-5xl min-h-0 flex-col px-8 py-7">
    <header className="mb-5 flex items-start gap-4 border-b border-line pb-4">
      <div className="min-w-0 flex-1">
        {editing ? <input aria-label="页面名称" value={draft.title} maxLength={80} onChange={(event) => update({ title: event.target.value })} className="w-full bg-transparent text-2xl font-semibold text-heading outline-none" /> : <h1 className="m-0 text-2xl font-semibold text-heading">{page.title}</h1>}
        {editing ? <input aria-label="页面说明" value={draft.description} maxLength={240} onChange={(event) => update({ description: event.target.value })} placeholder="添加简短说明" className="mt-2 w-full bg-transparent text-sm text-fg-2 outline-none placeholder:text-fg-3" /> : page.description && <p className="mb-0 mt-2 text-sm text-fg-2">{page.description}</p>}
      </div>
      <button type="button" onClick={() => setEditing((value) => !value)} className="rounded-lg border border-line px-3 py-1.5 text-xs text-fg-2 hover:bg-hover">{editing ? '完成编辑' : '编辑页面'}</button>
    </header>
    {editing ? <label className="flex min-h-0 flex-1 flex-col gap-2 text-xs text-fg-2">页面内容（Markdown）
      <textarea aria-label="页面内容（Markdown）" value={draft.content} onChange={(event) => update({ content: event.target.value })} placeholder={'# 我的页面\n\n在这里记录说明、链接和清单。'} className="min-h-[240px] flex-1 resize-none rounded-xl border border-line bg-surface p-4 font-mono text-[13px] leading-6 text-fg outline-none focus:border-brand" />
    </label> : <div className="min-h-0 flex-1 overflow-auto rounded-xl border border-line bg-surface p-6">
      {page.content.trim() ? <MarkdownContent content={page.content} /> : <p className="m-0 text-sm text-fg-3">这个页面还没有内容。选择“编辑页面”配置说明和 Markdown 内容。</p>}
    </div>}
  </section>;
}
