import { useEffect, useLayoutEffect, useRef, useState, type DragEvent, type FormEvent, type KeyboardEvent, type ReactNode } from 'react';
import { ArrowUp, ChevronDown, Code2, Film, ImagePlus, Image as ImageIcon, MessageCircle, Mic, Paperclip, Repeat, Search, SlidersHorizontal, X, type LucideIcon } from 'lucide-react';
import type { ModelInfo } from '@atlas/backend-adapter';
import { cn } from '../ui/cn';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from '../ui/Menu';
import { Tip } from '../ui/Tooltip';

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

export interface ComposerMode { id: string; label: string; icon: LucideIcon }

/** An entry in the `/` menu. `takesArgument` commands receive the text typed after the command name. */
export interface SlashCommand { id: string; label: string; hint?: string; takesArgument?: boolean; run: (argument: string) => void }

/** Commands matching a `/query` draft; only while the draft is a single command word (plus an argument for argument commands). */
export function matchCommands(value: string, commands: SlashCommand[]): SlashCommand[] {
  const match = /^\/(\S*)(\s[\s\S]*)?$/.exec(value);
  if (!match) return [];
  const [, word, rest] = match;
  if (rest !== undefined) return commands.filter((command) => command.takesArgument && command.label === `/${word}`);
  const query = word.toLowerCase();
  return commands.filter((command) => command.label.slice(1).toLowerCase().includes(query)).slice(0, 8);
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
  /** Content shown above the text area, e.g. the live run status. */
  header?: ReactNode;
  commands?: SlashCommand[];
}

export default function Composer(props: ComposerProps) {
  const hero = props.variant === 'hero';
  const textRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const intent = guessIntent(props.value);
  const current = props.models.find((item) => item.id === props.model);
  const canSend = Boolean(props.value.trim() || props.attachments.length);
  const hint = props.listening ? '正在听你说…' : intent?.note ?? props.status;

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
  const [dragging, setDragging] = useState(false);
  const matches = matchCommands(props.value, props.commands ?? []);
  useEffect(() => setCursor(0), [matches.length]);

  const runCommand = (command: SlashCommand) => {
    const argument = props.value.replace(/^\/\S*\s?/, '');
    props.onChange('');
    command.run(argument);
  };
  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (matches.length) { runCommand(matches[Math.min(cursor, matches.length - 1)]); return; }
    if (canSend) props.onSubmit();
  };
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (matches.length && !event.nativeEvent.isComposing) {
      if (event.key === 'ArrowDown') { event.preventDefault(); setCursor((value) => (value + 1) % matches.length); return; }
      if (event.key === 'ArrowUp') { event.preventDefault(); setCursor((value) => (value - 1 + matches.length) % matches.length); return; }
      if (event.key === 'Tab') { event.preventDefault(); props.onChange(`${matches[cursor].label}${matches[cursor].takesArgument ? ' ' : ''}`); return; }
      if (event.key === 'Escape') { event.preventDefault(); props.onChange(''); return; }
    }
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); }
  };
  const hasFiles = (event: DragEvent<HTMLFormElement>) => Array.from(event.dataTransfer.types).includes('Files');

  return <form onSubmit={submit}
    onDragOver={(event) => { if (!hasFiles(event)) return; event.preventDefault(); setDragging(true); }}
    onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
    onDrop={(event) => { if (!hasFiles(event)) return; event.preventDefault(); setDragging(false); props.onPickImages(event.dataTransfer.files); }}
    className={cn('raised relative transition-shadow focus-within:shadow-[var(--shadow-raised),0_0_0_4px_var(--brand-soft)]',
      hero ? 'rounded-[20px] px-5 pt-[18px] pb-3' : 'rounded-2xl px-4 pt-3 pb-2.5',
      dragging && 'shadow-[var(--shadow-raised),0_0_0_2px_var(--brand)]')}>
    {matches.length > 0 && <div role="listbox" aria-label="命令" className="pop anim-pop absolute right-0 bottom-[calc(100%+8px)] left-0 z-30 max-h-[300px] overflow-auto rounded-xl p-1.5">
      {matches.map((command, index) => <button key={command.id} type="button" role="option" aria-selected={index === cursor}
        onMouseMove={() => setCursor(index)} onMouseDown={(event) => { event.preventDefault(); runCommand(command); }}
        className={cn('flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-[13.5px]', index === cursor && 'bg-selected')}>
        <span className="shrink-0 font-mono text-[13px] text-fg">{command.label}</span>
        {command.hint && <span className="min-w-0 truncate text-[12.5px] text-fg-3">{command.hint}</span>}
      </button>)}
    </div>}
    {dragging && <div className="pointer-events-none absolute inset-0 z-20 grid place-items-center rounded-[inherit] bg-brand-soft text-[13.5px] font-medium text-fg">松开添加图片</div>}
    {props.header}
    <textarea ref={textRef} value={props.value} rows={1} placeholder={props.placeholder} aria-label="消息内容"
      onChange={(event) => props.onChange(event.target.value)} onKeyDown={onKey}
      onPaste={(event) => { if (event.clipboardData.files.length) { event.preventDefault(); props.onPickImages(event.clipboardData.files); } }}
      className={cn('block w-full resize-none border-0 bg-transparent p-0 text-fg outline-none placeholder:text-fg-3',
        hero ? 'min-h-[60px] text-[16px] leading-[1.65]' : 'min-h-[26px] text-[15px] leading-[1.6]')} />
    {props.attachments.length > 0 && <div className="mt-2.5 flex flex-wrap gap-2" aria-label="待发送图片">
      {props.attachments.map((image, index) => <div key={`${index}-${image.length}`} className="relative size-14">
        <img src={image} alt={`待发送图片 ${index + 1}`} className="size-full rounded-[10px] object-cover shadow-[0_0_0_1px_var(--line)]" />
        <button type="button" aria-label="移除图片" onClick={() => props.onRemoveAttachment(index)}
          className="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full bg-fg text-bg"><X size={12} /></button>
      </div>)}
    </div>}
    <input ref={fileRef} hidden type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={(event) => { props.onPickImages(event.target.files); event.currentTarget.value = ''; }} />

    <div className={cn('flex items-center gap-1.5', hero ? 'mt-3' : 'mt-2')}>
      <Tip label="添加图片，也可以直接粘贴">
        <button type="button" aria-label="添加图片" onClick={() => fileRef.current?.click()}
          className="grid size-8 place-items-center rounded-[9px] text-fg-3 hover:bg-hover hover:text-fg">
          {props.attachments.length ? <ImagePlus size={18} /> : <Paperclip size={18} />}
        </button>
      </Tip>

      {props.modes && <div role="radiogroup" aria-label="任务类型" className="flex gap-0.5 rounded-[10px] bg-sunken p-[3px] shadow-[inset_0_0_0_1px_var(--line)]">
        {props.modes.options.map(({ id, label, icon: Icon }) => {
          const on = props.modes!.value === id;
          return <button key={id} type="button" role="radio" aria-checked={on} onClick={() => props.modes!.onChange(id)}
            className={cn('inline-flex h-7 items-center gap-1.5 rounded-lg px-3 text-[13px] transition-colors',
              on ? 'raised text-fg' : 'text-fg-2 hover:text-fg')}>
            <Icon size={14} />{label}
          </button>;
        })}
      </div>}

      {hint && <span className={cn('ml-1.5 min-w-0 truncate text-[12.5px]', props.listening ? 'text-brand' : 'text-fg-3')}>{hint}</span>}
      <span className="flex-1" />

      <Menu>
        <MenuTrigger asChild disabled={!props.models.length}>
          <button type="button" title="选择模型" className="inline-flex h-8 min-w-0 items-center gap-1.5 rounded-[9px] px-2.5 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-50">
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

      <Tip label={props.listening ? '停止语音输入' : '语音输入'}>
        <button type="button" aria-label={props.listening ? '停止语音输入' : '开始语音输入'} aria-pressed={props.listening} onClick={props.onToggleMic}
          className={cn('grid size-8 place-items-center rounded-full transition-colors',
            props.listening ? 'bg-brand text-on-primary' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
          <Mic size={17} />
        </button>
      </Tip>
      <button type="submit" aria-label="发送消息" disabled={!canSend}
        className="primary-fill grid size-9 place-items-center rounded-full transition-[filter,opacity] hover:brightness-110 disabled:opacity-30">
        <ArrowUp size={17} strokeWidth={2.2} />
      </button>
    </div>
  </form>;
}
