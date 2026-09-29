import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { ArrowUp, Check, ChevronDown, Code2, Film, ImagePlus, Image as ImageIcon, MessageCircle, Mic, Paperclip, Repeat, Search, SlidersHorizontal, X } from 'lucide-react';
import type { ModelInfo } from '@atlas/backend-adapter';

type Intent = { label: string; icon: typeof Code2; note?: string };

const INTENTS: Array<[RegExp, Intent]> = [
  [/视频|短片|剪辑|动画|video/i, { label: '视频', icon: Film, note: '视频生成尚未接入，会先按对话处理' }],
  [/画|生图|图片|插画|海报|头像|logo|配图|image/i, { label: '生图', icon: ImageIcon, note: '图像生成尚未接入，会先按对话处理' }],
  [/每天|每周|每月|定时|提醒我|每隔|自动(执行|运行)|cron/i, { label: '自动化', icon: Repeat, note: '也可以在「自动化」里建成定时任务' }],
  [/代码|bug|报错|函数|接口|重构|编译|测试用例|仓库|git|python|typescript|javascript|sql|\.tsx?\b|\.py\b/i, { label: '代码', icon: Code2 }],
  [/搜索|调研|查一下|资料|对比|最新|新闻|research/i, { label: '调研', icon: Search }],
];

export function guessIntent(text: string): Intent | null {
  if (text.trim().length < 2) return null;
  return INTENTS.find(([pattern]) => pattern.test(text))?.[1] ?? { label: '日常', icon: MessageCircle };
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
}

export default function Composer(props: ComposerProps) {
  const [modelOpen, setModelOpen] = useState(false);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const intent = guessIntent(props.value);
  const current = props.models.find((item) => item.id === props.model);
  const canSend = Boolean(props.value.trim() || props.attachments.length);

  useLayoutEffect(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [props.value]);
  useEffect(() => { if (props.autoFocus) textRef.current?.focus(); }, [props.autoFocus]);
  useEffect(() => {
    if (!modelOpen) return;
    const close = (event: MouseEvent) => { if (!menuRef.current?.contains(event.target as Node)) setModelOpen(false); };
    const esc = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') setModelOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
  }, [modelOpen]);

  const submit = (event?: FormEvent) => { event?.preventDefault(); if (canSend) props.onSubmit(); };
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); }
  };
  const IntentIcon = intent?.icon;
  const hint = props.listening ? '正在听你说…' : intent?.note ?? props.status;

  return <form className="composer" onSubmit={submit}>
    <textarea ref={textRef} value={props.value} rows={1} placeholder={props.placeholder} aria-label="消息内容"
      onChange={(event) => props.onChange(event.target.value)} onKeyDown={onKey}
      onPaste={(event) => { if (event.clipboardData.files.length) { event.preventDefault(); props.onPickImages(event.clipboardData.files); } }} />
    {props.attachments.length > 0 && <div className="attach" aria-label="待发送图片">
      {props.attachments.map((image, index) => <div key={`${index}-${image.length}`}>
        <img src={image} alt={`待发送图片 ${index + 1}`} />
        <button type="button" aria-label="移除图片" onClick={() => props.onRemoveAttachment(index)}><X size={12} /></button>
      </div>)}
    </div>}
    <input ref={fileRef} hidden type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={(event) => { props.onPickImages(event.target.files); event.currentTarget.value = ''; }} />
    <div className="crow">
      <button type="button" className="iconbtn" aria-label="添加图片" title="添加图片（也可以直接粘贴）" onClick={() => fileRef.current?.click()}>{props.attachments.length ? <ImagePlus size={18} /> : <Paperclip size={18} />}</button>
      {intent && IntentIcon && <span className="pill intent guessed" title="根据你的描述推测的任务类型"><IntentIcon size={14} /><span className="lbl">{intent.label}</span></span>}
      <div style={{ position: 'relative', minWidth: 0 }} ref={menuRef}>
        <button type="button" className="pill model" aria-haspopup="menu" aria-expanded={modelOpen} disabled={!props.models.length} title="选择模型" onClick={() => setModelOpen((open) => !open)}>
          <i className={`dot${current ? '' : ' none'}`} /><span className="lbl">{current?.name ?? current?.id ?? '默认模型'}</span><ChevronDown size={13} />
        </button>
        {modelOpen && <div className="menu up" role="menu">
          <h6>模型</h6>
          {props.models.map((item) => <button type="button" role="menuitemradio" aria-checked={item.id === props.model} key={item.id} onClick={() => { props.onSelectModel(item.id); setModelOpen(false); }}>
            <span>{item.name ?? item.id}</span>{item.id === props.model ? <Check size={15} className="check" /> : <small>{item.provider ?? ''}</small>}
          </button>)}
          <hr />
          <button type="button" onClick={() => { setModelOpen(false); props.onManageModels(); }}><SlidersHorizontal size={15} />管理模型与 API</button>
        </div>}
      </div>
      <span className={`hint${props.listening ? ' live' : ''}`}>{hint}</span>
      <span className="grow" />
      <button type="button" className="mic" aria-label={props.listening ? '停止语音输入' : '开始语音输入'} aria-pressed={props.listening} title="语音输入" onClick={props.onToggleMic}><Mic size={17} /></button>
      <button type="submit" className="send" aria-label="发送消息" disabled={!canSend}><ArrowUp size={18} /></button>
    </div>
  </form>;
}
