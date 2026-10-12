import { Children, isValidElement, memo, useCallback, useRef, useState, type MouseEvent, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
import { MoreHorizontal } from 'lucide-react';
import Mark from './Mark';
import MermaidBlock from './MermaidBlock';
import ClipboardAction from './message-actions/ClipboardAction';
import CodeBlock, { AccessibleContextMenu, CsvMarkdownTable, type ContextAction } from './message-actions/CodeBlock';
import ImagePreview from './message-actions/ImagePreview';
import { useAtlasStore } from '../store/useAtlasStore';

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

function localFileTarget(href: string): { file: string; line: number | null } | null {
  if (!href || href.startsWith('#') || /^(?:https?:|mailto:|tel:|data:|javascript:)/i.test(href)
    || (/^[a-z][a-z\d+.-]*:/i.test(href) && !/^[a-z]:[\\/]/i.test(href) && !/^file:/i.test(href))) return null;

  let target = href;
  let line: number | null = null;
  const lineFragment = target.match(/#(?:L|line=)(\d+)(?:C\d+)?$/i);
  if (lineFragment) line = Number(lineFragment[1]);
  target = target.replace(/#.*$/, '');

  const queryLine = target.match(/[?&](?:line|lineNumber)=(\d+)/i);
  if (line === null && queryLine) line = Number(queryLine[1]);
  target = target.replace(/[?].*$/, '');

  if (/^file:/i.test(target)) {
    try {
      const url = new URL(target);
      target = decodeURIComponent(url.pathname);
      if (/^\/[a-z]:\//i.test(target)) target = target.slice(1);
    } catch { return null; }
  } else {
    try { target = decodeURIComponent(target); } catch { return null; }
  }

  const lineSuffix = target.match(/:(\d+)(?::\d+)?$/);
  if (line === null && lineSuffix && lineSuffix.index !== 1) line = Number(lineSuffix[1]);
  if (lineSuffix && lineSuffix.index !== 1) target = target.slice(0, lineSuffix.index);

  target = target.replace(/\\/g, '/').replace(/^\.\//, '');
  if (!target || target.split('/').some((part) => part === '..')) return null;
  return { file: target, line };
}

function workspaceFileTarget(href: string): { file: string; line: number | null } | null {
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
  return { file, line: target.line };
}

function openWorkspaceFile(href: string): boolean {
  const target = workspaceFileTarget(href);
  if (!target) return false;
  useAtlasStore.getState().requestFileOpen(target.file, target.line);
  return true;
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

// ```mermaid blocks become diagrams; every other code block renders as usual.
const MARKDOWN_COMPONENTS: Components = {
  code({ className, children, node, ...rest }) {
    void node;
    if (className?.includes('language-mermaid')) return <MermaidBlock source={String(children ?? '').trimEnd()} />;
    const language = className?.match(/(?:^|\s)language-([^\s]+)/)?.[1];
    return <code className={className} data-code-language={language} {...rest}>{children}</code>;
  },
  pre({ children, node }) {
    void node;
    const child = Children.toArray(children).find((item) => isValidElement<CodeElementProps>(item));
    if (!child || !isValidElement<CodeElementProps>(child)) return <pre>{children}</pre>;
    if (child.type === MermaidBlock) return <>{children}</>;
    const language = child.props['data-code-language'];
    return <CodeBlock source={plainText(child.props.children).replace(/\n$/, '')} language={language}>{children}</CodeBlock>;
  },
  img({ src, alt, title }) {
    return <ImagePreview src={src} alt={alt} title={title} />;
  },
  table: CsvMarkdownTable,
  a({ href, children, node, ...rest }) {
    void node;
    return <a href={href} {...rest} onClick={(event) => {
      if (!href || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (openWorkspaceFile(href)) event.preventDefault();
    }}>{children}</a>;
  },
};

const MARKDOWN_PLUGINS = { remarkPlugins: [remarkGfm], rehypePlugins: [rehypeHighlight], components: MARKDOWN_COMPONENTS };

/** 还在流式输出的回复：先按纯文本渲染（保留换行），message.completed 后再换完整 Markdown 渲染。 */
function StreamingText({ content }: { content: string }) {
  return <div data-message-content className="prose-atlas whitespace-pre-wrap break-words">{content}</div>;
}

/**
 * One chat turn. The user speaks in the UI face inside a bubble; Atlas answers in serif, unboxed.
 * memo 化：历史消息在流式输出期间属性不变，不随每次 delta 重渲染。
 */
const ConversationMessage = memo(function ConversationMessage({ role, content, username, status, working = false, continued = false, note, actions, streaming = false }: {
  role: 'user' | 'assistant'; content: string; username: string; status?: string; working?: boolean;
  /** Small label above a user bubble, e.g. that it was folded into a running task. */
  note?: string;
  /** Controls revealed on hover, such as edit or fork. */
  actions?: ReactNode;
  /** Part of an Atlas turn that already showed its header; renders just the text, aligned under it. */
  continued?: boolean;
  /** 仍在生成中：用轻量纯文本渲染，落定后再切回完整 Markdown。 */
  streaming?: boolean;
}) {
  const [markdownSource, setMarkdownSource] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; items?: ContextAction[] } | null>(null);
  const contextTriggerRef = useRef<HTMLButtonElement>(null);
  const messageRootRef = useRef<HTMLDivElement>(null);
  const pendingSelectionRangeRef = useRef<Range | null>(null);
  const closeContextMenu = useCallback(() => setContextMenu(null), []);
  const buildContextActions = (range = selectionRangeWithin(messageRootRef.current)): ContextAction[] => [
      ...(content ? [{ id: 'copy-message', label: '复制消息', onSelect: () => navigator.clipboard.writeText(content) }] : []),
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
        const suffix = fileTarget.line === null ? '' : `（第 ${fileTarget.line} 行）`;
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
          { id: 'copy-linked-file-path', label: '复制文件路径', onSelect: () => navigator.clipboard.writeText(fileTarget.line === null ? fileTarget.file : `${fileTarget.file}:${fileTarget.line}`) },
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
  const assistantContent = streaming
    ? <StreamingText content={content} />
    : markdownSource
      ? <pre data-message-content className="my-2 max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-code p-3 font-mono text-[12px] leading-[1.6] text-fg-2">{content}</pre>
      : <div data-message-content className="prose-atlas"><ReactMarkdown {...MARKDOWN_PLUGINS}>{content}</ReactMarkdown></div>;
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
    return <div ref={messageRootRef} className="group my-3 pl-10" data-message-role="assistant" onContextMenu={openContextMenu}>
      {assistantContent}
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
    return <div ref={messageRootRef} className="group my-5 flex flex-col items-end gap-1" data-message-role="user" onContextMenu={openContextMenu}>
      {note && <span className="text-[11.5px] text-fg-3">{note}</span>}
      <div data-message-content className="max-w-[78%] whitespace-pre-wrap rounded-[16px] rounded-br-[5px] bg-sunken px-4 py-2.5 text-[14.5px] leading-[1.7] text-fg shadow-[inset_0_0_0_1px_var(--line)]" title={username}>{content}</div>
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
  return <div ref={messageRootRef} className="group my-5 grid grid-cols-[28px_minmax(0,1fr)] gap-3" data-message-role="assistant" onContextMenu={openContextMenu}>
    <Mark className="mt-[3px] size-[26px]" working={working} />
    <div className="min-w-0">
      <div className="mb-1.5 flex items-baseline gap-2.5">
        <b className="font-serif text-[14px] font-semibold tracking-[.04em] text-heading">Atlas</b>
        {status && <span className="text-[12px] text-fg-3">{status}</span>}
      </div>
      {assistantContent}
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
