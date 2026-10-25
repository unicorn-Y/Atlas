import { Children, createElement, isValidElement, memo, useCallback, useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react';
import { defaultRehypePlugins, defaultRemarkPlugins, Streamdown, type Components } from 'streamdown';
import { cjk } from '@streamdown/cjk';
import { createMathPlugin } from '@streamdown/math';
import remarkCjkFriendlyGfmStrikethrough from 'remark-cjk-friendly-gfm-strikethrough';
import rehypeHighlight from 'rehype-highlight';
import type { Pluggable } from 'unified';
import 'katex/dist/katex.min.css';
import { MoreHorizontal } from 'lucide-react';
import Mark from './Mark';
import MermaidBlock from './MermaidBlock';
import ClipboardAction from './message-actions/ClipboardAction';
import CodeBlock, { AccessibleContextMenu, CsvMarkdownTable, type ContextAction } from './message-actions/CodeBlock';
import ImagePreview from './message-actions/ImagePreview';
import { useAtlasStore } from '../store/useAtlasStore';
import { api } from '../services/api';

type CodeElementProps = { className?: string; children?: ReactNode; 'data-code-language'?: string };

function plainText(node: ReactNode): string {
  let output = '';
  Children.forEach(node, (child) => {
    if (typeof child === 'string' || typeof child === 'number') output += child;
    else if (isValidElement<{ children?: ReactNode }>(child)) output += plainText(child.props.children);
  });
  return output;
}

function historyContextActions(node: ReactNode): ContextAction[] {
  const actions: ContextAction[] = [];
  const visit = (value: ReactNode) => {
    Children.forEach(value, (child) => {
      if (!isValidElement<{ label?: string; onClick?: () => void; children?: ReactNode }>(child)) return;
      const { label, onClick, children } = child.props;
      if (typeof label === 'string' && typeof onClick === 'function'
        && ['修改后重新发送', '从这里分叉出一个新对话', '分叉，并把前面的内容总结成一段'].includes(label)) {
        actions.push({ id: `history-${actions.length}`, label, onSelect: onClick });
        return;
      }
      visit(children);
    });
  };
  visit(node);
  return actions;
}

function selectionRangeWithin(root: HTMLElement | null): Range | null {
  const selection = window.getSelection();
  if (!root || !selection?.rangeCount || !selection.toString().trim()) return null;
  const content = root.querySelector<HTMLElement>('[data-message-content]');
  if (!content) return null;
  const range = selection.getRangeAt(0);
  const start = range.startContainer instanceof Element ? range.startContainer : range.startContainer.parentElement;
  const end = range.endContainer instanceof Element ? range.endContainer : range.endContainer.parentElement;
  if (!content.contains(range.startContainer) || !content.contains(range.endContainer)
    || start?.closest('button, input, textarea, [role="menu"]') || end?.closest('button, input, textarea, [role="menu"]')) return null;
  return range.cloneRange();
}

function localFileTarget(href: string): { file: string; line: number | null; column: number | null } | null {
  if (!href || href.startsWith('#') || /^(?:https?:|mailto:|tel:|data:|javascript:)/i.test(href)
    || (/^[a-z][a-z\d+.-]*:/i.test(href) && !/^[a-z]:[\\/]/i.test(href) && !/^file:/i.test(href))) return null;

  let target = href;
  let line: number | null = null;
  let column: number | null = null;
  const lineFragment = target.match(/#(?:L|line=)(\d+)(?:C(\d+))?$/i);
  if (lineFragment) {
    line = Number(lineFragment[1]);
    if (lineFragment[2]) column = Number(lineFragment[2]);
  }
  target = target.replace(/#.*$/, '');

  const queryLine = target.match(/[?&](?:line|lineNumber)=(\d+)/i);
  if (line === null && queryLine) line = Number(queryLine[1]);
  const queryColumn = target.match(/[?&](?:column|columnNumber)=(\d+)/i);
  if (column === null && queryColumn) column = Number(queryColumn[1]);
  target = target.replace(/[?].*$/, '');

  if (/^file:/i.test(target)) {
    try {
      const url = new URL(target);
      if (url.protocol !== 'file:' || (url.hostname && url.hostname !== 'localhost')) return null;
      target = decodeURIComponent(url.pathname);
      if (/^\/[a-z]:\//i.test(target)) target = target.slice(1);
    } catch { return null; }
  } else {
    try { target = decodeURIComponent(target); } catch { return null; }
  }

  const locationSuffix = target.match(/:(\d+)(?::(\d+))?$/);
  if (line === null && locationSuffix && locationSuffix.index !== 1) {
    line = Number(locationSuffix[1]);
    if (locationSuffix[2]) column = Number(locationSuffix[2]);
  }
  if (locationSuffix && locationSuffix.index !== 1) target = target.slice(0, locationSuffix.index);

  target = target.replace(/\\/g, '/').replace(/^\.\//, '');
  if (!target || target.split('/').some((part) => part === '..')) return null;
  return { file: target, line, column };
}

function workspaceFileTarget(href: string): { file: string; line: number | null; column: number | null } | null {
  const target = localFileTarget(href);
  if (!target) return null;

  const state = useAtlasStore.getState();
  const conversation = state.conversations.find((item) => item.id === state.activeConversationId);
  const workspaceRoot = conversation?.worktree_path ?? conversation?.workspace;
  if (!workspaceRoot) return null;

  let file = target.file;
  const root = workspaceRoot.replace(/\\/g, '/').replace(/\/$/, '');
  if (/^(?:[a-z]:\/|\/)/i.test(file)) {
    const absolute = file.replace(/\\/g, '/');
    const normalizedRoot = root.replace(/\/$/, '');
    const caseSensitive = !/^[a-z]:\//i.test(absolute);
    const candidate = caseSensitive ? absolute : absolute.toLowerCase();
    const prefix = caseSensitive ? `${normalizedRoot}/` : `${normalizedRoot}/`.toLowerCase();
    if (!candidate.startsWith(prefix)) return null;
    file = absolute.slice(normalizedRoot.length + 1);
  }
  if (!file || file.startsWith('/') || file.split('/').some((part) => part === '..')) return null;
  return { file, line: target.line, column: target.column };
}

function openWorkspaceFile(href: string): boolean {
  const target = workspaceFileTarget(href);
  if (!target) return false;
  useAtlasStore.getState().requestFileOpen(target.file, target.line, target.column);
  return true;
}

function safeExternalHref(href: string | undefined): string | null {
  if (!href) return null;
  try {
    const url = new URL(href);
    return (url.protocol === 'http:' || url.protocol === 'https:') && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

function externalWorkspaceFilePath(href: string): string | null {
  const target = workspaceFileTarget(href);
  if (!target) return null;
  const state = useAtlasStore.getState();
  const conversation = state.conversations.find((item) => item.id === state.activeConversationId);
  const workspaceRoot = conversation?.worktree_path ?? conversation?.workspace;
  if (!workspaceRoot || workspaceRoot.startsWith('ssh://') || !/^(?:[a-z]:[\\/]|\\\\|\/)/i.test(workspaceRoot)) return null;
  const separator = workspaceRoot.includes('\\') ? '\\' : '/';
  return `${workspaceRoot.replace(/[\\/]+$/, '')}${separator}${target.file.replace(/[\\/]/g, separator)}`;
}

function openWorkspaceFileInEditor(href: string, editor: 'vscode' | 'cursor' | 'zed' | 'idea' | 'pycharm'): Promise<void> {
  const full = externalWorkspaceFilePath(href);
  const target = workspaceFileTarget(href);
  if (!full || !target) return Promise.reject(new Error('这个文件不属于当前本地工作区。'));
  const state = useAtlasStore.getState();
  const conversation = state.conversations.find((item) => item.id === state.activeConversationId);
  const workspaceRoot = conversation?.worktree_path ?? conversation?.workspace;
  if (!workspaceRoot || !window.atlasDesktop?.openFileInEditor) return Promise.reject(new Error('当前环境不能在 IDE 中打开文件。'));
  return window.atlasDesktop.openFileInEditor(editor, workspaceRoot, full);
}

// 不让 Streamdown 自带的 tailwind 类名混进 .prose-atlas 排版：这些标签按原生元素输出，和以前 ReactMarkdown 的 DOM 一致。
const PLAIN_TAGS = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'strong', 'blockquote', 'hr', 'thead', 'tbody', 'tr', 'th', 'td', 'sup', 'sub'] as const;
const plainComponents = Object.fromEntries(PLAIN_TAGS.map((tag) => [tag, ({ node, ...props }: { node?: unknown } & Record<string, unknown>) => {
  void node;
  return createElement(tag, props);
}])) as Components;

const codeLanguage = (className?: string) => className?.match(/(?:^|\s)language-([^\s]+)/)?.[1];

// ```mermaid blocks become diagrams once the reply settles; every other code block renders as usual.
function markdownComponents(streaming: boolean): Components {
  return {
    ...plainComponents,
    code({ className, children, node, ...rest }) {
      void node;
      // 流式中的 mermaid 源码多半没写完，先当普通代码显示，落定后再画图。
      if (!streaming && className?.includes('language-mermaid')) return <MermaidBlock source={String(children ?? '').trimEnd()} />;
      return <code className={className} data-code-language={codeLanguage(className)} {...rest}>{children}</code>;
    },
    pre({ children, node }) {
      void node;
      const child = Children.toArray(children).find((item) => isValidElement<CodeElementProps>(item));
      if (!child || !isValidElement<CodeElementProps>(child)) return <pre>{children}</pre>;
      if (child.type === MermaidBlock) return <>{children}</>;
      const language = child.props['data-code-language'] ?? codeLanguage(child.props.className);
      return <CodeBlock source={plainText(child.props.children).replace(/\n$/, '')} language={language}>{children}</CodeBlock>;
    },
    img({ src, alt, title }) {
      return <ImagePreview src={typeof src === 'string' ? src : undefined} alt={alt} title={title} />;
    },
    table: ({ children }) => <CsvMarkdownTable>{children}</CsvMarkdownTable>,
    a({ href, children, node, ...rest }) {
      void node;
      const fileTarget = href ? workspaceFileTarget(href) : null;
      const externalHref = safeExternalHref(href);
      if (!fileTarget && !externalHref) return <span {...rest}>{children}</span>;
      const safeHref = fileTarget ? href ?? undefined : externalHref ?? undefined;
      return <a href={safeHref} {...rest} target={externalHref ? '_blank' : undefined}
        rel={externalHref ? 'noopener noreferrer' : undefined} onClick={(event) => {
          if (!fileTarget) return;
          event.preventDefault();
          openWorkspaceFile(href!);
        }}>{children}</a>;
    },
  };
}
const STATIC_COMPONENTS = markdownComponents(false);
const STREAMING_COMPONENTS = markdownComponents(true);

// 照 ZCode message.tsx：`1~2` 这类中文常见写法别被当成删除线（GFM 与 CJK 删除线扩展默认都开 singleTilde）。
function disableSingleTilde(plugin: Pluggable): Pluggable {
  if (!Array.isArray(plugin)) return typeof plugin === 'function' ? [plugin, { singleTilde: false }] : plugin;
  const [attacher, options] = plugin;
  return [attacher, { ...(typeof options === 'object' && options !== null ? options : {}), singleTilde: false }];
}
const cjkRemarkPluginsAfter = cjk.remarkPluginsAfter.map((plugin) =>
  (Array.isArray(plugin) ? plugin[0] : plugin) === remarkCjkFriendlyGfmStrikethrough ? disableSingleTilde(plugin) : plugin);
const STREAMDOWN_PLUGINS = {
  cjk: { ...cjk, remarkPlugins: [...cjk.remarkPluginsBefore, ...cjkRemarkPluginsAfter], remarkPluginsAfter: cjkRemarkPluginsAfter },
  // @streamdown/math 默认不认 `$...$` 行内公式。
  math: createMathPlugin({ singleDollarTextMath: true }),
};
const REMARK_PLUGINS = Object.entries(defaultRemarkPlugins).map(([name, plugin]) => name === 'gfm' ? disableSingleTilde(plugin) : plugin);
const REHYPE_PLUGINS = [...Object.values(defaultRehypePlugins), rehypeHighlight];
// 链接由上面的 a 渲染器自己判安全；表格、代码块有 Atlas 自己的操作按钮。
const LINK_SAFETY = { enabled: false } as const;

/**
 * 正文 Markdown：流式和落定走同一个渲染器，避免完成时整体跳一下。
 * 照 ZCode：只有真正在流式时才用 streaming 模式 + 补全未闭合语法（remend）；
 * 已结束消息一律 static，否则 remend 会把 `./src/**\/*` 误补出 `**`。
 */
function MarkdownBody({ content, streaming }: { content: string; streaming: boolean }) {
  return <div data-message-content className="prose-atlas">
    <Streamdown mode={streaming ? 'streaming' : 'static'} parseIncompleteMarkdown={streaming}
      components={streaming ? STREAMING_COMPONENTS : STATIC_COMPONENTS} plugins={STREAMDOWN_PLUGINS}
      remarkPlugins={REMARK_PLUGINS} rehypePlugins={REHYPE_PLUGINS} linkSafety={LINK_SAFETY}
      controls={false} animated={false} isAnimating={false}>{content}</Streamdown>
  </div>;
}

/** Full Markdown renderer reused by compact history previews. */
export function FormattedMessageContent({ content }: { content: string }) {
  return <MarkdownBody content={content} streaming={false} />;
}

/**
 * One chat turn. The user speaks in the UI face inside a bubble; Atlas answers in serif, unboxed.
 * memo 化：历史消息在流式输出期间属性不变，不随每次 delta 重渲染。
 */
const ConversationMessage = memo(function ConversationMessage({ id, role, content, username, status, working = false, continued = false, note, actions, streaming = false, memoryCitations = [], createdAt }: {
  id?: string;
  role: 'user' | 'assistant'; content: string; username: string; status?: string; working?: boolean;
  /** Small label above a user bubble, e.g. that it was folded into a running task. */
  note?: string;
  /** Controls revealed on hover, such as edit or fork. */
  actions?: ReactNode;
  /** Part of an Atlas turn that already showed its header; renders just the text, aligned under it. */
  continued?: boolean;
  /** 仍在生成中：Streamdown 流式模式（补全未闭合语法），落定后切 static。 */
  streaming?: boolean;
  memoryCitations?: string[];
  createdAt?: string;
}) {
  const [showTimestamp, setShowTimestamp] = useState(() => { try { return localStorage.getItem('atlas.preference.message-timestamps') === 'true'; } catch { return false; } });
  useEffect(() => { const update = () => { try { setShowTimestamp(localStorage.getItem('atlas.preference.message-timestamps') === 'true'); } catch { setShowTimestamp(false); } }; window.addEventListener('atlas:message-timestamps-changed', update); return () => window.removeEventListener('atlas:message-timestamps-changed', update); }, []);
  const timestampLabel = showTimestamp && createdAt ? new Date(createdAt).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : null;
  const [markdownSource, setMarkdownSource] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; items?: ContextAction[] } | null>(null);
  const [selectionTooltip, setSelectionTooltip] = useState<{ x: number; y: number; text: string } | null>(null);
  const contextTriggerRef = useRef<HTMLButtonElement>(null);
  const messageRootRef = useRef<HTMLDivElement>(null);
  const pendingSelectionRangeRef = useRef<Range | null>(null);
  const [citationOpen, setCitationOpen] = useState(false);
  const [citationDetails, setCitationDetails] = useState<Record<string, { path: string; text: string; ref: string }>>({});
  const [citationError, setCitationError] = useState('');
  const apiBaseUrl = useAtlasStore((state) => state.apiBaseUrl);
  const loadCitations = async () => {
    if (citationOpen) { setCitationOpen(false); return; }
    setCitationOpen(true); setCitationError('');
    try {
      const rows = await Promise.all(memoryCitations.map(async (ref) => {
        const row = await api<{ ref: string; path: string; text: string }>(apiBaseUrl, `/api/memlib/citation?ref=${encodeURIComponent(ref)}`);
        return [ref, { ref, path: row.path, text: row.text }] as const;
      }));
      setCitationDetails(Object.fromEntries(rows));
    } catch (reason) { setCitationError(reason instanceof Error ? reason.message : String(reason)); }
  };
  const citationControl = role === 'assistant' && !streaming && memoryCitations.length > 0 && <div className="mt-2">
    <button type="button" aria-expanded={citationOpen} onClick={() => void loadCitations()} className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11px] text-fg-3 hover:bg-hover">记忆来源 · {memoryCitations.length}</button>
    {citationOpen && <div className="mt-2 grid gap-2 rounded-lg border border-line bg-panel p-3 text-xs">
      {citationError && <p role="alert" className="m-0 text-danger">来源读取失败：{citationError}</p>}
      {memoryCitations.map((ref) => { const source = citationDetails[ref]; return <article key={ref} className="border-b border-line pb-2 last:border-0 last:pb-0">
        {source ? <><b>{source.path}</b><p className="my-1 whitespace-pre-wrap text-fg-2">{source.text}</p><button type="button" className="text-brand underline" onClick={async () => {
          try { const original = await api<{ messages?: Array<{ role?: string; text?: string; at?: string }> }>(apiBaseUrl, `/api/memlib/open?ref=${encodeURIComponent(ref)}&window=3`); const excerpt = (original.messages ?? []).map((message) => `${message.role ?? '消息'}：${message.text ?? ''}`).join('\n'); setCitationDetails((current) => ({ ...current, [ref]: { ...source, text: `${source.text}\n\n原对话出处：\n${excerpt || '原始对话片段暂不可用。'}` } })); }
          catch (reason) { setCitationError(reason instanceof Error ? reason.message : String(reason)); }
        }}>展开原对话出处</button></> : <span className="text-fg-3">正在读取来源 {ref}…</span>}
      </article>; })}
    </div>}
  </div>;
  const closeContextMenu = useCallback(() => setContextMenu(null), []);
  const showSelectionTooltip = (event: MouseEvent<HTMLElement>) => {
    if (event.target instanceof Element && event.target.closest('button, input, textarea, [role="menu"]')) return;
    const range = selectionRangeWithin(messageRootRef.current);
    if (!range) { setSelectionTooltip(null); return; }
    const rect = range.getBoundingClientRect();
    setSelectionTooltip({ text: range.toString().trim(), x: Math.min(Math.max(rect.left + rect.width / 2, 120), window.innerWidth - 120), y: Math.max(48, rect.top - 8) });
  };
  useEffect(() => {
    if (!selectionTooltip) return;
    const dismiss = (event: globalThis.MouseEvent) => {
      if (event.target instanceof Element && event.target.closest('[data-selection-tooltip]')) return;
      setSelectionTooltip(null);
    };
    window.addEventListener('mousedown', dismiss);
    return () => window.removeEventListener('mousedown', dismiss);
  }, [selectionTooltip]);
  const buildContextActions = (range = selectionRangeWithin(messageRootRef.current)): ContextAction[] => [
      ...(content ? [{ id: 'copy-message', label: '复制消息', onSelect: () => navigator.clipboard.writeText(content) }] : []),
      ...(content ? [{ id: 'copy-message-markdown', label: '复制为 Markdown', onSelect: () => navigator.clipboard.writeText(content) }] : []),
      ...historyContextActions(actions),
      ...(range ? [{ id: 'add-selection-to-draft', label: '将选中文本加入消息草稿', restoreFocus: false, onSelect: () => {
        const selection = window.getSelection();
        if (!selection) throw new Error('selection unavailable');
        selection.removeAllRanges();
        selection.addRange(range);
        const shortcut = new KeyboardEvent('keydown', { key: 'a', altKey: true, shiftKey: true, bubbles: true, cancelable: true });
        window.dispatchEvent(shortcut);
        if (!shortcut.defaultPrevented) throw new Error('selected-text command unavailable');
      } }] : []),
      ...(range ? [{ id: 'side-chat-selection', label: '用选中文本开启侧聊', restoreFocus: false, onSelect: () => {
        window.dispatchEvent(new CustomEvent('atlas:side-chat-selection', { detail: { text: range.toString().trim() } }));
      } }] : []),
      ...(role === 'assistant' && content && !streaming ? [{
        id: 'markdown-source',
        label: markdownSource ? '查看渲染预览' : '查看 Markdown 源码',
        onSelect: () => setMarkdownSource((value) => !value),
      }] : []),
    ];
  const contextActions = buildContextActions(null);
  const openContextMenu = (event: MouseEvent<HTMLElement>) => {
    const target = event.target;
    if (target instanceof Element) {
      const anchor = target.closest<HTMLAnchorElement>('a[href]');
      if (anchor) {
        const href = anchor.getAttribute('href') ?? '';
        const fileTarget = workspaceFileTarget(href);
        if (!fileTarget) return;
        event.preventDefault();
        const suffix = fileTarget.line === null ? '' : `（第 ${fileTarget.line} 行${fileTarget.column === null ? '' : `，第 ${fileTarget.column} 列`}）`;
        const externalPath = externalWorkspaceFilePath(href);
        const fileMention = fileTarget.file;
        setContextMenu({ x: event.clientX, y: event.clientY, items: [
          { id: 'open-linked-file', label: `在工作区打开文件${suffix}`, onSelect: () => { if (!openWorkspaceFile(href)) throw new Error('file target changed'); } },
          { id: 'attach-linked-file', label: '加入消息上下文', onSelect: () => window.dispatchEvent(new CustomEvent('atlas:add-context-file', { detail: { path: fileMention } })) },
          ...(externalPath && window.atlasDesktop?.openPath ? [{ id: 'open-linked-file-external', label: '用系统默认程序打开', onSelect: async () => {
            const result = await window.atlasDesktop!.openPath(externalPath);
            if (result !== 'opened' && result !== 'revealed') throw new Error(`无法打开文件：${result}`);
          } }] : []),
          ...(externalPath && window.atlasDesktop?.openFileInEditor ? (['vscode', 'cursor', 'zed', 'idea', 'pycharm'] as const).map((editor) => ({
            id: `open-linked-file-${editor}`, label: `在 ${{ vscode: 'VS Code', cursor: 'Cursor', zed: 'Zed', idea: 'IntelliJ IDEA', pycharm: 'PyCharm' }[editor]} 中打开`,
            onSelect: () => openWorkspaceFileInEditor(href, editor),
          })) : []),
          { id: 'copy-linked-file-path', label: '复制文件路径', onSelect: () => navigator.clipboard.writeText(fileTarget.line === null ? fileTarget.file : `${fileTarget.file}:${fileTarget.line}${fileTarget.column === null ? '' : `:${fileTarget.column}`}`) },
        ] });
        return;
      }
      if (target.closest('button, input, textarea, [role="menu"]')) return;
    }
    if (!contextActions.length) return;
    event.preventDefault();
    setContextMenu({ x: event.clientX, y: event.clientY, items: buildContextActions(selectionRangeWithin(messageRootRef.current)) });
  };
  const openContextMenuFromButton = () => {
    const rect = contextTriggerRef.current?.getBoundingClientRect();
    if (rect && contextActions.length) {
      const range = pendingSelectionRangeRef.current ?? selectionRangeWithin(messageRootRef.current);
      setContextMenu({ x: rect.left, y: rect.bottom + 4, items: buildContextActions(range) });
      pendingSelectionRangeRef.current = null;
    }
  };
  const currentContextActions = contextMenu?.items ?? contextActions;
  const selectionActionTooltip = selectionTooltip && <div data-selection-tooltip role="toolbar" aria-label="选中文本操作"
    onMouseDown={(event) => event.preventDefault()}
    style={{ left: selectionTooltip.x, top: selectionTooltip.y, transform: 'translate(-50%, -100%)' }}
    className="fixed z-[120] flex items-center gap-1 rounded-lg border border-line bg-panel p-1 shadow-xl">
    <button type="button" onClick={() => {
      window.dispatchEvent(new CustomEvent('atlas:add-selection-to-draft', { detail: { text: selectionTooltip.text } }));
      setSelectionTooltip(null);
    }} className="rounded-md px-2 py-1 text-[12px] text-fg hover:bg-hover">引用这段继续问</button>
    <button type="button" onClick={() => {
      window.dispatchEvent(new CustomEvent('atlas:side-chat-selection', { detail: { text: selectionTooltip.text } }));
      setSelectionTooltip(null);
    }} className="rounded-md px-2 py-1 text-[12px] text-fg hover:bg-hover">开启侧聊</button>
  </div>;
  const assistantContent = markdownSource && !streaming
    ? <pre data-message-content className="my-2 max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-code p-3 font-mono text-[12px] leading-[1.6] text-fg-2">{content}</pre>
    : <MarkdownBody content={content} streaming={streaming} />;
  const assistantActions = <>
    {content && <ClipboardAction text={content} />}
    {content && !streaming && <button type="button" aria-pressed={markdownSource}
      aria-label={markdownSource ? '查看渲染预览' : '查看 Markdown 源码'}
      title={markdownSource ? '查看渲染预览' : '查看 Markdown 源码'}
      onClick={() => setMarkdownSource((value) => !value)}
      className="inline-flex h-7 items-center rounded-lg px-2 text-[11px] text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand">
      {markdownSource ? '预览' : '源码'}
    </button>}
  </>;
  if (role === 'assistant' && continued) {
    return <div ref={messageRootRef} className="group my-3" data-message-id={id} data-message-role="assistant" onContextMenu={openContextMenu} onMouseUp={showSelectionTooltip}>
      {timestampLabel && <time dateTime={createdAt} className="mb-1 block text-[10.5px] text-fg-3">{timestampLabel}</time>}
      {assistantContent}
      {citationControl}
      {selectionActionTooltip}
      {content && <div className="mt-1 flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        {assistantActions}
        {contextActions.length > 0 && <button ref={contextTriggerRef} type="button" aria-label="更多消息操作" title="更多消息操作"
          onMouseDown={() => { pendingSelectionRangeRef.current = selectionRangeWithin(messageRootRef.current); }}
          aria-haspopup="menu" aria-expanded={Boolean(contextMenu)} onClick={openContextMenuFromButton}
          className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand"><MoreHorizontal size={14} /></button>}
      </div>}
      {contextMenu && <AccessibleContextMenu label="消息操作" items={currentContextActions} x={contextMenu.x} y={contextMenu.y}
        onClose={closeContextMenu} restoreFocus={() => contextTriggerRef.current?.focus()} />}
    </div>;
  }
  if (role === 'user') {
    return <div ref={messageRootRef} className="group my-5 flex flex-col items-end gap-1" data-message-id={id} data-message-role="user" onContextMenu={openContextMenu} onMouseUp={showSelectionTooltip}>
      {timestampLabel && <time dateTime={createdAt} className="text-[10.5px] text-fg-3">{timestampLabel}</time>}
      {note && <span className="text-[11.5px] text-fg-3">{note}</span>}
      <div data-message-content data-no-i18n className="max-w-[80%] whitespace-pre-wrap rounded-[18px] bg-[var(--user-bubble)] px-4 py-2 text-[14px] leading-[1.65]" style={{ color: 'var(--user-bubble-fg)' }} title={username}>{content}</div>
      {selectionActionTooltip}
      {(content || actions) && <div className="flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        {content && <ClipboardAction text={content} />}{actions}
        {contextActions.length > 0 && <button ref={contextTriggerRef} type="button" aria-label="更多消息操作" title="更多消息操作"
          onMouseDown={() => { pendingSelectionRangeRef.current = selectionRangeWithin(messageRootRef.current); }}
          aria-haspopup="menu" aria-expanded={Boolean(contextMenu)} onClick={openContextMenuFromButton}
          className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand"><MoreHorizontal size={14} /></button>}
      </div>}
      {contextMenu && <AccessibleContextMenu label="消息操作" items={currentContextActions} x={contextMenu.x} y={contextMenu.y}
        onClose={closeContextMenu} restoreFocus={() => contextTriggerRef.current?.focus()} />}
    </div>;
  }
  // Replies read as plain text under the user's turn (Codex 26.1007, Claude 2.37337): no avatar, no name.
  return <div ref={messageRootRef} className="group my-5" data-message-id={id} data-message-role="assistant" aria-label="Atlas 的回复" onContextMenu={openContextMenu} onMouseUp={showSelectionTooltip}>
    {timestampLabel && <time dateTime={createdAt} className="mb-1 block text-[10.5px] text-fg-3">{timestampLabel}</time>}
    <div className="min-w-0">
      {(working || status) && <div className="mb-1.5 flex items-center gap-2 text-[12px] text-fg-3">
        {working && <Mark className="size-4" working />}
        {status && <span>{status}</span>}
      </div>}
      {assistantContent}
      {citationControl}
      {selectionActionTooltip}
      {(content || actions) && <div className="mt-1 flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        {assistantActions}{actions}
        {contextActions.length > 0 && <button ref={contextTriggerRef} type="button" aria-label="更多消息操作" title="更多消息操作"
          onMouseDown={() => { pendingSelectionRangeRef.current = selectionRangeWithin(messageRootRef.current); }}
          aria-haspopup="menu" aria-expanded={Boolean(contextMenu)} onClick={openContextMenuFromButton}
          className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand"><MoreHorizontal size={14} /></button>}
      </div>}
      {contextMenu && <AccessibleContextMenu label="消息操作" items={currentContextActions} x={contextMenu.x} y={contextMenu.y}
        onClose={closeContextMenu} restoreFocus={() => contextTriggerRef.current?.focus()} />}
    </div>
  </div>;
});

export default ConversationMessage;
