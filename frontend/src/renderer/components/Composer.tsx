import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type DragEvent, type FormEvent, type KeyboardEvent, type ReactNode } from 'react';
import { Accessibility, ArrowLeft, ArrowRight, ArrowUp, AtSign, ChevronDown, Code2, File as FileIcon, Film, Hash, ImagePlus, Image as ImageIcon, Keyboard, MessageCircle, Mic, Paperclip, Repeat, Search, SlidersHorizontal, Sparkles, X, type LucideIcon } from 'lucide-react';
import type { ModelInfo } from '@atlas/backend-adapter';
import { fuzzyScore } from '../services/fuzzy';
import { matchSlashCommands, registerSlashCommands, type SlashCommand } from '../services/slashCommands';
import { cn } from '../ui/cn';
import { Dialog } from '../ui/Dialog';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from '../ui/Menu';
import { Tip } from '../ui/Tooltip';
import DrawingPad from './DrawingPad';
import { ExpertModeToggle, useExpertMode } from './settings/ExpertModePanel';
import { backend } from '../store/useAtlasStore';

type Intent = { label: string; icon: LucideIcon; note?: string };

const INTENTS: Array<[RegExp, Intent]> = [
  [/视频|短片|剪辑|动画|video/i, { label: '视频', icon: Film, note: '视频生成还没接入，会先按对话处理' }],
  [/画|生图|图片|插画|海报|头像|logo|配图|image/i, { label: '生图', icon: ImageIcon, note: '想直接出图，可以切到「图像」' }],
  [/每天|每周|每月|定时|提醒我|每隔|自动(执行|运行)|cron/i, { label: '自动化', icon: Repeat, note: '也可以在「自动化」里建成定时任务' }],
  [/代码|bug|报错|函数|接口|重构|编译|测试用例|仓库|git|python|typescript|javascript|sql|\.tsx?\b|\.py\b/i, { label: '代码', icon: Code2 }],
  [/搜索|调研|查一下|资料|对比|最新|新闻|research/i, { label: '调研', icon: Search }],
];

export function guessIntent(text: string): Intent | null {
  if (text.trim().length < 2) return null;
  return INTENTS.find(([pattern]) => pattern.test(text))?.[1] ?? { label: '日常', icon: MessageCircle };
}

/** Something an @ or # mention can refer to. */
export interface MentionItem { kind: 'file' | 'conversation'; id: string; label: string; hint?: string }

/** The @, #, or $ query being typed at the end of the draft, if any. */
export function mentionAt(value: string): { trigger: '@' | '#' | '$'; query: string; start: number } | null {
  const match = /(^|\s)([@#$])([^\s@#$]*)$/.exec(value);
  if (!match) return null;
  return { trigger: match[2] as '@' | '#' | '$', query: match[3], start: match.index + match[1].length };
}

/** Pastes longer than this (a log, a whole file) become an attachment. */
const LONG_PASTE = 4000;
const SCREEN_READER_MODE_KEY = 'atlas.composer.screen-reader-mode';
function readScreenReaderMode(): boolean {
  try { return localStorage.getItem(SCREEN_READER_MODE_KEY) === 'true'; } catch { return false; }
}

export interface ComposerMode { id: string; label: string; icon: LucideIcon }

/** An entry in the `/` menu. `takesArgument` commands receive the text typed after the command name. */
export type { SlashCommand } from '../services/slashCommands';

interface SkillSuggestion {
  id: string;
  skillName: string;
  label: string;
  hint?: string;
  group: string;
  source: string;
}

/** Commands matching a `/query` draft; only while the draft is a single command word (plus an argument for argument commands). */
export function matchCommands(value: string, commands: SlashCommand[]): SlashCommand[] {
  return matchSlashCommands(value, commands);
}

function matchSkillSuggestions(query: string, commands: readonly SlashCommand[]): SkillSuggestion[] {
  return commands
    .filter((command) => command.id.startsWith('skill-'))
    .map((command, index) => {
      const skillName = command.label.replace(/^\/+/, '');
      return {
        command,
        index,
        skillName,
        score: query ? fuzzyScore(query, skillName) : 0,
      };
    })
    .filter((item) => item.score >= 0)
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .slice(0, 8)
    .map(({ command, skillName }) => ({
      id: command.id,
      skillName,
      label: `$${skillName}`,
      hint: command.hint,
      group: '消息提及（作为文本发送）',
      source: command.source ?? '技能',
    }));
}

/** 已发送消息的召回历史（像终端的 ↑ 一样）；全局共用一份，localStorage 持久化最近 50 条。 */
const HISTORY_KEY = 'atlas.composer-history';
const HISTORY_LIMIT = 50;
function readHistory(): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]');
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string' && item.trim().length > 0).slice(-HISTORY_LIMIT) : [];
  } catch { return []; }
}
function appendHistory(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) return readHistory();
  const next = [...readHistory().filter((item) => item !== trimmed), trimmed].slice(-HISTORY_LIMIT);
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)); } catch { /* storage unavailable */ }
  return next;
}

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder: string;
  attachments: string[];
  onRemoveAttachment: (index: number) => void;
  onPickImages: (files: FileList | null) => void;
  listening: boolean;
  onToggleMic: () => void;
  models: ModelInfo[];
  model: string;
  onSelectModel: (id: string) => void;
  onManageModels: () => void;
  status: string;
  autoFocus?: boolean;
  /** `hero` is the large home composer; `dock` sits under a conversation. */
  variant?: 'hero' | 'dock';
  modes?: { value: string; options: ComposerMode[]; onChange: (id: string) => void };
  onCyclePermission?: () => void;
  /** Content shown above the text area, e.g. the live run status. */
  header?: ReactNode;
  commands?: SlashCommand[];
  /** Non-image attachments, shown as chips. */
  files?: Array<{ name: string; size: number }>;
  onRemoveFile?: (index: number) => void;
  /** Looks up @ files / # conversations for the query being typed. */
  findMentions?: (trigger: '@' | '#', query: string) => Promise<MentionItem[]>;
  /** Picked mentions, shown as chips and sent as context. */
  mentions?: MentionItem[];
  onAddMention?: (item: MentionItem) => void;
  onRemoveMention?: (item: MentionItem) => void;
  /** Called instead of inserting pasted text longer than LONG_PASTE characters. */
  onLongPaste?: (text: string) => void;
  /** Extra toolbar controls next to the attach button (working directory, plan mode). */
  tools?: ReactNode;
  onEnhancePrompt?: (text: string) => Promise<string>;
  onAttachDrawing?: (dataUrl: string) => boolean;
  contextKey?: string;
}

export default function Composer(props: ComposerProps) {
  const hero = props.variant === 'hero';
  const [expert] = useExpertMode(backend.apiBaseUrl);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const valueRef = useRef(props.value);
  valueRef.current = props.value;
  const textareaId = useId();
  const suggestionListId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const intent = guessIntent(props.value);
  const current = props.models.find((item) => item.id === props.model);
  const canSend = Boolean(props.value.trim() || props.attachments.length || props.files?.length || props.mentions?.length);
  // 连接状态这类重要提示优先显示；意图提示只在它后面补位，不把它挤掉。
  const hint = props.listening ? '正在听你说…' : props.status || intent?.note || '';

  // ↑ 召回已发送的消息：浏览时草稿先存起来，↓ 回到末尾或失焦时放回来。
  const historyRef = useRef<string[]>([]);
  const historyDraftRef = useRef('');
  const [historyIndex, setHistoryIndex] = useState<number | null>(null);
  useEffect(() => { historyRef.current = readHistory(); }, []);
  const recallHistory = (step: -1 | 1) => {
    const history = historyRef.current;
    if (!history.length) return;
    if (historyIndex === null) {
      if (step === 1 || props.value) return; // 只有输入框为空时 ↑ 才开始召回
      historyDraftRef.current = props.value;
      setHistoryIndex(history.length - 1);
      props.onChange(history[history.length - 1]);
      return;
    }
    const next = historyIndex + step;
    if (next >= history.length) { setHistoryIndex(null); props.onChange(historyDraftRef.current); return; }
    setHistoryIndex(Math.max(0, next));
    props.onChange(history[Math.max(0, next)]);
  };

  useLayoutEffect(() => {
    const el = textRef.current;
    if (!el) return;
    // Empty: fall back to the CSS min-height. Chrome counts the placeholder in scrollHeight,
    // which measures absurdly tall before the layout width settles.
    if (!props.value) { el.style.height = ''; return; }
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, hero ? 240 : 200)}px`;
  }, [props.value, hero]);
  useEffect(() => { if (props.autoFocus) textRef.current?.focus(); }, [props.autoFocus]);

  const [cursor, setCursor] = useState(0);
  const [screenReaderMode, setScreenReaderMode] = useState(readScreenReaderMode);
  const [suggestionAnnouncement, setSuggestionAnnouncement] = useState('');
  const [screenReaderModeNotice, setScreenReaderModeNotice] = useState('');
  const suggestionWasOpenRef = useRef(false);
  const [enhancing, setEnhancing] = useState(false);
  const [enhanceStatus, setEnhanceStatus] = useState('');
  const [dragging, setDragging] = useState(false);
  const [found, setFound] = useState<MentionItem[]>([]);
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false);
  const [shellConfirmation, setShellConfirmation] = useState<string | null>(null);
  const shortcutHelpButtonRef = useRef<HTMLButtonElement>(null);
  const shortcutHelpCloseRef = useRef<HTMLButtonElement>(null);
  const previewOpen = previewIndex !== null;
  const previewTriggerRef = useRef<HTMLButtonElement | null>(null);
  const previewCloseRef = useRef<HTMLButtonElement | null>(null);
  const registeredCommands = useMemo(() => registerSlashCommands(props.commands ?? []), [props.commands]);
  const commandMatches = matchCommands(props.value, registeredCommands);
  const parsedMention = mentionAt(props.value);
  const mention = parsedMention?.trigger === '$' || props.findMentions ? parsedMention : null;
  const skillMatches = useMemo(
    () => mention?.trigger === '$' ? matchSkillSuggestions(mention.query, props.commands ?? []) : [],
    [mention?.query, mention?.trigger, props.commands],
  );
  const mentionKey = mention ? `${mention.trigger}${mention.query}` : '';
  useEffect(() => {
    if (!mention || mention.trigger === '$' || !props.findMentions) { setFound([]); return; }
    const trigger = mention.trigger;
    const query = mention.query;
    let stale = false;
    const timer = window.setTimeout(() => { void props.findMentions!(trigger, query).then((items) => { if (!stale) setFound(items.slice(0, 8)); }).catch(() => undefined); }, 120);
    return () => { stale = true; window.clearTimeout(timer); };
  }, [mentionKey, mention?.trigger, mention?.query, props.findMentions]);
  // Slash commands and mentions share one popup; a draft can only be in one of the two states.
  const matches: Array<SlashCommand | MentionItem | SkillSuggestion> = commandMatches.length
    ? commandMatches
    : mention?.trigger === '$' ? skillMatches : mention ? found : [];
  const matchCount = matches.length;
  const activeSuggestion = matchCount ? matches[Math.min(cursor, matchCount - 1)] : null;
  const activeSuggestionLabel = activeSuggestion?.label ?? '';
  const activeSuggestionHint = activeSuggestion?.hint ?? '';
  useEffect(() => setCursor(0), [matches.length, props.value]);
  useEffect(() => {
    if (!screenReaderMode) {
      suggestionWasOpenRef.current = matchCount > 0;
      setSuggestionAnnouncement('');
      return;
    }
    if (!matchCount) {
      const wasOpen = suggestionWasOpenRef.current;
      suggestionWasOpenRef.current = false;
      if (!wasOpen) { setSuggestionAnnouncement(''); return; }
      setSuggestionAnnouncement('建议列表已关闭。');
      const timer = window.setTimeout(() => setSuggestionAnnouncement(''), 1400);
      return () => window.clearTimeout(timer);
    }
    suggestionWasOpenRef.current = true;
    const timer = window.setTimeout(() => {
      const hintText = activeSuggestionHint ? `，${activeSuggestionHint}` : '';
      setSuggestionAnnouncement(`建议列表，共 ${matchCount} 项。第 ${Math.min(cursor, matchCount - 1) + 1} 项：${activeSuggestionLabel}${hintText}。焦点保留在消息输入框。使用上下方向键浏览，Enter 选择，Escape 关闭。`);
    }, 100);
    return () => window.clearTimeout(timer);
  }, [screenReaderMode, matchCount, cursor, activeSuggestionLabel, activeSuggestionHint]);
  useEffect(() => {
    if (!screenReaderMode || !screenReaderModeNotice) return;
    const timer = window.setTimeout(() => setScreenReaderModeNotice(''), 1800);
    return () => window.clearTimeout(timer);
  }, [screenReaderMode, screenReaderModeNotice]);
  useEffect(() => {
    if (!previewOpen) return;
    previewCloseRef.current?.focus();
    const onPreviewKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setPreviewIndex(null);
        window.requestAnimationFrame(() => previewTriggerRef.current?.focus());
      }
      if (!props.attachments.length) return;
      if (event.key === 'ArrowLeft') { event.preventDefault(); setPreviewIndex((index) => index === null ? null : (index - 1 + props.attachments.length) % props.attachments.length); }
      if (event.key === 'ArrowRight') { event.preventDefault(); setPreviewIndex((index) => index === null ? null : (index + 1) % props.attachments.length); }
    };
    window.addEventListener('keydown', onPreviewKey);
    return () => window.removeEventListener('keydown', onPreviewKey);
  }, [previewOpen, props.attachments.length]);
  useEffect(() => {
    if (!shortcutHelpOpen) return;
    const frame = window.requestAnimationFrame(() => shortcutHelpCloseRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [shortcutHelpOpen]);
  useEffect(() => {
    if (previewIndex !== null && previewIndex >= props.attachments.length) {
      setPreviewIndex(props.attachments.length ? props.attachments.length - 1 : null);
    }
  }, [previewIndex, props.attachments.length]);

  const runCommand = (command: SlashCommand) => {
    const argument = props.value.replace(/^\/\S*\s?/, '');
    props.onChange('');
    command.run(argument);
  };
  const choose = (item: SlashCommand | MentionItem | SkillSuggestion) => {
    if ('skillName' in item) {
      // ZCode's $skill is a message-level mention. Atlas has no structured
      // message-level skill transport yet, so keep it as explicit prompt text
      // instead of toggling the conversation-wide active skill.
      if (mention?.trigger === '$') props.onChange(`${props.value.slice(0, mention.start)}$${item.skillName} `);
      textRef.current?.focus();
      return;
    }
    if ('run' in item) { runCommand(item); return; }
    if (mention) props.onChange(props.value.slice(0, mention.start));
    props.onAddMention?.(item);
    textRef.current?.focus();
  };
  const openAttachmentPreview = (index: number, trigger: HTMLButtonElement) => {
    previewTriggerRef.current = trigger;
    setPreviewIndex(index);
  };
  const closeAttachmentPreview = () => {
    setPreviewIndex(null);
    window.requestAnimationFrame(() => previewTriggerRef.current?.focus());
  };
  const submit = (event?: FormEvent, confirmedShell = false) => {
    event?.preventDefault();
    if (matches.length) { choose(matches[Math.min(cursor, matches.length - 1)]); return; }
    if (canSend) {
      const shellCommand = props.value.trim();
      if (!confirmedShell && props.variant === 'dock' && shellCommand.startsWith('!') && shellCommand.length > 1) {
        setShellConfirmation(shellCommand.slice(1).trim());
        return;
      }
      historyRef.current = appendHistory(props.value);
      setHistoryIndex(null);
      props.onSubmit();
    }
  };
  const enhancePrompt = async () => {
    if (!props.onEnhancePrompt || !props.value.trim() || enhancing) return;
    const original = props.value;
    setEnhancing(true);
    setEnhanceStatus('正在改写提示词…');
    try {
      const rewritten = await props.onEnhancePrompt(original);
      if (valueRef.current !== original) {
        setEnhanceStatus('草稿在改写期间有变化，已保留当前内容；需要时请再次改写。');
        return;
      }
      if (!rewritten.trim()) throw new Error('没有收到改写内容');
      props.onChange(rewritten.trim());
      setEnhanceStatus('提示词已改写，可继续编辑后发送。');
      requestAnimationFrame(() => textRef.current?.focus());
    } catch (error) {
      setEnhanceStatus(`改写失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setEnhancing(false);
    }
  };
  const toggleScreenReaderMode = () => {
    const next = !screenReaderMode;
    try { localStorage.setItem(SCREEN_READER_MODE_KEY, String(next)); } catch { /* storage unavailable */ }
    setScreenReaderMode(next);
    setScreenReaderModeNotice(next ? '屏幕阅读增强已开启。运行和提示状态、建议项会自动播报。' : '');
  };
  const onShortcutHelpOpenChange = (open: boolean) => {
    setShortcutHelpOpen(open);
    if (!open) window.requestAnimationFrame(() => shortcutHelpButtonRef.current?.focus());
  };
  const shortcutRows = [
    { keys: 'Enter', description: '发送消息；建议列表打开时选择当前项。' },
    { keys: 'Shift + Enter', description: '在消息中插入换行。' },
    { keys: '↑ / ↓', description: '建议列表打开时浏览选项；建议列表关闭且输入框为空时，↑ 回看已发送消息，翻阅期间 ↓ 返回较新的消息或原草稿。' },
    { keys: 'Tab', description: '建议列表打开时补全或选择当前建议。' },
    { keys: 'Escape', description: '关闭建议列表；图片预览打开时关闭预览。' },
    { keys: 'Alt + Shift + A', description: '把当前选中的页面或对话文字放入消息草稿。' },
    ...(props.onCyclePermission ? [{ keys: 'Shift + Tab', description: '在会话输入框内循环切换权限模式。' }] : []),
    ...(props.attachments.length > 1 ? [{ keys: '← / →', description: '在多张图片的预览中切换图片。' }] : []),
  ];
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Tab' && event.shiftKey && props.onCyclePermission) {
      event.preventDefault();
      props.onCyclePermission();
      return;
    }
    if (matches.length && !event.nativeEvent.isComposing) {
      if (event.key === 'ArrowDown') { event.preventDefault(); setCursor((value) => (value + 1) % matches.length); return; }
      if (event.key === 'ArrowUp') { event.preventDefault(); setCursor((value) => (value - 1 + matches.length) % matches.length); return; }
      if (event.key === 'Tab') {
        event.preventDefault();
        const item = matches[cursor];
        if ('skillName' in item) choose(item);
        else if ('run' in item) props.onChange(`${item.label}${item.takesArgument ? ' ' : ''}`);
        else choose(item);
        return;
      }
      if (event.key === 'Escape') { event.preventDefault(); props.onChange(mention ? props.value.slice(0, mention.start) : ''); return; }
    }
    // `/` 菜单打开时不抢方向键；空输入框按 ↑ 召回上一条已发送的消息，↓ 往回翻。
    if (!event.nativeEvent.isComposing && !matches.length) {
      if (event.key === 'ArrowUp') { recallHistory(-1); if (historyIndex !== null || !props.value) event.preventDefault(); return; }
      if (event.key === 'ArrowDown') { const browsing = historyIndex !== null; if (browsing) event.preventDefault(); recallHistory(1); return; }
    }
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); }
  };
  const hasFiles = (event: DragEvent<HTMLFormElement>) => Array.from(event.dataTransfer.types).includes('Files');

  return <form onSubmit={submit} data-expert={expert || undefined}
    onDragOver={(event) => { if (!hasFiles(event)) return; event.preventDefault(); setDragging(true); }}
    onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
    onDrop={(event) => { if (!hasFiles(event)) return; event.preventDefault(); setDragging(false); props.onPickImages(event.dataTransfer.files); }}
    className={cn('raised relative transition-shadow focus-within:shadow-[var(--shadow-raised),0_0_0_4px_var(--brand-soft)]',
      hero ? 'rounded-[20px] px-5 pt-[18px] pb-3' : 'rounded-2xl px-4 pt-3 pb-2.5',
      expert && 'shadow-[var(--shadow-raised),0_0_0_1.5px_var(--brand-soft)]',
      dragging && 'shadow-[var(--shadow-raised),0_0_0_2px_var(--brand)]')}>
    {matches.length > 0 && <div id={suggestionListId} role="listbox" aria-label={mention && !commandMatches.length ? (mention.trigger === '@' ? '引用文件' : mention.trigger === '#' ? '引用对话' : '技能文本提及') : '命令'} className="pop anim-pop absolute right-0 bottom-[calc(100%+8px)] left-0 z-30 max-h-[300px] overflow-auto rounded-xl p-1.5">
      {matches.map((item, index) => <button id={`${suggestionListId}-${index}`} key={item.id} type="button" role="option"
        aria-selected={index === cursor} aria-posinset={index + 1} aria-setsize={matchCount} tabIndex={screenReaderMode ? -1 : undefined}
        onMouseMove={() => setCursor(index)} onMouseDown={(event) => { event.preventDefault(); choose(item); }}
        className={cn('flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-[13.5px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand', index === cursor && 'bg-selected')}>
        {'skillName' in item ? <span className="flex shrink-0 items-center gap-1.5 font-mono text-[13px] text-fg"><Sparkles size={13} className="text-brand" />{item.label}</span>
          : 'run' in item ? <span className="shrink-0 font-mono text-[13px] text-fg">{item.label}</span>
          : <span className="flex min-w-0 shrink-0 items-center gap-1.5 text-fg">{item.kind === 'file' ? <AtSign size={13} className="text-fg-3" /> : <Hash size={13} className="text-fg-3" />}<span className="max-w-[260px] truncate">{item.label}</span></span>}
        {('run' in item || 'skillName' in item) && item.source && <span className="shrink-0 rounded bg-sunken px-1.5 py-0.5 text-[10.5px] text-fg-3">{item.source}</span>}
        {('run' in item || 'skillName' in item) && item.group && <span className="shrink-0 rounded bg-sunken px-1.5 py-0.5 text-[10.5px] text-fg-3">{item.group}</span>}
        {item.hint && <span className="min-w-0 truncate text-[12.5px] text-fg-3">{item.hint}</span>}
      </button>)}
    </div>}
    {dragging && <div className="pointer-events-none absolute inset-0 z-20 grid place-items-center rounded-[inherit] bg-brand-soft text-[13.5px] font-medium text-fg">松开添加附件</div>}
    {props.header}
    <textarea id={textareaId} ref={textRef} value={props.value} rows={1} placeholder={props.placeholder} aria-label="消息内容"
      aria-describedby={screenReaderMode ? `${textareaId}-help ${textareaId}-screen-reader-help` : `${textareaId}-help ${textareaId}-status`}
      aria-keyshortcuts={screenReaderMode && matches.length ? 'ArrowDown ArrowUp Enter Escape' : undefined}
      aria-autocomplete={matches.length ? 'list' : undefined}
      aria-expanded={matches.length > 0} aria-controls={matches.length ? suggestionListId : undefined}
      aria-activedescendant={matches.length ? `${suggestionListId}-${cursor}` : undefined}
      onChange={(event) => props.onChange(event.target.value)} onKeyDown={onKey}
      onBlur={() => {
        // 正在翻发送历史时点到别处：结束翻阅，把原来的草稿放回来。
        if (historyIndex === null) return;
        setHistoryIndex(null);
        props.onChange(historyDraftRef.current);
      }}
      onPaste={(event) => {
        if (event.clipboardData.files.length) { event.preventDefault(); props.onPickImages(event.clipboardData.files); return; }
        const text = event.clipboardData.getData('text');
        if (props.onLongPaste && text.length > LONG_PASTE) { event.preventDefault(); props.onLongPaste(text); }
      }}
      className={cn('block w-full resize-none border-0 bg-transparent p-0 text-fg outline-none placeholder:text-fg-3',
        hero ? 'min-h-[60px] text-[16px] leading-[1.65]' : 'min-h-[26px] text-[15px] leading-[1.6]')} />
    <span id={`${textareaId}-help`} className="sr-only">按 Enter 发送，Shift 加 Enter 换行；建议列表可用上下方向键选择、Tab 补全，Escape 关闭。选中文字后按 Alt 加 Shift 加 A，可将选中文字放入消息草稿。</span>
    <span id={`${textareaId}-screen-reader-help`} className={screenReaderMode ? 'sr-only' : 'hidden'}>屏幕阅读增强已开启。建议列表打开时焦点保留在消息输入框；使用上下方向键浏览，当前项和运行提示会自动播报，Enter 选择，Escape 关闭。</span>
    <span id={`${textareaId}-status`} role={screenReaderMode ? undefined : 'status'} aria-live={screenReaderMode ? undefined : 'polite'}
      aria-atomic={screenReaderMode ? undefined : 'true'} aria-hidden={screenReaderMode || undefined}
      className={enhanceStatus ? 'mt-1 block text-[11.5px] text-fg-3' : 'sr-only'}>{enhanceStatus}</span>
    {screenReaderMode && <>
      <span role="status" aria-live="polite" aria-atomic="true" className="sr-only">{screenReaderModeNotice}</span>
      <span role="status" aria-live="polite" aria-atomic="true" className="sr-only">{hint}</span>
      <span role="status" aria-live="polite" aria-atomic="true" className="sr-only">{enhanceStatus}</span>
      <span role="status" aria-live="polite" aria-atomic="true" className="sr-only">{suggestionAnnouncement}</span>
    </>}
    {props.attachments.length > 0 && <div className="mt-2.5 flex flex-wrap gap-2" aria-label="待发送图片">
      {props.attachments.map((image, index) => <div key={`${index}-${image.length}:${image.length > 72 ? `${image.slice(24, 56)}…${image.slice(-24)}` : image}`} className="relative size-14">
        <button type="button" aria-label={`预览图片 ${index + 1}`} onClick={(event) => openAttachmentPreview(index, event.currentTarget)} className="size-full cursor-zoom-in rounded-[10px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
          <img src={image} alt={`待发送图片 ${index + 1}`} className="size-full rounded-[10px] object-cover shadow-[0_0_0_1px_var(--line)]" />
        </button>
        <button type="button" aria-label={`移除图片 ${index + 1}`} onClick={() => props.onRemoveAttachment(index)}
          className="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full bg-fg text-bg focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"><X size={12} /></button>
      </div>)}
    </div>}
    {props.mentions && props.mentions.length > 0 && <div className="mt-2.5 flex flex-wrap gap-2" aria-label="引用的上下文">
      {props.mentions.map((item) => <span key={`${item.kind}:${item.id}`} className="inline-flex max-w-[260px] items-center gap-1 rounded-lg bg-brand-soft py-1 pr-1 pl-2 text-[12.5px] text-fg">
        {item.kind === 'file' ? <AtSign size={12} className="shrink-0" /> : <Hash size={12} className="shrink-0" />}<span className="min-w-0 truncate" title={item.hint ?? item.label}>{item.label}</span>
        <button type="button" aria-label={`移除引用 ${item.label}`} onClick={() => props.onRemoveMention?.(item)} className="grid size-5 place-items-center rounded-md hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"><X size={12} /></button>
      </span>)}
    </div>}
    {props.files && props.files.length > 0 && <div className="mt-2.5 flex flex-wrap gap-2" aria-label="待发送文件">
      {props.files.map((file, index) => <span key={`${index}-${file.name}`} className="inline-flex max-w-[240px] items-center gap-1.5 rounded-lg bg-sunken py-1 pr-1 pl-2 text-[12.5px] text-fg-2 shadow-[inset_0_0_0_1px_var(--line)]">
        <FileIcon size={13} className="shrink-0 text-fg-3" /><span className="min-w-0 truncate">{file.name}</span>
        <span className="shrink-0 text-[11px] text-fg-3">{file.size >= 1024 * 1024 ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`}</span>
        <button type="button" aria-label={`移除 ${file.name}`} onClick={() => props.onRemoveFile?.(index)} className="grid size-5 place-items-center rounded-md hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"><X size={12} /></button>
      </span>)}
    </div>}
    <input ref={fileRef} hidden type="file" multiple onChange={(event) => { props.onPickImages(event.target.files); event.currentTarget.value = ''; }} />

    <div className={cn('@container flex items-center gap-1.5', hero ? 'mt-3' : 'mt-2')}>
      <Tip label="添加图片或文件，也可以直接粘贴、拖进来">
        <button type="button" aria-label="添加附件" onClick={() => fileRef.current?.click()}
          className="grid size-8 shrink-0 place-items-center rounded-[9px] text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
          {props.attachments.length ? <ImagePlus size={18} /> : <Paperclip size={18} />}
        </button>
      </Tip>
      {/* Narrow composers (split view, wide task panel): the tool row scrolls rather than pushing send out of view. */}
      {props.tools && <div onWheel={(event) => { if (!event.deltaX && event.deltaY) event.currentTarget.scrollLeft += event.deltaY; }}
        className="flex min-w-0 shrink items-center gap-1.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">{props.tools}</div>}

      {props.modes && <div role="radiogroup" aria-label="任务类型" className="flex shrink-0 gap-0.5 rounded-[10px] bg-sunken p-[3px] shadow-[inset_0_0_0_1px_var(--line)]">
        {props.modes.options.map(({ id, label, icon: Icon }) => {
          const on = props.modes!.value === id;
          return <button key={id} type="button" role="radio" aria-checked={on} aria-label={label} title={label} onClick={() => props.modes!.onChange(id)}
            className={cn('inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 text-[13px] transition-colors',
              on ? 'raised text-fg' : 'text-fg-2 hover:text-fg')}>
            {/* Labels give way to icons when the toolbar gets crowded. */}
            <Icon size={14} /><span className="hidden @[700px]:inline">{label}</span>
          </button>;
        })}
      </div>}

      {hint && <span role={screenReaderMode ? undefined : 'status'} aria-live={screenReaderMode ? undefined : 'polite'}
        aria-atomic={screenReaderMode ? undefined : 'true'} className={cn('ml-1.5 min-w-0 truncate text-[12.5px]', props.listening ? 'text-brand' : 'text-fg-3')}>{hint}</span>}
      <span className="flex-1" />

      <ExpertModeToggle apiBaseUrl={backend.apiBaseUrl} />
      <Menu>
        <MenuTrigger asChild disabled={!props.models.length}>
          <button type="button" aria-label={`选择模型，当前${current?.name ?? current?.id ?? '默认模型'}`} title="选择模型" className="inline-flex h-8 min-w-0 shrink items-center gap-1.5 rounded-[9px] px-2.5 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-50">
            <span className={cn('size-1.5 shrink-0 rounded-full', current ? 'bg-ok shadow-[0_0_8px_var(--ok)]' : 'bg-fg-3')} />
            <span className="max-w-[160px] truncate">{current?.name ?? current?.id ?? '默认模型'}</span>
            <ChevronDown size={13} />
          </button>
        </MenuTrigger>
        <MenuContent align="end" side="top">
          <MenuLabel>模型</MenuLabel>
          {props.models.map((item) => <MenuItem key={item.id} checked={item.id === props.model} hint={item.provider ?? ''} onSelect={() => props.onSelectModel(item.id)}>{item.name ?? item.id}</MenuItem>)}
          <MenuSeparator />
          <MenuItem onSelect={props.onManageModels}><SlidersHorizontal />管理模型与 API</MenuItem>
        </MenuContent>
      </Menu>

      {props.onAttachDrawing && <DrawingPad key={props.contextKey} onAttach={props.onAttachDrawing} />}
      {props.onEnhancePrompt && <Tip label="用当前模型改写草稿，结果仍可编辑；不会自动发送">
        <button type="button" aria-label="增强提示词" aria-busy={enhancing} disabled={!props.value.trim() || enhancing}
          onClick={() => void enhancePrompt()}
          className="grid size-8 shrink-0 place-items-center rounded-full text-fg-2 hover:bg-hover hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-40">
          <Sparkles size={16} />
        </button>
      </Tip>}

      <Tip label="查看输入区快捷键">
        <button ref={shortcutHelpButtonRef} type="button" aria-label="打开快捷键帮助" aria-haspopup="dialog"
          aria-expanded={shortcutHelpOpen} title="快捷键帮助" onClick={() => onShortcutHelpOpenChange(true)}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2 text-[11.5px] text-fg-2 hover:bg-hover hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
          <Keyboard size={15} /><span>快捷键</span>
        </button>
      </Tip>

      <Tip label={screenReaderMode ? '关闭屏幕阅读增强' : '开启屏幕阅读增强；播报运行状态和建议项，并保持建议焦点在输入框'}>
        <button type="button" aria-label={screenReaderMode ? '关闭屏幕阅读增强' : '开启屏幕阅读增强'}
          aria-pressed={screenReaderMode} title="屏幕阅读增强" onClick={toggleScreenReaderMode}
          className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2 text-[11.5px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand',
            screenReaderMode ? 'bg-brand-soft text-brand' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
          <Accessibility size={16} /><span>读屏</span>
        </button>
      </Tip>

      <Tip label={props.listening ? '停止语音输入' : '语音输入'}>
        <button type="button" aria-label={props.listening ? '停止语音输入' : '开始语音输入'} aria-pressed={props.listening} onClick={props.onToggleMic}
          className={cn('grid size-8 shrink-0 place-items-center rounded-full transition-colors',
            props.listening ? 'bg-brand text-on-primary' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
          <Mic size={17} />
        </button>
      </Tip>
      <button type="submit" aria-label="发送消息" disabled={!canSend}
        onMouseDown={(event) => event.preventDefault()}
        className="primary-fill grid size-9 shrink-0 place-items-center rounded-full transition-[filter,opacity] hover:brightness-110 disabled:opacity-30">
        <ArrowUp size={17} strokeWidth={2.2} />
      </button>
    </div>
    {previewIndex !== null && props.attachments[previewIndex] && <div role="dialog" aria-modal="true" aria-label={`图片预览 ${previewIndex + 1} / ${props.attachments.length}`}
      onClick={(event) => { if (event.target === event.currentTarget) closeAttachmentPreview(); }}
      className="fixed inset-0 z-[100] grid place-items-center bg-black/80 p-5 backdrop-blur-sm">
      <button ref={previewCloseRef} type="button" aria-label="关闭图片预览" onClick={closeAttachmentPreview}
        className="absolute top-4 right-4 grid size-10 place-items-center rounded-full bg-black/50 text-white hover:bg-black/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"><X size={21} /></button>
      {props.attachments.length > 1 && <button type="button" aria-label="上一张图片" onClick={() => setPreviewIndex((index) => index === null ? null : (index - 1 + props.attachments.length) % props.attachments.length)}
        className="absolute left-4 grid size-11 place-items-center rounded-full bg-black/50 text-white hover:bg-black/70"><ArrowLeft size={22} /></button>}
      <img src={props.attachments[previewIndex]} alt={`待发送图片 ${previewIndex + 1}`} className="max-h-[88vh] max-w-[90vw] rounded-xl object-contain shadow-2xl" />
      {props.attachments.length > 1 && <button type="button" aria-label="下一张图片" onClick={() => setPreviewIndex((index) => index === null ? null : (index + 1) % props.attachments.length)}
        className="absolute right-4 grid size-11 place-items-center rounded-full bg-black/50 text-white hover:bg-black/70"><ArrowRight size={22} /></button>}
      <span className="absolute bottom-4 rounded-full bg-black/50 px-3 py-1 text-[12px] text-white">{previewIndex + 1} / {props.attachments.length}</span>
    </div>}
    <Dialog open={shellConfirmation !== null} onOpenChange={(open) => { if (!open) setShellConfirmation(null); }} label="确认在终端运行命令"
      className="w-[min(520px,calc(100vw-32px))] bg-panel p-5 shadow-xl">
      <h2 className="m-0 text-[16px] font-semibold text-fg">在终端运行这条命令？</h2>
      <p className="mb-3 mt-1.5 text-[13px] text-fg-2">确认后会在当前会话工作目录的终端执行，不会发送给 Atlas。</p>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-sunken p-3 text-[12.5px] text-fg">{shellConfirmation}</pre>
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={() => setShellConfirmation(null)} className="rounded-lg px-3 py-2 text-[13px] text-fg-2 hover:bg-hover">取消</button>
        <button type="button" onClick={() => { setShellConfirmation(null); submit(undefined, true); }} className="rounded-lg bg-brand px-3 py-2 text-[13px] font-medium text-white hover:brightness-110">运行命令</button>
      </div>
    </Dialog>
    <Dialog open={shortcutHelpOpen} onOpenChange={onShortcutHelpOpenChange} label="快捷键帮助"
      className="max-h-[82vh] w-[min(560px,92vw)] overflow-auto bg-panel p-4 shadow-xl">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="m-0 text-[15px] font-semibold text-heading">输入区快捷键</h2>
        <span className="flex-1" />
        <button ref={shortcutHelpCloseRef} type="button" aria-label="关闭快捷键帮助" onClick={() => onShortcutHelpOpenChange(false)}
          className="grid size-8 place-items-center rounded-lg hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"><X size={16} /></button>
      </div>
      <p className="mb-3 text-[12.5px] leading-relaxed text-fg-3">按 Tab 聚焦“快捷键帮助”并按 Enter 或空格打开；在此弹层中按 Escape 关闭。</p>
      <dl className="m-0 grid grid-cols-[130px_minmax(0,1fr)] gap-x-3 text-[12.5px]">
        {shortcutRows.map(({ keys, description }) => <div key={keys} className="contents">
          <dt className="border-t border-line py-2 font-mono text-fg"><kbd>{keys}</kbd></dt>
          <dd className="m-0 border-t border-line py-2 leading-relaxed text-fg-2">{description}</dd>
        </div>)}
      </dl>
    </Dialog>
  </form>;
}
